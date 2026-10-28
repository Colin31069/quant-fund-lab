import json
import sqlite3
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.execution import PortfolioState, execute_market_order, prior_session_liquidity
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_account_settings,
    verify_odd_lot_study_report,
)
from quant_fund_lab.trade_analytics import position_episodes, summarize_episodes


def test_open_liquidity_does_not_use_the_execution_day_or_future():
    volume = pd.DataFrame({"A": [100.0, 200.0, 10_000.0, 50.0]})
    proxy = prior_session_liquidity(volume, lookback=2)
    assert list(proxy["A"]) == [0.0, 100.0, 150.0, 5100.0]
    changed = volume.copy()
    changed.loc[2:, "A"] = 999_999.0
    pd.testing.assert_series_equal(proxy.loc[:2, "A"], prior_session_liquidity(changed, 2).loc[:2, "A"])


def test_odd_lot_minimum_fee_is_affordable_and_order_is_capped():
    config = BacktestConfig(tw_costs=MarketCostConfig(
        commission_bps=14.25, min_commission=20.0, lot_size=1,
        max_order_shares=999, slippage_bps=0.0, impact_coefficient=0.0,
        max_participation=1.0,
    ))
    state = PortfolioState(cash=1_000.0)
    fill = execute_market_order(state, "2330.TW", "BUY", 999, 10, 100_000, 10,
                                pd.Timestamp("2025-01-02"), config)
    assert fill.quantity == 98
    assert fill.fees == 20
    assert state.cash == pytest.approx(0.0)
    state = PortfolioState(cash=1_000_000.0)
    fill = execute_market_order(state, "2330.TW", "BUY", 2_000, 10, 100_000, 10,
                                pd.Timestamp("2025-01-02"), config)
    assert fill.quantity == 999


def test_position_episode_accounts_for_partial_trades_dividend_and_split():
    fills = pd.DataFrame([
        {"timestamp": "2024-01-02", "symbol": "2330.TW", "side": "BUY", "quantity": 10,
         "gross_value": 1000, "fees": 20, "planned_risk": 200},
        {"timestamp": "2024-01-05", "symbol": "2330.TW", "side": "SELL", "quantity": 8,
         "gross_value": 480, "fees": 20},
        {"timestamp": "2024-01-08", "symbol": "2330.TW", "side": "SELL", "quantity": 12,
         "gross_value": 720, "fees": 20},
    ])
    actions = pd.DataFrame([
        {"timestamp": "2024-01-03", "symbol": "2330.TW", "action": "cash_dividend", "cash_value": 50},
        {"timestamp": "2024-01-04", "symbol": "2330.TW", "action": "stock_split", "cash_value": 0,
         "quantity_before": 10, "quantity_after": 20, "cash_in_lieu_price_source": ""},
    ])
    result = position_episodes(fills, actions, pd.DataFrame(), pd.Series({"2330.TW": 60}))
    assert len(result) == 1
    assert result.iloc[0]["pnl"] == pytest.approx(190.0)
    assert result.iloc[0]["risk_multiple"] == pytest.approx(0.95)
    assert result.iloc[0]["status"] == "closed"
    summary = summarize_episodes(result)
    assert summary["payoff_ratio"] is None
    assert summary["profit_factor"] is None


def test_payoff_win_rate_expectancy_and_open_pnl_are_distinct():
    episodes = pd.DataFrame({"status": ["closed"] * 10 + ["open"],
                             "pnl": [1000.0] * 3 + [-500.0] * 7 + [-900.0]})
    summary = summarize_episodes(episodes)
    assert summary["payoff_ratio"] == 2
    assert summary["win_rate"] == pytest.approx(0.3)
    assert summary["expectancy"] == pytest.approx(-50.0)
    assert summary["open_pnl"] == -900
    assert not summary["sample_sufficient"]


def test_delayed_fractional_settlement_stays_with_its_original_episode():
    fills = pd.DataFrame([
        {"timestamp": "2024-01-02", "symbol": "2330.TW", "side": "BUY", "quantity": 10,
         "gross_value": 1000, "fees": 20, "planned_risk": 200},
        {"timestamp": "2024-01-04", "symbol": "2330.TW", "side": "BUY", "quantity": 2,
         "gross_value": 180, "fees": 20, "planned_risk": 50},
    ])
    actions = pd.DataFrame([
        {"timestamp": "2024-01-03", "symbol": "2330.TW", "action": "stock_split", "cash_value": 0,
         "quantity_before": 10, "quantity_after": 0, "cash_in_lieu_price_source": "pending_settlement",
         "cash_in_lieu_settlement_date": "2024-01-05", "fractional_quantity": 0.5},
        {"timestamp": "2024-01-05", "symbol": "2330.TW", "action": "cash_in_lieu_settlement",
         "cash_value": 1_100, "fractional_quantity": 0.5},
    ])
    episodes = position_episodes(fills, actions, pd.DataFrame(), pd.Series({"2330.TW": 100}))
    assert list(episodes.status) == ["closed", "open"]
    assert list(episodes.pnl) == pytest.approx([80, 0])


def test_stop_levels_adjust_for_split_instead_of_triggering_a_false_exit():
    dates = pd.bdate_range("2024-01-02", periods=60)
    adjusted = pd.DataFrame({"2330.TW": np.linspace(80, 120, 60),
                             "2317.TW": np.linspace(60, 90, 60)}, index=dates)
    raw = adjusted.copy()
    raw.loc[dates[40]:, "2330.TW"] /= 2
    splits = adjusted * 0.0
    splits.loc[dates[40], "2330.TW"] = 2.0
    data = MarketData(open=adjusted, close=adjusted, raw_open=raw, raw_close=raw,
                      stock_splits=splits, volume=adjusted * 100_000)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=5)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, research, base)
    assert not result.corporate_actions.empty
    assert result.corporate_actions.action.eq("stock_split").any()
    false_stop = result.signals[(result.signals.timestamp == dates[40]) &
                                (result.signals.symbol == "2330.TW") &
                                (result.signals.reason == "stop")]
    assert false_stop.empty
    assert result.equity_curve.equity.iloc[-1] - base.initial_cash == pytest.approx(result.episodes.pnl.sum())


def test_split_adjusted_raw_prices_are_rejected_before_double_counting():
    data = synthetic_market_data(("2330.TW", "2317.TW"), periods=80, seed=4)
    splits = data.stock_splits.copy()
    splits.loc[data.close.index[50], "2330.TW"] = 2.0
    data = replace(data, stock_splits=splits)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    with pytest.raises(ValueError, match="raw prices appear split-adjusted"):
        run_odd_lot_research(data, base_config=base)


def test_terminal_day_cancels_an_unfilled_entry_even_without_a_position():
    dates = pd.bdate_range("2024-01-02", periods=40)
    close = pd.DataFrame({"2330.TW": np.linspace(80, 120, 40),
                          "2317.TW": np.linspace(60, 90, 40)}, index=dates)
    terminal = close * np.nan
    terminal.loc[dates[30], "2330.TW"] = -1.0
    data = MarketData(open=close, close=close, volume=close * 100_000,
                      terminal_returns=terminal)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=5)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, research, base)
    assert not ((result.fills.timestamp == dates[30]) & result.fills.symbol.eq("2330.TW")).any()


def test_daily_stop_retries_after_missing_open_and_never_buys_more_while_exiting():
    dates = pd.bdate_range("2024-01-02", periods=65)
    prices = np.r_[np.linspace(90, 110, 40), [95, 94, 93], np.linspace(93, 100, 22)]
    close = pd.DataFrame({"2330.TW": prices, "2317.TW": prices * 0.8}, index=dates)
    opening = close.copy()
    opening.loc[dates[41], "2330.TW"] = np.nan
    opening.loc[dates[41], "2317.TW"] = np.nan
    data = MarketData(open=opening, close=close, raw_open=opening, raw_close=close,
                      volume=close * 10_000)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=5, rebalance_every=5)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    result = run_odd_lot_research(data, research, base)
    stops = result.signals[result.signals.reason == "stop"]
    assert not stops.empty
    for row in stops.itertuples():
        later = result.fills[(result.fills.symbol == row.symbol) & (result.fills.timestamp > row.timestamp)]
        assert not later.empty
        assert later.iloc[0]["side"] == "SELL"
        assert later.iloc[0]["timestamp"] > row.timestamp
    assert all(result.fills.quantity <= 999)
    assert all(result.fills.loc[result.fills.side == "BUY", "planned_risk"] <= 2000.0 + 1e-8)


def test_future_data_cannot_change_past_research_signals_and_fills():
    data = synthetic_market_data(("2330.TW", "2317.TW", "2454.TW"), periods=180, seed=12)
    research = OddLotResearchConfig(strategy="momentum", momentum_lookback=20)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=40))
    first = run_odd_lot_research(data, research, base)
    cutoff = data.close.index[140]
    close = data.close.copy()
    close.loc[close.index > cutoff] *= 1.7
    volume = data.volume.copy()
    volume.loc[volume.index > cutoff] *= 3
    revised = replace(data, close=close, raw_close=close, volume=volume)
    second = run_odd_lot_research(revised, research, base)
    for left, right in ((first.signals, second.signals), (first.fills, second.fills)):
        pd.testing.assert_frame_equal(
            left[left.timestamp <= cutoff].reset_index(drop=True),
            right[right.timestamp <= cutoff].reset_index(drop=True),
        )


def test_frozen_study_export_and_account_assumptions_are_locked(tmp_path):
    symbols = ("2330.TW", "2317.TW")
    data = synthetic_market_data((*symbols, "0050.TW"), periods=80, seed=4)
    base = BacktestConfig(initial_cash=100_000, base_currency="TWD",
                          strategy=StrategyConfig(warmup_days=30))
    config = OddLotResearchConfig(momentum_lookback=5, volatility_lookback=10)
    root = freeze_odd_lot_study(data, tmp_path, symbols=symbols, research=config,
                                base_config=base, source="synthetic")
    assert freeze_odd_lot_study(data, tmp_path, symbols=symbols, research=config,
                                base_config=base, source="synthetic") == root
    loaded, manifest = load_frozen_odd_lot_study(root)
    assert loaded.symbols == [*symbols, "0050.TW"]
    assert manifest["holdout_untouched"] is False
    study = run_frozen_odd_lot_study(root)
    assert ("validation", "momentum") in study.results
    assert "development/momentum" in study.unavailable
    report = export_odd_lot_study_report(root, study)
    assert verify_odd_lot_study_report(report)
    ledger = report / "study_ledger.sqlite"
    result = study.results[("validation", "momentum")]
    assert verify_odd_lot_account_settings(ledger, "validation/momentum", result)
    different = replace(result, config=replace(result.config, risk_budget=500.0))
    assert not verify_odd_lot_account_settings(ledger, "validation/momentum", different)
    with sqlite3.connect(ledger) as db, pytest.raises(sqlite3.IntegrityError, match="settings are locked"):
        db.execute("UPDATE accounts SET settings_json='{}'")
    (report / "comparison.csv").write_text("tampered", encoding="utf-8")
    assert not verify_odd_lot_study_report(report)
    settings_path = root / "study.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["research_config"]["risk_budget"] = 1.0
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(ValueError, match="configuration integrity"):
        load_frozen_odd_lot_study(root)
