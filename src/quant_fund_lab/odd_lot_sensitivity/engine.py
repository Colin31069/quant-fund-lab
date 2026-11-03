"""Run every frozen scenario on identical strategy/ETF sessions and retain failures."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, replace

import pandas as pd

from ..analytics import performance_metrics
from ..data import MarketData
from ..odd_lot_benchmarks import BenchmarkSpec, run_tradable_benchmark
from ..odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config, run_odd_lot_research
from ..odd_lot_study import OddLotStudyResult, _backtest_config, _subset
from ..trade_analytics import summarize_episodes
from ..twse_odd_lot import _total_return
from .reporting import summary_frame
from .types import MatchedSensitivity, SensitivityOutcome, SensitivityScenario


def scenario_config(research: OddLotResearchConfig, scenario: SensitivityScenario,
                    strategy: str, benchmark: BenchmarkSpec) -> OddLotResearchConfig:
    config = replace(research, **asdict(scenario))
    if strategy == benchmark.result_name:
        return replace(config, strategy="equal_weight", max_positions=1, max_weight=1.0,
                       instrument_rules={benchmark.symbol: benchmark.instrument_rule})
    if strategy not in {"ensemble", "momentum"}:
        raise ValueError("unknown matched sensitivity strategy")
    return replace(config, strategy=strategy)


def account_summaries(curve: pd.DataFrame, fills: pd.DataFrame, orders: pd.DataFrame,
                      episodes: pd.DataFrame) -> str:
    """Summarize already-net account NAV; never deduct fees/slippage a second time."""
    last = curve.iloc[-1]
    nav = float(last.equity)
    holdings = nav - last["cash"] - last.sale_receivables - last.receivable_value
    values = {**performance_metrics(curve.equity), **summarize_episodes(episodes),
        "ending_equity": nav, "ending_cash": float(last["cash"]),
        "ending_invested_fraction": holdings / nav if nav > 0 else None,
        "ending_cash_fraction": last["cash"] / nav if nav > 0 else None,
        "ending_buy_payables": float(last.buy_payables), "ending_sale_receivables": float(last.sale_receivables),
        "ending_sale_payables": float(last.sale_payables), "ending_entitlement_value": float(last.receivable_value),
        "orders": len(orders), "filled_quantity": int(fills.get("quantity", pd.Series(dtype=float)).sum()),
        "expired_quantity": int(orders.get("expired_quantity", pd.Series(dtype=float)).sum()),
        **{name: float(fills.get(name, pd.Series(dtype=float)).sum()) for name in ("commission", "sell_tax", "slippage_cost")}}
    cleaned = {}
    for name, value in values.items():
        scalar = value.item() if hasattr(value, "item") else value
        cleaned[name] = None if isinstance(scalar, float) and not math.isfinite(scalar) else scalar
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), allow_nan=False)


def run_matched_sensitivity(data: MarketData, metadata: dict, study: OddLotStudyResult,
                            benchmark: BenchmarkSpec, scenarios: tuple[SensitivityScenario, ...]) -> OddLotStudyResult:
    """Use only the frozen validation interval; no automatic selection or backfilling."""
    research = OddLotResearchConfig(**metadata["research_config"])
    base = _backtest_config(metadata["backtest_config"])
    strategies = ("ensemble", "momentum", benchmark.result_name)
    decision = next(row for row in metadata["readiness"]["periods"] if row["period"] == "validation")
    start, end = metadata["periods"]["validation"]
    outcomes, accounts = [], {}
    window = None
    for scenario in scenarios:
        for strategy in strategies:
            reference = study.results.get(("validation", strategy))
            if decision["status"] != "ready" or reference is None:
                reason = study.unavailable.get(f"validation/{strategy}", "required validation account or inputs are not ready")
                outcomes.append(SensitivityOutcome(scenario, strategy, "blocked", reason))
                continue
            try:
                if window is None:
                    first = int(data.close.index.searchsorted(pd.Timestamp(start), side="left"))
                    warmup = max(120, base.strategy.warmup_days)
                    if first < warmup:
                        raise ValueError("sensitivity warmup disagrees with frozen readiness")
                    selected = data.slice(start=data.close.index[first - warmup], end=pd.Timestamp(end))
                    adjusted = _total_return(selected.raw_close, selected.dividends, selected.stock_splits)
                    window = replace(selected, close=adjusted, open=selected.raw_open * adjusted.div(selected.raw_close),
                                     reference=adjusted.shift(1))
                config = scenario_config(research, scenario, strategy, benchmark)
                if config == reference.config:
                    result = reference
                elif strategy == benchmark.result_name:
                    result = run_tradable_benchmark(window, benchmark, replace(research, **asdict(scenario)),
                                                    base, start=start, end=end)
                else:
                    result = run_odd_lot_research(_subset(window, metadata["symbols"]), config, base, start=start, end=end)
                if not result.equity_curve.index.equals(reference.equity_curve.index):
                    raise ValueError("sensitivity and primary account sessions differ")
                if result.config != config or result.backtest_config != odd_lot_backtest_config(base, config):
                    raise ValueError("sensitivity account configuration differs from scenario")
                summaries = account_summaries(result.equity_curve, result.fills, result.orders, result.episodes)
            except Exception as exc:  # noqa: BLE001 -- Retain the failed scenario and fail the registered attempt after exporting all outcomes.
                outcomes.append(SensitivityOutcome(scenario, strategy, "failed", f"{type(exc).__name__}: {exc}"))
                continue
            accounts[(scenario.scenario_id, strategy)] = result
            outcomes.append(SensitivityOutcome(scenario, strategy, "succeeded", "", summaries))
    matched = MatchedSensitivity(scenarios, strategies, tuple(outcomes), accounts)
    return replace(study, sensitivity=summary_frame(matched), matched_sensitivity=matched)
