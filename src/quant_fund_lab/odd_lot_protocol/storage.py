"""Create and verify immutable protocol files before any candidate execution."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .types import StudyProtocol, canonical_json


def load_protocol(directory: str | Path) -> StudyProtocol:
    root = Path(directory)
    if root.is_symlink() or (root / "protocol.json").is_symlink():
        raise ValueError("protocol paths cannot be symlinks")
    raw = json.loads((root / "protocol.json").read_text(encoding="utf-8"))
    if set(raw) != {"protocol_id", "recorded_at", "protocol"}:
        raise ValueError("unsupported protocol envelope")
    protocol = StudyProtocol.from_dict(raw["protocol"])
    if raw["protocol_id"] != protocol.protocol_id:
        raise ValueError("protocol content fingerprint mismatch")
    stamp = datetime.fromisoformat(raw["recorded_at"])
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("protocol recording timestamp requires a timezone")
    for period in protocol.periods:
        if period.data_access == "unseen" and period.start <= str(stamp.date()):
            raise ValueError("recorded protocol cannot retroactively declare unseen data")
    return protocol


def freeze_protocol(protocol: StudyProtocol, directory: str | Path) -> Path:
    """Publish one immutable protocol; retries verify and reuse the original bytes.

    Recording time is separate from a supplied declaration time. Neither local
    timestamps nor hashes independently prove historical preregistration.
    """
    parent = Path(directory)
    destination = parent / protocol.protocol_id
    if destination.exists():
        if load_protocol(destination) != protocol:
            raise ValueError("existing protocol content differs; cannot overwrite")
        return destination
    if protocol.parent_protocol_id is not None:
        previous = load_protocol(parent / protocol.parent_protocol_id)
        if datetime.fromisoformat(previous.declared_at) > datetime.fromisoformat(protocol.declared_at):
            raise ValueError("child protocol declaration precedes its parent")
    recorded_at = datetime.now(timezone.utc)
    if datetime.fromisoformat(protocol.declared_at) > recorded_at:
        raise ValueError("protocol declaration cannot be in the future")
    for period in protocol.periods:
        if period.data_access == "unseen" and period.start <= str(recorded_at.date()):
            raise ValueError("cannot preregister an already historical period as unseen")
    parent.mkdir(parents=True, exist_ok=True)
    payload = {"protocol_id": protocol.protocol_id, "recorded_at": recorded_at.isoformat(),
               "protocol": protocol.to_dict()}
    with tempfile.TemporaryDirectory(prefix=".protocol-", dir=parent) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        with (staging / "protocol.json").open("w", encoding="utf-8") as file:
            file.write(canonical_json(payload))
            file.flush()
            os.fsync(file.fileno())
        try:
            os.rename(staging, destination)
        except FileExistsError:
            if load_protocol(destination) != protocol:
                raise ValueError("concurrent protocol differs; cannot overwrite") from None
    return destination
