"""Acceptance indexing must preserve scope and never infer approval from claims."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_acceptance_index.py"


def _fixture(tmp_path):
    plans = tmp_path / "src/ARCHITECTURE/plans"
    plans.mkdir(parents=True)
    (plans / "spec.md").write_text("| R-A01 | repeat |\n| R-A02 | identity |\n")
    evidence = tmp_path / "artifacts/acceptance/unit"
    evidence.mkdir(parents=True)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text("def test_repeat():\n    pass\n")
    record = {"checks": [{"case_id": "R-A01_partial_scope", "status": "passed",
        "test": "tests/test_sample.py::test_repeat"}]}
    (evidence / "acceptance.json").write_text(json.dumps(record))
    return evidence


def _run(tmp_path):
    output = tmp_path / "index.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(tmp_path),
        "--output", str(output)], check=False, capture_output=True, text=True)
    return result, output


def test_partial_evidence_is_preserved_without_promoting_case_to_accepted(tmp_path):
    _fixture(tmp_path)
    result, output = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    first, second = json.loads(output.read_text())["cases"]
    assert first["evidence"][0]["record"]["case_id"] == "R-A01_partial_scope"
    assert first["status"] == "evidence_available_requires_review" and not first["accepted"]
    assert first["test_reference_review"][0]["file_and_function_exist"]
    assert not first["test_reference_review"][0]["execution_verified_by_this_check"]
    assert second["status"] == "evidence_mapping_missing" and not second["accepted"]
    before = output.read_bytes()
    assert _run(tmp_path)[0].returncode == 0 and output.read_bytes() == before


def test_missing_test_is_reported_and_failed_evidence_remains_visible(tmp_path):
    evidence = _fixture(tmp_path)
    (evidence / "acceptance.json").write_text(json.dumps({"case_id": "R-A01",
        "status": "failed", "test": "tests/test_sample.py::test_missing"}))
    result, output = _run(tmp_path)
    assert result.returncode == 0
    row = json.loads(output.read_text())["cases"][0]
    assert row["evidence"][0]["record"]["status"] == "failed"
    assert not row["test_reference_review"][0]["file_and_function_exist"]


def test_malformed_evidence_does_not_replace_existing_index(tmp_path):
    evidence = _fixture(tmp_path)
    output = tmp_path / "index.json"
    output.write_text("preserved")
    (evidence / "acceptance.json").write_text("invalid json")
    result, _ = _run(tmp_path)
    assert result.returncode != 0 and output.read_text() == "preserved"


def test_test_locator_cannot_escape_repository(tmp_path):
    evidence = _fixture(tmp_path)
    (evidence / "acceptance.json").write_text(json.dumps({"case_id": "R-A01",
        "test": "../outside.py::test_external"}))
    result, output = _run(tmp_path)
    assert result.returncode != 0 and "escapes repository" in result.stderr
    assert not output.exists()
