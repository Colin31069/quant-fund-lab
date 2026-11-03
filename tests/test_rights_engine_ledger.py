"""New combined ledger commits real engine/account days atomically and read-only."""
import json
from dataclasses import replace

import pytest
from rights_engine_ledger_fixtures import sequence

from quant_fund_lab.odd_lot_paper.ledger import OddLotLedger
from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.engine_checkpoint import RightsEngineCheckpoint
from quant_fund_lab.odd_lot_rights.engine_checkpoint_codec import (
    decode_engine_rights,
    encode_engine_rights,
)
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.engine_ledger_types import payload_digest


@pytest.mark.parametrize("restart", [False, True])
def test_actual_trade_tplus2_election_and_nav_events_commit_one_combined_day(tmp_path, monkeypatch, restart):
    initial, config, records = sequence(monkeypatch)
    path = tmp_path/"rights.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    cash = []
    for record in records:
        identity = ledger.commit(record)
        state, digest = ledger.verify()
        assert state == record.checkpoint and digest == identity
        assert decode_engine_rights(encode_engine_rights(state)) == state
        cash.append(state.engine.cash)
        if restart:
            ledger.close()
            ledger = RightsEngineLedger(path, config=config)
    assert cash == [0., 0., 0., 290., 90., 90.]
    assert len(ledger.verify()[0].account.authorizations) == 1
    assert dict(ledger.verify()[0].engine.shares).get("2317.TW") == 2
    before = path.read_bytes()
    for record in records:
        ledger.commit(record)
    assert path.read_bytes() == before
    assert ledger.connection.execute("SELECT COUNT(*) FROM rights_completed").fetchone()[0] == 6
    ledger.close()
    readonly = RightsEngineLedger(path, config=config, read_only=True)
    assert readonly.verify()[0] == records[-1].checkpoint
    with pytest.raises(ValueError, match="read-only"):
        readonly.commit(records[-1])
    readonly.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("phase", ["checkpoint", "events", "completion", "before_commit"])
@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_payment_day_fault_rolls_back_engine_inventory_authorization_events_and_completion(
        tmp_path, monkeypatch, phase, error):
    initial, config, records = sequence(monkeypatch)
    path = tmp_path/"fault.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    for record in records[:3]:
        ledger.commit(record)
    before_state, before_digest = ledger.verify()
    def interrupt(where):
        if where == phase:
            raise error("injected "+phase)
    with pytest.raises(error):
        ledger.commit(records[3], _fault=interrupt)
    ledger.close()
    restored = RightsEngineLedger(path, config=config)
    assert restored.verify() == (before_state, before_digest)
    assert not restored.verify()[0].account.authorizations and restored.verify()[0].engine.cash == 0
    for table in ("rights_checkpoints", "rights_events", "rights_completed"):
        assert restored.connection.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] == 3
    restored.commit(records[3])
    assert restored.verify()[0].engine.cash == 290
    assert len(restored.verify()[0].account.authorizations) == 1
    restored.close()


def test_precommit_business_validator_rejection_rolls_back_whole_day(tmp_path, monkeypatch):
    initial, config, records = sequence(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"rejected.sqlite", config=config, initial=initial)
    baseline = ledger.verify()
    def reject(db):
        assert db.execute("SELECT COUNT(*) FROM rights_completed").fetchone()[0] == 1
        raise ValueError("source/risk/NAV precommit validator rejected")
    with pytest.raises(ValueError, match="precommit validator rejected"):
        ledger.commit(records[0], _validate=reject)
    assert ledger.verify() == baseline
    ledger.close()


@pytest.mark.parametrize("change", ["calendar", "policy", "completed", "parent", "offset", "cash"])
def test_wrong_configuration_or_checkpoint_cannot_change_existing_account(tmp_path, monkeypatch, change):
    initial, config, records = sequence(monkeypatch)
    path = tmp_path/"locked.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    ledger.commit(records[0])
    before = ledger.verify()
    if change in {"calendar", "policy"}:
        changed = replace(config, **{change+"_sha256": "f"*64})
        with pytest.raises(ValueError, match="configuration"):
            RightsEngineLedger(path, config=changed)
    elif change == "cash":
        with pytest.raises(ValueError, match="cash/holdings"):
            RightsEngineCheckpoint(replace(records[1].checkpoint.engine, cash=1.), records[1].checkpoint.account)
    else:
        record = records[0] if change == "completed" else records[1]
        if change == "completed":
            record = replace(record, input_fingerprint="f"*64)
        elif change == "parent":
            record = replace(record, previous_digest="f"*64)
        else:
            record = replace(record, checkpoint=replace(record.checkpoint,
                engine=replace(record.checkpoint.engine, session_offset=99)))
        with pytest.raises(ValueError):
            ledger.commit(record)
    assert ledger.verify() == before
    ledger.close()


def test_rehashed_checkpoint_cash_tampering_fails_financial_cross_binding(tmp_path, monkeypatch):
    initial, config, records = sequence(monkeypatch)
    path = tmp_path/"tampered.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    ledger.commit(records[0])
    row = ledger.connection.execute("SELECT session,state_json,input_digest,parent_digest FROM rights_checkpoints").fetchone()
    session, payload, inputs, parent = row
    value = json.loads(payload)
    engine = json.loads(value["engine"])
    engine["cash"] += 1
    value["engine"] = canonical(engine)
    forged = canonical(value)
    events = ledger.connection.execute("SELECT events_json FROM rights_events").fetchone()[0]
    ledger.connection.execute("UPDATE rights_checkpoints SET state_json=?", (forged,))
    ledger.connection.execute("UPDATE rights_completed SET commit_digest=?",
                              (payload_digest(canonical([parent, forged, inputs, events])),))
    with pytest.raises(ValueError, match="cash/holdings"):
        ledger.verify()
    ledger.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="cash/holdings"):
        RightsEngineLedger(path, config=config, read_only=True)
    assert path.read_bytes() == before and session == records[0].checkpoint.engine.session


@pytest.mark.parametrize("readonly", [False, True])
def test_legacy_sqlite_format_refused_without_migration_or_byte_changes(tmp_path, monkeypatch, readonly):
    initial, config, _ = sequence(monkeypatch)
    path = tmp_path/"legacy.sqlite"
    old = OddLotLedger(path, config_json="{}", initial_state=initial.engine)
    old.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="format"):
        RightsEngineLedger(path, config=config, read_only=readonly)
    assert path.read_bytes() == before


def test_externally_pinned_initial_checkpoint_rejects_a_valid_substituted_genesis(tmp_path, monkeypatch):
    initial, config, _ = sequence(monkeypatch)
    path = tmp_path/"genesis.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    substitute = replace(initial, engine=replace(initial.engine, origin_session="2024-01-01"))
    encoded = encode_engine_rights(substitute)  # Structurally/financially valid, different pinned root.
    ledger.connection.execute("UPDATE rights_metadata SET value=? WHERE key='initial'", (encoded,))
    ledger.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="initial anchor"):
        RightsEngineLedger(path, config=config, read_only=True)
    assert path.read_bytes() == before
    new_path = tmp_path/"not-created.sqlite"
    with pytest.raises(ValueError, match="initial state"):
        RightsEngineLedger(new_path, config=config, initial=substitute)
    assert not new_path.exists()


def test_precommit_callback_cannot_silently_replace_record_and_rehash_it(tmp_path, monkeypatch):
    initial, config, records = sequence(monkeypatch)
    ledger = RightsEngineLedger(tmp_path/"callback.sqlite", config=config, initial=initial)
    before = ledger.verify()
    def replace_events(db):
        payload, inputs, parent = db.execute(
            "SELECT state_json,input_digest,parent_digest FROM rights_checkpoints").fetchone()
        events = canonical({"substituted": []})
        db.execute("UPDATE rights_events SET events_json=?", (events,))
        db.execute("UPDATE rights_completed SET commit_digest=?",
                   (payload_digest(canonical([parent, payload, inputs, events])),))
    with pytest.raises(ValueError, match="changed the expected rights record"):
        ledger.commit(records[0], _validate=replace_events)
    assert ledger.verify() == before
    ledger.close()


def test_two_writers_recheck_prefix_inside_transaction_and_share_exact_replay(tmp_path, monkeypatch):
    initial, config, records = sequence(monkeypatch)
    path = tmp_path/"writers.sqlite"
    first = RightsEngineLedger(path, config=config, initial=initial)
    second = RightsEngineLedger(path, config=config)
    identity = first.commit(records[0])
    assert second.commit(records[0]) == identity
    with pytest.raises(ValueError, match="predecessor"):
        second.commit(replace(records[1], previous_digest=records[0].previous_digest))
    second.commit(records[1])
    assert first.verify() == second.verify()
    first.close()
    second.close()


def test_each_next_actual_engine_day_runs_from_reopened_sql_engine_and_full_account(tmp_path, monkeypatch):
    _, _, uninterrupted = sequence(monkeypatch)
    path = tmp_path/"actual-resume.sqlite"
    def persist_and_reload(initial, config, record):
        ledger = RightsEngineLedger(path, config=config, initial=initial if not path.exists() else None)
        ledger.commit(record)
        ledger.close()
        reader = RightsEngineLedger(path, config=config, read_only=True)
        restored = reader.verify()
        reader.close()
        return restored
    _, config, resumed = sequence(monkeypatch, after_record=persist_and_reload)
    assert resumed == uninterrupted  # Every next engine input used the reopened SQL state.
    final = RightsEngineLedger(path, config=config, read_only=True)
    assert final.verify()[0] == resumed[-1].checkpoint
    assert final.verify()[0].account.inventory.cash == 90
    assert len(final.verify()[0].account.authorizations) == 1
    final.close()
