import json
import struct

import pytest

from app.assisted.media import validate_image
from app.assisted.provider import OpenAIActivityExtractionProvider
from app.assisted.schemas import AssistedError


def test_png_validation_checks_magic_mime_and_pixels() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 100, 200) + b"rest"
    assert validate_image(png, "image/png", max_bytes=1_000, max_pixels=50_000) == "image/png"
    with pytest.raises(AssistedError) as captured:
        validate_image(png, "image/jpeg", max_bytes=1_000, max_pixels=50_000)
    assert captured.value.code == "IMAGE_MIME"


def test_openai_response_parser_accepts_strict_output() -> None:
    payload = {
        "id": "resp-1",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "is_run": True,
                                "local_date": "2026-07-08",
                                "local_time": "07:30",
                                "distance_m": 5000,
                                "elapsed_time_sec": 1800,
                                "moving_time_sec": None,
                                "avg_hr": None,
                                "max_hr": None,
                                "avg_cadence_spm": None,
                                "elevation_gain_m": None,
                                "title": None,
                            }
                        ),
                    }
                ],
            }
        ],
    }
    provider = OpenAIActivityExtractionProvider("test", "secret")

    captured_body: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode()

    from app.assisted import provider as provider_module

    original = provider_module.urllib.request.urlopen

    def open_response(request, **_kwargs):
        captured_body.update(json.loads(request.data))
        return Response()

    provider_module.urllib.request.urlopen = open_response
    try:
        from datetime import date

        from app.activities.models import DraftInputMethod
        from app.assisted.schemas import ExtractionRequest

        result = provider._extract_sync(
            ExtractionRequest(
                method=DraftInputMethod.TEXT,
                timezone="Europe/Moscow",
                local_date=date(2026, 7, 11),
                text="5 км за 30 минут",
            )
        )
    finally:
        provider_module.urllib.request.urlopen = original
    assert result.provider_request_id == "resp-1"
    assert result.run.distance_m == 5000
    assert captured_body["store"] is False
    assert "tools" not in captured_body
    text_format = captured_body["text"]
    assert isinstance(text_format, dict)
    output_format = text_format["format"]
    assert isinstance(output_format, dict)
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    schema = output_format["schema"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False
