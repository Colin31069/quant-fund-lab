from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, sqrt

import pandas as pd

from .config import BacktestConfig, MarketCostConfig
from .fx import currency_for_symbol


@dataclass(frozen=True)
class Fill:
    timestamp: pd.Timestamp
    symbol: str
    side: str
    quantity: int
    reference_price: float
    fill_price: float
    gross_value: float
    fees: float
    slippage_cost: float
    local_currency: str
    fx_to_base: float
    gross_value_local: float
    fees_local: float
    slippage_cost_local: float


@dataclass(frozen=True)
class TerminalEvent:
    timestamp: pd.Timestamp
    symbol: str
    quantity: int
    reference_price: float
    terminal_return: float
    proceeds: float
    local_currency: str
    fx_to_base: float
    proceeds_local: float


@dataclass
class PortfolioState:
    cash: float
    shares: dict[str, int] = field(default_factory=dict)

    def equity(self, prices: pd.Series, fx_to_base: pd.Series | None = None) -> float:
        factors = (
            fx_to_base.reindex(prices.index).fillna(1.0)
            if fx_to_base is not None
            else pd.Series(1.0, index=prices.index)
        )
        holdings = sum(
            self.shares.get(symbol, 0)
            * float(prices.get(symbol, 0.0))
            * float(factors.get(symbol, 1.0))
            for symbol in self.shares
        )
        return float(self.cash + holdings)

    def weights(self, prices: pd.Series, fx_to_base: pd.Series | None = None) -> pd.Series:
        factors = (
            fx_to_base.reindex(prices.index).fillna(1.0)
            if fx_to_base is not None
            else pd.Series(1.0, index=prices.index)
        )
        equity = self.equity(prices, factors)
        symbols = list(prices.index)
        if equity <= 0:
            return pd.Series(0.0, index=symbols)
        return pd.Series(
            {
                symbol: self.shares.get(symbol, 0)
                * float(prices[symbol])
                * float(factors[symbol])
                / equity
                for symbol in symbols
            },
            dtype=float,
        )


def market_for_symbol(symbol: str, market_code: object = None) -> str:
    if pd.notna(market_code):
        normalized = str(market_code).upper().strip()
        if normalized not in {"US", "TW"}:
            raise ValueError(f"unsupported market code for {symbol}: {market_code}")
        return normalized
    upper = symbol.upper()
    return "TW" if upper.endswith((".TW", ".TWO")) else "US"


def _cost_config(
    symbol: str, config: BacktestConfig, market_code: object = None
) -> MarketCostConfig:
    return config.tw_costs if market_for_symbol(symbol, market_code) == "TW" else config.us_costs


def _trade_costs(side: str, gross: float, costs: MarketCostConfig) -> float:
    commission = gross * costs.commission_bps / 10_000.0
    sell_tax = gross * costs.sell_tax_bps / 10_000.0 if side == "SELL" else 0.0
    sec_fee = gross * costs.sec_fee_per_million / 1_000_000.0 if side == "SELL" else 0.0
    return float(commission + sell_tax + sec_fee)


def _tw_tick_size(price: float) -> float:
    if price < 10.0:
        return 0.01
    if price < 50.0:
        return 0.05
    if price < 100.0:
        return 0.10
    if price < 500.0:
        return 0.50
    if price < 1_000.0:
        return 1.0
    return 5.0


def _blocked_by_price_limit(
    symbol: str,
    side: str,
    open_price: float,
    reference_price: float,
    costs: MarketCostConfig,
    market_code: object = None,
) -> bool:
    """Conservative Taiwan locked-limit proxy when official auction reference is unavailable."""

    if market_for_symbol(symbol, market_code) != "TW" or costs.price_limit_pct is None:
        return False
    if not pd.notna(reference_price) or reference_price <= 0:
        return False
    tick = _tw_tick_size(reference_price)
    upper = reference_price * (1.0 + costs.price_limit_pct)
    lower = reference_price * (1.0 - costs.price_limit_pct)
    tolerance = tick / 2.0
    return (side == "BUY" and open_price >= upper - tolerance) or (
        side == "SELL" and open_price <= lower + tolerance
    )


def _fx_factor(symbol: str, fx_to_base: pd.Series | None) -> float:
    factor = 1.0 if fx_to_base is None else float(fx_to_base.get(symbol, float("nan")))
    if not pd.notna(factor) or factor <= 0.0:
        raise ValueError(f"missing or invalid FX conversion factor for {symbol}")
    return factor


def apply_terminal_returns(
    state: PortfolioState,
    terminal_returns: pd.Series,
    reference_prices: pd.Series,
    timestamp: pd.Timestamp,
    fx_to_base: pd.Series | None = None,
    currency_codes: pd.Series | None = None,
) -> list[TerminalEvent]:
    events: list[TerminalEvent] = []
    for symbol, terminal_return in terminal_returns.items():
        if not pd.notna(terminal_return):
            continue
        terminal_return = float(terminal_return)
        if terminal_return < -1.0:
            raise ValueError(f"terminal return below -100% for {symbol}")
        quantity = state.shares.get(symbol, 0)
        if quantity <= 0:
            continue
        reference = float(reference_prices.get(symbol, float("nan")))
        if not pd.notna(reference) or reference < 0.0:
            raise ValueError(f"missing terminal reference price for {symbol}")
        factor = _fx_factor(symbol, fx_to_base)
        proceeds_local = quantity * reference * (1.0 + terminal_return)
        proceeds = proceeds_local * factor
        state.cash += proceeds
        state.shares[symbol] = 0
        events.append(
            TerminalEvent(
                timestamp=timestamp,
                symbol=symbol,
                quantity=quantity,
                reference_price=reference,
                terminal_return=terminal_return,
                proceeds=float(proceeds),
                local_currency=currency_for_symbol(
                    symbol,
                    None if currency_codes is None else currency_codes.get(symbol),
                ),
                fx_to_base=float(factor),
                proceeds_local=float(proceeds_local),
            )
        )
    return events


def desired_quantities(
    state: PortfolioState,
    target_weights: pd.Series,
    prices: pd.Series,
    config: BacktestConfig,
    fx_to_base: pd.Series | None = None,
    market_codes: pd.Series | None = None,
) -> dict[str, int]:
    """Translate target weights into lot-rounded desired share quantities."""

    symbols = list(target_weights.index)
    factors = pd.Series(
        {symbol: _fx_factor(symbol, fx_to_base) for symbol in symbols}, dtype=float
    )
    equity = state.equity(prices, factors)
    desired: dict[str, int] = {}
    for symbol in symbols:
        price = float(prices.get(symbol, float("nan")))
        if not pd.notna(price) or price <= 0.0:
            desired[symbol] = state.shares.get(symbol, 0)
            continue
        costs = _cost_config(
            symbol,
            config,
            None if market_codes is None else market_codes.get(symbol),
        )
        desired_value = max(float(target_weights[symbol]), 0.0) * equity
        base_price = price * float(factors[symbol])
        desired[symbol] = int(
            floor(desired_value / base_price / costs.lot_size) * costs.lot_size
        )
    return desired


def execute_market_order(
    state: PortfolioState,
    symbol: str,
    side: str,
    quantity: int,
    open_price: float,
    volume: float,
    reference_price: float,
    timestamp: pd.Timestamp,
    config: BacktestConfig,
    fx_to_base: float = 1.0,
    market_code: object = None,
    local_currency: object = None,
) -> Fill | None:
    """Execute one virtual market order with the same rules used by backtests."""

    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    costs = _cost_config(symbol, config, market_code)
    ref = float(open_price)
    available_volume = max(float(volume), 0.0)
    if quantity <= 0 or available_volume <= 0.0 or not pd.notna(ref) or ref <= 0.0:
        return None
    if _blocked_by_price_limit(
        symbol,
        side,
        ref,
        float(reference_price),
        costs,
        market_code,
    ):
        return None
    if not pd.notna(fx_to_base) or fx_to_base <= 0.0:
        raise ValueError(f"missing or invalid FX conversion factor for {symbol}")

    max_liquidity_qty = int(
        floor(available_volume * costs.max_participation / costs.lot_size) * costs.lot_size
    )
    qty = min(int(quantity), max_liquidity_qty)
    qty = int(floor(qty / costs.lot_size) * costs.lot_size)
    current = state.shares.get(symbol, 0)
    if side == "SELL":
        qty = min(qty, current)
    if qty <= 0:
        return None

    participation = qty / max(available_volume, 1.0)
    slip_rate = (
        costs.slippage_bps / 10_000.0
        + costs.impact_coefficient * sqrt(participation) / 100.0
    )
    fill_px = ref * (1.0 + slip_rate if side == "BUY" else 1.0 - slip_rate)
    factor = float(fx_to_base)
    gross_local = qty * fill_px
    fees_local = _trade_costs(side, gross_local, costs)

    if side == "BUY":
        per_share_cash = fill_px * (1.0 + costs.commission_bps / 10_000.0) * factor
        affordable = int(
            floor(state.cash / max(per_share_cash, 1e-12) / costs.lot_size) * costs.lot_size
        )
        qty = min(qty, affordable)
        if qty <= 0:
            return None
        gross_local = qty * fill_px
        fees_local = _trade_costs(side, gross_local, costs)
        state.cash -= (gross_local + fees_local) * factor
        state.shares[symbol] = current + qty
    else:
        state.cash += (gross_local - fees_local) * factor
        state.shares[symbol] = current - qty

    gross = gross_local * factor
    fees = fees_local * factor
    slippage_local = abs(fill_px - ref) * qty
    return Fill(
        timestamp=timestamp,
        symbol=symbol,
        side=side,
        quantity=qty,
        reference_price=ref,
        fill_price=float(fill_px),
        gross_value=float(gross),
        fees=float(fees),
        slippage_cost=float(slippage_local * factor),
        local_currency=currency_for_symbol(symbol, local_currency),
        fx_to_base=factor,
        gross_value_local=float(gross_local),
        fees_local=float(fees_local),
        slippage_cost_local=float(slippage_local),
    )


def rebalance_at_open(
    state: PortfolioState,
    target_weights: pd.Series,
    open_prices: pd.Series,
    volumes: pd.Series,
    reference_prices: pd.Series,
    timestamp: pd.Timestamp,
    config: BacktestConfig,
    fx_to_base: pd.Series | None = None,
    market_codes: pd.Series | None = None,
    currency_codes: pd.Series | None = None,
) -> list[Fill]:
    """Execute sells first, then buys, using a configurable liquidity/slippage model."""

    fills: list[Fill] = []
    symbols = list(target_weights.index)
    valuation_prices = open_prices.where(open_prices.notna() & (open_prices > 0), reference_prices)
    factors = pd.Series(
        {symbol: _fx_factor(symbol, fx_to_base) for symbol in symbols}, dtype=float
    )
    desired_qty = desired_quantities(
        state,
        target_weights,
        valuation_prices,
        config,
        factors,
        market_codes,
    )

    for side in ("SELL", "BUY"):
        for symbol in symbols:
            current = state.shares.get(symbol, 0)
            delta = desired_qty[symbol] - current
            if (side == "SELL" and delta >= 0) or (side == "BUY" and delta <= 0):
                continue
            fill = execute_market_order(
                state=state,
                symbol=symbol,
                side=side,
                quantity=abs(delta),
                open_price=float(open_prices.get(symbol, float("nan"))),
                volume=float(volumes.get(symbol, 0.0)),
                reference_price=float(reference_prices.get(symbol, float("nan"))),
                timestamp=timestamp,
                config=config,
                fx_to_base=float(factors[symbol]),
                market_code=None if market_codes is None else market_codes.get(symbol),
                local_currency=None if currency_codes is None else currency_codes.get(symbol),
            )
            if fill is not None:
                fills.append(fill)
    return fills
