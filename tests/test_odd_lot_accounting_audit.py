"""Financial audit rejects coherent hash changes that cannot reconcile from events."""
import json
import sqlite3
from dataclasses import replace

import pytest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.event_codec import decode_event, encode_event
from quant_fund_lab.odd_lot_paper.ledger import canonical, digest
from quant_fund_lab.odd_lot_paper.replay import _replay_account


def _rehash_latest(db, session):
    payload, inputs, parent = db.execute(
        "SELECT state_json,input_digest,previous_digest FROM session_checkpoints WHERE session=?",
        (session,)).fetchone()
    events = {}
    for category, row in db.execute("SELECT category,payload FROM session_events WHERE session=? ORDER BY category,ordinal", (session,)):
        events.setdefault(category, []).append(json.loads(row))
    db.execute("UPDATE session_checkpoints SET commit_digest=? WHERE session=?",
               (digest(canonical([parent, payload, inputs, events])), session))


def test_audit_rebuilds_normal_account_without_changing_file_bytes(tmp_path):
    path = tmp_path / "account.sqlite"
    data, research, base, identity = _fixture()
    _replay_account(path, data, research, base, identity, create=True)
    before = path.read_bytes()
    audit = audit_accounting(path)
    assert audit.passed and audit.sessions_checked == 35
    assert path.read_bytes() == before


def test_rehashed_cash_and_nav_changes_still_fail_independent_reconstruction(tmp_path):
    path = tmp_path / "account.sqlite"
    data, research, base, identity = _fixture()
    _replay_account(path, data, research, base, identity, create=True)
    with sqlite3.connect(path) as db:
        session, payload = db.execute("SELECT session,state_json FROM session_checkpoints ORDER BY session DESC LIMIT 1").fetchone()
        state = json.loads(payload)
        state["cash"] += 10
        db.execute("UPDATE session_checkpoints SET state_json=? WHERE session=?", (canonical(state), session))
        row = db.execute("SELECT payload FROM session_events WHERE session=? AND category='nav'", (session,)).fetchone()[0]
        nav = decode_event(json.loads(row))
        nav["cash"] += 10
        nav["settled_cash"] += 10
        nav["equity"] += 10
        db.execute("UPDATE session_events SET payload=? WHERE session=? AND category='nav'",
                   (canonical(encode_event(nav)), session))
        _rehash_latest(db, session)
    before = path.read_bytes()
    audit = audit_accounting(path)
    assert not audit.passed and any("cash" in issue for issue in audit.issues)
    with pytest.raises(ValueError, match="independent accounting"):
        _replay_account(path, data, research, base, identity)
    assert path.read_bytes() == before


def test_missing_valuation_evidence_is_not_treated_as_zero_or_success(tmp_path):
    path = tmp_path / "account.sqlite"
    data, research, base, identity = _fixture()
    _replay_account(path, data, research, base, identity, create=True)
    with sqlite3.connect(path) as db:
        session = db.execute("SELECT max(session) FROM session_checkpoints").fetchone()[0]
        db.execute("DELETE FROM session_events WHERE category='valuation' AND session=?", (session,))
        _rehash_latest(db, session)
    audit = audit_accounting(path)
    assert not audit.passed and any("valuation" in issue for issue in audit.issues)


def test_independent_audit_failure_rolls_back_day_before_sql_commit(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_paper.replay as module

    path = tmp_path / "account.sqlite"
    data, research, base, identity = _fixture()
    original = module.run_odd_lot_session
    def wrong_nav(inputs):
        result = original(inputs)
        return replace(result, nav={**result.nav, "equity": result.nav["equity"]+10})
    with monkeypatch.context() as patch:
        patch.setattr(module, "run_odd_lot_session", wrong_nav)
        with pytest.raises(ValueError, match="independent accounting"):
            _replay_account(path, data, research, base, identity, create=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM session_checkpoints").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM session_events").fetchone()[0] == 0
    _replay_account(path, data, research, base, identity)
    assert audit_accounting(path).passed
