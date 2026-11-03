"""Single-ETF tradable buy-and-hold benchmark using the shared odd-lot account engine."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields, replace

import pandas as pd

from .config import BacktestConfig
from .data import MarketData
from .odd_lot_execution import validate_instrument_rules
from .odd_lot_research import OddLotResearchConfig, OddLotResearchResult, run_odd_lot_research


@dataclass(frozen=True)
class BenchmarkSpec:
    """Declared benchmark assumptions, not certification of historical market rules."""

    symbol: str
    initial_cash: float
    sell_tax_bps: float
    price_limit_pct: float | None
    rule_note: str
    kind: str = "etf"
    entry_policy: str = "one_initial_close_signal_next_open_expire_v1"
    dividend_policy: str = "retain_cash_no_reinvestment"
    settlement_policy: str = "observed_market_sessions_as_t_plus_2_proxy_credit_after_open"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4,6}\.TW", self.symbol):
            raise ValueError("benchmark requires a canonical TWSE ETF symbol")
        if (isinstance(self.initial_cash, bool) or not math.isfinite(self.initial_cash)
                or self.initial_cash <= 0 or not self.rule_note.strip()):
            raise ValueError("benchmark requires positive initial cash and an explicit rule note")
        if (type(self.schema_version) is not int or self.schema_version != 1 or self.kind != "etf"
                or self.entry_policy != "one_initial_close_signal_next_open_expire_v1"
                or self.dividend_policy != "retain_cash_no_reinvestment"
                or self.settlement_policy != "observed_market_sessions_as_t_plus_2_proxy_credit_after_open"):
            raise ValueError("unsupported benchmark execution policy")
        validate_instrument_rules([self.symbol], {self.symbol: self.instrument_rule})

    @property
    def instrument_rule(self) -> dict:
        return {"kind": self.kind, "sell_tax_bps": self.sell_tax_bps,
                "price_limit_pct": self.price_limit_pct}

    @property
    def result_name(self) -> str:
        return f"{self.symbol}_tradable_buy_hold_proxy"


def run_tradable_benchmark(
    data: MarketData, spec: BenchmarkSpec, research: OddLotResearchConfig,
    base_config: BacktestConfig, *, start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> OddLotResearchResult:
    """Submit one passive ETF entry and reuse all matching, cash and action accounting.

    Order sizing uses the initial close; at most 999 shares are requested once.
    Unfilled shares expire, dividends stay cash, and no stop or model exit is added.
    The study's multi-asset guard is unchanged; this is a distinct benchmark API.
    """
    if base_config.initial_cash != spec.initial_cash:
        raise ValueError("benchmark and strategy initial cash must match")
    if spec.symbol not in data.symbols:
        raise ValueError("benchmark symbol is missing from verified study inputs")
    panels = {field.name: getattr(data, field.name).loc[:, [spec.symbol]]
              for field in fields(data) if isinstance(getattr(data, field.name), pd.DataFrame)}
    single = replace(data, **panels)
    passive = replace(research, strategy="equal_weight", max_positions=1, max_weight=1.0,
                      instrument_rules={spec.symbol: spec.instrument_rule})
    return run_odd_lot_research(single, passive, base_config, start=start, end=end,
                               _passive_without_risk_estimate=True)
