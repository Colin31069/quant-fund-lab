"""Explicit coverage publication preserves old bytes and independent blockers."""
import csv
import hashlib
import json
from dataclasses import replace

import pytest
from test_twse_odd_lot import _bundle
from test_twse_odd_lot import (
    test_twse_2881_real_report_detects_unmodelled_rights as _real_rights_case,
)

from quant_fund_lab.twse_amendments import _inventory
from quant_fund_lab.twse_coverage_amendments import CoverageReview, derive_coverage_bundle
from quant_fund_lab.twse_odd_lot import COVERAGE_CATEGORIES, prepare_twse_odd_lot


def _review(tmp_path, **changes):
    evidence = tmp_path / "review.json"
    evidence.write_text('{"fixture":"explicit offline review, not real coverage"}\n')
    return replace(CoverageReview("2330.TW", "2025-06-09", "2025-06-20", "reduction",
        "https://www.twse.com.tw/review", evidence,
        hashlib.sha256(evidence.read_bytes()).hexdigest(), "2026-10-29T12:00:00+08:00",
        "Reviewed fixture category only; other categories require separate review."), **changes)


def test_legacy_rows_are_not_upgraded_and_only_explicit_category_is_added(tmp_path):
    root, symbols = _bundle(tmp_path)
    (root / "coverage_reviews.csv").unlink()
    before = _inventory(root)
    item = _review(tmp_path)
    derived = derive_coverage_bundle(root, tmp_path / "versions", (item,))
    assert _inventory(root) == before
    assert (derived / "coverage.csv").read_bytes() == (root / "coverage.csv").read_bytes()
    assert derived == derive_coverage_bundle(root, tmp_path / "versions", (item,))
    with (derived / "coverage_reviews.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["category"] == "reduction"
    loaded = prepare_twse_odd_lot(derived, symbols, "2025-06-09", "2025-06-20")
    missing = [issue for issue in loaded.issues if "缺少企業行動覆蓋審核" in issue.detail]
    assert len(missing) == 14
    assert not any(issue.symbol == "2330.TW" and issue.detail.endswith("reduction") for issue in missing)
    assert any(issue.symbol == "2330.TW" and issue.detail.endswith("other_rights") for issue in missing)
    manifest = json.loads((derived / "manifest.json").read_text())
    assert len(manifest["amendment_records"]) == 3
    for entry in manifest["amendment_records"]:
        assert loaded.source_hashes[entry["path"]] == entry["sha256"]
    assert list((derived / "amendments").glob("*/previous_coverage_absent.json"))


def test_existing_reviews_preserved_and_one_calendar_day_gap_still_blocks(tmp_path):
    root, symbols = _bundle(tmp_path)
    item = _review(tmp_path)
    versions = tmp_path / "versions"
    first = derive_coverage_bundle(root, versions, (replace(item, start="2025-06-21", end="2025-06-22"),))
    assert (root / "coverage_reviews.csv").read_bytes() == next(
        (first / "amendments").glob("*/previous_coverage_reviews.csv")).read_bytes()
    (root / "coverage_reviews.csv").unlink()
    gap = derive_coverage_bundle(root, versions, (
        replace(item, end="2025-06-12"), replace(item, start="2025-06-14")))
    loaded = prepare_twse_odd_lot(gap, symbols, "2025-06-09", "2025-06-20")
    missing = [issue for issue in loaded.issues if issue.symbol == "2330.TW"
               and issue.detail.endswith("reduction")]
    assert len(missing) == 1
    assert missing[0].start == missing[0].end == "2025-06-13"


@pytest.mark.parametrize("changes", [
    {"category":"unknown"}, {"symbol":"2330"}, {"source_url":"https://example.com"},
    {"start":"2025-6-09"}, {"end":"2025-06-01"}, {"review_note":" "},
    {"reviewed_at":"2026-10-29T12:00:00"}, {"sha256":"a"*64},
])
def test_invalid_review_does_not_create_a_version(tmp_path, changes):
    root, _ = _bundle(tmp_path)
    before = _inventory(root)
    with pytest.raises(ValueError):
        derive_coverage_bundle(root, tmp_path / "versions", (_review(tmp_path, **changes),))
    assert _inventory(root) == before and not (tmp_path / "versions").exists()


def test_conflicting_existing_interval_duplicate_and_recursive_destination_refuse(tmp_path):
    root, _ = _bundle(tmp_path)
    item = _review(tmp_path)
    with pytest.raises(ValueError, match="conflicts"):
        derive_coverage_bundle(root, tmp_path / "versions", (item,))
    with pytest.raises(ValueError, match="duplicate"):
        derive_coverage_bundle(root, tmp_path / "versions", (item, item))
    with pytest.raises(ValueError, match="outside"):
        derive_coverage_bundle(root, root / "versions", (item,))


def test_evidence_and_amendment_tampering_are_rejected_without_replacement(tmp_path):
    root, symbols = _bundle(tmp_path)
    (root / "coverage_reviews.csv").unlink()
    item = _review(tmp_path)
    derived = derive_coverage_bundle(root, tmp_path / "versions", (item,))
    amendment = next((derived / "amendments").glob("*/review.json"))
    amendment.write_text("{}")
    before = _inventory(derived)
    with pytest.raises(ValueError, match="修訂紀錄雜湊不符"):
        prepare_twse_odd_lot(derived, symbols, "2025-06-09", "2025-06-20")
    with pytest.raises(ValueError, match="existing derived"):
        derive_coverage_bundle(root, tmp_path / "versions", (item,))
    assert _inventory(derived) == before
    item.evidence_file.write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        derive_coverage_bundle(root, tmp_path / "other-versions", (item,))


def test_source_change_during_copy_does_not_publish_a_partial_version(tmp_path, monkeypatch):
    import quant_fund_lab.twse_coverage_amendments as module

    root, _ = _bundle(tmp_path)
    (root / "coverage_reviews.csv").unlink()
    original = module.shutil.copyfile

    def changed_source(source, target):
        result = original(source, target)
        (root / "coverage.csv").write_text("external mutation")
        return result

    monkeypatch.setattr(module.shutil, "copyfile", changed_source)
    with pytest.raises(ValueError, match="source bundle changed"):
        derive_coverage_bundle(root, tmp_path / "versions", (_review(tmp_path),))
    assert not list((tmp_path / "versions").iterdir())


def test_even_all_five_coverage_categories_cannot_clear_an_unsupported_right(tmp_path):
    _real_rights_case(tmp_path)
    root = tmp_path / "official"
    before = _inventory(root)
    item = _review(tmp_path, symbol="2881.TW", start="2021-09-03", end="2021-09-06")
    derived = derive_coverage_bundle(root, tmp_path / "versions",
        tuple(replace(item, category=category) for category in COVERAGE_CATEGORIES))
    loaded = prepare_twse_odd_lot(derived, ["2881.TW"], item.start, item.end)
    assert not any("缺少企業行動覆蓋審核" in issue.detail for issue in loaded.issues)
    assert any("未建模權利" in issue.detail for issue in loaded.issues)
    assert loaded.data.raw_close.at["2021-09-06", "2881.TW"] == 77.20
    assert _inventory(root) == before
