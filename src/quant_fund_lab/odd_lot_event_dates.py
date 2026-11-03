"""Explicit, evidenced cash-dividend date resolutions for market-wide closures."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .market_calendar import expected_market_sessions
from .twse_calendar import official_closure_evidence

RULE_ID = "twse_disaster_cash_dividend_v1"
RULE_URL = "https://www.twse.com.tw/zh/about/suspended_faq.html"


@dataclass(frozen=True)
class CashDividendDateReview:
    """A reviewed date mapping, retaining the scheduled official event identity."""

    symbol: str
    scheduled_date: str
    effective_date: str
    cash_dividend: float
    rule_id: str
    rule_source_url: str
    rule_evidence_path: str
    rule_sha256: str
    event_source_url: str
    event_evidence_path: str
    event_sha256: str
    review_note: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4,6}\.TW", self.symbol):
            raise ValueError("date review requires a canonical TW symbol")
        for day in (self.scheduled_date, self.effective_date):
            if str(pd.Timestamp(day).date()) != day or day == "NaT":
                raise ValueError("date review requires canonical dates")
        if self.effective_date <= self.scheduled_date:
            raise ValueError("date resolution must follow its scheduled date")
        if (not math.isfinite(self.cash_dividend) or self.cash_dividend <= 0
                or self.rule_id != RULE_ID or self.rule_source_url != RULE_URL
                or not self.review_note.strip()):
            raise ValueError("date resolution requires the supported cash-dividend rule and review")
        for digest in (self.rule_sha256, self.event_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("date resolution requires evidence SHA-256")
        for name in (self.rule_evidence_path, self.event_evidence_path):
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or path.as_posix() != name):
                raise ValueError("date review evidence paths must be canonical and relative")


def resolve_cash_dividend_dates(
    root: Path, source_files: dict[str, Path],
    actions: dict, indexed_details: dict, unsupported_events: set,
    start: str, end: str,
) -> dict[tuple[pd.Timestamp, str], tuple[pd.Timestamp, str]]:
    """Verify all reviews before returning mappings; raw event files stay unchanged.

    The optional registry is bound to the source inventory. No registry means no
    behavior change for existing archives. This does not support subscriptions,
    stock distributions, payments or rights valuation.
    """
    from .twse_odd_lot import _official_url, _safe_file

    name = "action_date_reviews.csv"
    if not (root / name).exists():
        return {}
    registry = _safe_file(root, name)
    with registry.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if (len(reader.fieldnames or ()) != len(CashDividendDateReview.__dataclass_fields__)
                or set(reader.fieldnames or ()) != set(CashDividendDateReview.__dataclass_fields__)):
            raise ValueError("unexpected cash-dividend date review schema")
        reviews = [CashDividendDateReview(**{**row, "cash_dividend": float(row["cash_dividend"])})
                   for row in reader]
    additions = {name: registry}
    manifest = json.loads(source_files["manifest.json"].read_text(encoding="utf-8"))
    declared = {e["path"]: e for e in manifest["sources"] if e["kind"] == "ex_right_index"}
    seen, destinations = set(), set()
    relevant = []
    for review in reviews:
        old = (pd.Timestamp(review.scheduled_date), review.symbol)
        new = (pd.Timestamp(review.effective_date), review.symbol)
        if old in seen or new in destinations:
            raise ValueError("duplicate cash-dividend date review or destination")
        seen.add(old)
        destinations.add(new)
        event = declared.get(review.event_evidence_path)
        if (not _official_url(review.event_source_url) or event is None
                or event["url"] != review.event_source_url or event["sha256"] != review.event_sha256):
            raise ValueError("reviewed event must reference its declared official index")
        for path, digest in [(review.rule_evidence_path, review.rule_sha256),
                             (review.event_evidence_path, review.event_sha256)]:
            if path == review.rule_evidence_path and not path.startswith("evidence/"):
                raise ValueError("rule evidence must be inside evidence directory")
            target = _safe_file(root, path)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("cash-dividend review evidence hash differs")
            additions[path] = target
        if start <= review.scheduled_date <= end or start <= review.effective_date <= end:
            relevant.append((review, old, new))
    # Work on a copy until every source and mapping has passed validation.
    files = {**source_files, **additions}
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    closures = official_closure_evidence(files, hashes, start, end)
    if closures is None:
        raise ValueError("date resolution requires complete official calendar coverage")
    sessions = expected_market_sessions("TW", start, end, closures=closures).sessions
    mapping = {}
    for review, old, new in relevant:
        following = next((day for day in sessions if day > old[0]), None)
        if old[0] not in closures.sessions or new[0] != following:
            raise ValueError("reviewed date must follow an evidenced market closure to its next session")
        if old not in actions or old not in indexed_details or old in unsupported_events:
            raise ValueError("date resolution requires a supported indexed cash dividend")
        ratio, dividend = actions[old]
        _, _, category, official_dividend = indexed_details[old]
        if (ratio != 1 or category != "息" or abs(dividend - review.cash_dividend) > 1e-8
                or abs(official_dividend - review.cash_dividend) > 1e-8):
            raise ValueError("reviewed cash dividend differs from original event")
        if new in actions or new in indexed_details:
            raise ValueError("resolved cash dividend conflicts with an existing effective event")
        mapping[old] = new
    source_files.update(additions)
    return mapping
