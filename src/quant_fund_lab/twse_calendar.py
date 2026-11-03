"""Effective TWSE sessions backed by verified annual calendars and closures."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from .market_calendar import CalendarClosures, CalendarSessions, expected_market_sessions

if TYPE_CHECKING:
    from .twse_odd_lot import TWSEInput


def is_official_closure(name: str, explanation: str) -> bool:
    """Recognize explicit closure wording, including compensatory holidays."""
    return ("休市" in name or "無交易" in name or "放假" in explanation
            or "補假" in name or "補假" in explanation)


def official_calendar(inputs: TWSEInput, start: str, end: str) -> CalendarSessions | None:
    """Overlay verified TWSE closure evidence; absent annual coverage is unknown."""
    closures = official_closure_evidence(inputs.source_files, inputs.source_hashes, start, end)
    return (expected_market_sessions("TW", start, end, closures=closures)
            if closures is not None else None)


def official_closure_evidence(
    source_files: dict[str, Path], source_hashes: dict[str, str], start: str, end: str,
) -> CalendarClosures | None:
    """Verify source bytes and return the same evidence policy for all session consumers."""
    from .twse_odd_lot import _date, _field, _read_table

    for name, path in source_files.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_hashes.get(name):
            raise ValueError(f"calendar source integrity failure: {name}")
    manifest = source_files.get("manifest.json")
    if manifest is None:
        return None
    entries = json.loads(manifest.read_text(encoding="utf-8"))["sources"]
    annual = {int(e["year"]): e for e in entries if e["kind"] == "holiday_index"}
    years = set(range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1))
    if not years.issubset(annual):
        return None
    closures = set()
    evidence = {}
    for year in sorted(years):
        entry = annual[year]
        path = source_files.get(entry["path"])
        if path is None or source_hashes[entry["path"]] != entry["sha256"]:
            raise ValueError("annual calendar is absent from verified sources")
        fields, rows = _read_table(path)
        di, ni, ei = _field(fields, "日期"), _field(fields, "名稱"), _field(fields, "說明")
        for row in rows:
            day = _date(row[di])
            if day.year != year:
                raise ValueError("annual calendar date conflicts with year")
            if is_official_closure(str(row[ni]), str(row[ei])):
                closures.add(day)
        evidence[entry["path"]] = entry["sha256"]
    suspension = source_files.get("suspensions.csv")
    if suspension is not None:
        with suspension.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                if row["symbol"] == "*":
                    if row["evidence_path"] not in source_hashes:
                        raise ValueError("market closure lacks verified evidence")
                    closures.add(_date(row["date"]))
                    evidence[row["evidence_path"]] = source_hashes[row["evidence_path"]]
        evidence["suspensions.csv"] = source_hashes["suspensions.csv"]
    revision = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return CalendarClosures("TW", f"twse-closures-v1:{revision}", start, end,
                            tuple(sorted(closures)))
