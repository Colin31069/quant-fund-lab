"""Explicit risk/exit transfer for evidenced receipt-to-final-security conversions."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from ..odd_lot_paper.types import OddLotSessionState, PendingOrder, StopState
from .inventory import RightsInventory


@dataclass(frozen=True)
class ReceiptRiskTransfer:
    """A declared new-identity risk state, never a copied receipt price.

    carry_receipt_exit gives an existing receipt SELL priority on the final
    holding. The supplied exit must preserve its reason and cover actual final
    owned units. A receipt BUY can only be canceled by explicit instruction.
    Source/policy authenticity must be established by the outer workflow.
    """

    conversion_action_id: str
    final_stop: StopState
    final_exit: PendingOrder | None
    pending_policy: str
    cancel_receipt_buy: bool

    def __post_init__(self) -> None:
        if (not isinstance(self.conversion_action_id, str) or not self.conversion_action_id
                or self.pending_policy != "carry_receipt_exit"
                or type(self.cancel_receipt_buy) is not bool):
            raise ValueError("conversion risk requires explicit identity and supported pending policy")
        if not isinstance(self.final_stop, StopState):
            raise TypeError("conversion risk requires the final security's explicit typed stop")
        if self.final_exit is not None:
            if not isinstance(self.final_exit, PendingOrder):
                raise TypeError("conversion exit requires an explicit typed order")
            if (self.final_exit.symbol != self.final_stop.symbol or self.final_exit.side != "SELL"
                    or self.final_exit.stop != self.final_stop.stop
                    or self.final_exit.distance != self.final_stop.distance):
                raise ValueError("conversion exit must use its explicit final-security stop")


def transfer_conversion_risk(account: RightsInventory, checkpoint: OddLotSessionState,
                              anchor_action_id: str,
                              mappings: tuple[ReceiptRiskTransfer, ...]) -> OddLotSessionState:
    """Use only conversion commands after this recorded engine close.

    Partial conversions keep a receipt stop/exit for remaining receipt holdings;
    final exits use current final holdings, including any preexisting final lot.
    Under the declared receipt-exit priority, a final BUY is replaced by SELL.
    """
    if (type(mappings) is not tuple
            or any(not isinstance(row, ReceiptRiskTransfer) for row in mappings)):
        raise TypeError("conversion risk mappings require an immutable typed tuple")
    if not mappings:
        return checkpoint
    if (len({row.conversion_action_id for row in mappings}) != len(mappings)
            or len({row.final_stop.symbol for row in mappings}) != len(mappings)):
        raise ValueError("conversion risk mappings require unique actions and final identities")
    receipts = {row.action_id: (index, json.loads(row.command_json))
                for index, row in enumerate(account.book.receipts)}
    if anchor_action_id not in receipts:
        raise ValueError("conversion risk lacks its recorded engine anchor")
    anchor = receipts[anchor_action_id][0]
    owned = {}
    for lot in account.lots:
        owned[lot.security_id] = owned.get(lot.security_id, 0)+lot.units
    stops = {row.symbol: row for row in checkpoint.stops}
    pending = {row.symbol: row for row in checkpoint.pending}
    sources = set()
    for mapping in mappings:
        recorded = receipts.get(mapping.conversion_action_id)
        if recorded is None or recorded[0] <= anchor or recorded[1]["kind"] != "convert":
            raise ValueError("conversion risk requires a conversion after this engine anchor")
        terms = recorded[1]["terms"]
        receipt, final = terms["receipt_security_id"], terms["final_security_id"]
        if receipt in sources or final != mapping.final_stop.symbol or not owned.get(final, 0):
            raise ValueError("conversion risk identity differs from currently owned conversion output")
        sources.add(receipt)
        old = pending.get(receipt)
        if old is not None and old.side == "SELL":
            replacement = mapping.final_exit
            if (replacement is None or replacement.reason != old.reason
                    or replacement.quantity != owned[final]):
                raise ValueError("conversion must preserve the receipt exit for actual final holdings")
            pending[final] = replacement
            if owned.get(receipt, 0):
                pending[receipt] = replace(old, quantity=owned[receipt])
            else:
                del pending[receipt]
        elif mapping.final_exit is not None:
            raise ValueError("conversion mapping cannot invent an untriggered receipt exit")
        elif old is not None and old.side == "BUY":
            if mapping.cancel_receipt_buy:
                del pending[receipt]
            elif not owned.get(receipt, 0):
                raise ValueError("removed receipt BUY requires explicit cancellation policy")
        stops[final] = mapping.final_stop
        if not owned.get(receipt, 0):
            stops.pop(receipt, None)
    if sources & {row.final_stop.symbol for row in mappings}:
        raise ValueError("chained conversion risk requires separate ordered projections")
    return replace(checkpoint, stops=tuple(stops[key] for key in sorted(stops)),
                   pending=tuple(pending[key] for key in sorted(pending)))
