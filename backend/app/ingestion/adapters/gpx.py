from defusedxml import ElementTree

from app.activities.models import SourceType
from app.ingestion.adapters.track import normalize_track, parse_timestamp
from app.ingestion.schemas import ImportError, NormalizedActivity, TrackPoint


class GpxAdapter:
    source_type = SourceType.GPX

    def parse(self, content: bytes, timezone: str) -> NormalizedActivity:
        try:
            root = ElementTree.fromstring(content)
        except Exception as error:
            raise ImportError("Не удалось разобрать GPX.", code="GPX_PARSE_ERROR") from error
        points: list[TrackPoint] = []
        for element in root.findall(".//{*}trkpt"):
            time_element = element.find("{*}time")
            if time_element is None or not time_element.text:
                raise ImportError("GPX trackpoint не содержит время.", code="GPX_MISSING_TIME")
            try:
                latitude = float(element.attrib["lat"])
                longitude = float(element.attrib["lon"])
            except (KeyError, ValueError) as error:
                raise ImportError(
                    "GPX содержит некорректные координаты.", code="GPX_COORDINATES"
                ) from error
            elevation_element = element.find("{*}ele")
            heart_rate_element = element.find(".//{*}hr")
            points.append(
                TrackPoint(
                    timestamp=parse_timestamp(time_element.text),
                    latitude=latitude,
                    longitude=longitude,
                    elevation_m=(
                        float(elevation_element.text)
                        if elevation_element is not None and elevation_element.text
                        else None
                    ),
                    heart_rate=(
                        int(heart_rate_element.text)
                        if heart_rate_element is not None and heart_rate_element.text
                        else None
                    ),
                )
            )
        name_element = root.find(".//{*}trk/{*}name")
        return normalize_track(
            source_type=self.source_type,
            points=points,
            timezone=timezone,
            title=name_element.text.strip()
            if name_element is not None and name_element.text
            else None,
        )
