"""Pure entitlement/payment/delivery transitions with atomic batch cash checks."""
from dataclasses import asdict, replace
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .codec import canonical, fingerprint
from .types import (
    ActionReceipt,
    DeliveryTerms,
    EntitlementEvent,
    PaymentRequest,
    PaymentTerms,
    RightPosition,
    RightsBook,
    RightsTransition,
    SecurityCredit,
    clock,
    quantity,
)

ZERO = Decimal(0)


def _begin(book, action_id, as_of, command):
    stamp = clock(as_of)
    if not isinstance(action_id, str) or not action_id:
        raise ValueError("rights action requires an explicit idempotency key")
    payload = {"as_of":as_of, **command}
    identity = fingerprint(payload)
    old = next((row for row in book.receipts if row.action_id == action_id), None)
    if old is not None:
        if old.payload_sha256 != identity:
            raise ValueError("completed rights action payload changed")
        return None
    if book.through is not None and stamp < clock(book.through):
        raise ValueError("new rights action cannot precede the completed clock")
    return ActionReceipt(action_id, identity, canonical(payload)), stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()


def _known(terms, as_of):
    if clock(terms.available_at) > clock(as_of):
        raise ValueError("rights terms were not available at the processing clock")


def _position(book, key):
    result = next((row for row in book.positions if row.key == key), None)
    if result is None:
        raise ValueError("rights position is absent")
    return result


def _finish(book, action_id, as_of, identity, positions, cash, credits=(), debits=()):
    result = replace(book, cash=cash, positions=tuple(positions), through=as_of,
                     receipts=(*book.receipts, identity))
    return RightsTransition(result, action_id, cash-book.cash, tuple(credits), tuple(debits))


def grant_entitlements(book: RightsBook, action_id: str, event: EntitlementEvent,
                       eligible_parent_units: int, *, as_of: str) -> RightsTransition:
    """Grant all legs on the same pre-event ownership basis, without future terms.

    Bonus whole units become nontradable delivery claims. Bonus fractions and
    subscription entitlements retain exact quantities until explicitly settled
    or expired; they are never rounded up or treated as free tradable shares.
    """
    quantity(eligible_parent_units)
    started = _begin(book, action_id, as_of,
                     {"kind":"grant", "event":asdict(event), "eligible_units":eligible_parent_units})
    if started is None:
        return RightsTransition(book, action_id, ZERO, applied=False)
    identity, today = started
    _known(event, as_of)
    if today != event.ex_session:
        raise ValueError("entitlements require the event session and its frozen eligible holdings")
    positions = list(book.positions)
    with localcontext() as context:
        context.prec = 80
        for leg in event.legs:
            total = leg.units_per_parent * eligible_parent_units
            pending = int(total) if leg.kind == "bonus" else 0
            row = RightPosition(event, leg.leg_id, eligible_parent_units, total, total-pending,
                                pending, 0, ZERO, ZERO, ZERO, ZERO)
            if any(old.key == row.key for old in positions):
                raise ValueError("entitlement leg already granted under another action")
            positions.append(row)
        return _finish(book, action_id, as_of, identity, positions, book.cash)


def subscribe_batch(book: RightsBook, action_id: str, requests: tuple[PaymentRequest, ...],
                    *, as_of: str) -> RightsTransition:
    """Pay an explicit whole-unit election atomically from already usable cash.

    The caller excludes reserved cash and unsettled sale receivables before
    creating this book. Insufficient funds reject the whole command, never
    silently reduce units or choose an ordering between ordinary/preferred legs.
    """
    if (type(requests) is not tuple or not requests
            or any(not isinstance(row, PaymentRequest) for row in requests)):
        raise TypeError("subscription batch requires immutable typed requests")
    if len({row.terms.right_key for row in requests}) != len(requests):
        raise ValueError("subscription batch contains duplicate rights legs")
    started = _begin(book, action_id, as_of,
                     {"kind":"subscribe", "requests":[asdict(row) for row in requests]})
    if started is None:
        return RightsTransition(book, action_id, ZERO, applied=False)
    identity, today = started
    updates, total = {}, ZERO
    with localcontext() as context:
        context.prec = 80
        for request in requests:
            terms = request.terms
            _known(terms, as_of)
            row = _position(book, terms.right_key)
            if row.leg.kind != "subscription":
                raise ValueError("bonus entitlement cannot be subscribed as a paid leg")
            if not max(terms.payment_start, row.event.ex_session) <= today <= terms.payment_end:
                raise ValueError("subscription is outside the known payment window")
            if request.units > row.unpaid:
                raise ValueError("subscription exceeds exact remaining entitlement; pooling is not assumed")
            principal = terms.unit_price * request.units
            total += principal + request.fee
            updates[row.key] = replace(row, unpaid=row.unpaid-request.units,
                pending=row.pending+request.units, cash_paid=row.cash_paid+principal,
                fees_paid=row.fees_paid+request.fee, last_payment_session=today)
        if total > book.cash:
            raise ValueError("insufficient usable cash for the complete subscription batch")
        return _finish(book, action_id, as_of, identity,
            (updates.get(row.key, row) for row in book.positions), book.cash-total)


def deliver_claim(book: RightsBook, action_id: str, terms: DeliveryTerms, units: int,
                  *, as_of: str) -> RightsTransition:
    """Emit an explicit delivery credit; caller atomically posts it to asset inventory.

    Tradability remains on the credit, even if delivery happens earlier. Once
    delivered, its value belongs to that inventory, not the pending-rights NAV.
    """
    quantity(units)
    if units == 0:
        raise ValueError("delivery requires positive units")
    started = _begin(book, action_id, as_of,
                     {"kind":"deliver", "terms":asdict(terms), "units":units})
    if started is None:
        return RightsTransition(book, action_id, ZERO, applied=False)
    identity, today = started
    _known(terms, as_of)
    row = _position(book, terms.right_key)
    if today != terms.delivery_session or terms.asset_key != row.leg.asset_key:
        raise ValueError("delivery date or asset class differs from the declared claim")
    if units > row.pending:
        raise ValueError("delivery exceeds undelivered paid/bonus units")
    if terms.fee > book.cash:
        raise ValueError("insufficient usable cash for delivery fee")
    with localcontext() as context:
        context.prec = 80
        updated = replace(row, pending=row.pending-units, delivered=row.delivered+units,
                          fees_paid=row.fees_paid+terms.fee)
        credit = SecurityCredit(row.key, terms.security_id, units, terms.tradable_session)
        return _finish(book, action_id, as_of, identity,
            (updated if old.key == row.key else old for old in book.positions), book.cash-terms.fee, (credit,))


def expire_unpaid(book: RightsBook, action_id: str, terms: PaymentTerms,
                  *, as_of: str) -> RightsTransition:
    """Expire only unpaid rights after the known window; paid claims survive."""
    started = _begin(book, action_id, as_of, {"kind":"expire", "terms":asdict(terms)})
    if started is None:
        return RightsTransition(book, action_id, ZERO, applied=False)
    identity, today = started
    _known(terms, as_of)
    row = _position(book, terms.right_key)
    if (row.leg.kind != "subscription" or today <= terms.payment_end
            or (row.last_payment_session is not None and row.last_payment_session > terms.payment_end)):
        raise ValueError("unpaid expiry conflicts with the known subscription history/window")
    with localcontext() as context:
        context.prec = 80
        updated = replace(row, expired=row.expired+row.unpaid, unpaid=ZERO)
        return _finish(book, action_id, as_of, identity,
            (updated if old.key == row.key else old for old in book.positions), book.cash)


def revise_entitlements(book: RightsBook, action_id: str, event: EntitlementEvent,
                         *, as_of: str) -> RightsTransition:
    """Apply a later disclosed ratio before consumption; preserve prior commands.

    No past checkpoint is rewritten. Changes after payment, delivery, expiry or
    fractional settlement require a separate evidenced correction/refund flow,
    rather than silently replacing consumed quantities or historical costs.
    """
    started = _begin(book,action_id,as_of,{"kind":"revise","event":asdict(event)})
    if started is None:
        return RightsTransition(book,action_id,ZERO,applied=False)
    identity, today = started
    _known(event,as_of)
    old_rows = [row for row in book.positions if row.event.event_id == event.event_id]
    if not old_rows or today < event.ex_session:
        raise ValueError("entitlement revision requires an existing event")
    previous = old_rows[0].event
    if (previous.parent_security_id != event.parent_security_id or previous.ex_session != event.ex_session
            or {leg.leg_id for leg in previous.legs} != {leg.leg_id for leg in event.legs}
            or clock(event.available_at) <= clock(previous.available_at)
            or not set(event.evidence_sha256).difference(previous.evidence_sha256)):
        raise ValueError("entitlement revision lacks matching identity and later new evidence")
    updates = {}
    with localcontext() as context:
        context.prec = 80
        for row in old_rows:
            leg = next(leg for leg in event.legs if leg.leg_id == row.leg_id)
            if (row.leg.asset_key != leg.asset_key or row.leg.kind != leg.kind
                    or row.cash_paid or row.fees_paid or row.delivered or row.expired or row.settled_fraction):
                raise ValueError("consumed or reclassified entitlement requires explicit correction flow")
            total = leg.units_per_parent * row.eligible_parent_units
            pending = int(total) if leg.kind == "bonus" else 0
            updates[row.key] = replace(row,event=event,entitled=total,unpaid=total-pending,pending=pending)
        return _finish(book,action_id,as_of,identity,
            (updates.get(row.key,row) for row in book.positions),book.cash)
