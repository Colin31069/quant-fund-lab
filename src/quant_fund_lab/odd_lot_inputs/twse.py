"""Expose original TWSE price rows without relabeling other providers as official."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ..twse_odd_lot import TWSEInput, _date, _field, _number, _read_table, _safe_file
from .errors import PriceSourceError
from .types import PriceObservation, PriceSourceRef, iso_day


def _load_twse_price_observations(inputs: TWSEInput | str | Path) -> tuple[PriceObservation, ...]:
    """Read raw rows from an already prepared, evidence-checked official bundle."""
    if isinstance(inputs, TWSEInput):
        files, hashes = inputs.source_files, inputs.source_hashes
    else:
        root = Path(inputs)
        manifest_path = _safe_file(root, "manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported official source manifest")
        files = {"manifest.json": manifest_path}
        hashes = {"manifest.json": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
        for entry in manifest["sources"]:
            if entry["path"] in files:
                raise ValueError("duplicate official source path")
            files[entry["path"]] = _safe_file(root, entry["path"])
            hashes[entry["path"]] = entry["sha256"]
    for name, path in files.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes.get(name):
            raise PriceSourceError(name, None, f"TWSE price source integrity failure: {name}")
    manifest = json.loads(files["manifest.json"].read_text(encoding="utf-8"))
    result, seen = [], set()
    for entry in manifest["sources"]:
        if entry["kind"] != "price":
            continue
        try:
            source = PriceSourceRef("TWSE", "STOCK_DAY", entry["url"], entry["retrieved_at"],
                                    entry["path"], entry["sha256"],
                                    "existing local official research input; original provenance retained",
                                    (entry["url"],))
            iso_day(entry["month"] + "-01")
            fields, rows = _read_table(files[entry["path"]])
            di, oi, ci, vi = (_field(fields, "日期"), _field(fields, "開盤價"),
                              _field(fields, "收盤價"), _field(fields, "成交股數"))
        except (ValueError, TypeError, IndexError, KeyError) as exc:
            raise PriceSourceError(entry["path"], None, str(exc)) from exc
        for index, row in enumerate(rows):
            try:
                day = str(_date(row[di]).date())
            except (ValueError, TypeError, IndexError) as exc:
                if files[entry["path"]].suffix.lower() == ".csv":
                    continue  # Official CSV footers are not quotations.
                raise PriceSourceError(source.raw_path, f"data[{index}]",
                                       "invalid TWSE raw price date") from exc
            try:
                if day[:7] != entry["month"] or (entry["symbol"], day) in seen:
                    raise ValueError("duplicate TWSE quote or wrong source month")
                seen.add((entry["symbol"], day))
                opening, close, volume = _number(row[oi]), _number(row[ci]), _number(row[vi])
                if not math.isfinite(volume) or volume < 0 or int(volume) != volume:
                    raise ValueError("TWSE volume is not a nonnegative share count")
                no_quote = all(not math.isfinite(v) or v == 0 for v in (opening, close))
                high = _number(row[_field(fields, "最高價")]) if "最高價" in fields else None
                low = _number(row[_field(fields, "最低價")]) if "最低價" in fields else None
                result.append(PriceObservation(entry["symbol"], day,
                    None if no_quote else opening, None if no_quote else high,
                    None if no_quote else low, None if no_quote else close,
                    int(volume), no_quote, source, f"data[{index}]"))
            except (ValueError, TypeError, IndexError, KeyError) as exc:
                raise PriceSourceError(source.raw_path, f"data[{index}]", str(exc)) from exc
    return tuple(sorted(result, key=lambda row: (row.symbol, row.date, row.source.source_id)))



def load_twse_price_observations(inputs: TWSEInput | str | Path) -> tuple[PriceObservation, ...]:
    """Read official observations with typed file/row diagnostics, without source writes."""
    try:
        return _load_twse_price_observations(inputs)
    except PriceSourceError:
        raise
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        raise PriceSourceError("manifest.json", None, str(exc)) from exc
