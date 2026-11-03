"""Project audited rights changes back onto an existing completed engine state."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..odd_lot_paper.bridge import HistoricalSessionState, capture_session_state
from ..odd_lot_paper.types import OddLotSessionState, StopState
from .conversion_risk import ReceiptRiskTransfer, transfer_conversion_risk
from .inventory import RightsInventory
from .types import clock, day


@dataclass(frozen=True)
class RightsSessionProjection:
    """An immutable next-signal input, including separately enforced sale capacity.

    The checkpoint contains all owned shares for valuation. Its tradable_units
    must also be enforced by the later execution adapter; restoring this state
    alone does not authorize selling locked lots. No SQL or caller state changes.
    """

    checkpoint: OddLotSessionState
    exact_cash: Decimal
    tradable_units: tuple[tuple[str, int], ...]
    source_action_id: str
    rights_through: str


def project_rights_session(
    account: RightsInventory,
    runtime: HistoricalSessionState,
    *,
    completed_session: str,
    origin_session: str,
    session_offset: int,
    completed_index: int,
    as_of: str,
    opening_stops: tuple[StopState, ...] = (),
    conversion_risks: tuple[ReceiptRiskTransfer, ...] = (),
) -> RightsSessionProjection:
    """Replace cash/owned shares after rights commands, retaining engine history.

    Runtime must match the latest recorded engine close's cash and holdings.
    This anchors the projection before applying rights changes, rather than
    accepting an arbitrary stale runtime. Stops for newly held identities must
    be explicitly supplied, never inferred from the parent security. Timing and
    source authentication remain the outer workflow's responsibility.
    """
    RightsInventory(account.initial_cash, account.initial_lots, account.book,
                    account.lots, account.postings)
    day(completed_session)
    stamp = clock(as_of)
    if stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != completed_session:
        raise ValueError("projection processing date must match the completed signal session")
    if account.book.through is None or clock(account.book.through) > stamp:
        raise ValueError("projection cannot expose future rights knowledge")
    sessions = [(row, json.loads(row.command_json)) for row in account.book.receipts
                if json.loads(row.command_json)["kind"] in {"portfolio_session", "portfolio_lot_session"}]
    if not sessions:
        raise ValueError("projection requires a reconciled engine-session anchor")
    receipt, command = sessions[-1]
    link = command["terms"]["link"]
    if link["session"] != completed_session:
        raise ValueError("projection engine anchor is not the completed signal session")
    owned_before = {symbol: units for symbol, units in runtime.portfolio.shares.items() if units}
    if (Decimal(str(runtime.portfolio.cash)) != Decimal(link["cash_after"])
            or owned_before != dict(link["shares_after"])):
        raise ValueError("projection runtime differs from its recorded engine close")
    owned = {}
    for lot in account.lots:
        owned[lot.security_id] = owned.get(lot.security_id, 0) + lot.units
    cash = float(account.cash)
    if not math.isfinite(cash) or Decimal(str(cash)) != account.cash:
        raise ValueError("rights cash cannot cross the engine float boundary without precision loss")
    checkpoint = capture_session_state(runtime, session=completed_session,
        origin_session=origin_session, session_offset=session_offset,
        completed_index=completed_index)
    checkpoint = transfer_conversion_risk(account, checkpoint, receipt.action_id, conversion_risks)
    if (type(opening_stops) is not tuple
            or any(not isinstance(row, StopState) for row in opening_stops)):
        raise TypeError("projection opening stops require explicit immutable typed records")
    stops = {row.symbol: row for row in checkpoint.stops if row.symbol in owned}
    missing = set(owned) - set(stops)
    if (len({row.symbol for row in opening_stops}) != len(opening_stops)
            or {row.symbol for row in opening_stops} != missing):
        raise ValueError("projection requires exactly the new holdings' explicit stop states")
    if set(owned) & set(checkpoint.terminated):
        raise ValueError("projection cannot reactivate a terminated security identity")
    if any(row.symbol not in owned and row.side == "SELL" for row in checkpoint.pending):
        raise ValueError("projection requires an explicit policy for pending sales of removed holdings")
    stops.update((row.symbol, row) for row in opening_stops)
    projected = replace(checkpoint, cash=cash, shares=tuple(sorted(owned.items())),
                        stops=tuple(stops[key] for key in sorted(stops)))
    return RightsSessionProjection(projected, account.cash,
        tuple((key, account.tradable_units(key, completed_session)) for key in sorted(owned)),
        receipt.action_id, account.book.through)
