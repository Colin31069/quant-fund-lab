"""Evidence amendments preserve originals and never suppress quote contradictions."""
import hashlib
import json

import pytest
from test_twse_odd_lot import _bundle

from quant_fund_lab.twse_amendments import ClosureEvidence, derive_closure_bundle
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot


def evidence(tmp_path):
    path = tmp_path / "closure.txt"
    path.write_bytes(b"explicit offline closure evidence fixture")
    return ClosureEvidence("2025-06-12", "2025-06-11", "https://www.twse.com.tw/closure",
                           path, hashlib.sha256(path.read_bytes()).hexdigest(), "fixture review")


def test_derivation_is_reproducible_preserves_originals_and_keeps_conflicts(tmp_path):
    root, symbols = _bundle(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    item = evidence(tmp_path)
    derived = derive_closure_bundle(root, tmp_path / "versions", (item,))
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert derived == derive_closure_bundle(root, tmp_path / "versions", (item,))
    loaded = prepare_twse_odd_lot(derived, symbols, "2025-06-09", "2025-06-20")
    assert any(issue.detail == "休市紀錄與官方成交價量衝突" for issue in loaded.issues)
    assert list((derived / "amendments").glob("*/previous_suspensions.csv"))
    target = next((derived / "evidence").glob("closure_*"))
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="existing derived"):
        derive_closure_bundle(root, tmp_path / "versions", (item,))


def test_unverified_duplicate_and_recursive_derivations_are_rejected(tmp_path):
    root, _ = _bundle(tmp_path)
    item = evidence(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        derive_closure_bundle(root, root / "versions", (item,))
    with pytest.raises(ValueError, match="duplicate"):
        derive_closure_bundle(root, tmp_path / "versions", (item, item))
    item.evidence_file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        derive_closure_bundle(root, tmp_path / "versions", (item,))


def test_amendment_audit_is_bound_to_prepared_source_inventory(tmp_path):
    root, symbols = _bundle(tmp_path)
    derived = derive_closure_bundle(root, tmp_path / "versions", (evidence(tmp_path),))
    loaded = prepare_twse_odd_lot(derived, symbols, "2025-06-09", "2025-06-20")
    manifest = json.loads((derived / "manifest.json").read_text())
    assert len(manifest["amendment_records"]) == 3
    for record in manifest["amendment_records"]:
        assert loaded.source_hashes[record["path"]] == record["sha256"]
    review = next((derived / "amendments").glob("*/review.json"))
    review.write_text("{}")
    with pytest.raises(ValueError, match="修訂紀錄雜湊不符"):
        prepare_twse_odd_lot(derived, symbols, "2025-06-09", "2025-06-20")
