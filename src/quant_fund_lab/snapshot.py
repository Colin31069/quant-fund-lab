from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .data import MarketData


@dataclass(frozen=True)
class SnapshotManifest:
    dataset_id: str
    exchange: str | None
    base_currency: str | None
    symbols: tuple[str, ...]
    start: str
    end: str
    files: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_id(
    files: dict[str, str], exchange: str | None, base_currency: str | None
) -> str:
    payload = json.dumps(
        {
            "exchange": exchange,
            "base_currency": base_currency,
            "files": dict(sorted(files.items())),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def save_market_data_snapshot(
    data: MarketData, directory: str | Path, overwrite: bool = False
) -> SnapshotManifest:
    root = Path(directory)
    if root.exists() and any(root.iterdir()) and not overwrite:
        raise FileExistsError(f"snapshot directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    frames = {
        "open": data.open,
        "close": data.close,
        "volume": data.volume,
        "raw_open": data.raw_open,
        "raw_close": data.raw_close,
        "reference": data.reference,
        "membership": data.membership,
        "terminal_returns": data.terminal_returns,
        "dividends": data.dividends,
        "stock_splits": data.stock_splits,
        "cash_in_lieu_prices": data.cash_in_lieu_prices,
        "cash_in_lieu_settlement_dates": data.cash_in_lieu_settlement_dates,
        "fx_to_base": data.fx_to_base,
        "fx_age_days": data.fx_age_days,
        "market_codes": data.market_codes,
        "currency_codes": data.currency_codes,
    }
    file_hashes: dict[str, str] = {}
    for name, frame in frames.items():
        if frame is None:
            continue
        path = root / f"{name}.parquet"
        frame.to_parquet(path, engine="pyarrow", compression="zstd")
        file_hashes[path.name] = _sha256(path)

    manifest = {
        "schema_version": 6,
        "exchange": data.exchange,
        "base_currency": data.base_currency,
        "symbols": data.symbols,
        "start": str(pd.Timestamp(data.close.index.min()).date()),
        "end": str(pd.Timestamp(data.close.index.max()).date()),
        "files": dict(sorted(file_hashes.items())),
    }
    manifest["dataset_id"] = _dataset_id(
        file_hashes, data.exchange, data.base_currency
    )
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return SnapshotManifest(
        dataset_id=manifest["dataset_id"],
        exchange=data.exchange,
        base_currency=data.base_currency,
        symbols=tuple(data.symbols),
        start=manifest["start"],
        end=manifest["end"],
        files=dict(file_hashes),
    )


def load_market_data_snapshot(directory: str | Path) -> MarketData:
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in {2, 3, 4, 5, 6}:
        raise ValueError("unsupported snapshot schema version")
    files: dict[str, str] = manifest["files"]
    required = {"open.parquet", "close.parquet", "volume.parquet"}
    if not required.issubset(files):
        raise ValueError("snapshot manifest is missing required market-data files")
    for filename, expected_hash in files.items():
        path = root / filename
        if not path.exists() or _sha256(path) != expected_hash:
            raise ValueError(f"snapshot integrity check failed: {filename}")
    if _dataset_id(
        files, manifest.get("exchange"), manifest.get("base_currency")
    ) != manifest.get("dataset_id"):
        raise ValueError("snapshot manifest dataset_id mismatch")

    def read(name: str) -> pd.DataFrame | None:
        filename = f"{name}.parquet"
        return pd.read_parquet(root / filename) if filename in files else None

    return MarketData(
        open=read("open"),
        close=read("close"),
        volume=read("volume"),
        raw_open=read("raw_open") if schema_version >= 3 else None,
        raw_close=read("raw_close") if schema_version >= 3 else None,
        reference=read("reference"),
        membership=read("membership"),
        terminal_returns=read("terminal_returns"),
        dividends=read("dividends"),
        stock_splits=read("stock_splits"),
        cash_in_lieu_prices=(
            read("cash_in_lieu_prices") if schema_version >= 5 else None
        ),
        cash_in_lieu_settlement_dates=(
            read("cash_in_lieu_settlement_dates") if schema_version >= 6 else None
        ),
        fx_to_base=read("fx_to_base"),
        fx_age_days=read("fx_age_days"),
        market_codes=read("market_codes") if schema_version >= 4 else None,
        currency_codes=read("currency_codes") if schema_version >= 4 else None,
        base_currency=manifest.get("base_currency"),
        exchange=manifest.get("exchange"),
    )
