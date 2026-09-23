from __future__ import annotations

import math

import pandas as pd

_REQUIRED_DIVIDEND_COLUMNS = {
    "action",
    "cash_value",
    "gross_cash_value",
    "withholding_tax",
    "local_currency",
}


def _dividend_rows(corporate_actions: pd.DataFrame) -> pd.DataFrame:
    if corporate_actions.empty:
        return corporate_actions.copy()
    missing = sorted(_REQUIRED_DIVIDEND_COLUMNS - set(corporate_actions.columns))
    if missing:
        raise ValueError(f"corporate actions missing dividend tax columns: {missing}")
    rows = corporate_actions[corporate_actions["action"].eq("cash_dividend")].copy()
    if rows.empty:
        return rows
    for column in ("cash_value", "gross_cash_value", "withholding_tax"):
        rows[column] = pd.to_numeric(rows[column], errors="raise")
        if rows[column].isna().any() or (~rows[column].map(math.isfinite)).any():
            raise ValueError(f"invalid dividend cashflow values in {column}")
        if (rows[column] < -1e-12).any():
            raise ValueError(f"negative dividend cashflow values in {column}")
    imbalance = (
        rows["gross_cash_value"] - rows["withholding_tax"] - rows["cash_value"]
    ).abs()
    tolerance = 1e-8 + rows["gross_cash_value"].abs() * 1e-10
    if (imbalance > tolerance).any():
        raise ValueError("dividend cashflow does not reconcile gross = withholding + net")
    rows["local_currency"] = rows["local_currency"].fillna("").astype(str).str.upper()
    return rows


def summarize_dividend_tax(corporate_actions: pd.DataFrame) -> dict[str, float | int]:
    rows = _dividend_rows(corporate_actions)
    if rows.empty:
        return {
            "dividend_event_count": 0,
            "gross_dividend_cash": 0.0,
            "withholding_tax": 0.0,
            "net_dividend_cash": 0.0,
            "effective_withholding_rate": 0.0,
        }
    gross = float(rows["gross_cash_value"].sum())
    withholding = float(rows["withholding_tax"].sum())
    net = float(rows["cash_value"].sum())
    return {
        "dividend_event_count": len(rows),
        "gross_dividend_cash": gross,
        "withholding_tax": withholding,
        "net_dividend_cash": net,
        "effective_withholding_rate": 0.0 if gross <= 0.0 else withholding / gross,
    }


def dividend_tax_by_currency(corporate_actions: pd.DataFrame) -> pd.DataFrame:
    rows = _dividend_rows(corporate_actions)
    columns = [
        "dividend_event_count",
        "gross_dividend_cash",
        "withholding_tax",
        "net_dividend_cash",
        "effective_withholding_rate",
    ]
    if rows.empty:
        return pd.DataFrame(columns=columns).rename_axis("local_currency")
    grouped = rows.groupby("local_currency", dropna=False).agg(
        dividend_event_count=("action", "size"),
        gross_dividend_cash=("gross_cash_value", "sum"),
        withholding_tax=("withholding_tax", "sum"),
        net_dividend_cash=("cash_value", "sum"),
    )
    grouped["effective_withholding_rate"] = grouped["withholding_tax"].div(
        grouped["gross_dividend_cash"].where(grouped["gross_dividend_cash"] > 0.0)
    ).fillna(0.0)
    return grouped[columns]
