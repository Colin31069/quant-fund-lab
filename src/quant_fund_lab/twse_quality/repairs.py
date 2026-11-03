"""Derived repair counts preserve the frozen readiness decision and source keys."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .types import FindingCode

REPAIR_SUMMARY_RULE = "period_repairs_v1"


@dataclass(frozen=True)
class PeriodRepairSummary:
    """A source month can be needed by both windows; these counts are not additive.

    Missing expected calendar evidence leaves the warmup-month window unknown.
    Shortfall counts required but unverified sessions, not asserted missing prices.
    """

    period: str
    start: str
    end: str
    period_month_keys: tuple[tuple[str, str], ...]
    warmup_month_keys: tuple[tuple[str, str], ...] | None
    warmup_required: int
    warmup_verified: int
    warmup_expected: int | None
    warmup_unverified: int | None

    def to_record(self) -> dict:
        return {"period": self.period, "start": self.start, "end": self.end,
                "period_missing_months": len(self.period_month_keys),
                "warmup_missing_months": (len(self.warmup_month_keys)
                                          if self.warmup_month_keys is not None else None),
                "warmup_required": self.warmup_required, "warmup_verified": self.warmup_verified,
                "warmup_expected": self.warmup_expected, "warmup_unverified": self.warmup_unverified,
                "warmup_shortfall": max(0, self.warmup_required - self.warmup_verified),
                "period_source_keys": json.dumps(self.period_month_keys, ensure_ascii=False),
                "warmup_source_keys": json.dumps(self.warmup_month_keys, ensure_ascii=False)}


def _month_keys(active: list[dict], start: str, end: str) -> tuple[tuple[str, str], ...]:
    found = set()
    for finding in active:
        first, last = max(start, finding["start"]), min(end, finding["end"])
        if first <= last:
            found.update((finding["symbol"], str(month))
                         for month in pd.period_range(first, last, freq="M"))
    return tuple(sorted(found))


def period_repair_summaries(readiness: dict) -> tuple[PeriodRepairSummary, ...]:
    """Count only active missing-month findings; never infer or alter readiness.

    Keys are (symbol, month), independent of duplicate finding occurrences.
    Original intervals intersect each window before months are expanded, so a
    preceding month affects validation warmup without becoming a validation month.
    """
    findings = {row["finding_id"]: row for row in readiness["findings"]}
    result = []
    for period in readiness["periods"]:
        warmup = period["warmup"]
        expected = warmup.get("expected_sessions")
        verified = warmup["verified_sessions"]
        active = [findings[key] for key in period["blocking_ids"]
                  if findings[key]["code"] == FindingCode.MISSING_MONTH]

        warmup_keys = _month_keys(active, expected[0], expected[-1]) if expected else None
        result.append(PeriodRepairSummary(period["period"], period["start"], period["end"],
            _month_keys(active, period["start"], period["end"]), warmup_keys, warmup["required"], len(verified),
            len(expected) if expected is not None else None,
            len(set(expected) - set(verified)) if expected is not None else None))
    return tuple(result)


def repair_summary_frame(readiness: dict) -> pd.DataFrame:
    """The UI and exported CSV use the same immutable derived records."""
    return pd.DataFrame([row.to_record() for row in period_repair_summaries(readiness)])


def export_repair_summary(directory: Path, readiness: dict) -> str:
    """Write a presentation-only CSV and return its HTML, using frozen evidence."""
    frame = repair_summary_frame(readiness)
    frame.to_csv(directory / "readiness_repairs.csv", index=False)
    columns = ["period", "period_missing_months", "warmup_missing_months", "warmup_required",
               "warmup_verified", "warmup_unverified", "warmup_shortfall"]
    display = frame[columns].astype(object).where(frame[columns].notna(), "")
    return ("<h2>分期缺月與暖機依賴</h2>"
            "<p>期內與暖機的來源月份可重疊，計數不相加；空白為無法確認暖機窗口。</p>"
            + display.to_html(index=False))


def verify_repair_summary(directory: Path, metadata: dict, manifest: dict) -> bool:
    """Legacy reports stay readable; declared summaries must reconstruct exactly."""
    name = "readiness_repairs.csv"
    declared = manifest.get("repair_summary_rule")
    if declared is None and name not in manifest["files"] and not (directory / name).exists():
        return True
    if (declared != REPAIR_SUMMARY_RULE or metadata.get("schema_version") != 3
            or name not in manifest["files"]):
        return False
    try:
        expected = repair_summary_frame(metadata["readiness"]).to_csv(index=False).encode("utf-8")
        return (directory / name).read_bytes() == expected
    except (OSError, KeyError, ValueError, TypeError):
        return False
