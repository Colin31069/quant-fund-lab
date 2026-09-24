from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

_REQUIRED_COLUMNS = {
    "timestamp",
    "symbol",
    "action",
    "cash_value",
    "cash_in_lieu_price_source",
    "fractional_quantity",
    "cash_in_lieu_settlement_date",
}


def _fractional_events(corporate_actions: pd.DataFrame) -> pd.DataFrame:
    if corporate_actions.empty:
        return corporate_actions.copy()
    missing = sorted(_REQUIRED_COLUMNS - set(corporate_actions.columns))
    if missing:
        raise ValueError(f"corporate actions missing cash-in-lieu columns: {missing}")

    rows = corporate_actions[
        corporate_actions["action"].isin(["stock_split", "cash_in_lieu_settlement"])
    ].copy()
    if rows.empty:
        return rows

    rows["fractional_quantity"] = pd.to_numeric(
        rows["fractional_quantity"], errors="raise"
    )
    rows["cash_value"] = pd.to_numeric(rows["cash_value"], errors="raise")
    if rows[["fractional_quantity", "cash_value"]].isna().any().any():
        raise ValueError("cash-in-lieu event values cannot be missing")
    if (
        ~np.isfinite(rows["fractional_quantity"])
        | ~np.isfinite(rows["cash_value"])
        | (rows["fractional_quantity"] < -1e-12)
    ).any():
        raise ValueError("invalid cash-in-lieu event values")

    rows["timestamp"] = pd.to_datetime(rows["timestamp"], errors="coerce")
    if rows["timestamp"].isna().any():
        raise ValueError("cash-in-lieu event timestamp is required")
    rows["cash_in_lieu_price_source"] = (
        rows["cash_in_lieu_price_source"].fillna("").astype(str)
    )
    rows["symbol"] = rows["symbol"].fillna("").astype(str)
    return rows


def summarize_cash_in_lieu(corporate_actions: pd.DataFrame) -> dict[str, float | int]:
    rows = _fractional_events(corporate_actions)
    empty = {
        "fractional_split_event_count": 0,
        "immediate_settlement_count": 0,
        "delayed_receivable_count": 0,
        "delayed_settlement_count": 0,
        "provider_settlement_count": 0,
        "raw_open_fallback_count": 0,
        "unresolved_receivable_count": 0,
        "cash_in_lieu_cash": 0.0,
        "average_settlement_lag_days": 0.0,
        "max_settlement_lag_days": 0.0,
    }
    if rows.empty:
        return empty

    split_rows = rows[
        rows["action"].eq("stock_split") & (rows["fractional_quantity"] > 1e-12)
    ].copy()
    settlement_rows = rows[rows["action"].eq("cash_in_lieu_settlement")].copy()

    pending = split_rows["cash_in_lieu_price_source"].eq("pending_settlement")
    immediate = split_rows["cash_in_lieu_price_source"].isin(
        ["provider_settlement", "raw_open_fallback"]
    )
    unexpected = split_rows[
        ~(
            pending
            | immediate
        )
    ]
    if not unexpected.empty:
        raise ValueError("fractional split event has unsupported settlement source")

    lag_days: list[float] = []
    pending_keys: Counter[tuple[str, pd.Timestamp]] = Counter()
    pending_quantities: dict[tuple[str, pd.Timestamp], list[float]] = {}
    for row in split_rows.itertuples(index=False):
        settlement_text = str(row.cash_in_lieu_settlement_date).strip()
        if not settlement_text:
            raise ValueError("fractional split event is missing settlement date")
        settlement_date = pd.to_datetime(settlement_text, errors="coerce")
        if pd.isna(settlement_date):
            raise ValueError("fractional split event has invalid settlement date")
        settlement_date = pd.Timestamp(settlement_date)
        if settlement_date < pd.Timestamp(row.timestamp):
            raise ValueError("cash-in-lieu settlement date precedes split event")
        lag_days.append(
            float((settlement_date.normalize() - pd.Timestamp(row.timestamp).normalize()).days)
        )
        if row.cash_in_lieu_price_source == "pending_settlement":
            key = (str(row.symbol), settlement_date)
            pending_keys[key] += 1
            pending_quantities.setdefault(key, []).append(float(row.fractional_quantity))
            if not np.isclose(float(row.cash_value), 0.0, rtol=0.0, atol=1e-10):
                raise ValueError("pending cash-in-lieu receivable cannot credit cash")

    settled_keys: Counter[tuple[str, pd.Timestamp]] = Counter(
        (str(row.symbol), pd.Timestamp(row.timestamp))
        for row in settlement_rows.itertuples(index=False)
    )
    orphan_settlements = settled_keys - pending_keys
    if orphan_settlements:
        raise ValueError("cash-in-lieu settlement event has no pending receivable")
    for row in settlement_rows.itertuples(index=False):
        quantity = float(row.fractional_quantity)
        if quantity <= 1e-12:
            raise ValueError("cash-in-lieu settlement must have positive fractional quantity")
        key = (str(row.symbol), pd.Timestamp(row.timestamp))
        available = pending_quantities[key]
        match = next(
            (
                index
                for index, pending_quantity in enumerate(available)
                if np.isclose(pending_quantity, quantity, rtol=0.0, atol=1e-10)
            ),
            None,
        )
        if match is None:
            raise ValueError("cash-in-lieu settlement quantity does not match pending receivable")
        available.pop(match)
    unresolved = pending_keys - settled_keys

    cash_rows = pd.concat(
        [split_rows[immediate], settlement_rows],
        ignore_index=True,
    )
    provider_count = int(
        cash_rows["cash_in_lieu_price_source"].eq("provider_settlement").sum()
    )
    fallback_count = int(
        cash_rows["cash_in_lieu_price_source"].eq("raw_open_fallback").sum()
    )
    unsupported_cash_source = cash_rows[
        ~cash_rows["cash_in_lieu_price_source"].isin(
            ["provider_settlement", "raw_open_fallback"]
        )
    ]
    if not unsupported_cash_source.empty:
        raise ValueError("cash-in-lieu cash event has unsupported settlement source")

    result = dict(empty)
    result.update(
        {
            "fractional_split_event_count": len(split_rows),
            "immediate_settlement_count": int(immediate.sum()),
            "delayed_receivable_count": int(pending.sum()),
            "delayed_settlement_count": len(settlement_rows),
            "provider_settlement_count": provider_count,
            "raw_open_fallback_count": fallback_count,
            "unresolved_receivable_count": int(sum(unresolved.values())),
            "cash_in_lieu_cash": float(cash_rows["cash_value"].sum()),
            "average_settlement_lag_days": (
                0.0 if not lag_days else float(np.mean(lag_days))
            ),
            "max_settlement_lag_days": (
                0.0 if not lag_days else float(np.max(lag_days))
            ),
        }
    )
    return result


def cash_in_lieu_by_source(corporate_actions: pd.DataFrame) -> pd.DataFrame:
    # Standalone source breakdown must reject the same malformed events as the summary.
    summarize_cash_in_lieu(corporate_actions)
    rows = _fractional_events(corporate_actions)
    columns = ["settlement_event_count", "cash_value", "fractional_quantity"]
    if rows.empty:
        return pd.DataFrame(columns=columns).rename_axis("settlement_source")

    split_rows = rows[
        rows["action"].eq("stock_split")
        & (rows["fractional_quantity"] > 1e-12)
        & rows["cash_in_lieu_price_source"].isin(
            ["provider_settlement", "raw_open_fallback"]
        )
    ]
    settlement_rows = rows[rows["action"].eq("cash_in_lieu_settlement")]
    settled = pd.concat([split_rows, settlement_rows], ignore_index=True)
    if settled.empty:
        return pd.DataFrame(columns=columns).rename_axis("settlement_source")

    grouped = settled.groupby("cash_in_lieu_price_source").agg(
        settlement_event_count=("action", "size"),
        cash_value=("cash_value", "sum"),
        fractional_quantity=("fractional_quantity", "sum"),
    )
    grouped.index.name = "settlement_source"
    return grouped[columns]
