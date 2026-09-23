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
        raw_open=data.raw_open.iloc[:split] if data.raw_open is not None else None,
        raw_close=data.raw_close.iloc[:split] if data.raw_close is not None else None,
        reference=data.reference.iloc[:split] if data.reference is not None else None,
        membership=data.membership.iloc[:split] if data.membership is not None else None,
        terminal_returns=(
            data.terminal_returns.iloc[:split] if data.terminal_returns is not None else None
        ),
        dividends=data.dividends.iloc[:split] if data.dividends is not None else None,
        stock_splits=data.stock_splits.iloc[:split] if data.stock_splits is not None else None,
        fx_to_base=data.fx_to_base.iloc[:split] if data.fx_to_base is not None else None,
        fx_age_days=data.fx_age_days.iloc[:split] if data.fx_age_days is not None else None,
        market_codes=data.market_codes.iloc[:split] if data.market_codes is not None else None,
        currency_codes=(
            data.currency_codes.iloc[:split] if data.currency_codes is not None else None
        ),
        base_currency=data.base_currency,
        exchange=data.exchange,
    )
    paper_start = max(0, split - warmup)
    paper_data = MarketData(
        open=data.open.iloc[paper_start:],
        close=data.close.iloc[paper_start:],
        volume=data.volume.iloc[paper_start:],
        raw_open=data.raw_open.iloc[paper_start:] if data.raw_open is not None else None,
        raw_close=data.raw_close.iloc[paper_start:] if data.raw_close is not None else None,
        reference=data.reference.iloc[paper_start:] if data.reference is not None else None,
        membership=data.membership.iloc[paper_start:] if data.membership is not None else None,
        terminal_returns=(
            data.terminal_returns.iloc[paper_start:] if data.terminal_returns is not None else None
        ),
        dividends=data.dividends.iloc[paper_start:] if data.dividends is not None else None,
        stock_splits=(
            data.stock_splits.iloc[paper_start:] if data.stock_splits is not None else None
        ),
        fx_to_base=data.fx_to_base.iloc[paper_start:] if data.fx_to_base is not None else None,
        fx_age_days=data.fx_age_days.iloc[paper_start:] if data.fx_age_days is not None else None,
        market_codes=(
            data.market_codes.iloc[paper_start:] if data.market_codes is not None else None
        ),
        currency_codes=(
            data.currency_codes.iloc[paper_start:] if data.currency_codes is not None else None
        ),
        base_currency=data.base_currency,
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
