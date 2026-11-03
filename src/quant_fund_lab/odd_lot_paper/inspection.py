"""Read-only account inspection, clearly separated from source-authenticated resume."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .audit import AccountingAudit, audit_accounting
from .ledger import OddLotLedger
from .types import OddLotSessionState


@dataclass(frozen=True)
class AccountInspection:
    checkpoint: OddLotSessionState
    completion_digest: str
    committed_sessions: int
    events: tuple[tuple[str, int], ...]
    audit: AccountingAudit
    source_status: str = "not_checked_by_read_only_inspection"


def inspect_account(path: str | Path) -> AccountInspection:
    root = Path(path)
    if root.is_symlink() or not root.is_file():
        raise ValueError("inspection requires an existing account file")
    with closing(sqlite3.connect(root.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        row = db.execute("SELECT value FROM account_metadata WHERE key='config'").fetchone()
        if row is None:
            raise ValueError("account configuration is missing")
    ledger = OddLotLedger(root, config_json=row[0], read_only=True)
    try:
        checkpoint, identity = ledger.verify()
        count = ledger.connection.execute("SELECT count(*) FROM session_checkpoints").fetchone()[0]
        events = tuple(ledger.connection.execute("SELECT category,count(*) FROM session_events GROUP BY category ORDER BY category"))
        return AccountInspection(checkpoint, identity, count, events,
                                 audit_accounting(root, _connection=ledger.connection))
    finally:
        ledger.close()
