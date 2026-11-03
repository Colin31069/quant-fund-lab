"""Deterministic source choice; conflicts remain explicit and never become fills."""
from __future__ import annotations

import itertools
import math
from collections import defaultdict

from .types import PriceConflict, PriceObservation, PriceSelection, PriceSourcePolicy


def select_prices(observations: tuple[PriceObservation, ...],
                  policy: PriceSourcePolicy) -> PriceSelection:
    """Select per symbol/date under a frozen priority, with no averaging or silent overwrite."""
    groups = defaultdict(list)
    seen, source_ids = set(), set()
    for row in observations:
        if row.source.provider not in policy.priority or not policy.start <= row.date <= policy.end:
            continue
        key = (row.symbol, row.date, row.source.source_id)
        if key in seen:
            raise ValueError("duplicate provider/source observation")
        seen.add(key)
        source_ids.add(row.source.source_id)
        groups[(row.symbol, row.date)].append(row)
    selected, conflicts = [], []
    for (symbol, day), rows in sorted(groups.items()):
        differences = set()
        for left, right in itertools.combinations(rows, 2):
            if left.no_quote != right.no_quote:
                differences.add("no_quote")
            for field in ("raw_open", "raw_high", "raw_low", "raw_close", "volume_shares"):
                a, b = getattr(left, field), getattr(right, field)
                if a is None or b is None:
                    continue
                tolerance = 0 if field == "volume_shares" else policy.price_atol
                if not math.isclose(a, b, rel_tol=0, abs_tol=tolerance):
                    differences.add(field)
        if differences:
            conflicts.append(PriceConflict(symbol, day, tuple(sorted(r.source.source_id for r in rows)),
                                           tuple(sorted(differences))))
            continue
        selected.append(min(rows, key=lambda r: (policy.priority.index(r.source.provider),
                                                 r.source.source_id)))
    return PriceSelection(policy, tuple(selected), tuple(conflicts), tuple(sorted(source_ids)))


def price_selection_records(selection: PriceSelection) -> list[dict]:
    """Export selected and conflicting keys with policy identity and original row linkage."""
    policy_id = selection.policy.policy_fingerprint
    result = [{"symbol": r.symbol, "date": r.date, "status": "selected",
               "provider": r.source.provider, "source_id": r.source.source_id,
               "raw_path": r.source.raw_path, "sha256": r.source.sha256,
               "row_locator": r.row_locator, "source_url": r.source.source_url,
               "retrieved_at": r.source.retrieved_at, "no_quote": r.no_quote,
               "policy_fingerprint": policy_id, "conflict_fields": ""}
              for r in selection.selected]
    result.extend({"symbol": c.symbol, "date": c.date, "status": "conflict", "provider": "",
                   "source_id": ",".join(c.source_ids), "raw_path": "", "sha256": "",
                   "row_locator": "", "source_url": "", "retrieved_at": "", "no_quote": "",
                   "policy_fingerprint": policy_id, "conflict_fields": ",".join(c.fields)}
                  for c in selection.conflicts)
    return sorted(result, key=lambda row: (row["symbol"], row["date"]))
