"""Compare acquisition CSV and month claims to reconstructed raw observations."""
from __future__ import annotations

import csv
import math
from pathlib import Path

from .errors import PriceSourceError
from .types import PriceObservation, iso_day


def _verify_normalized_prices(path: Path, months: list,
                             observations: tuple[PriceObservation, ...]) -> None:
    """A matching CSV hash cannot substitute for agreement with original provider rows."""
    targets = {}
    if not isinstance(months, list) or not months:
        raise ValueError("normalized CSV requires explicit target month claims")
    for month in months:
        iso_day(month["month"] + "-01")
        key = (month["symbol"], month["month"])
        if key in targets:
            raise ValueError("duplicate target month")
        targets[key] = month
    expected = {(row.symbol, row.date): row for row in observations
                if (row.symbol, row.date[:7]) in targets}
    for key, month in targets.items():
        rows = [row for row in expected.values() if (row.symbol, row.date[:7]) == key]
        if (not rows or len(rows) != month["rows"] or min(r.date for r in rows) != month["first_date"]
                or max(r.date for r in rows) != month["last_date"]
                or any(r.source.raw_path != month["raw_path"]
                       or r.source.sha256 != month["sha256"] for r in rows)):
            raise ValueError("target-month claims differ from reconstructed raw data")
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"date", "symbol", "raw_open", "raw_high", "raw_low", "raw_close",
                    "volume_shares", "turnover_twd", "trades", "no_quote", "provider", "source_sha256"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("normalized CSV schema differs from price contract")
        for item in reader:
            try:
                key = (item["symbol"], item["date"])
                if key not in expected or key in seen:
                    raise ValueError("unexpected or duplicate normalized observation")
                seen.add(key)
                row = expected[key]
                if (item["provider"] != row.source.provider or item["source_sha256"] != row.source.sha256
                        or item["no_quote"] != str(row.no_quote)):
                    raise ValueError("normalized observation lineage/quote flag differs from raw source")
                for field in ("raw_open", "raw_high", "raw_low", "raw_close", "volume_shares",
                              "turnover_twd", "trades"):
                    value = float(item[field])
                    original = getattr(row, field)
                    if original is None and row.no_quote and field.startswith("raw_"):
                        original = 0
                    tolerance = 1e-8 if field.startswith("raw_") else 0
                    if original is None or not math.isfinite(value) or abs(value - original) > tolerance:
                        raise ValueError(f"normalized {field} differs from raw observation")
            except (ValueError, TypeError, KeyError) as exc:
                raise PriceSourceError(str(path), f"line[{reader.line_num}]", str(exc)) from exc
    if seen != set(expected):
        raise ValueError("normalized price CSV omits required raw observations")


def verify_normalized_prices(path: Path, months: list,
                             observations: tuple[PriceObservation, ...]) -> None:
    """Retain physical CSV lines, or file-level context for missing rows/schema."""
    try:
        _verify_normalized_prices(path, months, observations)
    except PriceSourceError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise PriceSourceError(str(path), None, str(exc)) from exc
