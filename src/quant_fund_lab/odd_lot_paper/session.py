"""One historical signal-close to next-close transition, independent of storage."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

from ..cash_carry import accrue_base_cash_interest
from ..config import BacktestConfig
from ..corporate_actions import settle_cash_in_lieu_receivables
from ..data import MarketData
from ..execution import apply_terminal_returns
from .bridge import HistoricalSessionState
from .closing import AccountCloseInput, close_odd_lot_session
from .distributions import DistributionInput, apply_session_distributions
from .event_prices import EventPriceInput, adjust_event_prices
from .opening import OpeningExecutionInput, execute_opening_orders
from .sale_limits import OpeningSaleLimits
from .signals import SignalPlanInput, plan_close_signals

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchConfig


@dataclass(frozen=True)
class OddLotSessionInput:
    runtime: HistoricalSessionState
    data: MarketData
    research: OddLotResearchConfig
    config: BacktestConfig
    signal_index: int
    origin_index: int
    prior_liquidity: pd.DataFrame
    passive_without_risk_estimate: bool = False
    sale_limits: OpeningSaleLimits | None = None


@dataclass(frozen=True)
class OddLotSessionResult:
    runtime: HistoricalSessionState
    signals: tuple[dict, ...]
    orders: tuple[dict, ...]
    fills: tuple[dict, ...]
    actions: tuple[dict, ...]
    terminal_events: tuple[dict, ...]
    nav: dict


def run_odd_lot_session(inputs: OddLotSessionInput) -> OddLotSessionResult:
    """Advance copied state once; signals never use the following session's history."""
    data, research, config = inputs.data, inputs.research, inputs.config
    i, start_index = inputs.signal_index, inputs.origin_index
    if (type(i) is not int or type(start_index) is not int
            or not 0 <= start_index <= i < len(data.close.index) - 1):
        raise ValueError("session indexes must preserve origin and have a following session")
    runtime = deepcopy(inputs.runtime)
    state, stops, pending = runtime.portfolio, runtime.stops, runtime.pending
    terminated, receivables, settlements = runtime.terminated, runtime.receivables, runtime.settlements
    passive_submitted = runtime.passive_submitted
    _passive_without_risk_estimate = inputs.passive_without_risk_estimate
    dates, raw_open, raw_close = data.close.index, data.raw_open, data.raw_close
    liquidity = inputs.prior_liquidity
    signal_rows, orders, fills, actions, terminal_events, equity_rows = [], [], [], [], [], []

    def unsettled(side: str) -> float:
        return sum(row["amount"] for row in settlements
                   if row["side"] == side and row["settled_at"] is None and row["amount"] >= 0)

    signal_date, date = dates[i], dates[i + 1]
    close_now = raw_close.loc[signal_date]
    planned = plan_close_signals(SignalPlanInput(
        state, stops, pending, frozenset(terminated), research, config, signal_date,
        i - start_index, data.close.iloc[:i + 1], data.membership.loc[signal_date],
        close_now, raw_open.loc[signal_date], liquidity.loc[date], unsettled("SELL"),
        passive_submitted, _passive_without_risk_estimate))
    stops, pending, passive_submitted = planned.stops, planned.pending, planned.passive_submitted
    signal_rows.extend(planned.signals)

    accrue_base_cash_interest(state, signal_date, date, config.cash_annual_yield)
    currencies = None if data.currency_codes is None else data.currency_codes.loc[date]
    settlement = settle_cash_in_lieu_receivables(
        state, receivables, date,
        None if data.cash_in_lieu_prices is None else data.cash_in_lieu_prices.loc[date],
        currency_codes=currencies,
    )
    actions.extend(asdict(event) for event in settlement)
    # Cash dividends are declared per pre-event share.  Apply them before a
    # simultaneous stock dividend/split, and adjust all price levels on the
    # same pre-event-share basis.
    for symbol in data.symbols:
        ratio = float(data.stock_splits.at[date, symbol])
        dividend = float(data.dividends.at[date, symbol])
        stop = stops.get(symbol)
        adjusted = adjust_event_prices(EventPriceInput(
            float(close_now[symbol]), ratio, dividend,
            stop.stop if stop else None, stop.high_close if stop else None))
        if stop is not None:
            stop.stop, stop.high_close = adjusted.stop, adjusted.high_close
        if adjusted.cancel_pending_buy and symbol in pending and pending[symbol].side == "BUY":
            del pending[symbol]
    distribution = apply_session_distributions(DistributionInput(
        state, tuple(receivables), date, data.dividends.loc[date],
        data.stock_splits.loc[date], raw_open.loc[date], config.dividend_withholding,
        currencies, None if data.market_codes is None else data.market_codes.loc[date],
        None if data.cash_in_lieu_prices is None else data.cash_in_lieu_prices.loc[date],
        None if data.cash_in_lieu_settlement_dates is None else data.cash_in_lieu_settlement_dates.loc[date]))
    state, receivables = distribution.portfolio, list(distribution.receivables)
    actions.extend(asdict(event) for event in distribution.dividend_events)
    split_events = distribution.split_events
    actions.extend(asdict(event) for event in split_events)
    reference = close_now.copy()
    for symbol in data.symbols:
        ratio = float(data.stock_splits.at[date, symbol])
        dividend = float(data.dividends.at[date, symbol])
        reference[symbol] = adjust_event_prices(EventPriceInput(
            float(reference[symbol]), ratio, dividend)).reference
    terminal = apply_terminal_returns(
        state, data.terminal_returns.loc[date], reference, date,
        currency_codes=currencies,
    )
    terminal_events.extend(asdict(event) for event in terminal)
    for symbol in data.terminal_returns.loc[date].dropna().index:
        terminated.add(symbol)
        stops.pop(symbol, None)
        pending.pop(symbol, None)
    for event in split_events:
        if event.quantity_after == 0:
            stops.pop(event.symbol, None)
            pending.pop(event.symbol, None)

    opening = execute_opening_orders(OpeningExecutionInput(
        state, stops, pending, tuple(data.symbols), research, config, date, i + 1,
        raw_open.loc[date], liquidity.loc[date], reference, inputs.sale_limits))
    state, stops, pending = opening.portfolio, opening.stops, opening.pending
    orders.extend(opening.orders)
    fills.extend(opening.fills)
    settlements.extend(opening.settlements)
    # The T+2 proceeds are credited after this day's open, so they cannot fund
    # today's orders. The observed session sequence is the settlement proxy.
    closed = close_odd_lot_session(AccountCloseInput(
        state, tuple(settlements), tuple(receivables), date, i + 1,
        raw_close.loc[date], currencies))
    state = closed.portfolio
    settlements = list(closed.settlements)
    equity_rows.append(closed.nav)

    runtime = HistoricalSessionState(state, stops, pending, terminated, receivables,
                                     settlements, passive_submitted)
    result = OddLotSessionResult(runtime, tuple(signal_rows), tuple(orders), tuple(fills),
                                tuple(actions), tuple(terminal_events), equity_rows[0])
    # The future rights bridge may consume only reconciled usable cash/holdings.
    # Keep the current event/result schema unchanged while checking this boundary.
    from ..odd_lot_rights.session_link import reconcile_session_portfolio

    reconcile_session_portfolio(inputs, result)
    return result
