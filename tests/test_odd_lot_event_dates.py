"""Reviewed date resolutions preserve raw events and cash-dividend accounting."""
import hashlib
import json
from dataclasses import asdict, replace

import pandas as pd
import pytest
from test_twse_odd_lot import _write_rows
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.odd_lot_event_dates import RULE_ID, RULE_URL, CashDividendDateReview
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_event_amendments import derive_cash_dividend_review_bundle
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot


def _review_bundle(tmp_path):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    scheduled, effective = dates[40], dates[41]
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    event_entry = None
    for entry in manifest["sources"]:
        path = root / entry["path"]
        data = json.loads(path.read_text())
        if entry["kind"] == "price":
            data["data"] = [row for row in data["data"] if pd.Timestamp(row[0]) != scheduled]
            for row in data["data"]:
                if entry["symbol"] == symbols[0] and pd.Timestamp(row[0]) >= effective:
                    row[1], row[2] = "98", "98"
        elif entry["kind"] == "holiday_index" and entry["year"] == scheduled.year:
            data["data"] = [[str(scheduled.date()), "災害休市", "全日休市"]]
        elif entry["kind"] == "ex_right_index" and entry["year"] == scheduled.year:
            data["fields"] = ["資料日期", "股票代號", "除權息前收盤價", "除權息參考價",
                              "減除股利參考價", "權/息", "權值+息值"]
            data["data"] = [[str(scheduled.date()), symbols[0][:-3], "100", "98", "98", "息", "2"]]
            event_entry = entry
        path.write_text(json.dumps(data))
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    ref = {"source_url": event_entry["url"], "evidence_path": event_entry["path"]}
    # Existing action evidence must remain in evidence/, as in production bundles.
    target = root / "evidence" / "event.json"
    target.write_bytes((root / event_entry["path"]).read_bytes())
    _write_rows(root / "actions.csv", ["date", "symbol", "split_ratio", "cash_dividend", *ref], [
        {"date": str(scheduled.date()), "symbol": symbols[0], "split_ratio": 1,
         "cash_dividend": 2, **ref, "evidence_path": "evidence/event.json"}
    ])
    rule = root / "evidence" / "rule.txt"
    rule.write_text("Offline fixture: scheduled closed-day cash dividend reference moves to the next session.")
    review = CashDividendDateReview(symbols[0], str(scheduled.date()), str(effective.date()), 2,
        RULE_ID, RULE_URL, "evidence/rule.txt", hashlib.sha256(rule.read_bytes()).hexdigest(),
        event_entry["url"], event_entry["path"], event_entry["sha256"], "explicit fixture review")
    return root, symbols, dates, review


def _write_review(root, *reviews):
    _write_rows(root / "action_date_reviews.csv", list(CashDividendDateReview.__dataclass_fields__),
                [asdict(review) for review in reviews])


def test_review_moves_only_evidenced_cash_dividend_without_rewriting_sources(tmp_path):
    root, symbols, dates, review = _review_bundle(tmp_path)
    start, end = str(dates[0].date()), str(dates[-1].date())
    baseline = prepare_twse_odd_lot(root, symbols, start, end)
    assert any("企業行動日缺少" in issue.detail for issue in baseline.issues)
    original = root
    original_bytes = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    root = derive_cash_dividend_review_bundle(root, tmp_path / "versions", (review,),
                                             {review.rule_evidence_path: root / review.rule_evidence_path})
    assert original_bytes == {p.relative_to(original): p.read_bytes()
                              for p in original.rglob("*") if p.is_file()}
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = prepare_twse_odd_lot(root, symbols, start, end)
    assert not result.issues
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert "action_date_reviews.csv" in result.source_hashes
    assert review.rule_evidence_path in result.source_hashes
    dividend = result.data.dividends[symbols[0]]
    assert dividend.sum() == 2 and dividend.at[dates[41]] == 2
    assert dates[40] not in result.data.close.index
    assert result.data.raw_close.at[dates[41], symbols[0]] == 98
    assert result.data.close.at[dates[41], symbols[0]] == pytest.approx(100)
    assert 10 * result.data.raw_close.at[dates[41], symbols[0]] + 10 * dividend.at[dates[41]] == 1000
    truncated = prepare_twse_odd_lot(root, symbols, start, str(dates[39].date()))
    pd.testing.assert_frame_equal(result.data.close.loc[:dates[39]], truncated.data.close)
    frozen = freeze_odd_lot_study(result.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="twse_official", source_provenance=result.provenance,
        source_files=result.source_files, source_hashes=result.source_hashes, quality_issues=[])
    assert "action_date_reviews.csv" in load_frozen_odd_lot_study(frozen)[1]["source_files"]
    report = export_odd_lot_study_report(frozen, run_frozen_odd_lot_study(frozen))
    assert verify_odd_lot_study_report(report)
    assert (report / "action_date_reviews.csv").read_bytes() == (root / "action_date_reviews.csv").read_bytes()
    (report / "action_date_reviews.csv").write_text("changed")
    assert not verify_odd_lot_study_report(report)
    (frozen / "sources" / "action_date_reviews.csv").write_text("changed")
    with pytest.raises(ValueError, match="source"):
        load_frozen_odd_lot_study(frozen)


@pytest.mark.parametrize("change,match", [
    ({"effective_date": "2024-12-31"}, "next session"),
    ({"cash_dividend": 3}, "differs from original"),
    ({"symbol": "2881.TW"}, "supported indexed"),
    ({"event_source_url": "https://example.com/event"}, "declared official"),
])
def test_invalid_reviews_do_not_unblock_or_change_originals(tmp_path, change, match):
    root, symbols, dates, review = _review_bundle(tmp_path)
    _write_review(root, replace(review, **change))
    with pytest.raises(ValueError, match=match):
        prepare_twse_odd_lot(root, symbols, str(dates[0].date()), str(dates[-1].date()))


def test_duplicate_review_rule_tampering_and_unsupported_rights_are_rejected(tmp_path):
    root, symbols, dates, review = _review_bundle(tmp_path)
    args = (root, symbols, str(dates[0].date()), str(dates[-1].date()))
    _write_review(root, review, review)
    with pytest.raises(ValueError, match="duplicate"):
        prepare_twse_odd_lot(*args)
    _write_review(root, review)
    rule = root / review.rule_evidence_path
    original = rule.read_bytes()
    rule.write_text("changed")
    with pytest.raises(ValueError, match="hash differs"):
        prepare_twse_odd_lot(*args)
    rule.write_bytes(original)
    event = root / review.event_evidence_path
    payload = json.loads(event.read_text())
    payload["data"][0][3] = "97"  # Separate subscription component, not pure cash dividend.
    event.write_text(json.dumps(payload))
    digest = hashlib.sha256(event.read_bytes()).hexdigest()
    manifest = json.loads((root / "manifest.json").read_text())
    next(e for e in manifest["sources"] if e["path"] == review.event_evidence_path)["sha256"] = digest
    (root / "manifest.json").write_text(json.dumps(manifest))
    _write_review(root, replace(review, event_sha256=digest))
    with pytest.raises(ValueError, match="supported indexed"):
        prepare_twse_odd_lot(*args)


def test_review_bundle_retries_are_immutable_and_recursive_targets_are_rejected(tmp_path):
    root, _, _, review = _review_bundle(tmp_path)
    evidence = {review.rule_evidence_path: root / review.rule_evidence_path}
    parent = tmp_path / "versions"
    derived = derive_cash_dividend_review_bundle(root, parent, (review,), evidence)
    assert derive_cash_dividend_review_bundle(root, parent, (review,), evidence) == derived
    with pytest.raises(ValueError, match="outside"):
        derive_cash_dividend_review_bundle(root, root / "versions", (review,), evidence)
    with pytest.raises(ValueError, match="duplicate"):
        derive_cash_dividend_review_bundle(root, parent, (review, review), evidence)
    (derived / "action_date_reviews.csv").write_text("changed")
    with pytest.raises(ValueError, match="cannot overwrite"):
        derive_cash_dividend_review_bundle(root, parent, (review,), evidence)


def test_open_scheduled_day_cannot_be_reclassified_by_a_date_review(tmp_path):
    root, symbols, dates, review = _review_bundle(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(e for e in manifest["sources"] if e["kind"] == "holiday_index"
                 and e["year"] == dates[40].year)
    path = root / entry["path"]
    payload = json.loads(path.read_text())
    payload["data"] = []
    path.write_text(json.dumps(payload))
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    _write_review(root, review)
    with pytest.raises(ValueError, match="evidenced market closure"):
        prepare_twse_odd_lot(root, symbols, str(dates[0].date()), str(dates[-1].date()))


@pytest.mark.parametrize("path", ["../outside.json", "/tmp/event.json", "evidence/../event.json"])
def test_review_paths_must_be_canonical(tmp_path, path):
    _, _, _, review = _review_bundle(tmp_path)
    with pytest.raises(ValueError, match="canonical and relative"):
        replace(review, rule_evidence_path=path)
