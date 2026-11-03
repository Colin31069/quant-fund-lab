"""Persisted development selections retain full audit prefixes without validation parsing."""
import hashlib
import json

import pytest
from decision_fixtures import decision_fixture, run_candidate
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_decisions.selection_capture import (
    export_development_selection,
    load_development_selection,
)
from quant_fund_lab.odd_lot_decisions.types import fingerprint
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry
from quant_fund_lab.odd_lot_protocol.types import canonical_json


def _export(root, frozen):
    return export_development_selection(frozen, registry_path=root / "registry.sqlite",
        studies_directory=root / "studies", output_directory=root / "decisions", source_directory=SOURCE)


def _load(root, directory):
    return load_development_selection(directory, registry_path=root / "registry.sqlite", studies_directory=root / "studies")


def _rehash(directory, path):
    manifest_path = directory / "selection_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("capture_fingerprint")
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["capture_fingerprint"] = fingerprint(manifest)
    manifest_path.write_text(canonical_json(manifest))


def test_saved_capture_preserves_incomplete_prefix_and_same_semantics_across_retries(tmp_path, monkeypatch):
    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    missing = _export(tmp_path, frozen)
    assert missing.inputs.selection.status == "incomplete_search"
    run = run_candidate(tmp_path, protocol, frozen)
    first = _export(tmp_path, frozen)
    second = _export(tmp_path, frozen)
    assert first.inputs.selection.status == "insufficient_sample"
    assert first.inputs.selection.selection_id == second.inputs.selection.selection_id
    assert first.directory != second.directory and first.capture_fingerprint != second.capture_fingerprint
    assert first.directory.parent.name == first.inputs.selection.selection_id
    assert first.directory.parent.parent.name == "selections"
    before = {p.name: p.read_bytes() for p in first.directory.iterdir()}
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.start_attempt(run.experiment.experiment_id)
    assert _load(tmp_path, missing.directory).inputs == missing.inputs
    assert _load(tmp_path, first.directory).inputs == first.inputs
    assert {p.name: p.read_bytes() for p in first.directory.iterdir()} == before
    assert _export(tmp_path, frozen).inputs.selection.status == "incomplete_search"


@pytest.mark.parametrize("artifact", ["selection", "sources", "context"])
def test_rehashed_capture_semantic_tampering_is_rejected(tmp_path, monkeypatch, artifact):
    _, _, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    saved = _export(tmp_path, frozen)
    if artifact == "selection":
        path = saved.directory / "development_selection.json"
        value = json.loads(path.read_text())
        value["selected_candidate"] = "f" * 64
    elif artifact == "sources":
        path = saved.directory / "sources.json"
        value = json.loads(path.read_text())
        value[0]["candidate_id"] = "f" * 64
    else:
        path = saved.directory / "selection_context.json"
        value = json.loads(path.read_text())
        value["policy_id"] = "f" * 64
    path.write_text(canonical_json(value))
    _rehash(saved.directory, path)
    with pytest.raises(ValueError):
        _load(tmp_path, saved.directory)


def test_registry_change_before_publication_does_not_publish_partial_capture(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.selection_capture as module

    _, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    run = run_candidate(tmp_path, protocol, frozen)
    original = module.load_development_selection
    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
            registry.start_attempt(run.experiment.experiment_id)
        return result
    monkeypatch.setattr(module, "load_development_selection", race)
    with pytest.raises(ValueError, match="changed before publication"):
        _export(tmp_path, frozen)
    assert not list((tmp_path / "decisions").rglob("selection_manifest.json"))


def test_wrong_source_directory_cannot_publish_selection(tmp_path, monkeypatch):
    _, _, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="executing package"):
        export_development_selection(frozen, registry_path=tmp_path / "registry.sqlite",
            studies_directory=tmp_path / "studies", output_directory=tmp_path / "decisions", source_directory=tmp_path)
