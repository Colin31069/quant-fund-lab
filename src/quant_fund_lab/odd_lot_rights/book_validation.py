"""Cross-leg checkpoint and original-command consistency, not source authentication."""
import json
import re
from dataclasses import asdict
from zoneinfo import ZoneInfo


def validate_history(book) -> None:
    from .codec import canonical
    from .types import clock, quantity

    if book.through is not None:
        stamp = clock(book.through)
        today = stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        times = [clock(json.loads(row.command_json)["as_of"]) for row in book.receipts]
        if times and (times != sorted(times) or times[-1] != stamp):
            raise ValueError("rights receipt sequence differs from the completed clock")
        if any(clock(row.event.available_at) > stamp or row.event.ex_session > today
               or (row.last_payment_session or row.event.ex_session) > today for row in book.positions):
            raise ValueError("rights checkpoint contains future ownership or payments")
    elif book.positions or book.receipts:
        raise ValueError("nonempty rights book requires its completed clock")
    if book.positions and not book.receipts:
        raise ValueError("rights positions require original command receipts")
    groups = {}
    for row in book.positions:
        groups.setdefault(row.event.event_id, []).append(row)
    grants, declarations = {}, {}
    for receipt in book.receipts:
        command = json.loads(receipt.command_json)
        if command["kind"] in {"grant", "revise"}:
            declared = command.get("event")
            if not isinstance(declared, dict):
                raise ValueError("rights event command requires its original terms")
            event_id = declared.get("event_id")
            if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-f]{64}", event_id):
                raise ValueError("rights event command has invalid identity")
            if command["kind"] == "grant":
                if event_id in grants:
                    raise ValueError("duplicate entitlement event in command history")
                quantity(command.get("eligible_units"))
                grants[event_id] = command["eligible_units"]
            elif event_id not in grants:
                raise ValueError("rights revision precedes the original grant")
            declarations[event_id] = declared
        if command["kind"] in {"grant", "revise"}:
            terms = [command["event"]]
        elif command["kind"] in {"subscribe", "policy_election"}:
            container = command
            extra = []
            if command["kind"] == "policy_election":
                container = command.get("terms")
                if not isinstance(container, dict) or not isinstance(container.get("cutoffs"), list):
                    raise ValueError("policy election requires its original cutoff terms")
                extra = [container, *container["cutoffs"]]
            requests = container.get("requests")
            if not isinstance(requests, list) or any(not isinstance(row, dict) for row in requests):
                raise ValueError("subscription command requires its original requests")
            terms = [*extra, *(row.get("terms") for row in requests)]
        else:
            terms = [command.get("terms")]
        for term in terms:
            if (not isinstance(term, dict) or "available_at" not in term
                    or clock(term["available_at"]) > clock(command["as_of"])):
                raise ValueError("rights command used missing or future terms")
    if set(groups) != set(grants):
        raise ValueError("rights event positions differ from original grant commands")
    for event_id, rows in groups.items():
        first = rows[0]
        if ({row.leg_id for row in rows} != {leg.leg_id for leg in first.event.legs}
                or any(row.event != first.event or row.eligible_parent_units != grants[event_id] for row in rows)):
            raise ValueError("rights event requires every leg and a shared original ownership basis")
        if json.loads(canonical(asdict(first.event))) != declarations[event_id]:
            raise ValueError("rights event differs from latest recorded terms")
