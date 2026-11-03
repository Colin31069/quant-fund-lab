"""Internal forward evidence commits atomically; fixtures do not activate a real plan."""
import hashlib
import json
import sqlite3
from dataclasses import asdict, replace

import pytest
from test_odd_lot_accounting_audit import _rehash_latest
from test_odd_lot_observation_gate import _assess, _fixture

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.odd_lot_paper.audit import audit_accounting
from quant_fund_lab.odd_lot_paper.event_codec import decode_event, encode_event
from quant_fund_lab.odd_lot_paper.forward_binding import ForwardReplayBinding
from quant_fund_lab.odd_lot_paper.ledger import canonical
from quant_fund_lab.odd_lot_paper.observation_gate import assess_forward_session
from quant_fund_lab.odd_lot_paper.replay import ReplayIdentity, _replay_account
from quant_fund_lab.odd_lot_paper.source_archive import publish_source_archive
from quant_fund_lab.odd_lot_research import OddLotResearchConfig
from quant_fund_lab.odd_lot_study import _subset


def _setup(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    research = OddLotResearchConfig(strategy="momentum")
    config = BacktestConfig(initial_cash=100000,base_currency="TWD",strategy=StrategyConfig(warmup_days=30))
    plan = replace(plan,strategy="momentum",research_config_json=canonical(asdict(research)),
                   execution_config_json=canonical(asdict(config)))
    result = _assess(root, symbols, dates, plan)
    archive = tmp_path / "archive"
    binding = ForwardReplayBinding(plan, result.evidence, publish_source_archive(result.inputs, archive),
                                   archive, tuple(symbols))
    data = _subset(result.inputs.data, symbols[:2])
    identity = ReplayIdentity(plan.protocol_id,plan.execution_id,result.evidence.calendar_revision,
                              str(dates[119].date()))
    return root,symbols,dates,plan,binding,data,research,config,identity


def _run(path, setup, *, create=False, binding=None, data=None, fault=None):
    *_, original, panels, research, config, identity = setup
    return _replay_account(path, panels if data is None else data, research, config, identity,
        create=create,snapshot_root=path.parent / "snapshots",observation=binding or original,_fault=fault)


def test_plan_and_provenance_are_locked_and_noop_preserves_bytes(tmp_path):
    setup = _setup(tmp_path)
    path = tmp_path / "account.sqlite"
    first = _run(path, setup, create=True)
    assert first.committed_sessions == 5 and audit_accounting(path).passed
    with sqlite3.connect(path) as db:
        config = json.loads(db.execute("SELECT value FROM account_metadata WHERE key='config'").fetchone()[0])
        assert config["observation"]["plan_id"] == setup[4].plan.plan_id
        assert db.execute("SELECT count(*) FROM session_events WHERE category='observation'").fetchone()[0] == 5
    before = path.read_bytes()
    assert _run(path, setup).committed_sessions == 0
    assert path.read_bytes() == before
    other_plan = replace(setup[3], access_note="Another independently registered intent")
    other = replace(setup[4], plan=other_plan, evidence=replace(setup[4].evidence,plan_id=other_plan.plan_id))
    with pytest.raises(ValueError, match="configuration"):
        _run(path, setup, binding=other)
    assert path.read_bytes() == before


def test_failure_after_provenance_insertion_rolls_back_entire_day(tmp_path):
    setup = _setup(tmp_path)
    path = tmp_path / "account.sqlite"
    def fail(stage):
        if stage == "events":
            raise RuntimeError("interrupted after provenance insertion")
    with pytest.raises(RuntimeError,match="interrupted"):
        _run(path, setup, create=True, fault=fail)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT * FROM session_checkpoints").fetchall()
        assert not db.execute("SELECT * FROM session_events").fetchall()
    assert _run(path, setup).committed_sessions == 5


def test_changed_archived_source_inside_transaction_blocks_completion(tmp_path):
    setup = _setup(tmp_path)
    path = tmp_path / "account.sqlite"
    archive_file = setup[4].source_root / setup[4].source_archive.archive_id / "sources/evidence/review.txt"
    saved = archive_file.read_bytes()
    def fail(stage):
        if stage == "events":
            archive_file.write_text("changed while completing day")
    with pytest.raises(ValueError,match="payload changed"):
        _run(path,setup,create=True,fault=fail)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT * FROM session_checkpoints").fetchall()
        assert not db.execute("SELECT * FROM session_events").fetchall()
    archive_file.write_bytes(saved)  # Explicitly undo this test's fault; product never repairs it.
    assert _run(path,setup).committed_sessions == 5


def test_rehashed_provenance_change_refuses_even_when_financial_audit_passes(tmp_path):
    setup = _setup(tmp_path)
    path = tmp_path / "account.sqlite"
    _run(path, setup, create=True)
    with sqlite3.connect(path) as db:
        session,payload = db.execute("SELECT session,payload FROM session_events WHERE category='observation' ORDER BY session DESC LIMIT 1").fetchone()
        record = decode_event(json.loads(payload))
        record["plan_id"] = "f"*64
        db.execute("UPDATE session_events SET payload=? WHERE session=? AND category='observation'",
                   (canonical(encode_event(record)),session))
        _rehash_latest(db,session)
    assert audit_accounting(path).passed
    before = path.read_bytes()
    with pytest.raises(ValueError,match="locked plan"):
        _run(path, setup)
    assert path.read_bytes() == before


def test_segmented_resume_checks_old_archive_after_new_source_capture(tmp_path):
    setup = _setup(tmp_path)
    root,symbols,dates,plan,binding,*_ = setup
    prefix = assess_forward_session(plan,str(dates[121].date()),official_directory=root,
        symbols=tuple(symbols[:2]),benchmark=symbols[2])
    partial = replace(binding,evidence=prefix.evidence)
    path = tmp_path / "account.sqlite"
    assert _run(path, setup, create=True, binding=partial, data=_subset(prefix.inputs.data,symbols[:2])).committed_sessions == 2
    (root / "evidence/review.txt").write_text("Updated offline source review")
    current = _assess(root,symbols,dates,plan)
    next_binding = replace(binding,evidence=current.evidence,
        source_archive=publish_source_archive(current.inputs,binding.source_root))
    old_file = binding.source_root / binding.source_archive.archive_id / "sources/evidence/review.txt"
    saved = old_file.read_bytes()
    old_file.unlink()
    before = path.read_bytes()
    with pytest.raises(ValueError,match="inventory"):
        _run(path, setup, binding=next_binding)
    assert path.read_bytes() == before
    old_file.write_bytes(saved)
    resumed = _run(path,setup,binding=next_binding)
    whole = _run(tmp_path / "whole.sqlite",setup,create=True,binding=next_binding)
    assert resumed.committed_sessions == 3 and resumed.checkpoint == whole.checkpoint


def test_candidate_setting_or_identity_override_refuses_before_account_creation(tmp_path):
    setup = _setup(tmp_path)
    *_,binding,data,research,base,identity = setup
    path = tmp_path / "account.sqlite"
    with pytest.raises(ValueError,match="settings"):
        _replay_account(path,data,replace(research,fill_fraction=.25),base,identity,create=True,
            snapshot_root=tmp_path / "snapshots",observation=binding)
    with pytest.raises(ValueError,match="identity"):
        _replay_account(path,data,research,base,replace(identity,protocol_id="f"*64),create=True,
            snapshot_root=tmp_path / "snapshots",observation=binding)
    assert not path.exists()


def test_coherent_alternative_source_archive_cannot_replace_committed_input(tmp_path):
    setup = _setup(tmp_path)
    root,symbols,dates,plan,binding,*_ = setup
    path = tmp_path / "account.sqlite"
    _run(path,setup,create=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        if entry["kind"] != "price":
            continue
        raw = root / entry["path"]
        payload = json.loads(raw.read_text())
        # Keep a valid, reconstructable alternate series; it is not the series
        # that produced the original financial checkpoint and normalized snapshot.
        for row in payload["data"]:
            row[1] = row[2] = "101"
        raw.write_text(json.dumps(payload))
        entry["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    alternate = _assess(root,symbols,dates,plan)
    other = replace(binding,evidence=alternate.evidence,
        source_archive=publish_source_archive(alternate.inputs,binding.source_root))
    last = str(dates[-1].date())
    with sqlite3.connect(path) as db:
        db.execute("UPDATE session_events SET payload=? WHERE session=? AND category='observation'",
                   (canonical(encode_event(other.record())),last))
        _rehash_latest(db,last)
    assert audit_accounting(path).passed
    before = path.read_bytes()
    with pytest.raises(ValueError,match="archived source prefix"):
        _run(path,setup)
    assert path.read_bytes() == before
