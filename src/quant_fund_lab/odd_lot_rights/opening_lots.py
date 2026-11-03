"""Project audited lots through known corporate actions before opening caps."""
from dataclasses import asdict
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from ..odd_lot_paper.sale_limits import OpeningSaleLimits
from .codec import fingerprint
from .inventory import RightsInventory, SecurityLot
from .inventory_codec import encode_inventory
from .lot_events import (
    LotRoundingPolicy,
    OpeningLotEvent,
    OpeningLotProjection,
    SplitLotFraction,
)
from .types import clock, day


def _key(lot):
    return lot.right_key, lot.security_id, lot.tradable_session


def project_opening_lots(account: RightsInventory, events: tuple[OpeningLotEvent, ...],
                         policy: LotRoundingPolicy, *, session: str,
                         as_of: str) -> OpeningLotProjection:
    """Preserve locks and exact fractions; never mutate or credit account cash.

    Whole units from each original lot keep that lot's release date. Residual
    whole units pooled across lots inherit the latest fractional contributor's
    release date. Residual fractions are disclosed, never assigned a cash value.
    Engine event authentication and durable posting are outer workflow gates.
    """
    day(session)
    now = clock(as_of)
    if now.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != session:
        raise ValueError("lot projection requires this opening's processing date")
    if not isinstance(account, RightsInventory) or not isinstance(policy, LotRoundingPolicy):
        raise TypeError("lot projection requires typed audited inventory and rounding policy")
    RightsInventory(account.initial_cash, account.initial_lots, account.book,
                    account.lots, account.postings)
    if account.book.through is not None and clock(account.book.through) > now:
        raise ValueError("lot projection cannot backdate the account's completed clock")
    if (type(events) is not tuple or any(not isinstance(row, OpeningLotEvent) for row in events)):
        raise TypeError("lot events require an immutable typed tuple")
    order = lambda row: (0 if row.kind == "split" else 1, row.security_id)
    if events != tuple(sorted(events, key=order)) or len({(row.kind, row.security_id) for row in events}) != len(events):
        raise ValueError("lot events require unique split-before-terminal ordering")
    if len({row.event_id for row in events}) != len(events):
        raise ValueError("lot events require unique event identities")
    for row in events:
        if row.session != session or clock(row.available_at) > now:
            raise ValueError("lot event is not known for this opening")
    lots = list(account.lots)
    fractions, residuals = [], {}
    with localcontext() as context:
        context.prec = 80
        for event in events:
            affected = [row for row in lots if row.security_id == event.security_id]
            lots = [row for row in lots if row.security_id != event.security_id]
            if event.kind == "terminal":
                # Corporate termination consumes locked ownership too; it is
                # not an executable SELL and creates no invented sale proceeds.
                continue
            total = Decimal(0)
            whole = 0
            contributors = []
            for lot in affected:
                exact = Decimal(lot.units) * event.ratio
                units = int(exact)
                total += exact
                whole += units
                if units:
                    lots.append(SecurityLot(lot.right_key, lot.security_id, units, lot.tradable_session))
                if exact != units:
                    contributors.append(lot)
                    fractions.append(SplitLotFraction(event.event_id, lot.right_key,
                        lot.security_id, exact-units, lot.tradable_session))
            pooled = int(total)-whole
            if pooled:
                key = "split-residual:"+event.event_id
                if any(row.right_key == key for row in affected):
                    raise ValueError("split residual identity collides with an existing lot")
                lots.append(SecurityLot(key, event.security_id,
                    pooled, max(lot.tradable_session for lot in contributors)))
            residuals[event.security_id] = total-int(total)
    shares, caps = {}, {}
    for lot in sorted(lots, key=_key):
        shares[lot.security_id] = shares.get(lot.security_id, 0)+lot.units
        caps.setdefault(lot.security_id, 0)
        if lot.tradable_session <= session:
            caps[lot.security_id] += lot.units
    return OpeningLotProjection(
        fingerprint({"inventory": encode_inventory(account), "events": [asdict(row) for row in events],
                     "policy": asdict(policy), "session": session, "as_of": as_of}),
        tuple(sorted(lots, key=_key)), tuple(fractions), tuple(sorted(shares.items())),
        tuple(sorted(residuals.items())), OpeningSaleLimits(session, tuple(sorted(caps.items()))))
