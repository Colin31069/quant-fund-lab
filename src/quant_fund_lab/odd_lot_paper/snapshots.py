"""Immutable snapshot publication and ledger linkage, separate from SQL commits."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from ..data import MarketData
from ..replay_provenance import replay_session_data_fingerprint
from ..snapshot import load_market_data_snapshot, save_market_data_snapshot
from .ledger import canonical, digest


def _logical_id(data: MarketData) -> str:
    return digest(canonical([replay_session_data_fingerprint(data, stamp,
        data.raw_close.loc[stamp], None) for stamp in data.close.index]))


def verify_snapshot_link(root: str | Path, link: dict) -> MarketData:
    """Verify exact files before decoding; reject paths and symlinked source bytes."""
    root = Path(root)
    if root.is_symlink() or not re.fullmatch(r"[0-9a-f]{64}", link["logical_id"]):
        raise ValueError("unsafe snapshot root or identity")
    target = root / link["logical_id"]
    if target.is_symlink() or not target.is_dir():
        raise ValueError("linked snapshot is missing or symlinked")
    manifest_path = target / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("snapshot manifest cannot be symlinked")
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != link["manifest_sha256"]:
        raise ValueError("linked snapshot manifest changed")
    manifest = json.loads(raw)
    if manifest["dataset_id"] != link["dataset_id"]:
        raise ValueError("linked snapshot dataset differs")
    for filename in manifest["files"]:
        if not re.fullmatch(r"[a-z_]+\.parquet", filename) or (target / filename).is_symlink():
            raise ValueError("unsafe snapshot payload path")
    if {p.name for p in target.iterdir()} != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("snapshot file inventory differs")
    data = load_market_data_snapshot(target)
    if _logical_id(data) != link["logical_id"]:
        raise ValueError("decoded snapshot identity differs")
    return data


def publish_snapshot(data: MarketData, root: str | Path) -> dict:
    """Publish without overwriting committed payloads; failed SQL may leave an orphan."""
    root = Path(root)
    if root.is_symlink():
        raise ValueError("snapshot root cannot be symlinked")
    identity = _logical_id(data)
    root.mkdir(parents=True, exist_ok=True)
    target = root / identity
    if target.exists():
        raw = (target / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        link = {"logical_id":identity,"dataset_id":manifest["dataset_id"],
                "manifest_sha256":hashlib.sha256(raw).hexdigest()}
        verify_snapshot_link(root, link)
        return link
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=root) as temporary:
        staging = Path(temporary) / "payload"
        manifest = save_market_data_snapshot(data, staging)
        raw = (staging / "manifest.json").read_bytes()
        link = {"logical_id":identity,"dataset_id":manifest.dataset_id,
                "manifest_sha256":hashlib.sha256(raw).hexdigest()}
        if _logical_id(load_market_data_snapshot(staging)) != identity or _logical_id(data) != identity:
            raise ValueError("snapshot input changed during publication")
        try:
            os.rename(staging, target)
        except FileExistsError:
            verify_snapshot_link(root, link)
    return link
