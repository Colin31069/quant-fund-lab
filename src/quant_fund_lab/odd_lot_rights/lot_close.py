"""Whole-lot trade accounting after the opening corporate-action projection."""
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .inventory import SecurityLot
from .types import day, number, quantity


@dataclass(frozen=True)
class LotSessionFill:
    security_id: str
    side: str
    units: int
    price: Decimal
    gross: Decimal
    fees: Decimal

    def __post_init__(self) -> None:
        quantity(self.units)
        if (not isinstance(self.security_id, str) or not self.security_id
                or self.side not in {"BUY", "SELL"} or not self.units):
            raise ValueError("lot fill requires explicit identity, side and positive units")
        for value in (self.price, self.gross, self.fees):
            number(value)
        with localcontext() as context:
            context.prec = 80
            tolerance = Decimal("0.000001")+Decimal("0.000000000001")*max(self.gross, self.price*self.units)
            if self.price <= 0 or abs(self.gross-self.price*self.units) > tolerance:
                raise ValueError("lot fill gross differs from explicit price and quantity")


def close_session_lots(lots: tuple[SecurityLot, ...], fills: tuple[LotSessionFill, ...],
                       action_id: str, session: str) -> tuple[SecurityLot, ...]:
    """Consume only released lots; preserve original right keys on remaining units."""
    day(session)
    if not isinstance(action_id, str) or not action_id:
        raise ValueError("lot close requires an explicit action identity")
    if (type(lots) is not tuple or any(not isinstance(row, SecurityLot) for row in lots)
            or type(fills) is not tuple or any(not isinstance(row, LotSessionFill) for row in fills)):
        raise TypeError("lot close requires immutable typed lots and fills")
    balances = {(row.right_key, row.security_id, row.tradable_session): row.units for row in lots}
    if len(balances) != len(lots):
        raise ValueError("lot close requires unique lot identities")
    for fill in fills:
        if fill.side == "BUY":
            key = "session:"+action_id+":"+fill.security_id, fill.security_id, session
            balances[key] = balances.get(key, 0)+fill.units
        else:
            remaining = fill.units
            for key in sorted(balances):
                if key[1] != fill.security_id or key[2] > session:
                    continue
                used = min(remaining, balances[key])
                balances[key] -= used
                remaining -= used
            if remaining:
                raise ValueError("lot close sale exceeds post-event tradable ownership")
    return tuple(SecurityLot(key[0], key[1], units, key[2])
                 for key, units in sorted(balances.items()) if units)
