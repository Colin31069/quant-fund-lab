"""Rebuild verified completed history from linked snapshots before delta replay."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import fields, replace
from pathlib import Path

import pandas as pd

from ..data import MarketData
from ..replay_provenance import replay_session_data_fingerprint
from .snapshots import verify_snapshot_link


def reconstruct_account_history(account_path: str | Path, snapshot_root: str | Path,
                                delta: MarketData) -> MarketData:
    """Rebuild bars through the last commit; uncommitted future values may change.

    This helper never writes. The replay runner must still authenticate every
    committed prefix and the account's structural/financial history before work.
    """
    account = Path(account_path)
    if account.is_symlink() or not account.is_file():
        raise ValueError("history reconstruction requires an existing account")
    with sqlite3.connect(account.resolve().as_uri()+"?mode=ro", uri=True) as db:
        metadata = dict(db.execute("SELECT key,value FROM account_metadata"))
        config = json.loads(metadata["config"])
        if config.get("snapshot_root") != str(Path(snapshot_root).resolve()):
            raise ValueError("history reconstruction snapshot root differs from locked account")
        last = db.execute("SELECT session FROM session_checkpoints ORDER BY session DESC LIMIT 1").fetchone()
        if last is None:
            raise ValueError("initial-only account has no committed snapshot; supply complete history")
        records = db.execute("SELECT payload FROM session_events WHERE session=? AND category='snapshot'",
                             (last[0],)).fetchall()
        if len(records) != 1:
            raise ValueError("completed history lacks a unique snapshot link")
    archived = verify_snapshot_link(snapshot_root, json.loads(records[0][0]))
    if (delta.symbols != archived.symbols or delta.exchange != archived.exchange
            or delta.base_currency != archived.base_currency):
        raise ValueError("incremental market identity differs from archived input")
    if not delta.close.index.is_unique or not delta.close.index.is_monotonic_increasing:
        raise ValueError("incremental sessions must be unique and chronological")
    last_date = pd.Timestamp(last[0])
    for stamp in delta.close.index.intersection(archived.close.index[archived.close.index <= last_date]):
        current = replay_session_data_fingerprint(delta, stamp, delta.raw_close.loc[stamp], None)
        original = replay_session_data_fingerprint(archived, stamp, archived.raw_close.loc[stamp], None)
        if current != original:
            raise ValueError("incremental overlap changes completed historical inputs")
    panels = {}
    for field in fields(archived):
        previous, incoming = getattr(archived, field.name), getattr(delta, field.name)
        if isinstance(previous, pd.DataFrame):
            if not isinstance(incoming, pd.DataFrame) or not incoming.columns.equals(previous.columns):
                raise ValueError("incremental input panels differ from archived schema")
            combined = pd.concat([previous.loc[:last_date], incoming])
            panels[field.name] = combined.loc[~combined.index.duplicated(keep="last")].sort_index()
        elif isinstance(incoming, pd.DataFrame):
            raise TypeError("incremental optional panel changes archived schema")
    return replace(archived, **panels)
