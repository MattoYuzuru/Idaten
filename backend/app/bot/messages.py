from app.activities.schemas import ActivitySummary, AggregateStats, PersonalRecords
from app.analytics.metrics import format_duration
from app.groups.models import ShareLevel
from app.groups.schemas import GroupWeek, LeaderboardEntry, PrivacyOverview, StreakEntry

HELP_TEXT = """Idaten сохраняет и анализирует ваши пробежки.

/run 10.02 1:02:41 — добавить пробежку
/stats — статистика за все время
/week — текущая неделя
/pr — лучшие зарегистрированные 5K и 10K
/privacy [on|off] — настройки приватности
/share <chat_id> <none|summary|detailed> — sharing для группы
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


def format_privacy(overview: PrivacyOverview) -> str:
    state = "включен" if overview.group_sharing_enabled else "выключен"
    lines = [f"Групповой sharing: {state}"]
    if not overview.groups:
        lines.append("Активных групп нет.")
    for group in overview.groups:
        auto = ", всегда" if group.auto_share else ""
        lines.append(f"{group.title} ({group.telegram_chat_id}): {group.share_level.value}{auto}")
    return "Privacy\n\n" + "\n".join(lines)


def format_share_level(group_title: str, share_level: ShareLevel) -> str:
    return f"Sharing для «{group_title}»: {share_level.value}."


def format_leaderboard(entries: tuple[LeaderboardEntry, ...]) -> str:
    if not entries:
        return "Leaderboard за неделю\n\nНет разрешенных пробежек."
    lines = [
        f"{position}. {entry.display_name} — {entry.distance_m / 1000:.2f} км ({entry.run_count})"
        for position, entry in enumerate(entries, start=1)
    ]
    return "Leaderboard за неделю\n\n" + "\n".join(lines)


def format_group_week(stats: GroupWeek) -> str:
    return (
        "Неделя группы\n\n"
        f"Пробежек: {stats.run_count}\n"
        f"Дистанция: {stats.distance_m / 1000:.2f} км\n"
        f"Участников: {stats.members}"
    )


def format_streaks(entries: tuple[StreakEntry, ...]) -> str:
    if not entries:
        return "Streaks\n\nНет разрешенных пробежек."
    return "Streaks\n\n" + "\n".join(
        f"{entry.display_name} — {entry.weeks} нед." for entry in entries
    )
