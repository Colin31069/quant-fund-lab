"""Reconstructable v6 decisions contain their immutable development capture."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..odd_lot_protocol.decision_rules import CAPTURE_RULE, PHASED_SOURCE_RULE
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import canonical_json
from .development_registry import collect_registered_development
from .phased_evaluation import PhasedEvaluation, evaluate_saved_selection
from .reporting import decision_tables, render_decision
from .selection_capture import CAPTURE_FILES
from .types import fingerprint
from .workflow import RegisteredDecision

SELECTION_FILES = CAPTURE_FILES | {"selection_manifest.json"}
ROOT_FILES = {"protocol.json", "context.json", "selection_reference.json", "development_selection.json",
              "sources.json", "evidence.json", "decision.json", "candidates.csv", "checks.csv", "report.html"}
ARTIFACTS = ROOT_FILES | {"selection/" + name for name in SELECTION_FILES}


def _payloads(evaluation: PhasedEvaluation, stamp: str) -> dict:
    selection, decision = evaluation.saved.inputs.selection, evaluation.decision
    return {
        "context.json": {"schema_version": 2, "created_at": stamp,
                         "source_rule": PHASED_SOURCE_RULE, "capture_rule": CAPTURE_RULE},
        "selection_reference.json": {"selection_id": selection.selection_id,
                                     "capture_fingerprint": evaluation.saved.capture_fingerprint},
        "development_selection.json": selection.to_dict(),
        "sources.json": evaluation.saved.inputs.to_dict()["sources"],
        "evidence.json": asdict(evaluation.validation) if evaluation.validation is not None else None,
        "decision.json": {"schema_version": 2, "selection_id": selection.selection_id,
                          "decision_id": decision.decision_id, "decision": decision.to_dict()},
    }


def _html(evaluation: PhasedEvaluation, stamp: str) -> str:
    section = ("<h2>已保存的開發選擇</h2><p>selection：" + evaluation.saved.inputs.selection.selection_id
               + "<br>capture：" + evaluation.saved.capture_fingerprint
               + "</p><p>開發選擇先保存及讀回核對，再收集固定選擇的驗證證據；驗證失敗不補位。"
               "原始歷史 batch 報告已存在，本流程不宣稱其驗證資料過去從未被接觸。</p>")
    return render_decision(evaluation.decision, evaluation.saved.inputs.sources, stamp).replace("</body>", section + "</body>")


def verify_phased_decision_report(directory: str | Path, *, registry_path: str | Path,
                                   studies_directory: str | Path) -> bool:
    """Replay the embedded capture and fixed validation, including historical prefixes."""
    root = Path(directory)
    try:
        if (root.is_symlink() or (root / "selection").is_symlink()
                or {p.name for p in root.iterdir()} != ROOT_FILES | {"selection", "report_manifest.json"}):
            return False
        paths = ARTIFACTS | {"report_manifest.json"}
        if any((root / name).is_symlink() or not (root / name).is_file() for name in paths):
            return False
        manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
            return False
        identity = manifest.pop("report_id")
        if (set(manifest) != {"schema_version", "protocol_id", "decision_id", "selection_id", "files"}
                or manifest["schema_version"] != 2 or set(manifest["files"]) != ARTIFACTS
                or fingerprint(manifest) != identity):
            return False
        if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
               for name, digest in manifest["files"].items()):
            return False
        context = json.loads((root / "context.json").read_text(encoding="utf-8"))
        if not isinstance(context, dict):
            return False
        stamp = context["created_at"]
        time = datetime.fromisoformat(stamp)
        if time.tzinfo is None or time.utcoffset() is None:
            return False
        evaluation = evaluate_saved_selection(root / "selection", registry_path=registry_path,
                                               studies_directory=studies_directory)
        if ((root / "protocol.json").read_bytes() != (root / "selection/protocol.json").read_bytes()
                or manifest["protocol_id"] != evaluation.decision.protocol_id
                or manifest["decision_id"] != evaluation.decision.decision_id
                or manifest["selection_id"] != evaluation.saved.inputs.selection.selection_id):
            return False
        for name, value in _payloads(evaluation, stamp).items():
            if (root / name).read_text(encoding="utf-8") != canonical_json(value):
                return False
        candidates, checks = decision_tables(evaluation.decision)
        return ((root / "candidates.csv").read_bytes() == candidates.to_csv(index=False).encode()
                and (root / "checks.csv").read_bytes() == checks.to_csv(index=False).encode()
                and (root / "report.html").read_text(encoding="utf-8") == _html(evaluation, stamp))
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration, sqlite3.Error):
        return False


def export_phased_decision(selection_directory: str | Path, *, registry_path: str | Path,
                            studies_directory: str | Path, output_directory: str | Path,
                            source_directory: str | Path) -> RegisteredDecision:
    """Publish a current decision only from an already saved, explicit v6 selection."""
    if Path(__file__).resolve().parents[1] != Path(source_directory).resolve() / "src" / "quant_fund_lab":
        raise ValueError("phased decision source differs from executing package")
    selection_root = Path(selection_directory)
    protocol = load_protocol(selection_root)
    execution = capture_execution_identity(source_directory)
    if execution != protocol.execution:
        raise ValueError("phased decision execution differs from protocol; freeze a new protocol")
    evaluation = evaluate_saved_selection(selection_root, registry_path=registry_path, studies_directory=studies_directory)
    initial_bytes = {name: (selection_root / name).read_bytes() for name in SELECTION_FILES}
    parent = Path(output_directory) / protocol.protocol_id / evaluation.decision.decision_id
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".phased-decision-", dir=parent) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        shutil.copytree(selection_root, staging / "selection")
        (staging / "protocol.json").write_bytes(initial_bytes["protocol.json"])
        stamp = datetime.now(timezone.utc).isoformat()
        for name, value in _payloads(evaluation, stamp).items():
            (staging / name).write_text(canonical_json(value), encoding="utf-8")
        candidates, checks = decision_tables(evaluation.decision)
        candidates.to_csv(staging / "candidates.csv", index=False)
        checks.to_csv(staging / "checks.csv", index=False)
        (staging / "report.html").write_text(_html(evaluation, stamp), encoding="utf-8")
        manifest = {"schema_version": 2, "protocol_id": protocol.protocol_id,
                    "decision_id": evaluation.decision.decision_id,
                    "selection_id": evaluation.saved.inputs.selection.selection_id,
                    "files": {name: hashlib.sha256((staging / name).read_bytes()).hexdigest() for name in sorted(ARTIFACTS)}}
        manifest["report_id"] = fingerprint(manifest)
        (staging / "report_manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
        if not verify_phased_decision_report(staging, registry_path=registry_path, studies_directory=studies_directory):
            raise ValueError("phased decision failed source reconstruction")
        latest = collect_registered_development(selection_root, registry_path=registry_path,
                                                studies_directory=studies_directory)
        if (latest != evaluation.saved.inputs or load_protocol(selection_root) != protocol
                or any((selection_root / name).read_bytes() != value for name, value in initial_bytes.items())
                or capture_execution_identity(source_directory) != execution):
            raise ValueError("phased decision sources or execution changed before publication")
        os.rename(staging, destination)
    return RegisteredDecision(evaluation.decision, destination)
