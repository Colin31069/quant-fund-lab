"""Locked identities and complete-session commit contract for the new ledger."""
import hashlib
import json
import re
from dataclasses import asdict, dataclass

from .codec import canonical, fingerprint
from .engine_checkpoint import RightsEngineCheckpoint


def sha256(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("rights ledger identities require explicit SHA-256")


@dataclass(frozen=True)
class RightsLedgerConfig:
    policy_sha256: str
    execution_sha256: str
    calendar_sha256: str
    settings_sha256: str
    protocol_sha256: str
    initial_checkpoint_sha256: str

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            sha256(value)

    @property
    def identity(self) -> str:
        return fingerprint(asdict(self))


def payload_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class RightsEngineCommit:
    checkpoint: RightsEngineCheckpoint
    input_fingerprint: str
    events_json: str
    previous_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, RightsEngineCheckpoint):
            raise TypeError("rights commit requires a typed combined checkpoint")
        sha256(self.input_fingerprint)
        sha256(self.previous_digest)
        events = json.loads(self.events_json)
        if (not isinstance(events, dict) or canonical(events) != self.events_json
                or any(not isinstance(key, str) or not isinstance(rows, list) for key, rows in events.items())):
            raise ValueError("rights commit events require canonical finite grouped JSON lists")
