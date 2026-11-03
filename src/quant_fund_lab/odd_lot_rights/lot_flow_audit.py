"""Reconstruct corporate-lot and fill journals without calling their transitions."""
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .inventory import SecurityLot
from .lot_events import LotRoundingPolicy, OpeningLotEvent
from .session_flow_audit import audit_session_flow
from .types import clock, number, quantity


def _lots(rows):
    if not isinstance(rows, list):
        raise TypeError("lot journal requires a canonical list")
    lots = tuple(SecurityLot(**row) for row in rows)
    keys = tuple((row.right_key, row.security_id, row.tradable_session) for row in lots)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("lot journal requires unique canonical lot ordering")
    return {key: row.units for key, row in zip(keys, lots)}


def audit_lot_session(command, cash, action_id):
    """Check independent lot equations and the established session cash equations.

    Source facts and the original runtime/market archive require authentication
    outside this recorded-command audit, just as in the older session boundary.
    """
    if set(command) != {"as_of", "kind", "terms"}:
        raise ValueError("lot session command schema differs")
    terms = command["terms"]
    if set(terms) != {"available_at", "evidence_sha256", "link", "lot_journal"}:
        raise ValueError("lot session terms schema differs")
    journal, link = terms["lot_journal"], terms["link"]
    if set(journal) != {"opening_at", "policy", "events", "initial_lots", "final_lots", "fills"}:
        raise ValueError("lot session journal schema differs")
    opening = clock(journal["opening_at"])
    if (opening > clock(command["as_of"])
            or opening.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != link["session"]):
        raise ValueError("lot session opening is after its completed close")
    LotRoundingPolicy(**journal["policy"])
    initial = _lots(journal["initial_lots"])
    balances = dict(initial)
    before = {}
    for (_, security, _), units in initial.items():
        before[security] = before.get(security, 0)+units
    if dict(link["shares_before"]) != before:
        raise ValueError("lot session initial lots differ from engine holding anchor")
    events = []
    for raw in journal["events"]:
        row = dict(raw)
        row["ratio"] = None if row["ratio"] is None else Decimal(row["ratio"])
        row["evidence_sha256"] = tuple(row["evidence_sha256"])
        event = OpeningLotEvent(**row)
        if event.session != link["session"] or clock(event.available_at) > opening:
            raise ValueError("lot session contains unavailable corporate terms")
        events.append(event)
    order = lambda row: (0 if row.kind == "split" else 1, row.security_id)
    if (events != sorted(events, key=order)
            or len({(row.kind, row.security_id) for row in events}) != len(events)
            or len({row.event_id for row in events}) != len(events)):
        raise ValueError("lot session event ordering or identity differs")
    with localcontext() as context:
        context.prec = 80
        for event in events:
            keys = [key for key in balances if key[1] == event.security_id]
            if event.kind == "terminal":
                for key in keys:
                    del balances[key]
                continue
            exact_total, whole, releases = Decimal(0), 0, []
            for key in keys:
                exact = balances.pop(key)*event.ratio
                units = int(exact)
                exact_total += exact
                whole += units
                if units:
                    balances[key] = units
                if exact != units:
                    releases.append(key[2])
            pooled = int(exact_total)-whole
            if pooled:
                right = "split-residual:"+event.event_id
                if any(key[0] == right for key in keys):
                    raise ValueError("lot audit residual identity collision")
                balances[right, event.security_id, max(releases)] = pooled
    execution_cash = Decimal(0)
    for fill in journal["fills"]:
        if set(fill) != {"security_id", "side", "units", "price", "gross", "fees"}:
            raise ValueError("lot journal fill schema differs")
        security, side, units = fill["security_id"], fill["side"], fill["units"]
        quantity(units)
        if not isinstance(security, str) or not security or not units or side not in {"BUY", "SELL"}:
            raise ValueError("lot journal fill identity or quantity differs")
        if any(not isinstance(fill[key], str) for key in ("price", "gross", "fees")):
            raise TypeError("lot fill financial assertions require Decimal strings")
        price, gross, fees = (Decimal(fill[key]) for key in ("price", "gross", "fees"))
        for value in (price, gross, fees):
            number(value)
        tolerance = Decimal("0.000001")+Decimal("0.000000000001")*max(gross, price*units)
        if price <= 0 or abs(gross-price*units) > tolerance:
            raise ValueError("lot audit fill gross does not reconcile to price and quantity")
        execution_cash += -(gross+fees) if side == "BUY" else min(Decimal(0), gross-fees)
        if side == "BUY":
            key = "session:"+action_id+":"+security, security, link["session"]
            balances[key] = balances.get(key, 0)+units
        else:
            remaining = units
            for key in sorted(balances):
                if key[1] == security and key[2] <= link["session"]:
                    used = min(remaining, balances[key])
                    balances[key] -= used
                    remaining -= used
            if remaining:
                raise ValueError("lot audit sale exceeds command-time released lots")
    if abs(execution_cash-Decimal(link["execution_cash"])) > Decimal("0.000001")+abs(execution_cash)*Decimal("0.000000000001"):
        raise ValueError("lot audit execution cash differs from actual fills")
    expected = {key: units for key, units in balances.items() if units}
    final = _lots(journal["final_lots"])
    if final != expected:
        raise ValueError("lot journal final inventory differs from independent event/fill reconstruction")
    after = {}
    for (_, security, _), units in final.items():
        after[security] = after.get(security, 0)+units
    if after != dict(link["shares_after"]):
        raise ValueError("lot journal final holdings differ from engine close")
    movements = tuple(("debit", key[0], key[1], units, None) for key, units in initial.items())+tuple(
        ("credit", key[0], key[1], units, key[2]) for key, units in final.items())
    net = []
    for security in sorted(set(before) | set(after)):
        delta = after.get(security, 0)-before.get(security, 0)
        if delta:
            net.append(["credit" if delta > 0 else "debit", "audit-net", security, abs(delta),
                        link["session"] if delta > 0 else None])
    synthetic = {"kind": "portfolio_session", "as_of": command["as_of"], "terms": {
        "available_at": terms["available_at"], "evidence_sha256": terms["evidence_sha256"],
        "link": link, "movements": net}}
    checked_cash, _ = audit_session_flow(synthetic, cash)
    return checked_cash, movements
