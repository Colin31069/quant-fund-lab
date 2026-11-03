"""Validate corporate lot terms against actual session inputs before execution."""
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from math import floor

import pandas as pd

from ..odd_lot_paper.session import OddLotSessionInput, OddLotSessionResult, run_odd_lot_session
from .inventory import RightsInventory
from .lot_events import LotRoundingPolicy, OpeningLotEvent, OpeningLotProjection
from .opening_lots import project_opening_lots


@dataclass(frozen=True)
class ProjectedLotSession:
    """Execution and its pre-opening lot plan, still awaiting atomic outer posting."""

    projection: OpeningLotProjection
    result: OddLotSessionResult


def run_lot_projected_session(account: RightsInventory, events: tuple[OpeningLotEvent, ...],
                              policy: LotRoundingPolicy, inputs: OddLotSessionInput, *,
                              as_of: str) -> ProjectedLotSession:
    """Bind declared lot events to actual engine inputs, then consume their caps.

    This pure copied-state execution does not post the old rights inventory.
    The outer versioned workflow must persist corporate transformations, fills,
    cash and rights together; old session posting cannot represent these lots.
    """
    i = inputs.signal_index
    if type(i) is not int or not 0 <= i < len(inputs.data.close.index)-1:
        raise ValueError("lot session requires a valid next opening index")
    date = inputs.data.close.index[i+1]
    session = str(date.date())
    projection = project_opening_lots(account, events, policy, session=session, as_of=as_of)
    owned = {}
    for lot in account.lots:
        owned[lot.security_id] = owned.get(lot.security_id, 0)+lot.units
    actual_before = {key: value for key, value in inputs.runtime.portfolio.shares.items() if value}
    if owned != actual_before or Decimal(str(inputs.runtime.portfolio.cash)) != account.cash:
        raise ValueError("lot session engine anchor differs from authoritative inventory")
    declared = {(row.kind, row.security_id): row for row in events}
    expected = set()
    after = dict(owned)
    for symbol in sorted(set(owned) | {row.security_id for row in events}):
        if symbol not in inputs.data.symbols:
            raise ValueError("lot event security is absent from actual session data")
        raw_ratio = float(inputs.data.stock_splits.at[date, symbol])
        if raw_ratio not in (0, 1):
            key = "split", symbol
            expected.add(key)
            if key not in declared or declared[key].ratio != Decimal(str(raw_ratio)):
                raise ValueError("declared split differs from actual session source ratio")
            units = owned.get(symbol, 0)
            with localcontext() as context:
                context.prec = 80
                exact = int(Decimal(units)*declared[key].ratio)
            if exact != floor(units*raw_ratio+1e-12):
                raise ValueError("split rounding is ambiguous across exact and engine quantities")
            after[symbol] = exact
        if pd.notna(inputs.data.terminal_returns.at[date, symbol]):
            expected.add(("terminal", symbol))
            after.pop(symbol, None)
    if set(declared) != expected:
        raise ValueError("declared lot events do not match actual opening corporate actions")
    after = {key: value for key, value in after.items() if value}
    if tuple(sorted(after.items())) != projection.shares:
        raise ValueError("projected lot ownership differs from actual post-event quantity")
    if inputs.sale_limits is not None and inputs.sale_limits != projection.sale_limits:
        raise ValueError("provided opening limits differ from the transformed lot plan")
    result = run_odd_lot_session(replace(inputs, sale_limits=projection.sale_limits))
    # The core independently reconciles its actions, fills and close. Verify
    # that its actual pre-trade event result also matches this explicit lot plan.
    observed = dict(owned)
    for row in result.actions:
        if row["action"] == "stock_split":
            observed[row["symbol"]] = row["quantity_after"]
    for row in result.terminal_events:
        observed.pop(row["symbol"], None)
    if {key: value for key, value in observed.items() if value} != after:
        raise ValueError("executed corporate actions differ from the opening lot plan")
    return ProjectedLotSession(projection, result)
