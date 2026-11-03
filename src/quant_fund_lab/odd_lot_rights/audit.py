"""Independent exact cash/quantity reconstruction from canonical rights commands."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from typing import Optional

from .audit_reconstruction import reconstruct
from .codec import canonical, decode_book, encode_book
from .types import RightsBook, day, number, quantity

Movement = tuple[str, str, str, str, int, Optional[str]]


def _valid_postings(rows) -> None:
    if type(rows) is not tuple:
        raise TypeError("inventory posting log must be an immutable tuple")
    for row in rows:
        if type(row) is not tuple or len(row) != 6:
            raise ValueError("inventory posting requires the exact six-field schema")
        action, side, key, security, units, tradable = row
        if (any(not isinstance(value,str) or not value for value in (action,side,key,security))
                or side not in {"credit","debit"}):
            raise ValueError("inventory posting identities or direction invalid")
        quantity(units)
        if not units:
            raise ValueError("inventory posting units must be positive")
        if side == "credit":
            day(tradable)
        elif tradable is not None:
            raise ValueError("inventory debit must not contain a tradability date")


@dataclass(frozen=True)
class RightsAudit:
    issues: tuple[str, ...]
    commands_checked: int
    expected_movements: tuple[Movement, ...] = ()
    scope: str = "independent_recorded_rights_cash_quantity_equations_v1"

    @property
    def passed(self) -> bool:
        return not self.issues


def audit_rights(book: RightsBook, *, initial_cash: Decimal,
                 recorded_movements: tuple[Movement, ...] | None = None) -> RightsAudit:
    """Use an external initial cash anchor and optional outer inventory posting log.

    Does not call grant/payment/delivery/settlement/revision transitions. It
    cannot authenticate official sources, current receipt holdings, market NAV
    marks, or unrecorded outer cash movements. Those remain integration gates.
    """
    count = 0
    try:
        number(initial_cash)
        verified = decode_book(encode_book(book))
        commands = []
        for receipt in verified.receipts:
            commands.append((receipt.action_id,json.loads(receipt.command_json)))
        count = len(commands)
        if recorded_movements is not None:
            _valid_postings(recorded_movements)
        with localcontext() as context:
            context.prec = 80
            cash, positions, movements = reconstruct(commands,initial_cash)
            issues = []
            if cash != verified.cash:
                issues.append("rights usable cash does not reconcile to external initial anchor and commands")
            actual = {row.key:asdict(row) for row in verified.positions}
            if set(actual) != set(positions):
                issues.append("rights position inventory differs from original command events")
            for key in sorted(set(actual).intersection(positions)):
                for field, expected in positions[key].items():
                    if canonical(actual[key][field]) != canonical(expected):
                        issues.append(key+" "+field+" does not reconcile")
            if recorded_movements is not None and (
                    type(recorded_movements) is not tuple
                    or any(type(row) is not tuple for row in recorded_movements)
                    or recorded_movements != movements):
                issues.append("rights inventory debit/credit postings differ from command reconstruction")
            return RightsAudit(tuple(issues),count,movements)
    except (ValueError,TypeError,KeyError,IndexError,ArithmeticError,AttributeError) as exc:
        return RightsAudit(("invalid or insufficient rights audit evidence: "+str(exc),),count)
