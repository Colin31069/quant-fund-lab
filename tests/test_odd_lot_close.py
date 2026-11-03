"""Hand calculations for post-open settlement, fee shortfalls and NAV preservation."""
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.odd_lot_paper.closing import AccountCloseInput, close_odd_lot_session


def test_post_open_settlement_preserves_nav_and_never_double_credits_or_mutates():
    day = pd.Timestamp("2024-01-05")
    rows = tuple({"side": side, "amount": amount, "settled_at": None,
                  "due_session_index": due} for side, amount, due in (
                      ("SELL", 200., 3), ("BUY", 100., 4), ("SELL", -5., 4)))
    portfolio = PortfolioState(695., {"2330.TW": 1})
    inputs = AccountCloseInput(portfolio, rows, (), day, 2, pd.Series({"2330.TW": 105.}))
    before = close_odd_lot_session(inputs)
    assert before.nav["equity"] == 1000
    assert before.nav["cash"] == 695 and before.nav["settled_cash"] == 800
    due = close_odd_lot_session(replace(inputs, session_index=3))
    assert due.nav["cash"] == 895 and due.nav["equity"] == 1000
    assert portfolio.cash == 695 and all(row["settled_at"] is None for row in rows)
    repeat = close_odd_lot_session(replace(inputs, portfolio=due.portfolio, settlements=due.settlements,
                                         session_index=3))
    assert repeat.nav == due.nav
    final = close_odd_lot_session(replace(inputs, portfolio=due.portfolio, settlements=due.settlements,
                                        session_index=4))
    assert final.nav["equity"] == 1000 and final.nav["cash"] == 895
    assert final.nav["settled_cash"] == 895
    assert final.nav["buy_payables"] == final.nav["sale_payables"] == 0


def test_failed_valuation_does_not_partially_credit_input_state():
    from quant_fund_lab.corporate_actions import CashInLieuReceivable

    day = pd.Timestamp("2024-01-05")
    state = PortfolioState(100.)
    row = {"side": "SELL", "amount": 20., "settled_at": None, "due_session_index": 3}
    receivable = CashInLieuReceivable("absent.TW", .5, day + pd.Timedelta(days=5), "TWD")
    inputs = AccountCloseInput(state, (row,), (receivable,), day, 3, pd.Series({"2330.TW": 100.}))
    with pytest.raises(ValueError):
        close_odd_lot_session(inputs)
    assert state.cash == 100 and row["settled_at"] is None
