import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.data import MarketData
from quant_fund_lab.execution import market_for_symbol
from quant_fund_lab.fx import attach_fx_rates, currency_for_symbol
from quant_fund_lab.identity_market_data import stitch_market_data_by_identity
from quant_fund_lab.security_master_events import SecurityMasterEventDataset

COLUMNS = [
    "security_id",
    "event_at",
    "event_type",
    "symbol",
    "exchange",
    "currency",
    "last_tradable_at",
    "terminal_return",
    "source",
]


def _ticker_change_data():
    dates = pd.bdate_range("2024-01-02", periods=8)
    open_px = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0, np.nan, np.nan, np.nan, np.nan, np.nan],
            "BBB": [np.nan, np.nan, np.nan, 13.0, 14.0, 15.0, np.nan, np.nan],
        },
        index=dates,
    )
    close_px = open_px.copy()
    volume = open_px.notna().astype(float) * 1_000.0
    settlements = pd.DataFrame(float("nan"), index=dates, columns=["AAA", "BBB"])
    settlements.loc[dates[1], "AAA"] = 11.25
    settlements.loc[dates[4], "BBB"] = 14.25
    data = MarketData(
        open=open_px,
        close=close_px,
        volume=volume,
        cash_in_lieu_prices=settlements,
        exchange="US",
    )
    lifecycle = SecurityMasterEventDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "us:001",
                    "event_at": dates[0],
                    "event_type": "LISTED",
                    "symbol": "AAA",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
                {
                    "security_id": "us:001",
                    "event_at": dates[3],
                    "event_type": "TICKER_CHANGED",
                    "symbol": "BBB",
                    "exchange": None,
                    "currency": None,
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
                {
                    "security_id": "us:001",
                    "event_at": dates[6],
                    "event_type": "DELISTED",
                    "symbol": None,
                    "exchange": None,
                    "currency": None,
                    "last_tradable_at": dates[5],
                    "terminal_return": -0.8,
                    "source": "fixture",
                },
            ],
            columns=COLUMNS,
        )
    )
    return dates, data, lifecycle


def test_stitch_ticker_change_preserves_continuous_identity_and_terminal_event():
    dates, data, lifecycle = _ticker_change_data()
    result = stitch_market_data_by_identity(data, lifecycle, ["us:001"])
    assert len(result.data.symbols) == 1
    asset = result.data.symbols[0]
    assert asset.startswith("BBB@@us:001")
    assert result.assets.loc[asset, "canonical_symbol"] == "BBB"
    assert result.assets.loc[asset, "aliases"] == ("AAA", "BBB")
    assert list(result.data.close.loc[dates[:6], asset]) == [10, 11, 12, 13, 14, 15]
    assert result.data.reference.loc[dates[3], asset] == pytest.approx(12.0)
    assert result.data.membership.loc[dates[5], asset]
    assert not result.data.membership.loc[dates[6], asset]
    assert result.data.terminal_returns.loc[dates[6], asset] == pytest.approx(-0.8)
    assert market_for_symbol(asset) == "US"
    assert currency_for_symbol(asset) == "USD"
    assert set(result.data.market_codes[asset].dropna()) == {"US"}
    assert set(result.data.currency_codes[asset].dropna()) == {"USD"}
    assert result.data.cash_in_lieu_prices.loc[dates[1], asset] == pytest.approx(11.25)
    assert result.data.cash_in_lieu_prices.loc[dates[4], asset] == pytest.approx(14.25)


def test_ticker_reuse_creates_two_stable_assets_without_prelisting_price_leakage():
    dates = pd.bdate_range("2020-01-02", periods=8)
    open_px = pd.DataFrame(
        {"ABC": [10.0, 11.0, 12.0, np.nan, np.nan, 20.0, 21.0, 22.0]},
        index=dates,
    )
    close_px = pd.DataFrame(
        {"ABC": [10.0, 11.0, 12.0, 12.0, 12.0, 20.0, 21.0, 22.0]},
        index=dates,
    )
    volume = open_px.notna().astype(float) * 1_000.0
    data = MarketData(open=open_px, close=close_px, volume=volume, exchange="US")
    lifecycle = SecurityMasterEventDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "us:old",
                    "event_at": dates[0],
                    "event_type": "LISTED",
                    "symbol": "ABC",
                    "exchange": "NYSE",
                    "currency": "USD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
                {
                    "security_id": "us:old",
                    "event_at": dates[3],
                    "event_type": "DELISTED",
                    "symbol": None,
                    "exchange": None,
                    "currency": None,
                    "last_tradable_at": dates[2],
                    "terminal_return": -1.0,
                    "source": "fixture",
                },
                {
                    "security_id": "us:new",
                    "event_at": dates[5],
                    "event_type": "LISTED",
                    "symbol": "ABC",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
            ],
            columns=COLUMNS,
        )
    )
    result = stitch_market_data_by_identity(data, lifecycle, ["us:old", "us:new"])
    old_key = result.assets[result.assets["security_id"].eq("us:old")].index[0]
    new_key = result.assets[result.assets["security_id"].eq("us:new")].index[0]
    assert old_key != new_key
    assert result.data.close.loc[dates[2], old_key] == pytest.approx(12.0)
    assert pd.isna(result.data.close.loc[dates[5], old_key])
    assert pd.isna(result.data.close.loc[dates[4], new_key])
    assert result.data.close.loc[dates[5], new_key] == pytest.approx(20.0)
    assert result.data.terminal_returns.loc[dates[3], old_key] == pytest.approx(-1.0)


def test_missing_alias_market_data_fails_closed():
    _, data, lifecycle = _ticker_change_data()
    missing = MarketData(
        open=data.open[["AAA"]],
        close=data.close[["AAA"]],
        volume=data.volume[["AAA"]],
        exchange="US",
    )
    with pytest.raises(ValueError, match="missing lifecycle symbol BBB"):
        stitch_market_data_by_identity(missing, lifecycle, ["us:001"])


def test_exchange_and_currency_transitions_materialize_point_in_time_metadata_and_fx():
    dates = pd.bdate_range("2024-01-02", periods=4)
    base = MarketData(
        open=pd.DataFrame({"AAA": [10.0, 11.0, 12.0, 13.0]}, index=dates),
        close=pd.DataFrame({"AAA": [10.0, 11.0, 12.0, 13.0]}, index=dates),
        volume=pd.DataFrame({"AAA": [100.0] * 4}, index=dates),
        exchange="US",
    )
    source_with_us_fx = attach_fx_rates(base, "USD")
    lifecycle = SecurityMasterEventDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "global:1",
                    "event_at": dates[0],
                    "event_type": "LISTED",
                    "symbol": "AAA",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
                {
                    "security_id": "global:1",
                    "event_at": dates[2],
                    "event_type": "EXCHANGE_CHANGED",
                    "symbol": None,
                    "exchange": "TWSE",
                    "currency": None,
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
                {
                    "security_id": "global:1",
                    "event_at": dates[2],
                    "event_type": "CURRENCY_CHANGED",
                    "symbol": None,
                    "exchange": None,
                    "currency": "TWD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
            ],
            columns=COLUMNS,
        )
    )
    result = stitch_market_data_by_identity(source_with_us_fx, lifecycle, ["global:1"])
    asset = result.data.symbols[0]
    assert list(result.data.market_codes[asset]) == ["US", "US", "TW", "TW"]
    assert list(result.data.currency_codes[asset]) == ["USD", "USD", "TWD", "TWD"]
    assert result.data.exchange is None
    assert result.data.fx_to_base is None
    usd_twd = pd.Series(32.0, index=dates, dtype=float)
    converted = attach_fx_rates(result.data, "USD", usd_twd=usd_twd)
    assert converted.fx_to_base.loc[dates[1], asset] == pytest.approx(1.0)
    assert converted.fx_to_base.loc[dates[2], asset] == pytest.approx(1.0 / 32.0)


def test_tw_stable_asset_key_preserves_market_and_currency_inference():
    dates = pd.bdate_range("2024-01-02", periods=3)
    data = MarketData(
        open=pd.DataFrame({"2330.TW": [600.0, 605.0, 610.0]}, index=dates),
        close=pd.DataFrame({"2330.TW": [602.0, 607.0, 612.0]}, index=dates),
        volume=pd.DataFrame({"2330.TW": [1_000.0] * 3}, index=dates),
        exchange="TW",
    )
    lifecycle = SecurityMasterEventDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "tw:isin:2330",
                    "event_at": dates[0],
                    "event_type": "LISTED",
                    "symbol": "2330.TW",
                    "exchange": "TWSE",
                    "currency": "TWD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                }
            ],
            columns=COLUMNS,
        )
    )
    result = stitch_market_data_by_identity(data, lifecycle, ["tw:isin:2330"])
    asset = result.data.symbols[0]
    assert asset.endswith(".TW")
    assert market_for_symbol(asset) == "TW"
    assert currency_for_symbol(asset) == "TWD"
    assert result.data.exchange == "TW"
    assert set(result.data.market_codes[asset].dropna()) == {"TW"}
    assert set(result.data.currency_codes[asset].dropna()) == {"TWD"}
