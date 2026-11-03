"""Valid structural hashes cannot excuse forged holdings, obligations or fills."""
import json
import sqlite3

import pytest
from test_odd_lot_accounting_audit import _rehash_latest
from test_odd_lot_durable_events import _fixture, _run

from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.ledger import OddLotLedger, canonical, digest


@pytest.mark.parametrize("mutation", ["positions", "settlements", "duplicate_fill"])
def test_rehashed_business_tampering_fails_independent_audit_without_repair(
    tmp_path, monkeypatch, mutation
):
    inputs = _fixture(monkeypatch)
    path = tmp_path / "account.sqlite"
    _run(path, inputs, count=31, create=True)
    assert audit_accounting(path).passed
    with sqlite3.connect(path) as connection:
        stamp, payload = connection.execute(
            "SELECT session,state_json FROM session_checkpoints ORDER BY session DESC LIMIT 1"
        ).fetchone()
        state = json.loads(payload)
        assert state["shares"] == [["2330.TW", 3]]
        assert len(state["settlements"]) == 1
        if mutation == "positions":
            state["shares"][0][1] = 4
        elif mutation == "settlements":
            state["settlements"][0]["amount"] += 1.
        else:
            fill = connection.execute(
                "SELECT payload FROM session_events WHERE session=? AND category='fills'",
                (stamp,),
            ).fetchone()[0]
            connection.execute("INSERT INTO session_events VALUES(?,?,?,?,?)", (
                digest(canonical([stamp, "fills", 1])), stamp, "fills", 1, fill))
        connection.execute("UPDATE session_checkpoints SET state_json=? WHERE session=?",
                           (canonical(state), stamp))
        _rehash_latest(connection, stamp)
        config = connection.execute(
            "SELECT value FROM account_metadata WHERE key='config'").fetchone()[0]

    before = path.read_bytes()
    # Prove this is a business failure rather than merely a stale hash or row ID.
    ledger = OddLotLedger(path, config_json=config, read_only=True)
    ledger.verify()
    ledger.close()
    assert path.read_bytes() == before
    audit = audit_accounting(path)
    assert not audit.passed
    expected_issue = {"positions": "positions differ", "settlements": "settlement history differs",
                      "duplicate_fill": "positions differ"}[mutation]
    assert any(expected_issue in issue for issue in audit.issues)
    with pytest.raises(ValueError, match="independent accounting audit failed"):
        _run(path, inputs)
    assert path.read_bytes() == before
