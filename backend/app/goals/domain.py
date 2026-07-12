from enum import StrEnum

from app.activities.standards import StandardDistance


class RunningGoalType(StrEnum):
    FIRST_5K = "FIRST_5K"
    FIRST_10K = "FIRST_10K"
    FIRST_HALF = "FIRST_HALF"
    FIRST_MARATHON = "FIRST_MARATHON"
    IMPROVE_HALF = "IMPROVE_HALF"
    IMPROVE_MARATHON = "IMPROVE_MARATHON"
    GENERAL_ENDURANCE = "GENERAL_ENDURANCE"


class RunningGoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


GOAL_DISTANCES: dict[RunningGoalType, StandardDistance] = {
    RunningGoalType.FIRST_5K: StandardDistance.FIVE_K,
    RunningGoalType.FIRST_10K: StandardDistance.TEN_K,
    RunningGoalType.FIRST_HALF: StandardDistance.HALF_MARATHON,
    RunningGoalType.FIRST_MARATHON: StandardDistance.MARATHON,
    RunningGoalType.IMPROVE_HALF: StandardDistance.HALF_MARATHON,
    RunningGoalType.IMPROVE_MARATHON: StandardDistance.MARATHON,
}
IMPROVEMENT_GOALS = {
    RunningGoalType.IMPROVE_HALF,
    RunningGoalType.IMPROVE_MARATHON,
}
