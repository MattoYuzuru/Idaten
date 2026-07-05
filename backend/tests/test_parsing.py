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
