#!/usr/bin/env python3
"""Run autonomous 30-round strategy evolution for trend and mean-reversion archetypes."""

from __future__ import annotations

import json
from pathlib import Path

from quant_fund_lab.agentic.evolutionary_generator import EvolutionaryStrategyGenerator
from quant_fund_lab.agentic.orchestrator import AgenticTournamentOrchestrator
from quant_fund_lab.agentic.tournament import TemporalPartition
from quant_fund_lab.agentic.trials_registry import TrialsRegistry
from quant_fund_lab.snapshot import load_market_data_snapshot


def main() -> None:
    print("=" * 70)
    print("  Quant Fund Lab: Autonomous Agentic Strategy Evolution (30 Rounds)")
    print("  Target Archetypes: [trend, mean_reversion]")
    print("=" * 70)

    # 1. Load Market Data Snapshot
    snapshot_dir = Path("artifacts/provider_cache/latest")
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

    print(f"\n[1/5] Loading market data snapshot from '{snapshot_dir}'...")
    data = load_market_data_snapshot(snapshot_dir)
    print(f"      Universe: {list(data.close.columns)} ({len(data.close.columns)} tickers)")
    print(f"      Date range: {data.close.index[0]} to {data.close.index[-1]} ({len(data.close)} bars)")

    # 2. Initialize Trials Registry
    artifacts_dir = Path("artifacts/agentic_evolution")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    db_path = artifacts_dir / "trials.db"
    if db_path.exists():
        db_path.unlink()
    registry = TrialsRegistry(db_path=db_path)
    print(f"\n[2/5] Initialized TrialsRegistry at '{db_path}'.")

    # 3. Configure Temporal Partition (IS + Embargo + OOS Vault)
    partition = TemporalPartition()
    is_data, oos_data = partition.split(data)
    print("\n[3/5] Temporal Partition:")
    print(f"      In-Sample Bars (Zones A+B): {len(is_data.close)} bars ({is_data.close.index[0]} to {is_data.close.index[-1]})")
    print(f"      OOS Vault Bars (Zone D):     {len(oos_data.close)} bars ({oos_data.close.index[0]} to {oos_data.close.index[-1]})")

    # 4. Orchestrate 30-Round Evolution
    print("\n[4/5] Executing 30 rounds of single-mutation evolution per archetype...")
    generator = EvolutionaryStrategyGenerator(seed=42)
    orchestrator = AgenticTournamentOrchestrator(
        registry=registry,
        partition=partition,
        archetypes=["trend", "mean_reversion"],
        max_rounds_per_lineage=30,
        early_stop_patience=None,
        seed=42,
    )

    result = orchestrator.run(data, generator, run_id="EVO_RUN_30R")
    print("      Evolution loops complete!")

    # 5. Output Summary & Lineage Diagnostics
    print("\n[5/5] Evolutionary Lineage Results:")
    for arch, lineage in result.lineages.items():
        print(f"\n--- Archetype: {arch.upper()} ---")
        print(f"Rounds Completed: {lineage.rounds_completed}")
        print(f"Best Strategy:    {lineage.best_contract.strategy_name}")
        print(f"Best Fitness J:   {lineage.best_fitness_j:.3f}")
        verdict = result.skeptic_verdicts.get(arch)
        if verdict:
            print(f"Skeptic Verdict:  {verdict.decision} (Score: {verdict.economic_coherence_score}/5)")
            print(f"Skeptic Critique: {verdict.overfitting_risk_critique}")

        print(f"\nLineage Trajectory Table ({arch}):")
        print(registry.format_lineage_markdown_table(lineage.lineage_id))

    print("\n" + "=" * 70)
    print("  Tournament Ensemble Outcome:")
    print(f"  Approved for OOS:     {result.approved_strategies}")
    print(f"  Tournament Survivors: {result.provenance_manifest.get('survivors', [])}")
    print(f"  Ensemble Weights:     {result.provenance_manifest.get('weights', {})}")
    print(f"  Total Trials in DB:   {result.provenance_manifest.get('total_trials_in_registry', 0)}")
    print("=" * 70)

    # Save summary artifact
    summary_path = artifacts_dir / "evolution_summary.json"
    summary_data = {
        "run_id": result.run_id,
        "timestamp": result.timestamp,
        "approved_strategies": result.approved_strategies,
        "survivors": result.provenance_manifest.get("survivors", []),
        "weights": result.provenance_manifest.get("weights", {}),
        "total_trials": result.provenance_manifest.get("total_trials_in_registry", 0),
        "lineages": {
            arch: {
                "rounds_completed": lin.rounds_completed,
                "best_strategy": lin.best_contract.strategy_name,
                "best_fitness_j": lin.best_fitness_j,
                "history": [
                    {k: v for k, v in h.items() if k != "diagnostics" and k != "contract"}
                    for h in lin.history
                ],
            }
            for arch, lin in result.lineages.items()
        },
    }
    summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
    print(f"\nSaved evolution summary to '{summary_path}'.")


if __name__ == "__main__":
    main()
