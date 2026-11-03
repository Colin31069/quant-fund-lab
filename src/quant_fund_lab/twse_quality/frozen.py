"""Bind a frozen study to the same readiness decision used before execution."""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from ..data import MarketData
from ..odd_lot_inputs.prepare import PreparedOddLotInput, prepare_reviewed_odd_lot_input
from ..odd_lot_inputs.types import PriceSourcePolicy
from ..twse_calendar import official_calendar
from ..twse_odd_lot import prepare_twse_odd_lot
from .readiness import _data_identity, assess_study_readiness
from .types import READINESS_RULE_VERSION, StudyReadiness, fingerprint


def reconstruct_reviewed_inputs(metadata: dict, root: Path) -> PreparedOddLotInput:
    """Rebuild the provider selection from archived raw bytes and its frozen policy."""
    policy = PriceSourcePolicy(**json.loads(metadata["source_provenance"]["source_policy_json"]))
    return prepare_reviewed_odd_lot_input(root / "sources", root / "sources" / "provider",
                metadata["symbols"] + [metadata["benchmark"]], policy)


def assess_frozen_inputs(data: MarketData, metadata: dict, root: Path) -> StudyReadiness:
    """Reconstruct verified evidence from an immutable study staging/archive directory."""
    hashes = metadata["source_files"]
    provenance = metadata["source_provenance"]
    reviewed = None
    if metadata["data_source"] == "provider_reviewed":
        reviewed = reconstruct_reviewed_inputs(metadata, root)
        inputs = reviewed.evidence
    else:
        inputs = prepare_twse_odd_lot(
            root / "sources", metadata["symbols"] + [metadata["benchmark"]],
            provenance["coverage_start"], provenance["coverage_end"],
        )
    if inputs.source_hashes != hashes:
        raise ValueError("frozen source inventory differs from prepared evidence")
    if fingerprint([asdict(v) for v in inputs.issues]) != fingerprint(metadata["quality_issues"]):
        raise ValueError("frozen quality findings differ from original sources")
    # A source hash alone does not prove the normalized prices were derived from it.
    if fingerprint(_data_identity(inputs)) != fingerprint(_data_identity(
            replace(inputs, data=data))):
        raise ValueError("frozen normalized data differs from original sources")
    periods = metadata["periods"]
    if reviewed is not None:
        return reviewed.assess(periods, warmup=metadata["backtest_config"]["strategy"]["warmup_days"])
    first = min(str(data.close.index.min().date()), min(v[0] for v in periods.values()))
    last = max(v[1] for v in periods.values())
    calendar = official_calendar(inputs, first, last)
    return assess_study_readiness(
        inputs, periods, calendar=calendar,
        warmup=metadata["backtest_config"]["strategy"]["warmup_days"],
        required_symbols=tuple(metadata["symbols"] + [metadata["benchmark"]]),
    )


def validate_frozen_readiness(data: MarketData, metadata: dict, root: Path) -> None:
    """Reject changed decisions or calendar revisions without rewriting old studies."""
    if metadata.get("schema_version") != 3:
        return
    actual = assess_frozen_inputs(data, metadata, root)
    if fingerprint(metadata["readiness"]) != metadata["readiness_fingerprint"]:
        raise ValueError("frozen readiness fingerprint differs from archived decision")
    rule = metadata["readiness"]["rule_version"]
    if rule == "readiness-v1":
        # Preserve archival integrity without claiming an old decision used new rules.
        return
    if rule != READINESS_RULE_VERSION:
        raise ValueError("unsupported frozen readiness rule version")
    if (actual.readiness_fingerprint != metadata["readiness_fingerprint"]
            or fingerprint(actual.to_dict()) != fingerprint(metadata["readiness"])):
        raise ValueError("frozen readiness differs from verified inputs or calendar revision")


def explicit_periods(periods: dict, coverage_end: str) -> dict[str, tuple[str, str]]:
    """Freeze an open end to the requested cutoff; empty future periods stay blocked."""
    return {name: (start, end or str(max(pd.Timestamp(start), pd.Timestamp(coverage_end)).date()))
            for name, (start, end) in periods.items()}
