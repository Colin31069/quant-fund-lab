import pandas as pd
import pytest

from quant_fund_lab.cash_in_lieu_analytics import (
    cash_in_lieu_by_source,
    summarize_cash_in_lieu,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-01-05"),
                "symbol": "AAA",
                "action": "stock_split",
                "cash_value": 5.0,
                "cash_in_lieu_price_source": "raw_open_fallback",
                "fractional_quantity": 0.25,
                "cash_in_lieu_settlement_date": "2026-01-05T00:00:00",
            },
            {
                "timestamp": pd.Timestamp("2026-01-06"),
                "symbol": "BBB",
                "action": "stock_split",
                "cash_value": 0.0,
                "cash_in_lieu_price_source": "pending_settlement",
                "fractional_quantity": 0.50,
                "cash_in_lieu_settlement_date": "2026-01-08T00:00:00",
            },
            {
                "timestamp": pd.Timestamp("2026-01-08"),
                "symbol": "BBB",
                "action": "cash_in_lieu_settlement",
                "cash_value": 9.0,
                "cash_in_lieu_price_source": "provider_settlement",
                "fractional_quantity": 0.50,
                "cash_in_lieu_settlement_date": "2026-01-08T00:00:00",
            },
        ]
    )


def test_cash_in_lieu_summary_tracks_source_lag_and_cash():
    summary = summarize_cash_in_lieu(_events())

    assert summary == {
        "fractional_split_event_count": 2,
        "immediate_settlement_count": 1,
        "delayed_receivable_count": 1,
        "delayed_settlement_count": 1,
        "provider_settlement_count": 1,
        "raw_open_fallback_count": 1,
        "unresolved_receivable_count": 0,
        "cash_in_lieu_cash": pytest.approx(14.0),
        "average_settlement_lag_days": pytest.approx(1.0),
        "max_settlement_lag_days": pytest.approx(2.0),
    }

    by_source = cash_in_lieu_by_source(_events())
    assert set(by_source.index) == {"provider_settlement", "raw_open_fallback"}
    assert by_source.loc["provider_settlement", "cash_value"] == pytest.approx(9.0)
    assert by_source.loc["raw_open_fallback", "cash_value"] == pytest.approx(5.0)


def test_cash_in_lieu_summary_reports_unresolved_receivable():
    events = _events().iloc[:2].copy()
    summary = summarize_cash_in_lieu(events)
    assert summary["delayed_receivable_count"] == 1
    assert summary["delayed_settlement_count"] == 0
    assert summary["unresolved_receivable_count"] == 1
    assert summary["cash_in_lieu_cash"] == pytest.approx(5.0)


def test_cash_in_lieu_summary_rejects_orphan_settlement_event():
    events = _events().iloc[[0, 2]].copy()
    with pytest.raises(ValueError, match="no pending receivable"):
        summarize_cash_in_lieu(events)


def test_cash_in_lieu_summary_is_empty_safe_and_schema_strict():
    summary = summarize_cash_in_lieu(pd.DataFrame())
    assert summary["fractional_split_event_count"] == 0
    assert summary["cash_in_lieu_cash"] == 0.0

    with pytest.raises(ValueError, match="missing cash-in-lieu columns"):
        summarize_cash_in_lieu(pd.DataFrame([{"action": "stock_split"}]))
