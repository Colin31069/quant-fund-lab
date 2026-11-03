"""Read-only risk lifecycle equations for SQL checkpoints and external requests."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ..odd_lot_paper.event_codec import decode_event
from ..odd_lot_paper.serialization import decode_state
from .day_risk_audit import audit_day_risk, engine_risk_groups
from .engine_checkpoint_codec import decode_engine_rights

if TYPE_CHECKING:
    from .durable_day_workflow import DurableRightsDay
    from .engine_ledger import RightsEngineLedger


@dataclass(frozen=True)
class PersistedRiskAudit:
    sessions_checked: int
    scope: str = "independent_persisted_stop_pending_declared_risk_transfer_equations"


def verify_persisted_risk(ledger: RightsEngineLedger,
                          days: tuple[DurableRightsDay, ...]) -> PersistedRiskAudit:
    """Use external source/declared mappings; never rerun the production engine.

    Old records without engine-close risk evidence are insufficient and fail;
    they are never silently repaired. Model weights are recorded signal inputs,
    not independent alpha verification. Source/policy authenticity is separate.
    """
    if type(days) is not tuple:
        raise TypeError("persisted risk audit needs immutable original day requests")
    ledger.verify()
    rows = ledger.connection.execute("""SELECT c.session,c.state_json,e.events_json FROM rights_checkpoints c
        JOIN rights_events e USING(session) ORDER BY c.session""").fetchall()
    if len(rows) != len(days):
        raise ValueError("persisted risk audit requires every original completed day")
    previous = ledger.initial
    for day, (session, payload, encoded) in zip(days, rows):
        inputs = day.request.inputs
        if str(inputs.data.close.index[inputs.signal_index+1].date()) != session:
            raise ValueError("persisted risk external request session differs")
        checkpoint = decode_engine_rights(payload)
        events = json.loads(encoded)
        evidence = events.get("risk_audit")
        if not isinstance(evidence, list) or len(evidence) != 1 or set(evidence[0]) != {"engine_close"}:
            raise ValueError("persisted risk audit lacks original engine-close checkpoint")
        close = decode_state(evidence[0]["engine_close"])
        # Only observed inputs come from the external request. Business signals,
        # fills and actions are read from the original stored event records.
        from types import SimpleNamespace

        business = SimpleNamespace(**{name: tuple(decode_event(row) for row in events[name])
                                      for name in ("signals", "fills", "actions")})
        groups = engine_risk_groups(inputs, business)
        result = audit_day_risk(previous.engine, close, checkpoint.engine, checkpoint.account,
            day.request.action_id, groups, asdict(inputs.research), day.request.opening_stops,
            day.request.conversion_risks)
        if not result.passed:
            raise ValueError("persisted independent risk audit failed: "+"; ".join(result.issues))
        previous = checkpoint
    return PersistedRiskAudit(len(rows))
