"""Durable event boundaries reconcile to hand-calculated shares, cash and NAV."""
import json
import sqlite3
from dataclasses import fields, replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.event_codec import decode_event
from quant_fund_lab.odd_lot_paper.replay import ReplayIdentity, _replay_account
from quant_fund_lab.odd_lot_research import OddLotResearchConfig


def _fixture(monkeypatch):
    dates = pd.bdate_range("2024-01-02",periods=36)
    adjusted = pd.DataFrame(100.,index=dates,columns=["2330.TW"])
    raw = adjusted.copy()
    raw.iloc[32:,0] = 196.
    dividends, splits = adjusted*0, adjusted*0+1
    dividends.iloc[32,0], splits.iloc[32,0] = 2., .5
    prices = adjusted*float("nan")
    prices.iloc[34,0] = 200.
    delivery = pd.DataFrame(pd.NaT,index=dates,columns=adjusted.columns)
    delivery.iloc[32,0] = dates[34]
    data = MarketData(adjusted,adjusted,adjusted*100000,raw_open=raw,raw_close=raw,
        reference=raw.shift(1),dividends=dividends,stock_splits=splits,
        cash_in_lieu_prices=prices,cash_in_lieu_settlement_dates=delivery,base_currency="TWD")
    research = OddLotResearchConfig(strategy="equal_weight",max_weight=.3,min_commission=0,
        commission_bps=0,slippage_bps=0,fill_fraction=1,max_participation=1,impact_coefficient=0)
    base = BacktestConfig(initial_cash=1000,base_currency="TWD",strategy=StrategyConfig(warmup_days=30))
    identity = ReplayIdentity("a"*64,"offline-fixture","offline-calendar",str(dates[29].date()))
    def targets(history,*args):
        return pd.Series(1.,index=history.columns),pd.Series(.3,index=history.columns)
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",targets)
    return data,research,base,identity


def _prefix(data, count):
    return replace(data,**{field.name:getattr(data,field.name).iloc[:count].copy()
        for field in fields(data) if isinstance(getattr(data,field.name),pd.DataFrame)})


def _run(path, inputs, *, count=None, create=False, fault=None):
    data,research,base,identity = inputs
    return _replay_account(path,_prefix(data,count) if count else data,research,base,identity,
        create=create,snapshot_root=path.parent/"snapshots",_fault=fault)


def _business(path):
    with sqlite3.connect(path) as db:
        states = db.execute("SELECT session,state_json,input_digest FROM session_checkpoints ORDER BY session").fetchall()
        events = db.execute("SELECT session,category,ordinal,payload FROM session_events WHERE category!='snapshot' ORDER BY session,category,ordinal").fetchall()
    return states,events


@pytest.mark.parametrize("count",list(range(30,37)))
def test_daily_sql_restart_across_dividend_reverse_split_and_deferred_cash(tmp_path,monkeypatch,count):
    inputs = _fixture(monkeypatch)
    full,split = tmp_path/"full.sqlite",tmp_path/"split.sqlite"
    reference = _run(full,inputs,create=True)
    prefix = _run(split,inputs,count=count,create=True)
    state = prefix.checkpoint
    if count == 30:
        assert state.cash == 1000. and not state.shares and not state.settlements
    elif count in {31,32}:
        assert state.cash == 700. and state.shares == (("2330.TW",3),)
        assert len(state.settlements) == 1 and state.settlements[0].remaining_sessions == 33-count
    elif count in {33,34}:
        assert state.cash == 706. and state.shares == (("2330.TW",1),)
        assert state.receivable_value == 98. and len(state.receivables) == 1
    else:
        assert state.cash == 806. and not state.receivables
    actual = _run(split,inputs)
    assert actual.checkpoint == reference.checkpoint
    assert actual.checkpoint.cash == 806. and actual.checkpoint.shares == (("2330.TW",1),)
    assert actual.checkpoint.receivable_value == 0. and not actual.checkpoint.receivables
    assert _business(full) == _business(split)
    assert audit_accounting(split).passed
    with sqlite3.connect(split) as db:
        navs = [decode_event(json.loads(row[0])) for row in db.execute(
            "SELECT payload FROM session_events WHERE category='nav' ORDER BY session")]
        actions = [decode_event(json.loads(row[0])) for row in db.execute(
            "SELECT payload FROM session_events WHERE category='actions' ORDER BY session,ordinal")]
    assert [row["cash"] for row in navs] == [700.,700.,706.,706.,806.,806.]
    assert [row["equity"] for row in navs] == [1000.,1000.,1000.,1000.,1002.,1002.]
    assert [row["action"] for row in actions] == ["cash_dividend","stock_split","cash_in_lieu_settlement"]
    before = split.read_bytes()
    assert _run(split,inputs).committed_sessions == 0 and split.read_bytes() == before


@pytest.mark.parametrize("event_index",[32,34])
def test_event_day_interruption_rolls_back_cash_shares_rights_and_events(tmp_path,monkeypatch,event_index):
    inputs = _fixture(monkeypatch)
    path,reference = tmp_path/"interrupted.sqlite",tmp_path/"reference.sqlite"
    _run(path,inputs,count=event_index,create=True)
    before = _business(path)
    def interrupt(stage):
        if stage == "events":
            raise RuntimeError("interruption after corporate-action events")
    with pytest.raises(RuntimeError,match="interruption"):
        _run(path,inputs,count=event_index+1,fault=interrupt)
    assert _business(path) == before and audit_accounting(path).passed
    _run(path,inputs)
    _run(reference,inputs,create=True)
    assert _business(path) == _business(reference)
    assert audit_accounting(path).passed
