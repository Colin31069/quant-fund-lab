"""Bind real day execution and explicit NAV to the combined atomic SQL ledger."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable

from ..odd_lot_paper.bridge import capture_session_state
from ..odd_lot_paper.event_codec import encode_event
from .codec import canonical, fingerprint
from .day_workflow import RightsDayRequest, RightsDayResult, advance_rights_day
from .engine_checkpoint import RightsEngineCheckpoint
from .engine_checkpoint_codec import encode_engine_rights
from .engine_ledger import RightsEngineLedger
from .engine_ledger_types import RightsEngineCommit
from .inventory_valuation import SecurityMark
from .session_nav import RightsSessionNAV, value_session_nav
from .valuation import RightsMark


@dataclass(frozen=True)
class DurableRightsDay:
    request: RightsDayRequest
    securities: tuple[SecurityMark, ...]
    rights: tuple[RightsMark, ...]
    valuation_at: str

    def __post_init__(self) -> None:
        from .types import clock

        clock(self.valuation_at)
        if not isinstance(self.request, RightsDayRequest):
            raise TypeError("durable day requires a typed day request")
        for rows, cls in ((self.securities, SecurityMark), (self.rights, RightsMark)):
            if type(rows) is not tuple or any(not isinstance(row, cls) for row in rows):
                raise TypeError("durable valuation requires immutable typed marks")


@dataclass(frozen=True)
class DurableRightsDayResult:
    day: RightsDayResult
    nav: RightsSessionNAV
    commit: RightsEngineCommit
    digest: str


def day_settings_sha256(day: DurableRightsDay) -> str:
    """Bind shared engine/research assumptions, plus the explicit lot policy."""
    request = day.request
    return fingerprint({"research": asdict(request.inputs.research),
                        "config": asdict(request.inputs.config), "lot_policy": asdict(request.lot_policy)})


def day_input_sha256(day: DurableRightsDay) -> str:
    """Hash complete supplied market frames, request clocks/commands and marks.

    This first workflow binds the entire supplied market frame. Future extension
    therefore requires a separately reviewed input contract; it never silently
    permits rewriting already provided bars. Hashes do not authenticate sources.
    """
    request, inputs = day.request, day.request.inputs
    source = {}
    for name in inputs.data.__dataclass_fields__:
        value = getattr(inputs.data, name)
        if hasattr(value, "itertuples"):
            source[name] = {"index": encode_event(tuple(value.index)),
                "columns": encode_event(tuple(value.columns)),
                "rows": [encode_event(row) for row in value.itertuples(index=False, name=None)]}
        else:
            source[name] = encode_event(value)
    return fingerprint({"source": source, "settings": day_settings_sha256(day),
        "signal_index": inputs.signal_index, "origin_index": inputs.origin_index,
        "passive_without_risk_estimate": inputs.passive_without_risk_estimate,
        "prior_liquidity": {"index": encode_event(tuple(inputs.prior_liquidity.index)),
            "columns": encode_event(tuple(inputs.prior_liquidity.columns)),
            "rows": [encode_event(row) for row in inputs.prior_liquidity.itertuples(index=False, name=None)]},
        "action_id": request.action_id, "events": [asdict(row) for row in request.events],
        "clocks": [request.opening_at, request.close_at, request.available_at, request.projection_at],
        "evidence": request.evidence_sha256, "commands": [asdict(row) for row in request.commands],
        "stops": [asdict(row) for row in request.opening_stops],
        "conversion_risks": [asdict(row) for row in request.conversion_risks],
        "security_marks": [asdict(row) for row in day.securities],
        "rights_marks": [asdict(row) for row in day.rights], "valuation_at": day.valuation_at})


def prepare_durable_day(previous: RightsEngineCheckpoint, previous_digest: str,
                         day: DurableRightsDay) -> tuple[RightsDayResult, RightsSessionNAV, RightsEngineCommit]:
    """Re-execute from the verified previous checkpoint before any SQL mutation."""
    if not isinstance(day, DurableRightsDay) or not isinstance(day.request, RightsDayRequest):
        raise TypeError("durable day requires a typed complete request")
    request, inputs = day.request, day.request.inputs
    if request.recorded_before is not None:
        raise ValueError("durable replay uses historical predecessor, not a caller-labelled prefix")
    dates = inputs.data.close.index
    i = inputs.signal_index
    if type(i) is not int or not 0 <= inputs.origin_index <= i < len(dates)-1:
        raise ValueError("durable day requires valid source indexes")
    captured = capture_session_state(inputs.runtime, session=str(dates[i].date()),
        origin_session=str(dates[inputs.origin_index].date()), session_offset=i-inputs.origin_index,
        completed_index=i)
    if captured != previous.engine or request.account != previous.account:
        raise ValueError("durable day engine/account does not match verified predecessor")
    source_before = day_input_sha256(day)
    result = advance_rights_day(request)
    from dataclasses import replace

    nav = value_session_nav(result.account.inventory,
        replace(inputs, sale_limits=result.execution.projection.sale_limits), result.execution.result,
        day.securities, day.rights, as_of=day.valuation_at)
    checkpoint = RightsEngineCheckpoint(result.projection.checkpoint, result.account)
    from .day_risk_audit import audit_day_risk, engine_risk_groups

    engine_close = capture_session_state(result.execution.result.runtime,
        session=str(dates[i+1].date()), origin_session=previous.engine.origin_session,
        session_offset=previous.engine.session_offset+1, completed_index=i+1)
    risk_checked = audit_day_risk(previous.engine, engine_close, checkpoint.engine, result.account,
        request.action_id, engine_risk_groups(inputs, result.execution.result), asdict(inputs.research),
        request.opening_stops, request.conversion_risks)
    if not risk_checked.passed:
        raise ValueError("durable independent risk audit failed: "+"; ".join(risk_checked.issues))
    from decimal import Decimal

    from .checkpoint_nav_audit import audit_checkpoint_nav

    prices = inputs.data.raw_close.iloc[i+1]
    codes = inputs.data.currency_codes
    currencies = {symbol: (str(codes.iloc[i+1][symbol]) if codes is not None
                  else "TWD" if symbol.endswith((".TW", ".TWO")) else "unknown") for symbol in prices.index}
    checked_nav = audit_checkpoint_nav(checkpoint, asdict(nav),
        [asdict(row) for row in day.securities], [asdict(row) for row in day.rights],
        {symbol: Decimal(str(value)) for symbol, value in prices.items()}, currencies, as_of=day.valuation_at)
    if not checked_nav.passed:
        raise ValueError("durable independent NAV audit failed: "+"; ".join(checked_nav.issues))
    events = {name: [encode_event(row) for row in getattr(result.execution.result, name)] for name in (
        "signals", "orders", "fills", "actions", "terminal_events")}
    events["engine_nav"] = [encode_event(result.execution.result.nav)]
    events["rights_nav"] = [asdict(nav)]
    from ..odd_lot_paper.serialization import encode_state

    events["risk_audit"] = [{"engine_close": encode_state(engine_close)}]
    events["workflow"] = [{"schema_version": 1, "action_id": request.action_id,
        "commands": [asdict(row) for row in request.commands],
        "conversion_risks": [asdict(row) for row in request.conversion_risks],
        "opening_stops": [asdict(row) for row in request.opening_stops],
        "security_marks": [asdict(row) for row in day.securities],
        "rights_marks": [asdict(row) for row in day.rights], "valuation_at": day.valuation_at}]
    if day_input_sha256(day) != source_before:
        raise ValueError("durable day inputs changed during execution/valuation")
    return result, nav, RightsEngineCommit(checkpoint, source_before, canonical(events), previous_digest)


def commit_rights_day(ledger: RightsEngineLedger, day: DurableRightsDay, *,
                      _fault: Callable[[str], None] | None = None) -> DurableRightsDayResult:
    """Execute, value and commit one combined checkpoint/events/completion.

    Historical no-op replay belongs to verify_durable_days, using original
    predecessor requests; this entry advances only the latest committed state.
    Execution/calendar/protocol identities are externally pinned in ledger config.
    """
    previous, digest = ledger.verify()
    config = json.loads(ledger.config_json)
    if day_settings_sha256(day) != config["settings_sha256"]:
        raise ValueError("durable day settings differ from locked engine/lot assumptions")
    result, nav, record = prepare_durable_day(previous, digest, day)
    def validate(_db):
        if day_input_sha256(day) != record.input_fingerprint:
            raise ValueError("durable day inputs changed before commit")

    def guarded_fault(phase):
        if _fault is not None:
            _fault(phase)
        validate(None)

    identity = ledger.commit(record, _fault=guarded_fault, _validate=validate)
    if encode_engine_rights(ledger.verify()[0]) != encode_engine_rights(record.checkpoint):
        raise ValueError("committed durable day differs from its validated checkpoint")
    return DurableRightsDayResult(result, nav, record, identity)
