"""Rebuild new-session inputs and reject gaps or inconsistent acquisition records.

Manifest timestamps are preserved acquisition records, not trusted timestamping
attestations. This gate does not authenticate a plan's decision or open an account.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from ..odd_lot_inputs.prepare import prepare_reviewed_odd_lot_input
from ..odd_lot_inputs.twse import load_twse_price_observations
from ..odd_lot_inputs.types import PriceSourcePolicy, PriceSourceRef
from ..twse_calendar import official_calendar
from ..twse_odd_lot import prepare_twse_odd_lot
from ..twse_quality.readiness import assess_study_readiness
from .observation import ObservationPlan
from .observation_evidence import ForwardSessionAssessment, SessionEvidence


def _now() -> datetime:
    return datetime.now(timezone.utc)


def assess_forward_session(plan: ObservationPlan, session: str, *,
                           official_directory: str | Path, symbols: tuple[str, ...],
                           benchmark: str, provider_directory: str | Path | None = None,
                           price_policy: PriceSourcePolicy | None = None) -> ForwardSessionAssessment:
    """Assess the full planned prefix, including all required warmup and benchmark.

    The requested first date must itself be an official session. A source-valid
    but incomplete period returns blocked; corrupt source bytes raise ValueError.
    No snapshot, ledger or plan is modified. Activation must authenticate the plan
    and recheck this result inside its own transaction boundary.
    """
    if date.fromisoformat(session).isoformat() != session or session < plan.first_session:
        raise ValueError("forward cutoff must be canonical and at/after the planned first session")
    if not symbols or len(set(symbols)) != len(symbols) or benchmark in symbols:
        raise ValueError("forward inputs require unique trading symbols and separate benchmark")
    required = (*symbols, benchmark)
    checked = _now()
    first = plan.first_session
    periods = {"forward_observation": (first, session)}
    warmup = json.loads(plan.execution_config_json).get("strategy", {}).get("warmup_days", 120)
    reviewed = None
    if provider_directory is not None:
        if price_policy is None or price_policy.start >= first or price_policy.end < session:
            raise ValueError("reviewed forward input requires an explicit policy covering warmup and cutoff")
        start = price_policy.start
        reviewed = prepare_reviewed_odd_lot_input(official_directory, provider_directory, list(required), price_policy)
        original = reviewed.evidence
        # An archive/policy may include newer rows. The execution boundary is
        # still the requested cutoff, never the end of the downloaded file.
        data = replace(original.data, **{field.name: getattr(original.data, field.name).loc[:session].copy()
            for field in fields(original.data) if isinstance(getattr(original.data, field.name), pd.DataFrame)})
        inputs = replace(original, data=data)
        reviewed = replace(reviewed, evidence=inputs)
        readiness = reviewed.assess(periods, warmup=warmup)
        observations = reviewed.selection.selected
    else:
        if price_policy is not None:
            raise ValueError("provider policy requires a provider directory")
        # Restrict reconstruction to the actual supplied archive coverage; a
        # missing prior annual calendar still leaves warmup/readiness blocked.
        manifest = json.loads((Path(official_directory) / "manifest.json").read_text())
        months = [entry["month"] for entry in manifest["sources"] if entry["kind"] == "price"]
        if not months:
            raise ValueError("forward source bundle contains no price evidence")
        start = min(months) + "-01"
        inputs = prepare_twse_odd_lot(official_directory, list(required), start, session)
        calendar = official_calendar(inputs, start, session)
        readiness = assess_study_readiness(inputs, periods, calendar=calendar,
            warmup=warmup, required_symbols=required)
        observations = load_twse_price_observations(inputs)
    calendar = official_calendar(inputs, min(start, str(inputs.data.close.index[0].date())), session)
    reasons = []
    if session > checked.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat():
        reasons.append("session_is_still_future")
    if readiness.periods[0].status.value != "ready":
        reasons.append("readiness_" + readiness.periods[0].status.value)
    expected = [str(day.date()) for day in calendar.sessions if first <= str(day.date()) <= session] if calendar else []
    if not expected or expected[0] != first or expected[-1] != session:
        reasons.append("requested_boundaries_are_not_verified_sessions")
    selected = {(row.date, row.symbol): row.source for row in observations}
    manifest = json.loads(inputs.source_files["manifest.json"].read_text())
    monthly = {(entry["symbol"], entry["month"]): entry for entry in manifest["sources"]
               if entry["kind"] == "price"}
    acquisitions = []
    registered = datetime.fromisoformat(plan.recorded_at)
    closes = {day: xcals.get_calendar(calendar.calendar).session_close(day).to_pydatetime()
              for day in expected} if calendar else {}
    for day in expected:
        for symbol in required:
            source = selected.get((day, symbol))
            # Official suspension valuation can carry the previous close even
            # when the monthly file has no quote row. Readiness verifies the halt.
            if source is None:
                entry = monthly.get((symbol, day[:7]))
                if entry is not None:
                    source = PriceSourceRef("TWSE", "STOCK_DAY", entry["url"], entry["retrieved_at"],
                        entry["path"], entry["sha256"], "Official suspension price context", (entry["url"],))
            if source is None:
                reasons.append(f"acquisition_missing:{day}:{symbol}")
                continue
            acquired = datetime.fromisoformat(source.retrieved_at.replace("Z", "+00:00"))
            if (acquired <= registered or acquired > checked or acquired < closes[day]):
                reasons.append(f"acquisition_time_invalid:{day}:{symbol}")
            acquisitions.append((day, symbol, source.source_id, source.retrieved_at))
    # All source files, not just prices, remain hash-bound after reconstruction.
    for name, path in inputs.source_files.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != inputs.source_hashes[name]:
            raise ValueError("forward source changed during assessment: " + name)
    if reasons:
        return ForwardSessionAssessment("blocked", tuple(sorted(set(reasons))), inputs, readiness, None)
    evidence = SessionEvidence(plan.plan_id, first, session, checked.isoformat(), calendar.revision,
        readiness.readiness_fingerprint, tuple(sorted(inputs.source_hashes.items())), tuple(acquisitions))
    return ForwardSessionAssessment("ready", (), inputs, readiness, evidence)
