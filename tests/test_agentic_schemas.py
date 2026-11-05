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


def test_primitive_config_valid_and_invalid():
    cfg = PrimitiveConfig(
        primitive_id="kalman_1",
        module_type="KalmanTrend",
        params={"measurement_noise": 0.01, "process_noise": 0.001},
    )
    assert cfg.primitive_id == "kalman_1"
    assert cfg.module_type == "KalmanTrend"
    assert cfg.params["measurement_noise"] == 0.01

    with pytest.raises(ValidationError):
        PrimitiveConfig(
            primitive_id="bad_1",
            module_type="InvalidModuleType",  # type: ignore[arg-type]
            params={},
        )


def test_execution_overlay_config_bounds():
    valid = ExecutionOverlayConfig(
        rebalance_frequency="1W",
        trade_buffer_delta_weight=0.02,
        max_single_position_weight=0.10,
        target_gross_leverage=0.8,
        odd_lot_execution_mode="avoid_odd_lots",
    )
    assert valid.rebalance_frequency == "1W"

    with pytest.raises(ValidationError):
        ExecutionOverlayConfig(
            rebalance_frequency="1W",
            trade_buffer_delta_weight=0.06,  # > 0.05
            max_single_position_weight=0.10,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        )

    with pytest.raises(ValidationError):
        ExecutionOverlayConfig(
            rebalance_frequency="1W",
            trade_buffer_delta_weight=0.02,
            max_single_position_weight=0.005,  # < 0.01
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        )

    with pytest.raises(ValidationError):
        ExecutionOverlayConfig(
            rebalance_frequency="1W",
            trade_buffer_delta_weight=0.02,
            max_single_position_weight=0.10,
            target_gross_leverage=1.2,  # > 1.0
            odd_lot_execution_mode="avoid_odd_lots",
        )


def test_strategy_contract_and_hypothesis_length():
    hypothesis = (
        "Post-earnings drift persists in liquid mid-cap equities due to delayed institutional "
        "rebalancing and analyst underreaction over a 30-day forecast horizon."
    )
    assert len(hypothesis) >= 80

    overlay = ExecutionOverlayConfig(
        rebalance_frequency="2W",
        trade_buffer_delta_weight=0.01,
        max_single_position_weight=0.15,
        target_gross_leverage=1.0,
        odd_lot_execution_mode="allow_with_liquidity_cap",
    )
    primitive = PrimitiveConfig(
        primitive_id="pead_mom",
        module_type="ResidualMomentum",
        params={"lookback": 60},
    )
    contract = StrategyContract(
        strategy_name="PEAD_Residual_Momentum",
        agent_archetype="trend",
        economic_hypothesis=hypothesis,
        market_universe="US_LIQUID_500",
        primitives=[primitive],
        signal_expression="pead_mom > 0.5",
        regime_gate_expression="market_trend_state['trend'] == 1.0",
        execution_overlay=overlay,
    )
    dumped = contract.model_dump_json()
    reloaded = StrategyContract.model_validate_json(dumped)
    assert reloaded.strategy_name == contract.strategy_name
    assert len(reloaded.primitives) == 1

    # Hypothesis too short (<80 chars)
    with pytest.raises(ValidationError):
        StrategyContract(
            strategy_name=contract.strategy_name,
            agent_archetype=contract.agent_archetype,
            economic_hypothesis="Too short",
            market_universe=contract.market_universe,
            primitives=contract.primitives,
            signal_expression=contract.signal_expression,
            execution_overlay=contract.execution_overlay,
        )


def test_skeptic_audit_verdict_and_violations():
    verdict = SkepticAuditVerdict(
        decision="REVISE",
        violation_codes=[
            SkepticViolationCode.EXCESSIVE_COMPLEXITY,
            SkepticViolationCode.FRICTION_UNVIABLE,
        ],
        structural_diff_summary="Added 4 ad-hoc parameters without economic justification.",
        economic_coherence_score=2,
        overfitting_risk_critique="High turnover creates severe friction drag exceeding alpha.",
        prescribed_single_modification="Simplify signal expression to single factor momentum.",
    )
    assert verdict.economic_coherence_score == 2
    assert len(verdict.violation_codes) == 2

    with pytest.raises(ValidationError):
        SkepticAuditVerdict(
            decision="REVISE",
            violation_codes=[],
            structural_diff_summary="Summary",
            economic_coherence_score=6,  # > 5
            overfitting_risk_critique="Critique",
        )

    with pytest.raises(ValidationError):
        SkepticAuditVerdict(
            decision="REVISE",
            violation_codes=[],
            structural_diff_summary="Summary",
            economic_coherence_score=3,
            overfitting_risk_critique="x" * 601,  # > 600 chars
        )


def test_compact_backtest_diagnostics_roundtrip():
    diag = CompactBacktestDiagnostics(
        iteration=3,
        global_dsr_context=GlobalDsrContext(
            universe_total_trials_N=25,
            expected_null_max_sharpe_SR0=1.2,
            strategy_deflated_sharpe_DSR=0.96,
            status="PASSED",
        ),
        core_performance=CorePerformance(
            net_sharpe=1.45,
            gross_sharpe=1.72,
            bootstrap_sharpe_p05=1.05,
            bootstrap_sharpe_p50=1.42,
            max_drawdown_pct=0.12,
            calmar_ratio=1.8,
            annualized_turnover_one_way=2.5,
        ),
        regime_conditioned_sharpe=RegimeConditionedSharpe(
            volatility_terciles={"low": 1.6, "mid": 1.4, "high": 0.9},
            dispersion_terciles={"low": 1.1, "mid": 1.5, "high": 1.7},
            market_trend_state={"trend": 1.8, "mean_reverting": 0.8},
        ),
        worst_anonymized_drawdown_episodes=[
            DrawdownEpisode(
                id="ep_1",
                depth_pct=0.11,
                duration_days=45,
                recovery_days=30,
                regime_state="high_volatility",
                driver="market_selloff",
            )
        ],
        execution_friction_decomposition_annual_bps=ExecutionFrictionDecomposition(
            gross_alpha_bps=350.0,
            commission_and_tax_drag_bps=45.0,
            slippage_and_tick_quantization_bps=35.0,
            net_alpha_bps=270.0,
            stress_1_5x_cost_net_sharpe=1.28,
        ),
    )
    json_str = diag.model_dump_json()
    parsed = CompactBacktestDiagnostics.model_validate_json(json_str)
    assert parsed.iteration == 3
    assert parsed.core_performance.net_sharpe == 1.45
    assert len(parsed.worst_anonymized_drawdown_episodes) == 1


def test_custom_alpha_evaluator_backtest_hook():
    data = synthetic_market_data(periods=200)

    # 1. Custom evaluator returning equal weights for all symbols
    calls: list[pd.Timestamp] = []

    def equal_weight_alpha(m_data, signal_date: pd.Timestamp) -> pd.Series:
        calls.append(signal_date)
        n = len(m_data.symbols)
        return pd.Series(1.0 / n, index=m_data.symbols, dtype=float)

    config = BacktestConfig(
        strategy=StrategyConfig(warmup_days=60, rebalance_every=5),
        custom_alpha_evaluator=equal_weight_alpha,
    )
    result = run_backtest(data, config)

    assert len(calls) > 0
    assert not result.regimes.empty
    assert (result.regimes["label"] == "custom").all()
    assert (result.regimes["gross_exposure_limit"] == 1.0).all()

    # Verify executed weights closely match equal weighting
    rebalance_weights = result.weights.dropna()
    expected_weight = 1.0 / len(data.symbols)
    first_weight_row = rebalance_weights.iloc[0]
    for symbol in data.symbols:
        assert first_weight_row[symbol] == pytest.approx(expected_weight, abs=1e-3)
