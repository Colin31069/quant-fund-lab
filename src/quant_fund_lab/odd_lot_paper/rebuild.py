"""Explicit historical rebuild into a different new file, preserving the parent."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import pandas as pd

from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config
from ..odd_lot_study import _backtest_config, load_frozen_odd_lot_study
from .inspection import inspect_account
from .ledger import canonical
from .replay import ReplayResult
from .workflow import replay_registered_account


@dataclass(frozen=True)
class HistoricalRebuildResult:
    source_account: str
    target_account: str
    source_files_sha256: tuple[tuple[str, str], ...]
    parent_completion_digest: str
    replay: ReplayResult


def _source_hashes(path: Path) -> tuple[tuple[str, str], ...]:
    paths = [path]
    wal = Path(str(path)+"-wal")
    if wal.exists():
        paths.append(wal)
    if any(file.is_symlink() or not file.is_file() for file in paths):
        raise ValueError("rebuild source must contain regular SQLite/WAL files")
    return tuple((str(file),hashlib.sha256(file.read_bytes()).hexdigest()) for file in paths)


def rebuild_registered_account(source_account: str | Path, target_account: str | Path,
                                protocol_directory: str | Path, candidate_id: str, *,
                                period: str, strategy: str, studies_directory: str | Path,
                                source_directory: str | Path, snapshot_root: str | Path,
                                through: str | None = None) -> HistoricalRebuildResult:
    """Recompute a verified historical parent into a separate previously absent path.

    No deletion, reset, source repair or forward-observation conversion occurs.
    Candidate, original origin and settings must match the verified parent.
    A changed parent aborts the new day's SQL transaction; prior new days, if any,
    remain explicit completed work. The returned reference records parent hashes;
    it does not claim the new SQL account depends on the parent for future resume.
    """
    source, target = Path(source_account), Path(target_account)
    if source.is_symlink() or not source.is_file():
        raise ValueError("rebuild requires an existing regular historical account")
    if target.is_symlink() or target.exists() or source.resolve() == target.resolve():
        raise ValueError("rebuild requires a different new target account path")
    before = _source_hashes(source)
    inspection = inspect_account(source)
    if not inspection.audit.passed:
        raise ValueError("rebuild parent accounting audit failed; repair is not automatic")
    if inspection.committed_sessions < 1:
        raise ValueError("rebuild requires a parent with at least one completed session")
    with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True)) as db:
        config = json.loads(db.execute("SELECT value FROM account_metadata WHERE key='config'").fetchone()[0])
    if "observation" in config:
        raise ValueError("historical rebuild cannot convert a forward observation")
    protocol = load_protocol(protocol_directory)
    candidate = next((row for row in protocol.candidates if row.candidate_id == candidate_id),None)
    selected = next((row for row in protocol.periods if row.name == period),None)
    if candidate is None or selected is None or selected.purpose == "forward_observation":
        raise ValueError("rebuild requires a declared historical candidate and period")
    if strategy not in {"ensemble","momentum","equal_weight"}:
        raise ValueError("rebuild requires a supported historical strategy")
    research = replace(OddLotResearchConfig(**json.loads(candidate.research_json)),strategy=strategy)
    execution = odd_lot_backtest_config(_backtest_config(json.loads(candidate.backtest_json)),research)
    data,_ = load_frozen_odd_lot_study(Path(studies_directory)/candidate.study_id)
    position = int(data.close.index.searchsorted(pd.Timestamp(selected.start),side="left"))
    if position < 1 or position >= len(data.close.index):
        raise ValueError("rebuild period lacks a verified origin")
    if (config["identity"]["protocol_id"] != protocol.protocol_id
            or config["identity"]["execution_revision"] != protocol.execution.identity
            or config["identity"]["origin_session"] != str(data.close.index[position-1].date())
            or canonical(config["research"]) != canonical(asdict(research))
            or canonical(config["execution"]) != canonical(asdict(execution))
            or config["symbols"] != list(protocol.symbols)):
        raise ValueError("rebuild candidate, period or settings differ from parent account")

    def verify_parent(_stage):
        if _source_hashes(source) != before:
            raise ValueError("rebuild parent account changed during execution")

    verify_parent("preflight")
    if not isinstance(config.get("snapshot_root"),str) or not config["snapshot_root"]:
        raise ValueError("rebuild parent lacks its verified snapshot root")
    # Financial/digest validity alone cannot certify the parent's market inputs.
    # Authenticate its frozen sources and every archived prefix without writing.
    checked = replay_registered_account(protocol_directory,candidate_id,period=period,strategy=strategy,
        studies_directory=studies_directory,source_directory=source_directory,account_path=source,
        snapshot_root=config["snapshot_root"],through=inspection.checkpoint.session,
        _source_guard=verify_parent,_read_only=True)
    if checked.checkpoint != inspection.checkpoint or checked.last_digest != inspection.completion_digest:
        raise ValueError("rebuild parent changed during source authentication")
    verify_parent("authenticated")
    result = replay_registered_account(protocol_directory,candidate_id,period=period,strategy=strategy,
        studies_directory=studies_directory,source_directory=source_directory,account_path=target,
        snapshot_root=snapshot_root,create=True,through=through,_source_guard=verify_parent)
    verify_parent("completed")
    return HistoricalRebuildResult(str(source.resolve()),str(target.resolve()),before,
                                   inspection.completion_digest,result)
