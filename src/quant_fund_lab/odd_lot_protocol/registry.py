"""Transactional experiment registration with immutable terminal attempt history."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from ..twse_quality.types import fingerprint
from .types import (
    ExecutionIdentity,
    ExperimentAttempt,
    ExperimentRecord,
    StudyProtocol,
    canonical_json,
)


class ExperimentRegistry:
    """A separate research registry; never opens a paper account for migration."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("experiment registry cannot be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and "registry_meta" not in tables:
                raise ValueError("existing database is not an experiment registry")
            if tables:
                row = self.connection.execute("SELECT value FROM registry_meta WHERE key='schema'").fetchone()
                if row is None or row[0] != "odd-lot-experiments-v1":
                    raise ValueError("unsupported experiment registry schema")
            else:
                self._create()
        except Exception:
            self.connection.close()
            raise

    def _create(self) -> None:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            statements = (
                "CREATE TABLE registry_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
                "INSERT INTO registry_meta VALUES('schema','odd-lot-experiments-v1')",
                "CREATE TABLE protocols(id TEXT PRIMARY KEY,payload TEXT NOT NULL)",
                "CREATE TABLE experiments(id TEXT PRIMARY KEY,protocol_id TEXT NOT NULL REFERENCES protocols(id),payload TEXT NOT NULL)",
                "CREATE TABLE attempts(experiment_id TEXT NOT NULL REFERENCES experiments(id),attempt INTEGER NOT NULL,payload TEXT NOT NULL,record_hash TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(experiment_id,attempt))",
                "CREATE TRIGGER terminal_attempt_immutable BEFORE UPDATE ON attempts WHEN OLD.status!='running' BEGIN SELECT RAISE(ABORT,'terminal attempt is immutable'); END",
            )
            for statement in statements:
                self.connection.execute(statement)
            for table in ("protocols", "experiments", "attempts"):
                self.connection.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'history cannot be deleted'); END")
                if table != "attempts":
                    self.connection.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'registered identity is immutable'); END")

    def __enter__(self) -> ExperimentRegistry:  # noqa: PYI034 - Python 3.9 project, no typing.Self.
        return self

    def __exit__(self, *_args) -> None:
        self.connection.close()

    def get_protocol(self, protocol_id: str) -> StudyProtocol:
        row = self.connection.execute("SELECT payload FROM protocols WHERE id=?", (protocol_id,)).fetchone()
        if row is None:
            raise ValueError("protocol is not registered")
        protocol = StudyProtocol.from_dict(json.loads(row[0]))
        if protocol.protocol_id != protocol_id:
            raise ValueError("registered protocol fingerprint mismatch")
        return protocol

    def register_protocol(self, protocol: StudyProtocol) -> None:
        payload = canonical_json(protocol.to_dict())
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if protocol.parent_protocol_id is not None:
                self.get_protocol(protocol.parent_protocol_id)
            row = self.connection.execute("SELECT payload FROM protocols WHERE id=?", (protocol.protocol_id,)).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError("registered protocol content differs")
                return
            self.connection.execute("INSERT INTO protocols VALUES(?,?)", (protocol.protocol_id, payload))

    def register_experiment(
        self, protocol: StudyProtocol, candidate_id: str, execution: ExecutionIdentity,
    ) -> ExperimentRecord:
        if protocol.execution != execution:
            raise ValueError("execution identity differs from protocol; freeze a new protocol")
        candidate = next((c for c in protocol.candidates if c.candidate_id == candidate_id), None)
        if candidate is None:
            raise ValueError("candidate is outside the frozen finite search budget")
        self.register_protocol(protocol)
        identity = fingerprint([protocol.protocol_id, candidate_id, candidate.study_id, execution.identity])
        record = ExperimentRecord(identity, protocol.protocol_id, candidate_id, candidate.study_id, execution.identity)
        payload = canonical_json(asdict(record))
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT payload FROM experiments WHERE id=?", (identity,)).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError("registered experiment content differs")
            else:
                self.connection.execute("INSERT INTO experiments VALUES(?,?,?)", (identity, protocol.protocol_id, payload))
        return record

    def get_experiment(self, experiment_id: str) -> ExperimentRecord:
        row = self.connection.execute("SELECT payload,protocol_id FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise ValueError("experiment is not registered")
        record = ExperimentRecord(**json.loads(row[0]))
        protocol = self.get_protocol(record.protocol_id)
        candidate = next((c for c in protocol.candidates if c.candidate_id == record.candidate_id), None)
        if (record.experiment_id != experiment_id or row[1] != record.protocol_id or candidate is None
                or candidate.study_id != record.study_id or protocol.execution.identity != record.execution_id):
            raise ValueError("registered experiment binding mismatch")
        return record

    def attempts(self, experiment_id: str) -> tuple[ExperimentAttempt, ...]:
        self.get_experiment(experiment_id)
        records = []
        for index, row in enumerate(self.connection.execute(
            "SELECT * FROM attempts WHERE experiment_id=? ORDER BY attempt", (experiment_id,)
        ), start=1):
            payload = json.loads(row["payload"])
            record = ExperimentAttempt(**payload)
            if (row["attempt"] != index or record.attempt != index or record.experiment_id != experiment_id
                    or row["status"] != record.status or row["record_hash"] != fingerprint(payload)):
                raise ValueError("experiment attempt history mismatch")
            records.append(record)
        return tuple(records)

    def experiments(self, protocol_id: str | None = None) -> tuple[ExperimentRecord, ...]:
        """List every registered candidate, including those with only failed attempts."""
        query, parameters = "SELECT id FROM experiments", ()
        if protocol_id is not None:
            self.get_protocol(protocol_id)
            query, parameters = query + " WHERE protocol_id=?", (protocol_id,)
        ids = [row[0] for row in self.connection.execute(query + " ORDER BY id", parameters)]
        return tuple(self.get_experiment(identity) for identity in ids)

    def start_attempt(self, experiment_id: str) -> ExperimentAttempt:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.attempts(experiment_id)
            if previous and previous[-1].status == "running":
                raise ValueError("running attempt requires explicit failure recovery before retry")
            record = ExperimentAttempt(experiment_id, len(previous) + 1, "running",
                                       datetime.now(timezone.utc).isoformat())
            payload = asdict(record)
            self.connection.execute("INSERT INTO attempts VALUES(?,?,?,?,?)", (
                experiment_id, record.attempt, canonical_json(payload), fingerprint(payload), record.status,
            ))
        return record

    def finish_attempt(
        self, experiment_id: str, attempt: int, *, status: str,
        result_fingerprint: str | None = None, report_path: str | None = None, reason: str = "",
    ) -> ExperimentAttempt:
        if status not in {"succeeded", "blocked", "failed"}:
            raise ValueError("attempt completion requires a terminal status")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            history = self.attempts(experiment_id)
            if not history or history[-1].attempt != attempt:
                raise ValueError("can only complete the latest registered attempt")
            current = history[-1]
            if current.status != "running":
                if (current.status, current.result_fingerprint, current.report_path, current.reason) == (
                    status, result_fingerprint, report_path, reason,
                ):
                    return current
                raise ValueError("terminal attempt cannot be rewritten")
            if status in {"succeeded", "blocked"} and any(
                p.status in {"succeeded", "blocked"} and p.result_fingerprint is not None
                and p.result_fingerprint != result_fingerprint for p in history
            ):
                status, reason = "failed", "nonreproducible numerical result for identical experiment inputs"
            record = replace(current, status=status, finished_at=datetime.now(timezone.utc).isoformat(),
                             result_fingerprint=result_fingerprint, report_path=report_path, reason=reason)
            payload = asdict(record)
            self.connection.execute("UPDATE attempts SET payload=?,record_hash=?,status=? WHERE experiment_id=? AND attempt=?", (
                canonical_json(payload), fingerprint(payload), record.status, experiment_id, attempt,
            ))
        return record
