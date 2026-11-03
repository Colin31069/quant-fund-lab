"""Hand-calculated single-ETF benchmark uses shared fees, fills and action accounting."""
from dataclasses import asdict, replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_benchmarks import BenchmarkSpec, run_tradable_benchmark
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research
from quant_fund_lab.odd_lot_study import freeze_odd_lot_study
from quant_fund_lab.twse_odd_lot import _total_return

SYMBOL = "0050.TW"


def _fixture(*, fraction=1.0, price=200.0):
    dates = pd.DatetimeIndex(expected_market_sessions("TW", "2024-01-01", "2024-12-31").sessions)[:36]
    raw = pd.DataFrame(price, index=dates, columns=[SYMBOL])
    opening = raw.copy()
    raw.loc[dates[30]:] = price * 1.05
    opening.loc[dates[31]:] = price * 1.05
    data = MarketData(opening, raw, raw * 10000, raw_open=opening, raw_close=raw)
    base = BacktestConfig(initial_cash=100000, base_currency="TWD", strategy=StrategyConfig(warmup_days=30))
    research = OddLotResearchConfig(min_commission=0, commission_bps=0, slippage_bps=0,
        impact_coefficient=0, fill_fraction=fraction, max_participation=1)
    spec = BenchmarkSpec(SYMBOL,100000,0,0.10,"Explicit offline zero-tax fixture; not a statutory claim.")
    return data, spec, research, base, dates


def test_full_fill_matches_hand_calculation_and_uses_next_session():
    data, spec, research, base, dates = _fixture()
    before = data.raw_close.copy()
    result = run_tradable_benchmark(data, spec, research, base)
    assert result.signals.iloc[0].timestamp == dates[29]
    assert result.fills.iloc[0].timestamp == dates[30]
    assert result.fills.iloc[0].quantity == 500 and result.fills.iloc[0].fill_price == 200
    assert result.equity_curve.loc[dates[30], "equity"] == 105000
    assert result.equity_curve.loc[dates[30], "cash"] == 0
    assert result.equity_curve.loc[dates[30], "buy_payables"] == 100000
    assert result.settlements.iloc[0].settled_at == dates[32]
    assert result.equity_curve.loc[dates[32], "buy_payables"] == 0
    assert len(result.orders) == len(result.fills) == 1
    pd.testing.assert_frame_equal(data.raw_close, before)


def test_partial_entry_expires_without_topup_and_retains_cash():
    data, spec, research, base, dates = _fixture(fraction=0.5)
    result = run_tradable_benchmark(data, spec, research, base)
    order = result.orders.iloc[0]
    assert (order.requested_quantity,order.filled_quantity,order.expired_quantity) == (500,250,250)
    assert order.status == "partial_expired" and len(result.orders) == 1
    assert result.equity_curve.loc[dates[30],"cash"] == 50000
    assert result.equity_curve.loc[dates[30],"equity"] == 102500
    short = run_tradable_benchmark(data.slice(end=dates[31]), spec, research, base)
    assert short.settlements.iloc[0].status == "pending_end_of_data"
    assert short.settlements.iloc[0].sessions_remaining == 1
    pd.testing.assert_frame_equal(result.fills, short.fills)


def test_same_fee_and_slippage_scenario_is_charged_once():
    data, spec, research, base, dates = _fixture(fraction=0.5)
    research = replace(research,min_commission=20,commission_bps=14.25,slippage_bps=5)
    result = run_tradable_benchmark(data, spec, research, base)
    fill = result.fills.iloc[0]
    expected_price = 200.10
    expected_gross = 250 * expected_price
    expected_commission = expected_gross * 14.25 / 10000
    assert fill.fill_price == expected_price
    assert fill.commission == pytest.approx(expected_commission)
    assert fill.sell_tax == 0 and fill.slippage_cost == pytest.approx(25)
    assert result.equity_curve.loc[dates[30],"cash"] == pytest.approx(100000-expected_gross-expected_commission)
    assert result.equity_curve.loc[dates[30],"equity"] == pytest.approx(100000-expected_gross-expected_commission+250*210)
    for field in ("min_commission","commission_bps","slippage_bps","max_participation","impact_coefficient"):
        assert getattr(result.backtest_config.tw_costs,field) == getattr(research,field)


def test_cash_dividend_precedes_split_and_is_not_reinvested_or_stopped():
    data, spec, research, base, dates = _fixture()
    raw = data.raw_close.copy()
    opening = data.raw_open.copy()
    raw.loc[dates[30]] = 200
    raw.loc[dates[31]:] = 99
    opening.loc[dates[31]:] = 99
    dividends, splits = data.dividends.copy(), data.stock_splits.copy()
    dividends.loc[dates[31],SYMBOL] = 2
    splits.loc[dates[31],SYMBOL] = 2
    adjusted = _total_return(raw,dividends,splits)
    modified = replace(data,raw_close=raw,raw_open=opening,close=adjusted,
                       open=opening*adjusted/raw,dividends=dividends,stock_splits=splits)
    result = run_tradable_benchmark(modified,spec,research,base)
    assert len(result.fills) == 1 and result.fills.side.eq("BUY").all()
    assert result.equity_curve.loc[dates[31],"cash"] == 1000
    assert result.equity_curve.loc[dates[31],"equity"] == 100000
    assert result.episodes.iloc[0].quantity == 1000
    assert result.corporate_actions.query("action == 'cash_dividend'").cash_value.sum() == 1000


def test_gap_or_missing_open_expires_initial_order_and_low_price_still_caps_at_999():
    data, spec, research, base, dates = _fixture()
    for opening, outcome in [(210,"limit_not_met"),(float("nan"),"missing_open")]:
        raw_open = data.raw_open.copy()
        raw_open.loc[dates[30],SYMBOL] = opening
        result = run_tradable_benchmark(replace(data,raw_open=raw_open,open=raw_open),spec,research,base)
        assert result.fills.empty and len(result.orders) == 1
        assert result.orders.iloc[0].outcome == outcome
        assert result.equity_curve.iloc[-1]["cash"] == 100000
    data, spec, research, base, _ = _fixture(price=20)
    result = run_tradable_benchmark(data,spec,research,base)
    assert result.orders.iloc[0].requested_quantity == 999
    assert result.fills.iloc[0].quantity == 999


def test_explicit_etf_rule_cash_and_existing_study_multi_asset_guard_are_preserved(tmp_path):
    data, spec, research, base, _ = _fixture()
    with pytest.raises(ValueError,match="initial cash"):
        run_tradable_benchmark(data,replace(spec,initial_cash=50000),research,base)
    with pytest.raises(ValueError,match="symbol is missing"):
        run_tradable_benchmark(data,replace(spec,symbol="0051.TW"),research,base)
    with pytest.raises(ValueError,match="execution policy"):
        replace(spec,dividend_policy="reinvest")
    with pytest.raises(ValueError,match="execution policy"):
        replace(spec,kind="stock")
    with pytest.raises(ValueError,match="at least two"):
        freeze_odd_lot_study(data,tmp_path,symbols=(SYMBOL,),benchmark="0051.TW",source="synthetic")
    assert asdict(spec)["sell_tax_bps"] == 0


def test_passive_benchmark_does_not_require_a_strategy_volatility_signal():
    data, spec, research, base, _ = _fixture()
    long_window = replace(research,volatility_lookback=1000)
    benchmark = run_tradable_benchmark(data,spec,long_window,base)
    assert benchmark.fills.iloc[0].quantity == 500
    assert benchmark.fills.planned_risk.eq(0).all() and benchmark.signals.stop.eq(0).all()
    legacy = run_odd_lot_research(data,replace(long_window,strategy="equal_weight",max_weight=1,
        instrument_rules={SYMBOL:spec.instrument_rule}),base)
    assert legacy.fills.empty  # Existing default entry behavior is preserved.
    with pytest.raises(ValueError,match="passive benchmark entry"):
        run_odd_lot_research(data,replace(long_window,strategy="momentum"),base,
                             _passive_without_risk_estimate=True)


def test_reverse_split_fractional_receivable_settles_once_without_reinvestment():
    data, spec, research, base, dates = _fixture()
    spec, base = replace(spec,initial_cash=100200), replace(base,initial_cash=100200)
    raw, opening = data.raw_close.copy(), data.raw_open.copy()
    raw.loc[dates[30]] = 200
    raw.loc[dates[31]:] = 396
    opening.loc[dates[31]:] = 396
    dividends, splits = data.dividends.copy(), data.stock_splits.copy()
    dividends.loc[dates[31],SYMBOL] = 2
    splits.loc[dates[31],SYMBOL] = 0.5
    cash_prices = pd.DataFrame(float("nan"),index=dates,columns=[SYMBOL])
    due = pd.DataFrame(pd.NaT,index=dates,columns=[SYMBOL])
    due.loc[dates[31],SYMBOL] = dates[33]
    cash_prices.loc[dates[33],SYMBOL] = 400
    adjusted = _total_return(raw,dividends,splits)
    modified = replace(data,raw_close=raw,raw_open=opening,close=adjusted,open=opening*adjusted/raw,
        dividends=dividends,stock_splits=splits,cash_in_lieu_prices=cash_prices,cash_in_lieu_settlement_dates=due)
    result = run_tradable_benchmark(modified,spec,research,base)
    assert result.fills.iloc[0].quantity == 501 and len(result.orders) == 1
    assert result.equity_curve.loc[dates[31],"cash"] == 1002
    assert result.equity_curve.loc[dates[31],"receivable_value"] == 198
    assert result.equity_curve.loc[dates[31],"equity"] == 100200
    assert result.equity_curve.loc[dates[33],"cash"] == 1202
    assert result.equity_curve.loc[dates[33],"receivable_value"] == 0
    settled = result.corporate_actions.query("action == 'cash_in_lieu_settlement'")
    assert len(settled) == 1 and settled.cash_value.sum() == 200
