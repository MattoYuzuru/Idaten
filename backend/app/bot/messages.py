# ruff: noqa: E501
from html import escape

from app.activities.schemas import (
    ActivitySummary,
    AggregateStats,
    DailyRunGroup,
    ManualDraft,
    PersonalRecords,
)
from app.analytics.metrics import format_duration
from app.groups.models import ShareLevel
from app.groups.schemas import GroupWeek, LeaderboardEntry, PrivacyOverview, StreakEntry
from app.ingestion.schemas import ImportHistoryItem, ImportPreview

HELP_TEXT = (
    "<b>Idaten 0.7</b>\n\n"
    "Сохраняет private-пробежки, синхронизирует Health Connect и показывает прогресс. "
    "Выберите раздел справки ниже."
)

HELP_SECTIONS = {
    "start": """<b>Старт и меню</b>

/start — private — регистрация и onboarding. Пример: /start. Результат: путь подключения или главное меню.
/menu — private — основные действия кнопками. Пример: /menu. Результат: главное меню.
/help — private/group — полная справка по категориям. Пример: /help.""",
    "activities": """<b>Активности и аналитика</b>

/run — private — кнопочный мастер.
/run &lt;км&gt; &lt;MM:SS|H:MM:SS&gt; [date=YYYY-MM-DD] [time=HH:MM] [moving=H:MM:SS] [hr=&lt;avg&gt;] [max_hr=&lt;max&gt;] [cadence=&lt;spm&gt;] [elevation=&lt;м&gt;] [title=&quot;...&quot;] [tz=&lt;IANA&gt;]
Пример: /run 21.10 1:55:30 date=2026-06-16 time=07:30 hr=152 max_hr=178 cadence=171 elevation=164 title=&quot;Полумарафон&quot;.
Результат: private Activity, отчет и отдельный opt-in на публикацию.
/stats — private — статистика за всё время. /week — private/group — текущая неделя.
/pr — private — зарегистрированные 5K/10K. /next — private — следующая тренировка.
/plan &lt;FIRST_10K|HALF|MARATHON|CUSTOM&gt; [цель] — private. Пример: /plan HALF 1:50.""",
    "imports": """<b>Импорт файлов</b>

Отправьте в private chat GPX, TCX, FIT, CSV или ZIP с одним поддерживаемым файлом. Бот покажет preview; кнопка подтверждения сохраняет Activity.
/imports — private — последние попытки и статусы. Пример: /imports.""",
    "health": """<b>Health Connect</b>

/link — private — одноразовый код Android. Установите APK, выдайте read permissions, введите код, загрузите последние пробежки и явно нажмите «Синхронизировать».
/devices — private — связанные устройства. /revoke_device &lt;device_uuid&gt; — private — немедленно отозвать token.
Telegram сам не читает Health Connect; sync остаётся foreground/manual в Android.""",
    "privacy": """<b>Privacy и группы</b>

/privacy [on|off] — private — общий group sharing. /share &lt;chat_id&gt; &lt;none|summary|detailed&gt; — private.
/setup_group — group admin — настроить группу. /join, /leave — group.
/month, /leaderboard, /streaks, /week — group. /group_goal &lt;км&gt; — group admin.
Пример: /share -100123 summary. Activity по умолчанию private; HR, cadence, точное время, route и raw payload в группу не отправляются.""",
    "external": """<b>Внешний wording</b>

/external_processing on|off — private. По умолчанию off. При on внешний provider получает только allowlisted facts и каноническую рекомендацию, но не raw activity, GPS/route или токены.
Пример: /external_processing off.""",
}


def format_stats(stats: AggregateStats, title: str) -> str:
    safe_title = escape(title)
    if stats.run_count == 0:
        return f"<b>{safe_title}</b>\n\nПробежек пока нет. Добавьте: /run 5 30:00"
    return (
        f"<b>{safe_title}</b>\n\n"
        f"Пробежек: <b>{stats.run_count}</b>\n"
        f"Дистанция: <b>{stats.distance_m / 1000:.2f} км</b>\n"
        f"Самая длинная: {stats.longest_run_m / 1000:.2f} км"
    )


def _format_record(label: str, record: ActivitySummary | None) -> str:
    if record is None:
        return f"{label}: пока нет подходящей пробежки"
    return f"{label}: <b>{format_duration(record.elapsed_time_sec)}</b> · {record.distance_m / 1000:.2f} км"


def format_personal_records(records: PersonalRecords) -> str:
    return "<b>Личные результаты</b>\n\n" + "\n".join(
        (_format_record("5K", records.best_5k), _format_record("10K", records.best_10k))
    )


def format_manual_draft(draft: ManualDraft) -> str:
    run = draft.run
    distance = f"{run.distance_m / 1000:.2f} км" if run.distance_m else "не указана"
    duration = format_duration(run.elapsed_time_sec) if run.elapsed_time_sec else "не указана"
    lines = [
        "🏃 <b>Новая пробежка</b>",
        f"Дистанция: <b>{distance}</b>",
        f"Длительность: <b>{duration}</b>",
        f"Дата: {run.started_at:%d.%m.%Y %H:%M} ({escape(run.timezone or 'UTC')})",
    ]
    if run.moving_time_sec is not None:
        lines.append(f"Moving time: {format_duration(run.moving_time_sec)}")
    if run.avg_hr is not None or run.max_hr is not None:
        lines.append(f"Пульс: {run.avg_hr or '—'} / {run.max_hr or '—'}")
    if run.avg_cadence_spm is not None:
        lines.append(f"Каденс: {run.avg_cadence_spm} spm")
    if run.elevation_gain_m is not None:
        lines.append(f"Набор высоты: {run.elevation_gain_m} м")
    if run.title:
        lines.append(f"Название: {escape(run.title)}")
    lines.append("\nActivity останется private. Выберите поле или сохраните.")
    return "\n".join(lines)


def format_run_history(groups: tuple[DailyRunGroup, ...], offset: int = 0, size: int = 5) -> str:
    page = groups[offset : offset + size]
    if not page:
        return "<b>Мои пробежки</b>\n\nПока нет сохраненных пробежек."
    lines = ["<b>Мои пробежки</b>"]
    for group in page:
        lines.append(
            f"\n📅 <b>{group.local_date:%d.%m.%Y}</b> · {group.run_count} сесс. · "
            f"{group.distance_m / 1000:.2f} км · {format_duration(group.elapsed_time_sec)}"
        )
        for run in reversed(group.runs):
            title = f" · {escape(run.title)}" if run.title else ""
            lines.append(
                f"• {run.started_at:%H:%M} · {run.distance_m / 1000:.2f} км · "
                f"{format_duration(run.elapsed_time_sec)}{title}"
            )
    return "\n".join(lines)


def format_privacy(overview: PrivacyOverview) -> str:
    state = "включен" if overview.group_sharing_enabled else "выключен"
    lines = [f"Групповой sharing: {state}"]
    if not overview.groups:
        lines.append("Активных групп нет.")
    for group in overview.groups:
        auto = ", всегда" if group.auto_share else ""
        lines.append(
            f"{escape(group.title)} ({group.telegram_chat_id}): {group.share_level.value}{auto}"
        )
    return "<b>Privacy</b>\n\n" + "\n".join(lines)


def format_share_level(group_title: str, share_level: ShareLevel) -> str:
    return f"Sharing для «{escape(group_title)}»: {share_level.value}."


def format_leaderboard(entries: tuple[LeaderboardEntry, ...]) -> str:
    if not entries:
        return "<b>Leaderboard за неделю</b>\n\nНет разрешенных пробежек."
    lines = [
        f"{position}. {escape(entry.display_name)} — {entry.distance_m / 1000:.2f} км ({entry.run_count})"
        for position, entry in enumerate(entries, start=1)
    ]
    return "<b>Leaderboard за неделю</b>\n\n" + "\n".join(lines)


def format_group_week(stats: GroupWeek) -> str:
    return (
        "<b>Неделя группы</b>\n\n"
        f"Пробежек: {stats.run_count}\n"
        f"Дистанция: <b>{stats.distance_m / 1000:.2f} км</b>\n"
        f"Участников: {stats.members}"
    )


def format_streaks(entries: tuple[StreakEntry, ...]) -> str:
    if not entries:
        return "<b>Streaks</b>\n\nНет разрешенных пробежек."
    return "<b>Streaks</b>\n\n" + "\n".join(
        f"{escape(entry.display_name)} — {entry.weeks} нед." for entry in entries
    )


def format_import_preview(preview: ImportPreview) -> str:
    duplicate = ""
    if preview.exact_duplicate_activity_id is not None:
        duplicate = "\nТочный дубликат уже сохраненной активности."
    elif preview.duplicate_candidates:
        duplicate = f"\nНайдено похожих активностей: {len(preview.duplicate_candidates)}."
    title = f"\nНазвание: {escape(preview.title)}" if preview.title else ""
    return (
        f"<b>Черновик {preview.source_type.value}</b>\n\n"
        f"Дистанция: <b>{preview.distance_m / 1000:.2f} км</b>\n"
        f"Время: {format_duration(preview.elapsed_time_sec)}\n"
        f"Старт: {preview.started_at:%d.%m.%Y %H:%M %Z}{title}{duplicate}"
        "\n\nДо подтверждения активность не сохранена."
    )


def format_import_history(items: tuple[ImportHistoryItem, ...]) -> str:
    if not items:
        return "История импортов пуста."
    lines = [
        f"{escape(item.filename)} — {item.status}"
        + (f" ({item.source_type.value})" if item.source_type else "")
        for item in items
    ]
    return "<b>Последние импорты</b>\n\n" + "\n".join(lines)
