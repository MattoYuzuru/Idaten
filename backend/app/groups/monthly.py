from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.coach.domain import CALCULATOR_VERSION, RULE_VERSION, calendar_bounds


@dataclass(frozen=True, slots=True)
class EligibleGroupRun:
    display_name: str
    started_at: datetime
    distance_m: int


@dataclass(frozen=True, slots=True)
class MonthlyFacts:
    calculator_version: str
    rule_version: str
    distance_m: int
    run_count: int
    members: int
    most_distance: str | None
    longest_run: str | None
    consistency: str | None
    pair_runs: int
    goal_distance_m: int | None

    def as_json(self) -> dict[str, object]:
        return {
            "calculator_version": self.calculator_version,
            "rule_version": self.rule_version,
            "distance_m": self.distance_m,
            "run_count": self.run_count,
            "members": self.members,
            "most_distance": self.most_distance,
            "longest_run": self.longest_run,
            "consistency": self.consistency,
            "pair_runs": self.pair_runs,
            "goal_distance_m": self.goal_distance_m,
        }


def calculate_monthly_facts(
    runs: tuple[EligibleGroupRun, ...], *, timezone: str, goal_distance_m: int | None
) -> MonthlyFacts:
    distance_by_name: dict[str, int] = defaultdict(int)
    days_by_name: dict[str, set[object]] = defaultdict(set)
    names_by_day: dict[object, set[str]] = defaultdict(set)
    zone = ZoneInfo(timezone)
    for run in runs:
        local_day = run.started_at.astimezone(zone).date()
        distance_by_name[run.display_name] += run.distance_m
        days_by_name[run.display_name].add(local_day)
        names_by_day[local_day].add(run.display_name)
    most_distance = _winner(distance_by_name)
    longest_run = None
    if runs:
        longest = sorted(runs, key=lambda item: (-item.distance_m, item.display_name))[0]
        longest_run = longest.display_name
    consistency = _winner({name: len(days) for name, days in days_by_name.items()})
    return MonthlyFacts(
        calculator_version=CALCULATOR_VERSION,
        rule_version=RULE_VERSION,
        distance_m=sum(run.distance_m for run in runs),
        run_count=len(runs),
        members=len(distance_by_name),
        most_distance=most_distance,
        longest_run=longest_run,
        consistency=consistency,
        pair_runs=sum(len(names) >= 2 for names in names_by_day.values()),
        goal_distance_m=goal_distance_m,
    )


def month_bounds(moment: datetime, timezone: str) -> tuple[datetime, datetime]:
    return calendar_bounds(moment, timezone, month=True)


def _winner(values: dict[str, int]) -> str | None:
    if not values:
        return None
    return sorted(values, key=lambda name: (-values[name], name))[0]
