"""Adversarial Risk Officer (Skeptic) auditing contracts for p-hacking and structural flaws."""

from __future__ import annotations

from typing import Callable

from .schemas import (
    CompactBacktestDiagnostics,
    SkepticAuditVerdict,
    SkepticViolationCode,
    StrategyContract,
)

SKEPTIC_SYSTEM_PROMPT: str = """You are the Adversarial Risk Officer & Quantitative Methodologist.
Your role is to rigorously challenge strategy proposals for data snooping, p-hacking, and microstructural fragility.

SCORING CRITERIA:
- Score 5 (Eligible for APPROVE_FOR_OOS): Falsifiable economic rationale; mathematical formula directly aligns with stated mechanism; low friction drag; robust bootstrap lower tail.
- Score 3 (Triggers REVISE): Plausible core idea, but execution parameters, rebalance frequency, or lack of liquidity filtering contradicts universe microstructure.
- Score 1 (Triggers HARD_REJECT): Mathematical formula directly contradicts stated hypothesis, or displays arbitrary data-mined parameter patchwork.

FEW-SHOT ANCHORS:
[Score 5 - APPROVE_FOR_OOS]:
Input: archetype="mean_reversion", hypothesis="Short-term OU dislocations revert in 5-10d among liquid stocks, but fail during cascades.", signal="cs_demean(-cs_zscore(ou_10d)) * where(effective_tick_bps <= 20.0, 1.0, 0.0)", regime_gate="where(mkt_vol_pct_252d <= 0.85, 1.0, 0.3)", diagnostics: net_sharpe=1.62, stress_cost=1.38
Verdict: economic_coherence_score=5, decision="APPROVE_FOR_OOS", violation_codes=["NONE"]

[Score 3 - REVISE]:
Input: archetype="trend", universe="TWSE_TOP_150", hypothesis="63d Kalman trend captures institutional accumulation.", signal="cs_zscore(kalman_63d) - 0.5 * cs_rank(ret_1d)", rebalance="1D", trade_buffer=0.0, diagnostics: gross_sharpe=1.75, net_sharpe=0.68, turnover=14.2
Verdict: economic_coherence_score=3, decision="REVISE", violation_codes=["FRICTION_UNVIABLE"], prescribed_single_modification="Modify ONLY execution_overlay: change rebalance_frequency to '1W' and trade_buffer_delta_weight to 0.015 to prevent TWSE 30bps STT drag."

[Score 1 - HARD_REJECT]:
Input: archetype="low_beta_defensive", hypothesis="Defensive low-volatility portfolio.", signal="cs_rank(vol_21d * turnover_ratio_21d) * where(mkt_disp_pct_252d > 0.41, 1.0, -1.0)"
Verdict: economic_coherence_score=1, decision="HARD_REJECT", violation_codes=["HYPOTHESIS_MISMATCH", "AD_HOC_PATCHING"]
"""


def compute_structural_diff(
    current: StrategyContract,
    prev: StrategyContract | None,
) -> tuple[int, list[str]]:
    """Determine number of modified top-level sections between refinement rounds."""
    if prev is None:
        return 0, []

    diffs: list[str] = []
    if current.primitives != prev.primitives:
        diffs.append("primitives")
    if current.signal_expression != prev.signal_expression:
        diffs.append("signal_expression")
    if current.regime_gate_expression != prev.regime_gate_expression:
        diffs.append("regime_gate_expression")
    if current.execution_overlay != prev.execution_overlay:
        diffs.append("execution_overlay")

    return len(diffs), diffs


def audit_strategy(
    contract: StrategyContract,
    diagnostics: CompactBacktestDiagnostics,
    prev_contract: StrategyContract | None = None,
    llm_critic: Callable[[str], SkepticAuditVerdict] | None = None,
) -> SkepticAuditVerdict:
    """Execute two-tier audit: deterministic physical/statistical gates + semantic critic."""
    violations: list[SkepticViolationCode] = []
    num_diffs, diff_fields = compute_structural_diff(contract, prev_contract)

    # 1. Deterministic Scientific Control Gate (One-Change-Per-Round)
    if num_diffs > 1:
        violations.append(SkepticViolationCode.MULTI_FACTOR_MUTATION)
        return SkepticAuditVerdict(
            decision="REVISE",
            violation_codes=violations,
            structural_diff_summary=f"Changed {num_diffs} components simultaneously: {diff_fields}",
            economic_coherence_score=2,
            overfitting_risk_critique=(
                f"Multi-factor mutation violated scientific control by altering {diff_fields}. "
                "You must isolate changes to a single component per round."
            ),
            prescribed_single_modification=(
                f"Revert all changes except for '{diff_fields[0]}' to maintain causal attribution."
            ),
        )

    # 2. Deterministic Friction / Viability Gate
    core = diagnostics.core_performance
    friction = diagnostics.execution_friction_decomposition_annual_bps
    if core.net_sharpe <= 0.0:
        violations.append(SkepticViolationCode.FRICTION_UNVIABLE)
        return SkepticAuditVerdict(
            decision="HARD_REJECT",
            violation_codes=violations,
            structural_diff_summary=f"Diff: {diff_fields or ['initial']}",
            economic_coherence_score=1,
            overfitting_risk_critique="Negative net Sharpe ratio indicates unviable alpha or terminal cost drag.",
            prescribed_single_modification=None,
        )

    if friction.stress_1_5x_cost_net_sharpe <= 0.20 or (
        friction.gross_alpha_bps > 0
        and (friction.gross_alpha_bps - friction.net_alpha_bps) / friction.gross_alpha_bps > 0.65
    ):
        violations.append(SkepticViolationCode.FRICTION_UNVIABLE)
        return SkepticAuditVerdict(
            decision="REVISE",
            violation_codes=violations,
            structural_diff_summary=f"Diff: {diff_fields or ['initial']}",
            economic_coherence_score=3,
            overfitting_risk_critique=(
                f"Friction drag consumes excessive alpha: 1.5x stress Sharpe is {friction.stress_1_5x_cost_net_sharpe:.2f}."
            ),
            prescribed_single_modification=(
                "Lengthen rebalance frequency or increase trade_buffer_delta_weight to dampen turnover friction."
            ),
        )

    # 3. Deterministic Bootstrap Robustness Gate
    if core.bootstrap_sharpe_p05 < 0.25:
        violations.append(SkepticViolationCode.BOOTSTRAP_FRAGILITY)
        return SkepticAuditVerdict(
            decision="REVISE",
            violation_codes=violations,
            structural_diff_summary=f"Diff: {diff_fields or ['initial']}",
            economic_coherence_score=3,
            overfitting_risk_critique=(
                f"Lower tail 5th-percentile bootstrap Sharpe is {core.bootstrap_sharpe_p05:.2f} (< 0.25), "
                "signaling severe regime fragility or reliance on lucky months."
            ),
            prescribed_single_modification=(
                "Add or tighten regime_gate_expression scaling down exposure during high-volatility regimes."
            ),
        )

    # 4. Semantic Critic Evaluation (LLM or Heuristic Validation)
    if llm_critic is not None:
        return llm_critic(contract.model_dump_json())

    # Heuristic default check for admission to OOS
    dsr_val = diagnostics.global_dsr_context.strategy_deflated_sharpe_DSR
    if (
        dsr_val >= 0.95
        and core.bootstrap_sharpe_p05 >= 0.40
        and friction.stress_1_5x_cost_net_sharpe >= 0.50
    ):
        return SkepticAuditVerdict(
            decision="APPROVE_FOR_OOS",
            violation_codes=[SkepticViolationCode.NONE],
            structural_diff_summary=f"Diff: {diff_fields or ['initial']}",
            economic_coherence_score=5,
            overfitting_risk_critique="Meets all statistical, bootstrap, and cost sensitivity admission hurdles.",
            prescribed_single_modification=None,
        )

    return SkepticAuditVerdict(
        decision="REVISE",
        violation_codes=[SkepticViolationCode.NONE],
        structural_diff_summary=f"Diff: {diff_fields or ['initial']}",
        economic_coherence_score=4,
        overfitting_risk_critique="Promising candidate, but DSR or bootstrap threshold not yet unlocked for OOS.",
        prescribed_single_modification="Fine-tune parameter or regime gate to push DSR above 0.95.",
    )
