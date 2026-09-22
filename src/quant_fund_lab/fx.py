from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import numpy as np
import pandas as pd

from .data import MarketData

SUPPORTED_CURRENCIES = {"USD", "TWD"}


@dataclass(frozen=True)
class FXValidation:
    base_currency: str
    max_age_days: float
    stale_cells: int
    missing_cells: int

    @property
    def is_valid(self) -> bool:
        return self.stale_cells == 0 and self.missing_cells == 0


def currency_for_symbol(symbol: str) -> str:
    upper = symbol.upper()
    return "TWD" if upper.endswith((".TW", ".TWO")) else "USD"


def _normalize_series(series: pd.Series) -> pd.Series:
    clean = series.dropna().astype(float).sort_index()
    clean.index = pd.DatetimeIndex(clean.index).tz_localize(None).normalize()
    clean = clean[~clean.index.duplicated(keep="last")]
    if clean.empty or bool((clean <= 0.0).any()) or not np.isfinite(clean.to_numpy()).all():
        raise ValueError("USD/TWD FX source must contain positive finite observations")
    return clean


def _align_prior_only(source: pd.Series, index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    target = pd.DatetimeIndex(index).tz_localize(None).normalize()
    source = _normalize_series(source)
    union = source.index.union(target).sort_values()
    values = source.reindex(union).ffill().reindex(target)
    last_observed = pd.Series(source.index, index=source.index).reindex(union).ffill().reindex(target)
    age = pd.Series(
        [(date - observed).days if pd.notna(observed) else np.nan for date, observed in zip(target, last_observed)],
        index=target,
        dtype=float,
    )
    values.index = index
    age.index = index
    return values, age


def attach_fx_rates(
    data: MarketData,
    base_currency: str,
    usd_twd: pd.Series | None = None,
    max_staleness_days: int = 5,
) -> MarketData:
    """Attach factors with semantics: local value * fx_to_base = base-currency value.

    ``usd_twd`` is TWD per 1 USD. Rates are aligned with forward-fill only, never back-filled.
    """

    base_currency = base_currency.upper()
    if base_currency not in SUPPORTED_CURRENCIES:
        raise ValueError("base_currency must be USD or TWD")
    currencies = {symbol: currency_for_symbol(symbol) for symbol in data.symbols}
    needs_cross = any(currency != base_currency for currency in currencies.values())

    aligned: pd.Series | None = None
    age: pd.Series | None = None
    if needs_cross:
        if usd_twd is None:
            raise ValueError("USD/TWD FX series is required for cross-currency valuation")
        aligned, age = _align_prior_only(usd_twd, data.close.index)
        if aligned.isna().any():
            raise ValueError("FX series has no prior observation for one or more market dates")
        if age.isna().any() or float(age.max()) > max_staleness_days:
            max_age = float(age.max()) if age.notna().any() else float("inf")
            raise ValueError(
                f"FX series is stale: max age {max_age:.0f} days exceeds {max_staleness_days}"
            )

    factors = pd.DataFrame(index=data.close.index, columns=data.symbols, dtype=float)
    ages = pd.DataFrame(0.0, index=data.close.index, columns=data.symbols, dtype=float)
    for symbol, currency in currencies.items():
        if currency == base_currency:
            factors[symbol] = 1.0
            ages[symbol] = 0.0
        elif base_currency == "TWD" and currency == "USD":
            factors[symbol] = aligned
            ages[symbol] = age
        elif base_currency == "USD" and currency == "TWD":
            factors[symbol] = 1.0 / aligned
            ages[symbol] = age
        else:
            raise ValueError(f"unsupported currency conversion {currency}->{base_currency}")

    return replace(
        data,
        fx_to_base=factors,
        fx_age_days=ages,
        base_currency=base_currency,
    )


def validate_fx(data: MarketData, max_staleness_days: int = 5) -> FXValidation:
    if data.fx_to_base is None or data.fx_age_days is None or data.base_currency is None:
        raise ValueError("market data does not have attached FX conversion factors")
    missing = int(data.fx_to_base.isna().sum().sum())
    stale = int((data.fx_age_days > max_staleness_days).sum().sum())
    return FXValidation(
        base_currency=data.base_currency,
        max_age_days=float(data.fx_age_days.max().max()),
        stale_cells=stale,
        missing_cells=missing,
    )


def download_yahoo_usd_twd(start: str, end: str) -> pd.Series:
    """Download TWD per 1 USD from Yahoo's explicit USDTWD=X currency pair."""

    import yfinance as yf

    raw = yf.download(
        "USDTWD=X",
        start=start,
        end=end,
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise ValueError("no USD/TWD FX data returned")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            close = raw.xs("Close", axis=1, level=1).iloc[:, 0]
    else:
        close = raw["Close"]
    close.name = "USDTWD"
    return _normalize_series(close)


def attach_yahoo_fx(
    data: MarketData, base_currency: str, max_staleness_days: int = 5
) -> MarketData:
    currencies = {currency_for_symbol(symbol) for symbol in data.symbols}
    if currencies == {base_currency.upper()}:
        return attach_fx_rates(data, base_currency, max_staleness_days=max_staleness_days)
    start = (pd.Timestamp(data.close.index.min()) - timedelta(days=10)).date().isoformat()
    end = (pd.Timestamp(data.close.index.max()) + timedelta(days=2)).date().isoformat()
    usd_twd = download_yahoo_usd_twd(start, end)
    return attach_fx_rates(
        data,
        base_currency=base_currency,
        usd_twd=usd_twd,
        max_staleness_days=max_staleness_days,
    )
