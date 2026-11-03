"""Protocol execution connects guarded studies, reports and durable attempt history."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from protocol_fixtures import selection_rule
from test_twse_odd_lot import _bundle
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    ProtocolPeriod,
    capture_execution_identity,
    freeze_protocol,
    numerical_result_fingerprint,
    protocol_from_studies,
    run_registered_study,
)
from quant_fund_lab.odd_lot_protocol.types import canonical_json
from quant_fund_lab.odd_lot_study import (
    OddLotStudyResult,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot

SOURCE = Path(__file__).resolve().parents[1]


def _study(tmp_path, monkeypatch, *, ready):
    import quant_fund_lab.odd_lot_study as module

    if ready:
        _, symbols, dates, inputs = _ready_official_bundle(tmp_path)
        monkeypatch.setattr(module, "PERIODS", {"validation": (str(dates[120].date()), str(dates[-1].date()))})
    else:
        root, symbols = _bundle(tmp_path)
        inputs = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    directory = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes, quality_issues=[])
    _, metadata = load_frozen_odd_lot_study(directory)
    periods = tuple(ProtocolPeriod(name, start, end,
        "historical_exploration" if end >= "2025-01-01" else (
            "development_selection" if name == "development" else "validation_check"),
        "accessed", "Self-built offline fixture; not an unseen sample.")
        for name, (start, end) in metadata["periods"].items())
    spec = protocol_from_studies((directory,), periods=periods, selection=selection_rule(),
        execution=capture_execution_identity(SOURCE), declared_at="2026-10-29T00:00:00+08:00")
    return directory, spec, freeze_protocol(spec, tmp_path / "protocols")


def test_registered_ready_runs_reproduce_numbers_and_export_bound_protocol(tmp_path, monkeypatch):
    directory, spec, frozen_protocol = _study(tmp_path, monkeypatch, ready=True)
    arguments = {"studies_directory": directory.parent, "registry_path": tmp_path / "registry.sqlite",
                 "source_directory": SOURCE}
    first = run_registered_study(frozen_protocol, spec.candidates[0].candidate_id, **arguments)
    second = run_registered_study(frozen_protocol, spec.candidates[0].candidate_id, **arguments)
    assert first.experiment == second.experiment
    assert first.attempt.status == second.attempt.status == "succeeded"
    assert first.attempt.result_fingerprint == second.attempt.result_fingerprint
    assert (first.attempt.attempt, second.attempt.attempt) == (1, 2)
    assert first.report != second.report
    for report in (first.report, second.report):
        assert verify_odd_lot_study_report(report)
        assert json.loads((report / "protocol.json").read_text())["protocol_id"] == spec.protocol_id
        assert spec.protocol_id in (report / "report.html").read_text()
        assert "historical_exploration" in (report / "report.html").read_text()
    (second.report / "protocol.json").write_text("{}")
    assert not verify_odd_lot_study_report(second.report)


def test_registered_blocked_inputs_never_call_performance_and_are_not_success(tmp_path, monkeypatch):
    directory, spec, frozen_protocol = _study(tmp_path, monkeypatch, ready=False)
    import quant_fund_lab.odd_lot_study as module

    def forbidden(*_args, **_kwargs):
        pytest.fail("blocked period reached strategy performance")

    monkeypatch.setattr(module, "run_odd_lot_research", forbidden)
    run = run_registered_study(frozen_protocol, spec.candidates[0].candidate_id,
        studies_directory=directory.parent, registry_path=tmp_path / "registry.sqlite", source_directory=SOURCE)
    assert run.attempt.status == "blocked" and run.attempt.reason
    assert verify_odd_lot_study_report(run.report)
    assert (run.report / "comparison.csv").read_text().strip() == ""
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        assert registry.attempts(run.experiment.experiment_id) == (run.attempt,)


def test_execution_failure_is_recorded_before_retry_and_code_mismatch_is_rejected(tmp_path, monkeypatch):
    directory, spec, frozen_protocol = _study(tmp_path, monkeypatch, ready=True)
    import quant_fund_lab.odd_lot_protocol.run as module

    original = module.run_frozen_odd_lot_study
    def fail(_directory):
        raise RuntimeError("injected strategy failure")

    monkeypatch.setattr(module, "run_frozen_odd_lot_study", fail)
    arguments = {"studies_directory": directory.parent, "registry_path": tmp_path / "registry.sqlite",
                 "source_directory": SOURCE}
    with pytest.raises(RuntimeError, match="injected"):
        run_registered_study(frozen_protocol, spec.candidates[0].candidate_id, **arguments)
    monkeypatch.setattr(module, "run_frozen_odd_lot_study", original)
    result = run_registered_study(frozen_protocol, spec.candidates[0].candidate_id, **arguments)
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        history = registry.attempts(result.experiment.experiment_id)
        assert [a.status for a in history] == ["failed", "succeeded"]
        assert "injected strategy failure" in history[0].reason
    monkeypatch.setattr(module, "capture_execution_identity", lambda _: replace(spec.execution, revision="changed"))
    with pytest.raises(ValueError, match="execution identity"):
        run_registered_study(frozen_protocol, spec.candidates[0].candidate_id, **arguments)


def test_numerical_fingerprint_detects_exact_value_and_missing_kind_changes():
    frame = pd.DataFrame({"cash": [100.0, 99.99]})
    study = OddLotStudyResult("fixture", "dataset", frame, pd.DataFrame(), {}, {}, False)
    original = numerical_result_fingerprint(study)
    assert numerical_result_fingerprint(replace(study, comparison=frame.copy())) == original
    changed = frame.copy()
    changed.loc[1, "cash"] += 0.01
    assert numerical_result_fingerprint(replace(study, comparison=changed)) != original
    first = pd.DataFrame({"missing": pd.Series([None], dtype=object)})
    second = pd.DataFrame({"missing": pd.Series([float("nan")], dtype=object)})
    assert numerical_result_fingerprint(replace(study, comparison=first)) != numerical_result_fingerprint(
        replace(study, comparison=second))


def test_rehashed_protocol_sidecar_cannot_claim_another_experiment(tmp_path, monkeypatch):
    directory, spec, frozen_protocol = _study(tmp_path, monkeypatch, ready=False)
    run = run_registered_study(frozen_protocol, spec.candidates[0].candidate_id,
        studies_directory=directory.parent, registry_path=tmp_path / "registry.sqlite", source_directory=SOURCE)
    path = run.report / "experiment.json"
    context = json.loads(path.read_text())
    context["experiment"]["protocol_id"] = "0" * 64
    path.write_text(canonical_json(context))
    manifest_path = run.report / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("report_id")
    manifest["files"]["experiment.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    manifest_path.write_text(canonical_json(manifest))
    assert not verify_odd_lot_study_report(run.report)
