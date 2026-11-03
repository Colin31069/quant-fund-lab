"""Independent engine risk equations and post-close receipt exit reconstruction."""
import json
from dataclasses import dataclass, replace

from ..odd_lot_paper.audit_risk import reconcile_risk_state


@dataclass(frozen=True)
class DayRiskAudit:
    issues: tuple[str, ...]
    scope: str = "independent_engine_stop_pending_and_declared_conversion_risk_equations"

    @property
    def passed(self) -> bool:
        return not self.issues


def audit_day_risk(previous, engine_close, final, account, action_id, groups,
                   research, opening_stops, conversion_risks) -> DayRiskAudit:
    """Rebuild risk without calling signal planning or production risk transfer.

    Alpha targets and new-instrument stop levels are explicit supplied policy
    inputs, not independently estimated market risk or authenticated facts.
    Financial quantities/ownership are checked by the separate account audits.
    """
    try:
        issues = list(reconcile_risk_state(previous, engine_close, groups, research))
        if engine_close.session != final.session or engine_close.origin_session != final.origin_session:
            raise ValueError("risk projection changed its completed session boundary")
        for name in ("session_offset", "receivable_value", "settlements", "receivables", "terminated", "passive_submitted"):
            if getattr(engine_close, name) != getattr(final, name):
                issues.append("risk projection changed retained engine "+name)
        stops = {row.symbol: row for row in engine_close.stops}
        pending = {row.symbol: row for row in engine_close.pending}
        owned = dict(final.shares)
        commands = {row.action_id: (index, json.loads(row.command_json)) for index, row in enumerate(account.inventory.book.receipts)}
        anchor = commands[action_id][0]
        if len({row.conversion_action_id for row in conversion_risks}) != len(conversion_risks):
            raise ValueError("risk audit duplicate conversion mapping")
        sources, destinations = set(), set()
        for mapping in conversion_risks:
            index, command = commands[mapping.conversion_action_id]
            if index <= anchor or command["kind"] != "convert" or mapping.pending_policy != "carry_receipt_exit":
                raise ValueError("risk audit mapping lacks a later supported conversion")
            terms = command["terms"]
            source, target = terms["receipt_security_id"], terms["final_security_id"]
            if (source in sources or target in destinations or target != mapping.final_stop.symbol
                    or not owned.get(target, 0)):
                raise ValueError("risk audit conversion identity or owned target differs")
            sources.add(source)
            destinations.add(target)
            old = pending.get(source)
            if old is not None and old.side == "SELL":
                transfer = mapping.final_exit
                if (transfer is None or transfer.side != "SELL" or transfer.symbol != target
                        or transfer.reason != old.reason or transfer.quantity != owned[target]
                        or transfer.stop != mapping.final_stop.stop or transfer.distance != mapping.final_stop.distance):
                    raise ValueError("risk audit conversion lost or changed the original exit")
                pending[target] = transfer
                if owned.get(source, 0):
                    pending[source] = replace(old, quantity=owned[source])
                else:
                    del pending[source]
            elif mapping.final_exit is not None:
                raise ValueError("risk audit invented a conversion exit without a prior sell")
            elif old is not None and old.side == "BUY":
                if mapping.cancel_receipt_buy:
                    del pending[source]
                elif not owned.get(source, 0):
                    raise ValueError("risk audit removed receipt BUY without cancellation policy")
            stops[target] = mapping.final_stop
            if not owned.get(source, 0):
                stops.pop(source, None)
        if sources & destinations:
            raise ValueError("risk audit chained conversions need ordered separate projections")
        stops = {symbol: row for symbol, row in stops.items() if owned.get(symbol, 0)}
        supplied = {row.symbol: row for row in opening_stops}
        if len(supplied) != len(opening_stops) or set(supplied) != {key for key, units in owned.items() if units}-set(stops):
            raise ValueError("risk audit new-held stops are missing, duplicate or unrelated")
        stops.update(supplied)
        if any(row.side == "SELL" and not owned.get(symbol, 0) for symbol, row in pending.items()):
            raise ValueError("risk audit pending sale has no remaining owned position")
        if tuple(stops[key] for key in sorted(stops)) != final.stops:
            issues.append("risk projection final stops differ from independent reconstruction")
        if tuple(pending[key] for key in sorted(pending)) != final.pending:
            issues.append("risk projection final pending orders differ from independent reconstruction")
        return DayRiskAudit(tuple(issues))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError) as exc:
        return DayRiskAudit(("invalid day risk evidence: "+str(exc),))


def engine_risk_groups(inputs, result):
    """Extract original observed inputs; quantities/decisions are not recalculated."""
    i = inputs.signal_index
    data = inputs.data
    return {"risk_inputs": [{"close": data.raw_close.iloc[i].to_dict(),
        "observed_open": data.raw_open.iloc[i].to_dict(),
        "dividends": data.dividends.iloc[i+1].to_dict(), "splits": data.stock_splits.iloc[i+1].to_dict(),
        "terminal_symbols": tuple(data.terminal_returns.iloc[i+1].dropna().index)}],
        **{name: list(getattr(result, name)) for name in ("signals", "fills", "actions")}}
