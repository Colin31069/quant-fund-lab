"""Archive admission always invokes independent value/risk and behavioral replay."""
import json

import pytest
from rights_durable_day_fixtures import initial_day, next_day

from quant_fund_lab.odd_lot_rights.codec import canonical
from quant_fund_lab.odd_lot_rights.day_request_archive import (
    archive_day_request,
    commit_archived_day,
    verify_archived_days,
)
from quant_fund_lab.odd_lot_rights.engine_ledger import RightsEngineLedger
from quant_fund_lab.odd_lot_rights.engine_ledger_types import payload_digest


def completed(tmp_path, monkeypatch):
    context, initial, config, day = initial_day(monkeypatch)
    path = tmp_path/"combined.sqlite"
    ledger = RightsEngineLedger(path, config=config, initial=initial)
    references = []
    for index in (29, 30):
        if index == 30:
            day = next_day(context, ledger.verify()[0], index)
        archived = archive_day_request(tmp_path/"requests", day)
        references.append(archived)
        commit_archived_day(ledger, archived)
    return path, config, ledger, tuple(references)


def test_full_archive_entry_runs_all_three_checks_without_changing_files(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_rights import persisted_nav_audit, persisted_risk_audit

    path, config, ledger, refs = completed(tmp_path, monkeypatch)
    ledger.close()
    files = [path, *(row.path for row in refs)]
    before = {p: p.read_bytes() for p in files}
    called = []
    original_nav, original_risk = persisted_nav_audit.verify_persisted_nav, persisted_risk_audit.verify_persisted_risk
    def nav(ledger, days):
        called.append("independent_nav")
        return original_nav(ledger, days)
    def risk(ledger, days):
        called.append("independent_risk")
        return original_risk(ledger, days)
    monkeypatch.setattr(persisted_nav_audit, "verify_persisted_nav", nav)
    monkeypatch.setattr(persisted_risk_audit, "verify_persisted_risk", risk)
    reader = RightsEngineLedger(path, config=config, read_only=True)
    result = verify_archived_days(reader, refs)
    assert result.sessions_checked == 2 and called == ["independent_nav", "independent_risk"]
    reader.close()
    assert before == {p: p.read_bytes() for p in files}


@pytest.mark.parametrize("change", ["nav", "stop", "missing_risk_evidence"])
def test_rehashed_corruption_rejected_before_production_history_replay(tmp_path, monkeypatch, change):
    from quant_fund_lab.odd_lot_rights import day_request_archive

    path, config, ledger, refs = completed(tmp_path, monkeypatch)
    session, state, inputs, parent = ledger.connection.execute(
        "SELECT session,state_json,input_digest,parent_digest FROM rights_checkpoints ORDER BY session DESC LIMIT 1").fetchone()
    events = json.loads(ledger.connection.execute("SELECT events_json FROM rights_events WHERE session=?", (session,)).fetchone()[0])
    if change == "nav":
        events["rights_nav"][0]["nav"] = "999999"
    elif change == "missing_risk_evidence":
        del events["risk_audit"]
    else:
        checkpoint = json.loads(state)
        engine = json.loads(checkpoint["engine"])
        next(row for row in engine["stops"] if row["symbol"] == "FINAL.TW")["stop"] += 1
        checkpoint["engine"] = canonical(engine)
        state = canonical(checkpoint)
        ledger.connection.execute("UPDATE rights_checkpoints SET state_json=? WHERE session=?", (state, session))
    encoded = canonical(events)
    ledger.connection.execute("UPDATE rights_events SET events_json=? WHERE session=?", (encoded, session))
    ledger.connection.execute("UPDATE rights_completed SET commit_digest=? WHERE session=?",
        (payload_digest(canonical([parent, state, inputs, encoded])), session))
    ledger.verify()
    ledger.close()
    def forbidden(*args, **kwargs):
        raise AssertionError("production replay reached before independent corruption rejection")
    monkeypatch.setattr(day_request_archive, "verify_durable_days", forbidden)
    before = path.read_bytes()
    reader = RightsEngineLedger(path, config=config, read_only=True)
    with pytest.raises(ValueError, match="persisted.*(NAV|risk)"):
        verify_archived_days(reader, refs)
    reader.close()
    assert path.read_bytes() == before
