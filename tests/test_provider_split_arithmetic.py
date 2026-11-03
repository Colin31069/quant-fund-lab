"""Provider-selected raw ETF prices retain one sourced split and execution basis."""
import hashlib
import json

import pandas as pd
import pytest
from test_odd_lot_price_inputs import bundle as bundle  # noqa: PLC0414 -- fixture re-export
from test_twse_odd_lot import _bundle

from quant_fund_lab.config import DividendWithholdingConfig, MarketCostConfig
from quant_fund_lab.execution import PortfolioState
from quant_fund_lab.odd_lot_execution import simulate_limit_order
from quant_fund_lab.odd_lot_inputs.prepare import prepare_reviewed_odd_lot_input
from quant_fund_lab.odd_lot_inputs.types import PriceSourcePolicy
from quant_fund_lab.odd_lot_paper.distributions import (
    DistributionInput,
    apply_session_distributions,
)


@pytest.mark.parametrize("version", [1, 2])
def test_provider_selected_split_prices_match_independent_shares_returns_and_fill_basis(tmp_path, bundle, version):
    root, symbols = _bundle(tmp_path)
    raw = bundle / "raw/0050.json"
    rows = [{"stock_id": "0050", "date": day, "open": price, "max": price,
             "min": price, "close": price, "Trading_Volume": 1000000,
             "Trading_money": int(price * 1000000), "Trading_turnover": 10}
            for day, price in [("2025-06-10", 188.65), ("2025-06-18", 47.57)]]
    raw.write_text(json.dumps({"status": 200, "msg": "success", "data": rows}))
    manifest_path = bundle / "provider_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=0050"
           "&start_date=2025-06-09&end_date=2025-06-20")
    manifest["sources"][0].update(sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        bytes=raw.stat().st_size, requested_url=url, final_url=url,
        request={"symbol": "0050.TW", "start": "2025-06-09", "end": "2025-06-20"})
    manifest["research_cutoff"] = "2025-06-20"
    # Normalized CSV is optional; this fixture exercises reconstruction directly from raw rows.
    manifest.pop("normalized_sha256")
    manifest.pop("months")
    manifest_path.write_text(json.dumps(manifest))
    before = {p: p.read_bytes() for directory in (root, bundle) for p in directory.rglob("*") if p.is_file()}
    policy = PriceSourcePolicy("2025-06-09", "2025-06-20", "2025-06-20",
        priority=("FinMind", "TWSE"), schema_version=version, policy_id=f"reviewed_provider_v{version}")
    prepared = prepare_reviewed_odd_lot_input(root, bundle, symbols, policy)
    provider = [r for r in prepared.selection.selected if r.source.provider == "FinMind"]
    assert [r.date for r in provider] == ["2025-06-10", "2025-06-18"]
    assert [r.row_locator for r in provider] == ["data[0]", "data[1]"]
    data = prepared.evidence.data
    day = pd.Timestamp("2025-06-18")
    assert data.raw_open.at[day, "0050.TW"] == 47.57
    assert data.stock_splits["0050.TW"].sum() == 4
    assert data.close.at[day, "0050.TW"] / data.close.at["2025-06-10", "0050.TW"] == pytest.approx(
        (4 * 47.57) / 188.65)
    assert pd.isna(data.raw_open.at["2025-06-12", "0050.TW"])
    assert data.volume.at["2025-06-12", "0050.TW"] == 0
    state = PortfolioState(0, {"0050.TW": 10})
    result = apply_session_distributions(DistributionInput(state, (), day, data.dividends.loc[day],
        data.stock_splits.loc[day], data.raw_open.loc[day], DividendWithholdingConfig()))
    assert state.shares == {"0050.TW": 10}  # Pure transition preserves the pre-event state.
    assert result.portfolio.shares == {"0050.TW": 40} and result.portfolio.cash == 0
    assert result.portfolio.equity(data.raw_close.loc[day]) == pytest.approx(40 * 47.57)
    assert len(result.split_events) == 1 and not result.receivables
    fill, _, outcome = simulate_limit_order(PortfolioState(1000), "0050.TW", "BUY", 1,
        data.raw_open.at[day, "0050.TW"], 1000000, 47.57, day,
        MarketCostConfig(commission_bps=0, min_commission=0, slippage_bps=0,
                         impact_coefficient=0, max_participation=1),
        {"kind": "etf", "sell_tax_bps": 0, "price_limit_pct": None}, .01, 1, "fractional")
    assert fill is not None and outcome == "filled"
    assert fill.fill_price == fill.gross_value == 47.57 and fill.quantity == 1
    assert all(p.read_bytes() == content for p, content in before.items())
