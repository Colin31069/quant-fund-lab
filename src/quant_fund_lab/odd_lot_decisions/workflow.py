"""Publish immutable decision reports reconstructed from frozen policies and registry sources."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..odd_lot_protocol.decision import decision_budgets, policy_from_plan
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import canonical_json
from .evaluate import evaluate_research_decision
from .registry_evidence import collect_decision_inputs
from .reporting import decision_tables, render_decision
from .source_types import DecisionInputs, DecisionSource
from .types import ResearchDecision, fingerprint

ARTIFACTS = {"protocol.json", "context.json", "sources.json", "evidence.json", "decision.json",
             "candidates.csv", "checks.csv", "report.html"}


@dataclass(frozen=True)
class RegisteredDecision:
    decision: ResearchDecision
    report: Path


def build_registered_decision(protocol_directory: str | Path, *, registry_path: str | Path,
                               studies_directory: str | Path,
                               snapshot: tuple[DecisionSource, ...] | None = None) -> tuple[ResearchDecision, DecisionInputs]:
    protocol = load_protocol(protocol_directory)
    policy = policy_from_plan(protocol.analysis_plan_json)
    if policy is None:
        raise ValueError("protocol has no executable decision policy")
    inputs = collect_decision_inputs(protocol_directory, registry_path=registry_path,
                                     studies_directory=studies_directory, snapshot=snapshot)
    return evaluate_research_decision(protocol.protocol_id, policy, decision_budgets(protocol), inputs.evidence), inputs


def verify_registered_decision_report(directory: str | Path, *, registry_path: str | Path,
                                      studies_directory: str | Path) -> bool:
    """Replay the captured prefix even after later attempts, refusing altered sources or results."""
    root = Path(directory)
    try:
        manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
        report_id = manifest.pop("report_id")
        if manifest.get("schema_version") != 1 or fingerprint(manifest) != report_id:
            return False
        if set(manifest["files"]) != ARTIFACTS or {p.name for p in root.iterdir()} != ARTIFACTS | {"report_manifest.json"}:
            return False
        if any((root / name).is_symlink() or hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
               for name, digest in manifest["files"].items()):
            return False
        context = json.loads((root / "context.json").read_text(encoding="utf-8"))
        if context.get("schema_version") != 1 or context.get("snapshot_rule") != "attempt_prefix_v1":
            return False
        stamp = datetime.fromisoformat(context["created_at"])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return False
        sources = tuple(DecisionSource(**row) for row in json.loads((root / "sources.json").read_text(encoding="utf-8")))
        decision, inputs = build_registered_decision(root, registry_path=registry_path,
                                                    studies_directory=studies_directory, snapshot=sources)
        if (manifest["protocol_id"] != decision.protocol_id or manifest["decision_id"] != decision.decision_id
                or (root / "decision.json").read_text(encoding="utf-8") != canonical_json(decision.to_dict())
                or (root / "evidence.json").read_text(encoding="utf-8") != canonical_json(inputs.to_dict()["evidence"])):
            return False
        candidates, checks = decision_tables(decision)
        return ((root / "candidates.csv").read_bytes() == candidates.to_csv(index=False).encode()
                and (root / "checks.csv").read_bytes() == checks.to_csv(index=False).encode()
                and (root / "report.html").read_text(encoding="utf-8") == render_decision(decision, inputs.sources, context["created_at"]))
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error):
        return False


def export_registered_decision(protocol_directory: str | Path, *, registry_path: str | Path,
                                studies_directory: str | Path, output_directory: str | Path,
                                source_directory: str | Path) -> RegisteredDecision:
    """Evaluate current complete registry history, then atomically publish a new report."""
    if Path(__file__).resolve().parents[1] != Path(source_directory).resolve() / "src" / "quant_fund_lab":
        raise ValueError("decision source directory does not match the executing package")
    protocol_root = Path(protocol_directory)
    protocol = load_protocol(protocol_root)
    execution = capture_execution_identity(source_directory)
    if execution != protocol.execution:
        raise ValueError("decision execution identity differs from protocol; freeze a new protocol")
    decision, inputs = build_registered_decision(protocol_root, registry_path=registry_path, studies_directory=studies_directory)
    parent = Path(output_directory) / protocol.protocol_id
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".decision-", dir=parent) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        (staging / "protocol.json").write_bytes((protocol_root / "protocol.json").read_bytes())
        stamp = datetime.now(timezone.utc).isoformat()
        payloads = {"context.json": {"schema_version": 1, "created_at": stamp, "snapshot_rule": "attempt_prefix_v1"},
                    "sources.json": inputs.to_dict()["sources"], "evidence.json": inputs.to_dict()["evidence"],
                    "decision.json": decision.to_dict()}
        for name, values in payloads.items():
            (staging / name).write_text(canonical_json(values), encoding="utf-8")
        candidates, checks = decision_tables(decision)
        candidates.to_csv(staging / "candidates.csv", index=False)
        checks.to_csv(staging / "checks.csv", index=False)
        (staging / "report.html").write_text(render_decision(decision, inputs.sources, stamp), encoding="utf-8")
        manifest = {"schema_version": 1, "protocol_id": protocol.protocol_id, "decision_id": decision.decision_id,
                    "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in staging.iterdir()}}
        manifest["report_id"] = fingerprint(manifest)
        (staging / "report_manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
        if not verify_registered_decision_report(staging, registry_path=registry_path, studies_directory=studies_directory):
            raise ValueError("decision report failed source reconstruction")
        latest = collect_decision_inputs(protocol_root, registry_path=registry_path, studies_directory=studies_directory)
        if (latest.sources != inputs.sources or load_protocol(protocol_root) != protocol
                or capture_execution_identity(source_directory) != execution):
            raise ValueError("decision source history, protocol or execution changed before publication")
        os.rename(staging, target)
    return RegisteredDecision(decision, target)
