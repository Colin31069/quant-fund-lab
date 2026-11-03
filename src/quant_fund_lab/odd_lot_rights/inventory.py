"""Join rights cash and typed security lots in one immutable posting boundary."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .audit import Movement, audit_rights
from .types import RightsBook, RightsTransition, day, number, quantity


@dataclass(frozen=True)
class SecurityLot:
    right_key: str
    security_id: str
    units: int
    tradable_session: str

    def __post_init__(self) -> None:
        quantity(self.units)
        day(self.tradable_session)
        if not self.right_key or not self.security_id or self.units == 0:
            raise ValueError("rights inventory requires stable identities and positive units")


def _lot_key(lot):
    return lot.right_key, lot.security_id, lot.tradable_session


def _apply(lots, movements):
    """Consume owned same-leg receipts; preserve per-lot trading restrictions."""
    balances = {_lot_key(row):row.units for row in lots}
    for _, side, key, security, units, tradable in movements:
        if side == "credit":
            lot_key = key,security,tradable
            balances[lot_key] = balances.get(lot_key,0)+units
        else:
            remaining = units
            for lot_key in sorted(balances):
                if lot_key[:2] != (key,security):
                    continue
                used = min(remaining,balances[lot_key])
                balances[lot_key] -= used
                remaining -= used
            if remaining:
                raise ValueError("rights debit exceeds actually owned same-leg security inventory")
    return tuple(SecurityLot(*key[:2],units,key[2]) for key,units in sorted(balances.items()) if units)


@dataclass(frozen=True)
class RightsInventory:
    """One cash balance: book.cash, never a second portfolio cash accumulator.

    Initial lots are explicitly anchored separately from delivered rights.
    This first boundary admits rights movements only; trading/settlement cash
    flows and source-backed opening inventory require their later adapter.
    """

    initial_cash: Decimal
    initial_lots: tuple[SecurityLot, ...]
    book: RightsBook
    lots: tuple[SecurityLot, ...]
    postings: tuple[Movement, ...] = ()

    def __post_init__(self) -> None:
        number(self.initial_cash)
        if not isinstance(self.book,RightsBook):
            raise TypeError("rights inventory requires a typed book")
        for rows in (self.initial_lots,self.lots):
            if type(rows) is not tuple or any(not isinstance(row,SecurityLot) for row in rows):
                raise TypeError("rights inventory lots must be immutable typed tuples")
            if tuple(sorted(rows,key=_lot_key)) != rows or len({_lot_key(row) for row in rows}) != len(rows):
                raise ValueError("rights inventory lots require unique canonical ordering")
        audit = audit_rights(self.book,initial_cash=self.initial_cash,recorded_movements=self.postings)
        if not audit.passed:
            raise ValueError("rights financial/posting audit failed: "+"; ".join(audit.issues))
        reconstructed = self.initial_lots
        for receipt in self.book.receipts:
            command = json.loads(receipt.command_json)
            if command["kind"] == "grant":
                owned = sum(row.units for row in reconstructed
                            if row.security_id == command["event"]["parent_security_id"])
                if owned != command["eligible_units"]:
                    raise ValueError("rights original grant ownership differs from pre-event inventory")
            elif command["kind"] == "portfolio_lot_session":
                from dataclasses import asdict

                from .codec import canonical

                if canonical([asdict(row) for row in reconstructed]) != canonical(
                        command["terms"]["lot_journal"]["initial_lots"]):
                    raise ValueError("lot session initial lots differ from reconstructed account prefix")
            elif command["kind"] == "portfolio_session":
                owned = {}
                for row in reconstructed:
                    owned[row.security_id] = owned.get(row.security_id,0)+row.units
                if owned != dict(command["terms"]["link"]["shares_before"]):
                    raise ValueError("session original holdings differ from reconstructed pre-event inventory")
                available = {}
                for lot in reconstructed:
                    if lot.tradable_session <= command["terms"]["link"]["session"]:
                        key = lot.right_key,lot.security_id
                        available[key] = available.get(key,0)+lot.units
                for action,side,key,security,units,_ in self.postings:
                    if action != receipt.action_id or side != "debit":
                        continue
                    lot_key = key,security
                    if units > available.get(lot_key,0):
                        raise ValueError("session recorded debit exceeds command-time tradable lots")
                    available[lot_key] -= units
            reconstructed = _apply(reconstructed,tuple(
                row for row in self.postings if row[0] == receipt.action_id))
        if _apply(self.initial_lots,self.postings) != self.lots:
            raise ValueError("rights owned inventory differs from anchored lots and audited postings")

    @property
    def cash(self) -> Decimal:
        return self.book.cash

    def tradable_units(self, security_id: str, session: str) -> int:
        day(session)
        if self.book.through is not None:
            from zoneinfo import ZoneInfo

            from .types import clock

            completed = clock(self.book.through).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
            if session < completed:
                raise ValueError("inventory query cannot expose future holdings to a past session")
        return sum(row.units for row in self.lots
                   if row.security_id == security_id and row.tradable_session <= session)


def post_rights_transition(account: RightsInventory, result: RightsTransition) -> RightsInventory:
    """Audit and publish cash, security debits and credits as one returned value.

    No mutation or I/O occurs before all checks pass. Only a single command
    extending this exact account prefix can be posted; matching replays return
    the same object and may not contain inventory or cash deltas.
    """
    # Recheck even callers that bypassed frozen-dataclass construction.
    RightsInventory(account.initial_cash,account.initial_lots,account.book,account.lots,account.postings)
    if not isinstance(result,RightsTransition):
        raise TypeError("posting requires a typed rights transition")
    if not result.applied:
        if result.book != account.book or result.cash_delta or result.credits or result.debits:
            raise ValueError("rights no-op cannot alter cash, inventory or checkpoint")
        if result.action_id not in {row.action_id for row in account.book.receipts}:
            raise ValueError("rights no-op requires a previously completed action")
        return account
    if (result.book.receipts[:-1] != account.book.receipts
            or len(result.book.receipts) != len(account.book.receipts)+1
            or result.book.receipts[-1].action_id != result.action_id):
        raise ValueError("rights transition does not extend the current account command prefix")
    with localcontext() as context:
        context.prec = 80
        if result.book.cash-account.cash != result.cash_delta:
            raise ValueError("rights transition cash delta differs from the single authoritative balance")
    audit = audit_rights(result.book,initial_cash=account.initial_cash)
    if not audit.passed:
        raise ValueError("rights financial audit failed: "+"; ".join(audit.issues))
    if audit.expected_movements[:len(account.postings)] != account.postings:
        raise ValueError("rights transition changes completed inventory postings")
    added = audit.expected_movements[len(account.postings):]
    declared = tuple((result.action_id,"debit",row.right_key,row.security_id,row.units,None)
                     for row in result.debits)+tuple(
        (result.action_id,"credit",row.right_key,row.security_id,row.units,row.tradable_session)
        for row in result.credits)
    if declared != added:
        raise ValueError("rights transition credits/debits differ from independently reconstructed command")
    command = json.loads(result.book.receipts[-1].command_json)
    if command["kind"] == "grant":
        parent = command["event"]["parent_security_id"]
        owned = sum(row.units for row in account.lots if row.security_id == parent)
        if owned != command["eligible_units"]:
            raise ValueError("entitlement ownership differs from current pre-event inventory")
    return RightsInventory(account.initial_cash,account.initial_lots,result.book,
                           _apply(account.lots,added),audit.expected_movements)
