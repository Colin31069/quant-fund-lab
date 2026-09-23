from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.data_quality import validate_corporate_actions
from quant_fund_lab.execution import PortfolioState, apply_terminal_returns, rebalance_at_open
from quant_fund_lab.fx import attach_fx_rates, validate_fx
from quant_fund_lab.market_calendar import require_valid_daily_sessions, validate_daily_sessions
from quant_fund_lab.models import ensemble_alpha
from quant_fund_lab.portfolio import optimize_weights
from quant_fund_lab.snapshot import load_market_data_snapshot, save_market_data_snapshot


def test_ensemble_alpha_is_finite():
    data = synthetic_market_data(periods=220)
    alpha = ensemble_alpha(data.close, StrategyConfig())
    assert list(alpha.columns) == ["kalman", "ou", "residual_momentum", "ensemble"]
    assert np.isfinite(alpha.to_numpy()).all()


def test_optimizer_respects_long_only_caps():
    data = synthetic_market_data(periods=220)
    cfg = StrategyConfig(max_weight=0.30)
    alpha = ensemble_alpha(data.close, cfg)["ensemble"]
    returns = data.close.pct_change(fill_method=None).tail(cfg.covariance_lookback)
    weights = optimize_weights(alpha, returns, None, cfg)
    assert (weights >= -1e-9).all()
    assert (weights <= 0.300001).all()
    assert float(weights.sum()) <= 1.000001


def test_fx_direction_and_mixed_currency_backtest():
    data = synthetic_market_data(symbols=("AAPL", "2330.TW"), periods=220)
    usd_twd = pd.Series(32.0, index=data.close.index, dtype=float)
    usd_data = attach_fx_rates(data, "USD", usd_twd=usd_twd)
    assert (usd_data.fx_to_base["AAPL"] == 1.0).all()
    assert np.allclose(usd_data.fx_to_base["2330.TW"], 1.0 / 32.0)

    twd_data = attach_fx_rates(data, "TWD", usd_twd=usd_twd)
    assert (twd_data.fx_to_base["AAPL"] == 32.0).all()
    assert (twd_data.fx_to_base["2330.TW"] == 1.0).all()

    cfg = BacktestConfig(
        initial_cash=1_000_000,
        base_currency="USD",
        strategy=StrategyConfig(warmup_days=80, rebalance_every=5, max_weight=0.5),
    )
    result = run_backtest(usd_data, cfg)
    assert result.base_currency == "USD"
    assert not result.fills.empty
    assert result.equity_curve["equity"].gt(0).all()


def test_fx_uses_point_in_time_currency_metadata_for_same_stable_asset():
    dates = pd.bdate_range("2026-01-02", periods=4)
    symbol = "ASSET@@stable-id"
    close = pd.DataFrame({symbol: [100.0, 101.0, 3_232.0, 3_264.0]}, index=dates)
    data = MarketData(
        open=close,
        close=close,
        volume=pd.DataFrame(10_000.0, index=dates, columns=[symbol]),
        membership=pd.DataFrame(True, index=dates, columns=[symbol]),
        market_codes=pd.DataFrame(["US", "US", "TW", "TW"], index=dates, columns=[symbol]),
        currency_codes=pd.DataFrame(["USD", "USD", "TWD", "TWD"], index=dates, columns=[symbol]),
    )
    usd_twd = pd.Series(32.0, index=dates, dtype=float)
    converted = attach_fx_rates(data, "USD", usd_twd=usd_twd)

    assert converted.fx_to_base.loc[dates[0], symbol] == pytest.approx(1.0)
    assert converted.fx_to_base.loc[dates[1], symbol] == pytest.approx(1.0)
    assert converted.fx_to_base.loc[dates[2], symbol] == pytest.approx(1.0 / 32.0)
    assert converted.fx_to_base.loc[dates[3], symbol] == pytest.approx(1.0 / 32.0)
    assert validate_fx(converted).is_valid


def test_backtest_execution_uses_point_in_time_market_and_currency_metadata():
    symbols = ("ASSET@@tw-a", "ASSET@@tw-b")
    data = synthetic_market_data(symbols=symbols, periods=220, seed=93)
    data = replace(
        data,
        market_codes=pd.DataFrame("TW", index=data.close.index, columns=data.symbols),
        currency_codes=pd.DataFrame("TWD", index=data.close.index, columns=data.symbols),
        exchange=None,
    )
    usd_twd = pd.Series(32.0, index=data.close.index, dtype=float)
    converted = attach_fx_rates(data, "USD", usd_twd=usd_twd)
    cfg = BacktestConfig(
        initial_cash=1_000_000.0,
        base_currency="USD",
        strategy=StrategyConfig(warmup_days=80, rebalance_every=5, max_weight=0.5),
    )
    result = run_backtest(converted, cfg)

    assert not result.fills.empty
    assert set(result.fills["local_currency"]) == {"TWD"}
    assert (result.fills["quantity"] % 1_000 == 0).all()


def test_fx_alignment_never_backfills_and_rejects_stale_rates():
    data = synthetic_market_data(symbols=("AAPL", "2330.TW"), periods=30)
    late = pd.Series(32.0, index=data.close.index[2:], dtype=float)
    with pytest.raises(ValueError, match="no prior observation"):
        attach_fx_rates(data, "USD", usd_twd=late)

    stale = pd.Series([32.0], index=[data.close.index[0]], dtype=float)
    with pytest.raises(ValueError, match="stale"):
        attach_fx_rates(data, "USD", usd_twd=stale, max_staleness_days=5)


def test_backtest_rejects_mixed_currency_without_fx():
    data = synthetic_market_data(symbols=("AAPL", "2330.TW"), periods=220)
    cfg = BacktestConfig(base_currency="USD", strategy=StrategyConfig(warmup_days=80))
    with pytest.raises(ValueError, match="mixed-currency"):
        run_backtest(data, cfg)


def test_backtest_produces_equity_and_trades():
    data = synthetic_market_data(periods=300)
    cfg = BacktestConfig(
        initial_cash=500_000,
        strategy=StrategyConfig(warmup_days=100, rebalance_every=5, max_weight=0.30),
    )
    result = run_backtest(data, cfg)
    assert len(result.equity_curve) > 100
    assert result.equity_curve["equity"].gt(0).all()
    assert result.equity_curve["cash"].ge(-1e-6).all()
    assert not result.weights.empty
    assert isinstance(result.fills, pd.DataFrame)
    assert set(result.cost_attribution.columns) == {
        "gross_turnover",
        "fees",
        "slippage_cost",
        "total_cost",
        "turnover_rate",
    }


def test_backtest_factor_overlay_records_learned_weights():
    data = synthetic_market_data(
        symbols=("A", "B", "C", "D", "E", "F", "G", "H"), periods=340, seed=62
    )
    cfg = BacktestConfig(
        initial_cash=500_000,
        strategy=StrategyConfig(
            warmup_days=160,
            rebalance_every=20,
            max_weight=0.25,
            factor_alpha_enabled=True,
            factor_alpha_weight=0.30,
            factor_ic_lookback=20,
            factor_ic_min_observations=4,
        ),
    )
    result = run_backtest(data, cfg)
    assert not result.factor_weights.empty
    assert np.isfinite(result.factor_weights.fillna(0.0).to_numpy()).all()
    assert (result.factor_weights.fillna(0.0).abs().sum(axis=1) <= 1.000001).all()
    assert result.equity_curve["equity"].gt(0.0).all()


def test_zero_volume_bar_cannot_fill():
    cfg = BacktestConfig(strategy=StrategyConfig(warmup_days=20))
    state = PortfolioState(cash=1_000_000)
    fills = rebalance_at_open(
        state=state,
        target_weights=pd.Series({"AAPL": 1.0}),
        open_prices=pd.Series({"AAPL": 100.0}),
        volumes=pd.Series({"AAPL": 0.0}),
        reference_prices=pd.Series({"AAPL": 99.0}),
        timestamp=pd.Timestamp("2026-01-02"),
        config=cfg,
    )
    assert fills == []
    assert state.cash == 1_000_000


def test_execution_converts_local_trade_cashflow_to_base_currency():
    cfg = BacktestConfig(base_currency="USD", strategy=StrategyConfig(warmup_days=20))
    state = PortfolioState(cash=10_000.0)
    fills = rebalance_at_open(
        state=state,
        target_weights=pd.Series({"2330.TW": 0.5}),
        open_prices=pd.Series({"2330.TW": 100.0}),
        volumes=pd.Series({"2330.TW": 1_000_000.0}),
        reference_prices=pd.Series({"2330.TW": 99.0}),
        timestamp=pd.Timestamp("2026-01-05"),
        config=cfg,
        fx_to_base=pd.Series({"2330.TW": 1.0 / 32.0}),
    )
    assert fills
    fill = fills[0]
    assert fill.local_currency == "TWD"
    assert fill.fx_to_base == pytest.approx(1.0 / 32.0)
    assert fill.gross_value == pytest.approx(fill.gross_value_local / 32.0)
    assert state.cash < 10_000.0


def test_tw_round_lot_and_locked_limit_guard():
    cfg = BacktestConfig(strategy=StrategyConfig(warmup_days=20))
    state = PortfolioState(cash=10_000_000)
    target = pd.Series({"2330.TW": 0.5})
    locked = rebalance_at_open(
        state=state,
        target_weights=target,
        open_prices=pd.Series({"2330.TW": 110.0}),
        volumes=pd.Series({"2330.TW": 1_000_000.0}),
        reference_prices=pd.Series({"2330.TW": 100.0}),
        timestamp=pd.Timestamp("2026-01-02"),
        config=cfg,
    )
    assert locked == []

    fills = rebalance_at_open(
        state=state,
        target_weights=target,
        open_prices=pd.Series({"2330.TW": 105.0}),
        volumes=pd.Series({"2330.TW": 1_000_000.0}),
        reference_prices=pd.Series({"2330.TW": 100.0}),
        timestamp=pd.Timestamp("2026-01-05"),
        config=cfg,
    )
    assert fills
    assert fills[0].quantity % 1_000 == 0


def test_calendar_missing_session_is_reported_but_not_fatal():
    observed = pd.DatetimeIndex(["2025-01-08", "2025-01-10"])
    report = require_valid_daily_sessions(observed, "US")
    assert pd.Timestamp("2025-01-09") in report.missing_sessions


def test_calendar_rejects_off_session_bar():
    observed = pd.DatetimeIndex(["2026-01-02", "2026-01-03"])
    report = validate_daily_sessions(observed, "US")
    assert pd.Timestamp("2026-01-03") in report.off_calendar_sessions
    with pytest.raises(ValueError, match="weekend"):
        require_valid_daily_sessions(observed, "US")


def test_point_in_time_membership_forces_ineligible_weight_to_zero():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC"), periods=220)
    cfg = StrategyConfig(max_weight=0.5)
    alpha = pd.Series({"AAA": 4.0, "BBB": 3.0, "CCC": 2.0})
    returns = data.close.pct_change(fill_method=None).tail(cfg.covariance_lookback)
    eligible = pd.Series({"AAA": False, "BBB": True, "CCC": True})
    weights = optimize_weights(alpha, returns, None, cfg, eligible=eligible)
    assert weights["AAA"] == pytest.approx(0.0)


def test_terminal_return_event_applies_explicit_delisting_loss():
    state = PortfolioState(cash=10_000.0, shares={"AAA": 100})
    events = apply_terminal_returns(
        state=state,
        terminal_returns=pd.Series({"AAA": -1.0}),
        reference_prices=pd.Series({"AAA": 50.0}),
        timestamp=pd.Timestamp("2026-01-05"),
    )
    assert len(events) == 1
    assert events[0].proceeds == 0.0
    assert state.shares["AAA"] == 0
    assert state.cash == 10_000.0


def test_terminal_return_cash_outs_holding():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=180)
    membership = data.membership.copy()
    terminal = data.terminal_returns.copy()
    exit_signal = data.close.index[120]
    exit_date = data.close.index[121]
    membership.loc[exit_signal:, "AAA"] = False
    terminal.loc[exit_date, "AAA"] = -1.0
    custom = MarketData(
        open=data.open,
        close=data.close,
        volume=data.volume,
        reference=data.reference,
        membership=membership,
        terminal_returns=terminal,
    )
    cfg = BacktestConfig(
        initial_cash=1_000_000,
        strategy=StrategyConfig(warmup_days=80, rebalance_every=1, max_weight=0.8),
    )
    result = run_backtest(custom, cfg)
    assert isinstance(result.terminal_events, pd.DataFrame)
    later_weights = result.weights.loc[result.weights.index >= exit_signal]
    assert (later_weights["AAA"].abs() < 1e-12).all()


def test_corporate_action_validation_flags_bad_metadata():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=80)
    dividends = data.dividends.copy()
    dividends.iloc[20, 0] = -1.0
    bad = MarketData(
        open=data.open,
        close=data.close,
        volume=data.volume,
        reference=data.reference,
        membership=data.membership,
        dividends=dividends,
        stock_splits=data.stock_splits,
    )
    report = validate_corporate_actions(bad)
    assert not report.is_valid
    assert report.negative_dividend_events


def test_snapshot_preserves_fx_metadata(tmp_path):
    data = synthetic_market_data(symbols=("AAPL", "2330.TW"), periods=80)
    usd_twd = pd.Series(32.0, index=data.close.index, dtype=float)
    converted = attach_fx_rates(data, "USD", usd_twd=usd_twd)
    root = tmp_path / "fx-snapshot"
    manifest = save_market_data_snapshot(converted, root)
    loaded = load_market_data_snapshot(root)
    assert manifest.base_currency == "USD"
    assert loaded.base_currency == "USD"
    pd.testing.assert_frame_equal(loaded.fx_to_base, converted.fx_to_base, check_freq=False)
    assert validate_fx(loaded).is_valid


def test_snapshot_round_trip_and_integrity(tmp_path):
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=80)
    root = tmp_path / "snapshot"
    manifest = save_market_data_snapshot(data, root)
    loaded = load_market_data_snapshot(root)
    assert manifest.dataset_id
    assert manifest.base_currency is None
    pd.testing.assert_frame_equal(loaded.close, data.close, check_freq=False)
    pd.testing.assert_frame_equal(loaded.membership, data.membership, check_freq=False)

    close_path = root / "close.parquet"
    close_path.write_bytes(close_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="integrity"):
        load_market_data_snapshot(root)
