from dataclasses import dataclass

from app.activities.schemas import ActivitySummary, AggregateStats
from app.analytics.metrics import format_duration, format_pace
from app.coach.domain import CALCULATOR_VERSION, RULE_VERSION


@dataclass(frozen=True, slots=True)
class BuiltReport:
    message: str
    facts_json: dict[str, object]
    rule_result_json: dict[str, object]


def build_after_run_report(activity: ActivitySummary, week: AggregateStats) -> BuiltReport:
    easy_min_km = max(2, round(activity.distance_m / 1000 * 0.7))
    easy_max_km = max(easy_min_km + 1, round(activity.distance_m / 1000 * 0.8))
    easy_pace_min = activity.avg_pace_sec_per_km + 30
    easy_pace_max = activity.avg_pace_sec_per_km + 65
    facts: dict[str, object] = {
        "calculator_version": CALCULATOR_VERSION,
        "rule_version": RULE_VERSION,
        "activity": {
            "activity_id": str(activity.activity_id),
            "distance_m": activity.distance_m,
            "elapsed_time_sec": activity.elapsed_time_sec,
            "avg_pace_sec_per_km": activity.avg_pace_sec_per_km,
        },
        "week": {
            "distance_m": week.distance_m,
            "run_count": week.run_count,
            "longest_run_m": week.longest_run_m,
        },
    }
    rules: dict[str, object] = {
        "next_workout": {
            "type": "EASY",
            "distance_km": f"{easy_min_km}–{easy_max_km}",
            "pace": f"{format_pace(easy_pace_min)}–{format_pace(easy_pace_max)}",
        },
        "rule_version": RULE_VERSION,
    }
    message = (
        "Сохранил тренировку:\n\n"
        f"{activity.distance_m / 1000:.2f} км · "
        f"{format_duration(activity.elapsed_time_sec)} · "
        f"{format_pace(activity.avg_pace_sec_per_km)}/км\n\n"
        f"Это ваша {week.run_count}-я пробежка за неделю. "
        f"Недельный объем: {week.distance_m / 1000:.2f} км.\n"
        f"Следующую лучше сделать легкой: {easy_min_km}–{easy_max_km} км в темпе "
        f"{format_pace(easy_pace_min)}–{format_pace(easy_pace_max)}/км."
    )
    return BuiltReport(
        message=message,
        facts_json=facts,
        rule_result_json=rules,
    )
