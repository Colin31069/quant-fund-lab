"""Evidence readers never initialize, migrate, or mutate registry files."""
import hashlib
import sqlite3

import pytest
from decision_fixtures import decision_fixture

from quant_fund_lab.odd_lot_decisions.registry_evidence import collect_decision_inputs
from quant_fund_lab.odd_lot_protocol.registry import ExperimentRegistry
from quant_fund_lab.odd_lot_protocol.registry_read import ReadOnlyExperimentRegistry


def test_read_only_registry_reuses_read_methods_and_enforces_write_refusal(tmp_path):
    path = tmp_path / "registry.sqlite"
    with ExperimentRegistry(path):
        pass
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with ReadOnlyExperimentRegistry(path) as registry:
        with pytest.raises(ValueError, match="not registered"):
            registry.experiments("f" * 64)
        with pytest.raises(sqlite3.OperationalError):
            registry.connection.execute("DELETE FROM registry_meta")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("kind", ["missing", "empty", "foreign", "unsupported", "symlink"])
def test_invalid_read_only_registry_is_rejected_without_file_changes(tmp_path, kind):
    path = tmp_path / "registry.sqlite"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "foreign":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE paper_accounts(id TEXT)")
    elif kind in {"unsupported", "symlink"}:
        with ExperimentRegistry(path):
            pass
        if kind == "unsupported":
            with sqlite3.connect(path) as db:
                db.execute("UPDATE registry_meta SET value='future' WHERE key='schema'")
        else:
            target = tmp_path / "target.sqlite"
            path.rename(target)
            path.symlink_to(target)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        ReadOnlyExperimentRegistry(path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("kind", ["empty", "foreign", "unsupported"])
def test_legacy_decision_reader_rejects_invalid_registry_without_initializing(tmp_path, monkeypatch, kind):
    _, _, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    path = tmp_path / "invalid.sqlite"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "foreign":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE paper_accounts(id TEXT)")
    else:
        with ExperimentRegistry(path):
            pass
        with sqlite3.connect(path) as db:
            db.execute("UPDATE registry_meta SET value='future' WHERE key='schema'")
    before = {p.name: p.read_bytes() for p in tmp_path.glob("invalid.sqlite*")}
    with pytest.raises(ValueError):
        collect_decision_inputs(frozen, registry_path=path, studies_directory=tmp_path / "studies")
    assert {p.name: p.read_bytes() for p in tmp_path.glob("invalid.sqlite*")} == before


def test_legacy_decision_reader_preserves_valid_registry_and_attempt_history(tmp_path, monkeypatch):
    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    path = tmp_path / "registry.sqlite"
    with ExperimentRegistry(path) as registry:
        record = registry.register_experiment(protocol, protocol.candidates[0].candidate_id, protocol.execution)
        attempt = registry.start_attempt(record.experiment_id)
        registry.finish_attempt(record.experiment_id, attempt.attempt, status="failed", reason="offline failure")
    before = path.read_bytes()
    inputs = collect_decision_inputs(frozen, registry_path=path, studies_directory=tmp_path / "studies")
    assert len(inputs.sources) == 1
    assert inputs.sources[0].attempts[-1].status == "failed"
    assert all(row.development.status == "failed" for row in inputs.evidence)
    assert path.read_bytes() == before
