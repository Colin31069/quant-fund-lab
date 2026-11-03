"""Real decision authentication with explicitly simulated future source/time fixtures."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture, publish, save_selection
from test_odd_lot_observation import _plan
from test_registered_odd_lot_study import SOURCE
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.forward_workflow import (
    _check_source_policy,
    run_observation_account,
)
from quant_fund_lab.odd_lot_paper.observation import register_forward_observation


def test_pending_start_has_no_account_or_archive_side_effects(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_paper.forward_workflow as module

    plan = _plan()
    monkeypatch.setattr(module,"authenticate_observation_plan",lambda *a,**k:SimpleNamespace(plan=plan,protocol=None))
    monkeypatch.setattr(module.observation_gate,"_now",lambda:datetime(2026,10,29,tzinfo=timezone.utc))
    result = run_observation_account(tmp_path/"plan",through=plan.first_session,
        registry_path=tmp_path/"registry",studies_directory=tmp_path/"studies",source_directory=SOURCE,
        official_directory=tmp_path/"missing",account_path=tmp_path/"account.sqlite",
        snapshot_root=tmp_path/"snapshots",source_archive_root=tmp_path/"archive",create=True)
    assert result.status == "pending" and result.replay is None
    assert list(tmp_path.iterdir()) == []


def test_source_mode_cannot_switch_after_candidate_selection():
    with pytest.raises(ValueError,match="official-only"):
        _check_source_policy({"data_source":"twse_official"},"provider",None)
    with pytest.raises(ValueError,match="declared provider"):
        _check_source_policy({"data_source":"provider_reviewed"},None,None)
    with pytest.raises(ValueError,match="source-backed"):
        _check_source_policy({"data_source":"synthetic"},None,None)


def test_real_registered_decision_activates_one_simulated_future_session(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_paper.observation_gate as gate

    _, protocol, frozen, _, _ = phased_fixture(tmp_path,monkeypatch,positive=True)
    run_candidate(tmp_path,protocol,frozen)
    report = publish(tmp_path,save_selection(tmp_path,frozen)).report
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei")).date()
    first = expected_market_sessions("TW",str(today+timedelta(days=2)),str(today+timedelta(days=16))).sessions[0].date()
    plan = register_forward_observation(report,first_session=str(first),
        access_note="Offline simulated future/time fixture, not an actual observation.",
        registry_path=tmp_path/"registry.sqlite",studies_directory=tmp_path/"studies",
        source_directory=SOURCE,output_directory=tmp_path/"observations")
    future_root = tmp_path/"simulated-future"
    future_root.mkdir()
    official,_symbols,dates,_ = _ready_official_bundle(future_root,start=str(first-timedelta(days=365)),
        end=str(first),sessions=400,price="10000")
    assert str(dates[-1].date()) == str(first)
    checked = datetime.combine(first+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)
    manifest_path = official/"manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        entry["retrieved_at"] = (checked-timedelta(hours=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest))
    # The clock/source dates below are deliberately simulated. No live market data.
    monkeypatch.setattr(gate,"_now",lambda:checked)
    account = tmp_path/"forward.sqlite"
    result = run_observation_account(plan,through=str(first),registry_path=tmp_path/"registry.sqlite",
        studies_directory=tmp_path/"studies",source_directory=SOURCE,official_directory=official,
        account_path=account,snapshot_root=tmp_path/"snapshots",source_archive_root=tmp_path/"archives",create=True)
    assert result.status == "active" and result.replay.committed_sessions == 1
    assert result.replay.checkpoint.session == str(first) and audit_accounting(account).passed
    with sqlite3.connect(account) as db:
        config = json.loads(db.execute("SELECT value FROM account_metadata WHERE key='config'").fetchone()[0])
        assert config["observation"]["plan_id"] == result.plan_id
        assert db.execute("SELECT count(*) FROM session_events WHERE category='observation'").fetchone()[0] == 1
    arguments = {"registry_path":tmp_path/"registry.sqlite","studies_directory":tmp_path/"studies",
        "source_directory":SOURCE,"official_directory":official,"account_path":account,
        "snapshot_root":tmp_path/"snapshots","source_archive_root":tmp_path/"archives"}
    before = account.read_bytes()
    repeated = run_observation_account(plan,through=str(first),**arguments)
    assert repeated.status == "active" and repeated.replay.committed_sessions == 0
    assert account.read_bytes() == before
    # No trailing data is fabricated: an already completed ready prefix is no-op.
    following = expected_market_sessions("TW",str(first+timedelta(days=1)),str(first+timedelta(days=14))).sessions[0].date()
    missing = run_observation_account(plan,through=str(following),**arguments)
    assert missing.status == "blocked" and missing.replay.committed_sessions == 0
    assert missing.replay.checkpoint.session == str(first) and account.read_bytes() == before
