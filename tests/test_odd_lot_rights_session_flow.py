"""Actual trades/settlements and rights payments consume the same audited cash."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_durable_settlements import _fixture
from test_odd_lot_rights_transitions import HASHES, event

from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.bridge import HistoricalSessionState
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput, run_odd_lot_session
from quant_fund_lab.odd_lot_research import odd_lot_backtest_config
from quant_fund_lab.odd_lot_rights.audit import audit_rights
from quant_fund_lab.odd_lot_rights.inventory import (
    RightsInventory,
    SecurityLot,
    post_rights_transition,
)
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.session_flow import post_engine_session
from quant_fund_lab.odd_lot_rights.transitions import grant_entitlements, subscribe_batch
from quant_fund_lab.odd_lot_rights.types import (
    EntitlementLeg,
    PaymentRequest,
    PaymentTerms,
    RightsBook,
)


def _start(monkeypatch, shortfall=False):
    data,research,base,_ = _fixture(monkeypatch,shortfall=shortfall)
    runtime = HistoricalSessionState(PortfolioState(base.initial_cash),{},{},set(),[],[],False)
    account = RightsInventory(D(str(base.initial_cash)),(),RightsBook(D(str(base.initial_cash))),())
    config = odd_lot_backtest_config(base,research)
    return data,research,config,runtime,account


def _step(data,research,config,runtime,index):
    inputs = OddLotSessionInput(runtime,data,research,config,index,29,prior_session_liquidity(data.volume))
    return inputs,run_odd_lot_session(inputs)


def _post(account,inputs,result,action=None):
    stamp = str(inputs.data.close.index[inputs.signal_index+1].date())+"T16:00:00+08:00"
    return post_engine_session(account,action or stamp,inputs,result,as_of=stamp,
                               available_at=stamp,evidence_sha256=HASHES)


@pytest.mark.parametrize("restart", [False,True])
@pytest.mark.parametrize("shortfall", [False,True])
def test_real_session_flow_tracks_cash_shares_settlements_and_noop(monkeypatch,restart,shortfall):
    data,research,config,runtime,current = _start(monkeypatch,shortfall)
    cash=[]
    for index in range(29,35):
        inputs,result = _step(data,research,config,runtime,index)
        current = _post(current,inputs,result)
        cash.append(current.cash)
        assert current.cash == D(str(result.runtime.portfolio.cash))
        owned = {}
        for row in current.lots:
            owned[row.security_id] = owned.get(row.security_id,0)+row.units
        assert owned == {key:value for key,value in result.runtime.portfolio.shares.items() if value}
        assert audit_rights(current.book,initial_cash=current.initial_cash,recorded_movements=current.postings).passed
        assert _post(current,inputs,result) is current
        if restart:
            current = decode_inventory(encode_inventory(current))
        runtime = result.runtime
    assert cash == ([D(970),D(960),D(960),D(960),D(960),D(960)] if shortfall else
                    [D(0),D(0),D(0),D(300),D(0),D(0)])
    assert len(current.book.receipts) == 6


def test_actual_posted_tplus2_cash_funds_next_explicit_rights_payment_only_after_credit(monkeypatch):
    data,research,config,runtime,current = _start(monkeypatch)
    # Entitlement on acquired parent units after the first actual BUY.
    inputs,result = _step(data,research,config,runtime,29)
    current = _post(current,inputs,result)
    day = str(data.close.index[30].date())
    contract = replace(event(),parent_security_id="2330.TW",ex_session=day,
        available_at=day+"T08:00:00+08:00",
        legs=(EntitlementLeg("paid","new-share-class","subscription",D(1)),))
    current = post_rights_transition(current,grant_entitlements(current.book,"grant",contract,3,
                                     as_of=day+"T16:01:00+08:00"))
    right = current.book.positions[0]
    payment = PaymentTerms(right.key,D(10),day,"2025-12-31",day+"T08:00:00+08:00",HASHES)
    request = (PaymentRequest(payment,1,D(0)),)
    runtime = result.runtime
    for index in range(30,33):
        inputs,result = _step(data,research,config,runtime,index)
        current = _post(current,inputs,result)
        stamp = str(data.close.index[index+1].date())+"T16:01:00+08:00"
        if index < 32:
            with pytest.raises(ValueError,match="insufficient usable cash"):
                subscribe_batch(current.book,"pay",request,as_of=stamp)
        else:
            assert current.cash == 300
            current = post_rights_transition(current,subscribe_batch(current.book,"pay",request,as_of=stamp))
            assert current.cash == 290 and current.book.positions[0].pending == 1
        runtime = result.runtime
    assert audit_rights(current.book,initial_cash=D(300),recorded_movements=current.postings).passed


@pytest.mark.parametrize("change", ["cash","holdings","evidence","action","future"])
def test_session_transfer_rejects_wrong_anchor_changed_replay_or_future_evidence(monkeypatch,change):
    data,research,config,runtime,current = _start(monkeypatch)
    inputs,result = _step(data,research,config,runtime,29)
    if change == "cash":
        current = replace(current,initial_cash=D(301),book=RightsBook(D(301)))
    elif change == "holdings":
        lots = (SecurityLot("opening","2330.TW",1,"2020-01-01"),)
        current = replace(current,initial_lots=lots,lots=lots)
    else:
        current = _post(current,inputs,result)
    before = encode_inventory(current)
    stamp = str(data.close.index[30].date())+"T16:00:00+08:00"
    with pytest.raises(ValueError):
        post_engine_session(current,stamp if change != "action" else "different-key",inputs,result,
            as_of=stamp,available_at=stamp if change != "future" else "2026-01-01T08:00:00+08:00",
            evidence_sha256=("c"*64,) if change == "evidence" else HASHES)
    assert encode_inventory(current) == before


def test_real_engine_sale_of_owned_but_not_yet_tradable_lots_cannot_be_posted(monkeypatch):
    from quant_fund_lab.odd_lot_paper.engine_records import EngineStop

    data,research,config,runtime,_ = _start(monkeypatch)
    runtime.portfolio.cash = 0.
    runtime.portfolio.shares = {"2330.TW":3}
    runtime.stops = {"2330.TW":EngineStop(95.,100.,.05)}
    lots = (SecurityLot("opening","2330.TW",3,"2025-01-01"),)
    current = RightsInventory(D(0),lots,RightsBook(D(0)),lots)
    inputs,result = _step(data,research,config,runtime,30)
    assert any(row["side"] == "SELL" and row["quantity"] == 3 for row in result.fills)
    before = encode_inventory(current)
    with pytest.raises(ValueError,match="actual lot tradability"):
        _post(current,inputs,result)
    assert encode_inventory(current) == before


def test_roundtrip_preserves_all_session_checkpoints_not_just_final_cash(monkeypatch):
    data,research,config,runtime,current = _start(monkeypatch)
    uninterrupted = current
    for index in range(29,35):
        inputs,result = _step(data,research,config,runtime,index)
        uninterrupted = _post(uninterrupted,inputs,result)
        current = decode_inventory(encode_inventory(_post(current,inputs,result)))
        assert encode_inventory(current) == encode_inventory(uninterrupted)
        runtime = result.runtime
