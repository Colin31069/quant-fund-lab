import pandas as pd

from quant_fund_lab.data import MarketData
from quant_fund_lab.security_master_events import (
    SecurityMasterEventDataset,
    save_security_lifecycle_dataset,
)
from quant_fund_lab.snapshot import save_market_data_snapshot
from quant_fund_lab.ui_inputs import load_verified_ui_inputs

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


def _fixture(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=8)
    symbols = ["AAA", "BBB", "SPY"]
    values = {
        "AAA": [10.0 + i for i in range(8)],
        "BBB": [20.0 + i for i in range(8)],
        "SPY": [100.0 + i for i in range(8)],
    }
    close = pd.DataFrame(values, index=dates)
    market = MarketData(
        open=close.copy(),
        close=close,
        volume=pd.DataFrame(1_000.0, index=dates, columns=symbols),
        exchange="US",
    )
    market_root = tmp_path / "market"
    market_manifest = save_market_data_snapshot(market, market_root)

    events = []
    for security_id, symbol in [("us:a", "AAA"), ("us:b", "BBB"), ("us:spy", "SPY")]:
        events.append(
            {
                "security_id": security_id,
                "event_at": dates[0],
                "event_type": "LISTED",
                "symbol": symbol,
                "exchange": "NYSE",
                "currency": "USD",
                "last_tradable_at": None,
                "terminal_return": None,
                "source": "fixture",
            }
        )
    lifecycle = SecurityMasterEventDataset(pd.DataFrame(events, columns=EVENT_COLUMNS))
    lifecycle_root = tmp_path / "lifecycle"
    lifecycle_manifest = save_security_lifecycle_dataset(lifecycle, lifecycle_root)
    return dates, market_root, lifecycle_root, market_manifest, lifecycle_manifest


def test_verified_ui_inputs_maps_security_ids_and_preserves_provenance(tmp_path):
    dates, market_root, lifecycle_root, market_manifest, lifecycle_manifest = _fixture(tmp_path)
    result = load_verified_ui_inputs(
        market_root,
        lifecycle_root,
        ["us:a", "us:b"],
        "us:spy",
        start=dates[2],
        end=dates[6],
        base_currency="USD",
    )

    assert len(result.trade_assets) == 2
    assert result.benchmark_asset not in result.trade_assets
    assert result.trade_data.symbols == list(result.trade_assets)
    assert result.raw.close.index.min() == dates[2]
    assert result.raw.close.index.max() == dates[6]
    assert result.raw.fx_to_base[result.benchmark_asset].eq(1.0).all()
    assert result.data_provenance == {
        "market_data_dataset_id": market_manifest.dataset_id,
        "security_lifecycle_dataset_id": lifecycle_manifest.dataset_id,
    }
