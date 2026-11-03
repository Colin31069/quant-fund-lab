"""Build combined-ledger requests for the actual receipt conversion lifecycle."""
from dataclasses import replace
from decimal import Decimal as D

from rights_receipt_lifecycle_fixtures import HASHES, converted_case
from test_odd_lot_rights_day_workflow import first_request, request

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state
from quant_fund_lab.odd_lot_rights.close_commands import RightsCloseCommand
from quant_fund_lab.odd_lot_rights.durable_day_workflow import DurableRightsDay, day_settings_sha256
from quant_fund_lab.odd_lot_rights.engine_checkpoint import RightsEngineCheckpoint
from quant_fund_lab.odd_lot_rights.engine_checkpoint_codec import encode_engine_rights
from quant_fund_lab.odd_lot_rights.engine_ledger_types import RightsLedgerConfig, payload_digest
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark


def initial_day(monkeypatch):
    context = converted_case(monkeypatch, workflow_context=True)
    source = first_request(context)
    day = source.close_at[:10]
    marks = tuple(SecurityMark(symbol, D(100), day, source.close_at, HASHES)
                  for symbol in ("PARENT.TW", "RECEIPT.TW"))
    durable = DurableRightsDay(source, marks, (), source.projection_at)
    origin = str(source.inputs.data.close.index[29].date())
    engine = capture_session_state(source.inputs.runtime, session=origin, origin_session=origin,
                                   session_offset=0, completed_index=29)
    initial = RightsEngineCheckpoint(engine, source.account)
    config = RightsLedgerConfig(source.account.policy.policy_sha256, "a"*64, "b"*64,
        day_settings_sha256(durable), "c"*64, payload_digest(encode_engine_rights(initial)))
    return context, initial, config, durable


def next_day(context, previous, index):
    runtime = restore_session_state(previous.engine, completed_index=index)
    inputs = replace(context["initial_inputs"], runtime=runtime, signal_index=index)
    day = str(inputs.data.close.index[index+1].date())
    commands, extra = (), {}
    if index == 30:
        commands = (RightsCloseCommand("convert", day+"T16:01:00+08:00", "convert",
                                      context["conversion_terms"], 3),)
        extra = {"conversion_risks": (context["mapping"],)}
    source = request(previous.account, inputs, "durable-"+str(index), commands, **extra)
    symbols = ["PARENT.TW", "FINAL.TW"] if index in (30, 31) else ["PARENT.TW"]
    marks = tuple(SecurityMark(symbol, D(100), day, source.close_at, HASHES) for symbol in sorted(symbols))
    return DurableRightsDay(source, marks, (), source.projection_at)
