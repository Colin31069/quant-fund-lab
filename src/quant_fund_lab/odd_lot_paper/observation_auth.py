"""Authenticate a registered plan against its exact historical decision and code."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..odd_lot_decisions.development_registry import collect_registered_development
from ..odd_lot_decisions.phased_evaluation import evaluate_saved_selection
from ..odd_lot_decisions.phased_reporting import verify_phased_decision_report
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import StudyProtocol
from .observation import ObservationPlan, load_observation_plan


@dataclass(frozen=True)
class AuthenticatedObservation:
    plan: ObservationPlan
    protocol: StudyProtocol
    decision_directory: Path


def authenticate_observation_plan(directory: str | Path, *, registry_path: str | Path,
                                   studies_directory: str | Path,
                                   source_directory: str | Path) -> AuthenticatedObservation:
    """Read only; changed decisions/settings, stale history or code refuse activation.

    Local manifest and registration timestamps are preserved provenance records;
    this does not provide an independent trusted-time attestation.
    """
    root = Path(directory)
    if root.is_symlink() or {path.name for path in root.iterdir()} != {"plan.json", "decision_reference.json"}:
        raise ValueError("observation registration inventory differs")
    before = {}
    for name in ("plan.json", "decision_reference.json"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("observation registration files must be regular files")
        before[name] = path.read_bytes()
    plan = load_observation_plan(root)
    reference = json.loads(before["decision_reference.json"])
    if (set(reference) != {"report", "report_manifest_sha256"}
            or reference["report_manifest_sha256"] != plan.source_manifest_sha256):
        raise ValueError("observation decision reference differs from registered plan")
    report = Path(reference["report"])
    if not verify_phased_decision_report(report,registry_path=registry_path,studies_directory=studies_directory):
        raise ValueError("observation decision cannot be reconstructed")
    manifest = (report / "report_manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != plan.source_manifest_sha256:
        raise ValueError("observation decision manifest differs from registration")
    protocol = load_protocol(report)
    source = Path(source_directory).resolve()
    if Path(__file__).resolve().parents[1] != source / "src/quant_fund_lab":
        raise ValueError("observation source directory differs from executing package")
    execution = capture_execution_identity(source)
    if protocol.execution != execution or plan.execution_id != execution.identity:
        raise ValueError("observation execution differs from registration")
    evaluation = evaluate_saved_selection(report / "selection",registry_path=registry_path,
                                          studies_directory=studies_directory)
    decision = evaluation.decision
    candidate = next((row for row in protocol.candidates if row.candidate_id == plan.candidate_id), None)
    if (decision.status != "continue" or decision.protocol_id != plan.protocol_id
            or decision.decision_id != plan.decision_id or decision.selected_candidate != plan.candidate_id
            or decision.selected_strategy != plan.strategy or candidate is None
            or candidate.research_json != plan.research_config_json
            or candidate.backtest_json != plan.execution_config_json
            or evaluation.saved.inputs.selection.selection_id != plan.selection_id):
        raise ValueError("observation settings or choice differ from registered decision")
    current = collect_registered_development(report,registry_path=registry_path,studies_directory=studies_directory)
    if current.sources != evaluation.saved.inputs.sources:
        raise ValueError("observation decision is stale relative to experiment history")
    registered = datetime.fromisoformat(plan.recorded_at)
    published = datetime.fromisoformat(json.loads((report / "context.json").read_text())["created_at"])
    if registered < max(published, datetime.fromisoformat(protocol.declared_at)):
        raise ValueError("observation registration predates its decision or protocol")
    if (not verify_phased_decision_report(report,registry_path=registry_path,
            studies_directory=studies_directory)
            or any((root / name).read_bytes() != raw for name, raw in before.items())
            or (report / "report_manifest.json").read_bytes() != manifest
            or load_protocol(report) != protocol or capture_execution_identity(source) != execution
            or collect_registered_development(report,registry_path=registry_path,
                studies_directory=studies_directory).sources != current.sources):
        raise ValueError("observation registration or decision changed during authentication")
    return AuthenticatedObservation(plan, protocol, report)
