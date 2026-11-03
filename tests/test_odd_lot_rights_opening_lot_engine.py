"""Projected corporate-action lot caps reach the actual shared session engine."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_odd_lot_rights_session_flow import _start
from test_odd_lot_rights_transitions import HASHES

from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.engine_records import EngineStop
from quant_fund_lab.odd_lot_paper.sale_limits import OpeningSaleLimits
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput, run_odd_lot_session
from quant_fund_lab.odd_lot_rights.inventory import RightsInventory, SecurityLot
from quant_fund_lab.odd_lot_rights.inventory_codec import encode_inventory
from quant_fund_lab.odd_lot_rights.lot_events import LotRoundingPolicy, OpeningLotEvent
from quant_fund_lab.odd_lot_rights.lot_session import run_lot_projected_session
from quant_fund_lab.odd_lot_rights.opening_lots import project_opening_lots
from quant_fund_lab.odd_lot_rights.types import RightsBook


@pytest.mark.parametrize("ratio,capacity,owned", [(D(2), 4, 12), (D("0.5"), 1, 3)])
def test_split_before_opening_sells_only_transformed_unlocked_units(monkeypatch, ratio, capacity, owned):
    data, research, config, runtime, _ = _start(monkeypatch)
    opening = str(data.close.index[31].date())
    runtime.portfolio = PortfolioState(0., {"2330.TW": 6})
    runtime.stops = {"2330.TW": EngineStop(105., 110., .05)}
    lots = (SecurityLot("a-free", "2330.TW", 2, opening),
            SecurityLot("b-locked", "2330.TW", 4, "2025-01-01"))
    account = RightsInventory(D(0), lots, RightsBook(D(0)), lots)
    before = encode_inventory(account)
    splits = data.stock_splits.copy()
    splits.iloc[31, splits.columns.get_loc("2330.TW")] = float(ratio)
    raw_open, raw_close = data.raw_open.copy(), data.raw_close.copy()
    raw_open.loc[data.close.index[31]:, "2330.TW"] /= float(ratio)
    raw_close.loc[data.close.index[31]:, "2330.TW"] /= float(ratio)
    data = replace(data, stock_splits=splits, raw_open=raw_open, raw_close=raw_close)
    event = OpeningLotEvent("d"*64, "2330.TW", opening, "split", ratio,
                            opening+"T08:00:00+08:00", HASHES)
    projected = project_opening_lots(account, (event,), LotRoundingPolicy(1, "latest_contributor_release"),
                                     session=opening, as_of=opening+"T09:00:00+08:00")
    assert projected.shares == (("2330.TW", owned),)
    inputs = OddLotSessionInput(runtime, data, research, config, 30, 29,
        prior_session_liquidity(data.volume), sale_limits=projected.sale_limits)
    result = run_odd_lot_session(inputs)
    joined = run_lot_projected_session(account, (event,), LotRoundingPolicy(1, "latest_contributor_release"),
                                      inputs, as_of=opening+"T09:00:00+08:00")
    assert joined.projection == projected and joined.result.nav == result.nav
    assert joined.result.fills == result.fills
    split = next(row for row in result.actions if row["action"] == "stock_split")
    assert split["quantity_before"] == 6 and split["quantity_after"] == owned
    sells = [row for row in result.fills if row["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["quantity"] == capacity
    assert result.runtime.portfolio.shares["2330.TW"] == owned-capacity
    assert result.runtime.portfolio.cash == 0
    assert result.runtime.settlements[-1]["amount"] == 200
    assert result.runtime.pending["2330.TW"].side == "SELL"
    assert result.runtime.stops["2330.TW"].stop == 105/float(ratio)
    assert encode_inventory(account) == before and runtime.portfolio.shares["2330.TW"] == 6
    with pytest.raises(ValueError, match="actual session source ratio"):
        run_lot_projected_session(account, (replace(event, ratio=ratio+3),),
            LotRoundingPolicy(1, "latest_contributor_release"), replace(inputs, sale_limits=None),
            as_of=opening+"T09:00:00+08:00")
    with pytest.raises(ValueError, match="actual session source ratio"):
        run_lot_projected_session(account, (), LotRoundingPolicy(1, "latest_contributor_release"),
                                  replace(inputs, sale_limits=None), as_of=opening+"T09:00:00+08:00")


def test_terminal_before_opening_consumes_locked_units_as_corporate_action(monkeypatch):
    data, research, config, runtime, _ = _start(monkeypatch)
    opening = str(data.close.index[31].date())
    runtime.portfolio = PortfolioState(0., {"2330.TW": 6})
    runtime.stops = {"2330.TW": EngineStop(105., 110., .05)}
    lots = (SecurityLot("locked", "2330.TW", 6, "2025-01-01"),)
    account = RightsInventory(D(0), lots, RightsBook(D(0)), lots)
    terminal = data.terminal_returns.copy()
    terminal.loc[data.close.index[31], "2330.TW"] = -.5
    data = replace(data, terminal_returns=terminal)
    event = OpeningLotEvent("e"*64, "2330.TW", opening, "terminal", None,
                            opening+"T08:00:00+08:00", HASHES)
    projected = project_opening_lots(account, (event,), LotRoundingPolicy(1, "latest_contributor_release"),
                                     session=opening, as_of=opening+"T09:00:00+08:00")
    assert not projected.sale_limits.units and not projected.lots
    inputs = OddLotSessionInput(runtime, data, research, config, 30, 29,
        prior_session_liquidity(data.volume), sale_limits=projected.sale_limits)
    result = run_odd_lot_session(inputs)
    joined = run_lot_projected_session(account, (event,), LotRoundingPolicy(1, "latest_contributor_release"),
                                      inputs, as_of=opening+"T09:00:00+08:00")
    assert joined.result.nav == result.nav and joined.projection == projected
    with pytest.raises(ValueError, match="do not match actual opening"):
        run_lot_projected_session(account, (), LotRoundingPolicy(1, "latest_contributor_release"),
                                  replace(inputs, sale_limits=None), as_of=opening+"T09:00:00+08:00")
    assert len(result.terminal_events) == 1 and result.terminal_events[0]["quantity"] == 6
    assert result.runtime.portfolio.cash == 300 and not result.runtime.portfolio.shares.get("2330.TW", 0)
    assert not result.fills and not result.runtime.settlements
    assert "2330.TW" not in result.runtime.stops and "2330.TW" in result.runtime.terminated


@pytest.mark.parametrize("change", ["cash_anchor", "cap", "ambiguous_rounding"])
def test_bad_anchor_cap_or_rounding_is_rejected_before_engine_execution(monkeypatch, change):
    from quant_fund_lab.odd_lot_rights import lot_session

    data, research, config, runtime, _ = _start(monkeypatch)
    opening = str(data.close.index[31].date())
    units = 3 if change == "ambiguous_rounding" else 6
    ratio = D("0.3333333333333") if change == "ambiguous_rounding" else D(2)
    runtime.portfolio = PortfolioState(1. if change == "cash_anchor" else 0., {"2330.TW": units})
    lots = (SecurityLot("opening", "2330.TW", units, opening),)
    account = RightsInventory(D(0), lots, RightsBook(D(0)), lots)
    splits = data.stock_splits.copy()
    splits.loc[data.close.index[31], "2330.TW"] = float(ratio)
    data = replace(data, stock_splits=splits)
    inputs = OddLotSessionInput(runtime, data, research, config, 30, 29,
                               prior_session_liquidity(data.volume))
    if change == "cap":
        inputs = replace(inputs, sale_limits=OpeningSaleLimits(opening, (("2330.TW", 1),)))
    event = OpeningLotEvent("d"*64, "2330.TW", opening, "split", ratio,
                            opening+"T08:00:00+08:00", HASHES)

    def forbidden(_):
        pytest.fail("bad lot plan reached session execution")

    monkeypatch.setattr(lot_session, "run_odd_lot_session", forbidden)
    expected = {"cash_anchor": "anchor differs", "cap": "opening limits differ",
                "ambiguous_rounding": "rounding is ambiguous"}[change]
    before = encode_inventory(account)
    with pytest.raises(ValueError, match=expected):
        run_lot_projected_session(account, (event,), LotRoundingPolicy(1, "latest_contributor_release"),
                                  inputs, as_of=opening+"T09:00:00+08:00")
    assert encode_inventory(account) == before
