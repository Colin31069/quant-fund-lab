from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .analytics import metric_frame
from .backtest import BacktestResult, run_backtest
from .config import BacktestConfig
from .data import MarketData


@dataclass(frozen=True)
class ReplayComparison:
    backtest: BacktestResult
    paper_replay: BacktestResult
    metrics: pd.DataFrame
    split_date: pd.Timestamp


def historical_vs_paper_replay(
    data: MarketData,
    config: BacktestConfig,
    train_fraction: float = 0.70,
) -> ReplayComparison:
    """Reset capital at the split and replay the unseen tail with the same execution engine."""

    if not (0.55 <= train_fraction <= 0.90):
        raise ValueError("train_fraction must be between 0.55 and 0.90")
    warmup = config.strategy.warmup_days
    split = int(len(data.close) * train_fraction)
    if split <= warmup + 2 or len(data.close) - split < 20:
        raise ValueError("not enough data for both backtest and paper replay")

    backtest_data = MarketData(
        open=data.open.iloc[:split],
        close=data.close.iloc[:split],
        volume=data.volume.iloc[:split],
        reference=data.reference.iloc[:split] if data.reference is not None else None,
        exchange=data.exchange,
    )
    paper_start = max(0, split - warmup)
    paper_data = MarketData(
        open=data.open.iloc[paper_start:],
        close=data.close.iloc[paper_start:],
        volume=data.volume.iloc[paper_start:],
        reference=data.reference.iloc[paper_start:] if data.reference is not None else None,
        exchange=data.exchange,
    )
    backtest = run_backtest(backtest_data, config)
    paper = run_backtest(paper_data, config)
    metrics = metric_frame(
        {
            "historical_backtest": backtest.equity_curve["equity"],
            "paper_replay": paper.equity_curve["equity"],
        }
    )
    return ReplayComparison(
        backtest=backtest,
        paper_replay=paper,
        metrics=metrics,
        split_date=pd.Timestamp(data.close.index[split]),
    )
