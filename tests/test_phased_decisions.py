"""V6 requires an on-disk selection before reading fixed-candidate validation sources."""
import hashlib
import json

import pytest
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture, publish, save_selection

from quant_fund_lab.odd_lot_decisions.phased_evaluation import evaluate_saved_selection
from quant_fund_lab.odd_lot_decisions.phased_reporting import verify_phased_decision_report
from quant_fund_lab.odd_lot_decisions.selection_capture import load_development_selection
from quant_fund_lab.odd_lot_decisions.types import DecisionPolicy, fingerprint
from quant_fund_lab.odd_lot_decisions.workflow import build_registered_decision
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry, protocol_from_studies
from quant_fund_lab.odd_lot_protocol.decision import policy_from_plan
from quant_fund_lab.odd_lot_protocol.storage import load_protocol
from quant_fund_lab.odd_lot_protocol.types import canonical_json


def _verify(root, report):
    return verify_phased_decision_report(report, registry_path=root / "registry.sqlite", studies_directory=root / "studies")


def test_v6_declarations_are_explicit_and_old_batch_path_cannot_bypass_capture(tmp_path, monkeypatch):
    studies, protocol, frozen, legacy, args = phased_fixture(tmp_path, monkeypatch)
    policy = policy_from_plan(protocol.analysis_plan_json)
    plan = json.loads(protocol.analysis_plan_json)
    assert plan["engine"] == "frozen_odd_lot_batch_v6"
    for field in ("decision_source_rule", "decision_capture_rule", "decision_selection_rule"):
        changed = {**plan, field:"unknown"}
        with pytest.raises(ValueError, match="source rule"):
            policy_from_plan(canonical_json(changed))
    with pytest.raises(ValueError, match="explicit policy"):
        protocol_from_studies(studies, **args, phased_decisions=True)
    with pytest.raises(ValueError, match="saved development selection"):
        build_registered_decision(frozen, registry_path=tmp_path / "registry.sqlite", studies_directory=tmp_path / "studies")
    with pytest.raises(ValueError, match="explicit phased protocol"):
        evaluate_saved_selection(legacy, registry_path=tmp_path / "registry.sqlite", studies_directory=tmp_path / "studies")
    old = load_protocol(legacy)
    assert policy == policy_from_plan(old.analysis_plan_json)
    assert json.loads(old.analysis_plan_json)["engine"] == "frozen_odd_lot_batch_v5"
    assert protocol.protocol_id != old.protocol_id
    legacy_plan = {"engine":"frozen_odd_lot_batch_v4", "automatic_candidate_selection":False,
                   "decision_capture_rule":"persist_before_validation_v1"}
    with pytest.raises(ValueError, match="legacy protocol"):
        policy_from_plan(canonical_json(legacy_plan))


@pytest.mark.parametrize("attempted,status", [(False,"incomplete_search"), (True,"insufficient_sample")])
def test_without_development_choice_no_validation_reader_runs(tmp_path, monkeypatch, attempted, status):
    import quant_fund_lab.odd_lot_decisions.phased_evaluation as module

    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    if attempted:
        run_candidate(tmp_path, protocol, frozen)
    def forbidden(*args, **kwargs):
        raise AssertionError("validation must not be parsed without a saved choice")
    monkeypatch.setattr(module, "checked_report", forbidden)
    monkeypatch.setattr(module, "report_candidate_evidence", forbidden)
    saved = save_selection(tmp_path, frozen)
    result = publish(tmp_path, saved)
    assert result.decision.status == status and result.decision.selected_candidate is None
    assert _verify(tmp_path, result.report)
    assert json.loads((result.report / "evidence.json").read_text()) is None
    assert result.report.parent.name == result.decision.decision_id


def test_actual_complete_grid_reads_only_fixed_candidate_after_selection_is_saved(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.phased_evaluation as module

    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch, positive=True, count=2)
    runs = [run_candidate(tmp_path, protocol, frozen, candidate.candidate_id) for candidate in protocol.candidates]
    original_check, original_evidence = module.checked_report, module.report_candidate_evidence
    observed = []
    def checked(report, *args, **kwargs):
        captures = list((tmp_path / "decisions").glob("*/selections/*/*/selection_manifest.json"))
        assert captures, "first validation read must follow an independently published selection"
        saved = load_development_selection(captures[0].parent, registry_path=tmp_path / "registry.sqlite",
                                           studies_directory=tmp_path / "studies")
        chosen = saved.inputs.selection.selected_candidate
        assert report == next(run.report for run in runs if run.experiment.candidate_id == chosen)
        observed.append((chosen, saved.inputs.selection.selection_id))
        return original_check(report, *args, **kwargs)
    def evidence(*args, **kwargs):
        assert kwargs["strategies"] == ("ensemble",)
        return original_evidence(*args, **kwargs)
    monkeypatch.setattr(module, "checked_report", checked)
    monkeypatch.setattr(module, "report_candidate_evidence", evidence)
    saved = save_selection(tmp_path, frozen)
    assert not observed
    result = publish(tmp_path, saved)
    assert observed and result.decision.status == "continue"
    assert result.decision.selected_candidate == saved.inputs.selection.selected_candidate
    assert _verify(tmp_path, result.report)
    assert "開發選擇先保存" in (result.report / "report.html").read_text()


@pytest.mark.parametrize("artifact", ["decision.json", "selection_reference.json", "development_selection.json"])
def test_rehashed_phased_report_tampering_is_rejected(tmp_path, monkeypatch, artifact):
    _, _, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    result = publish(tmp_path, save_selection(tmp_path, frozen))
    path = result.report / artifact
    value = json.loads(path.read_text())
    if artifact == "decision.json":
        value["decision"]["status"] = "continue"
    elif artifact == "selection_reference.json":
        value["capture_fingerprint"] = "f" * 64
    else:
        value["selected_candidate"] = "f" * 64
    path.write_text(canonical_json(value))
    manifest_path = result.report / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("report_id")
    manifest["files"][artifact] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["report_id"] = fingerprint(manifest)
    manifest_path.write_text(canonical_json(manifest))
    assert not _verify(tmp_path, result.report)


def test_stale_capture_cannot_publish_current_decision_but_archived_report_remains_valid(tmp_path, monkeypatch):
    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    saved = save_selection(tmp_path, frozen)
    first = publish(tmp_path, saved)
    before = {path.name:path.read_bytes() for path in saved.directory.iterdir()}
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.start_attempt(run.experiment.experiment_id)
    with pytest.raises(ValueError, match="changed before publication"):
        publish(tmp_path, saved)
    assert _verify(tmp_path, first.report)
    assert {path.name:path.read_bytes() for path in saved.directory.iterdir()} == before
    assert len(list((tmp_path / "decisions").rglob("report_manifest.json"))) == 1


def test_validation_exception_keeps_previously_published_selection(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.phased_evaluation as module

    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch, positive=True)
    run_candidate(tmp_path, protocol, frozen)
    saved = save_selection(tmp_path, frozen)
    before = {path.name:path.read_bytes() for path in saved.directory.iterdir()}
    def fail(*args, **kwargs):
        raise ValueError("injected validation source failure")
    with monkeypatch.context() as patch:
        patch.setattr(module, "checked_report", fail)
        with pytest.raises(ValueError, match="injected validation"):
            publish(tmp_path, saved)
    assert {path.name:path.read_bytes() for path in saved.directory.iterdir()} == before
    assert load_development_selection(saved.directory, registry_path=tmp_path / "registry.sqlite",
                                      studies_directory=tmp_path / "studies").inputs == saved.inputs
    assert not list((tmp_path / "decisions").rglob("report_manifest.json"))


def test_actual_validation_rejection_is_exported_with_original_choice(tmp_path, monkeypatch):
    policy = DecisionPolicy("annual_return", 1, .01, -1, 1, require_benchmark_outperformance=False)
    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch, positive=True, policy=policy)
    run_candidate(tmp_path, protocol, frozen)
    saved = save_selection(tmp_path, frozen)
    result = publish(tmp_path, saved)
    assert result.decision.status == "return"
    assert (result.decision.selected_candidate, result.decision.selected_strategy) == (
        saved.inputs.selection.selected_candidate, saved.inputs.selection.selected_strategy)
    assert "validation_annual_return_outside_bound" in result.decision.reasons
    assert _verify(tmp_path, result.report)


@pytest.mark.parametrize("value", [None, [], {"files":[]}])
def test_invalid_manifest_shapes_return_false_without_throwing(tmp_path, monkeypatch, value):
    _, _, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    result = publish(tmp_path, save_selection(tmp_path, frozen))
    (result.report / "report_manifest.json").write_text(canonical_json(value))
    assert not _verify(tmp_path, result.report)
