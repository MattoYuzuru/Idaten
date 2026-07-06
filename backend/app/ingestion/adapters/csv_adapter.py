import csv
import io

from app.activities.models import ActivityType, SourceType
from app.ingestion.adapters.track import parse_timestamp
from app.ingestion.schemas import ImportError, NormalizedActivity

REQUIRED_COLUMNS = {"started_at", "distance_m", "elapsed_time_sec"}


class CsvAdapter:
    source_type = SourceType.CSV

    def parse(self, content: bytes, timezone: str) -> NormalizedActivity:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ImportError("CSV должен быть в UTF-8.", code="CSV_ENCODING") from error
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except csv.Error as error:
            raise ImportError("Не удалось разобрать CSV.", code="CSV_PARSE_ERROR") from error
        if len(rows) != 1:
            raise ImportError("CSV должен содержать одну activity-строку.", code="CSV_ROW_COUNT")
        row = rows[0]
        if None in row:
            raise ImportError("CSV содержит лишние колонки.", code="CSV_COLUMNS")
        if not REQUIRED_COLUMNS.issubset(row):
            raise ImportError("CSV не содержит обязательные колонки.", code="CSV_COLUMNS")
        try:
            activity_type = ActivityType(row.get("activity_type", "RUN").upper())
            distance = int(row["distance_m"])
            elapsed = int(row["elapsed_time_sec"])
            moving = int(row["moving_time_sec"]) if row.get("moving_time_sec") else None
            avg_hr = int(row["avg_hr"]) if row.get("avg_hr") else None
            max_hr = int(row["max_hr"]) if row.get("max_hr") else None
        except (TypeError, ValueError) as error:
            raise ImportError(
                "CSV содержит некорректные числовые поля.", code="CSV_VALUES"
            ) from error
        return NormalizedActivity(
            source_type=self.source_type,
            activity_type=activity_type,
            started_at=parse_timestamp(row["started_at"]),
            timezone=timezone,
            distance_m=distance,
            elapsed_time_sec=elapsed,
            moving_time_sec=moving,
            title=row.get("title") or None,
            external_id=row.get("external_id") or None,
            avg_hr=avg_hr,
            max_hr=max_hr,
        )
