import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.data import MarketData
from quant_fund_lab.fundamentals import FundamentalDataset
from quant_fund_lab.market_cap import (
    estimate_market_cap_from_fundamentals,
    split_adjusted_reported_shares,
)
from quant_fund_lab.snapshot import load_market_data_snapshot, save_market_data_snapshot

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


def test_market_data_defaults_raw_prices_to_existing_basis():
    dates = pd.bdate_range("2026-01-02", periods=3)
    close = pd.DataFrame({"AAA": [10.0, 11.0, 12.0]}, index=dates)
    data = MarketData(
        open=close,
        close=close,
        volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
    )
    pd.testing.assert_frame_equal(data.raw_open, data.open)
    pd.testing.assert_frame_equal(data.raw_close, data.close)


def test_snapshot_v6_round_trips_raw_price_and_asset_metadata(tmp_path):
    dates = pd.bdate_range("2026-01-02", periods=3)
    adjusted = pd.DataFrame({"AAA": [50.0, 51.0, 52.0]}, index=dates)
    raw = pd.DataFrame({"AAA": [100.0, 102.0, 104.0]}, index=dates)
    data = MarketData(
        open=adjusted,
        close=adjusted,
        volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
        raw_open=raw,
        raw_close=raw,
        market_codes=pd.DataFrame("US", index=dates, columns=["AAA"]),
        currency_codes=pd.DataFrame("USD", index=dates, columns=["AAA"]),
    )
    root = tmp_path / "snapshot"
    save_market_data_snapshot(data, root)
    loaded = load_market_data_snapshot(root)
    pd.testing.assert_frame_equal(loaded.raw_open, raw, check_freq=False)
    pd.testing.assert_frame_equal(loaded.raw_close, raw, check_freq=False)
    pd.testing.assert_frame_equal(loaded.close, adjusted, check_freq=False)
    pd.testing.assert_frame_equal(
        loaded.market_codes, data.market_codes, check_freq=False, check_dtype=False
    )
    pd.testing.assert_frame_equal(
        loaded.currency_codes, data.currency_codes, check_freq=False, check_dtype=False
    )


def test_market_data_validates_and_slices_point_in_time_asset_metadata():
    dates = pd.bdate_range("2026-01-02", periods=4)
    close = pd.DataFrame({"AAA": [10.0, 11.0, 12.0, 13.0]}, index=dates)
    data = MarketData(
        open=close,
        close=close,
        volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
        market_codes=pd.DataFrame(["us", "US", "US", "US"], index=dates, columns=["AAA"]),
        currency_codes=pd.DataFrame("usd", index=dates, columns=["AAA"]),
    )
    sliced = data.slice(start=dates[1], end=dates[2])
    assert set(sliced.market_codes["AAA"].dropna()) == {"US"}
    assert set(sliced.currency_codes["AAA"].dropna()) == {"USD"}

    with pytest.raises(ValueError, match="market_codes contains unsupported"):
        MarketData(
            open=close,
            close=close,
            volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
            market_codes=pd.DataFrame("EU", index=dates, columns=["AAA"]),
        )


def test_cash_in_lieu_settlement_prices_validate_slice_and_snapshot(tmp_path):
    dates = pd.bdate_range("2026-01-02", periods=4)
    close = pd.DataFrame({"AAA": [10.0, 11.0, 12.0, 13.0]}, index=dates)
    settlements = pd.DataFrame(
        {"AAA": [float("nan"), 18.25, float("nan"), float("nan")]},
        index=dates,
    )
    settlement_dates = pd.DataFrame(pd.NaT, index=dates, columns=["AAA"])
    settlement_dates.loc[dates[1], "AAA"] = dates[3]
    data = MarketData(
        open=close,
        close=close,
        volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
        cash_in_lieu_prices=settlements,
        cash_in_lieu_settlement_dates=settlement_dates,
    )

    sliced = data.slice(start=dates[1], end=dates[2])
    assert sliced.cash_in_lieu_prices.loc[dates[1], "AAA"] == pytest.approx(18.25)
    assert pd.Timestamp(
        sliced.cash_in_lieu_settlement_dates.loc[dates[1], "AAA"]
    ) == dates[3]

    root = tmp_path / "cil-snapshot"
    save_market_data_snapshot(data, root)
    loaded = load_market_data_snapshot(root)
    pd.testing.assert_frame_equal(
        loaded.cash_in_lieu_prices,
        settlements,
        check_freq=False,
    )
    pd.testing.assert_frame_equal(
        loaded.cash_in_lieu_settlement_dates,
        settlement_dates,
        check_freq=False,
    )

    invalid = settlements.copy()
    invalid.loc[dates[1], "AAA"] = 0.0
    with pytest.raises(ValueError, match="cash_in_lieu_prices"):
        MarketData(
            open=close,
            close=close,
            volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
            cash_in_lieu_prices=invalid,
        )

    invalid_dates = settlement_dates.copy()
    invalid_dates.loc[dates[1], "AAA"] = dates[0]
    with pytest.raises(ValueError, match="cannot precede"):
        MarketData(
            open=close,
            close=close,
            volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
            cash_in_lieu_settlement_dates=invalid_dates,
        )


def test_split_adjusted_reported_shares_keeps_raw_market_cap_continuous():
    dates = pd.bdate_range("2026-01-02", periods=4)
    reported = pd.DataFrame({"AAA": [10.0, 10.0, 10.0, 10.0]}, index=dates)
    splits = pd.DataFrame({"AAA": [0.0, 0.0, 2.0, 0.0]}, index=dates)
    effective = split_adjusted_reported_shares(reported, splits)
    assert effective.loc[dates[1], "AAA"] == pytest.approx(10.0)
    assert effective.loc[dates[2], "AAA"] == pytest.approx(20.0)
    raw_close = pd.Series([100.0, 100.0, 50.0, 50.0], index=dates)
    market_cap = raw_close * effective["AAA"]
    assert market_cap.loc[dates[1]] == pytest.approx(market_cap.loc[dates[2]])


def test_new_share_report_resets_split_adjusted_carry():
    dates = pd.bdate_range("2026-01-02", periods=5)
    reported = pd.DataFrame({"AAA": [10.0, 10.0, 10.0, 22.0, 22.0]}, index=dates)
    splits = pd.DataFrame({"AAA": [0.0, 0.0, 2.0, 0.0, 0.0]}, index=dates)
    effective = split_adjusted_reported_shares(reported, splits)
    assert effective.loc[dates[2], "AAA"] == pytest.approx(20.0)
    assert effective.loc[dates[3], "AAA"] == pytest.approx(22.0)


def test_market_cap_uses_raw_close_and_point_in_time_filed_shares():
    dates = pd.bdate_range("2026-01-02", periods=5)
    adjusted_close = pd.DataFrame({"AAA": [50.0] * 5}, index=dates)
    raw_close = pd.DataFrame({"AAA": [100.0, 100.0, 50.0, 50.0, 50.0]}, index=dates)
    splits = pd.DataFrame({"AAA": [0.0, 0.0, 2.0, 0.0, 0.0]}, index=dates)
    data = MarketData(
        open=adjusted_close,
        close=adjusted_close,
        volume=pd.DataFrame(1000.0, index=dates, columns=["AAA"]),
        raw_open=raw_close,
        raw_close=raw_close,
        stock_splits=splits,
        fx_to_base=pd.DataFrame(2.0, index=dates, columns=["AAA"]),
        fx_age_days=pd.DataFrame(0.0, index=dates, columns=["AAA"]),
        base_currency="TWD",
    )
    facts = pd.DataFrame(
        [{
            "symbol": "AAA",
            "metric": "shares_outstanding",
            "value": 10.0,
            "unit": "shares",
            "period_start": None,
            "period_end": "2026-01-01",
            "filed_at": dates[0],
            "form": "10-Q",
            "accession": "shares-1",
            "fiscal_year": 2026,
            "fiscal_period": "Q1",
            "source": "fixture",
        }],
        columns=COLUMNS,
    )
    result = estimate_market_cap_from_fundamentals(data, FundamentalDataset(facts))
    assert result.local_market_cap.loc[dates[1], "AAA"] == pytest.approx(1000.0)
    assert result.local_market_cap.loc[dates[2], "AAA"] == pytest.approx(1000.0)
    assert result.base_market_cap.loc[dates[2], "AAA"] == pytest.approx(2000.0)
    assert np.isfinite(result.base_market_cap.to_numpy()).all()
