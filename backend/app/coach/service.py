from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import CoachReport, ReportType, SourceType
from app.activities.repository import ActivityRepository
from app.analytics.metrics import format_duration, format_pace
from app.coach.domain import (
    CALCULATOR_VERSION,
    RULE_VERSION,
    CoachFacts,
    RunClassification,
    RunFact,
    WorkoutRecommendation,
    calculate_facts,
    recommend_next,
    safe_weekly_targets,
)
from app.coach.models import PlannedWorkout, PlanStatus, TrainingGoal, TrainingPlan
from app.coach.provider import ProviderExecutor, allowlisted_payload
from app.coach.repository import CoachRepository
from app.coach.schemas import CoachError, CoachResponse, PlanResponse, PlanWorkout, WeekResponse
from app.users.models import User
from app.users.repository import UserRepository


class CoachService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_executor: ProviderExecutor,
    ) -> None:
        self.session_factory = session_factory
        self.provider_executor = provider_executor

    async def set_external_processing(self, telegram_user_id: int, *, enabled: bool) -> bool:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            user.external_processing_enabled = enabled
            return user.external_processing_enabled

    async def week(self, telegram_user_id: int, moment: datetime | None = None) -> WeekResponse:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            facts, _sources = await self._facts(session, user, moment or datetime.now(UTC))
        return WeekResponse(facts=facts, message=format_week(facts))

    async def next_workout(
        self, telegram_user_id: int, moment: datetime | None = None
    ) -> CoachResponse:
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            facts, sources = await self._facts(session, user, now)
            recommendation = recommend_next(facts)
            template = format_recommendation(recommendation)
            report = CoachReport(
                user_id=user.id,
                report_type=ReportType.NEXT_WORKOUT,
                facts_json=facts.as_json(),
                rule_result_json=recommendation.as_json(),
                message_private=template,
                provider="NONE",
            )
            CoachRepository(session).add_report(report)
            await session.flush()
            report_id = report.id
            external_allowed = user.external_processing_enabled and SourceType.STRAVA not in sources

        message = template
        provider_name = "NONE"
        if external_allowed:
            result = await self.provider_executor.execute(
                allowlisted_payload(facts.as_json(), recommendation.as_json())
            )
            if result.message is not None:
                message = result.message
                provider_name = result.provider.value
                async with self.session_factory.begin() as session:
                    stored = await CoachRepository(session).report(report_id)
                    if stored is not None:
                        stored.message_private = result.message
                        stored.provider = result.provider.value
                        stored.provider_model = result.model
                        stored.prompt_hash = result.prompt_hash
        return CoachResponse(report_id, facts, recommendation, message, provider_name)

    async def create_plan(
        self,
        telegram_user_id: int,
        goal: TrainingGoal,
        *,
        custom_goal: str | None = None,
        moment: datetime | None = None,
    ) -> PlanResponse:
        now = moment or datetime.now(UTC)
        if goal == TrainingGoal.CUSTOM and not (custom_goal or "").strip():
            raise CoachError("Для CUSTOM укажите цель после названия.")
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            facts, _sources = await self._facts(session, user, now)
            starts_on = now.astimezone(ZoneInfo(user.timezone)).date()
            repository = CoachRepository(session)
            if await repository.plan_for_start(user.id, starts_on) is not None:
                raise CoachError("План на эту дату уже создан.")
            targets = safe_weekly_targets(facts.baseline_weekly_distance_m)
            plan = TrainingPlan(
                user_id=user.id,
                goal=goal,
                custom_goal=(custom_goal or "").strip() or None,
                starts_on=starts_on,
                weeks=len(targets),
                baseline_weekly_distance_m=facts.baseline_weekly_distance_m,
                calculator_version=CALCULATOR_VERSION,
                rule_version=RULE_VERSION,
                status=PlanStatus.DRAFT,
            )
            repository.add_plan(plan)
            await session.flush()
            workouts: list[PlanWorkout] = []
            for index, weekly_target in enumerate(targets, start=1):
                distance = max(3_000, weekly_target * 30 // 100)
                pace = facts.average_pace_30d
                recommendation = WorkoutRecommendation(
                    workout_type=RunClassification.EASY,
                    distance_m=distance,
                    duration_sec=max(1_800, distance * ((pace or 360) + 35) // 1000),
                    pace_min_sec_per_km=None if pace is None else pace + 15,
                    pace_max_sec_per_km=None if pace is None else pace + 50,
                    reason=(
                        f"Неделя {index}: целевой объем {weekly_target / 1000:.1f} км "
                        "без роста >10%."
                    ),
                    risk_flags=facts.risk_flags,
                )
                scheduled = starts_on + timedelta(days=(index - 1) * 7 + 2)
                repository.add_workout(
                    PlannedWorkout(
                        plan_id=plan.id,
                        week_index=index,
                        scheduled_for=scheduled,
                        workout_type=recommendation.workout_type.value,
                        distance_m=recommendation.distance_m,
                        duration_sec=recommendation.duration_sec,
                        pace_min_sec_per_km=recommendation.pace_min_sec_per_km,
                        pace_max_sec_per_km=recommendation.pace_max_sec_per_km,
                        reason=recommendation.reason,
                        risk_flags=",".join(recommendation.risk_flags),
                        created_at=now,
                    )
                )
                workouts.append(PlanWorkout(index, scheduled, recommendation))
            message = format_plan(goal, facts.baseline_weekly_distance_m, tuple(workouts))
            repository.add_report(
                CoachReport(
                    user_id=user.id,
                    report_type=ReportType.PLAN,
                    facts_json=facts.as_json(),
                    rule_result_json={
                        "rule_version": RULE_VERSION,
                        "goal": goal.value,
                        "weekly_targets_m": list(targets),
                    },
                    message_private=message,
                    provider="NONE",
                )
            )
            return PlanResponse(
                plan.id, goal, facts.baseline_weekly_distance_m, tuple(workouts), message
            )

    async def _facts(
        self, session: AsyncSession, user: User, moment: datetime
    ) -> tuple[CoachFacts, set[SourceType]]:
        history = await ActivityRepository(session).run_history(user.id, started_before=moment)
        facts = calculate_facts(
            tuple(
                RunFact(
                    item.started_at
                    if item.started_at.tzinfo is not None
                    else item.started_at.replace(tzinfo=UTC),
                    item.distance_m,
                    item.elapsed_time_sec,
                    item.avg_pace_sec_per_km,
                    item.title,
                )
                for item in history
            ),
            as_of=moment,
            timezone=user.timezone,
        )
        return facts, {item.source_type for item in history}

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise CoachError("Сначала выполните /start.")
        return found[0]


def format_recommendation(recommendation: WorkoutRecommendation) -> str:
    pace = "по самочувствию"
    if recommendation.pace_min_sec_per_km is not None and recommendation.pace_max_sec_per_km:
        pace = (
            f"{format_pace(recommendation.pace_min_sec_per_km)}–"
            f"{format_pace(recommendation.pace_max_sec_per_km)}/км"
        )
    flags = ", ".join(recommendation.risk_flags) or "нет"
    return (
        "<b>Следующая тренировка</b>\n\n"
        f"Тип: {recommendation.workout_type.value}\n"
        f"Дистанция: <b>{recommendation.distance_m / 1000:.2f} км</b>\n"
        f"Длительность: {format_duration(recommendation.duration_sec)}\n"
        f"Темп: {pace}\nПричина: {recommendation.reason}\nРиски: {flags}"
    )


def format_week(facts: CoachFacts) -> str:
    pace = (
        "нет данных"
        if facts.average_pace_30d is None
        else f"{format_pace(facts.average_pace_30d)}/км"
    )
    risks = ", ".join(facts.risk_flags) or "нет"
    return (
        "<b>Текущая неделя</b>\n\n"
        f"Пробежек: {facts.week.run_count}\n"
        f"Дистанция: <b>{facts.week.distance_m / 1000:.2f} км</b>\n"
        f"Longest 7d/30d/all: {facts.last_7d.longest_run_m / 1000:.2f}/"
        f"{facts.last_30d.longest_run_m / 1000:.2f}/{facts.all_time_longest_m / 1000:.2f} км\n"
        f"Средний темп 30d: {pace}\nРиски: {risks}"
    )


def format_plan(goal: TrainingGoal, baseline_m: int, workouts: tuple[PlanWorkout, ...]) -> str:
    lines = [f"<b>План {goal.value}</b>", f"Baseline: {baseline_m / 1000:.1f} км/нед."]
    lines.extend(
        f"{item.week_index}. {item.recommendation.workout_type.value} "
        f"{item.recommendation.distance_m / 1000:.1f} км — {item.recommendation.reason}"
        for item in workouts
    )
    return "\n".join(lines)
