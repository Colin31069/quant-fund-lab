import pandas as pd
import pytest

from quant_fund_lab.cash_in_lieu_data import (
    CashInLieuSettlementDataset,
    save_cash_in_lieu_settlement_dataset,
)
from quant_fund_lab.data import MarketData
from quant_fund_lab.research_inputs import load_verified_identity_research_inputs
from quant_fund_lab.security_master_events import (
    SecurityMasterEventDataset,
    save_security_lifecycle_dataset,
)
from quant_fund_lab.snapshot import save_market_data_snapshot

EVENT_COLUMNS = [
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


def _save_ticker_change_inputs(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=8)
    open_px = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0, None, None, None, None, None],
            "BBB": [None, None, None, 13.0, 14.0, 15.0, None, None],
        },
        index=dates,
    )
    close_px = open_px.ffill()
    volume = open_px.notna().astype(float) * 1_000.0
    market = MarketData(open=open_px, close=close_px, volume=volume, exchange="US")
    market_root = tmp_path / "market"
    market_manifest = save_market_data_snapshot(market, market_root)

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
            columns=EVENT_COLUMNS,
        )
    )
    lifecycle_root = tmp_path / "lifecycle"
    lifecycle_manifest = save_security_lifecycle_dataset(lifecycle, lifecycle_root)
    return dates, market_root, lifecycle_root, market_manifest, lifecycle_manifest


def test_verified_research_input_bundle_stitches_identity_and_provenance(tmp_path):
    dates, market_root, lifecycle_root, market_manifest, lifecycle_manifest = (
        _save_ticker_change_inputs(tmp_path)
    )
    bundle = load_verified_identity_research_inputs(
        market_root,
        lifecycle_root,
        ["us:001"],
        base_currency="USD",
    )

    assert bundle.data_provenance == {
        "market_data_dataset_id": market_manifest.dataset_id,
        "security_lifecycle_dataset_id": lifecycle_manifest.dataset_id,
    }
    asset = bundle.data.symbols[0]
    assert list(bundle.data.close.loc[dates[:6], asset]) == [10, 11, 12, 13, 14, 15]
    assert bundle.data.base_currency == "USD"
    assert bundle.data.fx_to_base[asset].dropna().eq(1.0).all()
    assert bundle.assets.loc[asset, "security_id"] == "us:001"


def test_verified_bundle_applies_cash_in_lieu_snapshot_and_provenance(tmp_path):
    dates = pd.bdate_range("2026-01-05", periods=5)
    close = pd.DataFrame({"AAA": [20.0, 21.0, 22.0, 23.0, 24.0]}, index=dates)
    splits = pd.DataFrame(0.0, index=dates, columns=["AAA"])
    splits.loc[dates[1], "AAA"] = 0.5
    market = MarketData(
        open=close,
        close=close,
        raw_open=close,
        raw_close=close,
        volume=pd.DataFrame(1_000.0, index=dates, columns=["AAA"]),
        stock_splits=splits,
        exchange="US",
    )
    market_root = tmp_path / "market-cil"
    market_manifest = save_market_data_snapshot(market, market_root)

    lifecycle = SecurityMasterEventDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "us:aaa",
                    "event_at": dates[0],
                    "event_type": "LISTED",
                    "symbol": "AAA",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                }
            ],
            columns=EVENT_COLUMNS,
        )
    )
    lifecycle_root = tmp_path / "lifecycle-cil"
    lifecycle_manifest = save_security_lifecycle_dataset(lifecycle, lifecycle_root)

    settlements = CashInLieuSettlementDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "us:aaa",
                    "split_date": dates[1],
                    "settlement_date": dates[3],
                    "settlement_price": 18.0,
                    "settlement_date_available_at": dates[1],
                    "settlement_price_available_at": dates[3],
                    "local_currency": "USD",
                    "source": "broker-export",
                }
            ]
        )
    )
    settlement_root = tmp_path / "settlements"
    settlement_manifest = save_cash_in_lieu_settlement_dataset(settlements, settlement_root)

    bundle = load_verified_identity_research_inputs(
        market_root,
        lifecycle_root,
        ["us:aaa"],
        cash_in_lieu_snapshot_directory=settlement_root,
        base_currency="USD",
    )
    asset = bundle.data.symbols[0]
    assert pd.Timestamp(
        bundle.data.cash_in_lieu_settlement_dates.loc[dates[1], asset]
    ) == dates[3]
    assert bundle.data.cash_in_lieu_prices.loc[dates[3], asset] == pytest.approx(18.0)
    assert bundle.cash_in_lieu_snapshot == settlement_manifest
    assert bundle.data_provenance == {
        "market_data_dataset_id": market_manifest.dataset_id,
        "security_lifecycle_dataset_id": lifecycle_manifest.dataset_id,
        "cash_in_lieu_settlement_dataset_id": settlement_manifest.dataset_id,
    }


def test_verified_research_input_bundle_fails_when_requested_identity_is_missing(tmp_path):
    _, market_root, lifecycle_root, _, _ = _save_ticker_change_inputs(tmp_path)
    with pytest.raises(ValueError, match="missing security_ids"):
        load_verified_identity_research_inputs(
            market_root,
            lifecycle_root,
            ["us:missing"],
        )


def test_verified_research_input_bundle_requires_fx_for_cross_currency_identity(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=4)
    market = MarketData(
        open=pd.DataFrame(
            {
                "AAA": [10.0, 11.0, None, None],
                "2330.TW": [None, None, 3_200.0, 3_210.0],
            },
            index=dates,
        ),
        close=pd.DataFrame(
            {
                "AAA": [10.0, 11.0, 11.0, 11.0],
                "2330.TW": [None, None, 3_200.0, 3_210.0],
            },
            index=dates,
        ),
        volume=pd.DataFrame(
            {
                "AAA": [100.0, 100.0, 0.0, 0.0],
                "2330.TW": [0.0, 0.0, 1_000.0, 1_000.0],
            },
            index=dates,
        ),
    )
    market_root = tmp_path / "market"
    save_market_data_snapshot(market, market_root)
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
                    "event_type": "TICKER_CHANGED",
                    "symbol": "2330.TW",
                    "exchange": None,
                    "currency": None,
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
            columns=EVENT_COLUMNS,
        )
    )
    lifecycle_root = tmp_path / "lifecycle"
    save_security_lifecycle_dataset(lifecycle, lifecycle_root)

    with pytest.raises(ValueError, match="USD/TWD FX series is required"):
        load_verified_identity_research_inputs(
            market_root,
            lifecycle_root,
            ["global:1"],
            base_currency="USD",
        )

    bundle = load_verified_identity_research_inputs(
        market_root,
        lifecycle_root,
        ["global:1"],
        base_currency="USD",
        usd_twd=pd.Series(32.0, index=dates),
    )
    asset = bundle.data.symbols[0]
    assert bundle.data.fx_to_base.loc[dates[1], asset] == pytest.approx(1.0)
    assert bundle.data.fx_to_base.loc[dates[2], asset] == pytest.approx(1 / 32.0)
