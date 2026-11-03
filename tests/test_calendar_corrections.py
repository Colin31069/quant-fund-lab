"""Official calendar corrections cover stale providers without hiding bad observations."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_fund_lab.calendar_corrections import apply_official_closure_corrections
from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import (
    expected_market_sessions,
    validate_daily_sessions,
    validate_point_in_time_market_sessions,
)


@pytest.mark.parametrize("stale", [True, False])
def test_stale_and_current_provider_share_official_sessions_without_double_correction(monkeypatch, stale):
    import quant_fund_lab.market_calendar as module

    dates = pd.to_datetime(["2025-01-07", "2025-01-08", "2025-01-10"])
    if stale:
        dates = dates.union(pd.to_datetime(["2025-01-09"]))
    monkeypatch.setattr(module.xcals, "get_calendar", lambda _: SimpleNamespace(
        sessions_in_range=lambda first, last: dates[(dates >= first) & (dates <= last)]))
    expected = expected_market_sessions("US", "2025-01-07", "2025-01-10")
    assert expected.sessions == tuple(pd.to_datetime(["2025-01-07", "2025-01-08", "2025-01-10"]))
    assert ("official-closures-v1:" in expected.revision) is stale
    observed = pd.to_datetime(["2025-01-07", "2025-01-10"])
    report = validate_daily_sessions(observed, "US")
    prices = pd.DataFrame(100.0, index=observed, columns=["ASSET"])
    data = MarketData(prices, prices.copy(), prices * 10,
                      market_codes=pd.DataFrame("US", index=observed, columns=prices.columns))
    point_in_time = validate_point_in_time_market_sessions(data)["US"]
    assert report == point_in_time
    assert report.missing_sessions == (pd.Timestamp("2025-01-08"),)
    bad = validate_daily_sessions(pd.to_datetime(["2025-01-07", "2025-01-09", "2025-01-10"]), "US")
    assert bad.off_calendar_sessions == (pd.Timestamp("2025-01-09"),)


def test_correction_is_market_scoped_and_idempotent():
    dates = pd.date_range("2025-01-07", "2025-01-10")
    for market, calendar in [("TW", "XTAI"), ("US", "OTHER")]:
        actual, revision = apply_official_closure_corrections(market, calendar, dates)
        assert actual.equals(dates) and revision == ""
    first, revision = apply_official_closure_corrections("US", "XNYS", dates)
    second, repeated_revision = apply_official_closure_corrections("US", "XNYS", first)
    assert first.equals(second) and revision and repeated_revision == ""
