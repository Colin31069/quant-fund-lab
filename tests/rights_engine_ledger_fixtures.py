"""Real engine trades, eligible grant, T+2 and payment in combined checkpoints."""
from dataclasses import asdict, replace
from decimal import Decimal as D

from test_odd_lot_rights_session_flow import _post, _start, _step
from test_odd_lot_rights_transitions import HASHES, event

from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state
from quant_fund_lab.odd_lot_paper.event_codec import encode_event
from quant_fund_lab.odd_lot_rights.authorization_archive import (
    AuthorizedRightsAccount,
    apply_account_authorization,
)
from quant_fund_lab.odd_lot_rights.codec import canonical, fingerprint
from quant_fund_lab.odd_lot_rights.engine_checkpoint import RightsEngineCheckpoint
from quant_fund_lab.odd_lot_rights.engine_checkpoint_codec import encode_engine_rights
from quant_fund_lab.odd_lot_rights.engine_ledger_types import (
    RightsEngineCommit,
    RightsLedgerConfig,
    payload_digest,
)
from quant_fund_lab.odd_lot_rights.inventory import post_rights_transition
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
from quant_fund_lab.odd_lot_rights.payment_authorization import authorize_subscription
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


def sequence(monkeypatch, after_record=None):
    data, research, config, runtime, inventory = _start(monkeypatch)
    dates = [str(day.date()) for day in data.close.index]
    origin, ex_day, due = dates[29], dates[31], dates[33]
    contract = replace(event(), parent_security_id="2330.TW", ex_session=ex_day,
        available_at=origin+"T08:00:00+08:00",
        legs=(EntitlementLeg("paid", "new-share-class", "subscription", D(1)),))
    terms = PaymentTerms(contract.event_id+":paid", D(10), ex_day, due,
                         origin+"T08:00:00+08:00", HASHES)
    batch = (PaymentRequest(terms, 1, D(0)),)
    policy = RightsSessionPolicy(1, "Asia/Taipei", origin+"T09:00:00+08:00",
        (SubscriptionElection("pay", batch),), "usable_cash_only_atomic", "do_not_subscribe")
    account = AuthorizedRightsAccount(inventory, policy)
    initial = RightsEngineCheckpoint(capture_session_state(runtime, session=origin,
        origin_session=origin, session_offset=0, completed_index=29), account)
    locked = RightsLedgerConfig(policy.policy_sha256, "a"*64, "b"*64, "c"*64, "d"*64,
                                payload_digest(encode_engine_rights(initial)))
    parent = payload_digest(canonical([canonical(asdict(locked)), encode_engine_rights(initial)]))
    commits = []
    for index in range(29, 35):
        day = dates[index+1]
        if index == 30:
            # Eligibility uses the three parent units held before the ex-day;
            # the actual engine sale happens only after this known grant.
            inventory = post_rights_transition(account.inventory, grant_entitlements(account.inventory.book,
                "grant", contract, 3, as_of=day+"T08:00:00+08:00"))
            account = replace(account, inventory=inventory)
        inputs, result = _step(data, research, config, runtime, index)
        account = replace(account, inventory=_post(account.inventory, inputs, result))
        if index == 32:
            interval = (PaymentInterval(terms.right_key, due+"T09:00:00+08:00",
                due+"T17:00:00+08:00", origin+"T08:00:00+08:00", HASHES),)
            authorization = authorize_subscription(account.policy, "pay", batch, interval, as_of=day+"T16:01:00+08:00")
            account = apply_account_authorization(account, authorization)
        projected = project_rights_session(account.inventory, result.runtime, completed_session=day,
            origin_session=origin, session_offset=index+1-29, completed_index=index+1,
            as_of=day+"T16:05:00+08:00")
        checkpoint = RightsEngineCheckpoint(projected.checkpoint, account)
        securities = tuple(SecurityMark(symbol, D(str(data.raw_close.iloc[index+1][symbol])), day,
            day+"T16:00:00+08:00", HASHES) for symbol in sorted({lot.security_id for lot in account.inventory.lots}))
        rights = tuple(RightsMark(row.key, part, price, day, day+"T16:00:00+08:00", HASHES)
            for row in account.inventory.book.positions
            for part, units, price in (("unpaid", row.unpaid, D(90)), ("pending", row.pending, D(100))) if units)
        nav = value_session_nav(account.inventory, inputs, result, securities, rights, as_of=day+"T16:05:00+08:00")
        groups = {name: [encode_event(row) for row in getattr(result, name)] for name in (
            "signals", "orders", "fills", "actions", "terminal_events")}
        groups["engine_nav"] = [encode_event(result.nav)]
        groups["rights_nav"] = [asdict(nav)]
        record = RightsEngineCommit(checkpoint, fingerprint({"fixture_session": day}), canonical(groups), parent)
        commits.append(record)
        parent = payload_digest(canonical([parent, encode_engine_rights(checkpoint), record.input_fingerprint,
                                          record.events_json]))
        if after_record is not None:
            stored, digest = after_record(initial, locked, record)
            assert digest == parent
            account = stored.account
            runtime = restore_session_state(stored.engine, completed_index=index+1)
        else:
            runtime = restore_session_state(projected.checkpoint, completed_index=index+1)
    return initial, locked, tuple(commits)
