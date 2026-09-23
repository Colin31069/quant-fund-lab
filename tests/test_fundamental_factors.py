import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.factors import build_market_factor_panel
from quant_fund_lab.fundamental_factors import build_fundamental_factor_panels
from quant_fund_lab.fundamentals import FundamentalDataset

COLUMNS = [
    "symbol",
    "metric",
    "value",
    "unit",
    "period_start",
    "period_end",
    "filed_at",
    "form",
    "accession",
    "fiscal_year",
    "fiscal_period",
    "source",
]


def _fact(
    symbol,
    metric,
    value,
    period_end,
    filed_at,
    period_start=None,
    form="10-Q",
    accession="x",
    fiscal_period="Q1",
):
    return {
        "symbol": symbol,
        "metric": metric,
        "value": value,
        "unit": "USD",
        "period_start": period_start,
        "period_end": period_end,
        "filed_at": filed_at,
        "form": form,
        "accession": accession,
        "fiscal_year": pd.Timestamp(period_end).year,
        "fiscal_period": fiscal_period,
        "source": "fixture",
    }


def _dataset():
    rows = [
        _fact("AAA", "net_income", 25.0, "2025-03-31", "2025-05-01", "2025-01-01", accession="ni-q1"),
        _fact("AAA", "revenue", 250.0, "2025-03-31", "2025-05-01", "2025-01-01", accession="rev-q1"),
        _fact("AAA", "operating_income", 50.0, "2025-03-31", "2025-05-01", "2025-01-01", accession="op-q1"),
        _fact("AAA", "gross_profit", 100.0, "2025-03-31", "2025-05-01", "2025-01-01", accession="gp-q1"),
        _fact("AAA", "assets", 500.0, "2025-03-31", "2025-05-01", accession="a25"),
        _fact("AAA", "equity", 200.0, "2025-03-31", "2025-05-01", accession="e25"),
        _fact("AAA", "cash", 75.0, "2025-03-31", "2025-05-01", accession="c25"),
        _fact("AAA", "assets", 400.0, "2024-03-31", "2024-05-01", accession="a24"),
        _fact("AAA", "monthly_revenue", 120.0, "2025-06-01", "2025-07-10", accession="mr25"),
        _fact("AAA", "monthly_revenue", 100.0, "2024-06-01", "2024-07-10", accession="mr24"),
        _fact("BBB", "net_income", 10.0, "2025-03-31", "2025-05-03", "2025-01-01", accession="b-ni"),
        _fact("BBB", "assets", 300.0, "2025-03-31", "2025-05-03", accession="b-a"),
        _fact("BBB", "assets", 280.0, "2024-03-31", "2024-05-03", accession="b-a24"),
        _fact("BBB", "equity", 150.0, "2025-03-31", "2025-05-03", accession="b-e"),
    ]
    return FundamentalDataset(pd.DataFrame(rows, columns=COLUMNS))


def test_profitability_margin_quality_and_investment_are_point_in_time():
    dataset = _dataset()
    dates = pd.DatetimeIndex(["2025-04-30", "2025-05-10", "2025-07-15"])
    result = build_fundamental_factor_panels(dataset, dates, ["AAA", "BBB"])
    assert pd.isna(result.panels["profitability_roe"].loc[dates[0], "AAA"])
    expected_annualized_income = 25.0 * 365.0 / 90.0
    assert result.panels["profitability_roe"].loc[dates[1], "AAA"] == pytest.approx(
        expected_annualized_income / 200.0
    )
    assert result.panels["profitability_roa"].loc[dates[1], "AAA"] == pytest.approx(
        expected_annualized_income / 500.0
    )
    assert result.panels["operating_margin"].loc[dates[1], "AAA"] == pytest.approx(0.20)
    assert result.panels["gross_margin"].loc[dates[1], "AAA"] == pytest.approx(0.40)
    assert result.panels["cash_to_assets"].loc[dates[1], "AAA"] == pytest.approx(0.15)
    assert result.panels["conservative_asset_growth"].loc[dates[1], "AAA"] == pytest.approx(-0.25)
    assert result.panels["monthly_revenue_yoy"].loc[dates[2], "AAA"] == pytest.approx(0.20)


def test_future_amendment_does_not_leak_into_earlier_signal():
    dataset = _dataset()
    amendment = pd.DataFrame(
        [
            _fact(
                "AAA",
                "net_income",
                40.0,
                "2025-03-31",
                "2025-06-01",
                "2025-01-01",
                form="10-Q/A",
                accession="ni-amend",
            )
        ],
        columns=COLUMNS,
    )
    amended = FundamentalDataset(pd.concat([dataset.facts, amendment], ignore_index=True))
    dates = pd.DatetimeIndex(["2025-05-15", "2025-06-02"])
    result = build_fundamental_factor_panels(amended, dates, ["AAA"])
    early = result.panels["profitability_roe"].loc[dates[0], "AAA"]
    late = result.panels["profitability_roe"].loc[dates[1], "AAA"]
    assert early == pytest.approx((25.0 * 365.0 / 90.0) / 200.0)
    assert late == pytest.approx((40.0 * 365.0 / 90.0) / 200.0)


def test_flow_selector_prefers_discrete_quarter_over_ytd_context():
    base = _dataset().facts
    extra = pd.DataFrame(
        [
            _fact(
                "AAA",
                "net_income",
                55.0,
                "2025-06-30",
                "2025-08-01",
                "2025-01-01",
                accession="ni-ytd",
                fiscal_period="Q2",
            ),
            _fact(
                "AAA",
                "net_income",
                30.0,
                "2025-06-30",
                "2025-08-01",
                "2025-04-01",
                accession="ni-q2",
                fiscal_period="Q2",
            ),
            _fact("AAA", "equity", 220.0, "2025-06-30", "2025-08-01", accession="e-q2", fiscal_period="Q2"),
        ],
        columns=COLUMNS,
    )
    dataset = FundamentalDataset(pd.concat([base, extra], ignore_index=True))
    date = pd.DatetimeIndex(["2025-08-02"])
    result = build_fundamental_factor_panels(dataset, date, ["AAA"])
    expected = (30.0 * 365.0 / 91.0) / 220.0
    assert result.panels["profitability_roe"].iloc[0, 0] == pytest.approx(expected)


def test_valuation_factors_require_explicit_base_market_cap_and_fx():
    dataset = _dataset()
    dates = pd.DatetimeIndex(["2025-05-10"])
    market_cap = pd.DataFrame({"AAA": [1000.0], "BBB": [800.0]}, index=dates)
    with pytest.raises(ValueError, match="fundamental_fx_to_base"):
        build_fundamental_factor_panels(dataset, dates, ["AAA", "BBB"], market_cap_base=market_cap)

    fx = pd.DataFrame(1.0, index=dates, columns=["AAA", "BBB"])
    result = build_fundamental_factor_panels(
        dataset,
        dates,
        ["AAA", "BBB"],
        market_cap_base=market_cap,
        fundamental_fx_to_base=fx,
    )
    assert result.panels["book_to_market"].loc[dates[0], "AAA"] == pytest.approx(0.20)
    assert result.panels["earnings_yield"].loc[dates[0], "AAA"] == pytest.approx(
        (25.0 * 365.0 / 90.0) / 1000.0
    )
    assert result.panels["small_size"].loc[dates[0], "AAA"] == pytest.approx(-np.log(1000.0))


def test_unknown_duration_flow_fails_closed_instead_of_guessing():
    rows = [
        _fact("AAA", "net_income", 100.0, "2025-03-31", "2025-05-01", period_start=None),
        _fact("AAA", "equity", 200.0, "2025-03-31", "2025-05-01"),
    ]
    dataset = FundamentalDataset(pd.DataFrame(rows, columns=COLUMNS))
    dates = pd.DatetimeIndex(["2025-05-10"])
    result = build_fundamental_factor_panels(dataset, dates, ["AAA"])
    assert pd.isna(result.panels["profitability_roe"].iloc[0, 0])


def test_fundamental_panels_feed_factor_laboratory_without_reindexing():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=400, seed=71)
    dataset = _dataset()
    result = build_fundamental_factor_panels(dataset, data.close.index, data.symbols)
    panel = build_market_factor_panel(
        data,
        sampling_every=5,
        external_factors=result.panels,
    )
    factor_names = set(panel.index.get_level_values("factor"))
    assert "profitability_roe" in factor_names
    assert "conservative_asset_growth" in factor_names


def test_coverage_reports_available_cross_section():
    dataset = _dataset()
    dates = pd.DatetimeIndex(["2025-05-10", "2025-07-15"])
    result = build_fundamental_factor_panels(dataset, dates, ["AAA", "BBB"])
    assert "profitability_roe" in result.coverage.index
    assert result.coverage.loc["profitability_roe", "max_names"] == 2
