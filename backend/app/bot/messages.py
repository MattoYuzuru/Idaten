from app.activities.schemas import ActivitySummary, AggregateStats, PersonalRecords
from app.analytics.metrics import format_duration

HELP_TEXT = """Idaten сохраняет и анализирует ваши пробежки.

/run 10.02 1:02:41 — добавить пробежку
/stats — статистика за все время
/week — текущая неделя
/pr — лучшие зарегистрированные 5K и 10K
/help — эта справка"""


def format_stats(stats: AggregateStats, title: str) -> str:
    if stats.run_count == 0:
        return f"{title}\n\nПробежек пока нет. Добавьте первую: /run 5 30:00"
    return (
        f"{title}\n\n"
        f"Пробежек: {stats.run_count}\n"
        f"Дистанция: {stats.distance_m / 1000:.2f} км\n"
        f"Самая длинная: {stats.longest_run_m / 1000:.2f} км"
    )


def _format_record(label: str, record: ActivitySummary | None) -> str:
    if record is None:
        return f"{label}: пока нет подходящей пробежки"
    return (
        f"{label}: {format_duration(record.elapsed_time_sec)} ({record.distance_m / 1000:.2f} км)"
    )


def format_personal_records(records: PersonalRecords) -> str:
    return "Личные результаты\n\n" + "\n".join(
        (_format_record("5K", records.best_5k), _format_record("10K", records.best_10k))
    )
