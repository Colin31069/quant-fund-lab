"""Independent policy/cutoff checks on original election commands."""
from zoneinfo import ZoneInfo

from .codec import fingerprint
from .types import clock, evidence


def _keys(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ValueError("audit policy election schema differs")


def audit_policy_election(command, positions):
    """Return a bare payment for financial reconstruction, or None for decline.

    Do not call policy constructors, production authorization or transitions.
    This proves declared semantics and clock consistency, not source truth.
    """
    _keys(command, "as_of kind terms")
    terms = command["terms"]
    _keys(terms, "available_at policy policy_id decision right_keys requests cutoffs")
    policy = terms["policy"]
    _keys(policy, "name frozen_at participation insufficient_funds fractional_rights valuation cash_source cutoff_boundary schema_version")
    stamp = clock(command["as_of"])
    if (not isinstance(policy["name"], str) or not policy["name"]
            or type(policy["schema_version"]) is not int or policy["schema_version"] != 1
            or policy["participation"] not in {"explicit_election", "decline_all"}
            or policy["insufficient_funds"] != "reject_batch"
            or policy["fractional_rights"] != "retain_until_evidenced"
            or policy["valuation"] != "explicit_current_marks"
            or policy["cash_source"] != "already_usable"
            or policy["cutoff_boundary"] not in {"inclusive", "exclusive"}
            or fingerprint(policy) != terms["policy_id"]
            or terms["available_at"] != policy["frozen_at"] or clock(policy["frozen_at"]) > stamp):
        raise ValueError("audit policy identity, behavior or knowledge clock differs")
    keys = terms["right_keys"]
    if (not isinstance(keys, list) or not keys or any(not isinstance(key, str) or not key for key in keys)
            or len(set(keys)) != len(keys)):
        raise ValueError("audit election requires explicit unique rights scope")
    for key in keys:
        row = positions[key]
        leg = next(leg for leg in row["event"]["legs"] if leg["leg_id"] == row["leg_id"])
        if leg["kind"] != "subscription" or row["unpaid"] <= 0:
            raise ValueError("audit election scope has no unpaid subscription right")
    requests, windows = terms["requests"], terms["cutoffs"]
    if not isinstance(requests, list) or not isinstance(windows, list):
        raise TypeError("audit election requests/cutoffs must be explicit lists")
    decision = terms["decision"]
    if decision not in {"pay", "decline"} or (policy["participation"] == "decline_all" and decision != "decline"):
        raise ValueError("audit payment decision conflicts with frozen participation policy")
    if decision == "decline":
        if requests or windows:
            raise ValueError("audit decline policy contains a payment")
        return None
    requested = [row["terms"]["right_key"] for row in requests]
    for window in windows:
        _keys(window, "right_key opens_at cutoff_at available_at evidence_sha256")
    cutoff_keys = [row["right_key"] for row in windows]
    if (not requests or len(set(requested)) != len(requested) or set(requested) != set(keys)
            or len(set(cutoff_keys)) != len(cutoff_keys) or set(cutoff_keys) != set(keys)):
        raise ValueError("audit request/cutoff scope differs from declared election")
    zone = ZoneInfo("Asia/Taipei")
    today = stamp.astimezone(zone).date()
    for window in windows:
        evidence(window["available_at"], tuple(window["evidence_sha256"]))
        opening, cutoff = clock(window["opens_at"]), clock(window["cutoff_at"])
        if (clock(window["available_at"]) > stamp or opening >= cutoff
                or opening.astimezone(zone).date() != today or cutoff.astimezone(zone).date() != today
                or stamp < opening or stamp > cutoff
                or (stamp == cutoff and policy["cutoff_boundary"] == "exclusive")):
            raise ValueError("audit payment is outside its known daily cutoff")
    return {"kind": "subscribe", "as_of": command["as_of"], "requests": requests}
