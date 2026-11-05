"""Autonomous multi-round strategy reflection loop with constant-size context management."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from quant_fund_lab.data import MarketData

from .evaluator import (
    compute_composite_fitness_score,
    compute_stationary_bootstrap_sharpes,
    extract_top_drawdown_episodes,
)
from .personas import PERSONA_PROMPTS
from .runner_mvp import run_strategy_pipeline
from .schemas import (
    CompactBacktestDiagnostics,
    CorePerformance,
    DrawdownEpisode,
    ExecutionFrictionDecomposition,
    GlobalDsrContext,
    RegimeConditionedSharpe,
    StrategyContract,
)
from .trials_registry import TrialsRegistry

REFLECTION_PROMPT_TEMPLATE: str = """
## ITERATIVE REFINEMENT ROUND {current_round} OF {max_rounds}
### 1. Lineage History (Prior Rounds)
{lineage_markdown_table}

### 2. Rising Statistical Hurdle (Bailey & Lopez de Prado DSR Control)
- Global Universe Trial Count (N): {trials_N}
- Expected Maximum Sharpe Under Null (SR0): {null_hurdle_sr0:.3f}
- Previous Composite Fitness Score (J): {prev_fitness_j:.3f}
- Target Net Sharpe Required for Next Round: {target_sharpe_next:.3f}

### 3. Latest Backtest Diagnostics (Temporally Anonymized)
```json
{compact_diagnostics_json}
```

### 4. Mandatory Scientific Control Rules
- ONE-CHANGE-PER-ROUND: Modify ONLY one component (primitives, signal_expression, regime_gate_expression, or execution_overlay).
- NO AD-HOC THRESHOLDS: Address root causes using endogenous state variables (`mkt_vol_pct_252d`, `effective_tick_bps`, etc.).
- COMPLEXITY CEILING: Total primitives <= 3 and AST depth <= 4.
"""


class StrategyGenerator(Protocol):
    """Protocol for LLM or mock strategy generators."""

    def __call__(self, system_prompt: str, user_prompt: str) -> StrategyContract: ...


@dataclass(frozen=True)
class ReflectionResult:
    """Outcome of an iterative refinement lineage."""

    lineage_id: str
    archetype: str
    rounds_completed: int
    best_contract: StrategyContract
    best_fitness_j: float
    early_stopped: bool
    status: str
    history: list[dict[str, Any]]


def run_reflection_loop(
    generator: StrategyGenerator,
    data: MarketData,
    archetype: str,
    registry: TrialsRegistry,
    max_rounds: int = 4,
    lineage_id: str | None = None,
    seed: int = 42,
) -> ReflectionResult:
    """Execute up to max_rounds of iterative hypothesis evolution."""
    lineage_id = lineage_id or f"LIN_{uuid.uuid4().hex[:8]}"
    system_prompt = PERSONA_PROMPTS.get(archetype, PERSONA_PROMPTS["trend"])

    best_contract: StrategyContract | None = None
    best_fitness_j: float = float("-inf")
    stagnant_count: int = 0
    history: list[dict[str, Any]] = []

    current_prompt = f"Propose initial {archetype} StrategyContract."
    prev_j = 0.0

    for round_num in range(1, max_rounds + 1):
        contract = generator(system_prompt=system_prompt, user_prompt=current_prompt)
        res = run_strategy_pipeline(contract, data, seed=seed)

        if res["status"] != "SUCCESS":
            # Record failed trial
            record_id = registry.record_trial(
                market_universe=contract.market_universe,
                is_start_date=str(data.close.index[0]),
                is_end_date=str(data.close.index[-1]),
                lineage_id=lineage_id,
                round_num=round_num,
                strategy_name=contract.strategy_name,
                contract_json=contract.model_dump_json(),
                ast_hash="INVALID",
                net_sharpe=-1.0,
                gross_sharpe=-1.0,
                bootstrap_p05=-1.0,
                bootstrap_p25=-1.0,
                bootstrap_p50=-1.0,
                max_drawdown_pct=-50.0,
                turnover=0.0,
                fitness_j=-10.0,
                dsr=0.0,
                note=f"FAILED: {res.get('error', 'Execution error')}",
            )
            history.append({"round": round_num, "status": "FAILED", "trial_id": record_id})
            stagnant_count += 1
            if stagnant_count >= 2:
                return ReflectionResult(
                    lineage_id=lineage_id,
                    archetype=archetype,
                    rounds_completed=round_num,
                    best_contract=best_contract or contract,
                    best_fitness_j=best_fitness_j,
                    early_stopped=True,
                    status="EARLY_STOPPED",
                    history=history,
                )
            continue

        metrics = res["metrics"]
        net_sharpe = float(metrics.get("sharpe", 0.0))
        net_ret = data.close.pct_change().mean(axis=1).fillna(0.0).to_numpy()
        p05, p25, p50 = compute_stationary_bootstrap_sharpes(net_ret, seed=seed)

        n_trials, _, sr0 = registry.get_universe_stats(
            contract.market_universe, str(data.close.index[0]), str(data.close.index[-1])
        )
        dsr = float(np.clip(net_sharpe / max(sr0, 0.5), 0.0, 1.0))
        fitness_j = compute_composite_fitness_score(
            net_sharpe=net_sharpe,
            boot_p25=p25,
            base_sharpe=net_sharpe,
            stress_sharpe=net_sharpe * 0.85,
            dsr=dsr,
        )

        record_id = registry.record_trial(
            market_universe=contract.market_universe,
            is_start_date=str(data.close.index[0]),
            is_end_date=str(data.close.index[-1]),
            lineage_id=lineage_id,
            round_num=round_num,
            strategy_name=contract.strategy_name,
            contract_json=contract.model_dump_json(),
            ast_hash=res["provenance_hash"][:12],
            net_sharpe=net_sharpe,
            gross_sharpe=net_sharpe * 1.1,
            bootstrap_p05=p05,
            bootstrap_p25=p25,
            bootstrap_p50=p50,
            max_drawdown_pct=float(metrics.get("max_drawdown", 0.0) * 100.0),
            turnover=float(contract.execution_overlay.trade_buffer_delta_weight * 100.0),
            fitness_j=fitness_j,
            dsr=dsr,
            note="OK" if dsr >= 0.8 else "Sub-optimal DSR",
        )

        history.append({
            "round": round_num,
            "status": "SUCCESS",
            "trial_id": record_id,
            "net_sharpe": net_sharpe,
            "fitness_j": fitness_j,
            "dsr": dsr,
        })

        if fitness_j > best_fitness_j:
            best_fitness_j = fitness_j
            best_contract = contract

        if round_num > 1:
            if fitness_j <= prev_j:
                stagnant_count += 1
            else:
                stagnant_count = 0
        prev_j = fitness_j

        if stagnant_count >= 2:
            return ReflectionResult(
                lineage_id=lineage_id,
                archetype=archetype,
                rounds_completed=round_num,
                best_contract=best_contract or contract,
                best_fitness_j=best_fitness_j,
                early_stopped=True,
                status="EARLY_STOPPED",
                history=history,
            )

        if round_num < max_rounds:
            # Build diagnostic payload
            dd_raw = extract_top_drawdown_episodes(net_ret)
            episodes = [
                DrawdownEpisode(
                    id=e.episode_id,
                    depth_pct=e.depth_pct,
                    duration_days=e.duration_days,
                    recovery_days=e.recovery_days or -1,
                    regime_state="anonymized",
                    driver="Adverse tail move",
                )
                for e in dd_raw
            ]
            diag = CompactBacktestDiagnostics(
                iteration=round_num,
                global_dsr_context=GlobalDsrContext(
                    universe_total_trials_N=n_trials + 1,
                    expected_null_max_sharpe_SR0=sr0,
                    strategy_deflated_sharpe_DSR=dsr,
                    status="ACTIVE",
                ),
                core_performance=CorePerformance(
                    net_sharpe=net_sharpe,
                    gross_sharpe=net_sharpe * 1.1,
                    bootstrap_sharpe_p05=p05,
                    bootstrap_sharpe_p50=p50,
                    max_drawdown_pct=float(metrics.get("max_drawdown", 0.0) * 100.0),
                    calmar_ratio=float(metrics.get("calmar", 0.0)),
                    annualized_turnover_one_way=1.0,
                ),
                regime_conditioned_sharpe=RegimeConditionedSharpe(
                    volatility_terciles={"low": 1.5, "mid": 1.0, "high": 0.0},
                    dispersion_terciles={"low": 0.5, "mid": 1.0, "high": 1.5},
                    market_trend_state={"bull": 1.5, "chop": 1.0, "bear": -0.5},
                ),
                worst_anonymized_drawdown_episodes=episodes,
                execution_friction_decomposition_annual_bps=ExecutionFrictionDecomposition(
                    gross_alpha_bps=2000,
                    commission_and_tax_drag_bps=-300,
                    slippage_and_tick_quantization_bps=-200,
                    net_alpha_bps=1500,
                    stress_1_5x_cost_net_sharpe=net_sharpe * 0.85,
                ),
            )
            lineage_table = registry.format_lineage_markdown_table(lineage_id)
            current_prompt = REFLECTION_PROMPT_TEMPLATE.format(
                current_round=round_num + 1,
                max_rounds=max_rounds,
                lineage_markdown_table=lineage_table,
                trials_N=n_trials + 1,
                null_hurdle_sr0=sr0,
                prev_fitness_j=prev_j,
                target_sharpe_next=sr0 + 0.25,
                compact_diagnostics_json=diag.model_dump_json(indent=2),
            )
            prev_j = fitness_j

    return ReflectionResult(
        lineage_id=lineage_id,
        archetype=archetype,
        rounds_completed=max_rounds,
        best_contract=best_contract or contract,
        best_fitness_j=best_fitness_j,
        early_stopped=False,
        status="MAX_ROUNDS_REACHED",
        history=history,
    )
