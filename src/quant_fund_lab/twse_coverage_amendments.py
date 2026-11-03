"""Publish explicit category coverage reviews without rewriting source bundles."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .twse_amendments import _inventory
from .twse_odd_lot import COVERAGE_CATEGORIES, _official_url
from .twse_quality.types import fingerprint

FIELDS = ["symbol", "start", "end", "category", "source_url", "evidence_path"]


@dataclass(frozen=True)
class CoverageReview:
    """One actually reviewed category and interval; never infer from legacy rows.

    The evidence file should retain the reviewed official source references,
    hashes, relevant events and limitations. This type authenticates reviewed
    bytes, not the truth of an arbitrary reviewer's claim or historical timing.
    """

    symbol: str
    start: str
    end: str
    category: str
    source_url: str
    evidence_file: Path
    sha256: str
    reviewed_at: str
    review_note: str

    def record(self) -> dict:
        for value in (self.start, self.end):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("coverage dates must be canonical ISO dates")
        if self.end < self.start:
            raise ValueError("coverage interval is reversed")
        stamp = datetime.fromisoformat(self.reviewed_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("coverage review time requires a timezone")
        if not re.fullmatch(r"\d{4,6}\.TW", self.symbol):
            raise ValueError("coverage symbol must be canonical TWSE identity")
        if self.category not in COVERAGE_CATEGORIES or not _official_url(self.source_url):
            raise ValueError("coverage requires an explicit category and official source URL")
        if not self.review_note.strip():
            raise ValueError("coverage requires an explicit review note")
        path = Path(self.evidence_file)
        if path.is_symlink() or not path.is_file():
            raise ValueError("coverage evidence must be a regular file")
        suffix = path.suffix.lower()
        if suffix not in {".json", ".txt", ".html", ".pdf"}:
            raise ValueError("unsupported coverage evidence format")
        raw = path.read_bytes()
        if not raw or hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError("coverage evidence hash differs from reviewed bytes")
        return {"symbol": self.symbol, "start": self.start, "end": self.end,
                "category": self.category, "source_url": self.source_url,
                "evidence_path": f"evidence/coverage_{self.sha256}{suffix}",
                "sha256": self.sha256, "reviewed_at": self.reviewed_at,
                "review_note": self.review_note}


def derive_coverage_bundle(directory: str | Path, parent: str | Path,
                           reviews: tuple[CoverageReview, ...]) -> Path:
    """Append only explicit reviews to a content-addressed new bundle.

    Parent files, legacy coverage and existing reviews remain unchanged. The
    normalizer still checks event support and every other coverage category.
    """
    if Path(directory).is_symlink():
        raise ValueError("coverage source must not be symlinked")
    source, destination_parent = Path(directory).resolve(), Path(parent).resolve()
    if source == destination_parent or source in destination_parent.parents:
        raise ValueError("derived destination must be outside the original bundle")
    if not reviews or not (source / "manifest.json").is_file():
        raise ValueError("derivation requires a source manifest and explicit reviews")
    items = sorted(((item, item.record()) for item in reviews),
                   key=lambda pair: (pair[1]["symbol"], pair[1]["category"], pair[1]["start"], pair[1]["end"]))
    records = [record for _, record in items]
    keys = [(r["symbol"], r["category"], r["start"], r["end"]) for r in records]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate coverage review interval")
    baseline = _inventory(source)
    payload = {"schema_version": 1, "operation": "append_explicit_category_coverage",
               "base_files": baseline, "reviews": records}
    amendment_id = fingerprint(payload)
    destination = destination_parent / amendment_id[:24]
    destination_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".coverage-", dir=destination_parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for name in baseline:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        if _inventory(staging) != baseline or _inventory(source) != baseline:
            raise ValueError("source bundle changed during coverage derivation")
        registry = staging / "coverage_reviews.csv"
        previous = staging / "amendments" / amendment_id
        previous.mkdir(parents=True)
        rows = []
        saved = [previous / "previous_manifest.json"]
        shutil.copyfile(staging / "manifest.json", saved[0])
        if registry.exists():
            with registry.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != FIELDS:
                    raise ValueError("unexpected category coverage registry schema")
                rows = list(reader)
            saved.append(previous / "previous_coverage_reviews.csv")
            shutil.copyfile(registry, saved[-1])
        else:
            saved.append(previous / "previous_coverage_absent.json")
            saved[-1].write_text('{"coverage_reviews.csv":"absent"}\n')
        for item, record in items:
            key = tuple(record[name] for name in ("symbol", "category", "start", "end"))
            matching = [r for r in rows if tuple(r[name] for name in (
                "symbol", "category", "start", "end")) == key]
            row = {name: record[name] for name in FIELDS}
            if matching and matching != [row]:
                raise ValueError("coverage review conflicts with an existing interval")
            raw = item.evidence_file.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise ValueError("coverage evidence changed during derivation")
            target = staging / record["evidence_path"]
            if target.exists() and target.read_bytes() != raw:
                raise ValueError("coverage evidence path conflicts with existing bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            if not matching:
                rows.append(row)
        with registry.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        saved.append(previous / "review.json")
        saved[-1].write_text(json.dumps({"amendment_id": amendment_id, **payload},
                                      sort_keys=True, indent=2), encoding="utf-8")
        manifest_path = staging / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("amendment_records", []).extend(
            {"path": p.relative_to(staging).as_posix(),
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in saved)
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        if _inventory(source) != baseline:
            raise ValueError("source bundle changed before coverage publication")
        if destination.is_symlink():
            raise ValueError("existing derived bundle must not be symlinked")
        if destination.exists():
            if _inventory(destination) != _inventory(staging):
                raise ValueError("existing derived bundle has changed; preserve it")
            return destination
        os.rename(staging, destination)
    return destination
