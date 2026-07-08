from datetime import UTC, datetime

import pytest

from app.activities.schemas import ActivityInputError, parse_run_command


@pytest.mark.parametrize("distance", ["10.02", "10,02"])
def test_parse_run_command(distance: str) -> None:
    moment = datetime(2026, 7, 5, tzinfo=UTC)
    result = parse_run_command(f"{distance} 1:02:41", moment)
    assert result.distance_m == 10_020
    assert result.elapsed_time_sec == 3_761
    assert result.started_at == moment


@pytest.mark.parametrize("arguments", [None, "", "10", "ten 1:00", "10 1:60"])
def test_parse_run_command_rejects_invalid_input(arguments: str | None) -> None:
    with pytest.raises(ActivityInputError):
        parse_run_command(arguments, datetime.now(UTC))


def test_extended_run_command_parses_historical_optional_fields_and_title() -> None:
    result = parse_run_command(
        "21.10 1:55:30 date=2026-06-16 time=07:30 moving=1:50:00 hr=152 "
        'max_hr=178 cadence=171 elevation=164 title="Полумарафон" tz=Europe/Moscow',
        datetime(2026, 7, 8, 12, tzinfo=UTC),
    )
    assert result.started_at.isoformat() == "2026-06-16T07:30:00+03:00"
    assert result.moving_time_sec == 6_600
    assert result.avg_hr == 152
    assert result.max_hr == 178
    assert result.avg_cadence_spm == 171
    assert result.elevation_gain_m == 164
    assert result.title == "Полумарафон"


@pytest.mark.parametrize(
    "arguments",
    [
        "10 1:00 hr=180 max_hr=170",
        "10 1:00 moving=1:01",
        "10 1:00 cadence=301",
        "10 1:00 hr=150 hr=151",
        "10 1:00 pace=5:00",
        '10 1:00 title="unterminated',
    ],
)
def test_extended_run_command_rejects_inconsistent_or_unknown_fields(arguments: str) -> None:
    with pytest.raises(ActivityInputError):
        parse_run_command(arguments, datetime.now(UTC), "Europe/Moscow")
