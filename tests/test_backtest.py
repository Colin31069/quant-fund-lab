from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_fund_lab.agentic.schemas import (
    CompactBacktestDiagnostics,
    CorePerformance,
    DrawdownEpisode,
    ExecutionFrictionDecomposition,
    ExecutionOverlayConfig,
    GlobalDsrContext,
    PrimitiveConfig,
    RegimeConditionedSharpe,
    SkepticAuditVerdict,
    SkepticViolationCode,
    StrategyContract,
)
from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data


def test_backtest_config_custom_alpha_evaluator_default():
    config = BacktestConfig()
    assert config.custom_alpha_evaluator is None

    def dummy_alpha(data, signal_date):
        return pd.Series(0.1, index=data.symbols)

    custom_config = BacktestConfig(custom_alpha_evaluator=dummy_alpha)
    assert custom_config.custom_alpha_evaluator is dummy_alpha


def test_backtest_run_with_custom_alpha_evaluator_series():
    data = synthetic_market_data(periods=160)
    called_dates: list[pd.Timestamp] = []

    def custom_evaluator(mkt_data, signal_date):
        called_dates.append(pd.Timestamp(signal_date))
        # Equal weight signal
        weights = {sym: 1.0 / len(mkt_data.symbols) for sym in mkt_data.symbols}
        return pd.Series(weights)

    cfg = BacktestConfig(
        strategy=StrategyConfig(warmup_days=60, rebalance_every=5),
        custom_alpha_evaluator=custom_evaluator,
    )
    result = run_backtest(data, cfg)

    assert len(called_dates) > 0
    assert not result.equity_curve.empty
    assert not result.regimes.empty
    assert (result.regimes["label"] == "custom").all()


def test_backtest_run_with_custom_alpha_evaluator_non_series():
    data = synthetic_market_data(periods=160)

    def dict_evaluator(mkt_data, _signal_date):
        return {sym: 0.05 for sym in mkt_data.symbols}

    cfg = BacktestConfig(
        strategy=StrategyConfig(warmup_days=60, rebalance_every=5),
        custom_alpha_evaluator=dict_evaluator,
    )
    result = run_backtest(data, cfg)

    assert not result.equity_curve.empty
    assert not result.regimes.empty
    assert (result.regimes["label"] == "custom").all()


def test_strategy_contract_valid_and_bounds():
    valid_hypothesis = (
        "Exploiting medium-term price momentum driven by investor under-reaction "
        "and subsequent information diffusion across liquid equity markets."
    )
    contract = StrategyContract(
        strategy_name="AlphaTrendV1",
        agent_archetype="trend",
        economic_hypothesis=valid_hypothesis,
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="kalman_1",
                module_type="KalmanTrend",
                params={"lookback": 60, "smooth_factor": 0.5},
            )
        ],
        signal_expression="kalman_1",
        regime_gate_expression="1.0",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1W",
            trade_buffer_delta_weight=0.02,
            max_single_position_weight=0.10,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )
    assert contract.strategy_name == "AlphaTrendV1"
    assert contract.execution_overlay.rebalance_frequency == "1W"

    # Test hypothesis too short (<80 characters)
    with pytest.raises(ValidationError):
        StrategyContract(
            strategy_name="ShortHypo",
            agent_archetype="trend",
            economic_hypothesis="Too short hypothesis.",
            market_universe="US_LIQUID_500",
            primitives=[],
            signal_expression="kalman_1",
            execution_overlay=contract.execution_overlay,
        )

    # Test execution overlay bounds validation
    with pytest.raises(ValidationError):
        ExecutionOverlayConfig(
            rebalance_frequency="1D",
            trade_buffer_delta_weight=0.10,  # exceeds 0.05 max
            max_single_position_weight=0.10,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        )


def test_skeptic_verdict_and_compact_diagnostics():
    verdict = SkepticAuditVerdict(
        decision="APPROVE_FOR_OOS",
        violation_codes=[SkepticViolationCode.NONE],
        structural_diff_summary="Baseline contract approved with no prior mutations.",
        economic_coherence_score=5,
        overfitting_risk_critique="Clean economic rationale with disciplined shrinkage.",
        prescribed_single_modification=None,
    )
    assert verdict.decision == "APPROVE_FOR_OOS"
    assert verdict.economic_coherence_score == 5

    diagnostics = CompactBacktestDiagnostics(
        iteration=1,
        global_dsr_context=GlobalDsrContext(
            universe_total_trials_N=10,
            expected_null_max_sharpe_SR0=1.25,
            strategy_deflated_sharpe_DSR=0.92,
            status="PASS",
        ),
        core_performance=CorePerformance(
            net_sharpe=1.65,
            gross_sharpe=1.80,
            bootstrap_sharpe_p05=1.10,
            bootstrap_sharpe_p50=1.62,
            max_drawdown_pct=0.08,
            calmar_ratio=2.5,
            annualized_turnover_one_way=2.4,
        ),
        regime_conditioned_sharpe=RegimeConditionedSharpe(
            volatility_terciles={"low": 1.8, "mid": 1.6, "high": 1.2},
            dispersion_terciles={"low": 1.4, "mid": 1.7, "high": 1.9},
            market_trend_state={"bull": 2.1, "neutral": 1.3, "bear": 0.8},
        ),
        worst_anonymized_drawdown_episodes=[
            DrawdownEpisode(
                id="DD_1",
                depth_pct=0.078,
                duration_days=35,
                recovery_days=20,
                regime_state="bear",
                driver="trend reversal",
            )
        ],
        execution_friction_decomposition_annual_bps=ExecutionFrictionDecomposition(
            gross_alpha_bps=420.0,
            commission_and_tax_drag_bps=45.0,
            slippage_and_tick_quantization_bps=35.0,
            net_alpha_bps=340.0,
            stress_1_5x_cost_net_sharpe=1.45,
        ),
    )
    assert diagnostics.iteration == 1
    assert diagnostics.core_performance.net_sharpe == 1.65
