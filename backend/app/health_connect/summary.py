from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from app.activities.models import Activity
from app.analytics.metrics import format_duration


def build_batch_summary(
    activities: tuple[Activity, ...],
    *,
    timezone: str,
    period_start: datetime,
    period_end: datetime,
    found: int,
    saved: int,
    duplicate: int,
    skipped: int,
    errors: int,
    maximum_items: int = 5,
) -> str:
    zone = ZoneInfo(timezone)
    lines = [
        "🏃 <b>Синхронизация завершена</b>",
        f"Период: {period_start.astimezone(zone):%d.%m.%Y} — "
        f"{period_end.astimezone(zone):%d.%m.%Y}",
        f"Найдено: {found} · сохранено: {saved} · дубли: {duplicate} · "
        f"пропущено: {skipped} · ошибок: {errors}",
    ]
    if activities:
        lines.append(
            f"Итого новых: <b>{sum(item.distance_m for item in activities) / 1000:.2f} км</b> · "
            f"{format_duration(sum(item.elapsed_time_sec for item in activities))}"
        )
        local_groups: dict[str, list[Activity]] = {}
        latest = sorted(
            activities, key=lambda item: (item.started_at, item.external_id or ""), reverse=True
        )[:maximum_items]
        for activity in latest:
            key = activity.started_at.astimezone(zone).strftime("%d.%m.%Y")
            local_groups.setdefault(key, []).append(activity)
        for local_date, group in local_groups.items():
            lines.append(
                f"\n📅 <b>{local_date}</b> · {len(group)} сесс. · "
                f"{sum(item.distance_m for item in group) / 1000:.2f} км · "
                f"{format_duration(sum(item.elapsed_time_sec for item in group))}"
            )
            for activity in group:
                title = f" · {escape(activity.title)}" if activity.title else ""
                lines.append(
                    f"• {activity.started_at.astimezone(zone):%H:%M} · "
                    f"{activity.distance_m / 1000:.2f} км · "
                    f"{format_duration(activity.elapsed_time_sec)} · "
                    f"{activity.avg_pace_sec_per_km // 60}:"
                    f"{activity.avg_pace_sec_per_km % 60:02d}/км{title}"
                )
    lines.append("\nДальше: /stats · /run · отправить GPX/TCX/FIT/CSV · /help")
    return "\n".join(lines)
