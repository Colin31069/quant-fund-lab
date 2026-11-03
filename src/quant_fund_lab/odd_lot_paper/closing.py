"""Pure post-open trade-settlement and close valuation step shared by account paths."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..corporate_actions import CashInLieuReceivable, mark_cash_in_lieu_receivables
from ..execution import PortfolioState


@dataclass(frozen=True)
class AccountCloseInput:
    portfolio: PortfolioState
    settlements: tuple[dict, ...]
    receivables: tuple[CashInLieuReceivable, ...]
    session: pd.Timestamp
    session_index: int
    close_prices: pd.Series
    currency_codes: pd.Series | None = None


@dataclass(frozen=True)
class AccountCloseResult:
    portfolio: PortfolioState
    settlements: tuple[dict, ...]
    nav: dict


def close_odd_lot_session(inputs: AccountCloseInput) -> AccountCloseResult:
    """Settle only after today's opening orders; never mutate supplied state.

    Buy payments and fee shortfalls have already reduced spendable cash.
    Positive sale proceeds remain NAV assets until credited exactly once.
    """
    state = PortfolioState(inputs.portfolio.cash, dict(inputs.portfolio.shares),
                           inputs.portfolio.receivable_value)
    settlements = tuple(dict(row) for row in inputs.settlements)
    for row in settlements:
        if row["settled_at"] is None and row["due_session_index"] == inputs.session_index:
            row["settled_at"] = inputs.session
            if row["side"] == "SELL" and row["amount"] >= 0:
                state.cash += row["amount"]
    state.receivable_value = mark_cash_in_lieu_receivables(
        list(inputs.receivables), inputs.close_prices, currency_codes=inputs.currency_codes)
    outstanding = [row for row in settlements if row["settled_at"] is None]
    buys = sum(row["amount"] for row in outstanding if row["side"] == "BUY" and row["amount"] >= 0)
    sales = sum(row["amount"] for row in outstanding if row["side"] == "SELL" and row["amount"] >= 0)
    fees = sum(-row["amount"] for row in outstanding if row["side"] == "SELL" and row["amount"] < 0)
    nav = {"timestamp": inputs.session, "equity": state.equity(inputs.close_prices) + sales,
           "cash": state.cash, "settled_cash": state.cash + buys + fees,
           "buy_payables": buys, "sale_receivables": sales, "sale_payables": fees,
           "receivable_value": state.receivable_value}
    return AccountCloseResult(state, settlements, nav)
