"""Atomic new-schema storage of completed engine, rights and authorization state."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .codec import canonical
from .engine_checkpoint import RightsEngineCheckpoint, validate_checkpoint_extension
from .engine_checkpoint_codec import decode_engine_rights, encode_engine_rights
from .engine_ledger_types import RightsEngineCommit, RightsLedgerConfig, payload_digest

KIND = "rights_engine_checkpoint_v1"


class RightsEngineLedger:
    """A new-account ledger; never silently migrate an existing SQLite format.

    Expected config pins initial state, full policy, execution, calendar,
    settings and protocol digests. Source-prefix, risk/NAV and registration
    authentication still belong to the calling workflow's precommit gates.
    """

    def __init__(self, path: str | Path, *, config: RightsLedgerConfig,
                 initial: RightsEngineCheckpoint | None = None, read_only: bool = False):
        if not isinstance(config, RightsLedgerConfig):
            raise TypeError("rights ledger requires a typed externally supplied configuration")
        RightsLedgerConfig(**asdict(config))
        target = Path(path)
        if target.is_symlink() or (not target.exists() and initial is None):
            raise ValueError("rights ledger needs an existing account or explicit new initial state")
        new = not target.exists()
        if (read_only and (new or initial is not None)) or (not new and initial is not None):
            raise ValueError("rights ledger creation cannot replace an existing or read-only account")
        initial_json = None if initial is None else encode_engine_rights(initial)
        if initial is not None and (initial.engine.session_offset != 0
                or initial.account.policy.policy_sha256 != config.policy_sha256
                or payload_digest(initial_json) != config.initial_checkpoint_sha256):
            raise ValueError("rights ledger initial state differs from its pinned configuration")
        if new:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.open("xb").close()
        self.read_only = read_only
        self.config_json = canonical(asdict(config))
        self.connection = sqlite3.connect(target.resolve().as_uri()+("?mode=ro" if read_only else "?mode=rw"),
                                          uri=True, isolation_level=None)
        db = self.connection
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if new:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE rights_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE rights_checkpoints(session TEXT PRIMARY KEY,state_json TEXT NOT NULL,
                        input_digest TEXT NOT NULL,parent_digest TEXT NOT NULL);
                    CREATE TABLE rights_events(session TEXT PRIMARY KEY REFERENCES rights_checkpoints(session),
                        events_json TEXT NOT NULL);
                    CREATE TABLE rights_completed(session TEXT PRIMARY KEY REFERENCES rights_checkpoints(session),
                        commit_digest TEXT NOT NULL UNIQUE);
                """)
                db.executemany("INSERT INTO rights_metadata VALUES(?,?)", (
                    ("kind", KIND), ("config", self.config_json), ("initial", initial_json)))
                db.commit()
            metadata = dict(db.execute("SELECT key,value FROM rights_metadata"))
            if (set(metadata) != {"kind", "config", "initial"} or metadata["kind"] != KIND
                    or metadata["config"] != self.config_json
                    or payload_digest(metadata["initial"]) != config.initial_checkpoint_sha256):
                raise ValueError("rights ledger format, initial anchor or locked configuration differs")
            self.initial_json = metadata["initial"]
            self.initial = decode_engine_rights(self.initial_json)
            if self.initial.account.policy.policy_sha256 != config.policy_sha256:
                raise ValueError("rights ledger full policy differs from pinned configuration")
            self.verify()
        except sqlite3.DatabaseError as exc:
            db.rollback()
            db.close()
            raise ValueError("unsupported or damaged rights ledger SQLite format") from exc
        except BaseException:
            db.rollback()
            db.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def verify(self) -> tuple[RightsEngineCheckpoint, str]:
        db = self.connection
        if dict(db.execute("SELECT key,value FROM rights_metadata")) != {
                "kind": KIND, "config": self.config_json, "initial": self.initial_json}:
            raise ValueError("rights ledger metadata changed from its pinned initial identity")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("rights ledger SQLite integrity/foreign-key failure")
        counts = [db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                  for table in ("rights_checkpoints", "rights_events", "rights_completed")]
        if len(set(counts)) != 1:
            raise ValueError("rights ledger has an incomplete state/event/completion transaction")
        state = decode_engine_rights(self.initial_json)
        previous = payload_digest(canonical([self.config_json, self.initial_json]))
        rows = db.execute("""SELECT c.session,c.state_json,c.input_digest,c.parent_digest,e.events_json,d.commit_digest
            FROM rights_checkpoints c JOIN rights_events e USING(session)
            JOIN rights_completed d USING(session) ORDER BY c.session""").fetchall()
        if len(rows) != counts[0]:
            raise ValueError("rights ledger state/event/completion sessions differ")
        for session, payload, inputs, parent, events, recorded in rows:
            current = decode_engine_rights(payload)
            record = RightsEngineCommit(current, inputs, events, parent)
            if session != current.engine.session or parent != previous:
                raise ValueError("rights ledger session or predecessor digest differs")
            validate_checkpoint_extension(state, current)
            actual = payload_digest(canonical([record.previous_digest, payload, inputs, events]))
            if actual != recorded:
                raise ValueError("rights ledger state/event/completion digest differs")
            state, previous = current, recorded
        return state, previous

    def commit(self, record: RightsEngineCommit, *, _fault: Callable[[str], None] | None = None,
               _validate: Callable[[sqlite3.Connection], None] | None = None) -> str:
        """Publish the whole day once; roll back every boundary on BaseException.

        The optional precommit validator supports workflow source/business
        audits. This storage API alone does not certify those external facts.
        """
        if self.read_only:
            raise ValueError("read-only rights ledger cannot commit")
        RightsEngineCommit(record.checkpoint, record.input_fingerprint, record.events_json, record.previous_digest)
        payload = encode_engine_rights(record.checkpoint)
        identity = payload_digest(canonical([record.previous_digest, payload,
                                             record.input_fingerprint, record.events_json]))
        db = self.connection
        db.execute("BEGIN IMMEDIATE")
        try:
            latest, parent = self.verify()
            session = record.checkpoint.engine.session
            existing = db.execute("SELECT commit_digest FROM rights_completed WHERE session=?", (session,)).fetchone()
            if existing:
                if existing[0] != identity:
                    raise ValueError("completed rights session inputs or results changed")
                db.rollback()
                return identity
            if record.previous_digest != parent:
                raise ValueError("rights commit does not extend the verified predecessor")
            validate_checkpoint_extension(latest, record.checkpoint)
            db.execute("INSERT INTO rights_checkpoints VALUES(?,?,?,?)", (
                session, payload, record.input_fingerprint, parent))
            if _fault:
                _fault("checkpoint")
            db.execute("INSERT INTO rights_events VALUES(?,?)", (session, record.events_json))
            if _fault:
                _fault("events")
            db.execute("INSERT INTO rights_completed VALUES(?,?)", (session, identity))
            if _fault:
                _fault("completion")
            if _validate:
                _validate(db)
            if self.verify()[1] != identity:
                raise ValueError("precommit validation changed the expected rights record")
            if _fault:
                _fault("before_commit")
            db.commit()
            return identity
        except BaseException:
            db.rollback()
            raise
