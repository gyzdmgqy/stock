from dataclasses import dataclass
from json import dumps

from shared.enums import SignalComponent


@dataclass(frozen=True)
class RuleDetail:
    component: SignalComponent
    rule_name: str
    rule_value: str
    score: float | None
    explanation: str


@dataclass(frozen=True)
class ScoreResult:
    score: float | None
    details: tuple[RuleDetail, ...]


def check(
    component: SignalComponent,
    name: str,
    passed: bool | None,
    points: float,
    explanation: str,
) -> RuleDetail:
    granted = None if passed is None else points if passed else 0.0
    return RuleDetail(component, name, dumps(passed), granted, explanation)
