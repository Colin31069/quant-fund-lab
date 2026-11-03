"""Cash timing and fee shortfalls remain correct across SQLite account restarts."""
import json
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest
from test_odd_lot_durable_events import _business, _run

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.event_codec import decode_event
from quant_fund_lab.odd_lot_paper.replay import ReplayIdentity
from quant_fund_lab.odd_lot_research import OddLotResearchConfig


def _fixture(monkeypatch, *, shortfall=False):
    symbols = ["2330.TW"] if shortfall else ["2330.TW","2317.TW"]
    dates = pd.bdate_range("2024-01-02",periods=36)
    prices = pd.DataFrame(10. if shortfall else 100.,index=dates,columns=symbols)
    data = MarketData(prices,prices,prices*1000000,base_currency="TWD")
    research = OddLotResearchConfig(strategy="momentum",max_positions=1,
        max_weight=.01 if shortfall else 1.,rebalance_every=1,min_commission=20. if shortfall else 0.,
        commission_bps=0.,slippage_bps=0.,fill_fraction=1.,max_participation=1.,impact_coefficient=0.,
        instrument_rules={symbol:{"kind":"stock","sell_tax_bps":0.,"price_limit_pct":.1} for symbol in symbols})
    base = BacktestConfig(initial_cash=1000. if shortfall else 300.,base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    identity = ReplayIdentity("a"*64,"offline-fixture","offline-calendar",str(dates[29].date()))
    def targets(history,*args):
        weights = pd.Series(0.,index=history.columns)
        if len(history) == 30:
            weights.iloc[0] = research.max_weight
        elif len(history) >= 32 and not shortfall:
            weights.iloc[1] = 1.
        return pd.Series(1.,index=history.columns),weights
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",targets)
    return data,research,base,identity


def _events(path, category):
    with sqlite3.connect(path) as db:
        return [decode_event(json.loads(row[0])) for row in db.execute(
            "SELECT payload FROM session_events WHERE category=? ORDER BY session,ordinal",(category,))]


@pytest.mark.parametrize("count",[32,34])
def test_sold_proceeds_cannot_fund_opening_orders_on_or_before_settlement_day(tmp_path,monkeypatch,count):
    inputs = _fixture(monkeypatch)
    dates = inputs[0].close.index
    path,reference = tmp_path/"split.sqlite",tmp_path/"full.sqlite"
    prefix = _run(path,inputs,count=count,create=True)
    if count == 32:
        assert prefix.checkpoint.cash == 0.
        sale = next(row for row in prefix.checkpoint.settlements if row.side == "SELL")
        assert sale.amount == 300. and sale.remaining_sessions == 2 and sale.settled_at is None
    else:
        assert prefix.checkpoint.cash == 300. and not any(quantity for _,quantity in prefix.checkpoint.shares)
        assert not prefix.checkpoint.pending
    final = _run(path,inputs)
    whole = _run(reference,inputs,create=True)
    assert final.checkpoint == whole.checkpoint and _business(path) == _business(reference)
    fills = _events(path,"fills")
    assert [(str(row["timestamp"].date()),row["symbol"],row["side"],row["quantity"]) for row in fills] == [
        (str(dates[30].date()),"2330.TW","BUY",3),
        (str(dates[31].date()),"2330.TW","SELL",3),
        (str(dates[34].date()),"2317.TW","BUY",3)]
    navs = _events(path,"nav")
    assert [row["cash"] for row in navs] == [0.,0.,0.,300.,0.,0.]
    assert [row["sale_receivables"] for row in navs] == [0.,300.,300.,0.,0.,0.]
    assert [row["equity"] for row in navs] == [300.]*6
    assert audit_accounting(path).passed


def test_sale_below_minimum_fee_is_deducted_once_not_again_when_payable_settles(tmp_path,monkeypatch):
    inputs = _fixture(monkeypatch,shortfall=True)
    path,reference = tmp_path/"split.sqlite",tmp_path/"full.sqlite"
    first = _run(path,inputs,count=32,create=True)
    assert first.checkpoint.cash == 960.
    sale = next(row for row in first.checkpoint.settlements if row.side == "SELL")
    assert sale.amount == -10. and sale.remaining_sessions == 2
    assert _events(path,"nav")[-1]["sale_payables"] == 10.
    final = _run(path,inputs)
    _run(reference,inputs,create=True)
    assert final.checkpoint.cash == 960. and _business(path) == _business(reference)
    navs = _events(path,"nav")
    assert [row["cash"] for row in navs] == [970.,960.,960.,960.,960.,960.]
    assert [row["sale_payables"] for row in navs] == [0.,10.,10.,0.,0.,0.]
    assert [row["equity"] for row in navs] == [980.,960.,960.,960.,960.,960.]
    assert audit_accounting(path).passed
    before = path.read_bytes()
    assert _run(path,inputs).committed_sessions == 0 and path.read_bytes() == before


def test_partial_entry_expires_without_topup_after_sql_restart(tmp_path,monkeypatch):
    data,research,base,identity = _fixture(monkeypatch,shortfall=True)
    prices = data.close*0+1.
    data = MarketData(prices,prices,prices*1000000,base_currency="TWD")
    research = replace(research,strategy="equal_weight",max_weight=1.,min_commission=0.,fill_fraction=.5)
    def targets(history,*args):
        return pd.Series(1.,index=history.columns),pd.Series(1.,index=history.columns)
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",targets)
    inputs = data,research,base,identity
    path,reference = tmp_path/"split.sqlite",tmp_path/"full.sqlite"
    initial = _run(path,inputs,count=31,create=True)
    assert initial.checkpoint.cash == 501. and initial.checkpoint.shares == (("2330.TW",499),)
    assert not initial.checkpoint.pending
    final = _run(path,inputs)
    _run(reference,inputs,create=True)
    orders = _events(path,"orders")
    assert len(orders) == 1 and orders[0]["status"] == "partial_expired"
    assert (orders[0]["requested_quantity"],orders[0]["filled_quantity"],orders[0]["expired_quantity"]) == (999,499,500)
    fills = _events(path,"fills")
    assert len(fills) == 1 and fills[0]["quantity"] == 499
    assert final.checkpoint.cash == 501. and final.checkpoint.shares == (("2330.TW",499),)
    assert _business(path) == _business(reference) and audit_accounting(path).passed


def test_daily_stop_exit_retry_survives_unquoted_open_and_sql_restart(tmp_path,monkeypatch):
    data,research,base,identity = _fixture(monkeypatch)
    research = replace(research,rebalance_every=1000)
    close,opening = data.close.copy(),data.open.copy()
    close.iloc[31:,0] = 90.
    opening.iloc[32:,0] = 90.
    opening.iloc[32,0] = float("nan")
    data = MarketData(opening,close,data.volume,base_currency="TWD")
    def targets(history,*args):
        weights = pd.Series(0.,index=history.columns)
        weights.iloc[0] = 1.
        return pd.Series(1.,index=history.columns),weights
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",targets)
    inputs = data,research,base,identity
    path,reference = tmp_path/"split.sqlite",tmp_path/"full.sqlite"
    pending = _run(path,inputs,count=33,create=True).checkpoint
    assert pending.shares == (("2330.TW",3),) and len(pending.stops) == len(pending.pending) == 1
    assert pending.pending[0].side == "SELL" and pending.pending[0].reason == "stop"
    assert pending.pending[0].quantity == 3 and pending.stops[0].stop == 95.
    final = _run(path,inputs)
    _run(reference,inputs,create=True)
    assert final.checkpoint.cash == 270. and not final.checkpoint.stops and not final.checkpoint.pending
    assert not any(quantity for _,quantity in final.checkpoint.shares)
    sells = [row for row in _events(path,"orders") if row["side"] == "SELL"]
    assert len(sells) == 2 and sells[0]["filled_quantity"] == 0 and sells[1]["filled_quantity"] == 3
    assert all(row["reason"] == "stop" for row in sells)
    assert [str(row["timestamp"].date()) for row in sells] == [str(day.date()) for day in data.close.index[32:34]]
    assert _business(path) == _business(reference) and audit_accounting(path).passed
