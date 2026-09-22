from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MarketData:
    open: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    reference: pd.DataFrame | None = None
    membership: pd.DataFrame | None = None
    terminal_returns: pd.DataFrame | None = None
    dividends: pd.DataFrame | None = None
    stock_splits: pd.DataFrame | None = None
    exchange: str | None = None

    def __post_init__(self) -> None:
        if self.open.empty or self.close.empty:
            raise ValueError("market data cannot be empty")
        if not self.open.index.equals(self.close.index):
            raise ValueError("open and close indices must align")
        if list(self.open.columns) != list(self.close.columns):
            raise ValueError("open and close symbols must align")
        if not self.volume.index.equals(self.close.index) or list(self.volume.columns) != list(self.close.columns):
            raise ValueError("volume must align with close")
        if self.reference is None:
            object.__setattr__(self, "reference", self.close.shift(1))
        elif not self.reference.index.equals(self.close.index) or list(self.reference.columns) != list(self.close.columns):
            raise ValueError("reference prices must align with close")
        optional = {
            "membership": self.membership,
            "terminal_returns": self.terminal_returns,
            "dividends": self.dividends,
            "stock_splits": self.stock_splits,
        }
        for name, frame in optional.items():
            if frame is not None and (
                not frame.index.equals(self.close.index) or list(frame.columns) != list(self.close.columns)
            ):
                raise ValueError(f"{name} must align with close")
        if self.membership is None:
            object.__setattr__(
                self,
                "membership",
                pd.DataFrame(True, index=self.close.index, columns=self.close.columns, dtype=bool),
            )
        else:
            object.__setattr__(self, "membership", self.membership.fillna(False).astype(bool))
        if self.terminal_returns is None:
            object.__setattr__(
                self,
                "terminal_returns",
                pd.DataFrame(np.nan, index=self.close.index, columns=self.close.columns, dtype=float),
            )
        if self.dividends is None:
            object.__setattr__(
                self,
                "dividends",
                pd.DataFrame(0.0, index=self.close.index, columns=self.close.columns, dtype=float),
            )
        if self.stock_splits is None:
            object.__setattr__(
                self,
                "stock_splits",
                pd.DataFrame(0.0, index=self.close.index, columns=self.close.columns, dtype=float),
            )

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    def slice(self, start: object = None, end: object = None) -> MarketData:
        return MarketData(
            open=self.open.loc[start:end],
            close=self.close.loc[start:end],
            volume=self.volume.loc[start:end],
            reference=self.reference.loc[start:end] if self.reference is not None else None,
            membership=self.membership.loc[start:end] if self.membership is not None else None,
            terminal_returns=(
                self.terminal_returns.loc[start:end] if self.terminal_returns is not None else None
            ),
            dividends=self.dividends.loc[start:end] if self.dividends is not None else None,
            stock_splits=self.stock_splits.loc[start:end] if self.stock_splits is not None else None,
            exchange=self.exchange,
        )


def _extract_field(raw: pd.DataFrame, symbols: list[str], field: str) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(map(str, raw.columns.get_level_values(0)))
        level1 = set(map(str, raw.columns.get_level_values(1)))
        if field in level1:
            frame = raw.xs(field, axis=1, level=1)
        elif field in level0:
            frame = raw.xs(field, axis=1, level=0)
        else:
            raise KeyError(f"field {field!r} not present in downloaded data")
        return frame.reindex(columns=symbols)

    if len(symbols) != 1 or field not in raw.columns:
        raise ValueError("unexpected single-level yfinance response")
    return raw[[field]].rename(columns={field: symbols[0]})


def _extract_optional_field(
    raw: pd.DataFrame, symbols: list[str], field: str, default: float = 0.0
) -> pd.DataFrame:
    try:
        return _extract_field(raw, symbols, field).astype(float)
    except (KeyError, ValueError):
        return pd.DataFrame(default, index=raw.index, columns=symbols, dtype=float)


def _membership_from_observations(observed: pd.DataFrame) -> pd.DataFrame:
    membership = pd.DataFrame(False, index=observed.index, columns=observed.columns, dtype=bool)
    for symbol in observed.columns:
        dates = observed.index[observed[symbol].fillna(False)]
        if len(dates):
            membership.loc[dates[0] : dates[-1], symbol] = True
    return membership


def download_yahoo(
    symbols: Iterable[str],
    start: str,
    end: str,
    interval: str = "1d",
) -> MarketData:
    """Download public Yahoo market data. This is a data adapter, not a broker connection."""

    import yfinance as yf

    symbol_list = list(dict.fromkeys(s.strip() for s in symbols if s.strip()))
    if not symbol_list:
        raise ValueError("at least one symbol is required")

    raw = yf.download(
        tickers=symbol_list,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        actions=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    if raw.empty:
        raise ValueError("no market data returned")

    raw_open = _extract_field(raw, symbol_list, "Open").astype(float)
    raw_close = _extract_field(raw, symbol_list, "Close").astype(float)
    adjusted_close = _extract_field(raw, symbol_list, "Adj Close").astype(float)
    volume = _extract_field(raw, symbol_list, "Volume").astype(float)
    dividends = _extract_optional_field(raw, symbol_list, "Dividends")
    stock_splits = _extract_optional_field(raw, symbol_list, "Stock Splits")

    factor = adjusted_close / raw_close.replace(0.0, np.nan)
    invalid_factor = factor.notna() & ((factor <= 0.0) | ~np.isfinite(factor))
    if bool(invalid_factor.any().any()):
        raise ValueError("invalid corporate-action adjustment factor in Yahoo data")
    adjusted_open = raw_open * factor
    observed = raw_close.notna() | raw_open.notna()
    valid = adjusted_close.notna().sum(axis=1) > 0
    open_px = adjusted_open.loc[valid]
    close_px = adjusted_close.loc[valid].ffill()
    volume = volume.loc[valid].fillna(0.0)
    membership = _membership_from_observations(observed.loc[valid])
    dividends = dividends.loc[valid].fillna(0.0)
    stock_splits = stock_splits.loc[valid].fillna(0.0)
    reference = close_px.shift(1)
    markets = {"TW" if s.upper().endswith((".TW", ".TWO")) else "US" for s in symbol_list}
    exchange = markets.pop() if len(markets) == 1 else None
    return MarketData(
        open=open_px,
        close=close_px,
        volume=volume,
        reference=reference,
        membership=membership,
        dividends=dividends,
        stock_splits=stock_splits,
        exchange=exchange,
    )


def synthetic_market_data(
    symbols: Iterable[str] = ("AAA", "BBB", "CCC", "DDD"),
    periods: int = 360,
    seed: int = 7,
) -> MarketData:
    """Deterministic correlated synthetic data for tests and offline development."""

    symbols = list(symbols)
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=periods)
    market = rng.normal(0.00035, 0.009, size=periods)

    close = {}
    open_px = {}
    volume = {}
    for i, symbol in enumerate(symbols):
        beta = 0.7 + 0.2 * i
        idio = rng.normal(0.0001 * (i - 1), 0.006 + 0.001 * i, size=periods)
        cycle = 0.0015 * np.sin(np.arange(periods) / (10 + i * 2))
        returns = beta * market + idio + cycle
        prices = 100.0 * np.exp(np.cumsum(returns))
        overnight = rng.normal(0.0, 0.0025, size=periods)
        close[symbol] = prices
        open_px[symbol] = prices * np.exp(overnight)
        volume[symbol] = rng.integers(1_000_000, 5_000_000, size=periods)

    return MarketData(
        open=pd.DataFrame(open_px, index=dates),
        close=pd.DataFrame(close, index=dates),
        volume=pd.DataFrame(volume, index=dates),
        reference=pd.DataFrame(close, index=dates).shift(1),
        membership=pd.DataFrame(True, index=dates, columns=symbols, dtype=bool),
        exchange=None,
    )
