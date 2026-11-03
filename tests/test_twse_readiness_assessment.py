"""Evidence-based readiness rejects missing expected bars even with many rows."""
import hashlib
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.twse_odd_lot import TWSEInput, TWSEIssue
from quant_fund_lab.twse_quality.readiness import assess_study_readiness
from quant_fund_lab.twse_quality.types import FindingCode, ReadinessStatus


@pytest.fixture
def prepared(tmp_path):
    calendar = expected_market_sessions("TW", "2023-01-01", "2024-12-31")
    dates = pd.DatetimeIndex(calendar.sessions)[30:155]
    prices = pd.DataFrame(100.0, index=dates, columns=["2330.TW", "2317.TW", "0050.TW"])
    data = MarketData(prices.copy(), prices.copy(), prices * 10000)
    source = tmp_path / "evidence.txt"
    source.write_bytes(b"fixed offline source evidence")
    inputs = TWSEInput(data, (), {"evidence.txt": source},
                       {"evidence.txt": hashlib.sha256(source.read_bytes()).hexdigest()}, {})
    periods = {"development": (str(dates[120].date()), str(dates[-1].date()))}
    return inputs, periods, calendar


def assess(prepared, **kwargs):
    inputs, periods, calendar = prepared
    return assess_study_readiness(inputs, periods, calendar=calendar, **kwargs)


def test_complete_inputs_are_ready_and_read_only(prepared):
    inputs, _, _ = prepared
    before = {name: path.read_bytes() for name, path in inputs.source_files.items()}
    result = assess(prepared)
    assert result.periods[0].status == ReadinessStatus.READY
    assert len(result.periods[0].warmup.verified_sessions) == 120
    assert result.readiness_fingerprint == assess(prepared).readiness_fingerprint
    assert before == {name: path.read_bytes() for name, path in inputs.source_files.items()}


def test_common_missing_day_blocks_despite_120_observed_rows(prepared):
    inputs, periods, calendar = prepared
    day = inputs.data.close.index[50]
    data = inputs.data
    frames = {name: getattr(data, name).drop(index=day) for name in
              ("open", "close", "volume", "raw_open", "raw_close")}
    missing = MarketData(**frames)
    assert len(missing.close) >= 120
    result = assess((replace(inputs, data=missing), periods, calendar))
    assert result.periods[0].status == ReadinessStatus.BLOCKED
    assert len(result.periods[0].warmup.verified_sessions) == 119


def test_benchmark_missing_quote_or_entire_symbol_blocks(prepared):
    inputs, periods, calendar = prepared
    raw = inputs.data.raw_open.copy()
    raw.iloc[121, raw.columns.get_loc("0050.TW")] = float("nan")
    result = assess((replace(inputs, data=replace(inputs.data, raw_open=raw)), periods, calendar))
    assert any(f.symbol == "0050.TW" for f in result.findings)
    assert result.periods[0].status == ReadinessStatus.BLOCKED
    result = assess(prepared, required_symbols=("absent.TW",))
    assert any(f.code == FindingCode.MISSING_SYMBOL for f in result.findings)


def test_unknown_legacy_issue_and_missing_calendar_do_not_pass(prepared):
    inputs, periods, calendar = prepared
    start, end = periods["development"]
    issue = TWSEIssue(start, end, "*", "new unsupported legacy rule")
    result = assess((replace(inputs, issues=(issue,)), periods, calendar))
    assert result.periods[0].status == ReadinessStatus.UNKNOWN
    result = assess_study_readiness(inputs, periods, calendar=None)
    assert result.periods[0].status == ReadinessStatus.UNKNOWN
    result = assess((inputs, periods, replace(calendar, coverage_end=start)))
    assert result.periods[0].status == ReadinessStatus.UNKNOWN


def test_source_tampering_and_longer_warmup(prepared):
    assert assess(prepared, warmup=121).periods[0].status == ReadinessStatus.BLOCKED
    inputs, _, _ = prepared
    inputs.source_files["evidence.txt"].write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        assess(prepared)


def test_price_fix_does_not_remove_event_review_blocker(prepared):
    inputs, periods, calendar = prepared
    start, end = periods["development"]
    issue = TWSEIssue(start, end, "2330.TW", "缺少企業行動覆蓋審核：split")
    result = assess((replace(inputs, issues=(issue,)), periods, calendar))
    assert result.periods[0].status == ReadinessStatus.BLOCKED
    assert any(f.code == FindingCode.COVERAGE_REVIEW for f in result.findings)


def test_duplicate_legacy_findings_retain_occurrence_count(prepared):
    inputs, periods, calendar = prepared
    start, end = periods["development"]
    issue = TWSEIssue(start, end, "2330.TW", "缺少企業行動覆蓋審核：split")
    result = assess((replace(inputs, issues=(issue, issue)), periods, calendar))
    finding = next(f for f in result.findings if f.code == FindingCode.COVERAGE_REVIEW)
    assert finding.occurrences == 2
    assert finding.finding_id in result.periods[0].blocking_ids


def test_nonfinite_signal_valuation_is_not_ready(prepared):
    inputs, periods, calendar = prepared
    close = inputs.data.close.copy()
    close.iloc[-1, 0] = float("inf")
    result = assess((replace(inputs, data=replace(inputs.data, close=close)), periods, calendar))
    assert result.periods[0].status == ReadinessStatus.BLOCKED
    assert any(f.code == FindingCode.DERIVED_STATE for f in result.findings)
    assert not any(f.code == FindingCode.MISSING_SESSION for f in result.findings)
