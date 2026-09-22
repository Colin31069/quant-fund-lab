from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from itertools import product

import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .backtest import run_backtest
from .config import BacktestConfig, StrategyConfig
from .data import MarketData


@dataclass(frozen=True)
class WalkForwardSpec:
    train_bars: int = 252
    validation_bars: int = 84
    test_bars: int = 84
    step_bars: int | None = None
    expanding: bool = True
    objective: str = "calmar"
    max_validation_drawdown: float | None = 0.35

    def __post_init__(self) -> None:
        if min(self.train_bars, self.validation_bars, self.test_bars) < 2:
            raise ValueError("walk-forward windows must each contain at least two bars")
        step = self.test_bars if self.step_bars is None else self.step_bars
        if step < self.test_bars:
            raise ValueError("step_bars must be >= test_bars to prevent overlapping OOS tests")
        if self.objective not in {"calmar", "sharpe", "annual_return"}:
            raise ValueError("objective must be calmar, sharpe, or annual_return")
        if self.max_validation_drawdown is not None and not (
            0.0 < self.max_validation_drawdown <= 1.0
        ):
            raise ValueError("max_validation_drawdown must be in (0, 1]")


@dataclass(frozen=True)
class WalkForwardResult:
    folds: pd.DataFrame
    candidate_scores: pd.DataFrame
    oos_equity: pd.Series
    oos_metrics: dict[str, float]


def strategy_candidate_id(strategy: StrategyConfig) -> str:
    payload = json.dumps(asdict(strategy), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def generate_candidate_grid(
    base: StrategyConfig,
    risk_aversion: Iterable[float] = (2.0, 4.0, 8.0),
    covariance_shrinkage: Iterable[float] = (0.20, 0.50),
    rebalance_every: Iterable[int] = (5, 10),
) -> list[StrategyConfig]:
    candidates = {
        strategy_candidate_id(candidate): candidate
        for risk, shrinkage, rebalance in product(
            risk_aversion, covariance_shrinkage, rebalance_every
        )
        for candidate in [
            replace(
                base,
                risk_aversion=float(risk),
                covariance_shrinkage=float(shrinkage),
                rebalance_every=int(rebalance),
            )
        ]
    }
    return [candidates[key] for key in sorted(candidates)]


def _score_validation(
    equity: pd.Series,
    turnover: float,
    candidate_id: str,
    spec: WalkForwardSpec,
) -> tuple[float, dict[str, float]]:
    if len(equity.dropna()) < 2:
        metrics = {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
        }
        return float("-inf"), metrics
    metrics = performance_metrics(equity)
    if (
        spec.max_validation_drawdown is not None
        and abs(metrics["max_drawdown"]) > spec.max_validation_drawdown
    ):
        return float("-inf"), metrics
    score = float(metrics[spec.objective])
    if not np.isfinite(score):
        score = float("-inf")
    # Determinism for exact metric ties is handled by candidate_id ordering in selection.
    _ = turnover, candidate_id
    return score, metrics


def _slice_by_positions(data: MarketData, start: int, end_exclusive: int) -> MarketData:
    if start < 0 or end_exclusive > len(data.close) or start >= end_exclusive:
        raise ValueError("invalid walk-forward slice")
    return data.slice(data.close.index[start], data.close.index[end_exclusive - 1])


def run_walk_forward(
    data: MarketData,
    base_config: BacktestConfig,
    candidates: Iterable[StrategyConfig],
    spec: WalkForwardSpec | None = None,
) -> WalkForwardResult:
    spec = spec or WalkForwardSpec()
    candidate_map = {strategy_candidate_id(candidate): candidate for candidate in candidates}
    if not candidate_map:
        raise ValueError("at least one strategy candidate is required")
    max_warmup = max(candidate.warmup_days for candidate in candidate_map.values())
    if spec.train_bars < max_warmup + 2:
        raise ValueError("train_bars must exceed the largest candidate warmup_days")

    index = data.close.index
    step = spec.test_bars if spec.step_bars is None else spec.step_bars
    validation_start = spec.train_bars
    fold_rows: list[dict[str, object]] = []
    score_rows: list[dict[str, object]] = []
    oos_values: list[float] = []
    oos_dates: list[pd.Timestamp] = []
    chained_level = float(base_config.initial_cash)
    first_baseline_added = False
    fold_number = 0

    while validation_start + spec.validation_bars + spec.test_bars <= len(index):
        validation_end = validation_start + spec.validation_bars
        test_start = validation_end
        test_end = test_start + spec.test_bars
        train_start = 0 if spec.expanding else validation_start - spec.train_bars
        train_end = validation_start

        ranked: list[tuple[float, str, StrategyConfig, dict[str, float], float]] = []
        for candidate_id in sorted(candidate_map):
            candidate = candidate_map[candidate_id]
            candidate_config = replace(base_config, strategy=candidate)
            calibration_data = _slice_by_positions(data, train_start, validation_end)
            calibration = run_backtest(calibration_data, candidate_config)
            validation_baseline = index[validation_start - 1]
            validation_equity = calibration.equity_curve["equity"].loc[
                validation_baseline : index[validation_end - 1]
            ]
            validation_turnover = float(
                calibration.cost_attribution["turnover_rate"]
                .loc[index[validation_start] : index[validation_end - 1]]
                .sum()
                if not calibration.cost_attribution.empty
                else 0.0
            )
            score, metrics = _score_validation(
                validation_equity, validation_turnover, candidate_id, spec
            )
            ranked.append((score, candidate_id, candidate, metrics, validation_turnover))
            score_rows.append(
                {
                    "fold": fold_number,
                    "candidate_id": candidate_id,
                    "validation_score": score,
                    "validation_turnover": validation_turnover,
                    **{f"validation_{key}": value for key, value in metrics.items()},
                }
            )

        ranked.sort(key=lambda item: (-item[0], item[1]))
        best_score, best_id, best_strategy, best_metrics, _ = ranked[0]
        if not np.isfinite(best_score):
            raise ValueError(f"all candidates failed validation constraints in fold {fold_number}")

        context_start = max(0, test_start - best_strategy.warmup_days)
        if test_start - context_start < best_strategy.warmup_days:
            raise ValueError("not enough warm-up history before OOS test")
        test_data = _slice_by_positions(data, context_start, test_end)
        test_config = replace(base_config, strategy=best_strategy)
        test_result = run_backtest(test_data, test_config)
        baseline_date = index[test_start - 1]
        test_equity = test_result.equity_curve["equity"].loc[
            baseline_date : index[test_end - 1]
        ]
        test_returns = test_equity.pct_change().dropna().loc[
            index[test_start] : index[test_end - 1]
        ]
        if len(test_returns) != spec.test_bars:
            raise ValueError("OOS test return count does not match the requested test window")

        if not first_baseline_added:
            oos_dates.append(pd.Timestamp(baseline_date))
            oos_values.append(chained_level)
            first_baseline_added = True
        for timestamp, daily_return in test_returns.items():
            chained_level *= 1.0 + float(daily_return)
            oos_dates.append(pd.Timestamp(timestamp))
            oos_values.append(chained_level)

        test_curve = pd.Series(
            [float(base_config.initial_cash)]
            + list(
                float(base_config.initial_cash)
                * (1.0 + test_returns).cumprod().to_numpy(dtype=float)
            ),
            index=pd.DatetimeIndex([baseline_date, *test_returns.index]),
            dtype=float,
        )
        test_metrics = performance_metrics(test_curve)
        fold_rows.append(
            {
                "fold": fold_number,
                "train_start": index[train_start],
                "train_end": index[train_end - 1],
                "validation_start": index[validation_start],
                "validation_end": index[validation_end - 1],
                "test_start": index[test_start],
                "test_end": index[test_end - 1],
                "selected_candidate_id": best_id,
                "validation_score": best_score,
                "validation_calmar": best_metrics["calmar"],
                "validation_sharpe": best_metrics["sharpe"],
                "risk_aversion": best_strategy.risk_aversion,
                "covariance_shrinkage": best_strategy.covariance_shrinkage,
                "rebalance_every": best_strategy.rebalance_every,
                "test_total_return": test_metrics["total_return"],
                "test_sharpe": test_metrics["sharpe"],
                "test_max_drawdown": test_metrics["max_drawdown"],
                "test_calmar": test_metrics["calmar"],
            }
        )

        fold_number += 1
        validation_start += step

    if not fold_rows:
        raise ValueError("not enough observations for one complete walk-forward fold")
    oos_equity = pd.Series(oos_values, index=pd.DatetimeIndex(oos_dates), name="oos_equity")
    if oos_equity.index.has_duplicates:
        raise ValueError("walk-forward OOS windows overlap")
    return WalkForwardResult(
        folds=pd.DataFrame(fold_rows).set_index("fold"),
        candidate_scores=pd.DataFrame(score_rows),
        oos_equity=oos_equity,
        oos_metrics=performance_metrics(oos_equity),
    )
