from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import BacktestConfig

CONFIG_SCHEMA_VERSION = 1


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def serialized_config(config: BacktestConfig) -> dict[str, object]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "backtest_config": asdict(config),
    }


def deterministic_run_id(
    config: BacktestConfig,
    dataset_id: str,
    package_version: str = __version__,
    run_context: dict[str, object] | None = None,
    data_provenance: dict[str, str] | None = None,
) -> str:
    payload = {
        "config": serialized_config(config),
        "dataset_id": dataset_id,
        "package_version": package_version,
        "run_context": run_context or {},
        "data_provenance": data_provenance or {},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    dataset_id: str
    package_version: str
    config_schema_version: int
    config: dict[str, object]
    run_context: dict[str, object]
    data_provenance: dict[str, str]


def build_run_manifest(
    config: BacktestConfig,
    dataset_id: str,
    package_version: str = __version__,
    run_context: dict[str, object] | None = None,
    data_provenance: dict[str, str] | None = None,
) -> RunManifest:
    return RunManifest(
        run_id=deterministic_run_id(
            config,
            dataset_id,
            package_version,
            run_context,
            data_provenance,
        ),
        dataset_id=dataset_id,
        package_version=package_version,
        config_schema_version=CONFIG_SCHEMA_VERSION,
        config=serialized_config(config),
        run_context=run_context or {},
        data_provenance=data_provenance or {},
    )


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    timestamp: str
    event_type: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class AuditLog:
    """Append-only JSONL audit log with a SHA-256 hash chain."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _event_hash(body: dict[str, object]) -> str:
        return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()

    def read_and_verify(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        previous_hash = "GENESIS"
        for expected_sequence, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            raw = json.loads(line)
            event_hash = str(raw.pop("event_hash"))
            if int(raw["sequence"]) != expected_sequence:
                raise ValueError("audit log sequence mismatch")
            if str(raw["previous_hash"]) != previous_hash:
                raise ValueError("audit log previous-hash mismatch")
            calculated = self._event_hash(raw)
            if calculated != event_hash:
                raise ValueError("audit log hash mismatch")
            event = AuditEvent(event_hash=event_hash, **raw)
            events.append(event)
            previous_hash = event_hash
        return events

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> AuditEvent:
        events = self.read_and_verify()
        previous_hash = events[-1].event_hash if events else "GENESIS"
        observed_at = timestamp or datetime.now(timezone.utc)
        body: dict[str, object] = {
            "sequence": len(events),
            "timestamp": observed_at.astimezone(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        event_hash = self._event_hash(body)
        record = dict(body)
        record["event_hash"] = event_hash
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(record) + "\n")
        return AuditEvent(event_hash=event_hash, **body)
