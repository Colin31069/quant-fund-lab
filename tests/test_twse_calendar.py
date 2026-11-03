"""All consumers share evidenced closures without hiding genuine missing sessions."""
import hashlib
import json

import pandas as pd
import pytest
from test_twse_odd_lot import _write_rows
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.market_calendar import (
    CalendarClosures,
    expected_market_sessions,
    validate_daily_sessions,
    validate_point_in_time_market_sessions,
)
from quant_fund_lab.twse_calendar import official_calendar, official_closure_evidence
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot
from quant_fund_lab.twse_quality.readiness import assess_study_readiness


def _closure_bundle(tmp_path, *, unexplained=False):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    annual, emergency, suspended = dates[40], dates[50], dates[60]
    absent = {annual, emergency} | ({dates[41]} if unexplained else set())
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        path = root / entry["path"]
        payload = json.loads(path.read_text())
        if entry["kind"] == "price":
            payload["data"] = [row for row in payload["data"] if (
                pd.Timestamp(row[0]) not in absent and not (
                    entry["symbol"] == "0050.TW" and pd.Timestamp(row[0]) == suspended))]
        if entry["kind"] == "holiday_index" and entry["year"] == annual.year:
            payload["data"] = [[str(annual.date()), "測試補假", "補假一日"]]
        path.write_text(json.dumps(payload))
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    ref = {"source_url": "https://www.twse.com.tw/review", "evidence_path": "evidence/review.txt"}
    _write_rows(root / "suspensions.csv", ["date", "symbol", *ref], [
        {"date": str(emergency.date()), "symbol": "*", **ref},
        {"date": str(suspended.date()), "symbol": "0050.TW", **ref},
    ])
    return root, symbols, dates, annual, emergency, suspended


def test_general_preparation_and_readiness_share_exact_effective_sessions(tmp_path, monkeypatch):
    import quant_fund_lab.twse_odd_lot as preparation

    root, symbols, dates, annual, emergency, suspended = _closure_bundle(tmp_path)
    queried = []

    def capture(*args, **kwargs):
        result = expected_market_sessions(*args, **kwargs)
        queried.append(result)
        return result

    monkeypatch.setattr(preparation, "expected_market_sessions", capture)
    start, end = str(dates[0].date()), str(dates[-1].date())
    inputs = prepare_twse_odd_lot(root, symbols, start, end)
    assert not inputs.issues
    policy = official_closure_evidence(inputs.source_files, inputs.source_hashes, start, end)
    direct = expected_market_sessions("TW", start, end, closures=policy)
    effective = official_calendar(inputs, start, end)
    assert queried == [direct] and direct == effective
    assert annual not in direct.sessions and emergency not in direct.sessions
    assert suspended in direct.sessions
    assert inputs.data.raw_open.at[suspended, "0050.TW"] != inputs.data.raw_open.at[suspended, "0050.TW"]
    assert inputs.data.volume.at[suspended, "0050.TW"] == 0
    assert validate_daily_sessions(inputs.data.close.index, "TW", closures=policy).is_valid
    assert validate_point_in_time_market_sessions(inputs.data, closures={"TW": policy})["TW"].is_valid
    decision = assess_study_readiness(inputs, {"development": (str(dates[122].date()), end)},
                                      calendar=effective)
    assert decision.periods[0].status.value == "ready"
    assert len(decision.periods[0].warmup.verified_sessions) == 120
    assert decision.periods[0].warmup.calendar_revision == direct.revision
    assert not validate_daily_sessions(inputs.data.close.index, "TW").is_valid


def test_unexplained_whole_market_omission_remains_blocking_in_all_consumers(tmp_path):
    root, symbols, dates, *_ = _closure_bundle(tmp_path, unexplained=True)
    start, end = str(dates[0].date()), str(dates[-1].date())
    inputs = prepare_twse_odd_lot(root, symbols, start, end)
    assert any(i.start == str(dates[41].date()) and "交易日曆缺少整日資料" in i.detail
               for i in inputs.issues)
    policy = official_closure_evidence(inputs.source_files, inputs.source_hashes, start, end)
    assert dates[41] in validate_daily_sessions(inputs.data.close.index, "TW", closures=policy).missing_sessions
    report = validate_point_in_time_market_sessions(inputs.data, closures={"TW": policy})["TW"]
    assert dates[41] in report.missing_sessions
    decision = assess_study_readiness(inputs, {"development": (str(dates[122].date()), end)},
                                      calendar=official_calendar(inputs, start, end))
    assert decision.periods[0].status.value == "blocked"
    assert len(decision.periods[0].warmup.verified_sessions) == 119


def test_evidence_scope_market_and_bytes_are_checked(tmp_path):
    root, symbols, dates, *_ = _closure_bundle(tmp_path)
    start, end = str(dates[0].date()), str(dates[-1].date())
    inputs = prepare_twse_odd_lot(root, symbols, start, end)
    policy = official_closure_evidence(inputs.source_files, inputs.source_hashes, start, end)
    for market, first, last in [("US", start, end), ("TW", "2024-01-01", end)]:
        with pytest.raises(ValueError, match="cover requested"):
            expected_market_sessions(market, first, last, closures=policy)
    with pytest.raises(ValueError, match="mapping conflicts"):
        validate_point_in_time_market_sessions(inputs.data, closures={"US": policy})
    inputs.source_files["evidence/review.txt"].write_text("changed")
    with pytest.raises(ValueError, match="integrity"):
        official_closure_evidence(inputs.source_files, inputs.source_hashes, start, end)


@pytest.mark.parametrize("days", [(pd.NaT,), (pd.Timestamp("2025-01-01T12:00"),),
                                  (pd.Timestamp("2025-01-01T00:00Z"),),
                                  (pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-01"))])
def test_closure_contract_rejects_noncanonical_sessions(days):
    with pytest.raises(ValueError, match="sessions"):
        CalendarClosures("TW", "fixture", "2025-01-01", "2025-12-31", days)
