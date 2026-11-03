"""Authenticated historical account replay from an immutable registered candidate."""
from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from typing import Callable

import pandas as pd

from ..odd_lot_protocol.build import verify_candidate_binding
from ..odd_lot_protocol.provenance import capture_execution_identity
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_research import OddLotResearchConfig
from ..odd_lot_study import _backtest_config, _subset, load_frozen_odd_lot_study
from .replay import ReplayIdentity, ReplayResult, _replay_account


def replay_registered_account(protocol_directory: str | Path, candidate_id: str, *,
                              period: str, strategy: str, studies_directory: str | Path,
                              source_directory: str | Path, account_path: str | Path,
                              snapshot_root: str | Path, create: bool = False,
                              through: str | None = None,
                              _source_guard: Callable[[str], None] | None = None,
                              _read_only: bool = False) -> ReplayResult:
    """Replay a declared historical period only after authenticating inputs and code.

    This creates a virtual historical account, not a forward-observation account.
    New data under a changed study/protocol cannot silently extend this identity.
    """
    source = Path(source_directory).resolve()
    if Path(__file__).resolve().parents[1] != source / "src" / "quant_fund_lab":
        raise ValueError("account source directory differs from executing package")
    protocol_root = Path(protocol_directory)
    protocol = load_protocol(protocol_root)
    execution = capture_execution_identity(source)
    if execution != protocol.execution:
        raise ValueError("account execution identity differs; freeze a new protocol")
    candidate = next((row for row in protocol.candidates if row.candidate_id == candidate_id), None)
    selected_period = next((row for row in protocol.periods if row.name == period), None)
    if candidate is None or selected_period is None:
        raise ValueError("account requires a declared candidate and period")
    if strategy not in {"ensemble", "momentum", "equal_weight"}:
        raise ValueError("account requires a declared historical strategy")
    if selected_period.purpose == "forward_observation":
        raise ValueError("forward activation requires a separate observation workflow")
    study = Path(studies_directory) / candidate.study_id
    data, metadata = load_frozen_odd_lot_study(study)
    verify_candidate_binding(protocol, candidate, metadata)
    ready = next(row for row in metadata["readiness"]["periods"] if row["period"] == period)
    if ready["status"] != "ready":
        raise ValueError("account period readiness is "+ready["status"])
    if metadata["data_source"] not in {"twse_official", "provider_reviewed"}:
        raise ValueError("account activation requires verified source-backed study")
    first, last = pd.Timestamp(selected_period.start), pd.Timestamp(selected_period.end)
    cutoff = pd.Timestamp(through) if through is not None else last
    if not first <= cutoff <= last:
        raise ValueError("account cutoff is outside the frozen period")
    position = int(data.close.index.searchsorted(first, side="left"))
    if position < 1 or position >= len(data.close.index):
        raise ValueError("account needs a prior signal close and an evaluation session")
    origin = data.close.index[position-1]
    # Retain all verified warmup, but never trade the separate benchmark asset.
    data = _subset(data, list(protocol.symbols))
    data = replace(data, **{field.name: getattr(data, field.name).loc[:cutoff].copy()
        for field in fields(data) if isinstance(getattr(data, field.name), pd.DataFrame)})
    if data.base_currency not in {None, "TWD"}:
        raise ValueError("registered odd-lot account requires TWD inputs")
    research = replace(OddLotResearchConfig(**metadata["research_config"]), strategy=strategy)
    base = _backtest_config(metadata["backtest_config"])
    identity = ReplayIdentity(protocol.protocol_id, execution.identity,
                              ready["warmup"]["calendar_revision"], origin.date().isoformat())

    def verify_sources(_stage):
        if load_protocol(protocol_root) != protocol or capture_execution_identity(source) != execution:
            raise ValueError("registered account protocol or execution changed during replay")
        # Revalidate archived raw bytes, normalized snapshot and frozen readiness.
        load_frozen_odd_lot_study(study)
        if _source_guard is not None:
            _source_guard(_stage)

    verify_sources("preflight")
    return _replay_account(account_path, data, research, base, identity,
                           create=create, snapshot_root=snapshot_root, _fault=verify_sources,
                           _read_only=_read_only)
