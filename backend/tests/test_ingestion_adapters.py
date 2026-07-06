import base64

import pytest

from app.activities.models import SourceType
from app.ingestion.adapters.registry import AdapterRegistry
from app.ingestion.schemas import ImportError, validate_normalized

GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Morning run</name><trkseg>
    <trkpt lat="55.7500" lon="37.6100"><ele>150</ele><time>2026-07-06T06:00:00Z</time></trkpt>
    <trkpt lat="55.7590" lon="37.6100"><ele>152</ele><time>2026-07-06T06:06:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""

TCX = b"""<?xml version="1.0"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Running"><Id>2026-07-06T06:00:00Z</Id>
    <Lap StartTime="2026-07-06T06:00:00Z"><TotalTimeSeconds>360</TotalTimeSeconds>
      <DistanceMeters>1000</DistanceMeters><Track>
        <Trackpoint><Time>2026-07-06T06:00:00Z</Time><Position>
          <LatitudeDegrees>55.7500</LatitudeDegrees><LongitudeDegrees>37.6100</LongitudeDegrees>
        </Position></Trackpoint>
        <Trackpoint><Time>2026-07-06T06:06:00Z</Time><Position>
          <LatitudeDegrees>55.7590</LatitudeDegrees><LongitudeDegrees>37.6100</LongitudeDegrees>
        </Position></Trackpoint>
      </Track></Lap>
  </Activity></Activities>
</TrainingCenterDatabase>"""

CSV = (
    b"started_at,distance_m,elapsed_time_sec,moving_time_sec,activity_type,title,"
    b"external_id,avg_hr,max_hr\n"
    b"2026-07-06T06:00:00+00:00,5000,1800,1750,RUN,Tempo,csv-1,150,170\n"
)

# Small activity fixture from fitdecode's MIT-licensed upstream test suite.
FIT = base64.b64decode(
    "DBBkAPUCAAAuRklUQAABAAAFAwSMBASGAQKEAgKEAAEAAH////8p5gcSAA8AAQRAAAEAMQIAAoQBAQJAAAEAMQEAAoQAAPBBAAEAFQX9BIYDBIYAAQABAQAEAQJBAAEAFQX9BIYDAQAAAQABAQAEAQIBKeYHEgAAAABCAAEAFAb9BIYABIUBBIUFBIYCAoQGAoQCKeYHEh2FYS7L+7SXAAAAAg8zAAACKeYHEx2FYS7L+7SYAAAAAg8zAAACKeYHFB2FYS7L+7SYAAAAAg8zAAACKeYHFR2FYTnL+7SCAAAAFQ8zAAACKeYHFh2FYUDL+7R5AAAAHA8zAAACKeYHFx2FYUbL+7RyAAAAIw8zAAACKeYHGB2FYUrL+7RsAAAAKQ8zAAACKeYHGR2FYXfL+7QUAAAAcg8zAAACKeYHGh2FYY3L+7O0AAAAuQ8zAFwCKeYHGx2FYa7L+7M8AAABEw8zAJgCKeYHHB2FYczL+7LXAAABXw8zANECKeYHHR2FYarL+7J5AAABpg8zAQYCKeYHHh2FYV/L+7KNAAAB7Q8zATMCKeYHHx2FYRLL+7JXAAACPQ8zAXABKeYHHwAABABDAAEAExT9BIYCBIYDBIUEBIUFBIUGBIUHBIYIBIYJBIb+AoQLAoQMAoQNAoQOAoQVAoQWAoQAAQABAQAYAQAZAQADKeYHoynmBxIdhWEuy/u0lx2FYRLL+7JXAAA1tQAANbUAAAI9AAAAAAAAAaEBcAAAAAAJAQcBQQABABUF/QSGAwSGAAEAAQEABAECASnmB6MAAAABCAkBRAABABIV/QSGAgSGAwSFBASFBwSGCASGCQSG/gKECwKEDQKEDgKEDwKEFgKEFwKEGQKEGgKEAAEAAQEABQEABgEAHAEABCnmB6Mp5gcSHYVhLsv7tJcAADW1AAA1tQAAAj0AAAAAAAABoQFwAAAAAAAAAAEJAQEAAEUAAQAiB/0EhgAEhgUEhgEChAIBAAMBAAQBAAUp5gejAAA1tSnlz2MAAQAaAdWh"
)


@pytest.mark.parametrize(
    ("suffix", "content", "source_type"),
    [
        (".gpx", GPX, SourceType.GPX),
        (".tcx", TCX, SourceType.TCX),
        (".fit", FIT, SourceType.FIT),
        (".csv", CSV, SourceType.CSV),
    ],
)
def test_supported_file_produces_valid_normalized_draft(
    suffix: str, content: bytes, source_type: SourceType
) -> None:
    result = AdapterRegistry().parse(suffix, content, "Europe/Moscow")

    validate_normalized(result)
    assert result.source_type == source_type
    assert result.distance_m > 0
    assert result.elapsed_time_sec > 0


def test_xml_external_entity_is_rejected() -> None:
    malicious = b"""<?xml version="1.0"?>
<!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<gpx><trk><name>&xxe;</name></trk></gpx>"""

    with pytest.raises(ImportError, match="GPX"):
        AdapterRegistry().parse(".gpx", malicious, "Europe/Moscow")


def test_csv_requires_timezone_aware_started_at() -> None:
    content = b"started_at,distance_m,elapsed_time_sec\n2026-07-06T06:00:00,5000,1800\n"

    with pytest.raises(ImportError, match="часовой пояс"):
        AdapterRegistry().parse(".csv", content, "Europe/Moscow")
