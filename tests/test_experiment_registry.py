"""Durable experiments retain unsuccessful attempts and reject conflicting reruns."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from protocol_fixtures import protocol

from quant_fund_lab.odd_lot_protocol import ExperimentRegistry


def test_registry_preserves_failure_success_retry_and_numerical_mismatch(tmp_path):
    spec = protocol()
    path = tmp_path / "experiments.sqlite"
    with ExperimentRegistry(path) as registry:
        record = registry.register_experiment(spec, spec.candidates[0].candidate_id, spec.execution)
        assert registry.register_experiment(spec, record.candidate_id, spec.execution) == record
        first = registry.start_attempt(record.experiment_id)
        with pytest.raises(ValueError, match="explicit failure recovery"):
            registry.start_attempt(record.experiment_id)
        failed = registry.finish_attempt(record.experiment_id, first.attempt, status="failed", reason="injected failure")
        assert registry.finish_attempt(record.experiment_id, first.attempt, status="failed", reason="injected failure") == failed
        with pytest.raises(ValueError, match="rewritten"):
            registry.finish_attempt(record.experiment_id, first.attempt, status="failed", reason="hide failure")
        second = registry.start_attempt(record.experiment_id)
        success = registry.finish_attempt(record.experiment_id, second.attempt, status="succeeded",
                                          result_fingerprint="e" * 64, report_path="first-report")
        third = registry.start_attempt(record.experiment_id)
        reproduced = registry.finish_attempt(record.experiment_id, third.attempt, status="succeeded",
                                              result_fingerprint="e" * 64, report_path="second-report")
        assert success.result_fingerprint == reproduced.result_fingerprint
        fourth = registry.start_attempt(record.experiment_id)
        mismatch = registry.finish_attempt(record.experiment_id, fourth.attempt, status="succeeded",
                                           result_fingerprint="f" * 64, report_path="different-report")
        assert mismatch.status == "failed" and "nonreproducible" in mismatch.reason
        assert mismatch.result_fingerprint == "f" * 64
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            registry.connection.execute("UPDATE attempts SET status='running' WHERE attempt=1")
        registry.connection.rollback()
    with ExperimentRegistry(path) as reopened:
        assert [a.status for a in reopened.attempts(record.experiment_id)] == ["failed", "succeeded", "succeeded", "failed"]
        assert reopened.get_experiment(record.experiment_id) == record
        assert reopened.experiments(spec.protocol_id) == (record,)


def test_unknown_candidates_code_changes_and_missing_parent_are_rejected(tmp_path):
    spec = protocol()
    with ExperimentRegistry(tmp_path / "experiments.sqlite") as registry:
        with pytest.raises(ValueError, match="search budget"):
            registry.register_experiment(spec, "0" * 64, spec.execution)
        with pytest.raises(ValueError, match="execution identity"):
            registry.register_experiment(spec, spec.candidates[0].candidate_id,
                                         replace(spec.execution, revision="new-revision"))
        child = replace(spec, seed=1, parent_protocol_id=spec.protocol_id)
        with pytest.raises(ValueError, match="not registered"):
            registry.register_protocol(child)
        registry.register_protocol(spec)
        registry.register_protocol(child)
        assert registry.get_protocol(child.protocol_id).parent_protocol_id == spec.protocol_id
        parent_record = registry.register_experiment(spec, spec.candidates[0].candidate_id, spec.execution)
        child_record = registry.register_experiment(child, child.candidates[0].candidate_id, child.execution)
        assert parent_record.experiment_id != child_record.experiment_id


def test_unrelated_database_is_preserved_and_tampered_history_is_rejected(tmp_path):
    path = tmp_path / "paper.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE positions(symbol TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="not an experiment registry"):
        ExperimentRegistry(path)
    assert path.read_bytes() == before
    spec = protocol()
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        record = registry.register_experiment(spec, spec.candidates[0].candidate_id, spec.execution)
        registry.start_attempt(record.experiment_id)
        registry.connection.execute("UPDATE attempts SET payload='{}'")
        registry.connection.commit()
        with pytest.raises((TypeError, ValueError)):
            registry.attempts(record.experiment_id)


def test_blocked_rerun_mismatch_is_preserved_as_failure(tmp_path):
    spec = protocol()
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        record = registry.register_experiment(spec, spec.candidates[0].candidate_id, spec.execution)
        first = registry.start_attempt(record.experiment_id)
        registry.finish_attempt(record.experiment_id, first.attempt, status="blocked",
                                 result_fingerprint="e" * 64, reason="missing evidence")
        second = registry.start_attempt(record.experiment_id)
        mismatch = registry.finish_attempt(record.experiment_id, second.attempt, status="blocked",
                                           result_fingerprint="f" * 64, reason="changed decision")
        assert mismatch.status == "failed" and "nonreproducible" in mismatch.reason


def test_concurrent_attempt_start_cannot_duplicate_a_running_candidate(tmp_path):
    path = tmp_path / "registry.sqlite"
    spec = protocol()
    with ExperimentRegistry(path) as registry:
        record = registry.register_experiment(spec, spec.candidates[0].candidate_id, spec.execution)
    barrier = Barrier(2)

    def start():
        with ExperimentRegistry(path) as registry:
            barrier.wait(timeout=5)
            try:
                return registry.start_attempt(record.experiment_id).status
            except ValueError as exc:
                assert "running attempt" in str(exc)
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == ["rejected", "running"]
    with ExperimentRegistry(path) as registry:
        assert len(registry.attempts(record.experiment_id)) == 1
