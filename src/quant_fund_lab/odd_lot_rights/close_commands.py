"""Typed same-session rights commands executed only after an audited engine close."""
from __future__ import annotations

import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .authorization_archive import AuthorizedRightsAccount, apply_account_authorization
from .inventory import post_rights_transition
from .payment_authorization import PaymentAuthorization
from .settlement import (
    FractionalCashTerms,
    ReceiptConversionTerms,
    convert_receipt,
    settle_fraction,
)
from .transitions import deliver_claim, expire_unpaid, grant_entitlements, revise_entitlements
from .types import DeliveryTerms, EntitlementEvent, PaymentTerms, clock, quantity


@dataclass(frozen=True)
class RightsCloseCommand:
    """Explicit operation and clock; no automatic participation or fee inference.

    grant/deliver/convert require an explicit bounded quantity. pay retains its
    complete authorization. All operations retain their existing evidence and
    conservation checks. This first command phase is after-close only.
    """

    action_id: str
    as_of: str
    kind: str
    terms: EntitlementEvent | PaymentAuthorization | DeliveryTerms | ReceiptConversionTerms | FractionalCashTerms | PaymentTerms
    units: int | None

    def __post_init__(self) -> None:
        clock(self.as_of)
        expected = {"grant": EntitlementEvent, "revise": EntitlementEvent,
                    "pay": PaymentAuthorization, "deliver": DeliveryTerms,
                    "convert": ReceiptConversionTerms, "fraction": FractionalCashTerms,
                    "expire": PaymentTerms}
        if not isinstance(self.action_id, str) or not self.action_id or self.kind not in expected:
            raise ValueError("close command requires explicit action identity and supported operation")
        if not isinstance(self.terms, expected[self.kind]):
            raise TypeError("close command terms differ from its declared operation")
        if self.kind in {"grant", "deliver", "convert"}:
            quantity(self.units)
            if self.kind != "grant" and not self.units:
                raise ValueError("delivery/conversion command requires positive units")
        elif self.units is not None:
            raise ValueError("unitless close operation cannot override its frozen quantity")
        if self.kind == "pay" and (self.terms.action_id != self.action_id or self.terms.as_of != self.as_of):
            raise ValueError("payment command must preserve its complete original authorization")


def apply_close_commands(account: AuthorizedRightsAccount, source_action_id: str,
                          commands: tuple[RightsCloseCommand, ...]) -> AuthorizedRightsAccount:
    """Return a complete batch or raise without changing the caller's state.

    No SQL transaction is claimed: the resulting immutable value must be saved
    with the engine checkpoint by the later durable workflow. Bank cutoffs are
    still checked by payment authorization; earlier cutoffs are not relaxed.
    """
    AuthorizedRightsAccount(account.inventory, account.policy, account.authorizations)
    if (type(commands) is not tuple
            or any(not isinstance(row, RightsCloseCommand) for row in commands)):
        raise TypeError("close batch requires immutable typed commands")
    if len({row.action_id for row in commands}) != len(commands):
        raise ValueError("close batch requires unique action identities")
    sessions = [(row.action_id, json.loads(row.command_json)) for row in account.inventory.book.receipts
                if json.loads(row.command_json)["kind"] in {"portfolio_session", "portfolio_lot_session"}]
    if not sessions or sessions[-1][0] != source_action_id:
        raise ValueError("close batch requires the latest recorded engine-session anchor")
    anchor = sessions[-1][1]
    day = anchor["terms"]["link"]["session"]
    times = [clock(row.as_of) for row in commands]
    if (times != sorted(times) or any(stamp < clock(anchor["as_of"])
            or stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != day for stamp in times)):
        raise ValueError("rights commands must be ordered after this same-session engine close")
    current = account
    for command in commands:
        if command.kind == "pay":
            current = apply_account_authorization(current, command.terms)
            continue
        book, key, terms, stamp = current.inventory.book, command.action_id, command.terms, command.as_of
        if command.kind == "grant":
            result = grant_entitlements(book, key, terms, command.units, as_of=stamp)
        elif command.kind == "revise":
            result = revise_entitlements(book, key, terms, as_of=stamp)
        elif command.kind == "deliver":
            result = deliver_claim(book, key, terms, command.units, as_of=stamp)
        elif command.kind == "convert":
            held = sum(row.units for row in current.inventory.lots
                       if row.right_key == terms.right_key and row.security_id == terms.receipt_security_id)
            completed = any(row.action_id == key for row in book.receipts)
            if not completed and command.units > held:
                raise ValueError("close conversion exceeds actually owned same-leg receipts")
            result = convert_receipt(book, key, terms, command.units, as_of=stamp)
        elif command.kind == "fraction":
            result = settle_fraction(book, key, terms, as_of=stamp)
        else:
            result = expire_unpaid(book, key, terms, as_of=stamp)
        inventory = post_rights_transition(current.inventory, result)
        if inventory is not current.inventory:
            current = AuthorizedRightsAccount(inventory, current.policy, current.authorizations)
    return current
