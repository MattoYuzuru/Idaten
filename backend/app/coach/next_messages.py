from datetime import UTC, datetime, timedelta
from html import escape

from app.analytics.metrics import format_duration, format_pace
from app.coach.candidates import RecommendedRunKind, RunDecision
from app.coach.prescription import Prescription
from app.goals.domain import RunningGoalType
from app.readiness.schemas import ReadinessDraft

GOAL_LABELS: dict[RunningGoalType, str] = {
    RunningGoalType.FIRST_5K: "Впервые 5 км",
    RunningGoalType.FIRST_10K: "Впервые 10 км",
    RunningGoalType.FIRST_HALF: "Первый полумарафон",
    RunningGoalType.FIRST_MARATHON: "Первый марафон",
    RunningGoalType.IMPROVE_HALF: "Улучшить полумарафон",
    RunningGoalType.IMPROVE_MARATHON: "Улучшить марафон",
    RunningGoalType.GENERAL_ENDURANCE: "Общая выносливость",
}

REASON_TEMPLATES = {
    "ILLNESS_REST": "есть признаки болезни",
    "PAIN_REST": "указана боль, при которой безопаснее не начинать тренировку",
    "PAIN_CAUTION": "указана новая или умеренная боль",
    "VERY_LOW_READINESS": "готовность сегодня очень низкая",
    "LOW_READINESS": "восстановление пока ограничено",
    "HIGH_EXTERNAL_LOAD": "внешняя нагрузка сейчас высокая",
    "RETURN_AFTER_LONG_BREAK": "после длинного перерыва нагрузка ограничена",
    "CONSERVATIVE_LOW_CONFIDENCE": "истории пока недостаточно для интенсивной нагрузки",
    "RECENT_HARD_LOAD": "недавняя интенсивная нагрузка требует восстановления",
    "AVAILABLE_TIME_TOO_SHORT": "доступного времени недостаточно для безопасной пробежки",
    "GOAL_ALIGNED": "вариант соответствует цели и текущему восстановлению",
    "RECOVERY_DAY": "сейчас полезнее восстановление",
}


def format_prescription(prescription: Prescription) -> str:
    reasons = tuple(
        REASON_TEMPLATES[code] for code in prescription.reason_codes if code in REASON_TEMPLATES
    )
    why = "; ".join(reasons) or "учтены история, цель и подтверждённое самочувствие"
    if prescription.decision == RunDecision.REST:
        return (
            "<b>Следующая пробежка</b>\n\n"
            "Сегодня бег лучше отложить. Вы указали состояние, при котором безопаснее "
            "не начинать тренировку. Если боль или симптомы сохраняются либо усиливаются, "
            "обратитесь к медицинскому специалисту.\n\n"
            f"Почему: {escape(why)}"
        )
    assert prescription.kind is not None
    assert prescription.duration_sec is not None
    kind = {
        RecommendedRunKind.RECOVERY: "восстановительно",
        RecommendedRunKind.EASY: "легко",
        RecommendedRunKind.STEADY: "ровно",
        RecommendedRunKind.TEMPO: "контролируемо темпово",
        RecommendedRunKind.LONG_RUN: "длительно и легко",
    }[prescription.kind]
    main = _variant(prescription.distance_m, prescription.duration_sec, kind)
    short = "нет безопасного короткого варианта"
    if prescription.short is not None:
        short = _variant(
            prescription.short.distance_m,
            prescription.short.duration_sec,
            {
                RecommendedRunKind.RECOVERY: "восстановительно",
                RecommendedRunKind.EASY: "легко",
                RecommendedRunKind.STEADY: "ровно",
                RecommendedRunKind.TEMPO: "контролируемо темпово",
                RecommendedRunKind.LONG_RUN: "длительно и легко",
            }[prescription.short.kind],
        )
    intensity = f"RPE {prescription.rpe_min}–{prescription.rpe_max} из 10, разговорный темп"
    if prescription.pace_min_sec_per_km is not None:
        intensity += (
            f"; ориентир {format_pace(prescription.pace_min_sec_per_km)}–"
            f"{format_pace(prescription.pace_max_sec_per_km or 0)}/км"
        )
    return (
        "<b>Следующая пробежка</b>\n\n"
        f"Когда: не раньше {prescription.not_before:%d.%m.%Y %H:%M}\n"
        f"Основной вариант: {main}\n"
        f"Короткий вариант: {short}\n"
        f"Интенсивность: {intensity}\n\n"
        f"Почему: {escape(why)}.\n\n"
        "Перед стартом ещё раз проверьте самочувствие."
    )


def format_check_in(draft: ReadinessDraft, *, moment: datetime | None = None) -> str:
    values = draft.values
    pain = "нет"
    if values.pain_present:
        pain = f"да, выраженность {values.pain_severity}/10"
    sleep = "нет данных"
    if values.sleep_quality is not None or values.sleep_duration_sec is not None:
        quality = "нет данных" if values.sleep_quality is None else f"{values.sleep_quality}/5"
        duration = (
            "нет данных"
            if values.sleep_duration_sec is None
            else format_duration(values.sleep_duration_sec)
        )
        provenance = ""
        if values.sleep_summary_id is not None and values.sleep_ended_at is not None:
            now = moment or datetime.now(UTC)
            age = now.astimezone(UTC) - values.sleep_ended_at.astimezone(UTC)
            freshness = (
                "свежий prefill"
                if timedelta(0) <= age <= timedelta(hours=36)
                else "устарел и не войдёт в расчёт"
            )
            provenance = (
                f", Health Connect: {freshness} "
                f"(сон завершился {values.sleep_ended_at:%d.%m %H:%M})"
            )
        sleep = f"качество {quality}, длительность {duration}{provenance}"
    return (
        "<b>Проверка готовности</b>\n\n"
        f"Готовность: {_value(values.overall_readiness, '/5')}\n"
        f"Общая усталость: {_value(values.general_fatigue, '/10')}\n"
        f"Мышечная болезненность: {_value(values.muscle_soreness, '/10')}\n"
        f"Боль: {pain}\n"
        f"Признаки болезни: {_boolean(values.illness_symptoms)}\n"
        f"Сон: {sleep}\n"
        f"Внешняя нагрузка: {_value(values.external_load, '/10')}\n"
        f"Мотивация: {_value(values.motivation, '/5')}\n"
        f"Доступное время: {_duration(values.available_time_sec)}\n"
        f"RPE прошлой пробежки: {_value(values.session_rpe, '/10')}"
    )


def _variant(distance_m: int | None, duration_sec: int, kind: str) -> str:
    distance = "" if distance_m is None else f"{distance_m / 1000:g} км, "
    return f"{distance}{kind}, около {format_duration(duration_sec)}"


def _value(value: int | None, suffix: str) -> str:
    return "нет данных" if value is None else f"{value}{suffix}"


def _boolean(value: bool | None) -> str:
    return "нет данных" if value is None else "да" if value else "нет"


def _duration(value: int | None) -> str:
    return "нет данных" if value is None else format_duration(value)
