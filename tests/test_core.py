import numpy as np
import pandas as pd
import pytest

from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
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
