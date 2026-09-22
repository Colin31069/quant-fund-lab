from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .backtest import BacktestResult
from .config import BacktestConfig, MarketCostConfig
from .data import MarketData
from .paper import historical_vs_paper_replay


@dataclass(frozen=True)
class RobustnessResult:
    cost_stress: pd.DataFrame
    bootstrap_distribution: pd.DataFrame
    bootstrap_summary: pd.DataFrame
    regime_attribution: pd.DataFrame


def _stress_market_costs(costs: MarketCostConfig, multiplier: float) -> MarketCostConfig:
    if multiplier <= 0.0:
        raise ValueError("cost multiplier must be positive")
    return replace(
        costs,
        commission_bps=costs.commission_bps * multiplier,
        slippage_bps=costs.slippage_bps * multiplier,
        impact_coefficient=costs.impact_coefficient * multiplier,
    )


def stress_execution_costs(config: BacktestConfig, multiplier: float) -> BacktestConfig:
    """Stress broker/modelled execution costs while leaving statutory taxes/fees unchanged."""

    return replace(
        config,
        us_costs=_stress_market_costs(config.us_costs, multiplier),
        tw_costs=_stress_market_costs(config.tw_costs, multiplier),
    )


def run_paper_cost_stress(
    data: MarketData,
    config: BacktestConfig,
    train_fraction: float,
    multipliers: tuple[float, ...] = (1.0, 1.5, 2.0),
    baseline_paper_result: BacktestResult | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for multiplier in sorted({float(value) for value in multipliers}):
        stressed = stress_execution_costs(config, multiplier)
        if abs(multiplier - 1.0) < 1e-12 and baseline_paper_result is not None:
            paper = baseline_paper_result
        else:
            paper = historical_vs_paper_replay(
                data, stressed, train_fraction=train_fraction
            ).paper_replay
        metrics = performance_metrics(paper.equity_curve["equity"])
        costs = paper.cost_attribution
        rows.append(
            {
                "cost_multiplier": multiplier,
                **metrics,
                "fees": float(costs["fees"].sum()) if not costs.empty else 0.0,
                "slippage_cost": (
                    float(costs["slippage_cost"].sum()) if not costs.empty else 0.0
                ),
                "turnover": (
                    float(costs["turnover_rate"].sum()) if not costs.empty else 0.0
                ),
            }
        )
    return pd.DataFrame(rows).set_index("cost_multiplier").sort_index()


def block_bootstrap_performance(
    equity: pd.Series,
    iterations: int = 500,
    block_length: int = 10,
    seed: int = 17,
) -> pd.DataFrame:
    """Circular block bootstrap preserving short-range return dependence."""

    returns = equity.dropna().astype(float).pct_change().dropna().to_numpy(dtype=float)
    if len(returns) < 20:
        raise ValueError("at least 20 returns are required for bootstrap robustness")
    if iterations < 1 or block_length < 1:
        raise ValueError("iterations and block_length must be positive")
    rng = np.random.default_rng(seed)
    n = len(returns)
    rows: list[dict[str, float]] = []
    for iteration in range(iterations):
        sampled: list[float] = []
        while len(sampled) < n:
            start = int(rng.integers(0, n))
            indices = (start + np.arange(block_length)) % n
            sampled.extend(returns[indices].tolist())
        path_returns = np.asarray(sampled[:n], dtype=float)
        path = pd.Series(
            np.concatenate([[1.0], np.cumprod(1.0 + path_returns)]), dtype=float
        )
        rows.append({"iteration": float(iteration), **performance_metrics(path)})
    return pd.DataFrame(rows).set_index("iteration")


def summarize_bootstrap_distribution(distribution: pd.DataFrame) -> pd.DataFrame:
    if distribution.empty:
        return pd.DataFrame(columns=["p05", "median", "p95"])
    rows: dict[str, dict[str, float]] = {}
    for column in distribution.columns:
        values = distribution[column].dropna()
        rows[column] = {
            "p05": float(values.quantile(0.05)),
            "median": float(values.quantile(0.50)),
            "p95": float(values.quantile(0.95)),
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def regime_return_attribution(result: BacktestResult) -> pd.DataFrame:
    """Attribute realized daily strategy returns to the latest known rebalance regime."""

    returns = result.equity_curve["equity"].pct_change().dropna()
    if returns.empty or result.regimes.empty:
        return pd.DataFrame(
            columns=[
                "days",
                "mean_daily_return",
                "annualized_volatility",
                "sharpe",
                "hit_rate",
                "log_return_contribution",
            ]
        )
    labels = result.regimes["label"].reindex(returns.index, method="ffill")
    aligned = pd.DataFrame({"return": returns, "regime": labels}).dropna()
    rows: list[dict[str, object]] = []
    for label, group in aligned.groupby("regime"):
        series = group["return"].astype(float)
        volatility = float(series.std(ddof=1) * np.sqrt(252.0)) if len(series) > 1 else 0.0
        sharpe = (
            float(series.mean() / series.std(ddof=1) * np.sqrt(252.0))
            if len(series) > 1 and float(series.std(ddof=1)) > 0.0
            else 0.0
        )
        rows.append(
            {
                "regime": str(label),
                "days": len(series),
                "mean_daily_return": float(series.mean()),
                "annualized_volatility": volatility,
                "sharpe": sharpe,
                "hit_rate": float((series > 0.0).mean()),
                "log_return_contribution": float(np.log1p(series).sum()),
            }
        )
    return pd.DataFrame(rows).set_index("regime").sort_index()


def build_robustness_report(
    data: MarketData,
    config: BacktestConfig,
    train_fraction: float,
    baseline_paper_result: BacktestResult,
    cost_multipliers: tuple[float, ...] = (1.0, 1.5, 2.0),
    bootstrap_iterations: int = 300,
    block_length: int = 10,
    seed: int = 17,
) -> RobustnessResult:
    cost_stress = run_paper_cost_stress(
        data,
        config,
        train_fraction,
        multipliers=cost_multipliers,
        baseline_paper_result=baseline_paper_result,
    )
    distribution = block_bootstrap_performance(
        baseline_paper_result.equity_curve["equity"],
        iterations=bootstrap_iterations,
        block_length=block_length,
        seed=seed,
    )
    return RobustnessResult(
        cost_stress=cost_stress,
        bootstrap_distribution=distribution,
        bootstrap_summary=summarize_bootstrap_distribution(distribution),
        regime_attribution=regime_return_attribution(baseline_paper_result),
    )
