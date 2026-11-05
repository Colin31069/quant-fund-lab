"""Unit tests for Adversarial Risk Officer (Skeptic) deterministic and audit gates."""

from __future__ import annotations

import pytest

from quant_fund_lab.agentic.schemas import (
    CompactBacktestDiagnostics,
    CorePerformance,
    DrawdownEpisode,
    ExecutionFrictionDecomposition,
    ExecutionOverlayConfig,
    GlobalDsrContext,
    PrimitiveConfig,
    RegimeConditionedSharpe,
    SkepticViolationCode,
    StrategyContract,
)
from quant_fund_lab.agentic.skeptic import audit_strategy, compute_structural_diff


@pytest.fixture
def base_contract() -> StrategyContract:
    return StrategyContract(
        strategy_name="trend_v1",
        agent_archetype="trend",
        economic_hypothesis=(
            "Persistent trend signals filtered by linear decay on intermediate lookback windows "
            "to capture steady institutional momentum and avoid noise."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(
                primitive_id="k1",
                module_type="KalmanTrend",
                params={"half_life": 10},
            )
        ],
        signal_expression="ts_decay_linear(cs_rank(k1), 5)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1D",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.2,
            target_gross_leverage=0.8,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )


def make_diagnostics(
    net_sharpe: float = 1.5,
    bootstrap_p05: float = 0.5,
    stress_1_5x: float = 1.3,
    dsr: float = 0.96,
) -> CompactBacktestDiagnostics:
    return CompactBacktestDiagnostics(
        iteration=1,
        global_dsr_context=GlobalDsrContext(
            universe_total_trials_N=20,
            expected_null_max_sharpe_SR0=1.1,
            strategy_deflated_sharpe_DSR=dsr,
            status="ACTIVE",
        ),
        core_performance=CorePerformance(
            net_sharpe=net_sharpe,
            gross_sharpe=net_sharpe * 1.1,
            bootstrap_sharpe_p05=bootstrap_p05,
            bootstrap_sharpe_p50=net_sharpe,
            max_drawdown_pct=-12.0,
            calmar_ratio=1.2,
            annualized_turnover_one_way=2.0,
        ),
        regime_conditioned_sharpe=RegimeConditionedSharpe(
            volatility_terciles={"low": 1.6, "mid": 1.4, "high": 0.5},
            dispersion_terciles={"low": 0.5, "mid": 1.2, "high": 1.8},
            market_trend_state={"bull": 1.7, "chop": 1.2, "bear": -0.1},
        ),
        worst_anonymized_drawdown_episodes=[
            DrawdownEpisode(
                id="DD_1",
                depth_pct=-12.0,
                duration_days=30,
                recovery_days=25,
                regime_state="vol=80",
                driver="Normal rotation",
            )
        ],
        execution_friction_decomposition_annual_bps=ExecutionFrictionDecomposition(
            gross_alpha_bps=2000,
            commission_and_tax_drag_bps=-200,
            slippage_and_tick_quantization_bps=-100,
            net_alpha_bps=1700,
            stress_1_5x_cost_net_sharpe=stress_1_5x,
        ),
    )


def test_structural_diff(base_contract: StrategyContract) -> None:
    # 0 diffs
    assert compute_structural_diff(base_contract, None)[0] == 0

    # 1 diff: signal_expression
    revised_1 = base_contract.model_copy(
        update={"signal_expression": "ts_decay_linear(cs_rank(k1), 10)"}
    )
    diff_count, diff_fields = compute_structural_diff(revised_1, base_contract)
    assert diff_count == 1
    assert diff_fields == ["signal_expression"]

    # 2 diffs: signal_expression and execution_overlay
    revised_2 = revised_1.model_copy(
        update={
            "execution_overlay": base_contract.execution_overlay.model_copy(
                update={"trade_buffer_delta_weight": 0.02}
            )
        }
    )
    diff_count_2, _ = compute_structural_diff(revised_2, base_contract)
    assert diff_count_2 == 2


def test_multi_factor_mutation_rejected(base_contract: StrategyContract) -> None:
    revised_multi = base_contract.model_copy(
        update={
            "signal_expression": "cs_rank(k1)",
            "execution_overlay": base_contract.execution_overlay.model_copy(
                update={"rebalance_frequency": "1W"}
            ),
        }
    )
    diag = make_diagnostics()
    verdict = audit_strategy(revised_multi, diag, prev_contract=base_contract)
    assert verdict.decision == "REVISE"
    assert SkepticViolationCode.MULTI_FACTOR_MUTATION in verdict.violation_codes


def test_negative_sharpe_hard_reject(base_contract: StrategyContract) -> None:
    diag = make_diagnostics(net_sharpe=-0.2)
    verdict = audit_strategy(base_contract, diag)
    assert verdict.decision == "HARD_REJECT"
    assert SkepticViolationCode.FRICTION_UNVIABLE in verdict.violation_codes


def test_friction_unviable(base_contract: StrategyContract) -> None:
    diag = make_diagnostics(net_sharpe=1.0, stress_1_5x=0.15)
    verdict = audit_strategy(base_contract, diag)
    assert verdict.decision == "REVISE"
    assert SkepticViolationCode.FRICTION_UNVIABLE in verdict.violation_codes


def test_bootstrap_fragility(base_contract: StrategyContract) -> None:
    diag = make_diagnostics(net_sharpe=1.2, bootstrap_p05=0.10)
    verdict = audit_strategy(base_contract, diag)
    assert verdict.decision == "REVISE"
    assert SkepticViolationCode.BOOTSTRAP_FRAGILITY in verdict.violation_codes


def test_approve_for_oos(base_contract: StrategyContract) -> None:
    diag = make_diagnostics(net_sharpe=1.6, bootstrap_p05=0.45, stress_1_5x=1.35, dsr=0.97)
    verdict = audit_strategy(base_contract, diag)
    assert verdict.decision == "APPROVE_FOR_OOS"
    assert SkepticViolationCode.NONE in verdict.violation_codes
    assert verdict.economic_coherence_score == 5
