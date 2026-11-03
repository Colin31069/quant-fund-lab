"""Prepare reviewed provider inputs through shared event and calendar rules."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..twse_calendar import official_calendar
from ..twse_odd_lot import TWSEInput, TWSEIssue, prepare_twse_odd_lot
from ..twse_quality.legacy import legacy_findings
from ..twse_quality.readiness import assess_study_readiness
from ..twse_quality.types import ReadinessFinding, StudyReadiness, fingerprint
from .finmind import load_finmind_price_bundle
from .selection import select_prices
from .twse import load_twse_price_observations
from .types import PriceSelection, PriceSourcePolicy


@dataclass(frozen=True)
class PreparedOddLotInput:
    evidence: TWSEInput
    selection: PriceSelection
    official_context: tuple[ReadinessFinding, ...]

    def assess(self, periods: dict[str, tuple[str, str]], *, warmup: int = 120) -> StudyReadiness:
        first = min(self.selection.policy.start, min(v[0] for v in periods.values()))
        last = max(v[1] for v in periods.values())
        return assess_study_readiness(
            self.evidence, periods, calendar=official_calendar(self.evidence, first, last),
            warmup=warmup, policy_id=self.selection.policy.policy_id,
            context_findings=self.official_context,
        )


def prepare_reviewed_odd_lot_input(
    official_directory: str | Path, provider_directory: str | Path,
    symbols: list[str], policy: PriceSourcePolicy,
) -> PreparedOddLotInput:
    """Read originals without modifying them; the provider never becomes an official source."""
    root = Path(official_directory)
    provider = load_finmind_price_bundle(provider_directory)
    original_rows = load_twse_price_observations(root)
    selection = select_prices(original_rows + provider.observations, policy)
    context = ()
    try:
        original = prepare_twse_odd_lot(root, symbols, policy.start, policy.end)
        context = original.issues
    except ValueError as exc:
        if "指定期間沒有任何官方價量資料" not in str(exc):
            raise
        # An official-only interval may be entirely missing while provider rows exist.
        context = (TWSEIssue(policy.start, policy.end, "*",
                             "原官方來源在指定期間沒有價量，無法建立逐日判定"),)
    prepared = prepare_twse_odd_lot(root, symbols, policy.start, policy.end,
                                    _price_selection=selection)
    files = dict(prepared.source_files)
    for name, path in provider.source_files:
        key = "provider/" + name
        if key in files:
            raise ValueError("provider archive namespace conflicts with official evidence")
        files[key] = path
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}
    provenance = {**prepared.provenance, "provider_namespace": "provider",
                  "source_policy_json": json.dumps(asdict(policy), sort_keys=True),
                  "provider_bundle_fingerprint": provider.bundle_fingerprint,
                  "source_manifest_sha256": fingerprint(hashes)}
    prepared = replace(prepared, source_files=files, source_hashes=hashes, provenance=provenance)
    findings = tuple(replace(f, blocking=False, applicability_reason=(
        "保留原官方來源判定；本政策以選源後共用事件／日曆規則的重新核對結果守門"
    )) for f in legacy_findings(context, ("manifest.json",)))
    return PreparedOddLotInput(prepared, selection, findings)
