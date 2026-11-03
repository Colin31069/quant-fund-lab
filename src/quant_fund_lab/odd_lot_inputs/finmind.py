"""Read FinMind acquisition manifests offline; never manufacture TWSE responses."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import PriceSourceError
from .types import PriceBundle, PriceObservation, PriceSourceRef, iso_day
from .validation import verify_normalized_prices


def safe_file(root: Path, name: str) -> Path:
    relative = Path(name)
    path = (root / relative).resolve()
    if (relative.is_absolute() or ".." in relative.parts
            or root.resolve() not in path.parents or not path.is_file()):
        raise ValueError(f"missing or unsafe price source: {name}")
    return path


def number(row: dict, key: str, *, integer: bool = False) -> float | int:
    value = row[key]
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value < 0 or (integer and int(value) != value)):
        raise ValueError(f"invalid finite nonnegative price field: {key}")
    return int(value) if integer else float(value)


def parse_finmind_prices(raw: bytes, request: dict, source: PriceSourceRef,
                         cutoff: str) -> tuple[PriceObservation, ...]:
    """Keep row locators and no-quote flags; zero quotes become absent prices."""
    try:
        symbol, start, end = request["symbol"], iso_day(request["start"]), iso_day(request["end"])
        if not isinstance(symbol, str) or not start <= end <= iso_day(cutoff):
            raise ValueError("price request exceeds cutoff or has invalid boundaries")
    except (ValueError, TypeError, KeyError) as exc:
        raise PriceSourceError(source.raw_path, "request", str(exc)) from exc
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise PriceSourceError(source.raw_path, None, str(exc)) from exc
    if (not isinstance(payload, dict) or type(payload.get("status")) is not int or payload["status"] != 200
            or payload.get("msg") != "success" or not isinstance(payload.get("data"), list)
            or not payload["data"]):
        raise PriceSourceError(source.raw_path, None, "not a nonempty successful FinMind price response")
    result, seen = [], set()
    for index, row in enumerate(payload["data"]):
        try:
            if not isinstance(row, dict) or row.get("stock_id") != symbol.removesuffix(".TW"):
                raise ValueError("raw stock identity differs from request")
            day = iso_day(row["date"])
            if not start <= day <= end or day in seen:
                raise ValueError("raw dates are duplicate or outside the request")
            seen.add(day)
            prices = tuple(number(row, key) for key in ("open", "max", "min", "close"))
            no_quote = all(value == 0 for value in prices)
            result.append(PriceObservation(symbol, day, *((None,) * 4 if no_quote else prices),
                                           number(row, "Trading_Volume", integer=True), no_quote,
                                           source, f"data[{index}]",
                                           number(row, "Trading_money", integer=True),
                                           number(row, "Trading_turnover", integer=True)))
            # Validate additional provider fields even though execution does not consume them.
        except (ValueError, TypeError, KeyError) as exc:
            raise PriceSourceError(source.raw_path, f"data[{index}]", str(exc)) from exc
    return tuple(sorted(result, key=lambda row: row.date))


def _load_finmind_price_bundle(directory: str | Path) -> PriceBundle:
    """Verify provider, raw bytes and request identity before returning any prices."""
    root = Path(directory)
    manifest_file = safe_file(root, "provider_manifest.json")
    raw_manifest = manifest_file.read_bytes()
    manifest = json.loads(raw_manifest)
    expected = {"schema_version": 1, "provider": "FinMind", "dataset": "TaiwanStockPrice",
                "price_basis": "raw_unadjusted", "currency": "TWD", "volume_unit": "shares"}
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or any(manifest.get(key) != value for key, value in expected.items())):
        raise ValueError("unsupported provider price manifest or unit/basis")
    cutoff = iso_day(manifest["research_cutoff"])
    entries = manifest.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("price manifest has no sources")
    sources, observations = [], []
    files = {"provider_manifest.json": manifest_file}
    keys = set()
    for index, entry in enumerate(entries):
        try:
            if entry["provider"] != "FinMind" or entry["dataset"] != "TaiwanStockPrice":
                raise ValueError("source provider differs from manifest")
            source = PriceSourceRef(entry["provider"], entry["dataset"], entry["requested_url"],
                                    entry["retrieved_at"], entry["raw_path"], entry["sha256"],
                                    entry["usage"], tuple(entry["authorization_basis"]))
            request = entry["request"]
            parsed = urlparse(source.source_url)
            wanted = {"dataset": [source.dataset], "data_id": [request["symbol"].removesuffix(".TW")],
                      "start_date": [request["start"]], "end_date": [request["end"]]}
            if (parsed.path != "/api/v4/data" or parse_qs(parsed.query) != wanted
                    or entry.get("final_url") != source.source_url or entry.get("http_status") != 200):
                raise ValueError("price response provenance differs from request")
            if source.raw_path in files:
                raise ValueError("duplicate raw source path")
            path = safe_file(root, source.raw_path)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source.sha256 or len(raw) != entry["bytes"]:
                raise PriceSourceError(source.raw_path, None,
                                       f"raw price source integrity failure: {source.raw_path}")
            rows = parse_finmind_prices(raw, request, source, cutoff)
            if len(rows) != entry["rows"]:
                raise ValueError("raw price row count differs from manifest")
            for row in rows:
                key = (row.symbol, row.date)
                if key in keys:
                    raise PriceSourceError(source.raw_path, row.row_locator,
                                               "overlapping raw source rows require explicit conflict resolution")
                keys.add(key)
            sources.append(source)
            observations.extend(rows)
            files[source.raw_path] = path
        except PriceSourceError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise PriceSourceError("provider_manifest.json", f"sources[{index}]", str(exc)) from exc
    if "normalized_sha256" in manifest:
        normalized = safe_file(root, "normalized/finmind_prices.csv")
        if hashlib.sha256(normalized.read_bytes()).hexdigest() != manifest["normalized_sha256"]:
            raise PriceSourceError("normalized/finmind_prices.csv", None,
                                   "normalized price source integrity failure")
        files["normalized/finmind_prices.csv"] = normalized
        verify_normalized_prices(normalized, manifest["months"], tuple(observations))
    return PriceBundle(tuple(sorted(sources, key=lambda s: s.source_id)),
                       tuple(sorted(observations, key=lambda r: (r.symbol, r.date))),
                       hashlib.sha256(raw_manifest).hexdigest(), cutoff, tuple(sorted(files.items())))


def load_finmind_price_bundle(directory: str | Path) -> PriceBundle:
    """Read a verified bundle, retaining source/row context for invalid input."""
    try:
        return _load_finmind_price_bundle(directory)
    except PriceSourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PriceSourceError("provider_manifest.json", None, str(exc)) from exc
