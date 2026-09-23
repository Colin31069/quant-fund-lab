from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import MarketData
from .fundamentals import FundamentalDataset


@dataclass(frozen=True)
class MarketCapEstimate:
    reported_shares: pd.DataFrame
    effective_shares: pd.DataFrame
    local_market_cap: pd.DataFrame
    base_market_cap: pd.DataFrame


def split_adjusted_reported_shares(
    reported_shares: pd.DataFrame,
    stock_splits: pd.DataFrame,
) -> pd.DataFrame:
    """Carry reported shares forward and mechanically apply later split ratios.

    A newly reported share count resets the effective quantity on its availability date. Split
    events are applied only while carrying an older report forward, which keeps raw-price market
    capitalization approximately continuous across ordinary stock splits without using future
    filings.
    """

    if not reported_shares.index.equals(stock_splits.index) or list(reported_shares.columns) != list(
        stock_splits.columns
    ):
        raise ValueError("reported_shares and stock_splits must align exactly")
    output = pd.DataFrame(np.nan, index=reported_shares.index, columns=reported_shares.columns)
    for symbol in reported_shares.columns:
        effective = float("nan")
        last_reported = float("nan")
        for timestamp in reported_shares.index:
            reported = float(reported_shares.loc[timestamp, symbol])
            split = float(stock_splits.loc[timestamp, symbol])
            if np.isfinite(split) and split > 0.0 and np.isfinite(effective):
                effective *= split
            changed_report = np.isfinite(reported) and (
                not np.isfinite(last_reported) or not np.isclose(reported, last_reported)
            )
            if changed_report:
                effective = reported
                last_reported = reported
            output.loc[timestamp, symbol] = effective
    return output.astype(float)


def estimate_market_cap_from_fundamentals(
    data: MarketData,
    fundamentals: FundamentalDataset,
) -> MarketCapEstimate:
    """Estimate point-in-time market cap from raw close and filed shares outstanding."""

    if data.raw_close is None:
        raise ValueError("raw_close is required for market-cap estimation")
    reported = fundamentals.metric_panel(
        "shares_outstanding",
        pd.DatetimeIndex(data.close.index),
        data.symbols,
    )
    effective = split_adjusted_reported_shares(reported, data.stock_splits)
    local = data.raw_close.astype(float) * effective
    if data.fx_to_base is not None:
        base = local * data.fx_to_base.astype(float)
    else:
        base = local.copy()
    return MarketCapEstimate(
        reported_shares=reported,
        effective_shares=effective,
        local_market_cap=local,
        base_market_cap=base,
    )
