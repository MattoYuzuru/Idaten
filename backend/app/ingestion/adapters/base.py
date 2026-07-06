from typing import Protocol

from app.activities.models import SourceType
from app.ingestion.schemas import NormalizedActivity


class SourceAdapter(Protocol):
    source_type: SourceType

    def parse(self, content: bytes, timezone: str) -> NormalizedActivity: ...
