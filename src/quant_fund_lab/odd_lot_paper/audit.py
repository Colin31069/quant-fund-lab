"""Read-only independent reconstruction of cash, quantities, obligations and NAV."""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing, nullcontext
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .audit_fees import reconcile_fill_fees
from .audit_risk import reconcile_risk_state
from .event_codec import decode_event
from .serialization import decode_state


@dataclass(frozen=True)
class AccountingAudit:
    issues: tuple[str, ...]
    sessions_checked: int
    scope: str = "financial_reconstruction_and_recorded_risk_lifecycle_v2"

    @property
    def passed(self) -> bool:
        return not self.issues


def audit_accounting(path: str | Path, *, _connection: sqlite3.Connection | None = None) -> AccountingAudit:
    """Rebuild accounting without execution functions; never repair stored values.

    Risk lifecycle is checked against recorded close inputs and business events.
    Alpha target weights, market source truth, snapshot linkage and protocol
    preregistration require their separate verifiers.
    """
    root = Path(path)
    if root.is_symlink() or not root.is_file():
        return AccountingAudit(("account file is missing or symlinked",), 0)
    issues: list[str] = []
    count = 0

    def equal(label: str, actual: float, expected: float) -> None:
        if not (math.isfinite(actual) and math.isfinite(expected) and
                abs(actual-expected) <= 1e-6 + 1e-12 * max(abs(actual), abs(expected))):
            issues.append(label + " does not reconcile")

    try:
        connection = (closing(sqlite3.connect(root.resolve().as_uri()+"?mode=ro", uri=True))
                      if _connection is None else nullcontext(_connection))
        with connection as db:
            metadata = dict(db.execute("SELECT key,value FROM account_metadata"))
            if metadata["kind"] != "odd_lot_checkpoint_v1":
                raise ValueError("unsupported account schema")
            config = json.loads(metadata["config"])
            rate = config["execution"]["cash_annual_yield"]
            initial = decode_state(metadata["initial_state"])
            cash, shares = initial.cash, dict(initial.shares)
            previous = pd.Timestamp(initial.session)
            previous_state = initial
            obligations: list[dict] = []
            receivables: list[tuple[str, float, str]] = []
            for session, payload in db.execute("SELECT session,state_json FROM session_checkpoints ORDER BY session"):
                count += 1
                state = decode_state(payload)
                stamp = pd.Timestamp(session)
                cash += cash * rate * (stamp.date()-previous.date()).days / 365.
                groups: dict[str, list] = {}
                for category, event in db.execute(
                    "SELECT category,payload FROM session_events WHERE session=? ORDER BY category,ordinal", (session,)):
                    if category == "snapshot":
                        # External provenance links use their own verifier, not the event codec.
                        continue
                    groups.setdefault(category, []).append(decode_event(json.loads(event)))
                if len(groups.get("nav", [])) != 1 or len(groups.get("valuation", [])) != 1:
                    raise ValueError("missing NAV or valuation source evidence")
                marks = groups["valuation"][0]
                issues.extend(session+" "+issue for issue in reconcile_risk_state(
                    previous_state, state, groups, config["research"]))
                issues.extend(session+" "+issue for issue in reconcile_fill_fees(groups, config["research"]))
                for category in ("actions", "terminal_events", "fills"):
                    for event in groups.get(category, []):
                        if (pd.Timestamp(event["timestamp"]).date().isoformat() != session
                                or event["local_currency"] != "TWD" or event["fx_to_base"] != 1.):
                            raise ValueError("event date or currency differs from TWD account")
                for event in groups.get("actions", []):
                    symbol, action = event["symbol"], event["action"]
                    if event["quantity_before"] != shares.get(symbol, 0):
                        issues.append(session + " action starting quantity differs")
                    if action == "cash_dividend":
                        gross = shares.get(symbol, 0) * event["ratio_or_amount"]
                        locked_rate = config["execution"]["dividend_withholding"]["tw_rate"]
                        equal(session+" dividend withholding rate", event["withholding_rate"], locked_rate)
                        equal(session+" dividend withholding", event["withholding_tax"], gross*locked_rate)
                        equal(session+" dividend gross", event["gross_cash_value"], gross)
                        expected = gross * (1-locked_rate)
                        equal(session+" dividend", event["cash_value"], expected)
                    elif action == "stock_split":
                        exact = shares.get(symbol, 0) * event["ratio_or_amount"]
                        whole = math.floor(exact + 1e-12)
                        if whole != event["quantity_after"]:
                            issues.append(session+" split quantity differs")
                        shares[symbol] = whole
                        fraction = max(0., exact-whole)
                        if event["cash_in_lieu_price_source"] == "pending_settlement":
                            receivables.append((symbol, fraction, pd.Timestamp(event["cash_in_lieu_settlement_date"]).date().isoformat()))
                        else:
                            equal(session+" fractional proceeds", event["cash_value"], fraction*event["cash_in_lieu_price"])
                    elif action == "cash_in_lieu_settlement":
                        matches = [row for row in receivables if row[0] == symbol and row[2] == session
                                   and math.isclose(row[1], event["fractional_quantity"], abs_tol=1e-12)]
                        if not matches:
                            issues.append(session+" unmatched fractional settlement")
                        else:
                            receivables.remove(matches[0])
                        equal(session+" fractional settlement", event["cash_value"],
                              event["fractional_quantity"]*event["cash_in_lieu_price"])
                    else:
                        raise ValueError("unsupported corporate action evidence")
                    cash += event["cash_value"]
                for event in groups.get("terminal_events", []):
                    symbol = event["symbol"]
                    if shares.get(symbol, 0) != event["quantity"]:
                        issues.append(session+" terminal quantity differs")
                    equal(session+" terminal proceeds", event["proceeds"],
                          event["quantity"]*event["reference_price"]*max(0., 1+event["terminal_return"]))
                    cash += event["proceeds"]
                    shares.pop(symbol, None)
                for fill in groups.get("fills", []):
                    symbol, quantity = fill["symbol"], fill["quantity"]
                    if (type(quantity) is not int or quantity <= 0 or fill["side"] not in {"BUY", "SELL"}
                            or not math.isfinite(fill["fees"]) or fill["fees"] < 0):
                        raise ValueError("invalid fill quantity, side or fees")
                    equal(session+" fill gross", fill["gross_value"], quantity*fill["fill_price"])
                    if fill["side"] == "BUY":
                        amount = fill["gross_value"]+fill["fees"]
                        cash -= amount
                        shares[symbol] = shares.get(symbol, 0)+quantity
                    else:
                        amount = fill["gross_value"]-fill["fees"]
                        cash += min(0., amount)
                        shares[symbol] = shares.get(symbol, 0)-quantity
                    obligations.append({"trade_date": session, "symbol": symbol, "side": fill["side"],
                        "amount": amount, "due": count+2, "settled_at": None})
                for row in obligations:
                    if row["settled_at"] is None and row["due"] == count:
                        row["settled_at"] = session
                        if row["side"] == "SELL" and row["amount"] >= 0:
                            cash += row["amount"]
                actual_obligations = [{"trade_date": row.trade_date, "symbol": row.symbol, "side": row.side,
                    "amount": row.amount, "due": count+row.remaining_sessions if row.settled_at is None else None,
                    "settled_at": row.settled_at} for row in state.settlements]
                expected_obligations = [{**row, "due": row["due"] if row["settled_at"] is None else None} for row in obligations]
                if actual_obligations != expected_obligations:
                    issues.append(session+" settlement history differs")
                if {s:q for s,q in shares.items() if q} != {s:q for s,q in state.shares if q}:
                    issues.append(session+" positions differ")
                if sorted(receivables) != sorted((r.symbol,r.fractional_quantity,r.settlement_date) for r in state.receivables):
                    issues.append(session+" fractional rights differ")
                value = sum(quantity*marks[symbol] for symbol,quantity,_ in receivables)
                outstanding = [row for row in obligations if row["settled_at"] is None]
                buy = sum(row["amount"] for row in outstanding if row["side"] == "BUY")
                sale = sum(row["amount"] for row in outstanding if row["side"] == "SELL" and row["amount"] >= 0)
                fees = sum(-row["amount"] for row in outstanding if row["side"] == "SELL" and row["amount"] < 0)
                nav = groups["nav"][0]
                equal(session+" checkpoint cash", state.cash, cash)
                equal(session+" checkpoint receivable", state.receivable_value, value)
                for key, expected in {"cash":cash,"settled_cash":cash+buy+fees,"buy_payables":buy,
                    "sale_receivables":sale,"sale_payables":fees,"receivable_value":value,
                    "equity":cash+sum(q*marks[s] for s,q in shares.items() if q)+sale+value}.items():
                    equal(session+" NAV "+key, nav[key], expected)
                previous = stamp
                previous_state = state
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, sqlite3.Error, OSError) as exc:
        issues.append("insufficient or invalid accounting evidence: "+str(exc))
    return AccountingAudit(tuple(issues), count)
