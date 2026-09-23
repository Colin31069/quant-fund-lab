import pandas as pd
import pytest

from quant_fund_lab.cash_in_lieu_data import (
    CashInLieuCSVProvider,
    CashInLieuSettlementDataset,
    load_cash_in_lieu_settlement_dataset,
    save_cash_in_lieu_settlement_dataset,
)
from quant_fund_lab.data import MarketData

COLUMNS = [
    "security_id",
    "split_date",
    "settlement_date",
    "settlement_price",
    "settlement_date_available_at",
    "settlement_price_available_at",
    "local_currency",
    "source",
]


def _dataset() -> CashInLieuSettlementDataset:
    return CashInLieuSettlementDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "us:aaa",
                    "split_date": "2026-01-06",
                    "settlement_date": "2026-01-08",
                    "settlement_price": 18.0,
                    "settlement_date_available_at": "2026-01-06",
                    "settlement_price_available_at": "2026-01-08",
                    "local_currency": "USD",
                    "source": "broker-export",
                }
            ],
            columns=COLUMNS,
        )
    )


def test_settlement_dataset_rejects_availability_lookahead():
    raw = _dataset().records.copy()
    raw.loc[0, "settlement_date_available_at"] = pd.Timestamp("2026-01-07")
    with pytest.raises(ValueError, match="not known by the split date"):
        CashInLieuSettlementDataset(raw)

    raw = _dataset().records.copy()
    raw.loc[0, "settlement_price_available_at"] = pd.Timestamp("2026-01-09")
    with pytest.raises(ValueError, match="not available"):
        CashInLieuSettlementDataset(raw)


def test_settlement_dataset_applies_verified_panels_by_stable_identity():
    dates = pd.bdate_range("2026-01-05", periods=5)
    close = pd.DataFrame({"AAA@@us:aaa": [20.0, 21.0, 22.0, 23.0, 24.0]}, index=dates)
    splits = pd.DataFrame(0.0, index=dates, columns=close.columns)
    splits.loc[pd.Timestamp("2026-01-06"), "AAA@@us:aaa"] = 0.5
    currencies = pd.DataFrame("USD", index=dates, columns=close.columns)
    data = MarketData(
        open=close,
        close=close,
        raw_open=close,
        raw_close=close,
        volume=pd.DataFrame(1_000.0, index=dates, columns=close.columns),
        stock_splits=splits,
        currency_codes=currencies,
    )
    assets = pd.DataFrame(
        [
            {
                "security_id": "us:aaa",
                "asset_key": "AAA@@us:aaa",
            }
        ]
    )

    applied = _dataset().apply_to_market_data(data, assets)
    assert pd.Timestamp(
        applied.cash_in_lieu_settlement_dates.loc[
            pd.Timestamp("2026-01-06"), "AAA@@us:aaa"
        ]
    ) == pd.Timestamp("2026-01-08")
    assert applied.cash_in_lieu_prices.loc[
        pd.Timestamp("2026-01-08"), "AAA@@us:aaa"
    ] == pytest.approx(18.0)


def test_settlement_dataset_requires_matching_split_and_currency():
    dates = pd.bdate_range("2026-01-05", periods=5)
    close = pd.DataFrame({"AAA": [20.0] * 5}, index=dates)
    assets = pd.DataFrame([{"security_id": "us:aaa", "asset_key": "AAA"}])
    no_split = MarketData(
        open=close,
        close=close,
        volume=pd.DataFrame(1_000.0, index=dates, columns=close.columns),
    )
    with pytest.raises(ValueError, match="no matching split event"):
        _dataset().apply_to_market_data(no_split, assets)

    splits = pd.DataFrame(0.0, index=dates, columns=close.columns)
    splits.loc[pd.Timestamp("2026-01-06"), "AAA"] = 0.5
    wrong_currency = MarketData(
        open=close,
        close=close,
        volume=pd.DataFrame(1_000.0, index=dates, columns=close.columns),
        stock_splits=splits,
        currency_codes=pd.DataFrame("TWD", index=dates, columns=close.columns),
    )
    with pytest.raises(ValueError, match="currency mismatch"):
        _dataset().apply_to_market_data(wrong_currency, assets)


def test_settlement_snapshot_round_trip_and_tamper_detection(tmp_path):
    root = tmp_path / "settlements"
    first = save_cash_in_lieu_settlement_dataset(_dataset(), root)
    loaded, observed = load_cash_in_lieu_settlement_dataset(root)
    second = save_cash_in_lieu_settlement_dataset(loaded, tmp_path / "copy")

    assert observed == first
    assert second.dataset_id == first.dataset_id
    pd.testing.assert_frame_equal(_dataset().records, loaded.records, check_dtype=False)

    path = root / "cash_in_lieu_settlements.parquet"
    content = bytearray(path.read_bytes())
    content[-1] ^= 1
    path.write_bytes(bytes(content))
    with pytest.raises(ValueError, match="file hash mismatch"):
        load_cash_in_lieu_settlement_dataset(root)


def test_csv_provider_maps_columns_and_fills_source(tmp_path):
    raw = pd.DataFrame(
        [
            {
                "sid": "us:aaa",
                "split": "2026-01-06",
                "settle": "2026-01-08",
                "price": 18.0,
                "date_known": "2026-01-06",
                "price_known": "2026-01-08",
                "ccy": "usd",
            }
        ]
    )
    path = tmp_path / "settlements.csv"
    raw.to_csv(path, index=False)
    dataset = CashInLieuCSVProvider(
        source="broker-export",
        column_map={
            "sid": "security_id",
            "split": "split_date",
            "settle": "settlement_date",
            "price": "settlement_price",
            "date_known": "settlement_date_available_at",
            "price_known": "settlement_price_available_at",
            "ccy": "local_currency",
        },
    ).load(path)

    row = dataset.records.iloc[0]
    assert row["security_id"] == "us:aaa"
    assert row["local_currency"] == "USD"
    assert row["source"] == "broker-export"
