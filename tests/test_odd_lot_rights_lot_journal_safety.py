"""Rehashed journal mutations cannot bypass lot ownership, cash or release checks."""
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_odd_lot_rights_lot_posting import POLICY, post, split_case
from test_odd_lot_rights_transitions import HASHES

from quant_fund_lab.odd_lot_rights.codec import canonical, fingerprint
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.lot_flow import post_projected_lot_session


@pytest.mark.parametrize("change", ["ratio", "early_release", "fill_quantity", "gross", "future_open", "prefix", "execution_cash"])
def test_rehashed_lot_journal_or_initial_anchor_corruption_is_rejected(monkeypatch, change):
    original, inputs, events, opening = split_case(monkeypatch)
    done = post(original, inputs, events)
    encoded = encode_inventory(done.account)
    payload = json.loads(encoded)
    book = json.loads(payload["book"])
    receipt = book["book"]["receipts"][-1]
    command = json.loads(receipt["command_json"])
    journal = command["terms"]["lot_journal"]
    if change == "ratio":
        journal["events"][0]["ratio"] = "3"
    elif change == "early_release":
        journal["final_lots"][0]["tradable_session"] = opening
    elif change == "fill_quantity":
        journal["fills"][0]["units"] = 5
        journal["fills"][0]["gross"] = "250"
    elif change == "gross":
        journal["fills"][0]["gross"] = "199"
    elif change == "future_open":
        journal["opening_at"] = opening+"T17:00:00+08:00"
    elif change == "prefix":
        payload["initial_lots"][0]["tradable_session"] = "2025-01-01"
    else:
        command["terms"]["link"]["execution_cash"] = "-1"
    receipt["command_json"] = canonical(command)
    receipt["payload_sha256"] = fingerprint(command)
    payload["book"] = canonical(book)
    with pytest.raises(ValueError):
        decode_inventory(canonical(payload))
    assert encode_inventory(done.account) == encoded


def test_changed_replay_and_forged_engine_result_leave_original_accounts_unchanged(monkeypatch):
    original, inputs, events, opening = split_case(monkeypatch)
    done = post(original, inputs, events)
    before = encode_inventory(original)
    bad_runtime = deepcopy(done.execution.result.runtime)
    bad_runtime.portfolio.cash += 1
    bad_result = replace(done.execution.result, runtime=bad_runtime,
                         nav={**done.execution.result.nav, "cash": 1.})
    with pytest.raises(ValueError, match="differs from reconstructed source session"):
        post_projected_lot_session(original, replace(done.execution, result=bad_result), inputs,
            "session", events, POLICY, opening_at=opening+"T09:00:00+08:00",
            as_of=opening+"T16:00:00+08:00", available_at=opening+"T16:00:00+08:00",
            evidence_sha256=HASHES)
    assert encode_inventory(original) == before
    completed = encode_inventory(done.account)
    with pytest.raises(ValueError, match="payload changed"):
        post_projected_lot_session(done.account, done.execution, inputs,
            "session", events, POLICY, opening_at=opening+"T09:00:00+08:00",
            as_of=opening+"T16:01:00+08:00", available_at=opening+"T16:00:00+08:00",
            evidence_sha256=HASHES, recorded_before=original)
    assert encode_inventory(done.account) == completed
