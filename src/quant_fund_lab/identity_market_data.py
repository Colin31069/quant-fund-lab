from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import MarketData
from .execution import market_for_symbol
from .security_master_events import SecurityMasterEventDataset


@dataclass(frozen=True)
class IdentityStitchResult:
    data: MarketData
    assets: pd.DataFrame


def _stable_asset_key(security_id: str, canonical_symbol: str) -> str:
    symbol = canonical_symbol.upper().strip()
    if symbol.endswith(".TWO"):
        return f"{symbol[:-4]}@@{security_id}.TWO"
    if symbol.endswith(".TW"):
        return f"{symbol[:-3]}@@{security_id}.TW"
    return f"{symbol}@@{security_id}"


def _interval_dates(
    index: pd.DatetimeIndex,
    effective_from: pd.Timestamp,
    effective_until_exclusive: object,
) -> pd.DatetimeIndex:
    mask = index >= effective_from
    if pd.notna(effective_until_exclusive):
        mask &= index < pd.Timestamp(effective_until_exclusive)
    return index[mask]


def stitch_market_data_by_identity(
    data: MarketData,
    lifecycle: SecurityMasterEventDataset,
    security_ids: list[str],
) -> IdentityStitchResult:
    """Stitch ticker-history segments into stable internal asset keys.

    This stage intentionally fails closed on exchange/currency transitions. Ticker changes and
    ticker reuse are supported because lifecycle intervals determine which security owns a source
    symbol at each date. The output keys are internal identifiers, not provider tickers.
    """

    requested = list(dict.fromkeys(str(value).strip() for value in security_ids if str(value).strip()))
    if not requested:
        raise ValueError("at least one security_id is required")
    index = pd.DatetimeIndex(data.close.index)
    if index.empty:
        raise ValueError("market data cannot be empty")

    history = lifecycle.identity_history()
    known = set(lifecycle.security_ids)
    missing_ids = sorted(set(requested) - known)
    if missing_ids:
        raise ValueError(f"security lifecycle missing security_ids: {missing_ids}")

    source_frames: dict[str, pd.DataFrame | None] = {
        "open": data.open,
        "close": data.close,
        "volume": data.volume,
        "raw_open": data.raw_open,
        "raw_close": data.raw_close,
        "dividends": data.dividends,
        "stock_splits": data.stock_splits,
        "fx_to_base": data.fx_to_base,
        "fx_age_days": data.fx_age_days,
    }
    output: dict[str, pd.DataFrame | None] = {
        "open": pd.DataFrame(index=index),
        "close": pd.DataFrame(index=index),
        "volume": pd.DataFrame(index=index),
        "raw_open": pd.DataFrame(index=index),
        "raw_close": pd.DataFrame(index=index),
        "dividends": pd.DataFrame(index=index),
        "stock_splits": pd.DataFrame(index=index),
        "fx_to_base": pd.DataFrame(index=index) if data.fx_to_base is not None else None,
        "fx_age_days": pd.DataFrame(index=index) if data.fx_age_days is not None else None,
    }
    membership = pd.DataFrame(index=index)
    terminal_returns = pd.DataFrame(index=index)
    market_codes = pd.DataFrame(index=index)
    currency_codes = pd.DataFrame(index=index)
    asset_rows: list[dict[str, object]] = []
    broad_markets: set[str] = set()

    for security_id in requested:
        identity = history[history["security_id"].eq(security_id)].sort_values(
            "effective_from", kind="stable"
        )
        if identity.empty:
            raise ValueError(f"security_id {security_id} has no identity history")

        lifecycle_rows = lifecycle.events[lifecycle.events["security_id"].eq(security_id)]
        if lifecycle_rows["event_type"].eq("EXCHANGE_CHANGED").any():
            raise ValueError(
                f"security_id {security_id} changes exchange; identity stitching requires "
                "per-date market metadata before this transition can be backtested safely"
            )
        if lifecycle_rows["event_type"].eq("CURRENCY_CHANGED").any():
            raise ValueError(
                f"security_id {security_id} changes currency; identity stitching requires "
                "per-date FX metadata before this transition can be backtested safely"
            )

        eligible_identity = identity[identity["effective_from"] <= index.max()]
        if eligible_identity.empty:
            raise ValueError(f"security_id {security_id} is not listed by the market-data end date")
        canonical = eligible_identity.iloc[-1]
        canonical_symbol = str(canonical["symbol"])
        market = market_for_symbol(canonical_symbol)
        currency = str(canonical["currency"])
        if any(market_for_symbol(str(value)) != market for value in identity["symbol"]):
            raise ValueError(f"security_id {security_id} crosses market families")
        if any(str(value) != currency for value in identity["currency"]):
            raise ValueError(f"security_id {security_id} has inconsistent currency history")

        asset_key = _stable_asset_key(security_id, canonical_symbol)
        broad_markets.add(market)
        market_codes[asset_key] = pd.Series(pd.NA, index=index, dtype="object")
        currency_codes[asset_key] = pd.Series(pd.NA, index=index, dtype="object")
        aliases: list[str] = []
        for segment in identity.itertuples(index=False):
            dates = _interval_dates(
                index,
                pd.Timestamp(segment.effective_from),
                segment.effective_until_exclusive,
            )
            if dates.empty:
                continue
            source_symbol = str(segment.symbol)
            aliases.append(source_symbol)
            market_codes.loc[dates, asset_key] = market
            currency_codes.loc[dates, asset_key] = currency
            if source_symbol not in data.symbols:
                raise ValueError(
                    f"market data missing lifecycle symbol {source_symbol} for {security_id}"
                )
            observed = data.open.loc[dates, source_symbol].notna() | (
                data.volume.loc[dates, source_symbol].fillna(0.0) > 0.0
            )
            if not bool(observed.any()):
                raise ValueError(
                    f"no market observations for {security_id} alias {source_symbol} "
                    f"inside its effective interval"
                )
            first_observed = dates[int(np.flatnonzero(observed.to_numpy())[0])]
            copy_dates = dates[dates >= first_observed]
            for field, frame in source_frames.items():
                destination = output[field]
                if frame is None or destination is None:
                    continue
                destination.loc[copy_dates, asset_key] = frame.loc[copy_dates, source_symbol].to_numpy()

        listed = lifecycle_rows[lifecycle_rows["event_type"].eq("LISTED")].iloc[0]
        active = index >= pd.Timestamp(listed["event_at"])
        delisted = lifecycle_rows[lifecycle_rows["event_type"].eq("DELISTED")]
        terminal = pd.Series(np.nan, index=index, dtype=float)
        if len(delisted):
            row = delisted.iloc[0]
            active &= index <= pd.Timestamp(row["last_tradable_at"])
            location = index.searchsorted(pd.Timestamp(row["event_at"]), side="left")
            if location < len(index):
                terminal.iloc[location] = float(row["terminal_return"])
        membership[asset_key] = active
        terminal_returns[asset_key] = terminal

        asset_rows.append(
            {
                "asset_key": asset_key,
                "security_id": security_id,
                "canonical_symbol": canonical_symbol,
                "market": market,
                "currency": currency,
                "aliases": tuple(dict.fromkeys(aliases)),
            }
        )

    for field in ("open", "close", "raw_open", "raw_close"):
        frame = output[field]
        if frame is not None:
            output[field] = frame.reindex(columns=[row["asset_key"] for row in asset_rows])
    for field in ("volume", "dividends", "stock_splits"):
        frame = output[field]
        if frame is not None:
            output[field] = (
                frame.reindex(columns=[row["asset_key"] for row in asset_rows]).fillna(0.0)
            )
    for field in ("fx_to_base", "fx_age_days"):
        frame = output[field]
        if frame is not None:
            output[field] = frame.reindex(columns=[row["asset_key"] for row in asset_rows])

    close = output["close"]
    if close is None:
        raise RuntimeError("stitched close frame was not created")
    reference = close.shift(1)
    exchange = next(iter(broad_markets)) if len(broad_markets) == 1 else None
    stitched = MarketData(
        open=output["open"],
        close=close,
        volume=output["volume"],
        raw_open=output["raw_open"],
        raw_close=output["raw_close"],
        reference=reference,
        membership=membership.reindex(columns=close.columns).fillna(False),
        terminal_returns=terminal_returns.reindex(columns=close.columns),
        dividends=output["dividends"],
        stock_splits=output["stock_splits"],
        fx_to_base=output["fx_to_base"],
        fx_age_days=output["fx_age_days"],
        market_codes=market_codes.reindex(columns=close.columns),
        currency_codes=currency_codes.reindex(columns=close.columns),
        base_currency=data.base_currency,
        exchange=exchange,
    )
    assets = pd.DataFrame(asset_rows).set_index("asset_key", drop=False)
    return IdentityStitchResult(data=stitched, assets=assets)
