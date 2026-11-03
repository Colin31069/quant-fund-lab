"""Separate later-known fractional payouts and one-for-one receipt conversions."""
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, localcontext

from .transitions import ZERO, _begin, _finish, _known, _position
from .types import (
    RightsBook,
    RightsTransition,
    SecurityCredit,
    SecurityDebit,
    day,
    evidence,
    number,
    quantity,
)


@dataclass(frozen=True)
class FractionalCashTerms:
    right_key: str
    fractional_units: Decimal
    net_cash: Decimal
    settlement_session: str
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        number(self.fractional_units)
        number(self.net_cash)
        day(self.settlement_session)
        evidence(self.available_at, self.evidence_sha256)
        if not self.right_key or not 0 < self.fractional_units < 1:
            raise ValueError("fractional payout requires an exact positive fraction below one")


@dataclass(frozen=True)
class ReceiptConversionTerms:
    right_key: str
    asset_key: str
    receipt_security_id: str
    final_security_id: str
    conversion_session: str
    tradable_session: str
    available_at: str
    evidence_sha256: tuple[str, ...]
    fee: Decimal

    def __post_init__(self) -> None:
        day(self.conversion_session)
        day(self.tradable_session)
        evidence(self.available_at, self.evidence_sha256)
        number(self.fee)
        if (not all((self.right_key,self.asset_key,self.receipt_security_id,self.final_security_id))
                or self.receipt_security_id == self.final_security_id
                or self.tradable_session < self.conversion_session):
            raise ValueError("receipt conversion requires distinct stable identities and ordered dates")


def settle_fraction(book: RightsBook, action_id: str, terms: FractionalCashTerms,
                    *, as_of: str) -> RightsTransition:
    """Use a documented net payout; never invent a sale price or pooling proceeds."""
    started = _begin(book,action_id,as_of,{"kind":"fraction_cash","terms":asdict(terms)})
    if started is None:
        return RightsTransition(book,action_id,ZERO,applied=False)
    identity, today = started
    _known(terms,as_of)
    row = _position(book,terms.right_key)
    if (today != terms.settlement_session or row.leg.kind != "bonus"
            or row.unpaid != terms.fractional_units):
        raise ValueError("fractional payout differs from the outstanding bonus claim or session")
    with localcontext() as context:
        context.prec = 80
        updated = replace(row,unpaid=ZERO,settled_fraction=row.settled_fraction+terms.fractional_units)
        return _finish(book,action_id,as_of,identity,
            (updated if old.key == row.key else old for old in book.positions),book.cash+terms.net_cash)


def convert_receipt(book: RightsBook, action_id: str, terms: ReceiptConversionTerms,
                    held_receipt_units: int, *, as_of: str) -> RightsTransition:
    """Convert only currently owned receipts, emitting a debit and matching credit.

    The outer account supplies verified current inventory and must atomically
    apply both changes with this book. Receipts sold earlier are not recreated.
    This contract covers one-for-one subscription receipt exchange only.
    """
    quantity(held_receipt_units)
    if held_receipt_units == 0:
        raise ValueError("receipt conversion requires currently owned units")
    started = _begin(book,action_id,as_of,
        {"kind":"convert","terms":asdict(terms),"units":held_receipt_units})
    if started is None:
        return RightsTransition(book,action_id,ZERO,applied=False)
    identity, today = started
    _known(terms,as_of)
    row = _position(book,terms.right_key)
    if row.leg.kind != "subscription":
        raise ValueError("receipt conversion requires a subscribed leg")
    if today != terms.conversion_session or terms.asset_key != row.leg.asset_key:
        raise ValueError("receipt conversion date or asset class differs")
    delivered = converted = 0
    for receipt in book.receipts:
        command = json.loads(receipt.command_json)
        old = command.get("terms",{})
        if old.get("right_key") != row.key:
            continue
        if command["kind"] == "deliver" and old["security_id"] == terms.receipt_security_id:
            delivered += command["units"]
        elif command["kind"] == "convert" and old["receipt_security_id"] == terms.receipt_security_id:
            converted += command["units"]
    if held_receipt_units > delivered-converted:
        raise ValueError("conversion exceeds delivered unconverted receipt units")
    if terms.fee > book.cash:
        raise ValueError("insufficient usable cash for receipt conversion fee")
    debit = SecurityDebit(row.key,terms.receipt_security_id,held_receipt_units)
    credit = SecurityCredit(row.key,terms.final_security_id,held_receipt_units,terms.tradable_session)
    with localcontext() as context:
        context.prec = 80
        updated = replace(row,fees_paid=row.fees_paid+terms.fee)
        return _finish(book,action_id,as_of,identity,
            (updated if old.key == row.key else old for old in book.positions),
            book.cash-terms.fee,(credit,),(debit,))
