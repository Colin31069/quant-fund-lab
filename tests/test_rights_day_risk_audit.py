"""Independent risk equations reject lost exits and projection drift before SQL."""
from dataclasses import asdict, replace

import pytest
from rights_durable_day_fixtures import initial_day, next_day

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state
from quant_fund_lab.odd_lot_rights.day_risk_audit import audit_day_risk, engine_risk_groups
from quant_fund_lab.odd_lot_rights.durable_day_workflow import (
    commit_rights_day,
    prepare_durable_day,
)
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.engine_ledger_types import payload_digest


def conversion_case(tmp_path, monkeypatch):
    context, initial, config, first = initial_day(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"risk.sqlite", config=config, initial=initial)
    commit_rights_day(ledger, first)
    previous, parent = ledger.verify()
    day = next_day(context, previous, 30)
    result, _, record = prepare_durable_day(previous, parent, day)
    close = capture_session_state(result.execution.result.runtime,
        session=record.checkpoint.engine.session, origin_session=previous.engine.origin_session,
        session_offset=previous.engine.session_offset+1, completed_index=31)
    ledger.close()
    return previous, day, result, record, close


def check(previous, day, result, record, close, final=None, mappings=None):
    return audit_day_risk(previous.engine, close, record.checkpoint.engine if final is None else final,
        result.account, day.request.action_id, engine_risk_groups(day.request.inputs, result.execution.result),
        asdict(day.request.inputs.research), day.request.opening_stops,
        day.request.conversion_risks if mappings is None else mappings)


def test_actual_partial_receipt_sale_and_conversion_risk_reconstruct_independently(tmp_path, monkeypatch):
    case = conversion_case(tmp_path, monkeypatch)
    assert check(*case).passed
    final = case[3].checkpoint.engine
    assert any(row.symbol == "FINAL.TW" and row.side == "SELL" and row.quantity == 3 for row in final.pending)


@pytest.mark.parametrize("change", ["lost_exit", "wrong_exit_quantity", "wrong_exit_reason", "lost_stop",
                                    "wrong_stop", "terminated", "settlements", "offset"])
def test_financially_valid_checkpoint_cannot_hide_risk_or_engine_history_drift(tmp_path, monkeypatch, change):
    case = conversion_case(tmp_path, monkeypatch)
    final = case[3].checkpoint.engine
    if change == "lost_exit":
        final = replace(final, pending=())
    elif change in {"wrong_exit_quantity", "wrong_exit_reason"}:
        pending = tuple(replace(row, **({"quantity": 2} if change == "wrong_exit_quantity" else {"reason": "entry"}))
                        if row.symbol == "FINAL.TW" else row for row in final.pending)
        final = replace(final, pending=pending)
    elif change == "lost_stop":
        final = replace(final, stops=tuple(row for row in final.stops if row.symbol != "FINAL.TW"))
    elif change == "wrong_stop":
        final = replace(final, stops=tuple(replace(row, stop=row.stop+1) if row.symbol == "FINAL.TW" else row
                                         for row in final.stops))
    elif change == "terminated":
        final = replace(final, terminated=("OTHER.TW",))
    elif change == "offset":
        final = replace(final, session_offset=99)
    else:
        final = replace(final, settlements=())
    assert not check(*case, final=final).passed


def test_missing_conversion_mapping_cannot_silently_keep_parent_stop(tmp_path, monkeypatch):
    case = conversion_case(tmp_path, monkeypatch)
    assert not check(*case, mappings=()).passed


def test_independent_risk_audit_does_not_call_signal_or_transfer_implementation(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_paper import signals
    from quant_fund_lab.odd_lot_rights import conversion_risk, session_projection

    case = conversion_case(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError("production risk implementation called by independent audit")
    monkeypatch.setattr(signals, "plan_close_signals", forbidden)
    monkeypatch.setattr(conversion_risk, "transfer_conversion_risk", forbidden)
    monkeypatch.setattr(session_projection, "transfer_conversion_risk", forbidden)
    assert check(*case).passed


def test_actual_durable_entry_rejects_production_projection_stop_drift_without_sql_commit(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_rights import durable_day_workflow

    _, initial, config, day = initial_day(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"rejected.sqlite", config=config, initial=initial)
    before = ledger.verify()
    original = durable_day_workflow.advance_rights_day
    def wrong_stop(request):
        result = original(request)
        state = result.projection.checkpoint
        stop = state.stops[0]
        changed = replace(state, stops=(replace(stop, stop=stop.stop+1), *state.stops[1:]))
        return replace(result, projection=replace(result.projection, checkpoint=changed))
    monkeypatch.setattr(durable_day_workflow, "advance_rights_day", wrong_stop)
    with pytest.raises(ValueError, match="independent risk audit"):
        commit_rights_day(ledger, day)
    assert ledger.verify() == before
    assert ledger.connection.execute("SELECT COUNT(*) FROM rights_completed").fetchone()[0] == 0
    ledger.close()


def test_persisted_risk_rejects_rehashed_stop_drift_without_production_replay(tmp_path, monkeypatch):
    import json

    from quant_fund_lab.odd_lot_rights import conversion_risk, durable_day_workflow
    from quant_fund_lab.odd_lot_rights.codec import canonical
    from quant_fund_lab.odd_lot_rights.persisted_risk_audit import verify_persisted_risk

    context, initial, config, first = initial_day(monkeypatch)
    path = tmp_path/"stored-risk.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    days = [first]
    commit_rights_day(ledger, first)
    second = next_day(context, ledger.verify()[0], 30)
    days.append(second)
    commit_rights_day(ledger, second)
    def forbidden(*args, **kwargs):
        raise AssertionError("production engine/projection replay called by persisted risk audit")
    monkeypatch.setattr(durable_day_workflow, "prepare_durable_day", forbidden)
    monkeypatch.setattr(durable_day_workflow, "advance_rights_day", forbidden)
    monkeypatch.setattr(conversion_risk, "transfer_conversion_risk", forbidden)
    assert verify_persisted_risk(ledger, tuple(days)).sessions_checked == 2
    session, payload, inputs, parent = ledger.connection.execute(
        "SELECT session,state_json,input_digest,parent_digest FROM rights_checkpoints ORDER BY session DESC LIMIT 1").fetchone()
    state = json.loads(payload)
    engine = json.loads(state["engine"])
    final_stop = next(row for row in engine["stops"] if row["symbol"] == "FINAL.TW")
    final_stop["stop"] += 1
    state["engine"] = canonical(engine)
    changed = canonical(state)
    events = ledger.connection.execute("SELECT events_json FROM rights_events WHERE session=?", (session,)).fetchone()[0]
    ledger.connection.execute("UPDATE rights_checkpoints SET state_json=? WHERE session=?", (changed, session))
    ledger.connection.execute("UPDATE rights_completed SET commit_digest=? WHERE session=?",
        (payload_digest(canonical([parent, changed, inputs, events])), session))
    ledger.verify()  # Cash, holdings and storage digests still reconcile.
    ledger.close()
    before = path.read_bytes()
    read = RightsEngineLedger(path, config=config, read_only=True)
    with pytest.raises(ValueError, match="persisted independent risk audit"):
        verify_persisted_risk(read, tuple(days))
    read.close()
    assert path.read_bytes() == before
