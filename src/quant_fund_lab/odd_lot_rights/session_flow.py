"""Post real, reconciled engine session results into the same rights cash/inventory."""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from decimal import localcontext
from typing import TYPE_CHECKING

from .codec import canonical
from .inventory import RightsInventory, post_rights_transition
from .session_link import reconcile_session_portfolio
from .transitions import ZERO, _begin, _finish
from .types import SecurityCredit, SecurityDebit, evidence

if TYPE_CHECKING:
    from ..odd_lot_paper.session import OddLotSessionInput, OddLotSessionResult


def post_engine_session(account: RightsInventory, action_id: str, inputs: OddLotSessionInput,
                         result: OddLotSessionResult, *, as_of: str, available_at: str,
                         evidence_sha256: tuple[str, ...]) -> RightsInventory:
    """Reconcile actual engine output, then atomically return one combined account.

    Supplied evidence IDs need authentication by the outer source/SQL workflow.
    This boundary never executes a broker order or credits unsettled sale cash.
    """
    link = reconcile_session_portfolio(inputs,result)
    evidence(available_at,evidence_sha256)
    before,after = dict(link.shares_before),dict(link.shares_after)
    old = next((row for row in account.book.receipts if row.action_id == action_id),None)
    if old is not None:
        command = json.loads(old.command_json)
        if command["kind"] != "portfolio_session":
            raise ValueError("session action identity already used for another command")
        terms = command["terms"]
        expected = {"available_at":available_at,"evidence_sha256":evidence_sha256,"link":asdict(link)}
        actual = {key:terms[key] for key in expected}
        if canonical(expected) != canonical(actual) or command["as_of"] != as_of:
            raise ValueError("completed engine session source/result payload changed")
        started = _begin(account.book,action_id,as_of,command | {"as_of":as_of})
        if started is not None:
            raise ValueError("completed engine session is not a verified no-op")
        from .types import RightsTransition

        return post_rights_transition(account,RightsTransition(account.book,action_id,ZERO,applied=False))
    if any(json.loads(row.command_json).get("kind") == "portfolio_session"
           and json.loads(row.command_json)["terms"]["link"]["session"] == link.session for row in account.book.receipts):
        raise ValueError("engine session already completed under another action identity")
    if account.cash != link.cash_before:
        raise ValueError("engine prior cash differs from authoritative rights cash")
    owned = {}
    for lot in account.lots:
        owned[lot.security_id] = owned.get(lot.security_id,0)+lot.units
    if owned != before:
        raise ValueError("engine prior holdings differ from authoritative rights inventory")
    tradable = {security:account.tradable_units(security,link.session) for security in owned}
    for row in result.actions:
        if row["action"] == "stock_split":
            security = row["symbol"]
            tradable[security] = math.floor(tradable.get(security,0)*row["ratio_or_amount"]+1e-12)
    for fill in result.fills:
        security,units = fill["symbol"],fill["quantity"]
        if fill["side"] == "SELL":
            if units > tradable.get(security,0):
                raise ValueError("engine fill sells units before their actual lot tradability")
            tradable[security] -= units
        else:
            tradable[security] = tradable.get(security,0)+units
    debits,credits = [],[]
    for security in sorted(set(before)|set(after)):
        delta = after.get(security,0)-before.get(security,0)
        if delta > 0:
            credits.append(SecurityCredit("session:"+action_id+":"+security,security,delta,link.session))
        elif delta < 0:
            remaining = -delta
            for lot in account.lots:
                if lot.security_id != security or lot.tradable_session > link.session:
                    continue
                units = min(remaining,lot.units)
                if units:
                    debits.append(SecurityDebit(lot.right_key,security,units))
                    remaining -= units
            if remaining:
                raise ValueError("engine decrease exceeds currently tradable owned units")
    movements = [("debit",row.right_key,row.security_id,row.units,None) for row in debits]+[
        ("credit",row.right_key,row.security_id,row.units,row.tradable_session) for row in credits]
    terms = {"available_at":available_at,"evidence_sha256":evidence_sha256,
             "link":asdict(link),"movements":movements}
    command = {"kind":"portfolio_session","terms":terms}
    started = _begin(account.book,action_id,as_of,command)
    if started is None:
        raise ValueError("engine session action unexpectedly completed")
    receipt,_ = started
    with localcontext() as context:
        context.prec = 80
        transition = _finish(account.book,action_id,as_of,receipt,account.book.positions,
                             link.cash_after,tuple(credits),tuple(debits))
    return post_rights_transition(account,transition)
