"""Corporate lot changes and actual trades publish one independently audited account."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_session_flow import _start
from test_odd_lot_rights_transitions import HASHES
from test_odd_lot_session_events import _fixture as event_inputs

from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.engine_records import EngineStop
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput
from quant_fund_lab.odd_lot_rights.audit import audit_rights
from quant_fund_lab.odd_lot_rights.inventory import RightsInventory, SecurityLot
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
from quant_fund_lab.odd_lot_rights.lot_events import LotRoundingPolicy, OpeningLotEvent
from quant_fund_lab.odd_lot_rights.lot_flow import run_and_post_lot_session
from quant_fund_lab.odd_lot_rights.session_nav import value_session_nav
from quant_fund_lab.odd_lot_rights.types import RightsBook

POLICY = LotRoundingPolicy(1, "latest_contributor_release")


def split_case(monkeypatch, ratio=D(2)):
    data, research, config, runtime, _ = _start(monkeypatch)
    opening = str(data.close.index[31].date())
    release = str(data.close.index[32].date())
    runtime.portfolio = PortfolioState(0., {"2330.TW": 6})
    runtime.stops = {"2330.TW": EngineStop(105., 110., .05)}
    lots = (SecurityLot("a-free", "2330.TW", 2, opening),
            SecurityLot("b-locked", "2330.TW", 4, release))
    account = RightsInventory(D(0), lots, RightsBook(D(0)), lots)
    splits = data.stock_splits.copy()
    splits.loc[data.close.index[31], "2330.TW"] = float(ratio)
    raw_open, raw_close = data.raw_open.copy(), data.raw_close.copy()
    raw_open.loc[data.close.index[31]:, "2330.TW"] /= float(ratio)
    raw_close.loc[data.close.index[31]:, "2330.TW"] /= float(ratio)
    data = replace(data, stock_splits=splits, raw_open=raw_open, raw_close=raw_close)
    events = (OpeningLotEvent("d"*64, "2330.TW", opening, "split", ratio,
                              opening+"T08:00:00+08:00", HASHES),)
    inputs = OddLotSessionInput(runtime, data, research, config, 30, 29,
                               prior_session_liquidity(data.volume))
    return account, inputs, events, opening


def post(account, inputs, events=(), action="session", **extra):
    opening = str(inputs.data.close.index[inputs.signal_index+1].date())
    return run_and_post_lot_session(account, events, POLICY, inputs, action,
        opening_at=opening+"T09:00:00+08:00", as_of=opening+"T16:00:00+08:00",
        available_at=opening+"T16:00:00+08:00", evidence_sha256=HASHES, **extra)


@pytest.mark.parametrize("ratio,remaining", [(D(2), 8), (D("0.5"), 2)])
def test_split_fill_and_released_next_sale_post_and_restart_without_losing_lot_locks(monkeypatch, ratio, remaining):
    original, inputs, events, _ = split_case(monkeypatch, ratio)
    before = encode_inventory(original)
    first = post(original, inputs, events)
    assert first.applied and first.account.cash == 0
    assert [(lot.right_key, lot.units) for lot in first.account.lots] == [("b-locked", remaining)]
    assert audit_rights(first.account.book, initial_cash=D(0), recorded_movements=first.account.postings).passed
    current = decode_inventory(encode_inventory(first.account))
    assert current == first.account
    replay = post(current, inputs, events, recorded_before=original)
    assert not replay.applied and replay.account is current
    with pytest.raises(ValueError, match="original recorded account prefix"):
        post(current, inputs, events)
    following = replace(inputs, runtime=first.execution.result.runtime, signal_index=31)
    second = post(current, following, action="second")
    assert not second.account.lots and second.account.cash == 0
    assert second.execution.result.fills[0]["quantity"] == remaining
    assert decode_inventory(encode_inventory(second.account)) == second.account
    assert encode_inventory(original) == before


def test_terminal_can_remove_locked_lots_without_disguising_it_as_a_trade(monkeypatch):
    account, inputs, _, opening = split_case(monkeypatch)
    splits = inputs.data.stock_splits.copy()*0
    terminal = inputs.data.terminal_returns.copy()
    terminal.loc[inputs.data.close.index[31], "2330.TW"] = -.5
    data = replace(inputs.data, stock_splits=splits, terminal_returns=terminal)
    inputs = replace(inputs, data=data)
    event = OpeningLotEvent("e"*64, "2330.TW", opening, "terminal", None,
                            opening+"T08:00:00+08:00", HASHES)
    done = post(account, inputs, (event,))
    assert done.account.cash == 300 and not done.account.lots
    assert not done.execution.result.fills and not done.execution.result.runtime.settlements
    assert decode_inventory(encode_inventory(done.account)) == done.account


def test_fractional_reverse_split_dividend_and_later_cil_share_the_posted_cash_and_nav():
    inputs = event_inputs()
    day = str(inputs.data.close.index[1].date())
    lots = (SecurityLot("a-free", "2330.TW", 1, day),
            SecurityLot("b-locked", "2330.TW", 2, "2025-01-01"))
    account = RightsInventory(D(100), lots, RightsBook(D(100)), lots)
    split = OpeningLotEvent("d"*64, "2330.TW", day, "split", D("0.5"),
                            day+"T08:00:00+08:00", HASHES)
    cash, nav = [], []
    for index in range(4):
        current = replace(inputs, signal_index=index)
        done = post(account, current, (split,) if index == 0 else (), action="fraction-"+str(index))
        account = decode_inventory(encode_inventory(done.account))
        assert account.lots == (SecurityLot("b-locked", "2330.TW", 1, "2025-01-01"),)
        result = done.execution.result
        close = str(inputs.data.close.index[index+1].date())
        stamp = close+"T16:01:00+08:00"
        mark = SecurityMark("2330.TW", D(196), close, stamp, HASHES)
        valued = value_session_nav(account, replace(current, sale_limits=done.execution.projection.sale_limits),
                                   result, (mark,), (), as_of=stamp)
        cash.append(account.cash)
        nav.append(valued.nav)
        inputs = replace(inputs, runtime=result.runtime)
    assert cash == [D(106), D(126), D(226), D(226)]
    assert nav == [D(420), D(420), D(422), D(422)]
    assert not inputs.runtime.receivables
