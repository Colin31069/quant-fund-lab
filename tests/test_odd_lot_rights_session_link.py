"""Reconcile real shared-session outputs before rights can consume their cash."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_session_events import _fixture

from quant_fund_lab.odd_lot_paper.session import run_odd_lot_session
from quant_fund_lab.odd_lot_rights.session_link import reconcile_session_portfolio


def test_actual_session_dividend_reverse_split_tplus2_and_fraction_cash_link():
    inputs = _fixture()
    runtime = inputs.runtime
    links = []
    for index in range(4):
        step = replace(inputs,runtime=runtime,signal_index=index)
        result = run_odd_lot_session(step)
        link = reconcile_session_portfolio(step,result)
        links.append(link)
        runtime = result.runtime
    assert [row.cash_after for row in links] == [D(106),D(126),D(226),D(226)]
    assert [row.event_cash for row in links] == [D(6),D(0),D(100),D(0)]
    assert [row.settled_sales for row in links] == [D(0),D(20),D(0),D(0)]
    assert [row.unsettled_sales for row in links] == [D(20),D(0),D(0),D(0)]
    assert links[0].shares_before == (("2330.TW",3),)
    assert links[-1].shares_after == (("2330.TW",1),)
    assert inputs.runtime.portfolio.cash == 100


@pytest.mark.parametrize("mutation", ["cash","shares","sale_receivable","settlement_date","settlement_amount"])
def test_session_link_refuses_cash_holdings_or_obligation_drift_without_mutation(mutation):
    inputs = _fixture()
    result = run_odd_lot_session(inputs)
    copied = deepcopy(result)
    if mutation == "cash":
        copied.runtime.portfolio.cash += 1
        copied.nav["cash"] += 1
    elif mutation == "shares":
        copied.runtime.portfolio.shares["2330.TW"] += 1
    elif mutation == "sale_receivable":
        copied.nav["sale_receivables"] = 0
    elif mutation == "settlement_date":
        copied.runtime.settlements[0]["settled_at"] = inputs.data.close.index[1]
    else:
        copied.runtime.settlements[0]["amount"] += 1
    with pytest.raises(ValueError,match="session link"):
        reconcile_session_portfolio(inputs,copied)
    assert inputs.runtime.portfolio.cash == 100
    assert result.runtime.portfolio.cash == 106


def test_actual_order_execution_link_separates_reservation_and_negative_fee_shortfall(monkeypatch):
    from test_odd_lot_durable_settlements import _fixture as trading_fixture

    from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
    from quant_fund_lab.odd_lot_paper.bridge import HistoricalSessionState
    from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput
    from quant_fund_lab.odd_lot_research import odd_lot_backtest_config

    data,research,base,_ = trading_fixture(monkeypatch,shortfall=True)
    runtime = HistoricalSessionState(PortfolioState(1000.),{},{},set(),[],[],False)
    config = odd_lot_backtest_config(base,research)
    links = []
    for index in range(29,35):
        inputs = OddLotSessionInput(runtime,data,research,config,index,29,prior_session_liquidity(data.volume))
        result = run_odd_lot_session(inputs)
        link = reconcile_session_portfolio(inputs,result)
        links.append(link)
        runtime = result.runtime
    assert [row.cash_after for row in links] == [D(970),D(960),D(960),D(960),D(960),D(960)]
    assert [row.execution_cash for row in links] == [D(-30),D(-10),D(0),D(0),D(0),D(0)]
    assert all(row.settled_sales == 0 for row in links)


def test_actual_order_execution_link_does_not_offer_future_tplus2_sale_proceeds(monkeypatch):
    from test_odd_lot_durable_settlements import _fixture as trading_fixture

    from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
    from quant_fund_lab.odd_lot_paper.bridge import HistoricalSessionState
    from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput
    from quant_fund_lab.odd_lot_research import odd_lot_backtest_config

    data,research,base,_ = trading_fixture(monkeypatch)
    runtime = HistoricalSessionState(PortfolioState(300.),{},{},set(),[],[],False)
    config = odd_lot_backtest_config(base,research)
    links = []
    for index in range(29,35):
        inputs = OddLotSessionInput(runtime,data,research,config,index,29,prior_session_liquidity(data.volume))
        result = run_odd_lot_session(inputs)
        links.append(reconcile_session_portfolio(inputs,result))
        runtime = result.runtime
    assert [row.cash_after for row in links] == [D(0),D(0),D(0),D(300),D(0),D(0)]
    assert [row.settled_sales for row in links] == [D(0),D(0),D(0),D(300),D(0),D(0)]
    assert links[1].cash_after == 0 and links[1].unsettled_sales == 300


def test_existing_session_rejects_injected_cash_drift_before_returning_a_result(monkeypatch):
    from quant_fund_lab.odd_lot_paper import session

    inputs = _fixture()
    original = session.close_odd_lot_session

    def wrong_cash(arguments):
        result = original(arguments)
        result.portfolio.cash += 1
        result.nav["cash"] += 1
        result.nav["settled_cash"] += 1
        return result

    monkeypatch.setattr(session,"close_odd_lot_session",wrong_cash)
    with pytest.raises(ValueError,match="session link portfolio cash"):
        session.run_odd_lot_session(inputs)
    assert inputs.runtime.portfolio.cash == 100
    assert inputs.runtime.portfolio.shares == {"2330.TW":3}


def test_link_interest_uses_only_prior_spendable_cash_before_new_dividend_or_settlement():
    inputs = _fixture()
    inputs = replace(inputs,config=replace(inputs.config,cash_annual_yield=.0365))
    result = run_odd_lot_session(inputs)
    link = reconcile_session_portfolio(inputs,result)
    assert link.interest == D("0.01")
    assert link.event_cash == 6 and link.cash_after == D("106.01")
    assert link.settled_sales == 0 and link.unsettled_sales == 20
