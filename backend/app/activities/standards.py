from enum import IntEnum


class StandardDistance(IntEnum):
    FIVE_K = 5_000
    TEN_K = 10_000
    HALF_MARATHON = 21_097
    MARATHON = 42_195

    @property
    def label(self) -> str:
        return {
            StandardDistance.FIVE_K: "5 км",
            StandardDistance.TEN_K: "10 км",
            StandardDistance.HALF_MARATHON: "Полумарафон",
            StandardDistance.MARATHON: "Марафон",
        }[self]


STANDARD_DISTANCES = tuple(StandardDistance)


def is_actual_distance(distance_m: int, target: StandardDistance) -> bool:
    return int(target) * 98 <= distance_m * 100 <= int(target) * 102


def proves_finish(distance_m: int, target: StandardDistance) -> bool:
    return distance_m * 100 >= int(target) * 98
