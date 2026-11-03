"""Read existing immutable registry histories without initialization or migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .registry import ExperimentRegistry


class ReadOnlyExperimentRegistry(ExperimentRegistry):
    """Reuse verified read methods on an enforced read-only SQLite connection.

    The writable registry constructor intentionally initializes empty databases;
    evidence readers must reject those instead. Inherited mutation methods are
    also rejected by SQLite, even if accidentally called by an evidence adapter.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError("read-only registry requires an existing regular database")
        self.connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"registry_meta", "protocols", "experiments", "attempts"}.issubset(tables):
                raise ValueError("database is not an initialized experiment registry")
            row = self.connection.execute("SELECT value FROM registry_meta WHERE key='schema'").fetchone()
            if row is None or row[0] != "odd-lot-experiments-v1":
                raise ValueError("unsupported read-only experiment registry schema")
        except Exception:
            self.connection.close()
            raise
