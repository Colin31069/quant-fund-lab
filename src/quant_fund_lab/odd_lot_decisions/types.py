"""Finite research decision inputs; executable thresholds must be frozen before evaluation."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

DECISION_RULE = "development_then_validation_v1"
STRATEGIES = ("ensemble", "momentum")


def _digest(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("decision identities require full SHA-256 values")


def finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class DecisionPolicy:
    development_objective: str
    maximum_validation_drawdown: float
    minimum_validation_annual_return: float
    minimum_sensitivity_total_return: float
    maximum_sensitivity_drawdown: float
    minimum_completed_trades: int = 30
    require_benchmark_outperformance: bool = True
    maximum_loss_to_budget_ratio: float | None = None
    maximum_stop_delay_sessions: int | None = None
    tie_break: str = "candidate_id_then_strategy_ascending"
    rule_version: str = DECISION_RULE

    def __post_init__(self) -> None:
        if (self.development_objective not in {"calmar", "sharpe", "annual_return"}
                or self.tie_break != "candidate_id_then_strategy_ascending" or self.rule_version != DECISION_RULE):
            raise ValueError("unsupported executable decision rule")
        for name in ("maximum_validation_drawdown", "minimum_validation_annual_return",
                     "minimum_sensitivity_total_return", "maximum_sensitivity_drawdown"):
            if not finite_number(getattr(self, name)):
                raise ValueError("decision thresholds must be explicit finite numbers")
            object.__setattr__(self, name, float(getattr(self, name)))
        if not 0 <= self.maximum_validation_drawdown <= 1 or not 0 <= self.maximum_sensitivity_drawdown <= 1:
            raise ValueError("drawdown bounds must be between zero and one")
        if type(self.minimum_completed_trades) is not int or self.minimum_completed_trades < 30:
            raise ValueError("decision policy requires at least 30 completed episodes")
        if type(self.require_benchmark_outperformance) is not bool:
            raise TypeError("benchmark rule must be an explicit boolean")
        if self.maximum_loss_to_budget_ratio is not None:
            if not finite_number(self.maximum_loss_to_budget_ratio) or self.maximum_loss_to_budget_ratio < 0:
                raise ValueError("invalid loss-to-budget bound")
            object.__setattr__(self, "maximum_loss_to_budget_ratio", float(self.maximum_loss_to_budget_ratio))
        if self.maximum_stop_delay_sessions is not None and (
            type(self.maximum_stop_delay_sessions) is not int or self.maximum_stop_delay_sessions < 0
        ):
            raise ValueError("stop delay bound must be a nonnegative integer")


@dataclass(frozen=True)
class PeriodEvidence:
    status: str
    reason: str = ""
    completed_episodes: int | None = None
    annual_return: float | None = None
    total_return: float | None = None
    max_drawdown: float | None = None
    annual_volatility: float | None = None
    sharpe: float | None = None
    calmar: float | None = None
    risk_evidence_complete: bool = False
    maximum_loss_to_budget_ratio: float | None = None
    maximum_stop_delay_sessions: int | None = None
    pending_stop_episodes: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {"available", "blocked", "failed", "unavailable"}:
            raise ValueError("invalid decision evidence status")
        if self.status != "available" and not self.reason.strip():
            raise ValueError("missing decision evidence needs a reason")
        for name in ("completed_episodes", "maximum_stop_delay_sessions", "pending_stop_episodes"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("episode and session counts must be nonnegative integers")
        for name in ("annual_return", "total_return", "max_drawdown", "annual_volatility", "sharpe", "calmar",
                     "maximum_loss_to_budget_ratio"):
            value = getattr(self, name)
            if value is not None and not finite_number(value):
                raise ValueError("unavailable decision metrics must be null, never NaN/Inf")
        if self.max_drawdown is not None and not -1 <= self.max_drawdown <= 0:
            raise ValueError("observed drawdown must be a negative return or zero")
        if type(self.risk_evidence_complete) is not bool:
            raise TypeError("risk evidence completeness must be boolean")
        if any(value is not None and value < 0 for value in (self.annual_volatility, self.maximum_loss_to_budget_ratio)):
            raise ValueError("volatility and loss ratios cannot be negative")
        metrics = [value for name, value in asdict(self).items() if name not in {"status", "reason", "risk_evidence_complete"}]
        if self.status != "available" and (any(value is not None for value in metrics) or self.risk_evidence_complete):
            raise ValueError("unavailable decision evidence cannot contain invented metrics")


@dataclass(frozen=True)
class CandidateBudget:
    candidate_id: str
    scenario_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.candidate_id)
        if not isinstance(self.scenario_ids, tuple) or not self.scenario_ids or len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("decision scenario budget must be finite, nonempty and immutable")
        for value in self.scenario_ids:
            _digest(value)


@dataclass(frozen=True)
class ScenarioEvidence:
    scenario_id: str
    result: PeriodEvidence

    def __post_init__(self) -> None:
        _digest(self.scenario_id)
        if not isinstance(self.result, PeriodEvidence):
            raise TypeError("scenario result requires typed period evidence")


@dataclass(frozen=True)
class CandidateEvidence:
    candidate_id: str
    strategy: str
    development: PeriodEvidence
    validation: PeriodEvidence
    validation_benchmark: PeriodEvidence
    sensitivity: tuple[ScenarioEvidence, ...]
    source_fingerprint: str

    def __post_init__(self) -> None:
        _digest(self.candidate_id)
        _digest(self.source_fingerprint)
        if self.strategy not in STRATEGIES or not isinstance(self.sensitivity, tuple):
            raise ValueError("invalid decision strategy or mutable scenario evidence")
        if not all(isinstance(value, PeriodEvidence) for value in (self.development, self.validation, self.validation_benchmark)):
            raise TypeError("candidate requires typed period evidence")
        if len({row.scenario_id for row in self.sensitivity}) != len(self.sensitivity):
            raise ValueError("duplicate decision scenario evidence")


@dataclass(frozen=True)
class DecisionCheck:
    gate: str
    status: str
    observed: float | int | None
    bound: float | int | None
    reason: str

    def __post_init__(self) -> None:
        if self.status not in {"passed", "failed", "unavailable", "insufficient_sample"} or not self.gate or not self.reason:
            raise ValueError("invalid decision gate result")
        if any(value is not None and not finite_number(value) for value in (self.observed, self.bound)):
            raise ValueError("decision gate values must be finite or null")


@dataclass(frozen=True)
class CandidateDecision:
    candidate_id: str
    strategy: str
    status: str
    development_score: float | None
    reasons: tuple[str, ...]
    checks: tuple[DecisionCheck, ...] = ()

    def __post_init__(self) -> None:
        _digest(self.candidate_id)
        if self.strategy not in STRATEGIES or self.status not in {
            "eligible", "unavailable", "insufficient_sample", "not_selected", "return", "continue",
        } or not self.reasons:
            raise ValueError("invalid candidate decision")
        if self.development_score is not None and not finite_number(self.development_score):
            raise ValueError("development score must be finite or null")
        if self.status in {"eligible", "not_selected", "return", "continue"} and self.development_score is None:
            raise ValueError("ranked candidate requires an observed development score")


@dataclass(frozen=True)
class ResearchDecision:
    protocol_id: str
    policy: DecisionPolicy
    status: str
    selected_candidate: str | None
    selected_strategy: str | None
    candidates: tuple[CandidateDecision, ...]
    evidence_fingerprint: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.protocol_id)
        _digest(self.evidence_fingerprint)
        if self.status not in {"incomplete_search", "insufficient_sample", "unavailable", "return", "continue"}:
            raise ValueError("invalid research decision status")
        if (self.selected_candidate is None) != (self.selected_strategy is None):
            raise ValueError("selection requires both candidate and strategy")
        if self.selected_candidate is None:
            if self.status not in {"incomplete_search", "insufficient_sample"}:
                raise ValueError("decision requires a development-selected candidate")
        elif not any(row.candidate_id == self.selected_candidate and row.strategy == self.selected_strategy
                     and row.status == self.status for row in self.candidates):
            raise ValueError("selected decision is absent from candidate audit")

    def to_dict(self) -> dict:
        return {"rule_version": DECISION_RULE, **asdict(self),
                "limitations": ["Development alone determines ranking; validation never chooses a replacement.",
                    "Continue means continue research/observation, not evidence of strategy effectiveness.",
                    "This pure evaluator does not authenticate sources or independently prove preregistration."]}

    @property
    def decision_id(self) -> str:
        return fingerprint(self.to_dict())
