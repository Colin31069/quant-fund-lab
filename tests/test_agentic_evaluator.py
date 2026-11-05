"""Unit tests for deterministic evaluator, drawdown extraction, and vectorized bootstrap."""

from __future__ import annotations

import time

import numpy as np
import pytest

from quant_fund_lab.agentic.evaluator import (
    build_compact_diagnostics,
    compute_composite_fitness_score,
    compute_stationary_bootstrap_sharpes,
    extract_top_drawdown_episodes,
    synthesize_drawdown_driver,
)
from quant_fund_lab.agentic.schemas import (
    CompactBacktestDiagnostics,
    CorePerformance,
    DrawdownEpisode,
    ExecutionFrictionDecomposition,
    GlobalDsrContext,
    RegimeConditionedSharpe,
)


def test_extract_top_drawdown_episodes_recovered() -> None:
    # Construct synthetic series: rise, drop 10%, recover, rise, drop 15%, recover
    r = np.array([
        0.05, 0.05, -0.05, -0.06, 0.08, 0.05, 0.05, -0.08, -0.08, 0.10, 0.10, 0.02
    ])
    episodes = extract_top_drawdown_episodes(r, max_episodes=2, min_depth_pct=2.0, min_duration_days=1)
    assert len(episodes) >= 1
    ep1 = episodes[0]
    assert ep1.depth_pct < -5.0
    assert ep1.recovery_idx is not None
    assert ep1.recovery_days is not None
    assert ep1.recovery_days > 0


def test_extract_top_drawdown_episodes_unrecovered_tail() -> None:
    # Ends in an unrecovered trough
    r = np.array([
        0.02, 0.02, 0.02, -0.04, -0.04, -0.04, -0.02
    ])
    episodes = extract_top_drawdown_episodes(r, max_episodes=2, min_depth_pct=2.0, min_duration_days=1)
    assert len(episodes) >= 1
    unrecovered = [ep for ep in episodes if ep.recovery_idx is None]
    assert len(unrecovered) >= 1
    assert unrecovered[0].recovery_days is None


def test_extract_top_drawdown_episodes_ignores_shallow() -> None:
    # 0.5% fluctuation only
    r = np.array([0.001, -0.005, 0.002, -0.003, 0.004])
    episodes = extract_top_drawdown_episodes(r, max_episodes=3, min_depth_pct=2.0, min_duration_days=1)
    assert len(episodes) == 0


def test_synthesize_drawdown_driver() -> None:
    # Case 1: severe friction in whipsaw regime with wide tick spreads
    driver1 = synthesize_drawdown_driver(
        friction_share=0.40,
        mkt_vol_pct=0.85,
        mkt_autocorr=-0.15,
        effective_tick_bps=30.0,
    )
    assert "Severe turnover friction bleed" in driver1
    assert "high-volatility whipsaw regime" in driver1
    assert "wide discrete tick spreads" in driver1

    # Case 2: unhedged directional drawdown in bear regime leaving unrecovered crash
    driver2 = synthesize_drawdown_driver(
        beta_corr=0.35,
        mkt_return=-0.12,
        mkt_vol_pct=0.90,
        mkt_autocorr=0.10,
        is_unrecovered=True,
    )
    assert "Unhedged positive market-beta" in driver2
    assert "sustained high-volatility directional bear regime" in driver2
    assert "unrecovered structural drawdown" in driver2


def test_compute_stationary_bootstrap_sharpes_performance() -> None:
    rng = np.random.default_rng(123)
    # 1638 bars (~6.5 years daily returns)
    returns = rng.normal(0.0005, 0.012, size=1638)

    t0 = time.perf_counter()
    p05, p25, p50 = compute_stationary_bootstrap_sharpes(
        returns, n_boot=2000, avg_block_len=20, annualization_factor=252.0, seed=42
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Performance constraint: sub-200ms
    assert elapsed_ms < 200.0
    # Monotonicity of quantiles
    assert p05 <= p25 <= p50
    # Plausible Sharpe range
    assert -2.0 <= p05 <= 4.0


def test_compute_composite_fitness_score() -> None:
    # High DSR, low cost degradation
    j1 = compute_composite_fitness_score(
        net_sharpe=1.5,
        boot_p25=1.3,
        base_sharpe=1.5,
        stress_sharpe=1.45,
        dsr=0.96,
        lambda_cost=1.50,
    )
    # Conservative Sharpe is min(1.5, 1.3) = 1.3 -> 0.96 * 1.3 - 1.5 * 0.05 = 1.248 - 0.075 = 1.173
    assert j1 == pytest.approx(1.173, rel=1e-3)

    # Severe cost degradation
    j2 = compute_composite_fitness_score(
        net_sharpe=1.5,
        boot_p25=1.3,
        base_sharpe=1.5,
        stress_sharpe=0.8,
        dsr=0.96,
        lambda_cost=1.50,
    )
    # Cost drag = 1.5 - 0.8 = 0.7 -> 0.96 * 1.3 - 1.5 * 0.7 = 1.248 - 1.05 = 0.198
    assert j2 < j1


def test_build_compact_diagnostics() -> None:
    diag = build_compact_diagnostics(
        iteration=1,
        global_dsr=GlobalDsrContext(
            universe_total_trials_N=10,
            expected_null_max_sharpe_SR0=1.1,
            strategy_deflated_sharpe_DSR=0.92,
            status="ACTIVE",
        ),
        core_perf=CorePerformance(
            net_sharpe=1.4,
            gross_sharpe=1.8,
            bootstrap_sharpe_p05=0.6,
            bootstrap_sharpe_p50=1.35,
            max_drawdown_pct=-15.2,
            calmar_ratio=1.1,
            annualized_turnover_one_way=6.5,
        ),
        regime_sharpes=RegimeConditionedSharpe(
            volatility_terciles={"low": 1.6, "mid": 1.4, "high": 0.2},
            dispersion_terciles={"low": 0.5, "mid": 1.2, "high": 1.7},
            market_trend_state={"bull": 1.8, "chop": 1.3, "bear": -0.2},
        ),
        drawdown_episodes=[
            DrawdownEpisode(
                id="DD_1",
                depth_pct=-15.2,
                duration_days=45,
                recovery_days=30,
                regime_state="vol_pct=88",
                driver="Severe turnover friction bleed",
            )
        ],
        friction_decomp=ExecutionFrictionDecomposition(
            gross_alpha_bps=2200,
            commission_and_tax_drag_bps=-450,
            slippage_and_tick_quantization_bps=-250,
            net_alpha_bps=1500,
            stress_1_5x_cost_net_sharpe=0.95,
        ),
    )
    assert isinstance(diag, CompactBacktestDiagnostics)
    payload = diag.model_dump_json()
    assert "DD_1" in payload
    assert "volatility_terciles" in payload
