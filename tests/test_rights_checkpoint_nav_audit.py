"""Independent persisted NAV checks use actual trade/election checkpoints."""
import json
from copy import deepcopy
from decimal import Decimal as D

import pytest
from rights_engine_ledger_fixtures import sequence
from test_odd_lot_rights_transitions import HASHES

from quant_fund_lab.odd_lot_rights.checkpoint_nav_audit import audit_checkpoint_nav


def evidence(record):
    checkpoint = record.checkpoint
    day = checkpoint.engine.session
    known = day+"T16:00:00+08:00"
    stocks = [{"security_id": symbol, "unit_value": "100", "session": day,
               "available_at": known, "evidence_sha256": list(HASHES)}
              for symbol in sorted({lot.security_id for lot in checkpoint.account.inventory.lots})]
    rights = [{"right_key": row.key, "component": part, "unit_value": price, "session": day,
               "available_at": known, "evidence_sha256": list(HASHES)}
              for row in checkpoint.account.inventory.book.positions
              for part, units, price in (("unpaid", row.unpaid, "90"), ("pending", row.pending, "100")) if units]
    return json.loads(record.events_json)["rights_nav"][0], stocks, rights


def check(record, nav, stocks, rights, raw=None, currencies=None):
    return audit_checkpoint_nav(record.checkpoint, nav, stocks, rights,
        {"2330.TW": D(100), "2317.TW": D(100)} if raw is None else raw,
        {"2330.TW": "TWD", "2317.TW": "TWD"} if currencies is None else currencies,
        as_of=record.checkpoint.engine.session+"T16:05:00+08:00")


def test_every_actual_buy_sell_tplus2_payment_and_next_purchase_nav_reconstructs(monkeypatch):
    _, _, records = sequence(monkeypatch)
    for record in records:
        assert check(record, *evidence(record)).passed
    assert records[3].checkpoint.engine.cash == 290
    assert records[-1].checkpoint.engine.cash == 90


@pytest.mark.parametrize("field", ["cash", "held_securities", "unpaid_rights", "pending_claims",
    "sale_receivables", "fractional_receivables", "buy_payables", "sale_fee_payables",
    "settled_cash", "engine_equity", "nav"])
def test_each_reported_component_requires_independent_equation_even_with_valid_checkpoint(monkeypatch, field):
    _, _, records = sequence(monkeypatch)
    record = records[3]
    nav, stocks, rights = evidence(record)
    nav[field] = str(D(nav[field])+1)
    result = check(record, nav, stocks, rights)
    assert not result.passed and any(field+" differs" in issue for issue in result.issues)


@pytest.mark.parametrize("change", ["future", "stale", "missing", "duplicate", "quote", "currency", "raw_missing", "source_action", "processing_clock", "float_value"])
def test_wrong_or_unavailable_external_marks_and_anchor_fail(monkeypatch, change):
    _, _, records = sequence(monkeypatch)
    record = records[-1]
    nav, stocks, rights = evidence(record)
    raw, currencies = None, None
    if change == "future":
        rights[0]["available_at"] = "2026-01-01T08:00:00+08:00"
    elif change == "stale":
        stocks[0]["session"] = "2024-01-01"
    elif change == "missing":
        rights.pop()
    elif change == "duplicate":
        stocks += deepcopy(stocks)
    elif change == "quote":
        stocks[0]["unit_value"] = "101"
    elif change == "currency":
        currencies = {"2330.TW": "USD", "2317.TW": "USD"}
    elif change == "raw_missing":
        raw = {}
    elif change == "source_action":
        nav["source_action_id"] = "unrelated"
    elif change == "processing_clock":
        nav["as_of"] = "2026-01-01T16:05:00+08:00"
    else:
        nav["cash"] = 90.0
    assert not check(record, nav, stocks, rights, raw, currencies).passed


def test_independent_nav_audit_does_not_call_production_valuation(monkeypatch):
    from quant_fund_lab.odd_lot_rights import inventory_valuation, session_nav, valuation

    _, _, records = sequence(monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError("production valuation called by independent audit")
    monkeypatch.setattr(session_nav, "value_session_nav", forbidden)
    monkeypatch.setattr(session_nav, "value_inventory", forbidden)
    monkeypatch.setattr(inventory_valuation, "value_inventory", forbidden)
    monkeypatch.setattr(valuation, "value_book", forbidden)
    assert check(records[3], *evidence(records[3])).passed


def test_durable_entry_rejects_wrong_production_nav_before_any_sql_commit(tmp_path, monkeypatch):
    from dataclasses import replace

    from rights_durable_day_fixtures import initial_day

    from quant_fund_lab.odd_lot_rights import durable_day_workflow
    from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger

    _, initial, config, day = initial_day(monkeypatch)
    path = tmp_path/"independent.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    original = durable_day_workflow.value_session_nav
    def wrong_nav(*args, **kwargs):
        value = original(*args, **kwargs)
        return replace(value, nav=value.nav+1, held_securities=value.held_securities+1)
    monkeypatch.setattr(durable_day_workflow, "value_session_nav", wrong_nav)
    before = ledger.verify()
    with pytest.raises(ValueError, match="independent NAV audit"):
        durable_day_workflow.commit_rights_day(ledger, day)
    assert ledger.verify() == before
    assert ledger.connection.execute("SELECT COUNT(*) FROM rights_completed").fetchone()[0] == 0
    ledger.close()


def test_actual_reverse_split_fraction_and_dividend_components_reconstruct():
    from dataclasses import asdict

    from test_odd_lot_rights_session_flow import _post
    from test_odd_lot_session_events import _fixture

    from quant_fund_lab.odd_lot_paper.bridge import capture_session_state
    from quant_fund_lab.odd_lot_paper.session import run_odd_lot_session
    from quant_fund_lab.odd_lot_rights.authorization_archive import AuthorizedRightsAccount
    from quant_fund_lab.odd_lot_rights.engine_checkpoint import RightsEngineCheckpoint
    from quant_fund_lab.odd_lot_rights.inventory import RightsInventory, SecurityLot
    from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
    from quant_fund_lab.odd_lot_rights.session_nav import value_session_nav
    from quant_fund_lab.odd_lot_rights.session_policy import RightsSessionPolicy
    from quant_fund_lab.odd_lot_rights.types import RightsBook

    inputs = _fixture()
    result = run_odd_lot_session(inputs)
    day = str(inputs.data.close.index[1].date())
    lots = (SecurityLot("opening", "2330.TW", 3, "2024-01-01"),)
    inventory = _post(RightsInventory(D(100), lots, RightsBook(D(100)), lots), inputs, result)
    policy = RightsSessionPolicy(1, "Asia/Taipei", "2024-01-01T08:00:00+08:00", (),
                                "usable_cash_only_atomic", "do_not_subscribe")
    state = capture_session_state(result.runtime, session=day,
        origin_session=str(inputs.data.close.index[0].date()), session_offset=1, completed_index=1)
    checkpoint = RightsEngineCheckpoint(state, AuthorizedRightsAccount(inventory, policy))
    marks = (SecurityMark("2330.TW", D(196), day, day+"T16:00:00+08:00", HASHES),)
    stamp = day+"T16:05:00+08:00"
    nav = value_session_nav(inventory, inputs, result, marks, (), as_of=stamp)
    assert nav.nav == 420 and nav.fractional_receivables == 98
    audit = audit_checkpoint_nav(checkpoint, asdict(nav), [asdict(row) for row in marks], [],
        {"2330.TW": D(196)}, {"2330.TW": "TWD"}, as_of=stamp)
    assert audit.passed


def test_rehashed_sql_nav_fails_without_calling_engine_or_workflow_replay(tmp_path, monkeypatch):
    from rights_durable_day_fixtures import initial_day

    from quant_fund_lab.odd_lot_rights import durable_day_workflow, session_nav
    from quant_fund_lab.odd_lot_rights.codec import canonical
    from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
    from quant_fund_lab.odd_lot_rights.engine_ledger_types import payload_digest
    from quant_fund_lab.odd_lot_rights.persisted_nav_audit import verify_persisted_nav

    _, initial, config, day = initial_day(monkeypatch)
    path = tmp_path/"rehashed-nav.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    durable_day_workflow.commit_rights_day(ledger, day)
    def forbidden(*args, **kwargs):
        raise AssertionError("production engine/replay/valuation called by persisted NAV audit")
    monkeypatch.setattr(durable_day_workflow, "advance_rights_day", forbidden)
    monkeypatch.setattr(durable_day_workflow, "prepare_durable_day", forbidden)
    monkeypatch.setattr(session_nav, "value_session_nav", forbidden)
    assert verify_persisted_nav(ledger, (day,)).sessions_checked == 1
    payload, inputs, parent = ledger.connection.execute(
        "SELECT state_json,input_digest,parent_digest FROM rights_checkpoints").fetchone()
    events = json.loads(ledger.connection.execute("SELECT events_json FROM rights_events").fetchone()[0])
    events["rights_nav"][0]["nav"] = "999999"
    changed = canonical(events)
    ledger.connection.execute("UPDATE rights_events SET events_json=?", (changed,))
    ledger.connection.execute("UPDATE rights_completed SET commit_digest=?",
        (payload_digest(canonical([parent, payload, inputs, changed])),))
    assert ledger.verify()[0].engine.cash == 50  # Storage chain remains valid.
    ledger.close()
    before = path.read_bytes()
    reader = RightsEngineLedger(path, config=config, read_only=True)
    with pytest.raises(ValueError, match="persisted independent NAV audit"):
        verify_persisted_nav(reader, (day,))
    reader.close()
    assert path.read_bytes() == before
