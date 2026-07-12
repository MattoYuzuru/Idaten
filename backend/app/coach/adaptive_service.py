import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import CoachReport, ReportType
from app.activities.repository import ActivityRepository
from app.activities.schemas import RunHistoryItem
from app.coach.candidates import RecommendedRunKind, RunDecision
from app.coach.engine import AdaptiveRecommendation, calculate_adaptive_recommendation
from app.coach.facts import RunFact
from app.coach.lifecycle import RecommendationLifecycle
from app.coach.models import NextRunRecommendation, RecommendationStatus
from app.coach.next_messages import format_prescription
from app.coach.prescription import SafeBounds
from app.coach.repository import CoachRepository
from app.coach.schemas import (
    CoachError,
    NextFlowResult,
    NextFlowState,
    RecommendationDto,
)
from app.goals.repository import GoalRepository
from app.goals.service import GoalService
from app.readiness.domain import CheckInInputSource, CheckInPhase, CheckInStatus
from app.readiness.repository import ReadinessRepository
from app.readiness.schemas import ReadinessDraft, ReadinessValues
from app.readiness.service import ReadinessService
from app.users.models import User
from app.users.repository import UserRepository

if TYPE_CHECKING:
    from app.health_connect.service import HealthConnectService


class NextRunService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        sleep_service: "HealthConnectService",
    ) -> None:
        self.session_factory = session_factory
        self.sleep_service = sleep_service
        self.goals = GoalService(session_factory)
        self.readiness = ReadinessService(session_factory)
        self.lifecycle = RecommendationLifecycle()

    async def state(
        self, telegram_user_id: int, *, moment: datetime | None = None
    ) -> NextFlowResult:
        now = moment or datetime.now(UTC)
        achievement = await self.goals.achievement(telegram_user_id, moment=now)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            goal_model = await GoalRepository(session).active(user.id)
            if goal_model is None:
                return NextFlowResult(NextFlowState.NEED_GOAL)
            goal = GoalService._dto(goal_model)
            if achievement is not None:
                return NextFlowResult(
                    NextFlowState.GOAL_ACHIEVEMENT_CONFIRMATION,
                    goal=goal,
                    achievement=achievement,
                )
            current = await CoachRepository(session).current_recommendation(user.id)
            if current is not None and self._utc(current.valid_until) <= now:
                current.status = RecommendationStatus.EXPIRED
                current = None
            if current is None:
                draft = await ReadinessRepository(session).active_draft(
                    user.id, CheckInPhase.POST_RUN
                )
                if draft is not None and self._utc(draft.expires_at) > now:
                    return NextFlowResult(
                        NextFlowState.EDIT_CHECK_IN,
                        goal=goal,
                        check_in=ReadinessService._dto(draft),
                    )
                return NextFlowResult(NextFlowState.NEED_CHECK_IN_METHOD, goal=goal)
            recommendation = await self._recommendation_dto(session, current)
            if current.status == RecommendationStatus.CONFIRMED:
                return NextFlowResult(
                    NextFlowState.SHOW_CONFIRMED,
                    goal=goal,
                    recommendation=recommendation,
                )
            if now < self._utc(current.not_before):
                return NextFlowResult(
                    NextFlowState.SHOW_PROVISIONAL,
                    goal=goal,
                    recommendation=recommendation,
                )
            draft = await ReadinessRepository(session).active_draft(user.id, CheckInPhase.PRE_RUN)
            if draft is not None and self._utc(draft.expires_at) > now:
                return NextFlowResult(
                    NextFlowState.EDIT_CHECK_IN,
                    goal=goal,
                    check_in=ReadinessService._dto(draft),
                    recommendation=recommendation,
                )
            return NextFlowResult(
                NextFlowState.NEED_PRE_RUN_CHECK_IN,
                goal=goal,
                recommendation=recommendation,
            )

    async def expire(self, telegram_user_id: int, *, moment: datetime | None = None) -> bool:
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            return await self.lifecycle.expire_current(session, user.id, moment=now)

    async def start_check_in(
        self,
        telegram_user_id: int,
        phase: CheckInPhase,
        *,
        source: CheckInInputSource = CheckInInputSource.MANUAL,
        prefill: ReadinessValues | None = None,
        moment: datetime | None = None,
    ) -> ReadinessDraft:
        linked_activity_id: uuid.UUID | None = None
        user_id: uuid.UUID | None = None
        if phase == CheckInPhase.POST_RUN:
            async with self.session_factory() as session:
                user = await self._require_user(session, telegram_user_id)
                user_id = user.id
                history = await ActivityRepository(session).run_history(
                    user.id, started_before=moment or datetime.now(UTC)
                )
                if history:
                    linked_activity_id = history[-1].activity_id
        if user_id is None:
            async with self.session_factory() as session:
                user_id = (await self._require_user(session, telegram_user_id)).id
        selected_source = source
        selected_prefill = prefill
        if selected_prefill is None:
            sleep = await self.sleep_service.sleep_prefill_for_user(user_id, moment=moment)
            if sleep is not None:
                selected_prefill = ReadinessValues(
                    sleep_quality=sleep.sleep_quality,
                    sleep_duration_sec=sleep.duration_sec,
                    sleep_ended_at=sleep.ended_at,
                    sleep_summary_id=sleep.summary_id,
                )
                selected_source = CheckInInputSource.HEALTH_CONNECT
        return await self.readiness.start_draft(
            telegram_user_id,
            phase,
            source=selected_source,
            linked_activity_id=linked_activity_id,
            prefill=selected_prefill,
            moment=moment,
        )

    async def revision_draft(
        self,
        telegram_user_id: int,
        recommendation_id: uuid.UUID,
        *,
        moment: datetime | None = None,
    ) -> ReadinessDraft:
        now = moment or datetime.now(UTC)
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            recommendation = await CoachRepository(session).recommendation(recommendation_id)
            if recommendation is None or recommendation.user_id != user.id:
                raise CoachError("Recommendation не найдена.")
            if recommendation.status not in {
                RecommendationStatus.PROVISIONAL,
                RecommendationStatus.CONFIRMED,
            }:
                raise CoachError("Recommendation уже закрыта.")
            source = await ReadinessRepository(session).by_id(recommendation.check_in_id)
            if source is None:
                raise CoachError("Source check-in не найден.")
            values = ReadinessService._values(source)
            input_source = source.source
            phase = (
                CheckInPhase.PRE_RUN
                if recommendation.status == RecommendationStatus.PROVISIONAL
                and now >= self._utc(recommendation.not_before)
                else CheckInPhase.POST_RUN
            )
        return await self.start_check_in(
            telegram_user_id,
            phase,
            source=input_source,
            prefill=values,
            moment=now,
        )

    async def recalculate(
        self,
        telegram_user_id: int,
        recommendation_id: uuid.UUID,
        *,
        idempotency_key: str,
        moment: datetime | None = None,
    ) -> RecommendationDto:
        now = moment or datetime.now(UTC)
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = CoachRepository(session)
            repeated = await repository.recommendation_by_idempotency(user.id, idempotency_key)
            if repeated is not None:
                return await self._recommendation_dto(session, repeated)
            current = await repository.recommendation(recommendation_id)
            if (
                current is None
                or current.user_id != user.id
                or current.status != RecommendationStatus.PROVISIONAL
            ):
                raise CoachError("Provisional recommendation не найдена.")
            if now >= self._utc(current.not_before):
                raise CoachError("Перед стартом сначала подтвердите новое самочувствие.")
            active_draft = await ReadinessRepository(session).active_draft(
                user.id, CheckInPhase.POST_RUN
            )
            if active_draft is not None:
                raise CoachError("Сначала завершите или отмените текущий check-in.")
        draft = await self.revision_draft(telegram_user_id, recommendation_id, moment=now)
        return await self.confirm_and_recommend(
            telegram_user_id,
            draft.check_in_id,
            idempotency_key=idempotency_key,
            moment=now,
        )

    async def confirm_and_recommend(
        self,
        telegram_user_id: int,
        check_in_id: uuid.UUID,
        *,
        idempotency_key: str | None = None,
        moment: datetime | None = None,
    ) -> RecommendationDto:
        now = moment or datetime.now(UTC)
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
            raise CoachError("Некорректный idempotency key.")
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = CoachRepository(session)
            if idempotency_key is not None:
                repeated = await repository.recommendation_by_idempotency(user.id, idempotency_key)
                if repeated is not None:
                    return await self._recommendation_dto(session, repeated)
            check_in = await ReadinessRepository(session).by_id(check_in_id, for_update=True)
            if check_in is None or check_in.user_id != user.id:
                raise CoachError("Check-in не найден.")
            repeated = await repository.recommendation_by_check_in(check_in.id)
            if repeated is not None:
                return await self._recommendation_dto(session, repeated)
            if check_in.status != CheckInStatus.DRAFT:
                raise CoachError("Check-in уже закрыт.")
            if self._utc(check_in.expires_at) <= now:
                check_in.status = CheckInStatus.EXPIRED
                raise CoachError("Check-in истёк.")
            confirmed = ReadinessService.confirm_locked(check_in, now)
            goal = await GoalRepository(session).active(user.id, for_update=True)
            if goal is None:
                raise CoachError("Сначала выберите беговую цель.")
            history = await ActivityRepository(session).run_history(user.id, started_before=now)
            runs = tuple(self._run_fact(item) for item in history)
            calculation = calculate_adaptive_recommendation(
                runs,
                goal.type,
                confirmed.values,
                as_of=now,
                timezone=user.timezone,
            )
            current = await repository.current_recommendation(user.id, for_update=True)
            if check_in.phase == CheckInPhase.PRE_RUN:
                if current is None or current.status != RecommendationStatus.PROVISIONAL:
                    raise CoachError("Provisional recommendation не найдена.")
                calculation = await self._bounded_pre_run(session, calculation, current)
            previous_id = None if current is None else current.id
            if current is not None:
                current.status = RecommendationStatus.SUPERSEDED
            report = self._report(user.id, calculation)
            repository.add_report(report)
            await session.flush()
            recommendation = NextRunRecommendation(
                user_id=user.id,
                goal_id=goal.id,
                source_activity_id=history[-1].activity_id if history else None,
                check_in_id=check_in.id,
                report_id=report.id,
                status=(
                    RecommendationStatus.CONFIRMED
                    if check_in.phase == CheckInPhase.PRE_RUN
                    else RecommendationStatus.PROVISIONAL
                ),
                recommended_for=calculation.prescription.recommended_for,
                not_before=calculation.prescription.not_before,
                valid_until=calculation.prescription.valid_until,
                supersedes_id=previous_id,
                inputs_fingerprint=calculation.inputs_fingerprint,
                idempotency_key=idempotency_key,
            )
            repository.add_recommendation(recommendation)
            await session.flush()
            return await self._recommendation_dto(session, recommendation)

    async def _bounded_pre_run(
        self,
        session: AsyncSession,
        calculation: AdaptiveRecommendation,
        provisional: NextRunRecommendation,
    ) -> AdaptiveRecommendation:
        report = await CoachRepository(session).report(provisional.report_id)
        if report is None:
            raise CoachError("Provisional report не найден.")
        raw = report.rule_result_json.get("prescription")
        if not isinstance(raw, dict):
            raise CoachError("Provisional bounds повреждены.")
        bounds = raw.get("safe_bounds")
        if not isinstance(bounds, dict) or calculation.prescription.decision == RunDecision.REST:
            return calculation
        maximum_duration = bounds.get("maximum_duration_sec")
        maximum_distance = bounds.get("maximum_distance_m")
        maximum_kind = bounds.get("maximum_kind")
        if not isinstance(maximum_duration, int) or not isinstance(maximum_kind, str):
            raise CoachError("Provisional bounds повреждены.")
        try:
            kind_cap = RecommendedRunKind(maximum_kind)
        except ValueError as error:
            raise CoachError("Provisional bounds повреждены.") from error
        prescription = calculation.prescription
        duration = prescription.duration_sec
        distance = prescription.distance_m
        if duration is not None:
            duration = min(duration, maximum_duration)
        if distance is not None and isinstance(maximum_distance, int):
            distance = min(distance, maximum_distance)
        kind = prescription.kind
        if kind is not None and self._kind_rank(kind) > self._kind_rank(kind_cap):
            kind = kind_cap
        safe = SafeBounds(
            prescription.safe_bounds.minimum_duration_sec
            if prescription.safe_bounds is not None
            else 0,
            maximum_duration,
            maximum_distance if isinstance(maximum_distance, int) else None,
            kind_cap,
        )
        bounded = replace(
            prescription,
            kind=kind,
            duration_sec=duration,
            distance_m=distance,
            safe_bounds=safe,
        )
        fingerprint = hashlib.sha256(
            f"{calculation.inputs_fingerprint}:{provisional.id}".encode()
        ).hexdigest()
        return replace(calculation, prescription=bounded, inputs_fingerprint=fingerprint)

    @staticmethod
    def _report(user_id: uuid.UUID, calculation: AdaptiveRecommendation) -> CoachReport:
        return CoachReport(
            user_id=user_id,
            report_type=ReportType.NEXT_WORKOUT,
            facts_json=calculation.facts_json(),
            rule_result_json=calculation.rule_result_json(),
            message_private=format_prescription(calculation.prescription),
            provider="NONE",
        )

    @staticmethod
    def _run_fact(item: RunHistoryItem) -> RunFact:
        started_at = (
            item.started_at if item.started_at.tzinfo else item.started_at.replace(tzinfo=UTC)
        )
        return RunFact(
            item.activity_id,
            started_at,
            item.distance_m,
            item.elapsed_time_sec,
            item.moving_time_sec,
            item.avg_pace_sec_per_km,
            item.avg_hr,
            item.max_hr,
            item.avg_cadence_spm,
            item.elevation_gain_m,
            item.source_type,
            item.title,
            item.session_rpe,
            item.start_time_known,
        )

    async def _recommendation_dto(
        self, session: AsyncSession, recommendation: NextRunRecommendation
    ) -> RecommendationDto:
        report = await CoachRepository(session).report(recommendation.report_id)
        if report is None:
            raise CoachError("Recommendation report не найден.")
        return RecommendationDto(
            recommendation.id,
            recommendation.status.value,
            recommendation.report_id,
            recommendation.check_in_id,
            recommendation.recommended_for,
            self._utc(recommendation.not_before),
            self._utc(recommendation.valid_until),
            report.message_private,
            recommendation.inputs_fingerprint,
        )

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise CoachError("Сначала выполните /start.")
        return found[0]

    @staticmethod
    def _kind_rank(kind: RecommendedRunKind) -> int:
        return {
            RecommendedRunKind.RECOVERY: 1,
            RecommendedRunKind.EASY: 2,
            RecommendedRunKind.STEADY: 3,
            RecommendedRunKind.LONG_RUN: 4,
            RecommendedRunKind.TEMPO: 5,
        }[kind]

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
