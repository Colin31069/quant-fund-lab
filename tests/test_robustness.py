import pandas as pd

from quant_fund_lab.config import BacktestConfig, MarketCostConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.paper import historical_vs_paper_replay
from quant_fund_lab.robustness import (
    block_bootstrap_performance,
    build_robustness_report,
    regime_return_attribution,
    stress_execution_costs,
    summarize_bootstrap_distribution,
)


def test_execution_cost_stress_scales_only_modelled_costs():
    config = BacktestConfig(
        us_costs=MarketCostConfig(
            commission_bps=1.0,
            sell_tax_bps=2.0,
            sec_fee_per_million=20.6,
            slippage_bps=3.0,
            impact_coefficient=0.1,
        )
    )
    stressed = stress_execution_costs(config, 2.0)
    assert stressed.us_costs.commission_bps == 2.0
    assert stressed.us_costs.slippage_bps == 6.0
    assert stressed.us_costs.impact_coefficient == 0.2
    assert stressed.us_costs.sell_tax_bps == 2.0
    assert stressed.us_costs.sec_fee_per_million == 20.6


def test_block_bootstrap_is_deterministic_and_summarized():
    index = pd.bdate_range("2025-01-02", periods=100)
    equity = pd.Series((1.0 + pd.Series([0.001, -0.0005] * 50)).cumprod().to_numpy(), index=index)
    first = block_bootstrap_performance(equity, iterations=30, block_length=5, seed=9)
    second = block_bootstrap_performance(equity, iterations=30, block_length=5, seed=9)
    pd.testing.assert_frame_equal(first, second)
    summary = summarize_bootstrap_distribution(first)
    assert (summary["p05"] <= summary["median"]).all()
    assert (summary["median"] <= summary["p95"]).all()


def test_regime_attribution_and_robustness_report():
    data = synthetic_market_data(symbols=("A", "B", "C", "D"), periods=280, seed=92)
    config = BacktestConfig(
        initial_cash=500_000,
        strategy=StrategyConfig(warmup_days=80, rebalance_every=10, max_weight=0.4),
    )
    comparison = historical_vs_paper_replay(data, config, train_fraction=0.70)
    attribution = regime_return_attribution(comparison.paper_replay)
    assert not attribution.empty
    assert attribution["days"].sum() <= len(comparison.paper_replay.equity_curve) - 1

    report = build_robustness_report(
        data,
        config,
        0.70,
        comparison.paper_replay,
        cost_multipliers=(1.0, 1.5),
        bootstrap_iterations=20,
        block_length=5,
        seed=3,
    )
    assert list(report.cost_stress.index) == [1.0, 1.5]
    assert len(report.bootstrap_distribution) == 20
    assert not report.bootstrap_summary.empty
    assert not report.regime_attribution.empty
