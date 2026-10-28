"""Explicit daily-bar proxy for Taiwan odd-lot limit orders.

This does not infer odd-lot liquidity, queue priority, or actual executions.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from math import floor, isfinite, sqrt

import pandas as pd

from .config import MarketCostConfig
from .execution import Fill, PortfolioState

SAMPLE_STOCKS = ("2330.TW", "2317.TW", "2454.TW", "2308.TW", "2881.TW",
                 "2882.TW", "2891.TW", "1216.TW", "1301.TW", "2412.TW")


def default_instrument_rules() -> dict[str, dict]:
    return {symbol: {"kind": "stock", "sell_tax_bps": 30.0, "price_limit_pct": 0.10}
            for symbol in SAMPLE_STOCKS}


def validate_instrument_rules(symbols: list[str], rules: dict[str, dict]) -> None:
    for symbol in symbols:
        rule = rules.get(symbol)
        if not isinstance(rule, dict) or set(rule) != {"kind", "sell_tax_bps", "price_limit_pct"}:
            raise ValueError(f"missing explicit odd-lot instrument rules for {symbol}")
        if rule["kind"] not in {"stock", "etf"}:
            raise ValueError(f"unsupported odd-lot instrument type for {symbol}")
        tax, limit = rule["sell_tax_bps"], rule["price_limit_pct"]
        if isinstance(tax, bool) or not isinstance(tax, (float, int)) or not isfinite(tax) or tax < 0:
            raise ValueError(f"invalid sell tax assumption for {symbol}")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (float, int))
                                  or not isfinite(limit) or not 0 < limit < 1):
            raise ValueError(f"invalid price limit assumption for {symbol}")


def _tick_cents(cents: int, kind: str) -> int:
    if kind == "etf":
        return 1 if cents < 5000 else 5
    if kind != "stock":
        raise ValueError("unsupported instrument type")
    for threshold, tick in ((1000, 1), (5000, 5), (10000, 10), (50000, 50),
                            (100000, 100)):
        if cents < threshold:
            return tick
    return 500


def round_price(price: float, kind: str, direction: str) -> float:
    """Round to a legal price, including when crossing a tick-size boundary."""
    if not isfinite(price) or price <= 0 or direction not in {"up", "down"}:
        raise ValueError("invalid price or rounding direction")
    value = Decimal(str(price)) * 100
    cents = int(value.to_integral_value(rounding=ROUND_FLOOR))
    if direction == "up" and value != cents:
        cents += 1
    step = 1 if direction == "up" else -1
    while cents > 0 and cents % _tick_cents(cents, kind):
        cents += step
    if cents <= 0:
        raise ValueError("price below minimum tick")
    return cents / 100.0


def fee_breakdown(side: str, gross: float, costs: MarketCostConfig, rounding: str) -> tuple[float, float]:
    commission = max(gross * costs.commission_bps / 10_000.0, costs.min_commission)
    tax = gross * costs.sell_tax_bps / 10_000.0 if side == "SELL" else 0.0
    if rounding == "fractional":
        return float(commission), float(tax)
    if rounding not in {"floor", "nearest"}:
        raise ValueError("invalid fee rounding")
    mode = ROUND_FLOOR if rounding == "floor" else ROUND_HALF_UP
    return tuple(float(Decimal(str(x)).quantize(Decimal(1), rounding=mode))
                 for x in (commission, tax))


def trade_fees(side: str, gross: float, costs: MarketCostConfig, rounding: str) -> float:
    return sum(fee_breakdown(side, gross, costs, rounding))


def simulate_limit_order(
    state: PortfolioState, symbol: str, side: str, quantity: int, opening: float,
    liquidity: float, reference: float, date: pd.Timestamp, costs: MarketCostConfig,
    rule: dict, limit_offset: float, fill_fraction: float, fee_rounding: str,
) -> tuple[Fill | None, float | None, str]:
    """Attempt one daily proxy fill; cash is spendable cash, not settled balance."""
    if not isfinite(reference) or reference <= 0:
        return None, None, "missing_reference"
    kind = rule["kind"]
    side_limit = reference * (1 + limit_offset if side == "BUY" else 1 - limit_offset)
    try:
        limit_price = round_price(side_limit, kind, "down" if side == "BUY" else "up")
        band = rule["price_limit_pct"]
        upper = round_price(reference * (1 + band), kind, "down") if band is not None else None
        lower = round_price(reference * (1 - band), kind, "up") if band is not None else None
    except ValueError:
        return None, None, "invalid_price_band"
    if upper is not None and lower is not None:
        if lower > upper:
            return None, None, "invalid_price_band"
        limit_price = min(max(limit_price, lower), upper)
    if not isfinite(opening) or opening <= 0:
        return None, limit_price, "missing_open"
    if not isfinite(liquidity) or liquidity <= 0:
        return None, limit_price, "no_liquidity_proxy"
    if (side == "BUY" and upper is not None and opening >= upper) or (
        side == "SELL" and lower is not None and opening <= lower
    ):
        return None, limit_price, "price_limit_proxy"
    capacity = floor(liquidity * costs.max_participation)
    fraction_cap = max(1, floor(quantity * fill_fraction)) if quantity > 0 else 0
    qty = min(quantity, fraction_cap, capacity, costs.max_order_shares or 999, 999)
    if side == "SELL":
        qty = min(qty, state.shares.get(symbol, 0))
    if qty <= 0:
        return None, limit_price, "no_capacity"
    slip = costs.slippage_bps / 10_000.0 + costs.impact_coefficient * sqrt(qty / liquidity) / 100.0
    raw_fill = opening * (1 + slip if side == "BUY" else 1 - slip)
    if raw_fill <= 0:
        return None, limit_price, "invalid_proxy_price"
    price = round_price(raw_fill, kind, "up" if side == "BUY" else "down")
    if (upper is not None and price > upper) or (lower is not None and price < lower):
        return None, limit_price, "proxy_outside_price_band"
    if (side == "BUY" and price > limit_price) or (side == "SELL" and price < limit_price):
        return None, limit_price, "limit_not_met"
    if side == "BUY":
        low, high = 0, qty
        while low < high:
            mid = (low + high + 1) // 2
            gross = mid * price
            if gross + trade_fees(side, gross, costs, fee_rounding) <= state.cash + 1e-9:
                low = mid
            else:
                high = mid - 1
        qty = low
        if qty == 0:
            return None, limit_price, "insufficient_cash"
    gross = qty * price
    fees = trade_fees(side, gross, costs, fee_rounding)
    if side == "SELL" and gross < fees and state.cash < fees - gross:
        return None, limit_price, "insufficient_cash_for_fees"
    current = state.shares.get(symbol, 0)
    if side == "BUY":
        state.cash -= gross + fees
        state.shares[symbol] = current + qty
    else:
        state.cash += gross - fees
        state.shares[symbol] = current - qty
    slip_cost = abs(price - opening) * qty
    fill = Fill(date, symbol, side, qty, opening, price, gross, fees, slip_cost,
                "TWD", 1.0, gross, fees, slip_cost)
    return fill, limit_price, "filled" if qty == quantity else "partial"
