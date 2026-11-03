"""Provider quotes share official event rules while preserving policy applicability."""
import csv
import hashlib
import json

import pandas as pd
import pytest
from test_odd_lot_price_inputs import bundle as bundle  # noqa: PLC0414 -- pytest fixture re-export
from test_twse_odd_lot import _bundle, _write_rows

from quant_fund_lab.odd_lot_inputs.prepare import prepare_reviewed_odd_lot_input
from quant_fund_lab.odd_lot_inputs.types import PriceSourcePolicy
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot
from quant_fund_lab.twse_quality.types import FindingCode


def test_provider_period_can_be_prepared_without_any_official_quotes(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    prepared = prepare_reviewed_odd_lot_input(
        root, bundle, symbols, PriceSourcePolicy("2024-01-02", "2024-01-03", "2024-01-03"))
    assert prepared.evidence.data.raw_open.at["2024-01-02", "0050.TW"] == 100
    assert prepared.evidence.provenance["source"] == "TWSE+FinMind"
    assert all(not finding.blocking and finding.applicability_reason for finding in prepared.official_context)
    assessment = prepared.assess({"validation": ("2024-01-02", "2024-01-03")})
    assert assessment.periods[0].status != "ready"
    assert any(f.code == FindingCode.MISSING_SESSION and f.blocking for f in assessment.findings)
    assert all(f.finding_id not in assessment.periods[0].blocking_ids
               for f in prepared.official_context)


def test_shared_split_and_suspension_rules_keep_original_bytes(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    original = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    before = {name: hashlib.sha256(path.read_bytes()).hexdigest()
              for name, path in original.source_files.items()}
    prepared = prepare_reviewed_odd_lot_input(
        root, bundle, symbols, PriceSourcePolicy("2025-06-09", "2025-06-20", "2025-06-20"))
    pd.testing.assert_frame_equal(original.data.close, prepared.evidence.data.close)
    assert pd.isna(prepared.evidence.data.raw_open.at["2025-06-12", "0050.TW"])
    assert prepared.evidence.data.stock_splits.at["2025-06-18", "0050.TW"] == 4
    assert before == {name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for name, path in original.source_files.items()}
    assert "provider/provider_manifest.json" in prepared.evidence.source_files


def test_coverage_still_blocks_under_new_policy_and_context_is_retained(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    ref = {"source_url": "https://www.twse.com.tw/review", "evidence_path": "evidence/official.txt"}
    _write_rows(root / "coverage_reviews.csv", ["symbol", "start", "end", "category", *ref], [])
    prepared = prepare_reviewed_odd_lot_input(
        root, bundle, symbols, PriceSourcePolicy("2025-06-09", "2025-06-20", "2025-06-20"))
    assessment = prepared.assess({"validation": ("2025-06-18", "2025-06-20")})
    active = [f for f in assessment.findings if f.blocking and f.code == FindingCode.COVERAGE_REVIEW]
    context = [f for f in assessment.findings if not f.blocking and f.code == FindingCode.COVERAGE_REVIEW]
    assert len(active) == len(context) == 15
    assert all(f.policy_id == "reviewed_provider_v1" for f in active)
    assert all(f.policy_id == "twse_official" for f in context)
    assert assessment.periods[0].status != "ready"


def test_reviewed_inputs_cannot_be_frozen_as_official(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    prepared = prepare_reviewed_odd_lot_input(
        root, bundle, symbols, PriceSourcePolicy("2025-06-09", "2025-06-20", "2025-06-20"))
    inputs = prepared.evidence
    with pytest.raises(ValueError, match="own source identity"):
        freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
                             benchmark=symbols[2], source="twse_official",
                             source_provenance=inputs.provenance, source_files=inputs.source_files,
                             source_hashes=inputs.source_hashes, quality_issues=[])


def test_provider_freeze_reload_and_report_share_the_same_guard(tmp_path, bundle):
    from dataclasses import asdict

    root, symbols = _bundle(tmp_path)
    prepared = prepare_reviewed_odd_lot_input(
        root, bundle, symbols, PriceSourcePolicy("2025-06-09", "2025-06-20", "2025-06-20"))
    inputs = prepared.evidence
    frozen = freeze_odd_lot_study(
        inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]), benchmark=symbols[2],
        source="provider_reviewed", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(v) for v in inputs.issues],
    )
    _, metadata = load_frozen_odd_lot_study(frozen)
    assert metadata["schema_version"] == 3 and metadata["data_source"] == "provider_reviewed"
    result = run_frozen_odd_lot_study(frozen)
    assert not result.results and len(result.unavailable) == 12
    assert result.readiness_fingerprint == metadata["readiness_fingerprint"]
    report = export_odd_lot_study_report(frozen, result)
    assert verify_odd_lot_study_report(report)
    assert (report / "price_selection.csv").exists()
    (report / "price_selection.csv").write_text("changed")
    assert not verify_odd_lot_study_report(report)


def _ready_provider_selection(tmp_path, bundle):
    from test_twse_readiness_frozen import _ready_official_bundle

    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    days = [str(day.date()) for day in dates[-2:]]
    raw = bundle / "raw" / "0050.json"
    row = {"stock_id": "0050", "open": 100, "max": 101, "min": 99, "close": 100,
           "Trading_Volume": 1000000, "Trading_money": 100000000, "Trading_turnover": 10}
    raw.write_text(json.dumps({"status": 200, "msg": "success", "data": [{**row, "date": d} for d in days]}))
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    manifest_path = bundle / "provider_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = manifest["sources"][0]
    entry.update(sha256=sha, bytes=raw.stat().st_size)
    entry["request"].update(start=days[0], end=days[-1])
    url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=0050"
           f"&start_date={days[0]}&end_date={days[-1]}")
    entry.update(requested_url=url, final_url=url)
    manifest["research_cutoff"] = days[-1]
    manifest["months"] = [{"symbol": "0050.TW", "month": month,
        "rows": sum(d.startswith(month) for d in days),
        "first_date": min(d for d in days if d.startswith(month)),
        "last_date": max(d for d in days if d.startswith(month)),
        "raw_path": "raw/0050.json", "sha256": sha} for month in sorted({d[:7] for d in days})]
    normalized = bundle / "normalized" / "finmind_prices.csv"
    with normalized.open() as file:
        fields = csv.DictReader(file).fieldnames
    with normalized.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(dict(zip(fields, [d, "0050.TW", 100, 101, 99, 100, 1000000,
                                           100000000, 10, False, "FinMind", sha])) for d in days)
    manifest["normalized_sha256"] = hashlib.sha256(normalized.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    policy = PriceSourcePolicy(str(dates[0].date()), days[-1], days[-1], priority=("FinMind", "TWSE"))
    prepared = prepare_reviewed_odd_lot_input(root, bundle, symbols, policy)
    assert sum(row.source.provider == "FinMind" for row in prepared.selection.selected) == 2
    return root, symbols, dates, prepared


def test_ready_provider_selection_runs_without_bypassing_shared_rules(tmp_path, bundle, monkeypatch):
    import quant_fund_lab.odd_lot_study as module

    _root, symbols, dates, prepared = _ready_provider_selection(tmp_path, bundle)
    days = [str(day.date()) for day in dates[-2:]]
    monkeypatch.setattr(module, "PERIODS", {"validation": (str(dates[120].date()), days[-1])})
    inputs = prepared.evidence
    frozen = freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:2]),
        benchmark=symbols[2], source="provider_reviewed", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes, quality_issues=[])
    result = run_frozen_odd_lot_study(frozen)
    assert not result.unavailable and len(result.results) == 3
    assert verify_odd_lot_study_report(export_odd_lot_study_report(frozen, result))
