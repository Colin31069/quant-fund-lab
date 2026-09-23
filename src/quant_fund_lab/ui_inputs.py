from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .data import MarketData
from .research_inputs import load_verified_identity_research_inputs


@dataclass(frozen=True)
class VerifiedUIInputs:
    raw: MarketData
    trade_data: MarketData
    trade_assets: tuple[str, ...]
    benchmark_asset: str
    data_provenance: dict[str, str]


def _asset_for_security_id(assets: pd.DataFrame, security_id: str) -> str:
    rows = assets[assets["security_id"].eq(security_id)]
    if len(rows) != 1:
        raise ValueError(f"security_id must map to exactly one asset: {security_id}")
    return str(rows.iloc[0]["asset_key"])


def _subset_assets(data: MarketData, symbols: list[str]) -> MarketData:
    def subset(frame: pd.DataFrame | None) -> pd.DataFrame | None:
        return None if frame is None else frame[symbols]

    return MarketData(
        open=data.open[symbols],
        close=data.close[symbols],
        volume=data.volume[symbols],
        raw_open=subset(data.raw_open),
        raw_close=subset(data.raw_close),
        reference=subset(data.reference),
        membership=subset(data.membership),
        terminal_returns=subset(data.terminal_returns),
        dividends=subset(data.dividends),
        stock_splits=subset(data.stock_splits),
        cash_in_lieu_prices=subset(data.cash_in_lieu_prices),
        fx_to_base=subset(data.fx_to_base),
        fx_age_days=subset(data.fx_age_days),
        market_codes=subset(data.market_codes),
        currency_codes=subset(data.currency_codes),
        base_currency=data.base_currency,
        exchange=data.exchange,
    )


def load_verified_ui_inputs(
    market_snapshot_directory: str | Path,
    lifecycle_snapshot_directory: str | Path,
    trade_security_ids: list[str],
    benchmark_security_id: str,
    *,
    start: object,
    end: object,
    base_currency: str,
    usd_twd: pd.Series | None = None,
    max_fx_staleness_days: int = 5,
) -> VerifiedUIInputs:
    trade_ids = list(
        dict.fromkeys(str(value).strip() for value in trade_security_ids if str(value).strip())
    )
    benchmark_id = str(benchmark_security_id).strip()
    if len(trade_ids) < 2:
        raise ValueError("verified lifecycle mode requires at least two trade security_ids")
    if not benchmark_id:
        raise ValueError("benchmark security_id is required")

    requested = list(dict.fromkeys(trade_ids + [benchmark_id]))
    bundle = load_verified_identity_research_inputs(
        market_snapshot_directory,
        lifecycle_snapshot_directory,
        requested,
        base_currency=base_currency,
        usd_twd=usd_twd,
        max_fx_staleness_days=max_fx_staleness_days,
    )
    raw = bundle.data.slice(start=start, end=end)
    if raw.close.empty:
        raise ValueError("verified snapshots do not contain the requested date range")

    trade_assets = tuple(_asset_for_security_id(bundle.assets, value) for value in trade_ids)
    benchmark_asset = _asset_for_security_id(bundle.assets, benchmark_id)
    trade_data = _subset_assets(raw, list(trade_assets))
    return VerifiedUIInputs(
        raw=raw,
        trade_data=trade_data,
        trade_assets=trade_assets,
        benchmark_asset=benchmark_asset,
        data_provenance=dict(bundle.data_provenance),
    )
