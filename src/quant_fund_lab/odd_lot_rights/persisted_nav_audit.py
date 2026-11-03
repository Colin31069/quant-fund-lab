"""Read-only independent NAV checks on completed SQL records and external marks."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .checkpoint_nav_audit import audit_checkpoint_nav
from .engine_checkpoint_codec import decode_engine_rights

if TYPE_CHECKING:
    from .durable_day_workflow import DurableRightsDay
    from .engine_ledger import RightsEngineLedger


@dataclass(frozen=True)
class PersistedNAVAudit:
    sessions_checked: int
    scope: str = "independent_persisted_nav_equations_against_external_marks"


def verify_persisted_nav(ledger: RightsEngineLedger,
                         days: tuple[DurableRightsDay, ...]) -> PersistedNAVAudit:
    """Do not call production engine, day replay or valuation functions.

    External days supply complete raw closes/currencies and explicit marks.
    Their source/publication and locked-policy identities must be authenticated
    separately. This audit establishes value equations, not strategy validity.
    """
    if type(days) is not tuple:
        raise TypeError("persisted NAV audit requires immutable external day inputs")
    ledger.verify()
    rows = ledger.connection.execute("""SELECT c.session,c.state_json,e.events_json
        FROM rights_checkpoints c JOIN rights_events e USING(session) ORDER BY c.session""").fetchall()
    if len(rows) != len(days):
        raise ValueError("persisted NAV audit needs every completed session's external marks")
    for day, (session, payload, events) in zip(days, rows):
        inputs = day.request.inputs
        index = inputs.signal_index+1
        if str(inputs.data.close.index[index].date()) != session or inputs.config.base_currency != "TWD":
            raise ValueError("persisted NAV audit external session/currency differs")
        recorded = json.loads(events).get("rights_nav")
        if not isinstance(recorded, list) or len(recorded) != 1:
            raise ValueError("persisted NAV audit needs one recorded joined NAV")
        prices = inputs.data.raw_close.iloc[index]
        codes = inputs.data.currency_codes
        currencies = {symbol: (str(codes.iloc[index][symbol]) if codes is not None
            else "TWD" if symbol.endswith((".TW", ".TWO")) else "unknown") for symbol in prices.index}
        audit = audit_checkpoint_nav(decode_engine_rights(payload), recorded[0],
            [asdict(row) for row in day.securities], [asdict(row) for row in day.rights],
            {symbol: Decimal(str(value)) for symbol, value in prices.items()}, currencies, as_of=day.valuation_at)
        if not audit.passed:
            raise ValueError("persisted independent NAV audit failed: "+"; ".join(audit.issues))
    return PersistedNAVAudit(len(rows))
