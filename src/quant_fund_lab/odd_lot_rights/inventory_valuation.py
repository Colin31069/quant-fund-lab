"""Count one cash balance and every held or pending asset exactly once."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .inventory import RightsInventory
from .types import clock, day, evidence, number
from .valuation import RightsMark, value_book


@dataclass(frozen=True)
class SecurityMark:
    security_id: str
    unit_value: Decimal
    session: str
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        number(self.unit_value)
        day(self.session)
        evidence(self.available_at,self.evidence_sha256)
        if not self.security_id:
            raise ValueError("security mark requires a stable inventory identity")


@dataclass(frozen=True)
class InventoryValuation:
    cash: Decimal
    held_assets: Decimal
    unpaid_rights: Decimal
    pending_claims: Decimal
    nav: Decimal


def value_inventory(account: RightsInventory, securities: tuple[SecurityMark, ...],
                     rights: tuple[RightsMark, ...], *, as_of: str) -> InventoryValuation:
    """Nontradable delivered units still need a known explicit valuation mark.

    Pending units use claim marks; delivered units use security marks instead.
    No price is invented from subscription cost or a parent security quote.
    """
    RightsInventory(account.initial_cash,account.initial_lots,account.book,account.lots,account.postings)
    stamp = clock(as_of)
    today = stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
    if type(securities) is not tuple or any(not isinstance(row,SecurityMark) for row in securities):
        raise TypeError("inventory valuation requires immutable typed security marks")
    marks = {row.security_id:row for row in securities}
    if len(marks) != len(securities) or set(marks) != {row.security_id for row in account.lots}:
        raise ValueError("held security marks are missing, duplicated or unrelated")
    rights_value = value_book(account.book,rights,as_of=as_of)
    with localcontext() as context:
        context.prec = 80
        held = Decimal(0)
        for row in account.lots:
            mark = marks[row.security_id]
            if mark.session != today or clock(mark.available_at) > stamp:
                raise ValueError("held security mark is stale or not yet available")
            held += row.units*mark.unit_value
        return InventoryValuation(account.cash,held,rights_value.unpaid_rights,
            rights_value.pending_claims,rights_value.total_book_value+held)
