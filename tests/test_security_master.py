import pandas as pd
import pytest

from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.security_master import (
    SecurityMaster,
    load_security_master,
    save_security_master,
)

COLUMNS = [
    "security_id",
    "symbol",
    "exchange",
    "currency",
    "tradable_from",
    "tradable_until",
    "terminal_event_at",
    "terminal_return",
    "source",
]


def _master() -> SecurityMaster:
    return SecurityMaster(
        pd.DataFrame(
            [
                {
                    "security_id": "sec-aaa",
                    "symbol": "AAA",
                    "exchange": "US",
                    "currency": "USD",
                    "tradable_from": "2024-01-10",
                    "tradable_until": "2024-03-15",
                    "terminal_event_at": "2024-03-18",
                    "terminal_return": -0.75,
                    "source": "fixture",
                },
                {
                    "security_id": "sec-bbb",
                    "symbol": "BBB",
                    "exchange": "US",
                    "currency": "USD",
                    "tradable_from": "2024-01-02",
                    "tradable_until": None,
                    "terminal_event_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
            ],
            columns=COLUMNS,
        )
    )


def test_membership_does_not_exclude_future_delister_before_last_trade():
    dates = pd.bdate_range("2024-01-02", "2024-03-20")
    membership = _master().membership_panel(dates, ["AAA", "BBB"])
    assert not membership.loc[pd.Timestamp("2024-01-09"), "AAA"]
    assert membership.loc[pd.Timestamp("2024-01-10"), "AAA"]
    assert membership.loc[pd.Timestamp("2024-03-15"), "AAA"]
    assert not membership.loc[pd.Timestamp("2024-03-18"), "AAA"]
    assert membership["BBB"].all()


def test_terminal_return_appears_only_at_or_after_terminal_event():
    dates = pd.bdate_range("2024-03-14", "2024-03-20")
    panel = _master().terminal_return_panel(dates, ["AAA", "BBB"])
    assert pd.isna(panel.loc[pd.Timestamp("2024-03-15"), "AAA"])
    assert panel.loc[pd.Timestamp("2024-03-18"), "AAA"] == pytest.approx(-0.75)
    assert panel["BBB"].isna().all()


def test_security_master_rejects_lookahead_terminal_event_order():
    bad = pd.DataFrame(
        [
            {
                "security_id": "sec-aaa",
                "symbol": "AAA",
                "exchange": "US",
                "currency": "USD",
                "tradable_from": "2024-01-02",
                "tradable_until": "2024-03-15",
                "terminal_event_at": "2024-03-15",
                "terminal_return": -1.0,
                "source": "fixture",
            }
        ],
        columns=COLUMNS,
    )
    with pytest.raises(ValueError, match="after the last tradable date"):
        SecurityMaster(bad)


def test_security_master_rejects_terminal_event_without_last_tradable_date():
    bad = _master().records.copy()
    bad.loc[bad["symbol"] == "AAA", "tradable_until"] = pd.NaT
    with pytest.raises(ValueError, match="requires tradable_until"):
        SecurityMaster(bad)


def test_security_master_rejects_duplicate_security_identity():
    bad = _master().records.copy()
    bad.loc[bad["symbol"] == "BBB", "security_id"] = "sec-aaa"
    with pytest.raises(ValueError, match="security_id must be unique"):
        SecurityMaster(bad)


def test_apply_to_market_data_replaces_observation_based_universe():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=70, seed=81)
    dates = data.close.index
    master = SecurityMaster(
        pd.DataFrame(
            [
                {
                    "security_id": "sec-aaa",
                    "symbol": "AAA",
                    "exchange": "US",
                    "currency": "USD",
                    "tradable_from": dates[10],
                    "tradable_until": dates[50],
                    "terminal_event_at": dates[51],
                    "terminal_return": -1.0,
                    "source": "fixture",
                },
                {
                    "security_id": "sec-bbb",
                    "symbol": "BBB",
                    "exchange": "US",
                    "currency": "USD",
                    "tradable_from": dates[0],
                    "tradable_until": None,
                    "terminal_event_at": None,
                    "terminal_return": None,
                    "source": "fixture",
                },
            ],
            columns=COLUMNS,
        )
    )
    converted = master.apply_to_market_data(data)
    assert not bool(converted.membership.iloc[0]["AAA"])
    assert bool(converted.membership.loc[dates[50], "AAA"])
    assert not bool(converted.membership.loc[dates[51], "AAA"])
    assert converted.terminal_returns.loc[dates[51], "AAA"] == pytest.approx(-1.0)


def test_symbol_matching_is_normalized_and_stripped():
    dates = pd.bdate_range("2024-01-10", periods=3)
    membership = _master().membership_panel(dates, [" aaa ", "bbb"])
    assert list(membership.columns) == ["AAA", "BBB"]
    assert membership["AAA"].all()
    assert membership["BBB"].all()


def test_missing_security_fails_closed_by_default():
    dates = pd.bdate_range("2024-01-02", periods=5)
    with pytest.raises(ValueError, match="missing symbols"):
        _master().membership_panel(dates, ["AAA", "CCC"])


def test_security_master_snapshot_roundtrip_and_tamper_detection(tmp_path):
    master = _master()
    root = tmp_path / "security-master"
    manifest = save_security_master(master, root)
    loaded, loaded_manifest = load_security_master(root)
    assert loaded_manifest.dataset_id == manifest.dataset_id
    pd.testing.assert_frame_equal(master.records, loaded.records, check_dtype=False)

    data_path = root / "security_master.parquet"
    data_path.write_bytes(data_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_security_master(root)
