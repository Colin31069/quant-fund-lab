"""Dedicated atomic checkpoint store; source/snapshot preflight belongs to the runner."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .serialization import decode_state, encode_state
from .types import OddLotSessionState


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class SessionCommit:
    checkpoint: OddLotSessionState
    input_fingerprint: str
    events_json: str
    previous_digest: str

    def __post_init__(self) -> None:
        for value in (self.input_fingerprint, self.previous_digest):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("commit identities require SHA-256")
        events = json.loads(self.events_json)
        if (not isinstance(events, dict) or canonical(events) != self.events_json
                or any(not isinstance(rows, list) for rows in events.values())):
            raise ValueError("events require canonical finite grouped JSON lists")


class OddLotLedger:
    """An explicit new-account store, never a research archive or general ledger."""

    def __init__(self, path: str | Path, *, config_json: str,
                 initial_state: OddLotSessionState | None = None, read_only: bool = False):
        path = Path(path)
        if path.is_symlink() or (not path.exists() and initial_state is None):
            raise ValueError("existing account required; creation needs explicit initial state")
        config = json.loads(config_json)
        if not isinstance(config, dict) or canonical(config) != config_json:
            raise ValueError("account configuration must be canonical finite JSON")
        if initial_state is not None and initial_state.session_offset != 0:
            raise ValueError("initial checkpoint must have zero session offset")
        new = not path.exists()
        if read_only and (new or initial_state is not None):
            raise ValueError("read-only inspection requires an existing account")
        if not new and initial_state is not None:
            raise ValueError("account creation cannot replace an existing path")
        if new:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive file creation avoids truncation or racing another creator.
            path.open("xb").close()
        self.connection = (sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, isolation_level=None)
                           if read_only else sqlite3.connect(path, isolation_level=None))
        try:
            if new:
                with self.connection:
                    self.connection.executescript("""
                        BEGIN IMMEDIATE;
                        CREATE TABLE account_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                        CREATE TABLE session_checkpoints(
                            session TEXT PRIMARY KEY,state_json TEXT NOT NULL,input_digest TEXT NOT NULL,
                            previous_digest TEXT NOT NULL,commit_digest TEXT NOT NULL UNIQUE);
                        CREATE TABLE session_events(
                            business_id TEXT PRIMARY KEY,session TEXT NOT NULL REFERENCES session_checkpoints(session),
                            category TEXT NOT NULL,ordinal INTEGER NOT NULL,payload TEXT NOT NULL,
                            UNIQUE(session,category,ordinal));
                    """)
                    self.connection.executemany("INSERT INTO account_metadata VALUES(?,?)", (
                        ("kind", "odd_lot_checkpoint_v1"), ("config", config_json),
                        ("initial_state", encode_state(initial_state))))
                    self.connection.commit()
            self.connection.execute("PRAGMA foreign_keys=ON")
            metadata = dict(self.connection.execute("SELECT key,value FROM account_metadata"))
            if metadata.get("kind") != "odd_lot_checkpoint_v1" or metadata.get("config") != config_json:
                raise ValueError("account schema or locked execution configuration differs")
            self.initial = decode_state(metadata["initial_state"])
            self.config_json = config_json
            self.verify()
        except BaseException:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def _events(self, session: str) -> dict:
        result: dict[str, list] = {}
        for business_id, category, ordinal, payload in self.connection.execute(
            "SELECT business_id,category,ordinal,payload FROM session_events WHERE session=? ORDER BY category,ordinal",
            (session,)):
            rows = result.setdefault(category, [])
            if ordinal != len(rows) or business_id != digest(canonical([session, category, ordinal])):
                raise ValueError("event business identity or ordering differs")
            value = json.loads(payload)
            if canonical(value) != payload:
                raise ValueError("event encoding differs")
            rows.append(value)
        return result

    def verify(self) -> tuple[OddLotSessionState, str]:
        state, previous = self.initial, digest(canonical([self.config_json, encode_state(self.initial)]))
        if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("account SQLite integrity failure")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("orphan account events")
        for session, payload, inputs, parent, recorded in self.connection.execute(
            "SELECT session,state_json,input_digest,previous_digest,commit_digest FROM session_checkpoints ORDER BY session"):
            next_state = decode_state(payload)
            if (session != next_state.session or next_state.session <= state.session
                    or next_state.origin_session != state.origin_session
                    or next_state.session_offset != state.session_offset + 1 or parent != previous):
                raise ValueError("checkpoint chain or session boundary differs")
            events = self._events(session)
            actual = digest(canonical([parent, payload, inputs, events]))
            if actual != recorded:
                raise ValueError("checkpoint or event digest differs")
            state, previous = next_state, recorded
        return state, previous

    def commit(self, record: SessionCommit, *, _fault: Callable[[str], None] | None = None,
               _validate: Callable[[sqlite3.Connection], None] | None = None) -> str:
        """Commit state/events/completion together; identical replay is a verified no-op."""
        db = self.connection
        db.execute("BEGIN IMMEDIATE")
        try:
            latest, previous = self.verify()
            state_json = encode_state(record.checkpoint)
            events = {key: rows for key, rows in json.loads(record.events_json).items() if rows}
            identity = digest(canonical([record.previous_digest, state_json, record.input_fingerprint, events]))
            existing = db.execute("SELECT commit_digest FROM session_checkpoints WHERE session=?",
                                  (record.checkpoint.session,)).fetchone()
            if existing:
                if existing[0] != identity:
                    raise ValueError("completed session inputs or results changed")
                db.rollback()
                return identity
            if record.previous_digest != previous or record.checkpoint.session <= latest.session:
                raise ValueError("commit does not extend the verified checkpoint prefix")
            db.execute("INSERT INTO session_checkpoints VALUES(?,?,?,?,?)", (
                record.checkpoint.session, state_json, record.input_fingerprint, previous, identity))
            if _fault:
                _fault("checkpoint")
            for category, rows in events.items():
                db.executemany("INSERT INTO session_events VALUES(?,?,?,?,?)", [
                    (digest(canonical([record.checkpoint.session, category, ordinal])),
                     record.checkpoint.session, category, ordinal, canonical(row))
                    for ordinal, row in enumerate(rows)])
            if _fault:
                _fault("events")
            self.verify()
            if _validate:
                _validate(db)
            db.commit()
            return identity
        except BaseException:
            db.rollback()
            raise
