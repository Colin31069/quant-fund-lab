"""Validate boundary fixture counts with real matching before heavier report acceptance."""
import pandas as pd
import pytest
from phased_sample_boundaries import sample_boundary_targets

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research


@pytest.mark.parametrize("development,validation", [(29, 30), (30, 29), (30, 30)])
@pytest.mark.parametrize("trim_warmup", [False, True])
def test_boundary_schedule_generates_exact_completed_engine_episodes(monkeypatch, development, validation, trim_warmup):
    dates = pd.DatetimeIndex(expected_market_sessions("TW", "2023-01-01", "2024-12-31").sessions)[:280]
    prices = pd.DataFrame(10000.0, index=dates, columns=["2330.TW", "2317.TW"])
    data = MarketData(prices, prices, prices * 1000000, raw_open=prices.copy(), raw_close=prices.copy())
    research = OddLotResearchConfig(min_commission=0, commission_bps=0, slippage_bps=0,
        fill_fraction=1, max_participation=1, impact_coefficient=0, rebalance_every=1, max_weight=.011)
    base = BacktestConfig(initial_cash=1000000, base_currency="TWD", strategy=StrategyConfig(warmup_days=30))
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets",
        sample_boundary_targets(development, validation,
            signal_starts=(str(dates[119].date()), str(dates[199].date()))))
    for count, start, end in [(development, 120, 199), (validation, 200, 279)]:
        selected = data
        if trim_warmup:
            first = start-120
            selected = MarketData(prices.iloc[first:], prices.iloc[first:], (prices*1000000).iloc[first:],
                                 raw_open=prices.iloc[first:].copy(), raw_close=prices.iloc[first:].copy())
        result = run_odd_lot_research(selected, research, base,
            start=str(dates[start].date()), end=str(dates[end].date()))
        assert result.episodes.status.eq("closed").sum() == count
        assert result.trade_summary["closed_count"] == count
        assert result.trade_summary["sample_sufficient"] == (count == 30)
        assert len(result.fills) == count * 2 and set(result.fills.symbol) == {"2330.TW"}
        # The stock fixture retains its explicit30bps sale tax: one10000 share costs30 per exit.
        assert result.fills.quantity.eq(1).all()
        assert result.fills.loc[result.fills.side.eq("SELL"), "sell_tax"].eq(30).all()
        assert result.equity_curve.iloc[-1].equity == base.initial_cash - count * 30
