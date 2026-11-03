"""Immutable finite scenarios; failed/blocked outcomes have no invented metrics."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchResult

SENSITIVITY_RULE = "matched_sensitivity_v1"
ACCOUNT_FRAMES = ("equity_curve", "fills", "orders", "settlements", "signals", "episodes",
                  "corporate_actions", "terminal_events")


@dataclass(frozen=True)
class SensitivityScenario:
    min_commission: float
    slippage_bps: float
    fill_fraction: float

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("scenario assumptions must be finite numbers")
            object.__setattr__(self, name, float(value))
        if self.min_commission < 0 or self.slippage_bps < 0 or not 0 < self.fill_fraction <= 1:
            raise ValueError("invalid sensitivity cost or fill assumption")

    @property
    def scenario_id(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class SensitivityOutcome:
    scenario: SensitivityScenario
    strategy: str
    status: str
    reason: str
    summaries_json: str = "{}"

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "blocked", "failed"}:
            raise ValueError("invalid sensitivity outcome status")
        if (self.status == "succeeded") != (not self.reason):
            raise ValueError("unsuccessful sensitivity outcome requires a reason")
        values = json.loads(self.summaries_json)
        if not isinstance(values, dict):
            raise TypeError("sensitivity summaries must be a finite JSON object")
        json.dumps(values, allow_nan=False)
        if self.status != "succeeded" and values:
            raise ValueError("unavailable sensitivity outcome cannot contain metrics")

    @property
    def prefix(self) -> str:
        return f"scenario_{self.scenario.scenario_id}_{self.strategy}"

    def to_dict(self) -> dict:
        summaries = json.loads(self.summaries_json)
        return {"scenario_id": self.scenario.scenario_id, **asdict(self.scenario), "period": "validation",
                "strategy": self.strategy, "status": self.status, "reason": self.reason,
                "summaries": summaries, "undefined_metrics": sorted(key for key, value in summaries.items() if value is None)}


@dataclass(frozen=True)
class MatchedSensitivity:
    scenarios: tuple[SensitivityScenario, ...]
    strategies: tuple[str, ...]
    outcomes: tuple[SensitivityOutcome, ...]
    accounts: dict[tuple[str, str], OddLotResearchResult]

    def __post_init__(self) -> None:
        if (not self.scenarios or len({row.scenario_id for row in self.scenarios}) != len(self.scenarios)
                or len(set(self.strategies)) != 3 or not {"ensemble", "momentum"}.issubset(self.strategies)
                or not all(name in {"ensemble", "momentum"} or re.fullmatch(
                    r"\d{4,6}\.TW_tradable_buy_hold_proxy", name) for name in self.strategies)):
            raise ValueError("invalid matched sensitivity scenario/strategy set")
        expected = [(row.scenario_id, strategy) for row in self.scenarios for strategy in self.strategies]
        keys = [(row.scenario.scenario_id, row.strategy) for row in self.outcomes]
        successful = {key for key, row in zip(keys, self.outcomes) if row.status == "succeeded"}
        if keys != expected or set(self.accounts) != successful:
            raise ValueError("matched sensitivity outcomes/accounts do not cover the declared grid")

    @property
    def status(self) -> str:
        return next((state for state in ("failed", "blocked") if any(row.status == state for row in self.outcomes)), "succeeded")

    def to_dict(self) -> dict:
        return {"rule_version": SENSITIVITY_RULE, "period": "validation", "status": self.status,
                "scenarios": [{"scenario_id": row.scenario_id, **asdict(row)} for row in self.scenarios],
                "strategies": list(self.strategies), "outcomes": [row.to_dict() for row in self.outcomes],
                "limitations": ["Validation sensitivity is diagnostic, not automatic parameter selection.",
                    "ETF tax/price-band rules remain the explicit BenchmarkSpec assumptions.",
                    "Undefined summary metrics are null and named; no cost-free reference is ranked here."]}
