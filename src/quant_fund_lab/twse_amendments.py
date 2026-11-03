"""Create immutable derived bundles for explicitly reviewed closure evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .twse_odd_lot import _official_url
from .twse_quality.types import fingerprint


@dataclass(frozen=True)
class ClosureEvidence:
    session: str
    published_on: str
    source_url: str
    evidence_file: Path
    sha256: str
    review_note: str

    def record(self) -> dict:
        """Return portable reviewed metadata after checking original evidence bytes."""
        for value in (self.session, self.published_on):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("closure dates must be canonical ISO dates")
        if not _official_url(self.source_url) or not self.review_note:
            raise ValueError("closure requires a TWSE source and explicit review note")
        raw = self.evidence_file.read_bytes()
        if not raw or hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError("closure evidence hash differs from reviewed bytes")
        suffix = self.evidence_file.suffix.lower()
        if suffix not in {".pdf", ".html", ".json", ".txt"}:
            raise ValueError("unsupported closure evidence format")
        return {"date": self.session, "published_on": self.published_on,
                "source_url": self.source_url, "sha256": self.sha256,
                "evidence_path": f"evidence/closure_{self.session}_{self.sha256[:16]}{suffix}",
                "review_note": self.review_note}


@dataclass(frozen=True)
class SymbolSuspensionEvidence(ClosureEvidence):
    """One explicitly reviewed security suspension; never a market closure."""

    symbol: str

    def record(self) -> dict:
        if not re.fullmatch(r"\d{4,6}\.TW", self.symbol):
            raise ValueError("suspension requires a canonical individual TWSE symbol")
        record = super().record()
        record["symbol"] = self.symbol
        record["evidence_path"] = record["evidence_path"].replace("closure_", "suspension_")
        return record


def _inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("derived bundles cannot copy symlinked evidence")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def derive_closure_bundle(directory: str | Path, parent: str | Path,
                          closures: tuple[ClosureEvidence, ...]) -> Path:
    """Fork source bytes, append reviewed closures, and never replace an existing version.

    This records an actual review, not an automatic assertion that a URL proves a
    closure. Contradictory observed quotes remain detectable by the normalizer.
    """
    source, destination_parent = Path(directory).resolve(), Path(parent).resolve()
    if source == destination_parent or source in destination_parent.parents:
        raise ValueError("derived destination must be outside the original bundle")
    if not (source / "manifest.json").is_file() or not closures:
        raise ValueError("derivation requires a source manifest and reviewed closures")
    records = sorted((item.record() for item in closures),
                     key=lambda item: (item["date"], item.get("symbol", "*")))
    if len({(r["date"], r.get("symbol", "*")) for r in records}) != len(records):
        raise ValueError("duplicate reviewed closure date")
    symbol_records = ["symbol" in row for row in records]
    if any(symbol_records) and not all(symbol_records):
        raise ValueError("derive market closures and security suspensions separately")
    baseline = _inventory(source)
    operation = "append_reviewed_symbol_suspensions" if all(symbol_records) else "append_reviewed_market_closures"
    payload = {"schema_version": 1, "operation": operation,
               "base_files": baseline, "closures": records}
    amendment_id = fingerprint(payload)
    destination = destination_parent / amendment_id[:24]
    destination_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".closure-", dir=destination_parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for name in baseline:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        if _inventory(staging) != baseline or _inventory(source) != baseline:
            raise ValueError("source bundle changed during derivation")
        registry = staging / "suspensions.csv"
        with registry.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fields, rows = reader.fieldnames, list(reader)
        if fields != ["date", "symbol", "source_url", "evidence_path"]:
            raise ValueError("unexpected suspension registry schema")
        old = staging / "amendments" / amendment_id / "previous_suspensions.csv"
        old.parent.mkdir(parents=True)
        shutil.copyfile(registry, old)
        old_manifest = old.parent / "previous_manifest.json"
        shutil.copyfile(staging / "manifest.json", old_manifest)
        for item, record in zip(sorted(closures, key=lambda value: (value.session, getattr(value, "symbol", "*"))), records):
            symbol = record.get("symbol", "*")
            matching = [r for r in rows if (r["date"], r["symbol"]) == (record["date"], symbol)]
            new_row = {"date": record["date"], "symbol": symbol, "source_url": record["source_url"],
                       "evidence_path": record["evidence_path"]}
            if matching and matching != [new_row]:
                raise ValueError("closure conflicts with an existing market record")
            target = staging / record["evidence_path"]
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError("reviewed evidence path conflicts with existing bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = item.evidence_file.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise ValueError("closure evidence changed during derivation")
            target.write_bytes(raw)
            if not matching:
                rows.append(new_row)
        with registry.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        review_file = old.parent / "review.json"
        review_file.write_text(
            json.dumps({"amendment_id": amendment_id, **payload}, sort_keys=True, indent=2), encoding="utf-8"
        )
        manifest_path = staging / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = manifest.setdefault("amendment_records", [])
        records.extend({"path": p.relative_to(staging).as_posix(),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in (old, old_manifest, review_file))
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        if destination.exists():
            if _inventory(destination) != _inventory(staging):
                raise ValueError("existing derived bundle has changed; preserve it and use a new version")
            return destination
        os.rename(staging, destination)
    return destination
