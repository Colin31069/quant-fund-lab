"""Explicit research mutations; browser inspection never calls these operations."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from ..odd_lot_protocol import freeze_protocol, protocol_from_studies, run_registered_study
from ..odd_lot_protocol.benchmark import benchmark_from_plan
from ..odd_lot_protocol.decision_rules import PHASED_ENGINE
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.registry import ExperimentRegistry
from ..odd_lot_protocol.run import RegisteredStudyRun
from ..odd_lot_protocol.types import StudyProtocol, json_object
from .inspection import inspect_research
from .phased_reporting import export_phased_decision
from .selection_capture import export_development_selection
from .types import DecisionPolicy
from .workflow import RegisteredDecision


@dataclass(frozen=True)
class FrozenPolicyChild:
    protocol: StudyProtocol
    directory: Path


def explicit_policy(payload: str) -> DecisionPolicy:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise TypeError("policy must be a complete JSON object")
    policy = DecisionPolicy(**value)
    if set(value) != set(asdict(policy)):
        raise ValueError("policy must explicitly declare every field, including optional gate choices")
    return policy


def freeze_policy_child(parent_directory: str | Path, policy_json: str, *, registry_path: str | Path,
                         studies_directory: str | Path, protocols_directory: str | Path,
                         source_directory: str | Path) -> FrozenPolicyChild:
    """Retain parent data/budget/access history; changes form a new explicit v6 child."""
    if Path(__file__).resolve().parents[1] != Path(source_directory).resolve() / "src" / "quant_fund_lab":
        raise ValueError("policy source differs from executing package")
    policy = explicit_policy(policy_json)
    parent = inspect_research(parent_directory, registry_path=registry_path).protocol
    benchmark = benchmark_from_plan(parent.analysis_plan_json)
    if benchmark is None:
        raise ValueError("parent has no explicit tradable benchmark; freeze that research contract first")
    selection = replace(parent.selection, development_objective=policy.development_objective,
                         minimum_completed_trades=policy.minimum_completed_trades)
    execution = capture_execution_identity(source_directory)
    child = protocol_from_studies(tuple(Path(studies_directory) / candidate.study_id for candidate in parent.candidates),
        periods=parent.periods, selection=selection, execution=execution,
        declared_at=datetime.now(timezone.utc).isoformat(), seed=parent.seed,
        parent_protocol_id=parent.protocol_id, benchmark_spec=benchmark,
        risk_diagnostics=True, matched_sensitivity=True, decision_policy=policy, phased_decisions=True)
    # The standard freezer verifies the parent at the chosen output root; callers
    # cannot silently copy/rewrite an absent parent or change its historical access.
    if capture_execution_identity(source_directory) != execution:
        raise ValueError("policy execution changed before freezing")
    directory = freeze_protocol(child, protocols_directory)
    with ExperimentRegistry(registry_path) as registry:
        registry.register_protocol(child)
    return FrozenPolicyChild(child, directory)


def execute_frozen_candidate(protocol_directory: str | Path, candidate_id: str, *, registry_path: str | Path,
                               studies_directory: str | Path, source_directory: str | Path) -> RegisteredStudyRun:
    return run_registered_study(protocol_directory,candidate_id,registry_path=registry_path,
        studies_directory=studies_directory,source_directory=source_directory)


def save_current_decision(protocol_directory: str | Path, *, registry_path: str | Path,
                           studies_directory: str | Path, output_directory: str | Path,
                           source_directory: str | Path) -> RegisteredDecision:
    protocol = inspect_research(protocol_directory,registry_path=registry_path).protocol
    if json_object(protocol.analysis_plan_json)["engine"] != PHASED_ENGINE:
        raise ValueError("decision action requires an explicit v6 child policy")
    saved = export_development_selection(protocol_directory,registry_path=registry_path,
        studies_directory=studies_directory,output_directory=output_directory,source_directory=source_directory)
    # A validation exception deliberately leaves the already published selection
    # intact. It must never trigger a different choice, another run or a reset.
    return export_phased_decision(saved.directory,registry_path=registry_path,
        studies_directory=studies_directory,output_directory=output_directory,source_directory=source_directory)
