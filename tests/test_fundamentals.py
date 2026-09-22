import pandas as pd
import pytest

from quant_fund_lab.fundamentals import (
    FundamentalDataset,
    load_fundamental_dataset,
    save_fundamental_dataset,
)
from quant_fund_lab.sec_fundamentals import (
    SecCompanyFactsProvider,
    _normalize_ticker_mapping,
    parse_companyfacts,
)

COLUMNS = [
    "symbol", "metric", "value", "unit", "period_start", "period_end", "filed_at",
    "form", "accession", "fiscal_year", "fiscal_period", "source"
]


def _sec_fixture():
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01", "end": "2025-03-31", "val": 100.0,
                                "accn": "0001", "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01"
                            },
                            {
                                "start": "2025-01-01", "end": "2025-03-31", "val": 110.0,
                                "accn": "0002", "fy": 2025, "fp": "Q1", "form": "10-Q/A", "filed": "2025-05-20"
                            },
                            {
                                "start": "2025-04-01", "end": "2025-06-30", "val": 130.0,
                                "accn": "0003", "fy": 2025, "fp": "Q2", "form": "10-Q", "filed": "2025-08-01"
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-03-31", "val": 1000.0, "accn": "0001", "fy": 2025,
                                "fp": "Q1", "form": "10-Q", "filed": "2025-05-01"
                            }
                        ]
                    }
                },
            }
        }
    }


def test_sec_parser_and_asof_use_filing_date_not_period_end():
    dataset = parse_companyfacts("AAPL", _sec_fixture())
    assert set(dataset.metrics) == {"assets", "net_income"}
    before_filing = dataset.asof("2025-04-15", metrics=["net_income"])
    assert before_filing.empty
    original = dataset.asof("2025-05-10", metrics=["net_income"])
    assert float(original.iloc[0]["value"]) == 100.0
    amended = dataset.asof("2025-06-01", metrics=["net_income"])
    assert float(amended.iloc[0]["value"]) == 110.0
    later = dataset.asof("2025-09-01", metrics=["net_income"])
    assert float(later.iloc[0]["value"]) == 130.0


def test_metric_panel_never_backfills_future_filing():
    dataset = parse_companyfacts("AAPL", _sec_fixture())
    dates = pd.DatetimeIndex(["2025-04-15", "2025-05-10", "2025-06-01", "2025-08-10"])
    panel = dataset.metric_panel("net_income", dates, ["AAPL"])
    assert pd.isna(panel.loc[pd.Timestamp("2025-04-15"), "AAPL"])
    assert panel.loc[pd.Timestamp("2025-05-10"), "AAPL"] == pytest.approx(100.0)
    assert panel.loc[pd.Timestamp("2025-06-01"), "AAPL"] == pytest.approx(110.0)
    assert panel.loc[pd.Timestamp("2025-08-10"), "AAPL"] == pytest.approx(130.0)


def test_fundamental_dataset_round_trip(tmp_path):
    dataset = parse_companyfacts("AAPL", _sec_fixture())
    path = save_fundamental_dataset(dataset, tmp_path / "fundamentals.parquet")
    loaded = load_fundamental_dataset(path)
    pd.testing.assert_frame_equal(dataset.facts, loaded.facts, check_dtype=False)


def test_ticker_mapping_normalization():
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }
    assert _normalize_ticker_mapping(payload) == {"AAPL": 320193, "MSFT": 789019}


def test_sec_provider_requires_declared_contact(monkeypatch):
    monkeypatch.delenv("QFL_SEC_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="User-Agent"):
        SecCompanyFactsProvider(user_agent=None)


def test_dataset_rejects_missing_filed_at():
    bad = pd.DataFrame([
        {
            "symbol": "AAA", "metric": "assets", "value": 1.0, "unit": "USD",
            "period_start": None, "period_end": "2025-03-31", "filed_at": None,
            "form": "10-Q", "accession": "x", "fiscal_year": 2025,
            "fiscal_period": "Q1", "source": "fixture"
        }
    ], columns=COLUMNS)
    with pytest.raises(ValueError, match="filed_at"):
        FundamentalDataset(bad)
