"""Reviewed official full-day closures missing from older calendar providers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class OfficialClosureCorrection:
    """Announcement identity; the review digest is not a hash of the source HTML."""

    market: str
    calendar: str
    session: str
    published_on: str
    source_url: str
    review_note: str


# Verified against the issuer's December 30 announcement. Direct HTML archival
# returned HTTP 403; the review and access limitation are preserved in P0 evidence.
OFFICIAL_CLOSURE_CORRECTIONS = (
    OfficialClosureCorrection(
        "US", "XNYS", "2025-01-09", "2024-12-30",
        "https://ir.theice.com/press/news-details/2024/"
        "The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-"
        "Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx",
        "NYSE Group equity and options markets closed for the national day of mourning.",
    ),
)


def apply_official_closure_corrections(
    market: str, calendar: str, sessions: pd.DatetimeIndex,
) -> tuple[pd.DatetimeIndex, str]:
    """Remove only evidenced open dates; an already-correct provider keeps its identity.

    This is an ex-post session validation correction, not a signal announcing a
    future closure. Announcement time and market effective day remain distinct.
    """
    applied = [record for record in OFFICIAL_CLOSURE_CORRECTIONS
               if record.market == market and record.calendar == calendar
               and pd.Timestamp(record.session) in sessions]
    if not applied:
        return sessions, ""
    raw = json.dumps([asdict(r) for r in applied], sort_keys=True,
                     separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    dates = pd.DatetimeIndex([r.session for r in applied])
    return sessions.difference(dates), f";official-closures-v1:{digest}"
