from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DuplicateTolerance:
    distance_m: int
    elapsed_time_sec: int


def duplicate_tolerance(distance_m: int, elapsed_time_sec: int) -> DuplicateTolerance:
    return DuplicateTolerance(
        distance_m=max(200, round(distance_m * 0.03)),
        elapsed_time_sec=max(120, round(elapsed_time_sec * 0.03)),
    )


def metrics_match(
    *,
    existing_distance_m: int,
    existing_elapsed_time_sec: int,
    distance_m: int,
    elapsed_time_sec: int,
) -> tuple[bool, bool]:
    tolerance = duplicate_tolerance(distance_m, elapsed_time_sec)
    return (
        abs(existing_distance_m - distance_m) <= tolerance.distance_m,
        abs(existing_elapsed_time_sec - elapsed_time_sec) <= tolerance.elapsed_time_sec,
    )
