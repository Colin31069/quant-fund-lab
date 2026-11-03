"""Actual T+2 close credit cannot fund an earlier intraday payment deadline."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_session_flow import _post, _start, _step
from test_odd_lot_rights_transitions import HASHES, event

from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.payment_authorization import (
    apply_authorized_subscription,
    authorize_subscription,
)
from quant_fund_lab.odd_lot_rights.session_policy import (
    PaymentInterval,
    RightsSessionPolicy,
    SubscriptionElection,
)
from quant_fund_lab.odd_lot_rights.transitions import grant_entitlements
from quant_fund_lab.odd_lot_rights.types import EntitlementLeg, PaymentRequest, PaymentTerms


@pytest.mark.parametrize("cutoff", ["14:00:00", "17:00:00"])
def test_actual_tplus2_credit_respects_cutoff_and_authoritative_cash_clock(monkeypatch, cutoff):
    data, research, config, runtime, account = _start(monkeypatch)
    inputs, result = _step(data, research, config, runtime, 29)
    account = _post(account, inputs, result)
    first = str(data.close.index[30].date())
    due = str(data.close.index[33].date())
    contract = replace(event(), parent_security_id="2330.TW", ex_session=first,
        available_at=first+"T08:00:00+08:00",
        legs=(EntitlementLeg("paid", "new-share-class", "subscription", D(1)),))
    account = post_rights_transition(account, grant_entitlements(account.book, "grant", contract, 3,
                                    as_of=first+"T16:01:00+08:00"))
    terms = PaymentTerms(account.book.positions[0].key, D(10), first, due,
                         first+"T08:00:00+08:00", HASHES)
    batch = (PaymentRequest(terms, 1, D(0)),)
    policy = RightsSessionPolicy(1, "Asia/Taipei", first+"T16:02:00+08:00",
        (SubscriptionElection("policy-pay", batch),), "usable_cash_only_atomic", "do_not_subscribe")
    intervals = (PaymentInterval(terms.right_key, due+"T09:00:00+08:00",
        due+"T"+cutoff+"+08:00", first+"T08:00:00+08:00", HASHES),)
    runtime = result.runtime
    cash = [account.cash]
    for index in range(30, 33):
        inputs, result = _step(data, research, config, runtime, index)
        if index == 32:
            assert account.cash == 0
            early = authorize_subscription(policy, "policy-pay", batch, intervals,
                                            as_of=due+"T14:00:00+08:00")
            before = encode_inventory(account)
            with pytest.raises(ValueError, match="insufficient usable cash"):
                apply_authorized_subscription(account.book, early)
            assert encode_inventory(account) == before
        account = _post(account, inputs, result)
        cash.append(account.cash)
        runtime = result.runtime
    assert cash == [D(0), D(0), D(0), D(300)]
    account = decode_inventory(encode_inventory(account))
    before = encode_inventory(account)
    with pytest.raises(ValueError, match="cannot precede the completed clock"):
        apply_authorized_subscription(account.book, early)
    if cutoff == "14:00:00":
        with pytest.raises(ValueError, match="outside the evidenced"):
            authorize_subscription(policy, "policy-pay", batch, intervals,
                                    as_of=due+"T16:01:00+08:00")
        assert encode_inventory(account) == before
    else:
        authorized = authorize_subscription(policy, "policy-pay", batch, intervals,
                                             as_of=due+"T16:01:00+08:00")
        account = post_rights_transition(account,
            apply_authorized_subscription(account.book, authorized))
        assert account.cash == 290 and account.book.positions[0].pending == 1
        assert decode_inventory(encode_inventory(account)) == account
