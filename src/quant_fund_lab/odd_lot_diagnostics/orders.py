"""Group emitted unfilled orders and identify signals without a recorded outcome."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .types import RiskDiagnosticInputs


def unfilled_order_summary(inputs: RiskDiagnosticInputs) -> tuple[pd.DataFrame, tuple[str, ...]]:
    columns = ["side", "status", "outcome", "order_count", "requested_quantity",
               "filled_quantity", "expired_quantity"]
    required = {"timestamp", "symbol", "side", "status", "outcome", "requested_quantity",
                "filled_quantity", "expired_quantity"}
    rows, issues = [], []
    orders = inputs.orders
    valid_orders = orders.empty or required.issubset(orders.columns)
    if not valid_orders:
        issues.append("missing order source columns: " + ",".join(sorted(required - set(orders.columns))))
    elif not orders.empty:
        quantity = orders[["requested_quantity", "filled_quantity", "expired_quantity"]].apply(pd.to_numeric, errors="coerce")
        if (not np.isfinite(quantity.to_numpy()).all() or (quantity < 0).any().any()
                or (quantity % 1 != 0).any().any()
                or not quantity.requested_quantity.eq(quantity.filled_quantity + quantity.expired_quantity).all()):
            issues.append("invalid order quantity accounting")
            valid_orders = False
        else:
            orders = orders.assign(**{name: quantity[name] for name in quantity.columns})
            unfilled = orders.loc[orders["expired_quantity"].gt(0)]
            for (side, status, outcome), group in unfilled.groupby(["side", "status", "outcome"], dropna=False, sort=True):
                rows.append({"side": side, "status": status, "outcome": outcome, "order_count": len(group),
                    **{name: int(group[name].sum()) for name in columns[-3:]}})
    signals = inputs.signals
    if not signals.empty:
        if not {"timestamp", "symbol", "reason"}.issubset(signals.columns):
            issues.append("missing signal source columns")
        elif valid_orders:
            known = set() if orders.empty else {
                (pd.Timestamp(row.timestamp), str(row.symbol), str(row.side)) for row in orders.itertuples()
            }
            dates = pd.DatetimeIndex(inputs.equity_curve.index)
            if (dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing
                    or not pd.to_datetime(signals.timestamp, errors="coerce").isin(dates).all()):
                issues.append("entry signal or simulation session sequence is invalid")
                return pd.DataFrame(rows, columns=columns), tuple(issues)
            counts = {"unavailable_entry_signal_without_order": 0, "pending_entry_signal_at_end": 0}
            for signal in signals.loc[signals["reason"].eq("entry")].itertuples():
                position = int(dates.searchsorted(pd.Timestamp(signal.timestamp), side="right"))
                if position >= len(dates):
                    counts["pending_entry_signal_at_end"] += 1
                elif (dates[position], str(signal.symbol), "BUY") not in known:
                    counts["unavailable_entry_signal_without_order"] += 1
            for outcome, count in counts.items():
                if count:
                    rows.append({"side": "BUY", "status": "unavailable" if outcome.startswith("unavailable") else "pending",
                                 "outcome": outcome, "order_count": count,
                                 "requested_quantity": None, "filled_quantity": None, "expired_quantity": None})
                    if outcome.startswith("unavailable"):
                        issues.append(outcome)
    return pd.DataFrame(rows, columns=columns), tuple(issues)
