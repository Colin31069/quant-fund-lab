"""Hypothetical distinct parent/receipt/final identities with actual engine fills."""
from dataclasses import replace
from decimal import Decimal as D

import pandas as pd

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.bridge import HistoricalSessionState, restore_session_state
from quant_fund_lab.odd_lot_paper.engine_records import EngineStop
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput
from quant_fund_lab.odd_lot_paper.types import PendingOrder, StopState
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config
from quant_fund_lab.odd_lot_rights.conversion_risk import ReceiptRiskTransfer
from quant_fund_lab.odd_lot_rights.inventory import (
    RightsInventory,
    SecurityLot,
    post_rights_transition,
)
from quant_fund_lab.odd_lot_rights.lot_events import LotRoundingPolicy
from quant_fund_lab.odd_lot_rights.lot_flow import run_and_post_lot_session
from quant_fund_lab.odd_lot_rights.payment_authorization import (
    apply_authorized_subscription,
    authorize_subscription,
)
from quant_fund_lab.odd_lot_rights.session_policy import (
    PaymentInterval,
    RightsSessionPolicy,
    SubscriptionElection,
)
from quant_fund_lab.odd_lot_rights.session_projection import project_rights_session
from quant_fund_lab.odd_lot_rights.settlement import ReceiptConversionTerms, convert_receipt
from quant_fund_lab.odd_lot_rights.transitions import deliver_claim, grant_entitlements
from quant_fund_lab.odd_lot_rights.types import (
    DeliveryTerms,
    EntitlementEvent,
    EntitlementLeg,
    PaymentRequest,
    PaymentTerms,
    RightsBook,
)

PARENT, RECEIPT, FINAL = "PARENT.TW", "RECEIPT.TW", "FINAL.TW"
HASHES = ("b"*64,)
LOT_POLICY = LotRoundingPolicy(1, "latest_contributor_release")


def post(account, inputs, action):
    day = str(inputs.data.close.index[inputs.signal_index+1].date())
    return run_and_post_lot_session(account, (), LOT_POLICY, inputs, action,
        opening_at=day+"T09:00:00+08:00", as_of=day+"T16:00:00+08:00",
        available_at=day+"T16:00:00+08:00", evidence_sha256=HASHES)


def project(account, runtime, inputs, day, *, conversion_risks=(), opening_stops=()):
    index = inputs.data.close.index.get_loc(pd.Timestamp(day))
    value = project_rights_session(account, runtime, completed_session=day,
        origin_session=str(inputs.data.close.index[29].date()), session_offset=index-29,
        completed_index=index, as_of=day+"T16:10:00+08:00",
        conversion_risks=conversion_risks, opening_stops=opening_stops)
    return value, restore_session_state(value.checkpoint, completed_index=index)


def converted_case(monkeypatch, *, conversion_units=3, workflow_context=False):
    dates = pd.bdate_range("2024-01-02", periods=40)
    prices = pd.DataFrame(100., index=dates, columns=[PARENT, RECEIPT, FINAL])
    prices.loc[dates[:30], RECEIPT] = float("nan")
    prices.loc[dates[32]:, RECEIPT] = float("nan")
    volume = prices*1000000
    membership = prices.notna()
    data = MarketData(prices, prices, volume, membership=membership, base_currency="TWD")
    research = OddLotResearchConfig(strategy="momentum", max_positions=3, max_weight=1.,
        rebalance_every=1000, min_commission=0., commission_bps=0., slippage_bps=0.,
        fill_fraction=1., max_participation=1., impact_coefficient=0.,
        instrument_rules={symbol: {"kind": "stock", "sell_tax_bps": 0., "price_limit_pct": .1}
                          for symbol in prices.columns})
    base = BacktestConfig(initial_cash=100., base_currency="TWD", strategy=StrategyConfig(warmup_days=30))
    config = odd_lot_backtest_config(base, research)

    def targets(history, *_):
        weights = pd.Series(0., index=history.columns)
        weights[PARENT] = 1.
        return pd.Series(1., index=history.columns), weights

    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets", targets)
    runtime = HistoricalSessionState(PortfolioState(100., {PARENT: 5}),
        {PARENT: EngineStop(95., 100., .05)}, {}, set(), [], [], False)
    lots = (SecurityLot("opening", PARENT, 5, str(dates[29].date())),)
    account = RightsInventory(D(100), lots, RightsBook(D(100)), lots)
    inputs = OddLotSessionInput(runtime, data, research, config, 29, 29, prior_session_liquidity(data.volume))
    initial_account, initial_inputs = account, inputs
    first = post(account, inputs, "first")
    account, runtime = first.account, first.execution.result.runtime
    day, release = str(dates[30].date()), str(dates[33].date())
    event = EntitlementEvent("a"*64, PARENT, day, day+"T08:00:00+08:00", HASHES,
        (EntitlementLeg("receipt", "ordinary-claim", "subscription", D(1)),))
    account = post_rights_transition(account, grant_entitlements(account.book, "grant", event, 5,
                                    as_of=day+"T16:01:00+08:00"))
    key = account.book.positions[0].key
    payment = PaymentTerms(key, D(10), day, day, day+"T08:00:00+08:00", HASHES)
    batch = (PaymentRequest(payment, 5, D(0)),)
    policy = RightsSessionPolicy(1, "Asia/Taipei", day+"T08:00:00+08:00",
        (SubscriptionElection("pay", batch),), "usable_cash_only_atomic", "do_not_subscribe")
    interval = PaymentInterval(key, day+"T09:00:00+08:00", day+"T17:00:00+08:00", day+"T08:00:00+08:00", HASHES)
    authorization = authorize_subscription(policy, "pay", batch, (interval,), as_of=day+"T16:02:00+08:00")
    account = post_rights_transition(account, apply_authorized_subscription(account.book, authorization))
    deliveries = []
    for name, units, tradable, minute in (("free-delivery", 2, day, "03"), ("locked-delivery", 3, release, "04")):
        terms = DeliveryTerms(key, "ordinary-claim", RECEIPT, day, tradable, day+"T08:00:00+08:00", HASHES, D(0))
        deliveries.append((name, units, terms, day+"T16:"+minute+":00+08:00"))
        account = post_rights_transition(account, deliver_claim(account.book, name, terms, units,
                                        as_of=day+"T16:"+minute+":00+08:00"))
    first_day_account = account
    first_projection, runtime = project(account, runtime, inputs, day, opening_stops=(StopState(RECEIPT, 105., 110., .05),))
    inputs = replace(inputs, runtime=runtime, signal_index=30)
    partial = post(account, inputs, "partial-sale")
    account, runtime = partial.account, partial.execution.result.runtime
    assert [(row["symbol"], row["quantity"]) for row in partial.execution.result.fills] == [(RECEIPT, 2)]
    day = str(dates[31].date())
    terms = ReceiptConversionTerms(key, "ordinary-claim", RECEIPT, FINAL, day, release,
                                    day+"T08:00:00+08:00", HASHES, D(0))
    account = post_rights_transition(account, convert_receipt(account.book, "convert", terms, conversion_units,
                                    as_of=day+"T16:01:00+08:00"))
    stop = StopState(FINAL, 95., 100., .05)
    exit_order = PendingOrder(FINAL, "SELL", conversion_units, "stop", 95., 100., .05, 100000000.)
    mapping = ReceiptRiskTransfer("convert", stop, exit_order, "carry_receipt_exit", False)
    if workflow_context:
        return {"initial_account": initial_account, "initial_inputs": initial_inputs,
            "event": event, "authorization": authorization, "policy": policy, "deliveries": deliveries,
            "first_day_account": first_day_account, "first_projection": first_projection,
            "converted_account": account, "partial_inputs": inputs, "conversion_terms": terms,
            "conversion_units": conversion_units, "mapping": mapping}
    return account, runtime, inputs, partial, mapping, day
