import pandas as pd
import pytest

from quant_fund_lab.taiwan_fundamentals import (
    normalize_finmind_month_revenue,
    normalize_finmind_statement,
)


def test_taiwan_statement_requires_explicit_availability_mapping():
    raw = pd.DataFrame([
        {"date": "2025-03-31", "stock_id": "2330", "type": "IncomeAfterTaxes", "value": 100.0}
    ])
    availability = pd.DataFrame(columns=["stock_id", "period_end", "available_at"])
    with pytest.raises(ValueError, match="missing point-in-time availability"):
        normalize_finmind_statement(raw, availability, "TaiwanStockFinancialStatements")


def test_taiwan_statement_asof_uses_external_available_at():
    raw = pd.DataFrame([
        {"date": "2025-03-31", "stock_id": "2330", "type": "IncomeAfterTaxes", "value": 100.0},
        {"date": "2025-03-31", "stock_id": "2330", "type": "EPS", "value": 3.5},
    ])
    availability = pd.DataFrame([
        {"stock_id": "2330", "period_end": "2025-03-31", "available_at": "2025-05-08"}
    ])
    dataset = normalize_finmind_statement(
        raw,
        availability,
        "TaiwanStockFinancialStatements",
        symbol_map={"2330": "2330.TW"},
    )
    assert dataset.asof("2025-05-01").empty
    visible = dataset.asof("2025-05-09")
    assert set(visible["metric"]) == {"eps", "net_income"}
    assert set(visible["symbol"]) == {"2330.TW"}


def test_taiwan_statement_allows_explicit_schema_mapping_without_guessing():
    raw = pd.DataFrame([
        {"date": "2025-03-31", "stock_id": "2330", "type": "CustomTotalAssets", "value": 500.0}
    ])
    availability = pd.DataFrame([
        {"stock_id": "2330", "period_end": "2025-03-31", "available_at": "2025-05-08"}
    ])
    dataset = normalize_finmind_statement(
        raw,
        availability,
        "TaiwanStockBalanceSheet",
        metric_map={"CustomTotalAssets": "assets"},
    )
    assert dataset.facts.iloc[0]["metric"] == "assets"


def test_month_revenue_uses_create_time_proxy_and_drops_initialization_backfill():
    raw = pd.DataFrame([
        {
            "date": "2026-03-01", "stock_id": "2330", "revenue": 100.0,
            "revenue_year": 2026, "revenue_month": 3, "create_time": "2026-04-21"
        },
        {
            "date": "2026-05-01", "stock_id": "2330", "revenue": 120.0,
            "revenue_year": 2026, "revenue_month": 5, "create_time": "2026-06-10"
        },
    ])
    dataset = normalize_finmind_month_revenue(raw, symbol_map={"2330": "2330.TW"})
    assert len(dataset.facts) == 1
    row = dataset.facts.iloc[0]
    assert row["metric"] == "monthly_revenue"
    assert row["filed_at"] == pd.Timestamp("2026-06-10")
    assert "proxy" in row["source"]


def test_month_revenue_can_explicitly_allow_initialization_backfill_for_non_backtest_use():
    raw = pd.DataFrame([
        {
            "date": "2025-12-01", "stock_id": "2330", "revenue": 80.0,
            "create_time": "2026-04-21"
        }
    ])
    dataset = normalize_finmind_month_revenue(raw, allow_initialization_backfill=True)
    assert len(dataset.facts) == 1
