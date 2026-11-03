"""Bind finite candidate studies to their exact shared data and analysis plan."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .. import __version__
from ..odd_lot_benchmarks import BenchmarkSpec
from ..odd_lot_decisions.types import DecisionPolicy
from ..odd_lot_diagnostics.types import DIAGNOSTICS_RULE
from ..odd_lot_research import OddLotResearchConfig
from ..odd_lot_sensitivity.types import SENSITIVITY_RULE
from ..odd_lot_study import _backtest_config, load_frozen_odd_lot_study
from ..twse_quality.types import READINESS_RULE_VERSION, fingerprint
from .decision_rules import CAPTURE_RULE, PHASED_ENGINE, PHASED_SOURCE_RULE, SELECTION_RULE
from .types import (
    ExecutionIdentity,
    ProtocolCandidate,
    ProtocolPeriod,
    SelectionRule,
    StudyProtocol,
    canonical_json,
    json_object,
)


def analysis_plan(candidates: tuple[ProtocolCandidate, ...], benchmark_spec: BenchmarkSpec | None = None,
                  *, risk_diagnostics: bool = False, matched_sensitivity: bool = False,
                  decision_policy: DecisionPolicy | None = None, phased_decisions: bool = False) -> dict:
    """Describe the existing batch engine's fixed strategies and sensitivity grid."""
    if type(risk_diagnostics) is not bool or risk_diagnostics and benchmark_spec is None:
        raise ValueError("risk diagnostics require an explicit benchmark and boolean declaration")
    if type(matched_sensitivity) is not bool or matched_sensitivity and not risk_diagnostics:
        raise ValueError("matched sensitivity requires diagnostics and a boolean declaration")
    if decision_policy is not None and (not isinstance(decision_policy, DecisionPolicy) or not matched_sensitivity):
        raise ValueError("executable decisions require a typed policy and matched sensitivity")
    if type(phased_decisions) is not bool or phased_decisions and decision_policy is None:
        raise ValueError("phased decisions require an explicit policy and boolean declaration")
    scenarios = {}
    for candidate in candidates:
        research = json_object(candidate.research_json)
        rows = list(dict.fromkeys((
            (0.0, 5.0, research["fill_fraction"]), (20.0, 5.0, research["fill_fraction"]),
            (50.0, 5.0, research["fill_fraction"]), (20.0, 10.0, research["fill_fraction"]),
            (research["min_commission"], research["slippage_bps"], 0.25),
            (research["min_commission"], research["slippage_bps"], 0.50),
            (research["min_commission"], research["slippage_bps"], 1.00),
        )))
        scenarios[candidate.candidate_id] = [list(row) for row in rows]
    plan = {"engine": "frozen_odd_lot_batch_v1", "strategies": ["ensemble", "momentum", "equal_weight"],
            "sensitivity_period": "validation", "sensitivity_strategies": ["ensemble", "momentum"],
            "sensitivity_columns": ["min_commission", "slippage_bps", "fill_fraction"],
            "scenarios_by_candidate": scenarios, "randomness": "deterministic_no_random_draws",
            "reference_benchmark": "total_return_proxy_no_trading_costs",
            "tradable_benchmark": "not_yet_implemented", "automatic_candidate_selection": False}
    if benchmark_spec is not None:
        plan.update(engine="frozen_odd_lot_batch_v2", tradable_benchmark=asdict(benchmark_spec))
    if risk_diagnostics:
        plan.update(engine="frozen_odd_lot_batch_v3", risk_diagnostics=DIAGNOSTICS_RULE)
    if matched_sensitivity:
        plan.update(engine="frozen_odd_lot_batch_v4", sensitivity_execution_rule=SENSITIVITY_RULE,
                    sensitivity_strategies=["ensemble", "momentum", benchmark_spec.result_name])
    if decision_policy is not None:
        plan.update(engine="frozen_odd_lot_batch_v5", decision_policy=asdict(decision_policy),
                    automatic_candidate_selection=True, decision_ranking_period="development",
                    decision_validation_period="validation", decision_strategies=["ensemble", "momentum"],
                    decision_source_rule="latest_registered_attempt_prefix_v1")
    if phased_decisions:
        plan.update(engine=PHASED_ENGINE, decision_source_rule=PHASED_SOURCE_RULE,
                    decision_capture_rule=CAPTURE_RULE, decision_selection_rule=SELECTION_RULE)
    return plan


def _binding(metadata: dict) -> dict:
    if (metadata.get("schema_version") != 3
            or metadata.get("package_version") != __version__
            or metadata["readiness"]["rule_version"] != READINESS_RULE_VERSION):
        raise ValueError("protocol candidates require current verified schema-3 studies")
    return {"dataset_id": metadata["dataset_id"], "symbols": metadata["symbols"],
            "benchmark": metadata["benchmark"], "periods": metadata["periods"],
            "warmup": max(120, metadata["backtest_config"]["strategy"]["warmup_days"]),
            "input_fingerprint": metadata["readiness"]["input_fingerprint"],
            "calendar_revisions": sorted({p["warmup"]["calendar_revision"]
                                          for p in metadata["readiness"]["periods"]}),
            "source_policy": {"data_source": metadata["data_source"],
                              "provenance": metadata.get("source_provenance", {}),
                              "source_files_fingerprint": fingerprint(metadata["source_files"])}}


def protocol_from_studies(
    directories: tuple[Path, ...], *, periods: tuple[ProtocolPeriod, ...],
    selection: SelectionRule, execution: ExecutionIdentity, declared_at: str,
    seed: int = 0, parent_protocol_id: str | None = None,
    benchmark_spec: BenchmarkSpec | None = None,
    risk_diagnostics: bool = False,
    matched_sensitivity: bool = False,
    decision_policy: DecisionPolicy | None = None,
    phased_decisions: bool = False,
) -> StudyProtocol:
    """Freeze assumptions, not results; blocked data can still be registered honestly."""
    if not directories:
        raise ValueError("protocol requires at least one frozen candidate study")
    shared = None
    candidates = []
    for directory in directories:
        _, metadata = load_frozen_odd_lot_study(directory)
        binding = _binding(metadata)
        if shared is not None and shared != binding:
            raise ValueError("candidate studies do not share exact inputs, calendar and periods")
        shared = binding
        if benchmark_spec is not None and (
            benchmark_spec.symbol != metadata["benchmark"]
            or benchmark_spec.initial_cash != metadata["backtest_config"]["initial_cash"]
        ):
            raise ValueError("protocol benchmark must share frozen capital and benchmark symbol")
        OddLotResearchConfig(**metadata["research_config"])
        _backtest_config(metadata["backtest_config"])
        candidates.append(ProtocolCandidate(metadata["study_id"], canonical_json(metadata["research_config"]),
                                             canonical_json(metadata["backtest_config"])))
    declared = {period.name: [period.start, period.end] for period in periods}
    if declared != shared["periods"]:
        raise ValueError("protocol purposes must cover the exact frozen study periods")
    if "validation" not in declared:
        raise ValueError("current batch analysis requires an explicit validation period")
    from .decision import validate_decision_binding

    validate_decision_binding(periods, selection, decision_policy)
    ordered = tuple(sorted(candidates, key=lambda c: c.candidate_id))
    return StudyProtocol(shared["dataset_id"], shared["input_fingerprint"],
        canonical_json(shared["source_policy"]), tuple(shared["calendar_revisions"]),
        tuple(shared["symbols"]), shared["benchmark"], shared["warmup"],
        tuple(sorted(periods, key=lambda p: p.start)), ordered, len(ordered), selection,
        canonical_json(analysis_plan(ordered, benchmark_spec, risk_diagnostics=risk_diagnostics,
                                     matched_sensitivity=matched_sensitivity, decision_policy=decision_policy,
                                     phased_decisions=phased_decisions)),
        execution, declared_at, seed, parent_protocol_id)


def verify_candidate_binding(protocol: StudyProtocol, candidate: ProtocolCandidate, metadata: dict) -> None:
    """Revalidate archived assumptions before accepting a result under this protocol."""
    from .benchmark import benchmark_from_plan
    from .decision import policy_from_plan, validate_decision_binding
    from .diagnostics import diagnostics_enabled
    from .sensitivity import sensitivity_enabled

    benchmark_spec = benchmark_from_plan(protocol.analysis_plan_json)
    policy = policy_from_plan(protocol.analysis_plan_json)
    validate_decision_binding(protocol.periods, protocol.selection, policy)
    binding = _binding(metadata)
    actual = ProtocolCandidate(metadata["study_id"], canonical_json(metadata["research_config"]),
                               canonical_json(metadata["backtest_config"]))
    expected = {"dataset_id": protocol.dataset_id, "symbols": list(protocol.symbols),
                "benchmark": protocol.benchmark, "warmup": protocol.warmup,
                "periods": {p.name: [p.start, p.end] for p in protocol.periods},
                "input_fingerprint": protocol.input_fingerprint,
                "calendar_revisions": list(protocol.calendar_revisions),
                "source_policy": json_object(protocol.source_policy_json)}
    if (binding != expected or actual != candidate
            or canonical_json(analysis_plan(protocol.candidates, benchmark_spec,
                risk_diagnostics=diagnostics_enabled(protocol.analysis_plan_json),
                matched_sensitivity=sensitivity_enabled(protocol.analysis_plan_json),
                decision_policy=policy, phased_decisions=json_object(protocol.analysis_plan_json).get("engine") == PHASED_ENGINE)) != protocol.analysis_plan_json):
        raise ValueError("candidate or analysis plan differs from frozen protocol")
    if benchmark_spec is not None and (benchmark_spec.symbol != metadata["benchmark"]
            or benchmark_spec.initial_cash != metadata["backtest_config"]["initial_cash"]):
        raise ValueError("protocol benchmark differs from study capital or symbol")
