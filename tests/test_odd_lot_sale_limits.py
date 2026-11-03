"""Opening caps retain owned units, stop retries and actual settlement economics."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal as D

import pytest
from test_odd_lot_opening import _inputs
from test_odd_lot_rights_session_flow import _post, _start, _step
from test_odd_lot_rights_session_projection import funded, project
from test_odd_lot_rights_transitions import HASHES

from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.audit_risk import reconcile_risk_state
from quant_fund_lab.odd_lot_paper.bridge import capture_session_state, restore_session_state
from quant_fund_lab.odd_lot_paper.engine_records import EngineOrder, EngineStop
from quant_fund_lab.odd_lot_paper.opening import execute_opening_orders
from quant_fund_lab.odd_lot_paper.sale_limits import OpeningSaleLimits
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput, run_odd_lot_session
from quant_fund_lab.odd_lot_paper.types import StopState
from quant_fund_lab.odd_lot_rights.execution_capacity import opening_sale_limits
from quant_fund_lab.odd_lot_rights.inventory import (
    RightsInventory,
    SecurityLot,
    post_rights_transition,
)
from quant_fund_lab.odd_lot_rights.inventory_codec import decode_inventory, encode_inventory
from quant_fund_lab.odd_lot_rights.session_link import reconcile_session_portfolio
from quant_fund_lab.odd_lot_rights.transitions import deliver_claim
from quant_fund_lab.odd_lot_rights.types import DeliveryTerms, RightsBook


@pytest.mark.parametrize("cap", [0, 2, 5])
def test_real_opening_sells_only_allowed_units_and_retains_exit_retry(cap):
    inputs = _inputs(PortfolioState(0., {"2330.TW": 5}),
                     {"2330.TW": EngineOrder("SELL", 5, "stop")})
    inputs.stops["2330.TW"] = EngineStop(95., 100., .05)
    inputs = replace(inputs, sale_limits=OpeningSaleLimits("2024-01-05", (("2330.TW", cap),)))
    original = deepcopy(inputs)
    result = execute_opening_orders(inputs)
    order = result.orders[0]
    assert order["requested_quantity"] == 5
    assert order["filled_quantity"] == cap and order["expired_quantity"] == 5-cap
    assert result.portfolio.shares["2330.TW"] == 5-cap
    assert result.portfolio.cash == 0  # Positive sale cash remains unsettled.
    assert order["status"] == ("filled" if cap == 5 else "partial_expired" if cap else "expired")
    if cap < 5:
        assert result.pending["2330.TW"].reason == "stop" and "2330.TW" in result.stops
        assert order["outcome"] == ("tradability_limited" if cap else "not_tradable")
    else:
        assert not result.pending and not result.stops
    assert len(result.fills) == len(result.settlements) == int(cap > 0)
    assert inputs.portfolio == original.portfolio and inputs.pending == original.pending


@pytest.mark.parametrize("units", [(("2330.TW", True),), (("2330.TW", -1),),
                                   (("2330.TW", 1.0),), (("2330.TW", 2), ("2330.TW", 3))])
def test_caps_reject_noninteger_or_duplicate_quantities(units):
    with pytest.raises((ValueError, TypeError)):
        OpeningSaleLimits("2024-01-05", units)


@pytest.mark.parametrize("change", ["missing", "extra", "oversized", "session"])
def test_cap_contract_must_match_all_actual_post_event_positions(change):
    inputs = _inputs(PortfolioState(0., {"2330.TW": 5}),
                     {"2330.TW": EngineOrder("SELL", 5, "stop")})
    caps = {"2330.TW": 5}
    if change == "missing":
        caps.clear()
    elif change == "extra":
        caps["2317.TW"] = 0
    elif change == "oversized":
        caps["2330.TW"] = 6
    limits = OpeningSaleLimits("2024-01-08" if change == "session" else "2024-01-05",
                               tuple(sorted(caps.items())))
    with pytest.raises(ValueError):
        execute_opening_orders(replace(inputs, sale_limits=limits))
    assert inputs.portfolio.shares == {"2330.TW": 5}


@pytest.mark.parametrize("restart", [False, True])
def test_actual_shared_session_sells_unlocked_lot_then_retries_released_lot(monkeypatch, restart):
    data, research, config, runtime, _ = _start(monkeypatch)
    runtime.portfolio = PortfolioState(0., {"2330.TW": 3})
    runtime.stops = {"2330.TW": EngineStop(105., 110., .05)}
    first_day = str(data.close.index[31].date())
    release = str(data.close.index[32].date())
    lots = (SecurityLot("a-opening", "2330.TW", 1, first_day),
            SecurityLot("b-locked", "2330.TW", 2, release))
    account = RightsInventory(D(0), lots, RightsBook(D(0)), lots)
    for index, expected in ((30, 1), (31, 2)):
        opening = str(data.close.index[index+1].date())
        inputs = OddLotSessionInput(runtime, data, research, config, index, 29,
            prior_session_liquidity(data.volume), sale_limits=opening_sale_limits(account, opening))
        previous = capture_session_state(runtime, session=str(data.close.index[index].date()),
            origin_session=str(data.close.index[29].date()), session_offset=index-29,
            completed_index=index)
        result = run_odd_lot_session(inputs)
        checkpoint = capture_session_state(result.runtime, session=opening,
            origin_session=str(data.close.index[29].date()), session_offset=index+1-29,
            completed_index=index+1)
        evidence = {"risk_inputs": [{"close": data.raw_close.iloc[index].to_dict(),
            "observed_open": data.raw_open.iloc[index].to_dict(),
            "dividends": data.dividends.iloc[index+1].to_dict(),
            "splits": data.stock_splits.iloc[index+1].to_dict(), "terminal_symbols": ()}],
            "signals": result.signals, "fills": result.fills, "actions": result.actions}
        assert reconcile_risk_state(previous, checkpoint, evidence, asdict(research)) == ()
        sells = [row for row in result.fills if row["side"] == "SELL"]
        assert len(sells) == 1 and sells[0]["quantity"] == expected
        assert sells[0]["reason"] == "stop"
        account = _post(account, inputs, result)
        runtime = result.runtime
        assert account.cash == 0  # Neither sale has reached T+2 close yet.
        if index == 30:
            assert runtime.portfolio.shares["2330.TW"] == 2
            assert runtime.pending["2330.TW"].side == "SELL"
            assert len(account.lots) == 1 and account.lots[0].right_key == "b-locked"
        else:
            assert not account.lots and not runtime.stops and not runtime.pending
        if restart:
            account = decode_inventory(encode_inventory(account))
            runtime = restore_session_state(checkpoint, completed_index=index+1)
    assert [row["amount"] for row in runtime.settlements] == [100., 200.]
    assert [row["due_session_index"] for row in runtime.settlements] == [33, 34]


def test_legacy_opening_outputs_unchanged_when_explicit_caps_release_every_unit():
    inputs = _inputs(PortfolioState(0., {"2330.TW": 5}),
                     {"2330.TW": EngineOrder("SELL", 5, "model_exit")})
    unrestricted = execute_opening_orders(inputs)
    capped = execute_opening_orders(replace(inputs,
        sale_limits=OpeningSaleLimits("2024-01-05", (("2330.TW", 5),))))
    assert unrestricted == capped


def test_independent_session_link_rejects_real_fill_when_declared_sale_cap_is_lower(monkeypatch):
    data, research, config, runtime, _ = _start(monkeypatch)
    runtime.portfolio = PortfolioState(0., {"2330.TW": 3})
    runtime.stops = {"2330.TW": EngineStop(105., 110., .05)}
    inputs, result = _step(data, research, config, runtime, 30)
    assert result.fills[0]["quantity"] == 3
    capped = replace(inputs, sale_limits=OpeningSaleLimits(str(data.close.index[31].date()),
                                                         (("2330.TW", 1),)))
    with pytest.raises(ValueError, match="exceeds opening sale capacity"):
        reconcile_session_portfolio(capped, result)


def test_delivery_locked_at_signal_close_is_released_at_actual_next_opening(monkeypatch):
    data, research, config, runtime, account, day = funded(monkeypatch)
    opening = str(data.close.index[34].date())
    right = account.book.positions[0]
    terms = DeliveryTerms(right.key, right.leg.asset_key, "2330.TW", day, opening,
                          day+"T08:00:00+08:00", HASHES, D(0))
    account = post_rights_transition(account, deliver_claim(account.book, "deliver", terms, 1,
                                    as_of=day+"T16:02:00+08:00"))
    projected = project(data, runtime, account, day,
                        opening_stops=(StopState("2330.TW", 95., 100., .05),))
    assert projected.tradable_units == (("2330.TW", 0),)
    limits = opening_sale_limits(account, opening)
    assert limits.units == (("2330.TW", 1),)
    runtime = restore_session_state(projected.checkpoint, completed_index=33)
    inputs = OddLotSessionInput(runtime, data, research, config, 33, 29,
        prior_session_liquidity(data.volume), sale_limits=limits)
    result = run_odd_lot_session(inputs)
    account = _post(account, inputs, result)
    assert [(row["side"], row["quantity"]) for row in result.fills] == [("SELL", 1), ("BUY", 2)]
    assert account.cash == 90 and all(row.security_id != "2330.TW" for row in account.lots)


def test_checkpoint_reconstruction_rejects_recorded_sale_before_original_lot_release(monkeypatch):
    data, research, config, runtime, _ = _start(monkeypatch)
    runtime.portfolio = PortfolioState(0., {"2330.TW": 3})
    runtime.stops = {"2330.TW": EngineStop(105., 110., .05)}
    lots = (SecurityLot("opening", "2330.TW", 3, "2024-01-01"),)
    account = RightsInventory(D(0), lots, RightsBook(D(0)), lots)
    inputs, result = _step(data, research, config, runtime, 30)
    account = _post(account, inputs, result)
    assert not account.lots and account.postings[0][4] == 3
    before = encode_inventory(account)
    # Cash, commands and final inventory still reconcile, but the original lot
    # could not have funded the archived sale with this substituted release date.
    with pytest.raises(ValueError, match="command-time tradable lots"):
        replace(account, initial_lots=(replace(lots[0], tradable_session="2025-01-01"),))
    assert encode_inventory(account) == before
