"""Reconstruct complete position episodes from simulated fills and corporate actions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class _Episode:
    symbol: str
    entry: pd.Timestamp
    quantity: int = 0
    purchases: float = 0.0
    proceeds: float = 0.0
    planned_risk: float = 0.0
    exit: pd.Timestamp | None = None
    pending: list[tuple[pd.Timestamp, float]] = field(default_factory=list)


def position_episodes(
    fills: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    terminal_events: pd.DataFrame,
    final_prices: pd.Series,
) -> pd.DataFrame:
    """Return one row per zero-to-zero position, including unsettled entitlements.

    Fill prices already incorporate modeled slippage. Fees are subtracted once;
    cash interest belongs to the account, not to an individual security episode.
    """
    events: list[tuple[pd.Timestamp, int, int, dict]] = []
    for priority, frame in ((3, fills), (2, terminal_events)):
        if not frame.empty:
            events.extend(
                (pd.Timestamp(row["timestamp"]), priority, i, row)
                for i, row in enumerate(frame.to_dict("records"))
            )
    if not corporate_actions.empty:
        for i, row in enumerate(corporate_actions.to_dict("records")):
            action = row["action"]
            if action not in {"cash_in_lieu_settlement", "stock_split", "cash_dividend"}:
                raise ValueError(f"unsupported corporate action: {action}")
            priority = 0 if action == "cash_in_lieu_settlement" else 1
            events.append((pd.Timestamp(row["timestamp"]), priority, i, row))
    events.sort(key=lambda event: (event[0], event[1], event[2]))

    episodes: list[_Episode] = []
    active: dict[str, _Episode] = {}
    for timestamp, priority, _, row in events:
        symbol = str(row["symbol"])
        if priority == 0:
            quantity = float(row["fractional_quantity"])
            matches = [
                (episode, index)
                for episode in episodes if episode.symbol == symbol
                for index, (due, fraction) in enumerate(episode.pending)
                if due == timestamp and math.isclose(fraction, quantity, abs_tol=1e-10, rel_tol=0)
            ]
            if not matches:
                raise ValueError(f"unmatched cash-in-lieu settlement: {symbol} {timestamp}")
            episode, index = matches[0]
            episode.pending.pop(index)
            episode.proceeds += float(row["cash_value"])
        elif priority == 1:
            episode = active.get(symbol)
            if episode is None:
                raise ValueError(f"corporate action without a position: {symbol} {timestamp}")
            if row["action"] == "stock_split":
                if int(row["quantity_before"]) != episode.quantity:
                    raise ValueError(f"split quantity mismatch: {symbol} {timestamp}")
                episode.quantity = int(row["quantity_after"])
                episode.proceeds += float(row["cash_value"])
                if row.get("cash_in_lieu_price_source") == "pending_settlement":
                    episode.pending.append((
                        pd.Timestamp(row["cash_in_lieu_settlement_date"]),
                        float(row["fractional_quantity"]),
                    ))
                if episode.quantity == 0:
                    episode.exit = timestamp
                    del active[symbol]
            else:
                episode.proceeds += float(row["cash_value"])
        elif priority == 2:
            episode = active.get(symbol)
            if episode is None or episode.quantity != int(row["quantity"]):
                raise ValueError(f"terminal event quantity mismatch: {symbol} {timestamp}")
            episode.proceeds += float(row["proceeds"])
            episode.quantity = 0
            episode.exit = timestamp
            del active[symbol]
        else:
            side, quantity = str(row["side"]), int(row["quantity"])
            if quantity <= 0 or side not in {"BUY", "SELL"}:
                raise ValueError("invalid fill")
            if side == "BUY":
                episode = active.get(symbol)
                if episode is None:
                    episode = _Episode(symbol=symbol, entry=timestamp)
                    episodes.append(episode)
                    active[symbol] = episode
                episode.quantity += quantity
                episode.purchases += float(row["gross_value"]) + float(row["fees"])
                risk = row.get("planned_risk", 0.0)
                if pd.notna(risk):
                    episode.planned_risk += float(risk)
            else:
                episode = active.get(symbol)
                if episode is None or quantity > episode.quantity:
                    raise ValueError(f"sell exceeds position: {symbol} {timestamp}")
                episode.quantity -= quantity
                episode.proceeds += float(row["gross_value"]) - float(row["fees"])
                if episode.quantity == 0:
                    episode.exit = timestamp
                    del active[symbol]

    rows = []
    for episode in episodes:
        is_closed = episode.quantity == 0 and not episode.pending
        mark = 0.0
        if not is_closed:
            price = float(final_prices.get(episode.symbol, float("nan")))
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"missing final price for open episode: {episode.symbol}")
            mark = (episode.quantity + sum(item[1] for item in episode.pending)) * price
        pnl = episode.proceeds + mark - episode.purchases
        rows.append({
            "symbol": episode.symbol,
            "entry": episode.entry,
            "exit": episode.exit,
            "status": "closed" if is_closed else "open",
            "quantity": episode.quantity,
            "pending_receivables": len(episode.pending),
            "purchases": episode.purchases,
            "proceeds": episode.proceeds,
            "mark_value": mark,
            "pnl": pnl,
            "return_on_purchases": pnl / episode.purchases if episode.purchases else np.nan,
            "planned_risk": episode.planned_risk,
            "risk_multiple": pnl / episode.planned_risk if episode.planned_risk > 0 else np.nan,
        })
    return pd.DataFrame(rows, columns=[
        "symbol", "entry", "exit", "status", "quantity", "pending_receivables",
        "purchases", "proceeds", "mark_value", "pnl", "return_on_purchases",
        "planned_risk", "risk_multiple",
    ])


def summarize_episodes(episodes: pd.DataFrame) -> dict[str, float | int | None]:
    closed = episodes.loc[episodes["status"] == "closed", "pnl"].astype(float)
    opened = episodes.loc[episodes["status"] == "open", "pnl"].astype(float)
    wins = closed[closed > 1e-8]
    losses = closed[closed < -1e-8]
    average_win = float(wins.mean()) if len(wins) else None
    average_loss = float(-losses.mean()) if len(losses) else None
    return {
        "closed_count": len(closed),
        "open_count": len(opened),
        "wins": len(wins),
        "losses": len(losses),
        "flat": int(len(closed) - len(wins) - len(losses)),
        "average_win": average_win,
        "average_loss": average_loss,
        "payoff_ratio": average_win / average_loss if average_win is not None and average_loss else None,
        "win_rate": float(len(wins) / len(closed)) if len(closed) else None,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and len(wins) else None,
        "expectancy": float(closed.mean()) if len(closed) else None,
        "closed_pnl": float(closed.sum()),
        "open_pnl": float(opened.sum()),
        "sample_sufficient": len(closed) >= 30,
    }
