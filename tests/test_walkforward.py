import pandas as pd

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.walkforward import (
    WalkForwardSpec,
    generate_candidate_grid,
    run_walk_forward,
    strategy_candidate_id,
)


def _small_setup():
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC"), periods=430, seed=11)
    strategy = StrategyConfig(warmup_days=60, max_weight=0.4, rebalance_every=5)
    config = BacktestConfig(initial_cash=500_000, strategy=strategy)
    candidates = generate_candidate_grid(
        strategy,
        risk_aversion=(2.0, 6.0),
        covariance_shrinkage=(0.35,),
        rebalance_every=(5,),
    )
    spec = WalkForwardSpec(
        train_bars=120,
        validation_bars=60,
        test_bars=60,
        step_bars=60,
        expanding=True,
        objective="calmar",
        max_validation_drawdown=None,
    )
    return data, config, candidates, spec


def test_walk_forward_fold_chronology_and_no_overlap():
    data, config, candidates, spec = _small_setup()
    result = run_walk_forward(data, config, candidates, spec)
    assert len(result.folds) >= 2
    for _, fold in result.folds.iterrows():
        assert fold["train_start"] <= fold["train_end"]
        assert fold["train_end"] < fold["validation_start"]
        assert fold["validation_start"] <= fold["validation_end"]
        assert fold["validation_end"] < fold["test_start"]
        assert fold["test_start"] <= fold["test_end"]
    assert not result.oos_equity.index.has_duplicates
    assert result.oos_equity.index.is_monotonic_increasing
    assert result.candidate_validation_returns.shape == (
        len(result.folds) * spec.validation_bars,
        len(candidates),
    )
    assert not result.candidate_validation_returns.isna().any().any()
    assert result.candidate_validation_returns.index.names == ["fold", "timestamp"]


def test_walk_forward_selection_is_deterministic():
    data, config, candidates, spec = _small_setup()
    first = run_walk_forward(data, config, candidates, spec)
    second = run_walk_forward(data, config, candidates, spec)
    pd.testing.assert_series_equal(
        first.folds["selected_candidate_id"], second.folds["selected_candidate_id"]
    )
    assert [strategy_candidate_id(candidate) for candidate in candidates] == [
        strategy_candidate_id(candidate) for candidate in candidates
    ]


def test_walk_forward_chains_only_oos_returns():
    data, config, candidates, spec = _small_setup()
    result = run_walk_forward(data, config, candidates, spec)
    expected_test_days = len(result.folds) * spec.test_bars
    assert len(result.oos_equity) == expected_test_days + 1
    assert result.oos_equity.iloc[0] == config.initial_cash
    assert result.oos_equity.gt(0).all()
    assert set(result.oos_metrics) >= {"total_return", "sharpe", "max_drawdown", "calmar"}
