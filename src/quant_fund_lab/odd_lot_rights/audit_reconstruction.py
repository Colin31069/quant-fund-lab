"""Independent command equations; deliberately never call production transitions."""
from decimal import Decimal
from zoneinfo import ZoneInfo

from .types import clock, day, evidence, number, quantity

ZERO = Decimal(0)


def _amount(value):
    if not isinstance(value, str):
        raise TypeError("audit amount requires an exact decimal string")
    result = Decimal(value)
    number(result)
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError("audit command schema differs")


def _terms(value, kind, as_of):
    schemas = {
        "subscribe":"right_key unit_price payment_start payment_end available_at evidence_sha256",
        "expire":"right_key unit_price payment_start payment_end available_at evidence_sha256",
        "deliver":"right_key asset_key security_id delivery_session tradable_session available_at evidence_sha256 fee",
        "convert":"right_key asset_key receipt_security_id final_security_id conversion_session tradable_session available_at evidence_sha256 fee",
        "fraction_cash":"right_key fractional_units net_cash settlement_session available_at evidence_sha256"}
    _keys(value,schemas[kind])
    evidence(value["available_at"],tuple(value["evidence_sha256"]))
    if clock(value["available_at"]) > clock(as_of):
        raise ValueError("audit command used future terms")
    for key, item in value.items():
        if key.endswith("_session") or key in {"payment_start","payment_end"}:
            day(item)
        elif (key.endswith("_id") or key in {"right_key","asset_key"}) and (
                not isinstance(item,str) or not item):
            raise ValueError("audit term identity is empty or invalid")
    if kind in {"subscribe","expire"} and (
            _amount(value["unit_price"]) <= 0 or value["payment_end"] < value["payment_start"]):
        raise ValueError("audit invalid payment price/window")


def reconstruct(commands, initial_cash):
    """Return cash, per-leg independent balances and emitted inventory movements.

    The initial cash anchor is external. Source authenticity and current outer
    holdings need their own verifier; equations cannot prove those facts.
    """
    cash, positions, movements, receipts, conversions = initial_cash, {}, [], {}, {}
    sessions = set()
    last_session = None
    election_policy_id = None
    for action_id, command in commands:
        kind = command["kind"]
        if kind == "policy_election":
            from .payment_policy_audit import audit_policy_election

            normalized = audit_policy_election(command,positions)
            declared_policy = command["terms"]["policy_id"]
            if election_policy_id is not None and declared_policy != election_policy_id:
                raise ValueError("audit election policy changed inside the same account")
            election_policy_id = declared_policy
            if normalized is None:
                continue
            command,kind = normalized,"subscribe"
        elif kind == "subscribe" and election_policy_id is not None:
            raise ValueError("audit payment bypasses the account's frozen participation policy")
        if kind in {"portfolio_session", "portfolio_lot_session"}:
            from .session_flow_audit import audit_session_flow

            if kind == "portfolio_lot_session":
                from .lot_flow_audit import audit_lot_session

                cash,postings = audit_lot_session(command,cash,action_id)
            else:
                cash,postings = audit_session_flow(command,cash)
            session = command["terms"]["link"]["session"]
            if session in sessions:
                raise ValueError("audit duplicate engine session completion")
            if last_session is not None and session <= last_session:
                raise ValueError("audit engine session history is out of order")
            sessions.add(session)
            last_session = session
            movements.extend((action_id,*row) for row in postings)
            continue
        today = clock(command["as_of"]).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        if kind in {"grant", "revise"}:
            _keys(command, "as_of kind event eligible_units" if kind == "grant" else "as_of kind event")
            event = command["event"]
            if today < event["ex_session"] or (kind == "grant" and today != event["ex_session"]):
                raise ValueError("audit entitlement session differs")
            keys = {event["event_id"]+":"+leg["leg_id"] for leg in event["legs"]}
            if kind == "grant":
                quantity(command["eligible_units"])
                if keys.intersection(positions):
                    raise ValueError("audit duplicate entitlement grant")
                eligible = command["eligible_units"]
            else:
                existing = [row for key,row in positions.items() if key in keys]
                if len(existing) != len(keys):
                    raise ValueError("audit revision changes original legs")
                old = existing[0]["event"]
                if (old["parent_security_id"] != event["parent_security_id"] or old["ex_session"] != event["ex_session"]
                        or clock(old["available_at"]) >= clock(event["available_at"])
                        or not set(event["evidence_sha256"]).difference(old["evidence_sha256"])):
                    raise ValueError("audit revision lacks new matching evidence")
                eligible = existing[0]["eligible_parent_units"]
            for leg in event["legs"]:
                key = event["event_id"]+":"+leg["leg_id"]
                if kind == "revise":
                    row = positions[key]
                    previous = next(v for v in row["event"]["legs"] if v["leg_id"] == leg["leg_id"])
                    if (any(row[name] for name in ("cash_paid","fees_paid","delivered","expired","settled_fraction"))
                            or previous["kind"] != leg["kind"] or previous["asset_key"] != leg["asset_key"]):
                        raise ValueError("audit revision changes consumed or reclassified rights")
                total = _amount(leg["units_per_parent"]) * eligible
                pending = int(total) if leg["kind"] == "bonus" else 0
                positions[key] = {"event":event, "leg_id":leg["leg_id"], "eligible_parent_units":eligible,
                    "entitled":total,"unpaid":total-pending,"pending":pending,"delivered":0,
                    "expired":ZERO,"settled_fraction":ZERO,"cash_paid":ZERO,"fees_paid":ZERO,
                    "last_payment_session":None}
            continue
        if kind == "subscribe":
            _keys(command,"as_of kind requests")
            requests = command["requests"]
            if not requests or len({v["terms"]["right_key"] for v in requests}) != len(requests):
                raise ValueError("audit invalid or duplicate payment batch")
            for request in requests:
                _keys(request,"terms units fee")
                terms, units = request["terms"], request["units"]
                _terms(terms,kind,command["as_of"])
                row = positions[terms["right_key"]]
                leg = next(v for v in row["event"]["legs"] if v["leg_id"] == row["leg_id"])
                quantity(units)
                price, fee = _amount(terms["unit_price"]), _amount(request["fee"])
                if (leg["kind"] != "subscription" or units == 0 or units > row["unpaid"] or price <= 0
                        or not max(terms["payment_start"],row["event"]["ex_session"]) <= today <= terms["payment_end"]):
                    raise ValueError("audit payment exceeds entitlement or window")
                cash -= price*units+fee
                row.update(unpaid=row["unpaid"]-units,pending=row["pending"]+units,
                           cash_paid=row["cash_paid"]+price*units,fees_paid=row["fees_paid"]+fee,
                           last_payment_session=today)
            if cash < 0:
                raise ValueError("audit payment batch exceeds usable cash")
            continue
        _keys(command,"as_of kind terms units" if kind in {"deliver","convert"} else "as_of kind terms")
        terms = command["terms"]
        _terms(terms,kind,command["as_of"])
        key = terms["right_key"]
        row = positions[key]
        leg = next(v for v in row["event"]["legs"] if v["leg_id"] == row["leg_id"])
        if kind in {"deliver","convert"}:
            units = command["units"]
            quantity(units)
            if not units or terms["asset_key"] != leg["asset_key"]:
                raise ValueError("audit inventory units or class differ")
            fee = _amount(terms["fee"])
            if fee > cash:
                raise ValueError("audit inventory fee exceeds usable cash")
            cash -= fee
            row["fees_paid"] += fee
            if kind == "deliver":
                if (today != terms["delivery_session"] or units > row["pending"]
                        or terms["tradable_session"] < today):
                    raise ValueError("audit delivery exceeds pending claim or timing")
                row["pending"] -= units
                row["delivered"] += units
                receipt_key = key, terms["security_id"]
                receipts[receipt_key] = receipts.get(receipt_key,0)+units
                movements.append((action_id,"credit",key,terms["security_id"],units,terms["tradable_session"]))
            else:
                receipt_key = key, terms["receipt_security_id"]
                if (leg["kind"] != "subscription" or today != terms["conversion_session"]
                        or terms["tradable_session"] < today
                        or terms["receipt_security_id"] == terms["final_security_id"]
                        or units > receipts.get(receipt_key,0)-conversions.get(receipt_key,0)):
                    raise ValueError("audit conversion exceeds delivered receipts or timing")
                conversions[receipt_key] = conversions.get(receipt_key,0)+units
                movements.extend(((action_id,"debit",key,terms["receipt_security_id"],units,None),
                                  (action_id,"credit",key,terms["final_security_id"],units,terms["tradable_session"])))
        elif kind == "expire":
            if (leg["kind"] != "subscription" or today <= terms["payment_end"]
                    or (row["last_payment_session"] or row["event"]["ex_session"]) > terms["payment_end"]):
                raise ValueError("audit unpaid expiry window differs")
            row["expired"] += row["unpaid"]
            row["unpaid"] = ZERO
        elif kind == "fraction_cash":
            fraction = _amount(terms["fractional_units"])
            if (leg["kind"] != "bonus" or today != terms["settlement_session"]
                    or not 0 < fraction < 1 or fraction != row["unpaid"]):
                raise ValueError("audit fractional payout differs from outstanding claim")
            row["unpaid"] = ZERO
            row["settled_fraction"] += fraction
            cash += _amount(terms["net_cash"])
        else:
            raise ValueError("audit unsupported command kind")
    return cash, positions, tuple(movements)
