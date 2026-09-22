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


def _dataset_id(files: dict[str, str], exchange: str | None) -> str:
    payload = json.dumps(
        {"exchange": exchange, "files": dict(sorted(files.items()))},
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
        "reference": data.reference,
        "membership": data.membership,
        "terminal_returns": data.terminal_returns,
        "dividends": data.dividends,
        "stock_splits": data.stock_splits,
    }
    file_hashes: dict[str, str] = {}
    for name, frame in frames.items():
        if frame is None:
            continue
        path = root / f"{name}.parquet"
        frame.to_parquet(path, engine="pyarrow", compression="zstd")
        file_hashes[path.name] = _sha256(path)

    manifest = {
        "schema_version": 1,
        "exchange": data.exchange,
        "symbols": data.symbols,
        "start": str(pd.Timestamp(data.close.index.min()).date()),
        "end": str(pd.Timestamp(data.close.index.max()).date()),
        "files": dict(sorted(file_hashes.items())),
    }
    manifest["dataset_id"] = _dataset_id(file_hashes, data.exchange)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return SnapshotManifest(
        dataset_id=manifest["dataset_id"],
        exchange=data.exchange,
        symbols=tuple(data.symbols),
        start=manifest["start"],
        end=manifest["end"],
        files=dict(file_hashes),
    )


def load_market_data_snapshot(directory: str | Path) -> MarketData:
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema version")
    files: dict[str, str] = manifest["files"]
    required = {"open.parquet", "close.parquet", "volume.parquet"}
    if not required.issubset(files):
        raise ValueError("snapshot manifest is missing required market-data files")
    for filename, expected_hash in files.items():
        path = root / filename
        if not path.exists() or _sha256(path) != expected_hash:
            raise ValueError(f"snapshot integrity check failed: {filename}")
    if _dataset_id(files, manifest.get("exchange")) != manifest.get("dataset_id"):
        raise ValueError("snapshot manifest dataset_id mismatch")

    def read(name: str) -> pd.DataFrame | None:
        filename = f"{name}.parquet"
        return pd.read_parquet(root / filename) if filename in files else None

    return MarketData(
        open=read("open"),
        close=read("close"),
        volume=read("volume"),
        reference=read("reference"),
        membership=read("membership"),
        terminal_returns=read("terminal_returns"),
        dividends=read("dividends"),
        stock_splits=read("stock_splits"),
        exchange=manifest.get("exchange"),
    )
