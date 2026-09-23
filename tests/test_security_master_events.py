import pandas as pd
import pytest

from quant_fund_lab.security_master_events import (
    SecurityEventCSVProvider,
    SecurityMasterEventDataset,
    merge_security_event_datasets,
    normalize_security_event_frame,
)


def _events() -> SecurityMasterEventDataset:
    return SecurityMasterEventDataset(
        pd.DataFrame(
            [
                {
                    "security_id": "us:001",
                    "event_at": "2020-01-02",
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
                    "event_at": "2022-06-01",
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
                    "event_at": "2023-01-03",
                    "event_type": "EXCHANGE_CHANGED",
                    "symbol": None,
                    "exchange": "NYSE",
                    "currency": None,
                    "last_tradable_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
                {
                    "security_id": "us:001",
                    "event_at": "2024-03-18",
                    "event_type": "DELISTED",
                    "symbol": None,
                    "exchange": None,
                    "currency": None,
                    "last_tradable_at": "2024-03-15",
                    "terminal_return": -0.75,
                    "source": "fixture",
                },
            ]
        )
    )


def test_materialization_is_point_in_time_and_does_not_apply_future_delisting():
    dataset = _events()
    before_ticker_change = dataset.materialize("2021-12-31")
    row = before_ticker_change.records.iloc[0]
    assert row["symbol"] == "AAA"
    assert pd.isna(row["tradable_until"])
    assert pd.isna(row["terminal_event_at"])

    after_ticker_change = dataset.materialize("2022-06-01")
    assert after_ticker_change.records.iloc[0]["symbol"] == "BBB"

    complete = dataset.materialize()
    row = complete.records.iloc[0]
    assert row["symbol"] == "BBB"
    assert row["exchange"] == "NYSE"
    assert row["tradable_until"] == pd.Timestamp("2024-03-15")
    assert row["terminal_event_at"] == pd.Timestamp("2024-03-18")
    assert row["terminal_return"] == pytest.approx(-0.75)


def test_identity_history_uses_exclusive_change_boundaries_without_guessing_trading_days():
    history = _events().identity_history()
    assert list(history["symbol"]) == ["AAA", "BBB", "BBB"]
    assert history.iloc[0]["effective_until_exclusive"] == pd.Timestamp("2022-06-01")
    assert history.iloc[1]["effective_until_exclusive"] == pd.Timestamp("2023-01-03")
    assert history.iloc[2]["effective_until_exclusive"] == pd.Timestamp("2024-03-18")
    assert history.iloc[2]["exchange"] == "NYSE"

    assert _events().identity_at("us:001", "2022-05-31")["symbol"] == "AAA"
    assert _events().identity_at("us:001", "2022-06-01")["symbol"] == "BBB"
    with pytest.raises(KeyError, match="no unique identity"):
        _events().identity_at("us:001", "2024-03-18")


def test_delisting_requires_explicit_last_trade_and_terminal_return():
    raw = _events().events.copy()
    raw.loc[raw["event_type"].eq("DELISTED"), "last_tradable_at"] = pd.NaT
    with pytest.raises(ValueError, match="last_tradable_at"):
        SecurityMasterEventDataset(raw)

    raw = _events().events.copy()
    raw.loc[raw["event_type"].eq("DELISTED"), "terminal_return"] = pd.NA
    with pytest.raises(ValueError, match="terminal_return"):
        SecurityMasterEventDataset(raw)


def test_events_after_delisting_are_rejected():
    raw = _events().events.copy()
    extra = pd.DataFrame(
        [
            {
                "security_id": "us:001",
                "event_at": "2024-04-01",
                "event_type": "TICKER_CHANGED",
                "symbol": "CCC",
                "exchange": "",
                "currency": "",
                "last_tradable_at": pd.NaT,
                "terminal_return": float("nan"),
                "source": "fixture",
            }
        ],
        columns=raw.columns,
    )
    with pytest.raises(ValueError, match="after DELISTED"):
        SecurityMasterEventDataset(pd.concat([raw, extra], ignore_index=True))


def test_us_normalizer_uses_explicit_column_mapping_and_currency_default():
    raw = pd.DataFrame(
        [
            {
                "stable_id": "cik:1",
                "effective": "2020-01-02",
                "kind": "listed",
                "ticker": "abc",
                "venue": "nasdaq",
            }
        ]
    )
    dataset = normalize_security_event_frame(
        raw,
        market="US",
        source="official-export",
        column_map={
            "stable_id": "security_id",
            "effective": "event_at",
            "kind": "event_type",
            "ticker": "symbol",
            "venue": "exchange",
        },
    )
    row = dataset.events.iloc[0]
    assert row["symbol"] == "ABC"
    assert row["exchange"] == "NASDAQ"
    assert row["currency"] == "USD"
    assert row["source"] == "official-export"


def test_taiwan_normalizer_maps_exchange_suffix_without_inventing_security_id():
    raw = pd.DataFrame(
        [
            {
                "security_id": "tw:isin:AAA",
                "event_at": "2010-01-04",
                "event_type": "LISTED",
                "symbol": "2330",
                "exchange": "TSE",
            },
            {
                "security_id": "tw:isin:BBB",
                "event_at": "2015-02-02",
                "event_type": "LISTED",
                "symbol": "6488",
                "exchange": "OTC",
            },
        ]
    )
    dataset = normalize_security_event_frame(raw, market="TW", source="tw-export")
    assert list(dataset.events["symbol"]) == ["2330.TW", "6488.TWO"]
    assert list(dataset.events["exchange"]) == ["TWSE", "TPEX"]
    assert set(dataset.events["currency"]) == {"TWD"}
    assert set(dataset.events["security_id"]) == {"tw:isin:AAA", "tw:isin:BBB"}


def test_csv_provider_and_multi_market_merge(tmp_path):
    us = pd.DataFrame(
        [
            {
                "security_id": "us:1",
                "event_at": "2020-01-02",
                "event_type": "LISTED",
                "symbol": "AAA",
                "exchange": "NASDAQ",
            }
        ]
    )
    path = tmp_path / "us.csv"
    us.to_csv(path, index=False)
    us_dataset = SecurityEventCSVProvider("US", "us-file").load(path)

    tw = normalize_security_event_frame(
        pd.DataFrame(
            [
                {
                    "security_id": "tw:1",
                    "event_at": "2020-01-02",
                    "event_type": "LISTED",
                    "symbol": "2330",
                    "exchange": "TWSE",
                }
            ]
        ),
        market="TW",
        source="tw-file",
    )
    merged = merge_security_event_datasets(us_dataset, tw)
    assert set(merged.security_ids) == {"us:1", "tw:1"}
    assert set(merged.materialize().symbols) == {"AAA", "2330.TW"}
