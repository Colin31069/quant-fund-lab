"""One day entry point matches independent staged receipt lifecycle operations."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from rights_receipt_lifecycle_fixtures import HASHES, LOT_POLICY, RECEIPT, converted_case

from quant_fund_lab.odd_lot_paper.bridge import restore_session_state
from quant_fund_lab.odd_lot_paper.types import StopState
from quant_fund_lab.odd_lot_rights.authorization_archive import AuthorizedRightsAccount
from quant_fund_lab.odd_lot_rights.close_commands import RightsCloseCommand, apply_close_commands
from quant_fund_lab.odd_lot_rights.day_workflow import RightsDayRequest, advance_rights_day
from quant_fund_lab.odd_lot_rights.inventory_codec import encode_inventory


def request(account, inputs, action, commands=(), **extra):
    day = str(inputs.data.close.index[inputs.signal_index+1].date())
    return RightsDayRequest(account, inputs, (), LOT_POLICY, action,
        day+"T09:00:00+08:00", day+"T16:00:00+08:00", day+"T16:00:00+08:00", HASHES,
        commands, day+"T16:10:00+08:00", **extra)


def first_request(context):
    original = AuthorizedRightsAccount(context["initial_account"], context["policy"])
    auth = context["authorization"]
    day = auth.as_of[:10]
    commands = (
        RightsCloseCommand("grant", day+"T16:01:00+08:00", "grant", context["event"], 5),
        RightsCloseCommand("pay", auth.as_of, "pay", auth, None),
        *(RightsCloseCommand(name, stamp, "deliver", terms, units)
          for name, units, terms, stamp in context["deliveries"]))
    return request(original, context["initial_inputs"], "first", commands,
                   opening_stops=(StopState(RECEIPT, 105., 110., .05),))


def test_common_day_entry_matches_staged_delivery_conversion_and_replay(monkeypatch):
    context = converted_case(monkeypatch, workflow_context=True)
    start = first_request(context)
    initial = encode_inventory(start.account.inventory)
    first = advance_rights_day(start)
    assert encode_inventory(first.account.inventory) == encode_inventory(context["first_day_account"])
    assert first.projection == context["first_projection"]
    assert first.account.inventory.cash == 50 and len(first.account.authorizations) == 1
    runtime = restore_session_state(first.projection.checkpoint, completed_index=30)
    inputs = replace(context["initial_inputs"], runtime=runtime, signal_index=30)
    day = str(inputs.data.close.index[31].date())
    command = RightsCloseCommand("convert", day+"T16:01:00+08:00", "convert", context["conversion_terms"], 3)
    second_request = request(first.account, inputs, "partial-sale", (command,),
                             conversion_risks=(context["mapping"],))
    second = advance_rights_day(second_request)
    assert encode_inventory(second.account.inventory) == encode_inventory(context["converted_account"])
    assert second.projection.checkpoint.pending[0].symbol == context["mapping"].final_stop.symbol
    assert second.projection.checkpoint.pending[0].quantity == 3
    replay = advance_rights_day(replace(second_request, account=second.account, recorded_before=first.account))
    assert not replay.applied and replay.account is second.account
    assert replay.projection == second.projection
    first_replay = advance_rights_day(replace(start, account=first.account, recorded_before=start.account))
    assert not first_replay.applied and first_replay.account is first.account
    assert encode_inventory(start.account.inventory) == initial


@pytest.mark.parametrize("change", ["before_close", "wrong_day", "unordered", "duplicate", "late_failure", "no_anchor"])
def test_close_batch_invalid_phase_or_late_failure_does_not_publish_partial_state(monkeypatch, change):
    context = converted_case(monkeypatch, workflow_context=True)
    source = first_request(context)
    empty = replace(source, commands=(), opening_stops=())
    closed = advance_rights_day(empty).account
    commands = source.commands
    if change == "before_close":
        commands = (replace(commands[0], as_of=source.close_at[:10]+"T15:59:59+08:00"),)
    elif change == "wrong_day":
        commands = (replace(commands[0], as_of="2025-01-01T16:01:00+08:00"),)
    elif change == "unordered":
        commands = tuple(reversed(commands))
    elif change == "duplicate":
        commands = (commands[0], commands[0])
    elif change == "late_failure":
        commands = (*commands[:3], replace(commands[3], units=4))
    before = encode_inventory(closed.inventory)
    with pytest.raises(ValueError):
        apply_close_commands(closed, "missing" if change == "no_anchor" else "first", commands)
    assert encode_inventory(closed.inventory) == before
    assert closed.inventory.cash == D(100) and closed.authorizations == ()


@pytest.mark.parametrize("change", ["no_stop", "no_exit_transfer", "future_projection"])
def test_day_failure_keeps_original_authorized_account_intact(monkeypatch, change):
    context = converted_case(monkeypatch, workflow_context=True)
    source = first_request(context)
    before = encode_inventory(source.account.inventory)
    if change == "no_stop":
        source = replace(source, opening_stops=())
    elif change == "future_projection":
        source = replace(source, projection_at=source.close_at[:10]+"T16:03:00+08:00")
    else:
        first = advance_rights_day(source)
        inputs = context["partial_inputs"]
        day = str(inputs.data.close.index[31].date())
        source = request(first.account, inputs, "partial-sale", (
            RightsCloseCommand("convert", day+"T16:01:00+08:00", "convert", context["conversion_terms"], 3),),
            opening_stops=(context["mapping"].final_stop,))
        before = encode_inventory(source.account.inventory)
    with pytest.raises(ValueError):
        advance_rights_day(source)
    assert encode_inventory(source.account.inventory) == before
