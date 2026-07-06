from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.adapters.csv_adapter import CsvAdapter
from app.ingestion.adapters.fit import FitAdapter
from app.ingestion.adapters.gpx import GpxAdapter
from app.ingestion.adapters.tcx import TcxAdapter
from app.ingestion.schemas import ImportError, NormalizedActivity


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {
            ".gpx": GpxAdapter(),
            ".tcx": TcxAdapter(),
            ".fit": FitAdapter(),
            ".csv": CsvAdapter(),
        }

    def parse(self, suffix: str, content: bytes, timezone: str) -> NormalizedActivity:
        adapter = self._adapters.get(suffix.lower())
        if adapter is None:
            raise ImportError("Формат файла не поддерживается.", code="UNSUPPORTED_TYPE")
        return adapter.parse(content, timezone)
