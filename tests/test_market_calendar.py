"""Contracts for explicit, versioned expected sessions used by readiness."""
import pandas as pd
import pytest

from quant_fund_lab.market_calendar import expected_market_sessions, validate_daily_sessions


def test_expected_sessions_do_not_shrink_to_observed_rows():
    expected = expected_market_sessions("US", "2025-01-07", "2025-01-10")
    report = validate_daily_sessions(pd.to_datetime(["2025-01-07", "2025-01-10"]), "US")
    assert len(expected.sessions) == report.expected_sessions
    assert pd.Timestamp("2025-01-08") in expected.sessions
    assert expected.calendar == "XNYS"
    assert expected.revision.startswith("exchange-calendars:")
    assert tuple(sorted(set(expected.sessions))) == expected.sessions


@pytest.mark.parametrize("start,end", [(None, "2025-01-10"), ("2025-01-10", "2025-01-07")])
def test_expected_sessions_reject_invalid_boundaries(start, end):
    with pytest.raises(ValueError, match="boundaries"):
        expected_market_sessions("US", start, end)


def test_expected_sessions_normalize_timezone_and_preserve_weekend_closure():
    result = expected_market_sessions("US", "2026-01-03T12:00:00+08:00", "2026-01-04")
    assert result.sessions == ()
    with pytest.raises(ValueError, match="unsupported"):
        expected_market_sessions("unknown", "2026-01-03", "2026-01-04")
