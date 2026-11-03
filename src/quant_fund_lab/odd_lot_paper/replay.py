"""Internal durable replay mechanics; public study/snapshot/audit preflight is pending."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from ..config import BacktestConfig
from ..data import MarketData
from ..execution import PortfolioState, prior_session_liquidity
from ..odd_lot_execution import validate_instrument_rules
from ..odd_lot_research import (
    OddLotResearchConfig,
    odd_lot_backtest_config,
    validate_raw_split_basis,
)
from ..replay_provenance import replay_session_data_fingerprint
from .audit import audit_accounting
from .bridge import HistoricalSessionState, capture_session_state, restore_session_state
from .event_codec import encode_event
from .forward_binding import ForwardReplayBinding
from .ledger import OddLotLedger, SessionCommit, canonical, digest
from .session import OddLotSessionInput, run_odd_lot_session
from .snapshots import publish_snapshot, verify_snapshot_link
from .source_checks import risk_input_evidence, validate_source_events
from .types import OddLotSessionState


@dataclass(frozen=True)
class ReplayIdentity:
    protocol_id: str
    execution_revision: str
    calendar_revision: str
    origin_session: str

    def __post_init__(self) -> None:
        import re

        if not re.fullmatch(r"[0-9a-f]{64}", self.protocol_id):
            raise ValueError("replay requires a frozen protocol SHA-256")
        if not self.execution_revision or not self.calendar_revision:
            raise ValueError("replay requires execution and calendar revisions")
        if pd.Timestamp(self.origin_session).date().isoformat() != self.origin_session:
            raise ValueError("origin must be a canonical session date")


@dataclass(frozen=True)
class ReplayResult:
    checkpoint: OddLotSessionState
    committed_sessions: int
    last_digest: str


def _replay_account(path: str | Path, data: MarketData, research: OddLotResearchConfig,
                    base_config: BacktestConfig, identity: ReplayIdentity, *, create: bool = False,
                    snapshot_root: str | Path | None = None,
                    observation: ForwardReplayBinding | None = None,
                    _read_only: bool = False,
                    _fault: Callable[[str], None] | None = None) -> ReplayResult:
    """Replay complete input history; reject altered completed prefixes before writes.

    This internal layer does not authenticate a study's readiness or external
    snapshot files. A public account workflow must supply those preflight gates.
    """
    dates = data.close.index
    if _read_only and create:
        raise ValueError("read-only replay cannot create an account")
    if not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("durable input sessions must be unique and chronological")
    origin = pd.Timestamp(identity.origin_session)
    if origin not in dates:
        raise ValueError("complete replay history must contain the original checkpoint")
    index = int(dates.get_loc(origin))
    if observation is not None:
        if snapshot_root is None:
            raise ValueError("forward replay requires normalized snapshots")
        if (identity.protocol_id != observation.plan.protocol_id
                or identity.execution_revision != observation.plan.execution_id
                or identity.calendar_revision != observation.evidence.calendar_revision):
            raise ValueError("forward replay identity differs from registered evidence")
        observation.verify_configuration(research, base_config)
        observation.verify_current(data, identity.origin_session)
    config = odd_lot_backtest_config(base_config, research)
    if index < config.strategy.warmup_days - 1:
        raise ValueError("replay history does not satisfy the original warmup")
    validate_raw_split_basis(data)
    validate_instrument_rules(data.symbols, research.instrument_rules)
    if any((config.strategy.factor_alpha_enabled, config.strategy.volatility_target_enabled,
            config.strategy.cvar_control_enabled, config.strategy.drawdown_control_enabled)):
        raise ValueError("unsupported odd-lot portfolio overlays")
    config_json = canonical({"identity": asdict(identity), "research": asdict(research),
        "execution": asdict(config), "symbols": data.symbols,
        "first_input_session": dates[0].isoformat(), "transition_rule": "odd_lot_session_v3_risk",
        "snapshot_root": str(Path(snapshot_root).resolve()) if snapshot_root is not None else None})
    if observation is not None:
        config_json = canonical({**json.loads(config_json), "observation":observation.locked_config()})
    fingerprints = {}
    chain = digest("odd_lot_prefix_v1")
    for stamp in dates:
        daily = replay_session_data_fingerprint(data, stamp, data.raw_close.loc[stamp], None)
        chain = digest(canonical([chain, daily]))
        fingerprints[stamp.date().isoformat()] = chain
    runtime = HistoricalSessionState(PortfolioState(float(config.initial_cash)), {}, {}, set(), [], [], False)
    initial = capture_session_state(runtime, session=identity.origin_session,
        origin_session=identity.origin_session, session_offset=0, completed_index=index)
    # Bind warmup bars even before the first executed session.
    config_json = canonical({**json.loads(config_json),
                             "initial_input_digest": fingerprints[identity.origin_session]})
    ledger = OddLotLedger(path, config_json=config_json, initial_state=initial if create else None,
                         read_only=_read_only)
    def validate_account(connection):
        if observation is not None:
            observation.verify_ledger(connection)
        audit = audit_accounting(path, _connection=connection)
        if not audit.passed:
            raise ValueError("independent accounting audit failed: "+"; ".join(audit.issues))
        latest_session = connection.execute("SELECT max(session) FROM session_checkpoints").fetchone()[0]
        through = latest_session or identity.origin_session
        current_chain = digest("odd_lot_prefix_v1")
        for stamp in data.close.index:
            current_chain = digest(canonical([current_chain, replay_session_data_fingerprint(
                data, stamp, data.raw_close.loc[stamp], None)]))
            if stamp.date().isoformat() == through:
                break
        if current_chain != fingerprints[through]:
            raise ValueError("input data changed during account transaction")
        if latest_session is not None:
            validate_source_events(ledger._events(latest_session), data, latest_session, asdict(research))
        if snapshot_root is not None and latest_session is not None:
            links = ledger._events(latest_session).get("snapshot", [])
            if len(links) != 1:
                raise ValueError("transaction snapshot linkage is absent")
            verify_snapshot_link(snapshot_root, links[0])
    try:
        latest, previous = ledger.verify()
        validate_account(ledger.connection)
        rows = ledger.connection.execute("SELECT session,input_digest FROM session_checkpoints ORDER BY session").fetchall()
        for session, recorded in rows:
            if fingerprints.get(session) != recorded:
                raise ValueError("completed input prefix changed or is unavailable")
            validate_source_events(ledger._events(session), data, session, asdict(research))
            if snapshot_root is not None:
                links = ledger._events(session).get("snapshot", [])
                if len(links) != 1:
                    raise ValueError("completed session snapshot linkage is absent")
                archived = verify_snapshot_link(snapshot_root, links[0])
                archived_chain = digest("odd_lot_prefix_v1")
                for stamp in archived.close.index:
                    archived_chain = digest(canonical([archived_chain, replay_session_data_fingerprint(
                        archived, stamp, archived.raw_close.loc[stamp], None)]))
                    if stamp.date().isoformat() == session:
                        break
                else:
                    raise ValueError("linked snapshot does not include completed session")
                if archived_chain != recorded:
                    raise ValueError("linked snapshot input prefix differs from completed session")
        if latest.session not in fingerprints:
            raise ValueError("completed account history is absent from supplied data")
        completed = int(dates.get_loc(pd.Timestamp(latest.session)))
        if completed - index != latest.session_offset:
            raise ValueError("historical session sequence changed")
        if _read_only and completed != len(dates)-1:
            raise ValueError("read-only replay cannot advance beyond the last completed session")
        runtime = restore_session_state(latest, completed_index=completed)
        liquidity = prior_session_liquidity(data.volume)
        count = 0
        link = publish_snapshot(data, snapshot_root) if snapshot_root is not None and completed < len(dates)-1 else None
        for position in range(completed, len(dates) - 1):
            result = run_odd_lot_session(OddLotSessionInput(
                runtime, data, research, config, position, index, liquidity))
            session = dates[position+1].date().isoformat()
            checkpoint = capture_session_state(result.runtime, session=session,
                origin_session=identity.origin_session, session_offset=position+1-index,
                completed_index=position+1)
            groups = {name: [encode_event(row) for row in getattr(result, name)]
                      for name in ("signals", "orders", "fills", "actions", "terminal_events")}
            groups["nav"] = [encode_event(result.nav)]
            groups["valuation"] = [encode_event(data.raw_close.loc[dates[position+1]].to_dict())]
            groups["risk_inputs"] = [encode_event(risk_input_evidence(data, position))]
            if observation is not None:
                groups["observation"] = [encode_event(observation.record())]
            if link is not None:
                groups["snapshot"] = [link]
                verify_snapshot_link(snapshot_root, link)
            previous = ledger.commit(SessionCommit(checkpoint, fingerprints[session], canonical(groups), previous),
                                     _fault=_fault, _validate=validate_account)
            runtime, latest = result.runtime, checkpoint
            count += 1
        return ReplayResult(latest, count, previous)
    finally:
        ledger.close()
