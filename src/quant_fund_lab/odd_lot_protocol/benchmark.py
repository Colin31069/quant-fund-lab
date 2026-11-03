"""Run a protocol-declared benchmark only within the already-verified study periods."""
from __future__ import annotations

from dataclasses import asdict, replace

import pandas as pd

from ..data import MarketData
from ..odd_lot_benchmarks import BenchmarkSpec, run_tradable_benchmark
from ..odd_lot_research import OddLotResearchConfig
from ..odd_lot_study import OddLotStudyResult, _backtest_config
from ..twse_odd_lot import _total_return
from .types import json_object


def benchmark_from_plan(plan_json: str) -> BenchmarkSpec | None:
    plan = json_object(plan_json)
    value = plan.get("tradable_benchmark")
    if plan.get("engine") == "frozen_odd_lot_batch_v1" and value == "not_yet_implemented":
        return None
    if plan.get("engine") in {f"frozen_odd_lot_batch_v{version}" for version in range(2, 7)} and isinstance(value, dict):
        return BenchmarkSpec(**value)
    raise ValueError("unsupported protocol benchmark plan")


def add_tradable_benchmarks(
    data: MarketData, metadata: dict, study: OddLotStudyResult, spec: BenchmarkSpec,
) -> OddLotStudyResult:
    """Attach same-cost ETF results; preserve blocked periods without computing them."""
    base = _backtest_config(metadata["backtest_config"])
    if spec.symbol != metadata["benchmark"] or spec.initial_cash != base.initial_cash:
        raise ValueError("benchmark differs from the frozen study capital or symbol")
    research = OddLotResearchConfig(**metadata["research_config"])
    results, unavailable = dict(study.results), dict(study.unavailable)
    comparison = study.comparison.copy()
    if not comparison.empty:
        comparison["comparison_basis"] = comparison["strategy"].map(
            lambda name: "no_cost_total_return_reference" if name.endswith("_no_trading_costs")
            else "strategy_with_declared_costs"
        )
    rows = []
    for period, (start, end) in metadata["periods"].items():
        decision = next(p for p in metadata["readiness"]["periods"] if p["period"] == period)
        reference = results.get((period, "equal_weight"))
        if decision["status"] != "ready" or reference is None:
            unavailable[f"{period}/tradable_benchmark"] = "required period or shared benchmark inputs are not ready"
            continue
        first = int(data.close.index.searchsorted(pd.Timestamp(start), side="left"))
        warmup = max(120, base.strategy.warmup_days)
        if first < warmup:
            raise ValueError("benchmark warmup disagrees with frozen readiness")
        window = data.slice(start=data.close.index[first - warmup], end=pd.Timestamp(end))
        adjusted = _total_return(window.raw_close, window.dividends, window.stock_splits)
        window = replace(window, close=adjusted, open=window.raw_open * adjusted.div(window.raw_close),
                         reference=adjusted.shift(1))
        benchmark = run_tradable_benchmark(window, spec, research, base, start=start, end=end)
        if not benchmark.equity_curve.index.equals(reference.equity_curve.index):
            raise ValueError("benchmark and strategy evaluation sessions differ")
        results[(period, spec.result_name)] = benchmark
        last = benchmark.equity_curve.iloc[-1]
        holdings = last["equity"] - last["cash"] - last["sale_receivables"] - last["receivable_value"]
        rows.append({"period": period, "strategy": spec.result_name,
                     "comparison_basis": "tradable_benchmark_with_same_costs",
                     **benchmark.metrics, **benchmark.trade_summary,
                     "ending_invested_fraction": holdings / last["equity"] if last["equity"] > 0 else None,
                     "ending_cash_fraction": last["cash"] / last["equity"] if last["equity"] > 0 else None})
    if rows:
        comparison = pd.concat([comparison, pd.DataFrame(rows)], ignore_index=True)
    return replace(study, comparison=comparison, results=results, unavailable=unavailable,
                   benchmark_specs={spec.symbol: asdict(spec)})
