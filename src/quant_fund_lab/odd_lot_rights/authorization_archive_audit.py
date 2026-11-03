"""Independently bind complete frozen instruction catalogs to payment receipts."""
import json
from zoneinfo import ZoneInfo

from .audit_reconstruction import _amount, _keys, _terms
from .codec import fingerprint
from .types import clock, evidence, quantity


def validate_authorization_archive(policy, authorizations, receipts):
    """Check original JSON assertions without production policy/payment calls.

    Receipt cash/quantity equations are checked by the separate inventory audit.
    Historical registration/publication and an external initial anchor still
    need authentication; internally consistent replacement history is not proof.
    """
    _keys(policy, "schema_version timezone frozen_at elections cash_rule unlisted_action")
    frozen = clock(policy["frozen_at"])
    if (type(policy["schema_version"]) is not int or policy["schema_version"] != 1
            or policy["timezone"] != "Asia/Taipei" or policy["cash_rule"] != "usable_cash_only_atomic"
            or policy["unlisted_action"] != "do_not_subscribe"):
        raise ValueError("archive has unsupported frozen instruction policy")
    elections = policy["elections"]
    if not isinstance(elections, list):
        raise TypeError("archive elections must be explicit lists")
    declared = {}
    for election in elections:
        _keys(election, "action_id requests")
        action, requests = election["action_id"], election["requests"]
        if not isinstance(action, str) or not action or action in declared or not isinstance(requests, list) or not requests:
            raise ValueError("archive election identity/batch invalid")
        keys = []
        for request in requests:
            _keys(request, "terms units fee")
            _terms(request["terms"], "subscribe", policy["frozen_at"])
            quantity(request["units"])
            if request["units"] == 0:
                raise ValueError("archive election requires positive whole units")
            _amount(request["fee"])
            keys.append(request["terms"]["right_key"])
        if keys != sorted(set(keys)):
            raise ValueError("archive election legs are not unique and canonical")
        declared[action] = requests
    if list(declared) != sorted(declared):
        raise ValueError("archive election actions are not canonically ordered")
    if not isinstance(authorizations, list):
        raise TypeError("archive authorizations must be explicit lists")
    semantics = {"name": "authorization:"+fingerprint(policy), "frozen_at": policy["frozen_at"],
        "participation": "explicit_election", "insufficient_funds": "reject_batch",
        "fractional_rights": "retain_until_evidenced", "valuation": "explicit_current_marks",
        "cash_source": "already_usable", "cutoff_boundary": "inclusive", "schema_version": 1}
    payments = []
    for receipt in receipts:
        command = json.loads(receipt.command_json)
        if command["kind"] not in {"subscribe", "policy_election"}:
            continue
        if command["kind"] == "policy_election" and command["terms"].get("decision") == "decline":
            keys = command["terms"].get("right_keys")
            if (receipt.action_id in declared or clock(command["as_of"]) < frozen
                    or not isinstance(keys, list) or not keys
                    or any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys)):
                raise ValueError("archive decline conflicts with frozen election scope")
            expected = {"as_of": command["as_of"], "kind": "policy_election", "terms": {
                "available_at": policy["frozen_at"], "policy": semantics, "policy_id": fingerprint(semantics),
                "decision": "decline", "right_keys": keys, "requests": [], "cutoffs": []}}
            if command != expected:
                raise ValueError("archive decline differs from frozen participation semantics")
        else:
            payments.append(receipt)
    if len(payments) != len(authorizations):
        raise ValueError("archive requires exactly one original authorization per payment receipt")
    seen = set()
    for authorization, receipt in zip(authorizations, payments):
        _keys(authorization, "policy action_id requests intervals as_of")
        action, now = authorization["action_id"], clock(authorization["as_of"])
        if (authorization["policy"] != policy or action != receipt.action_id or action in seen
                or action not in declared or authorization["requests"] != declared[action] or now < frozen):
            raise ValueError("archive original authorization differs from complete frozen election")
        seen.add(action)
        intervals, requests = authorization["intervals"], authorization["requests"]
        if not isinstance(intervals, list) or len(intervals) != len(requests):
            raise ValueError("archive requires every elected leg's original daily interval")
        today = now.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        cutoffs = []
        for interval, request in zip(intervals, requests):
            _keys(interval, "right_key starts_at ends_at available_at evidence_sha256")
            evidence(interval["available_at"], tuple(interval["evidence_sha256"]))
            opening, cutoff = clock(interval["starts_at"]), clock(interval["ends_at"])
            terms = request["terms"]
            if (interval["right_key"] != terms["right_key"] or clock(interval["available_at"]) > now
                    or opening >= cutoff or not opening <= now <= cutoff
                    or opening.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != today
                    or cutoff.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != today
                    or not terms["payment_start"] <= today <= terms["payment_end"]):
                raise ValueError("archive payment is outside its known daily window")
            cutoffs.append({"right_key": interval["right_key"], "opens_at": interval["starts_at"],
                "cutoff_at": interval["ends_at"], "available_at": interval["available_at"],
                "evidence_sha256": interval["evidence_sha256"]})
        command = json.loads(receipt.command_json)
        if command["kind"] == "subscribe":
            expected = {"as_of": authorization["as_of"], "kind": "subscribe", "requests": requests}
        else:
            expected = {"as_of": authorization["as_of"], "kind": "policy_election", "terms": {
                "available_at": policy["frozen_at"], "policy": semantics, "policy_id": fingerprint(semantics),
                "decision": "pay", "right_keys": [row["terms"]["right_key"] for row in requests],
                "requests": requests, "cutoffs": cutoffs}}
        if command != expected:
            raise ValueError("archive original authorization does not match canonical payment receipt")
