"""Immutable source versions with explicitly reviewed cash-dividend date mappings."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from .odd_lot_event_dates import CashDividendDateReview
from .twse_amendments import _inventory
from .twse_quality.types import fingerprint


def derive_cash_dividend_review_bundle(
    directory: str | Path, parent: str | Path,
    reviews: tuple[CashDividendDateReview, ...], evidence_files: dict[str, Path],
) -> Path:
    """Append reviews in a new version, retaining the parent and all prior records.

    Preparation independently checks event amounts, official calendar evidence and
    the supported rule before these reviews can affect any normalized data.
    """
    source, destination_parent = Path(directory).resolve(), Path(parent).resolve()
    if source == destination_parent or source in destination_parent.parents:
        raise ValueError("review destination must be outside the original bundle")
    if not reviews or not (source / "manifest.json").is_file():
        raise ValueError("event derivation requires a manifest and explicit reviews")
    records = sorted((asdict(review) for review in reviews),
                     key=lambda r: (r["scheduled_date"], r["symbol"]))
    keys = [(r["scheduled_date"], r["symbol"]) for r in records]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate event date reviews")
    required = {r["rule_evidence_path"]: r["rule_sha256"] for r in records}
    if set(evidence_files) != set(required):
        raise ValueError("provide exactly the reviewed rule evidence files")
    for name, path in evidence_files.items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or not name.startswith("evidence/")
                or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != required[name]):
            raise ValueError("unsafe or changed event review evidence")
    baseline = _inventory(source)
    payload = {"schema_version": 1, "operation": "append_reviewed_cash_dividend_dates",
               "base_files": baseline, "reviews": records, "evidence_sha256": required}
    amendment_id = fingerprint(payload)
    destination = destination_parent / amendment_id[:24]
    destination_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".event-dates-", dir=destination_parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for name in baseline:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        if _inventory(staging) != baseline or _inventory(source) != baseline:
            raise ValueError("source bundle changed during event derivation")
        amendment = staging / "amendments" / amendment_id
        amendment.mkdir(parents=True)
        audit_files = []
        old_manifest = amendment / "previous_manifest.json"
        shutil.copyfile(staging / "manifest.json", old_manifest)
        audit_files.append(old_manifest)
        registry = staging / "action_date_reviews.csv"
        fields = list(CashDividendDateReview.__dataclass_fields__)
        rows = []
        if registry.exists():
            old = amendment / "previous_action_date_reviews.csv"
            shutil.copyfile(registry, old)
            audit_files.append(old)
            with registry.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                if reader.fieldnames != fields:
                    raise ValueError("unexpected prior date review schema")
                rows = list(reader)
        existing = {(r["scheduled_date"], r["symbol"]) for r in rows}
        if existing.intersection(keys):
            raise ValueError("new review conflicts with a prior reviewed event")
        for name, path in evidence_files.items():
            target = staging / name
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != required[name]:
                raise ValueError("review evidence changed during derivation")
            if target.exists() and target.read_bytes() != raw:
                raise ValueError("rule evidence path conflicts with existing bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        with registry.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows([*rows, *records])
        review_file = amendment / "review.json"
        review_file.write_text(json.dumps({"amendment_id": amendment_id, **payload},
                                          sort_keys=True, indent=2), encoding="utf-8")
        audit_files.append(review_file)
        manifest_path = staging / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("amendment_records", []).extend({
            "path": p.relative_to(staging).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        } for p in audit_files)
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        if destination.exists():
            if _inventory(destination) != _inventory(staging):
                raise ValueError("existing event review version changed; cannot overwrite")
            return destination
        os.rename(staging, destination)
    return destination
