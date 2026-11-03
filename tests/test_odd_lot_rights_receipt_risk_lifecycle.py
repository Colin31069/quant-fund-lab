"""Partial receipt sale, conversion, locked final exit and cash survive restarts."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from rights_receipt_lifecycle_fixtures import (
    FINAL,
    HASHES,
    PARENT,
    RECEIPT,
    converted_case,
    post,
    project,
)

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state
from quant_fund_lab.odd_lot_paper.engine_records import EngineOrder
from quant_fund_lab.odd_lot_paper.types import StopState
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
from quant_fund_lab.odd_lot_rights.session_nav import value_session_nav


@pytest.mark.parametrize("restart", [False, True])
def test_deliver_sell_some_convert_only_remaining_then_retry_final_exit(monkeypatch, restart):
    account, runtime, inputs, _, mapping, day = converted_case(monkeypatch)
    assert runtime.portfolio.shares[RECEIPT] == 3
    assert runtime.pending[RECEIPT].quantity == 5
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="pending sales of removed holdings"):
        project(account, runtime, inputs, day, opening_stops=(mapping.final_stop,))
    projected, runtime = project(account, runtime, inputs, day, conversion_risks=(mapping,))
    assert RECEIPT not in runtime.stops and RECEIPT not in runtime.pending
    assert runtime.pending[FINAL].quantity == 3 and runtime.pending[FINAL].reason == "stop"
    assert runtime.stops[FINAL].stop == 95. and runtime.stops[FINAL].high_close == 100.
    assert dict(projected.tradable_units) == {FINAL: 0, PARENT: 5}
    assert encode_inventory(account) == before
    cash, nav, filled = [], [], []
    for index in range(31, 35):
        day = str(inputs.data.close.index[index].date())
        if restart:
            account = decode_inventory(encode_inventory(account))
            checkpoint = capture_session_state(runtime, session=day,
                origin_session=str(inputs.data.close.index[29].date()), session_offset=index-29,
                completed_index=index)
            runtime = restore_session_state(checkpoint, completed_index=index)
        current = replace(inputs, runtime=runtime, signal_index=index)
        done = post(account, current, "after-convert-"+str(index))
        account, runtime = done.account, done.execution.result.runtime
        close = str(inputs.data.close.index[index+1].date())
        marks = tuple(SecurityMark(symbol, D(100), close, close+"T16:00:00+08:00", HASHES)
                      for symbol in sorted({row.security_id for row in account.lots}))
        valued = value_session_nav(account, replace(current, sale_limits=done.execution.projection.sale_limits),
            done.execution.result, marks, (), as_of=close+"T16:01:00+08:00")
        cash.append(account.cash)
        nav.append(valued.nav)
        filled.append(sum(row["quantity"] for row in done.execution.result.fills))
        if index == 31:
            assert runtime.pending[FINAL].reason == "stop" and runtime.portfolio.shares[FINAL] == 3
            assert done.execution.result.orders[0]["outcome"] == "not_tradable"
            with pytest.raises(ValueError, match="conversion after this engine anchor"):
                project(account, runtime, current, close, conversion_risks=(mapping,))
        else:
            assert FINAL not in runtime.pending and FINAL not in runtime.stops
        assert all(row["symbol"] == FINAL for row in done.execution.result.fills)
    assert cash == [D(50), D(250), D(250), D(550)]
    assert nav == [D(1050)]*4 and filled == [0, 3, 0, 0]
    assert all(row.security_id == PARENT for row in account.lots)
    assert [(row["symbol"], row["amount"]) for row in runtime.settlements] == [(RECEIPT, 200.), (FINAL, 300.)]
    assert all(row["settled_at"] is not None for row in runtime.settlements)
    assert account.book.positions[0].delivered == 5 and account.book.positions[0].pending == 0
    assert decode_inventory(encode_inventory(account)) == account


@pytest.mark.parametrize("change", ["missing_exit", "old_quantity", "reason", "target", "action", "invent_exit", "mutable", "duplicate"])
def test_invalid_conversion_risk_mapping_preserves_original_inventory(monkeypatch, change):
    account, runtime, inputs, _, mapping, day = converted_case(monkeypatch)
    before = encode_inventory(account)
    mappings = (mapping,)
    if change == "missing_exit":
        mappings = (replace(mapping, final_exit=None),)
    elif change == "old_quantity":
        mappings = (replace(mapping, final_exit=replace(mapping.final_exit, quantity=5)),)
    elif change == "reason":
        mappings = (replace(mapping, final_exit=replace(mapping.final_exit, reason="entry")),)
    elif change == "target":
        stop = StopState(PARENT, 95., 100., .05)
        mappings = (replace(mapping, final_stop=stop, final_exit=replace(mapping.final_exit, symbol=PARENT)),)
    elif change == "action":
        mappings = (replace(mapping, conversion_action_id="partial-sale"),)
    elif change == "invent_exit":
        runtime.pending.pop(RECEIPT)
        # The source engine anchor does not serialize pending orders. A supplied
        # extra exit must still be justified by the runtime's actual receipt exit.
    elif change == "mutable":
        mappings = [mapping]
    else:
        mappings = (mapping, mapping)
    with pytest.raises((ValueError, TypeError)):
        project(account, runtime, inputs, day, conversion_risks=mappings)
    assert encode_inventory(account) == before


def test_partial_conversion_preserves_both_receipt_and_final_pending_exits(monkeypatch):
    account, runtime, inputs, _, mapping, day = converted_case(monkeypatch, conversion_units=2)
    before = encode_inventory(account)
    projected, restored = project(account, runtime, inputs, day, conversion_risks=(mapping,))
    assert dict(projected.checkpoint.shares) == {PARENT: 5, RECEIPT: 1, FINAL: 2}
    assert restored.pending[RECEIPT].quantity == 1 and restored.pending[FINAL].quantity == 2
    assert restored.pending[RECEIPT].reason == restored.pending[FINAL].reason == "stop"
    assert restored.stops[RECEIPT].stop == 105. and restored.stops[FINAL].stop == 95.
    assert encode_inventory(account) == before


def test_receipt_buy_needs_explicit_cancellation_when_its_identity_is_removed(monkeypatch):
    account, runtime, inputs, _, mapping, day = converted_case(monkeypatch)
    runtime.pending[RECEIPT] = EngineOrder("BUY", 2, "entry")
    mapping = replace(mapping, final_exit=None)
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="explicit cancellation"):
        project(account, runtime, inputs, day, conversion_risks=(mapping,))
    _, restored = project(account, runtime, inputs, day,
        conversion_risks=(replace(mapping, cancel_receipt_buy=True),))
    assert RECEIPT not in restored.pending and not restored.pending
    assert encode_inventory(account) == before


def test_declared_receipt_exit_priority_replaces_a_competing_final_buy(monkeypatch):
    account, runtime, inputs, _, mapping, day = converted_case(monkeypatch)
    runtime.pending[FINAL] = EngineOrder("BUY", 2, "entry")
    _, restored = project(account, runtime, inputs, day, conversion_risks=(mapping,))
    assert restored.pending[FINAL].side == "SELL" and restored.pending[FINAL].quantity == 3
    assert restored.pending[FINAL].reason == "stop"
