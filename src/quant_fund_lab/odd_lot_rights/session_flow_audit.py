"""Independent cash-component and posting equations for recorded engine sessions."""
from decimal import Decimal, localcontext

from .types import clock, day, evidence, number, quantity


def audit_session_flow(command, cash):
    """Validate archived transfer assertions; source/session authentication is separate."""
    if set(command) != {"as_of","kind","terms"}:
        raise ValueError("session transfer command schema differs")
    terms = command["terms"]
    if set(terms) != {"available_at","evidence_sha256","link","movements"}:
        raise ValueError("session transfer terms schema differs")
    evidence(terms["available_at"],tuple(terms["evidence_sha256"]))
    if clock(terms["available_at"]) > clock(command["as_of"]):
        raise ValueError("session transfer evidence is not yet available")
    link = terms["link"]
    if set(link) != {"session","cash_before","cash_after","cash_delta","shares_before","shares_after",
                     "interest","event_cash","execution_cash","settled_sales","unsettled_sales"}:
        raise ValueError("session transfer link schema differs")
    day(link["session"])
    from zoneinfo import ZoneInfo

    if clock(command["as_of"]).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() < link["session"]:
        raise ValueError("session transfer cannot precede its close date")
    values = {}
    for name in ("cash_before","cash_after","cash_delta","interest","event_cash","execution_cash","settled_sales","unsettled_sales"):
        if not isinstance(link[name],str):
            raise TypeError("session cash assertions require exact Decimal strings")
        value = Decimal(link[name])
        number(value,signed=name in {"cash_delta","event_cash","execution_cash"})
        values[name] = value
    with localcontext() as context:
        context.prec = 80
        if cash != values["cash_before"] or values["cash_after"]-cash != values["cash_delta"]:
            raise ValueError("session transfer cash anchor/delta differs from completed rights account")
        expected = cash+values["interest"]+values["event_cash"]+values["execution_cash"]+values["settled_sales"]
        tolerance = Decimal("0.000001")+Decimal("0.000000000001")*max(abs(expected),abs(values["cash_after"]))
        if abs(expected-values["cash_after"]) > tolerance:
            raise ValueError("session transfer cash components do not reconcile")
    def shares(rows):
        if not isinstance(rows,list):
            raise TypeError("session holdings require canonical lists")
        result = {}
        for row in rows:
            if not isinstance(row,list) or len(row) != 2:
                raise ValueError("session holding shape differs")
            symbol,units = row
            quantity(units)
            if not isinstance(symbol,str) or not symbol or units == 0 or symbol in result:
                raise ValueError("session holding identity/quantity invalid")
            result[symbol] = units
        return result
    before,after = shares(link["shares_before"]),shares(link["shares_after"])
    balances = dict(before)
    movements = []
    for encoded in terms["movements"]:
        if not isinstance(encoded,list) or len(encoded) != 5:
            raise ValueError("session transfer posting schema differs")
        side,key,security,units,tradable = encoded
        quantity(units)
        if (side not in {"credit","debit"} or not units or not isinstance(key,str) or not key
                or not isinstance(security,str) or not security):
            raise ValueError("session transfer posting identities invalid")
        if side == "credit":
            day(tradable)
            if tradable != link["session"]:
                raise ValueError("session trade credit tradability differs from session")
            balances[security] = balances.get(security,0)+units
        else:
            if tradable is not None:
                raise ValueError("session debit must not assign tradability")
            balances[security] = balances.get(security,0)-units
            if balances[security] < 0:
                raise ValueError("session transfer oversells aggregate inventory")
        movements.append((side,key,security,units,tradable))
    if {key:value for key,value in balances.items() if value} != after:
        raise ValueError("session postings do not reconstruct resulting holdings")
    return values["cash_after"],tuple(movements)
