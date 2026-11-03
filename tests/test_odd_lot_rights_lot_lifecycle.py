"""Split, locked exit, T+2, policy payment and next engine buy share one account."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_lot_posting import post, split_case
from test_odd_lot_rights_transitions import HASHES, event

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state
from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
from quant_fund_lab.odd_lot_rights.payment_authorization import (
    apply_authorized_subscription,
    authorize_subscription,
)
from quant_fund_lab.odd_lot_rights.session_nav import value_session_nav
from quant_fund_lab.odd_lot_rights.session_policy import (
    PaymentInterval,
    RightsSessionPolicy,
    SubscriptionElection,
)
from quant_fund_lab.odd_lot_rights.session_projection import project_rights_session
from quant_fund_lab.odd_lot_rights.transitions import grant_entitlements
from quant_fund_lab.odd_lot_rights.types import EntitlementLeg, PaymentRequest, PaymentTerms
from quant_fund_lab.odd_lot_rights.valuation import RightsMark


@pytest.mark.parametrize("restart", [False, True])
def test_real_split_exit_settlement_payment_next_buy_and_joined_nav(monkeypatch, restart):
    original, first_inputs, events, _ = split_case(monkeypatch)
    data = first_inputs.data
    first = post(original, first_inputs, events, action="first")
    account, runtime = first.account, first.execution.result.runtime
    ex_day = str(data.close.index[32].date())
    terms = replace(event(), parent_security_id="2330.TW", ex_session=ex_day,
        available_at=ex_day+"T08:00:00+08:00",
        legs=(EntitlementLeg("paid", "ordinary-new", "subscription", D("0.25")),))
    # Eight owned post-split shares are the next day's pre-event ownership.
    account = post_rights_transition(account, grant_entitlements(account.book, "grant", terms, 8,
                                    as_of=ex_day+"T08:00:00+08:00"))
    payment = PaymentTerms(account.book.positions[0].key, D(10), ex_day,
                          str(data.close.index[34].date()), ex_day+"T08:00:00+08:00", HASHES)
    batch = (PaymentRequest(payment, 1, D(0)),)
    policy = RightsSessionPolicy(1, "Asia/Taipei", ex_day+"T08:01:00+08:00",
        (SubscriptionElection("pay", batch),), "usable_cash_only_atomic", "do_not_subscribe")
    cash = [account.cash]
    for index in (31, 32):
        if restart:
            account = decode_inventory(encode_inventory(account))
            day = str(data.close.index[index].date())
            checkpoint = capture_session_state(runtime, session=day,
                origin_session=str(data.close.index[29].date()), session_offset=index-29, completed_index=index)
            runtime = restore_session_state(checkpoint, completed_index=index)
        inputs = replace(first_inputs, runtime=runtime, signal_index=index)
        completed = post(account, inputs, action="session-"+str(index))
        account, runtime = completed.account, completed.execution.result.runtime
        cash.append(account.cash)
    assert cash == [D(0), D(0), D(200)]
    day = str(data.close.index[33].date())
    windows = (PaymentInterval(payment.right_key, day+"T09:00:00+08:00", day+"T17:00:00+08:00",
                               ex_day+"T08:00:00+08:00", HASHES),)
    auth = authorize_subscription(policy, "pay", batch, windows, as_of=day+"T16:01:00+08:00")
    account = post_rights_transition(account, apply_authorized_subscription(account.book, auth))
    assert account.cash == 190 and runtime.portfolio.cash == 200
    projected = project_rights_session(account, runtime, completed_session=day,
        origin_session=str(data.close.index[29].date()), session_offset=4, completed_index=33,
        as_of=day+"T16:05:00+08:00")
    runtime = restore_session_state(projected.checkpoint, completed_index=33)
    if restart:
        account = decode_inventory(encode_inventory(account))
    inputs = replace(first_inputs, runtime=runtime, signal_index=33)
    final = post(account, inputs, action="after-payment")
    assert [(row["symbol"], row["quantity"]) for row in final.execution.result.fills] == [("2317.TW", 1)]
    assert final.account.cash == 490 and final.account.book.positions[0].pending == 1
    assert decode_inventory(encode_inventory(final.account)) == final.account
    final_day = str(data.close.index[34].date())
    mark_at = final_day+"T16:01:00+08:00"
    securities = (SecurityMark("2317.TW", D(100), final_day, mark_at, HASHES),)
    rights = tuple(RightsMark(payment.right_key, component, price, final_day, mark_at, HASHES)
                   for component, price in (("unpaid", D(0)), ("pending", D(10))))
    nav = value_session_nav(final.account, replace(inputs, sale_limits=final.execution.projection.sale_limits),
                            final.execution.result, securities, rights, as_of=mark_at)
    assert nav.nav == 600
    before = encode_inventory(final.account)
    replay = post(final.account, first_inputs, events, action="first", recorded_before=original)
    assert not replay.applied and encode_inventory(replay.account) == before
