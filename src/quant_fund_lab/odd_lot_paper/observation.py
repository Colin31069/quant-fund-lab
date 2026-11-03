"""Immutable preregistration of a future virtual observation after a verified decision."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..odd_lot_decisions.development_registry import collect_registered_development
from ..odd_lot_decisions.phased_evaluation import evaluate_saved_selection
from ..odd_lot_decisions.phased_reporting import verify_phased_decision_report
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import json_object
from .ledger import canonical, digest


@dataclass(frozen=True)
class ObservationPlan:
    protocol_id: str
    candidate_id: str
    strategy: str
    decision_id: str
    selection_id: str
    execution_id: str
    first_session: str
    recorded_at: str
    source_manifest_sha256: str
    research_config_json: str
    execution_config_json: str
    access_note: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        for value in (self.protocol_id,self.candidate_id,self.decision_id,self.selection_id,
                      self.execution_id,self.source_manifest_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("observation identities require full SHA-256")
        first = date.fromisoformat(self.first_session)
        stamp = datetime.fromisoformat(self.recorded_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("observation recording requires an explicit timezone")
        if first.isoformat() != self.first_session or first <= stamp.astimezone(ZoneInfo("Asia/Taipei")).date():
            raise ValueError("observation first session must be strictly future at registration")
        if self.strategy not in {"ensemble","momentum"} or not self.access_note.strip():
            raise ValueError("observation requires a selected active strategy and access note")
        for payload in (self.research_config_json,self.execution_config_json):
            json_object(payload)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported observation schema")

    @property
    def plan_id(self) -> str:
        return digest(canonical(asdict(self)))


def register_forward_observation(decision_directory: str | Path, *, first_session: str,
                                  access_note: str, registry_path: str | Path,
                                  studies_directory: str | Path, source_directory: str | Path,
                                  output_directory: str | Path) -> Path:
    """Register future intent; no account is created before verified new-session data.

    This records actual registration time and preserves historical data exposure.
    It does not prove future data availability or activate a running account.
    """
    root = Path(decision_directory)
    if not verify_phased_decision_report(root,registry_path=registry_path,studies_directory=studies_directory):
        raise ValueError("observation requires a verified phased decision report")
    evaluation = evaluate_saved_selection(root / "selection",registry_path=registry_path,
                                          studies_directory=studies_directory)
    decision = evaluation.decision
    if decision.status != "continue" or decision.selected_candidate is None:
        raise ValueError("observation requires a continuing fixed-candidate decision")
    protocol = load_protocol(root)
    source = Path(source_directory).resolve()
    if Path(__file__).resolve().parents[1] != source / "src/quant_fund_lab":
        raise ValueError("observation source directory differs from executing package")
    execution = capture_execution_identity(source)
    if execution != protocol.execution:
        raise ValueError("observation execution identity differs from frozen protocol")
    latest = collect_registered_development(root,registry_path=registry_path,studies_directory=studies_directory)
    if latest.sources != evaluation.saved.inputs.sources:
        raise ValueError("observation decision is stale relative to current experiment history")
    candidate = next(row for row in protocol.candidates if row.candidate_id == decision.selected_candidate)
    manifest = (root / "report_manifest.json").read_bytes()
    plan = ObservationPlan(protocol.protocol_id,candidate.candidate_id,decision.selected_strategy,
        decision.decision_id,evaluation.saved.inputs.selection.selection_id,execution.identity,
        first_session,datetime.now(timezone.utc).isoformat(),hashlib.sha256(manifest).hexdigest(),
        candidate.research_json,candidate.backtest_json,access_note)
    output = Path(output_directory)
    if output.is_symlink():
        raise ValueError("observation output cannot be symlinked")
    output.mkdir(parents=True,exist_ok=True)
    target = output / plan.plan_id
    with tempfile.TemporaryDirectory(prefix=".observation-",dir=output) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        (staging / "plan.json").write_text(canonical({"plan_id":plan.plan_id,"plan":asdict(plan),
            "status":"registered_pending_verified_session"}))
        (staging / "decision_reference.json").write_text(canonical({"report":str(root.resolve()),
            "report_manifest_sha256":plan.source_manifest_sha256}))
        if (not verify_phased_decision_report(root,registry_path=registry_path,
                studies_directory=studies_directory)
                or capture_execution_identity(source) != execution or load_protocol(root) != protocol
                or (root / "report_manifest.json").read_bytes() != manifest
                or collect_registered_development(root,registry_path=registry_path,
                    studies_directory=studies_directory).sources != latest.sources):
            raise ValueError("observation sources changed before registration")
        os.rename(staging,target)
    return target


def load_observation_plan(directory: str | Path) -> ObservationPlan:
    root = Path(directory)
    if root.is_symlink() or (root / "plan.json").is_symlink():
        raise ValueError("observation plan cannot be symlinked")
    envelope = json.loads((root / "plan.json").read_text())
    if set(envelope) != {"plan_id","plan","status"} or envelope["status"] != "registered_pending_verified_session":
        raise ValueError("unsupported observation envelope")
    plan = ObservationPlan(**envelope["plan"])
    if plan.plan_id != envelope["plan_id"]:
        raise ValueError("observation plan fingerprint differs")
    return plan
