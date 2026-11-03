"""Development-only semantic inputs; whole-report and lifecycle identities belong to captures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .types import STRATEGIES, DecisionPolicy, _digest, finite_number

DEVELOPMENT_RULE = "development_selection_v1"
TIE_BREAK = "candidate_id_then_strategy_ascending"


@dataclass(frozen=True)
class DevelopmentPolicy:
    development_start: str
    development_end: str
    development_objective: str
    minimum_completed_trades: int = 30
    tie_break: str = TIE_BREAK
    rule_version: str = DEVELOPMENT_RULE

    def __post_init__(self) -> None:
        for value in (self.development_start, self.development_end):
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError("development dates require canonical ISO calendar dates")
        if self.development_start > self.development_end:
            raise ValueError("development dates are reversed")
        if (self.development_objective not in {"calmar", "sharpe", "annual_return"}
                or self.tie_break != TIE_BREAK or self.rule_version != DEVELOPMENT_RULE):
            raise ValueError("unsupported development ranking policy")
        if type(self.minimum_completed_trades) is not int or self.minimum_completed_trades < 30:
            raise ValueError("development requires at least 30 completed episodes")

    @classmethod
    def from_decision_policy(cls, policy: DecisionPolicy, *, start: str, end: str) -> DevelopmentPolicy:
        """Project only ranking rules; validation thresholds never enter this identity."""
        if not isinstance(policy, DecisionPolicy):
            raise TypeError("development policy requires a typed decision policy")
        return cls(start, end, policy.development_objective, policy.minimum_completed_trades, policy.tie_break)


@dataclass(frozen=True)
class DevelopmentEvidence:
    candidate_id: str
    strategy: str
    status: str
    source_fingerprint: str
    reason: str = ""
    completed_episodes: int | None = None
    annual_return: float | None = None
    max_drawdown: float | None = None
    annual_volatility: float | None = None
    sharpe: float | None = None
    calmar: float | None = None

    def __post_init__(self) -> None:
        _digest(self.candidate_id)
        _digest(self.source_fingerprint)
        if self.strategy not in STRATEGIES or self.status not in {"available", "blocked", "failed", "unavailable"}:
            raise ValueError("unsupported development evidence")
        if not isinstance(self.reason, str) or (self.status != "available" and not self.reason.strip()):
            raise ValueError("missing development evidence requires a reason")
        if self.completed_episodes is not None and (
            type(self.completed_episodes) is not int or self.completed_episodes < 0
        ):
            raise ValueError("development episode count must be a nonnegative integer")
        metrics = ("annual_return", "max_drawdown", "annual_volatility", "sharpe", "calmar")
        for name in metrics:
            value = getattr(self, name)
            if value is not None:
                if not finite_number(value):
                    raise ValueError("development metrics require finite numbers or null")
                object.__setattr__(self, name, float(value))
        if self.max_drawdown is not None and not -1 <= self.max_drawdown <= 0:
            raise ValueError("development drawdown must be a negative return or zero")
        if self.annual_volatility is not None and self.annual_volatility < 0:
            raise ValueError("development volatility cannot be negative")
        if self.status != "available" and (
            self.completed_episodes is not None or any(getattr(self, name) is not None for name in metrics)
        ):
            raise ValueError("unavailable development evidence cannot invent metrics")


@dataclass(frozen=True)
class DevelopmentRank:
    candidate_id: str
    strategy: str
    status: str
    score: float | None
    reason: str
    rank: int | None

    def __post_init__(self) -> None:
        _digest(self.candidate_id)
        if self.strategy not in STRATEGIES or not self.reason or self.status not in {
            "eligible", "unavailable", "insufficient_sample",
        }:
            raise ValueError("invalid development rank")
        if self.status == "eligible":
            if not finite_number(self.score) or type(self.rank) is not int or self.rank < 1:
                raise ValueError("eligible development row requires finite score and rank")
        elif self.score is not None or self.rank is not None:
            raise ValueError("ineligible development row cannot be ranked")
