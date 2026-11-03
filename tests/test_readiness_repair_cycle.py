"""Real import/assessment cycles preserve unresolved event and warmup blockers."""
import hashlib
import json
from dataclasses import replace

import pandas as pd
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.twse_calendar import official_calendar
from quant_fund_lab.twse_odd_lot import TWSEInput, prepare_twse_odd_lot
from quant_fund_lab.twse_preparation import (
    batch_import_twse,
    missing_source_manifest,
    read_batch_manifest,
)
from quant_fund_lab.twse_quality.readiness import assess_study_readiness
from quant_fund_lab.twse_quality.types import FindingCode, ReadinessStatus


def test_export_import_recheck_resolves_only_prices_and_rejects_conflicts(tmp_path):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    reviews = pd.read_csv(root / "coverage_reviews.csv")
    reviews = reviews[~((reviews.symbol == symbols[0]) & (reviews.category == "split"))]
    reviews.to_csv(root / "coverage_reviews.csv", index=False)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    removed = next(row for row in manifest["sources"] if row["kind"] == "price"
                   and row["symbol"] == symbols[0])
    source = tmp_path / "restored.json"
    target = root / removed["path"]
    source.write_bytes(target.read_bytes())
    target.unlink()
    manifest["sources"].remove(removed)
    manifest_path.write_text(json.dumps(manifest))
    start, end = str(dates[0].date()), str(dates[-1].date())
    periods = {"validation": (str(dates[120].date()), end)}

    def assess():
        inputs = prepare_twse_odd_lot(root, symbols, start, end)
        decision = assess_study_readiness(inputs, periods,
            calendar=official_calendar(inputs, start, end))
        return inputs, decision

    before_inputs, before = assess()
    assert any(row.code == FindingCode.MISSING_MONTH for row in before.findings)
    checklist = missing_source_manifest(before_inputs.issues + before_inputs.issues)
    assert len(checklist) == 1
    checklist["file"] = str(source)
    checklist_path = tmp_path / "repair.csv"
    checklist.to_csv(checklist_path, index=False)
    rows = read_batch_manifest(checklist_path)
    result = batch_import_twse(root, rows + rows, dry_run=False)
    assert result.status.tolist() == ["imported", "present"]
    _, after = assess()
    assert after.input_fingerprint != before.input_fingerprint
    assert not any(row.code == FindingCode.MISSING_MONTH for row in after.findings)
    assert any(row.code == FindingCode.COVERAGE_REVIEW for row in after.findings)
    assert after.periods[0].status == ReadinessStatus.BLOCKED
    frozen_bytes = target.read_bytes()
    changed = json.loads(source.read_text())
    changed["data"][0][1] = "101"
    source.write_text(json.dumps(changed))
    assert batch_import_twse(root, rows, dry_run=False).status.tolist() == ["error"]
    assert target.read_bytes() == frozen_bytes
    assert assess()[1].readiness_fingerprint == after.readiness_fingerprint


def test_prior_period_gap_blocks_next_period_warmup_without_inventing_month_count(tmp_path):
    calendar = expected_market_sessions("TW", "2023-01-01", "2024-12-31")
    dates = pd.DatetimeIndex(calendar.sessions)[30:240]
    prices = pd.DataFrame(100., index=dates, columns=["2330.TW", "2317.TW", "0050.TW"])
    source = tmp_path / "source.txt"
    source.write_text("synthetic reviewed source")
    inputs = TWSEInput(MarketData(prices, prices, prices * 10000), (),
        {"source.txt": source}, {"source.txt": hashlib.sha256(source.read_bytes()).hexdigest()}, {})
    periods = {"development": (str(dates[120].date()), str(dates[149].date())),
               "validation": (str(dates[150].date()), str(dates[180].date()))}
    intact = assess_study_readiness(inputs, periods, calendar=calendar)
    assert all(row.status == ReadinessStatus.READY for row in intact.periods)
    day = dates[135]
    missing = prices.drop(index=day)
    broken = replace(inputs, data=MarketData(missing, missing, missing * 10000))
    result = assess_study_readiness(broken, periods, calendar=calendar)
    assert all(row.status == ReadinessStatus.BLOCKED for row in result.periods)
    validation = next(row for row in result.periods if row.period == "validation")
    assert len(validation.warmup.verified_sessions) == 119
    assert not any(row.code == FindingCode.MISSING_MONTH for row in result.findings)
    assert any(row.code == FindingCode.MISSING_SESSION for row in result.findings)
