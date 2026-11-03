"""Immutable rights contracts; later payment/delivery knowledge is supplied separately."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext


def number(value: Decimal, *, signed: bool = False) -> None:
    if (not isinstance(value, Decimal) or not value.is_finite()
            or (not signed and value < 0) or len(value.as_tuple().digits) > 40
            or not -18 <= value.as_tuple().exponent <= 18):
        raise ValueError("rights values require bounded finite Decimal numbers")


def quantity(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError("rights quantities require explicit integers within 0..10^12")


def day(value: str) -> None:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("rights sessions require canonical ISO dates")


def clock(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("rights knowledge/processing time requires a timezone")
    return stamp


def evidence(available_at: str, hashes: tuple[str, ...]) -> None:
    clock(available_at)
    if (type(hashes) is not tuple or not hashes or len(set(hashes)) != len(hashes)
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in hashes)):
        raise ValueError("rights terms require explicit immutable evidence SHA-256 references")


@dataclass(frozen=True)
class EntitlementLeg:
    leg_id: str
    asset_key: str
    kind: str
    units_per_parent: Decimal

    def __post_init__(self) -> None:
        number(self.units_per_parent)
        if (not self.leg_id or not self.asset_key or self.kind not in {"bonus", "subscription"}
                or self.units_per_parent <= 0):
            raise ValueError("entitlement requires identity, asset class and positive ratio")


@dataclass(frozen=True)
class EntitlementEvent:
    event_id: str
    parent_security_id: str
    ex_session: str
    available_at: str
    evidence_sha256: tuple[str, ...]
    legs: tuple[EntitlementLeg, ...]

    def __post_init__(self) -> None:
        day(self.ex_session)
        evidence(self.available_at, self.evidence_sha256)
        if (not re.fullmatch(r"[0-9a-f]{64}", self.event_id) or not self.parent_security_id
                or type(self.legs) is not tuple or not self.legs
                or any(not isinstance(v, EntitlementLeg) for v in self.legs)
                or len({v.leg_id for v in self.legs}) != len(self.legs)):
            raise ValueError("rights event requires a stable event ID and unique typed legs")


@dataclass(frozen=True)
class PaymentTerms:
    right_key: str
    unit_price: Decimal
    payment_start: str
    payment_end: str
    available_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        number(self.unit_price)
        day(self.payment_start)
        day(self.payment_end)
        evidence(self.available_at, self.evidence_sha256)
        if not self.right_key or self.unit_price <= 0 or self.payment_end < self.payment_start:
            raise ValueError("subscription payment requires positive price and ordered window")


@dataclass(frozen=True)
class PaymentRequest:
    terms: PaymentTerms
    units: int
    fee: Decimal

    def __post_init__(self) -> None:
        quantity(self.units)
        number(self.fee)
        if not isinstance(self.terms, PaymentTerms) or self.units == 0:
            raise ValueError("subscription request requires terms and positive whole units")


@dataclass(frozen=True)
class DeliveryTerms:
    right_key: str
    asset_key: str
    security_id: str
    delivery_session: str
    tradable_session: str
    available_at: str
    evidence_sha256: tuple[str, ...]
    fee: Decimal

    def __post_init__(self) -> None:
        day(self.delivery_session)
        day(self.tradable_session)
        evidence(self.available_at, self.evidence_sha256)
        number(self.fee)
        if (not self.right_key or not self.asset_key or not self.security_id
                or self.tradable_session < self.delivery_session):
            raise ValueError("delivery requires stable identities and distinct ordered tradability")


@dataclass(frozen=True)
class RightPosition:
    event: EntitlementEvent
    leg_id: str
    eligible_parent_units: int
    entitled: Decimal
    unpaid: Decimal
    pending: int
    delivered: int
    expired: Decimal
    settled_fraction: Decimal
    cash_paid: Decimal
    fees_paid: Decimal
    last_payment_session: str | None = None

    @property
    def key(self) -> str:
        return self.event.event_id + ":" + self.leg_id

    @property
    def leg(self) -> EntitlementLeg:
        return next(v for v in self.event.legs if v.leg_id == self.leg_id)

    def __post_init__(self) -> None:
        if not isinstance(self.event, EntitlementEvent) or self.leg_id not in {v.leg_id for v in self.event.legs}:
            raise ValueError("position requires a declared entitlement leg")
        for value in (self.entitled, self.unpaid, self.expired, self.settled_fraction, self.cash_paid, self.fees_paid):
            number(value)
        quantity(self.eligible_parent_units)
        quantity(self.pending)
        quantity(self.delivered)
        with localcontext() as context:
            context.prec = 80
            if self.entitled != self.leg.units_per_parent * self.eligible_parent_units:
                raise ValueError("entitlement differs from the frozen pre-event ownership basis")
            if self.entitled != self.unpaid + self.pending + self.delivered + self.expired + self.settled_fraction:
                raise ValueError("rights quantities do not conserve original entitlement")
        if self.last_payment_session is not None:
            day(self.last_payment_session)
            if self.last_payment_session < self.event.ex_session:
                raise ValueError("subscription payment cannot precede entitlement")
        if self.leg.kind == "bonus":
            if (self.cash_paid or (self.fees_paid and not self.delivered) or self.expired or self.last_payment_session is not None
                    or self.unpaid+self.settled_fraction != self.entitled-int(self.entitled)):
                raise ValueError("bonus claims cannot contain subscription payments or implicit fraction disposal")
        elif (self.settled_fraction or bool(self.pending+self.delivered) != bool(self.cash_paid)
              or bool(self.pending+self.delivered) != (self.last_payment_session is not None)):
            raise ValueError("paid subscription units require matching payment history")


@dataclass(frozen=True)
class ActionReceipt:
    action_id: str
    payload_sha256: str
    command_json: str

    def __post_init__(self) -> None:
        if not self.action_id or not re.fullmatch(r"[0-9a-f]{64}", self.payload_sha256):
            raise ValueError("rights action requires stable identity and command SHA-256")
        command = json.loads(self.command_json)
        if (not isinstance(command, dict) or "kind" not in command or "as_of" not in command
                or command.get("kind") not in {"grant","subscribe","deliver","expire","fraction_cash","convert","revise","portfolio_session","portfolio_lot_session","policy_election"}
                or json.dumps(command, sort_keys=True, separators=(",", ":"), allow_nan=False) != self.command_json
                or hashlib.sha256(self.command_json.encode()).hexdigest() != self.payload_sha256):
            raise ValueError("rights receipt differs from the canonical original command")
        clock(command["as_of"])


@dataclass(frozen=True)
class RightsBook:
    cash: Decimal
    positions: tuple[RightPosition, ...] = ()
    receipts: tuple[ActionReceipt, ...] = ()
    through: str | None = None

    def __post_init__(self) -> None:
        number(self.cash)
        for rows, cls in ((self.positions, RightPosition), (self.receipts, ActionReceipt)):
            if type(rows) is not tuple or any(not isinstance(v, cls) for v in rows):
                raise TypeError("rights book requires immutable typed tuples")
        if (len({v.key for v in self.positions}) != len(self.positions)
                or len({v.action_id for v in self.receipts}) != len(self.receipts)):
            raise ValueError("duplicate rights position or action identity")
        from .book_validation import validate_history

        validate_history(self)


@dataclass(frozen=True)
class SecurityCredit:
    right_key: str
    security_id: str
    units: int
    tradable_session: str

    def __post_init__(self) -> None:
        quantity(self.units)
        day(self.tradable_session)
        if not self.right_key or not self.security_id or self.units == 0:
            raise ValueError("security delivery credit requires identities and positive units")


@dataclass(frozen=True)
class SecurityDebit:
    right_key: str
    security_id: str
    units: int

    def __post_init__(self) -> None:
        quantity(self.units)
        if not self.right_key or not self.security_id or self.units == 0:
            raise ValueError("security conversion debit requires identities and positive units")


@dataclass(frozen=True)
class RightsTransition:
    book: RightsBook
    action_id: str
    cash_delta: Decimal
    credits: tuple[SecurityCredit, ...] = ()
    debits: tuple[SecurityDebit, ...] = ()
    applied: bool = True

    def __post_init__(self) -> None:
        number(self.cash_delta, signed=True)
        if (not isinstance(self.book, RightsBook) or not self.action_id or type(self.applied) is not bool
                or type(self.credits) is not tuple or any(not isinstance(v, SecurityCredit) for v in self.credits)
                or type(self.debits) is not tuple or any(not isinstance(v, SecurityDebit) for v in self.debits)):
            raise ValueError("rights transition requires typed immutable results")
