from __future__ import annotations

from dataclasses import dataclass
from math import floor

import numpy as np
import pandas as pd

from .config import DividendWithholdingConfig
from .execution import PortfolioState, market_for_symbol
from .fx import currency_for_symbol


@dataclass(frozen=True)
class CorporateActionEvent:
    timestamp: pd.Timestamp
    symbol: str
    action: str
    quantity_before: int
    quantity_after: int
    ratio_or_amount: float
    cash_value: float
    cash_value_local: float
    local_currency: str
    fx_to_base: float
    gross_cash_value: float
    gross_cash_value_local: float
    withholding_tax: float
    withholding_tax_local: float


def _fx(symbol: str, fx_to_base: pd.Series | None) -> float:
    factor = 1.0 if fx_to_base is None else float(fx_to_base.get(symbol, float("nan")))
    if not np.isfinite(factor) or factor <= 0.0:
        raise ValueError(f"missing or invalid FX conversion factor for {symbol}")
    return factor


def apply_stock_split_events(
    state: PortfolioState,
    splits: pd.Series,
    raw_open_prices: pd.Series,
    timestamp: pd.Timestamp,
    fx_to_base: pd.Series | None = None,
    currency_codes: pd.Series | None = None,
) -> list[CorporateActionEvent]:
    """Apply observed split ratios to actual share quantities before ex-date trading.

    Fractional shares created by reverse/non-integer splits are converted to cash-in-lieu using the
    ex-date raw open as a transparent approximation; this is recorded explicitly in the event.
    """

    events: list[CorporateActionEvent] = []
    for symbol, value in splits.items():
        ratio = float(value)
        if not np.isfinite(ratio) or ratio <= 0.0 or np.isclose(ratio, 1.0):
            continue
        before = int(state.shares.get(symbol, 0))
        if before <= 0:
            continue
        exact_after = before * ratio
        whole_after = floor(exact_after + 1e-12)
        fractional = max(exact_after - whole_after, 0.0)
        factor = _fx(symbol, fx_to_base)
        raw_open = float(raw_open_prices.get(symbol, float("nan")))
        if fractional > 1e-12 and (not np.isfinite(raw_open) or raw_open <= 0.0):
            raise ValueError(f"raw open is required for split cash-in-lieu on {symbol}")
        cash_local = fractional * raw_open if fractional > 0.0 else 0.0
        cash_base = cash_local * factor
        state.shares[symbol] = whole_after
        state.cash += cash_base
        events.append(
            CorporateActionEvent(
                timestamp=pd.Timestamp(timestamp),
                symbol=symbol,
                action="stock_split",
                quantity_before=before,
                quantity_after=whole_after,
                ratio_or_amount=ratio,
                cash_value=float(cash_base),
                cash_value_local=float(cash_local),
                local_currency=currency_for_symbol(
                    symbol,
                    None if currency_codes is None else currency_codes.get(symbol),
                ),
                fx_to_base=float(factor),
                gross_cash_value=float(cash_base),
                gross_cash_value_local=float(cash_local),
                withholding_tax=0.0,
                withholding_tax_local=0.0,
            )
        )
    return events


def apply_cash_dividend_events(
    state: PortfolioState,
    dividends: pd.Series,
    timestamp: pd.Timestamp,
    fx_to_base: pd.Series | None = None,
    currency_codes: pd.Series | None = None,
    market_codes: pd.Series | None = None,
    withholding: DividendWithholdingConfig | None = None,
) -> list[CorporateActionEvent]:
    """Credit dividend cash after explicit market-level withholding assumptions."""

    tax_config = withholding or DividendWithholdingConfig()
    events: list[CorporateActionEvent] = []
    for symbol, value in dividends.items():
        amount = float(value)
        if not np.isfinite(amount) or amount <= 0.0:
            continue
        quantity = int(state.shares.get(symbol, 0))
        if quantity <= 0:
            continue
        factor = _fx(symbol, fx_to_base)
        market_code = None if market_codes is None else market_codes.get(symbol)
        market = market_for_symbol(symbol, market_code)
        rate = tax_config.tw_rate if market == "TW" else tax_config.us_rate
        gross_local = quantity * amount
        withholding_local = gross_local * rate
        cash_local = gross_local - withholding_local
        gross_base = gross_local * factor
        withholding_base = withholding_local * factor
        cash_base = cash_local * factor
        state.cash += cash_base
        events.append(
            CorporateActionEvent(
                timestamp=pd.Timestamp(timestamp),
                symbol=symbol,
                action="cash_dividend",
                quantity_before=quantity,
                quantity_after=quantity,
                ratio_or_amount=amount,
                cash_value=float(cash_base),
                cash_value_local=float(cash_local),
                local_currency=currency_for_symbol(
                    symbol,
                    None if currency_codes is None else currency_codes.get(symbol),
                ),
                fx_to_base=float(factor),
                gross_cash_value=float(gross_base),
                gross_cash_value_local=float(gross_local),
                withholding_tax=float(withholding_base),
                withholding_tax_local=float(withholding_local),
            )
        )
    return events
