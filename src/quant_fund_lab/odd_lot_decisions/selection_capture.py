"""Persist a development selection before any second-stage validation business parsing."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..odd_lot_protocol.decision import policy_from_plan
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import canonical_json
from .development import DevelopmentSelection
from .development_registry import collect_registered_development
from .development_source_types import DEVELOPMENT_SOURCE_RULE, DevelopmentInputs
from .source_types import DecisionSource
from .types import fingerprint

CAPTURE_FILES = {"protocol.json", "development_selection.json", "selection_context.json", "sources.json"}


@dataclass(frozen=True)
class SavedDevelopmentSelection:
    directory: Path
    inputs: DevelopmentInputs
    capture_fingerprint: str


def load_development_selection(directory: str | Path, *, registry_path: str | Path,
                                studies_directory: str | Path) -> SavedDevelopmentSelection:
    """Reconstruct a captured prefix; later attempts cannot promote its selection."""
    root = Path(directory)
    expected_files = CAPTURE_FILES | {"selection_manifest.json"}
    if root.is_symlink() or {path.name for path in root.iterdir()} != expected_files:
        raise ValueError("selection capture inventory differs from its schema")
    if any((root / name).is_symlink() or not (root / name).is_file() for name in expected_files):
        raise ValueError("selection capture artifacts must be regular files")
    manifest = json.loads((root / "selection_manifest.json").read_text(encoding="utf-8"))
    identity = manifest.pop("capture_fingerprint")
    if (set(manifest) != {"schema_version", "protocol_id", "selection_id", "files"}
            or manifest["schema_version"] != 1 or set(manifest["files"]) != CAPTURE_FILES
            or fingerprint(manifest) != identity):
        raise ValueError("selection capture manifest identity differs")
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
           for name, digest in manifest["files"].items()):
        raise ValueError("selection capture byte integrity failed")
    protocol = load_protocol(root)
    context = json.loads((root / "selection_context.json").read_text(encoding="utf-8"))
    if (set(context) != {"schema_version", "created_at", "source_rule", "protocol_id", "policy_id", "execution"}
            or context["schema_version"] != 1 or context["source_rule"] != DEVELOPMENT_SOURCE_RULE
            or context["protocol_id"] != protocol.protocol_id or context["execution"] != asdict(protocol.execution)
            or context["policy_id"] != fingerprint(asdict(policy_from_plan(protocol.analysis_plan_json)))):
        raise ValueError("selection capture context differs from frozen protocol")
    stamp = datetime.fromisoformat(context["created_at"])
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("selection capture time requires an explicit timezone")
    saved = DevelopmentSelection.from_dict(json.loads((root / "development_selection.json").read_text(encoding="utf-8")))
    sources = tuple(DecisionSource(**row) for row in json.loads((root / "sources.json").read_text(encoding="utf-8")))
    inputs = collect_registered_development(root, registry_path=registry_path,
        studies_directory=studies_directory, snapshot=sources)
    if (inputs.selection != saved or manifest["protocol_id"] != protocol.protocol_id
            or manifest["selection_id"] != saved.selection_id
            or (root / "development_selection.json").read_text(encoding="utf-8") != canonical_json(saved.to_dict())
            or (root / "sources.json").read_text(encoding="utf-8") != canonical_json(inputs.to_dict()["sources"])):
        raise ValueError("selection capture differs from development source reconstruction")
    return SavedDevelopmentSelection(root, inputs, identity)


def export_development_selection(protocol_directory: str | Path, *, registry_path: str | Path,
                                  studies_directory: str | Path, output_directory: str | Path,
                                  source_directory: str | Path) -> SavedDevelopmentSelection:
    """Authenticate development, persist/reconstruct it, then atomically publish a capture.

    This independent v5 analysis does not run validation or claim that the original
    batch research was staged. A phased decision workflow must explicitly reference
    this saved artifact and freeze its own supported collection contract.
    """
    if Path(__file__).resolve().parents[1] != Path(source_directory).resolve() / "src" / "quant_fund_lab":
        raise ValueError("selection source directory differs from executing package")
    protocol_root = Path(protocol_directory)
    protocol = load_protocol(protocol_root)
    execution = capture_execution_identity(source_directory)
    if execution != protocol.execution:
        raise ValueError("selection execution differs from protocol; freeze a new protocol")
    inputs = collect_registered_development(protocol_root, registry_path=registry_path,
                                            studies_directory=studies_directory)
    parent = Path(output_directory) / protocol.protocol_id / "selections" / inputs.selection.selection_id
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".selection-", dir=parent) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        (staging / "protocol.json").write_bytes((protocol_root / "protocol.json").read_bytes())
        context = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                   "source_rule": DEVELOPMENT_SOURCE_RULE, "protocol_id": protocol.protocol_id,
                   "policy_id": fingerprint(asdict(policy_from_plan(protocol.analysis_plan_json))),
                   "execution": asdict(execution)}
        for name, payload in {"selection_context.json": context,
                              "development_selection.json": inputs.selection.to_dict(),
                              "sources.json": inputs.to_dict()["sources"]}.items():
            (staging / name).write_text(canonical_json(payload), encoding="utf-8")
        manifest = {"schema_version": 1, "protocol_id": protocol.protocol_id,
                    "selection_id": inputs.selection.selection_id,
                    "files": {name: hashlib.sha256((staging / name).read_bytes()).hexdigest() for name in sorted(CAPTURE_FILES)}}
        manifest["capture_fingerprint"] = fingerprint(manifest)
        (staging / "selection_manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
        saved = load_development_selection(staging, registry_path=registry_path, studies_directory=studies_directory)
        latest = collect_registered_development(protocol_root, registry_path=registry_path,
                                                studies_directory=studies_directory)
        if (latest != inputs or load_protocol(protocol_root) != protocol
                or capture_execution_identity(source_directory) != execution):
            raise ValueError("selection sources, protocol or execution changed before publication")
        os.rename(staging, destination)
    return SavedDevelopmentSelection(destination, saved.inputs, saved.capture_fingerprint)
