"""Agentic Tournament Orchestrator coordinating hypothesis evolution, skeptic audit, and tournament allocation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, ClassVar

from quant_fund_lab.data import MarketData

from .reflection_loop import ReflectionResult, StrategyGenerator, run_reflection_loop
from .schemas import SkepticAuditVerdict, StrategyContract
from .skeptic import audit_strategy
from .tournament import TemporalPartition, evaluate_tournament_ensemble
from .trials_registry import TrialsRegistry


@dataclass(frozen=True)
class TournamentResult:
    """End-to-end outcome of agentic strategy evolution and tournament allocation."""

    run_id: str
    timestamp: str
    lineages: dict[str, ReflectionResult]
    skeptic_verdicts: dict[str, SkepticAuditVerdict]
    approved_strategies: list[str]
    tournament_ensemble: dict[str, Any]
    bootstrap_thresholds: dict[str, tuple[float, float]]
    provenance_manifest: dict[str, Any]


class AgenticTournamentOrchestrator:
    """Master orchestrator executing autonomous strategy evolution across archetypes."""

    DEFAULT_ARCHETYPES: ClassVar[list[str]] = [
        "trend",
        "mean_reversion",
        "quality_fundamental",
        "low_beta_defensive",
    ]

    def __init__(
        self,
        registry: TrialsRegistry,
        partition: TemporalPartition | None = None,
        archetypes: list[str] | None = None,
        max_rounds_per_lineage: int = 4,
        seed: int = 42,
    ) -> None:
        self.registry = registry
        self.partition = partition or TemporalPartition()
        self.archetypes = archetypes or list(self.DEFAULT_ARCHETYPES)
        self.max_rounds = max_rounds_per_lineage
        self.seed = seed

    def run(
        self,
        full_data: MarketData,
        generator: StrategyGenerator,
        run_id: str | None = None,
    ) -> TournamentResult:
        """Execute multi-archetype evolution, skeptic risk audit, and tournament assembly."""
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        run_id = run_id or f"ORCH_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # 1. Partition Data across Warmup, In-Sample, Purged Embargo, and OOS Vault
        is_data, oos_data = self.partition.split(full_data)

        lineages: dict[str, ReflectionResult] = {}
        skeptic_verdicts: dict[str, SkepticAuditVerdict] = {}
        approved_contracts: list[StrategyContract] = []
        bootstrap_thresholds: dict[str, tuple[float, float]] = {}
        dsr_scores: dict[str, float] = {}

        # 2. Evolutionary Search across Archetypes
        for archetype in self.archetypes:
            ref_res = run_reflection_loop(
                generator=generator,
                data=is_data,
                archetype=archetype,
                registry=self.registry,
                max_rounds=self.max_rounds,
                lineage_id=f"{run_id}_{archetype}",
                seed=self.seed,
            )
            lineages[archetype] = ref_res

            # Extract best trial diagnostics if available
            best_diag = None
            if ref_res.history:
                best_trial = max(ref_res.history, key=lambda h: float(h.get("fitness_j", float("-inf"))))
                best_diag = best_trial.get("diagnostics")

            # 3. Skeptic Audit
            if best_diag is not None:
                verdict = audit_strategy(ref_res.best_contract, best_diag)
            else:
                verdict = SkepticAuditVerdict(
                    decision="HARD_REJECT",
                    violation_codes=[],
                    structural_diff_summary="No valid diagnostics generated",
                    economic_coherence_score=1,
                    overfitting_risk_critique="Failed to generate valid diagnostics during reflection.",
                    prescribed_single_modification=None,
                )
            skeptic_verdicts[archetype] = verdict

            if verdict.decision == "APPROVE_FOR_OOS":
                approved_contracts.append(ref_res.best_contract)
                c_name = ref_res.best_contract.strategy_name
                dsr_val = best_diag.global_dsr_context.deflated_sharpe_ratio if best_diag else 0.95
                dsr_scores[c_name] = dsr_val

                # Precompute bootstrap confidence bounds for live drift monitoring
                if best_diag:
                    p01 = best_diag.core_performance.bootstrap_sharpe_p01
                    p05 = best_diag.core_performance.bootstrap_sharpe_p05
                else:
                    p01, p05 = -0.5, 0.0
                bootstrap_thresholds[c_name] = (p01, p05)

        # 4. Tournament Allocation on OOS Vault Data
        tournament_res = evaluate_tournament_ensemble(
            approved_contracts=approved_contracts,
            oos_data=oos_data,
            dsr_scores=dsr_scores,
            seed=self.seed,
        )

        # 5. Provenance Manifest
        manifest = {
            "run_id": run_id,
            "timestamp": now_iso,
            "archetypes_evaluated": self.archetypes,
            "approved_count": len(approved_contracts),
            "survivors": tournament_res.get("survivor_strategies", []),
            "weights": tournament_res.get("ensemble_weights", {}),
            "total_trials_in_registry": self.registry.count_trials(),
        }

        return TournamentResult(
            run_id=run_id,
            timestamp=now_iso,
            lineages=lineages,
            skeptic_verdicts=skeptic_verdicts,
            approved_strategies=[c.strategy_name for c in approved_contracts],
            tournament_ensemble=tournament_res,
            bootstrap_thresholds=bootstrap_thresholds,
            provenance_manifest=manifest,
        )
