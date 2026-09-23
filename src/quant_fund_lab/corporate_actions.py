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
    withholding_rate: float
    cash_in_lieu_price: float
    cash_in_lieu_price_source: str
    fractional_quantity: float
    cash_in_lieu_settlement_date: str


@dataclass(frozen=True)
class CashInLieuReceivable:
    symbol: str
    fractional_quantity: float
    settlement_date: pd.Timestamp
    local_currency: str



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
    cash_in_lieu_prices: pd.Series | None = None,
    cash_in_lieu_settlement_dates: pd.Series | None = None,
    receivables: list[CashInLieuReceivable] | None = None,
) -> list[CorporateActionEvent]:
    """Apply observed split ratios to actual share quantities before ex-date trading.

    Fractional shares created by reverse/non-integer splits use an explicit provider settlement
    price when available. Otherwise ex-date raw open remains a transparent fallback approximation.
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
        local_currency = currency_for_symbol(
            symbol,
            None if currency_codes is None else currency_codes.get(symbol),
        )
        settlement_price = 0.0
        settlement_source = ""
        settlement_date_text = ""
        cash_local = 0.0
        cash_base = 0.0
        if fractional > 1e-12:
            settlement_value = (
                pd.NaT
                if cash_in_lieu_settlement_dates is None
                else cash_in_lieu_settlement_dates.get(symbol, pd.NaT)
            )
            settlement_date = (
                pd.NaT if pd.isna(settlement_value) else pd.Timestamp(settlement_value)
            )
            if pd.notna(settlement_date) and settlement_date > pd.Timestamp(timestamp):
                explicit_value = (
                    float("nan")
                    if cash_in_lieu_prices is None
                    else cash_in_lieu_prices.get(symbol, float("nan"))
                )
                if pd.notna(explicit_value):
                    raise ValueError(
                        "future cash-in-lieu settlement cannot use an ex-date settlement price"
                    )
                if receivables is None:
                    raise ValueError(
                        "future cash-in-lieu settlement requires a receivable collection"
                    )
                receivables.append(
                    CashInLieuReceivable(
                        symbol=symbol,
                        fractional_quantity=float(fractional),
                        settlement_date=pd.Timestamp(settlement_date),
                        local_currency=local_currency,
                    )
                )
                settlement_source = "pending_settlement"
                settlement_date_text = pd.Timestamp(settlement_date).isoformat()
            else:
                explicit_value = (
                    float("nan")
                    if cash_in_lieu_prices is None
                    else cash_in_lieu_prices.get(symbol, float("nan"))
                )
                if pd.notna(explicit_value):
                    settlement_price = float(explicit_value)
                    if not np.isfinite(settlement_price) or settlement_price <= 0.0:
                        raise ValueError(
                            f"invalid explicit cash-in-lieu settlement price for {symbol}"
                        )
                    settlement_source = "provider_settlement"
                else:
                    settlement_price = float(raw_open_prices.get(symbol, float("nan")))
                    if not np.isfinite(settlement_price) or settlement_price <= 0.0:
                        raise ValueError(
                            f"raw open is required for split cash-in-lieu on {symbol}"
                        )
                    settlement_source = "raw_open_fallback"
                settlement_date_text = pd.Timestamp(timestamp).isoformat()
                cash_local = fractional * settlement_price
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
                local_currency=local_currency,
                fx_to_base=float(factor),
                gross_cash_value=float(cash_base),
                gross_cash_value_local=float(cash_local),
                withholding_tax=0.0,
                withholding_tax_local=0.0,
                withholding_rate=0.0,
                cash_in_lieu_price=float(settlement_price),
                cash_in_lieu_price_source=settlement_source,
                fractional_quantity=float(fractional),
                cash_in_lieu_settlement_date=settlement_date_text,
            )
        )
    return events


def mark_cash_in_lieu_receivables(
    receivables: list[CashInLieuReceivable],
    prices: pd.Series,
    fx_to_base: pd.Series | None = None,
    currency_codes: pd.Series | None = None,
) -> float:
    """Mark pending fractional entitlements into NAV without making them spendable cash."""

    total = 0.0
    for receivable in receivables:
        symbol = receivable.symbol
        price = float(prices.get(symbol, float("nan")))
        if not np.isfinite(price) or price <= 0.0:
            raise ValueError(f"missing receivable mark price for {symbol}")
        observed_currency = currency_for_symbol(
            symbol,
            None if currency_codes is None else currency_codes.get(symbol),
        )
        if observed_currency != receivable.local_currency:
            raise ValueError(
                f"cash-in-lieu receivable currency changed before settlement for {symbol}"
            )
        total += receivable.fractional_quantity * price * _fx(symbol, fx_to_base)
    return float(total)


def settle_cash_in_lieu_receivables(
    state: PortfolioState,
    receivables: list[CashInLieuReceivable],
    timestamp: pd.Timestamp,
    settlement_prices: pd.Series | None,
    fx_to_base: pd.Series | None = None,
    currency_codes: pd.Series | None = None,
) -> list[CorporateActionEvent]:
    """Convert receivables on the first session cash is spendable before open.

    The settlement date is a simulation-availability date, not merely a legal payment date.
    If broker cash arrives intraday or after close, the input must use the next session.
    """

    timestamp = pd.Timestamp(timestamp)
    events: list[CorporateActionEvent] = []
    remaining: list[CashInLieuReceivable] = []
    for receivable in receivables:
        if receivable.settlement_date < timestamp:
            raise ValueError(
                f"cash-in-lieu receivable missed settlement date for {receivable.symbol}"
            )
        if receivable.settlement_date != timestamp:
            remaining.append(receivable)
            continue
        symbol = receivable.symbol
        value = (
            float("nan")
            if settlement_prices is None
            else settlement_prices.get(symbol, float("nan"))
        )
        price = float(value)
        if not np.isfinite(price) or price <= 0.0:
            raise ValueError(
                f"explicit cash-in-lieu settlement price is required on settlement date for {symbol}"
            )
        observed_currency = currency_for_symbol(
            symbol,
            None if currency_codes is None else currency_codes.get(symbol),
        )
        if observed_currency != receivable.local_currency:
            raise ValueError(
                f"cash-in-lieu receivable currency changed before settlement for {symbol}"
            )
        factor = _fx(symbol, fx_to_base)
        cash_local = receivable.fractional_quantity * price
        cash_base = cash_local * factor
        state.cash += cash_base
        events.append(
            CorporateActionEvent(
                timestamp=timestamp,
                symbol=symbol,
                action="cash_in_lieu_settlement",
                quantity_before=state.shares.get(symbol, 0),
                quantity_after=state.shares.get(symbol, 0),
                ratio_or_amount=receivable.fractional_quantity,
                cash_value=float(cash_base),
                cash_value_local=float(cash_local),
                local_currency=receivable.local_currency,
                fx_to_base=float(factor),
                gross_cash_value=float(cash_base),
                gross_cash_value_local=float(cash_local),
                withholding_tax=0.0,
                withholding_tax_local=0.0,
                withholding_rate=0.0,
                cash_in_lieu_price=float(price),
                cash_in_lieu_price_source="provider_settlement",
                fractional_quantity=float(receivable.fractional_quantity),
                cash_in_lieu_settlement_date=timestamp.isoformat(),
            )
        )
    receivables[:] = remaining
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
                withholding_rate=float(rate),
                cash_in_lieu_price=0.0,
                cash_in_lieu_price_source="",
                fractional_quantity=0.0,
                cash_in_lieu_settlement_date="",
            )
        )
    return events
