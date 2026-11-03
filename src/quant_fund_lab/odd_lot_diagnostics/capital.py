"""Daily invested/cash/settlement ratios without double-subtracting reserved payables."""
from __future__ import annotations

import math

import pandas as pd


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def capital_utilization(curve: pd.DataFrame) -> pd.DataFrame:
    required = {"equity", "cash", "buy_payables", "sale_receivables", "sale_payables", "receivable_value"}
    columns = ["timestamp", "status", "reason", "equity", "holdings_value", "invested_fraction",
               "available_cash_fraction", "unsettled_payables_fraction", "unsettled_receivables_fraction"]
    rows = []
    for timestamp, row in curve.iterrows():
        output = dict.fromkeys(columns)
        output.update(timestamp=pd.Timestamp(timestamp).isoformat(), status="unavailable")
        if not required.issubset(curve.columns):
            output["reason"] = "missing capital source columns: " + ",".join(sorted(required - set(curve.columns)))
        else:
            values = {name: _number(row[name]) for name in required}
            nav = values["equity"]
            output["equity"] = nav if math.isfinite(nav) else None
            if not all(math.isfinite(value) for value in values.values()):
                output["reason"] = "nonfinite capital source value"
            elif nav <= 0:
                output["reason"] = "nonpositive NAV"
            else:
                holdings = nav - values["cash"] - values["sale_receivables"] - values["receivable_value"]
                output.update(status="available", reason="", holdings_value=holdings,
                    invested_fraction=holdings / nav, available_cash_fraction=values["cash"] / nav,
                    unsettled_payables_fraction=(values["buy_payables"] + values["sale_payables"]) / nav,
                    unsettled_receivables_fraction=(values["sale_receivables"] + values["receivable_value"]) / nav)
                computed = columns[4:]
                if not all(math.isfinite(output[name]) for name in computed):
                    output.update({name: None for name in computed})
                    output.update(status="unavailable", reason="nonfinite capital calculation")
        rows.append(output)
    return pd.DataFrame(rows, columns=columns)
