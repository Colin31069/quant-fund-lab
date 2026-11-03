"""Protocol identity, immutable publication and honest historical data exposure."""
import json
import subprocess
from dataclasses import replace

import pytest
from protocol_fixtures import protocol

from quant_fund_lab.odd_lot_protocol import (
    ProtocolPeriod,
    capture_execution_identity,
    freeze_protocol,
    load_protocol,
)
from quant_fund_lab.odd_lot_protocol.types import StudyProtocol, canonical_json


def test_protocol_roundtrip_retries_and_mutations_are_immutable(tmp_path):
    original = protocol()
    assert StudyProtocol.from_dict(json.loads(canonical_json(original.to_dict()))) == original
    root = freeze_protocol(original, tmp_path)
    before = (root / "protocol.json").read_bytes()
    assert freeze_protocol(original, tmp_path) == root
    assert (root / "protocol.json").read_bytes() == before
    changed = replace(original, seed=1, parent_protocol_id=original.protocol_id)
    other = freeze_protocol(changed, tmp_path)
    assert root != other and load_protocol(other).parent_protocol_id == original.protocol_id
    payload = json.loads(before)
    payload["protocol"]["seed"] = 100
    (root / "protocol.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="fingerprint"):
        load_protocol(root)
    with pytest.raises(ValueError, match="fingerprint"):
        freeze_protocol(original, tmp_path)


@pytest.mark.parametrize("change", [
    {"seed": True}, {"max_candidates": 2}, {"warmup": 119},
    {"declared_at": "2026-10-29T00:00:00"},
    {"source_policy_json": '{"a":NaN}'},
])
def test_protocol_rejects_invalid_contracts(change):
    with pytest.raises(ValueError):
        replace(protocol(), **change)


def test_historical_access_cannot_be_labeled_unseen_or_used_for_new_selection(tmp_path):
    with pytest.raises(ValueError, match="exploratory"):
        ProtocolPeriod("historical", "2025-01-01", "2025-12-31", "development_selection",
                       "unknown", "No evidence of first access.")
    unseen = ProtocolPeriod("future", "2025-01-01", "2025-12-31", "forward_observation",
                            "unseen", "A checkbox is insufficient.")
    with pytest.raises(ValueError, match="historical"):
        replace(protocol(), periods=(unseen,))
    backdated = replace(protocol(), periods=(unseen,), declared_at="2024-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="already historical"):
        freeze_protocol(backdated, tmp_path)


def test_execution_identity_includes_untracked_engine_files_but_excludes_progress_docs(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    source = tmp_path / "src" / "quant_fund_lab"
    source.mkdir(parents=True)
    (source / "engine.py").write_text("VERSION = 1\n")
    (source / "README.md").write_text("Initial project documentation.\n")
    git("add", "pyproject.toml", "src")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
    before = capture_execution_identity(tmp_path)
    (tmp_path / "progress.md").write_text("recorded result")
    (source / "README.md").write_text("Updated documentation without engine changes.\n")
    assert capture_execution_identity(tmp_path) == before
    untracked = source / "new_model.py"
    untracked.write_text("PARAMETER = 1\n")
    after = capture_execution_identity(tmp_path)
    assert after.source_tree_sha256 != before.source_tree_sha256
    assert after.code_diff_sha256 == before.code_diff_sha256
    (source / "engine.py").write_text("VERSION = 2\n")
    changed = capture_execution_identity(tmp_path)
    assert changed.source_tree_sha256 != after.source_tree_sha256
    assert changed.code_diff_sha256 != after.code_diff_sha256


def test_risk_cost_data_calendar_code_and_seed_changes_create_new_identity():
    spec = protocol()
    candidate = spec.candidates[0]
    variations = [
        replace(spec, seed=1), replace(spec, dataset_id="e" * 64),
        replace(spec, input_fingerprint="f" * 64),
        replace(spec, calendar_revisions=("different-calendar",)),
        replace(spec, execution=replace(spec.execution, revision="new-revision")),
        replace(spec, candidates=(replace(candidate, research_json=canonical_json({"risk": 3000})),)),
        replace(spec, candidates=(replace(candidate, backtest_json=canonical_json({"cost": 50})),)),
    ]
    assert len({spec.protocol_id, *(p.protocol_id for p in variations)}) == len(variations) + 1
