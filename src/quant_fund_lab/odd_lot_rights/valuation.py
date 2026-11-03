"""Explicit contemporaneous rights/claim marks; never invent a missing value."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .types import RightsBook, clock, day, evidence, number


@dataclass(frozen=True)
class RightsMark:
    right_key: str
    component: str
    unit_value: Decimal
    session: str
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        number(self.unit_value)
        day(self.session)
        evidence(self.available_at, self.evidence_sha256)
        if not self.right_key or self.component not in {"unpaid", "pending"}:
            raise ValueError("rights mark requires an explicit leg and valuation component")


@dataclass(frozen=True)
class RightsValuation:
    cash: Decimal
    unpaid_rights: Decimal
    pending_claims: Decimal
    total_book_value: Decimal


def value_book(book: RightsBook, marks: tuple[RightsMark, ...], *, as_of: str) -> RightsValuation:
    """Value only this cash/rights sub-book; delivered assets belong to outer inventory.

    A mark may explicitly be zero, but an absent, future or stale mark fails.
    Unpaid optional rights and paid pending assets have distinct marks: an
    option payoff, subscription cost and eventual stock price are not synonyms.
    """
    stamp = clock(as_of)
    today = stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
    if book.through is not None and stamp < clock(book.through):
        raise ValueError("rights valuation cannot read a future checkpoint")
    if type(marks) is not tuple or any(not isinstance(row, RightsMark) for row in marks):
        raise TypeError("rights valuation requires immutable typed marks")
    lookup = {(row.right_key, row.component):row for row in marks}
    if len(lookup) != len(marks):
        raise ValueError("duplicate rights valuation mark")
    required = {(row.key, component):units for row in book.positions
                for component, units in (("unpaid", row.unpaid), ("pending", row.pending)) if units > 0}
    if set(lookup) != set(required):
        raise ValueError("rights/claim valuation evidence is absent or unrelated")
    with localcontext() as context:
        context.prec = 80
        values = {"unpaid":Decimal(0), "pending":Decimal(0)}
        for key, units in required.items():
            mark = lookup[key]
            if mark.session != today or clock(mark.available_at) > stamp:
                raise ValueError("rights mark is stale or not yet available")
            values[mark.component] += mark.unit_value * units
        return RightsValuation(book.cash, values["unpaid"], values["pending"],
                               book.cash+values["unpaid"]+values["pending"])
