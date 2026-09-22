import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.execution import PortfolioState, rebalance_at_open
from quant_fund_lab.market_calendar import require_valid_daily_sessions, validate_daily_sessions
from quant_fund_lab.models import ensemble_alpha
from quant_fund_lab.portfolio import optimize_weights


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


def test_backtest_rejects_mixed_currency_markets():
    data = synthetic_market_data(symbols=("AAPL", "2330.TW"), periods=220)
    cfg = BacktestConfig(strategy=StrategyConfig(warmup_days=80))
    with pytest.raises(ValueError, match="FX conversion"):
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
