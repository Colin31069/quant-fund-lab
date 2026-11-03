"""Read-only period assessment using expected sessions rather than observed rows."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import fields

import numpy as np
import pandas as pd

from ..market_calendar import CalendarSessions
from ..twse_odd_lot import TWSEInput
from .legacy import legacy_findings
from .types import (
    FindingCode,
    PeriodReadiness,
    ReadinessFinding,
    ReadinessStatus,
    StudyReadiness,
    WarmupEvidence,
    fingerprint,
)


def _verify_sources(inputs: TWSEInput) -> None:
    if not inputs.source_files or set(inputs.source_files) != set(inputs.source_hashes):
        raise ValueError("readiness requires a complete source inventory")
    for name, path in inputs.source_files.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != inputs.source_hashes[name]:
            raise ValueError(f"readiness source integrity failure: {name}")


def _suspensions(inputs: TWSEInput) -> set[tuple[str, str]]:
    path = inputs.source_files.get("suspensions.csv")
    result = set()
    if path is None:
        return result
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"date", "symbol", "source_url", "evidence_path"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("invalid suspension evidence schema")
        for row in reader:
            if row["evidence_path"] not in inputs.source_hashes:
                raise ValueError("suspension evidence is absent from verified sources")
            result.add((row["date"], row["symbol"]))
    return result


def _data_identity(inputs: TWSEInput) -> dict:
    result = {}
    for field in fields(inputs.data):
        value = getattr(inputs.data, field.name)
        if isinstance(value, pd.DataFrame):
            hashed = pd.util.hash_pandas_object(value, index=True).values.tobytes()
            result[field.name] = {"columns": list(value.columns),
                                  "hash": hashlib.sha256(hashed).hexdigest()}
        else:
            result[field.name] = value
    return result


def assess_study_readiness(
    inputs: TWSEInput,
    periods: dict[str, tuple[str, str]],
    *,
    calendar: CalendarSessions | None,
    warmup: int = 120,
    required_symbols: tuple[str, ...] | None = None,
    policy_id: str = "twse_official",
    context_findings: tuple[ReadinessFinding, ...] = (),
) -> StudyReadiness:
    """Assess all supplied symbols, including the benchmark, without mutating inputs.

    The caller supplies the evidence-reviewed effective calendar, including official
    closures. Absent calendar evidence gives unknown, never an inferred ready result.
    Period ends must be explicit so missing trailing observations cannot shrink a study.
    """
    _verify_sources(inputs)
    if type(warmup) is not int or warmup < 1 or not periods:
        raise ValueError("readiness requires positive warmup and explicit periods")
    required = max(120, warmup)
    data = inputs.data
    if data.close.index.has_duplicates or not data.close.index.is_monotonic_increasing:
        raise ValueError("readiness dates must be unique and chronological")
    refs = tuple(sorted(inputs.source_hashes))
    issue_refs = tuple(name for name in ("manifest.json", "actions.csv", "coverage_reviews.csv",
                                        "suspensions.csv") if name in inputs.source_hashes)
    if any(f.blocking for f in context_findings):
        raise ValueError("context findings must explicitly declare nonblocking applicability")
    original = legacy_findings(inputs.issues, issue_refs, policy_id=policy_id)
    findings = {f.finding_id: f for f in original}
    for finding in context_findings:
        if finding.finding_id in findings:
            raise ValueError("context cannot replace an active finding")
        findings[finding.finding_id] = finding
    suspensions = _suspensions(inputs)
    expected = pd.DatetimeIndex(calendar.sessions if calendar else [])
    if expected.has_duplicates or not expected.is_monotonic_increasing:
        raise ValueError("expected sessions must be unique and chronological")
    decisions = []
    for name, (start, end) in sorted(periods.items(), key=lambda item: (item[1][0], item[0])):
        first, last = pd.Timestamp(start), pd.Timestamp(end)
        if not start or not end or pd.isna(first) or pd.isna(last) or first > last:
            raise ValueError("readiness periods must have explicit ordered boundaries")
        before = expected[expected < first][-required:]
        during = expected[(expected >= first) & (expected <= last)]
        window = before.append(during)
        window_start = str(before[0].date()) if len(before) else start
        blockers = {f.finding_id for f in original if f.start <= end and f.end >= window_start}

        def add(code: FindingCode, symbol: str, a: str, b: str, detail: str,
                target: set[str] = blockers, dependencies: tuple[str, ...] = ()) -> None:
            finding = ReadinessFinding(code, symbol, a, b, detail, source_refs=issue_refs,
                                       depends_on=dependencies, policy_id=policy_id)
            findings[finding.finding_id] = finding
            target.add(finding.finding_id)

        if calendar is None:
            add(FindingCode.UNKNOWN, "*", start, end, "缺少已核對的交易日曆")
        elif (calendar.market != "TW" or not calendar.revision or not calendar.coverage_start
              or not calendar.coverage_end or calendar.coverage_start > start
              or calendar.coverage_end < end):
            add(FindingCode.UNKNOWN, "*", start, end, "日曆涵蓋範圍或市場無法證明")
        elif not len(during):
            add(FindingCode.CALENDAR, "*", start, end, "研究期間沒有可驗證交易日")
        for symbol in sorted(set(required_symbols or data.symbols) - set(data.symbols)):
            add(FindingCode.MISSING_SYMBOL, symbol, window_start, end, "缺少必要標的或基準")
        if calendar is not None:
            extra = data.close.index.difference(expected)
            for day in extra[(extra >= pd.Timestamp(window_start)) & (extra <= last)]:
                text = str(day.date())
                add(FindingCode.CALENDAR, "*", text, text, "行情包含非預期交易日")
        verified = []
        for day in window:
            text = str(day.date())
            complete = True
            for symbol in data.symbols:
                present = day in data.close.index
                close = data.raw_close.at[day, symbol] if present else np.nan
                opening = data.raw_open.at[day, symbol] if present else np.nan
                volume = data.volume.at[day, symbol] if present else np.nan
                valuation = data.close.at[day, symbol] if present else np.nan
                dividend = data.dividends.at[day, symbol] if present else np.nan
                split = data.stock_splits.at[day, symbol] if present else np.nan
                valid_state = (np.isfinite(valuation) and valuation > 0
                               and np.isfinite(dividend) and dividend >= 0
                               and np.isfinite(split) and split >= 0)
                quoted = (np.isfinite(close) and close > 0 and np.isfinite(opening)
                          and opening > 0 and np.isfinite(volume) and volume > 0)
                suspended = ((text, symbol) in suspensions and np.isfinite(close)
                             and close > 0 and pd.isna(opening) and volume == 0)
                if not valid_state or (not quoted and not suspended):
                    complete = False
                    if not quoted and not suspended:
                        add(FindingCode.MISSING_SESSION, symbol, text, text,
                            "缺少可驗證行情或有來源的停牌估值")
                    else:
                        dependencies = tuple(sorted(f.finding_id for f in original
                            if f.symbol in {symbol, "*"} and f.start <= text
                            and f.code in {FindingCode.EVENT_CONFLICT, FindingCode.UNSUPPORTED_EVENT}))
                        add(FindingCode.DERIVED_STATE, symbol, text, text,
                            "行情存在，但總報酬估值或企業行動狀態無效；需核對事件與轉換",
                            dependencies=dependencies)
            if complete and day < first:
                verified.append(text)
        evidence = WarmupEvidence(calendar.revision if calendar else "unknown", required,
                                  tuple(str(d.date()) for d in before), tuple(verified), refs)
        if not evidence.complete:
            add(FindingCode.WARMUP, "*", window_start, start, "完整暖機交易日不足")
        unknown = any(findings[key].code == FindingCode.UNKNOWN for key in blockers)
        status = (ReadinessStatus.UNKNOWN if unknown else ReadinessStatus.BLOCKED) if blockers else ReadinessStatus.READY
        decisions.append(PeriodReadiness(name, start, end, status, evidence, tuple(sorted(blockers))))
    identity = fingerprint({"sources": inputs.source_hashes, "provenance": inputs.provenance,
                            "issues": [f.to_dict() for f in original],
                            "policy_id": policy_id,
                            "context_findings": [f.to_dict() for f in context_findings],
                            "required_symbols": sorted(required_symbols or data.symbols),
                            "data": _data_identity(inputs), "periods": periods,
                            "warmup": required, "calendar": {
                                "revision": calendar.revision,
                                "coverage": [calendar.coverage_start, calendar.coverage_end],
                                "sessions": [str(d.date()) for d in calendar.sessions],
                            } if calendar else None})
    return StudyReadiness(identity, tuple(findings[key] for key in sorted(findings)),
                          tuple(decisions), ("固定股票池；成交及交割使用代理模型",))
