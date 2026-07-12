import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from aiogram.types import InlineKeyboardMarkup

from app.bot.next_handlers import _field_prompt, _parse_field
from app.bot.next_keyboards import goal_keyboard, preview_keyboard, recommendation_keyboard
from app.coach.candidates import RecommendedRunKind, RunDecision
from app.coach.next_messages import format_check_in, format_prescription
from app.coach.prescription import Prescription
from app.readiness.domain import CheckInInputSource, CheckInPhase, CheckInStatus
from app.readiness.schemas import ReadinessDraft, ReadinessError, ReadinessValues

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def draft(
    values: ReadinessValues | None = None,
    *,
    phase: CheckInPhase = CheckInPhase.POST_RUN,
    linked_activity_id: uuid.UUID | None = None,
) -> ReadinessDraft:
    return ReadinessDraft(
        check_in_id=uuid.UUID(int=1),
        phase=phase,
        status=CheckInStatus.DRAFT,
        source=CheckInInputSource.MANUAL,
        source_confidence=None,
        values=values or ReadinessValues(),
        linked_activity_id=linked_activity_id,
        pending_field=None,
        expires_at=NOW + timedelta(hours=24),
        confirmed_at=None,
        version=1,
        telegram_message_id=None,
    )


def callbacks(keyboard: InlineKeyboardMarkup) -> tuple[str, ...]:
    return tuple(
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    )


def test_goal_and_readiness_keyboards_use_safe_labels_and_bounded_callbacks() -> None:
    goals = goal_keyboard()
    goal_labels = tuple(button.text for row in goals.inline_keyboard for button in row)
    check_in = draft()
    field_keyboards = tuple(
        _field_prompt(check_in, field)[1]
        for field in (
            "overall_readiness",
            "general_fatigue",
            "pain_present",
            "pain_location",
            "sleep_quality",
            "available_time_sec",
        )
    )
    values = callbacks(goals) + callbacks(preview_keyboard(check_in))
    values += callbacks(recommendation_keyboard(uuid.UUID(int=2)))
    values += tuple(value for keyboard in field_keyboards for value in callbacks(keyboard))

    assert "Впервые 5 км" in goal_labels
    assert "Общая выносливость" in goal_labels
    assert all(len(value.encode()) <= 64 for value in values)
    assert all("колено" not in value and "бол" not in value for value in values)


def test_preview_edits_available_time_and_only_post_run_linked_rpe() -> None:
    linked = draft(linked_activity_id=uuid.UUID(int=3))
    pre_run = draft(phase=CheckInPhase.PRE_RUN)

    linked_callbacks = callbacks(preview_keyboard(linked))
    pre_run_callbacks = callbacks(preview_keyboard(pre_run))

    assert f"next:e:{linked.check_in_id.hex}:a" in linked_callbacks
    assert f"next:e:{linked.check_in_id.hex}:r" in linked_callbacks
    assert f"next:e:{pre_run.check_in_id.hex}:a" in pre_run_callbacks
    assert all(not value.endswith(":r") for value in pre_run_callbacks)


def test_check_in_preview_hides_pain_location_and_internal_formulas() -> None:
    rendered = format_check_in(
        draft(
            ReadinessValues(
                overall_readiness=4,
                general_fatigue=3,
                muscle_soreness=2,
                external_load=1,
                pain_present=True,
                pain_severity=3,
                pain_location="<private location>",
                pain_affects_movement=False,
                pain_is_new=True,
                pain_is_worsening=False,
                illness_symptoms=False,
            )
        )
    )
    assert "выраженность 3/10" in rendered
    assert "private location" not in rendered
    assert "readiness_score" not in rendered
    assert "PAIN_" not in rendered


def test_sleep_prefill_shows_provenance_and_freshness_without_internal_id() -> None:
    rendered = format_check_in(
        draft(
            ReadinessValues(
                sleep_duration_sec=28_800,
                sleep_ended_at=NOW - timedelta(hours=8),
                sleep_summary_id=uuid.UUID(int=99),
            )
        ),
        moment=NOW,
    )

    assert "Health Connect: свежий prefill" in rendered
    assert uuid.UUID(int=99).hex not in rendered


def test_rest_presentation_is_allowlisted_and_has_no_diagnosis() -> None:
    prescription = Prescription(
        RunDecision.REST,
        None,
        date(2026, 7, 13),
        NOW,
        NOW + timedelta(hours=72),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0.8,
        ("PAIN_REST", "UNKNOWN_INTERNAL_REASON"),
        (),
    )
    rendered = format_prescription(prescription)
    assert "безопаснее не начинать" in rendered
    assert "медицинскому специалисту" in rendered
    assert "диагноз" not in rendered.casefold()
    assert "PAIN_REST" not in rendered
    assert "UNKNOWN_INTERNAL_REASON" not in rendered


def test_run_presentation_rounds_human_values_and_always_shows_rpe() -> None:
    prescription = Prescription(
        RunDecision.RUN,
        RecommendedRunKind.EASY,
        date(2026, 7, 13),
        NOW,
        NOW + timedelta(hours=72),
        1_800,
        5_000,
        380,
        405,
        None,
        None,
        3,
        4,
        None,
        None,
        0.8,
        ("GOAL_ALIGNED",),
        (),
    )
    rendered = format_prescription(prescription)
    assert "5 км" in rendered
    assert "RPE 3–4" in rendered
    assert "6:20–6:45/км" in rendered
    assert "GOAL_ALIGNED" not in rendered


def test_callback_parser_rejects_forged_or_non_opaque_ids() -> None:
    draft_id = uuid.UUID(int=10)
    assert _parse_field(f"next:f:{draft_id.hex}:x:3") == (
        draft_id,
        "external_load",
        "3",
    )
    with pytest.raises((ReadinessError, ValueError)):
        _parse_field("next:f:not-a-uuid:p:1")
    with pytest.raises(ReadinessError):
        _parse_field(f"next:publish:{draft_id.hex}:pain_present:1")
