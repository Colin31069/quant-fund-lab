"""Explicit split rounding preserves restrictions and discloses exact fractions."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_transitions import HASHES

from quant_fund_lab.odd_lot_rights.inventory import RightsInventory, SecurityLot
from quant_fund_lab.odd_lot_rights.inventory_codec import encode_inventory
from quant_fund_lab.odd_lot_rights.lot_events import LotRoundingPolicy, OpeningLotEvent
from quant_fund_lab.odd_lot_rights.opening_lots import project_opening_lots
from quant_fund_lab.odd_lot_rights.types import RightsBook

DAY = "2024-01-03"
NOW = DAY+"T09:00:00+08:00"
POLICY = LotRoundingPolicy(1, "latest_contributor_release")


def account(free=1, locked=3):
    lots = (SecurityLot("a-free", "2330.TW", free, DAY),
            SecurityLot("b-locked", "2330.TW", locked, "2024-01-05"))
    return RightsInventory(D(100), lots, RightsBook(D(100)), lots)


def event(ratio="0.5", **changes):
    values = {"event_id": "d"*64, "security_id": "2330.TW", "session": DAY, "kind": "split",
              "ratio": D(ratio) if ratio is not None else None,
              "available_at": DAY+"T08:00:00+08:00", "evidence_sha256": HASHES}
    return OpeningLotEvent(**(values | changes))


def project(current, events):
    return project_opening_lots(current, events, POLICY, session=DAY, as_of=NOW)


def test_split_preserves_each_lots_release_and_never_credits_cash():
    current = account()
    before = encode_inventory(current)
    result = project(current, (event("4"),))
    assert result.shares == (("2330.TW", 16),)
    assert result.sale_limits.units == (("2330.TW", 4),)
    assert [(lot.units, lot.tradable_session) for lot in result.lots] == [(4, DAY), (12, "2024-01-05")]
    assert result.fractions == () and result.fractional_units == (("2330.TW", D(0)),)
    assert encode_inventory(current) == before


def test_reverse_split_pools_residual_whole_unit_under_latest_contributors_lock():
    current = account()
    result = project(current, (event(),))
    assert result.shares == (("2330.TW", 2),)
    assert result.sale_limits.units == (("2330.TW", 0),)
    assert [(lot.right_key, lot.units, lot.tradable_session) for lot in result.lots] == [
        ("b-locked", 1, "2024-01-05"), ("split-residual:"+"d"*64, 1, "2024-01-05")]
    assert [(row.right_key, row.fraction) for row in result.fractions] == [("a-free", D("0.5")), ("b-locked", D("0.5"))]
    assert result.fractional_units == (("2330.TW", D(0)),)
    assert current.cash == 100


def test_unconverted_fraction_is_exact_disclosure_and_not_cash_or_an_owned_share():
    result = project(account(1, 2), (event(),))
    assert result.shares == (("2330.TW", 1),)
    assert result.sale_limits.units == (("2330.TW", 0),)
    assert result.fractional_units == (("2330.TW", D("0.5")),)
    assert sum(row.fraction for row in result.fractions) == D("0.5")


def test_same_security_split_then_terminal_consumes_locked_whole_shares_without_a_sale():
    current = account()
    terminal = event(kind="terminal", ratio=None, event_id="e"*64)
    result = project(current, (event(), terminal))
    assert not result.lots and not result.shares and not result.sale_limits.units
    assert current.cash == 100 and len(current.lots) == 2


def test_empty_events_preserve_lots_and_no_holdings_can_have_events_without_minting():
    current = account()
    result = project(current, ())
    assert result.lots == current.lots and result.sale_limits.units == (("2330.TW", 1),)
    empty = RightsInventory(D(0), (), RightsBook(D(0)), ())
    assert project(empty, (event(),)).lots == ()


@pytest.mark.parametrize("change", ["future", "wrong_day", "duplicate", "reversed", "same_id"])
def test_unknown_ambiguous_or_out_of_order_events_preserve_original_inventory(change):
    current = account()
    before = encode_inventory(current)
    split = event()
    terminal = event(kind="terminal", ratio=None, event_id="e"*64)
    cases = {"future": (replace(split, available_at=DAY+"T09:00:01+08:00"),),
             "wrong_day": (replace(split, session="2024-01-04"),),
             "duplicate": (split, split), "reversed": (terminal, split),
             "same_id": (split, replace(terminal, event_id=split.event_id))}
    with pytest.raises(ValueError):
        project(current, cases[change])
    assert encode_inventory(current) == before


@pytest.mark.parametrize("changes", [{"ratio": D(0)}, {"ratio": D(-1)}, {"ratio": D(1)},
    {"ratio": float("inf")}, {"kind": "guess_receipt_exchange"},
    {"kind": "terminal"}, {"event_id": "not-a-sha"}])
def test_event_contract_rejects_unknown_or_invalid_transformations(changes):
    with pytest.raises((TypeError, ValueError)):
        event(**changes)


def test_policy_and_source_identity_are_explicit_and_deterministic():
    current = account()
    first = project(current, (event(),))
    assert first == project(current, (event(),))
    assert first.source_sha256 != project(current, (event(evidence_sha256=("c"*64,)),)).source_sha256
    with pytest.raises(ValueError, match="unsupported lot rounding"):
        LotRoundingPolicy(1, "unlock_all_rounding_residuals")
    with pytest.raises(ValueError, match="processing date"):
        project_opening_lots(current, (), POLICY, session=DAY, as_of="2024-01-02T09:00:00+08:00")
