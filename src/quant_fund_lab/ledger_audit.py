"""Read-only independent accounting checks over persistent SQLite paper ledgers."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerAuditReport:
    nav_sessions: int
    fills: int
    position_marks: int
    cash_credits: int
    issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


def _matches(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-6)


def audit_paper_ledger(connection: sqlite3.Connection) -> LedgerAuditReport:
    """Verify persisted accounting independently of replay's in-memory state.

    Only reads the SQLite connection. The snapshot file hashes and external
    market-data provenance are checked separately by the replay preflight.
    A standalone, incomplete cash-interest credit after the final NAV is
    permitted, provided the metadata cash equals the credited amount.
    """

    issues: list[str] = []

    def flag(code: str, identifier: object = "") -> None:
        if len(issues) < 100:
            issues.append(f"{code}: {identifier}" if identifier != "" else code)

    for row in connection.execute("PRAGMA quick_check").fetchall():
        if str(row[0]) != "ok":
            flag("sqlite_integrity_failure", row[0])
    for row in connection.execute("PRAGMA foreign_key_check").fetchall():
        flag("foreign_key_violation", f"{row[0]} rowid={row[1]}")

    nav = connection.execute("SELECT * FROM nav ORDER BY timestamp").fetchall()
    commits = {
        str(row["timestamp"])
        for row in connection.execute("SELECT timestamp FROM session_commits").fetchall()
    }
    nav_dates = {str(row["timestamp"]) for row in nav}
    for stamp in sorted(nav_dates - commits):
        flag("missing_session_commit", stamp)
    for stamp in sorted(commits - nav_dates):
        flag("orphan_session_commit", stamp)

    snapshots = connection.execute(
        "SELECT timestamp, dataset_id FROM snapshots"
    ).fetchall()
    snapshot_links = {
        str(row["timestamp"]): row["snapshot_dataset_id"]
        for row in connection.execute(
            "SELECT timestamp, snapshot_dataset_id FROM session_commits"
        ).fetchall()
    }
    for row in snapshots:
        stamp = str(row["timestamp"])
        if snapshot_links.get(stamp) != row["dataset_id"]:
            flag("snapshot_linkage_mismatch", stamp)
    for stamp, dataset_id in snapshot_links.items():
        if dataset_id is not None and not any(
            str(row["timestamp"]) == stamp for row in snapshots
        ):
            flag("snapshot_link_missing", stamp)

    credits = connection.execute(
        "SELECT timestamp, interest_base FROM cash_interest_credits ORDER BY timestamp"
    ).fetchall()
    credit_by_day = {str(row["timestamp"]): float(row["interest_base"]) for row in credits}
    fills = connection.execute(
        "SELECT f.*, o.symbol AS order_symbol, o.side AS order_side "
        "FROM fills AS f LEFT JOIN orders AS o ON o.order_id=f.order_id "
        "ORDER BY f.timestamp, f.fill_id"
    ).fetchall()
    for row in fills:
        if row["order_symbol"] is None or (
            row["symbol"] != row["order_symbol"] or row["side"] != row["order_side"]
        ):
            flag("fill_order_mismatch", row["fill_id"])
        if int(row["quantity"]) <= 0 or float(row["fx_to_base"]) <= 0:
            flag("invalid_fill_quantity_or_fx", row["fill_id"])
        if not _matches(
            float(row["gross_value"]),
            float(row["gross_value_local"]) * float(row["fx_to_base"]),
        ) or not _matches(
            float(row["fees"]),
            float(row["fees_local"]) * float(row["fx_to_base"]),
        ) or not _matches(
            float(row["slippage_cost"]),
            float(row["slippage_cost_local"]) * float(row["fx_to_base"]),
        ):
            flag("fill_fx_accounting_mismatch", row["fill_id"])

    orders = connection.execute(
        "SELECT order_id, requested_qty, remaining_qty, status FROM orders"
    ).fetchall()
    for row in orders:
        requested, remaining = int(row["requested_qty"]), int(row["remaining_qty"])
        if requested < 0 or remaining < 0 or remaining > requested or (
            row["status"] == "FILLED" and remaining != 0
        ):
            flag("invalid_order_balance", row["order_id"])

    marks = connection.execute(
        "SELECT * FROM position_marks ORDER BY timestamp, symbol"
    ).fetchall()
    marks_by_day: dict[str, tuple[float, float]] = {}
    latest_marks: dict[str, int] = {}
    for row in marks:
        stamp = str(row["timestamp"])
        quantity = int(row["quantity"])
        price_base = float(row["close_price"]) * float(row["fx_to_base"])
        value = quantity * price_base
        unrealized = quantity * (price_base - float(row["avg_cost_base"]))
        if quantity <= 0 or not _matches(float(row["market_value_base"]), value) or (
            not _matches(float(row["unrealized_pnl_base"]), unrealized)
        ):
            flag("position_mark_arithmetic_mismatch", f"{stamp} {row['symbol']}")
        prev_value, prev_unrealized = marks_by_day.get(stamp, (0.0, 0.0))
        marks_by_day[stamp] = (
            prev_value + float(row["market_value_base"]),
            prev_unrealized + float(row["unrealized_pnl_base"]),
        )
        if stamp not in nav_dates:
            flag("orphan_position_mark", stamp)

    receivables = connection.execute(
        "SELECT created_at, settled_at, cost_basis_base FROM cash_in_lieu_receivables"
    ).fetchall()
    credit_index = 0
    fill_index = 0
    cumulative_interest = 0.0
    cumulative_fees = 0.0
    cumulative_slippage = 0.0
    for row in nav:
        stamp = str(row["timestamp"])
        while credit_index < len(credits) and str(credits[credit_index]["timestamp"]) <= stamp:
            cumulative_interest += float(credits[credit_index]["interest_base"])
            credit_index += 1
        while fill_index < len(fills) and str(fills[fill_index]["timestamp"]) <= stamp:
            cumulative_fees += float(fills[fill_index]["fees"])
            cumulative_slippage += float(fills[fill_index]["slippage_cost"])
            fill_index += 1

        equity = float(row["cash"]) + float(row["market_value"]) + float(
            row["receivable_value"]
        )
        if not _matches(float(row["equity"]), equity):
            flag("nav_equity_mismatch", stamp)
        if not _matches(float(row["reconciliation_error"]), 0.0):
            flag("nav_reconciliation_mismatch", stamp)
        if not _matches(float(row["cash_interest"]), credit_by_day.get(stamp, 0.0)):
            flag("daily_cash_interest_mismatch", stamp)
        if not _matches(float(row["cumulative_cash_interest"]), cumulative_interest):
            flag("cumulative_cash_interest_mismatch", stamp)
        if not _matches(float(row["cumulative_fees"]), cumulative_fees):
            flag("cumulative_fees_mismatch", stamp)
        if not _matches(float(row["cumulative_slippage"]), cumulative_slippage):
            flag("cumulative_slippage_mismatch", stamp)
        market_value, unrealized_marks = marks_by_day.get(stamp, (0.0, 0.0))
        if not _matches(float(row["market_value"]), market_value):
            flag("nav_market_value_mismatch", stamp)
        open_basis = sum(
            float(receivable["cost_basis_base"])
            for receivable in receivables
            if str(receivable["created_at"]) <= stamp
            and (
                receivable["settled_at"] is None
                or str(receivable["settled_at"]) > stamp
            )
        )
        expected_unrealized = (
            unrealized_marks + float(row["receivable_value"]) - open_basis
        )
        if not _matches(float(row["unrealized_pnl"]), expected_unrealized):
            flag("nav_unrealized_pnl_mismatch", stamp)

    if nav:
        last = nav[-1]
        last_stamp = str(last["timestamp"])
        latest_marks = {
            str(row["symbol"]): int(row["quantity"])
            for row in marks
            if str(row["timestamp"]) == last_stamp
        }
        holdings = connection.execute(
            "SELECT symbol, quantity, realized_pnl_base FROM positions"
        ).fetchall()
        for row in holdings:
            quantity = int(row["quantity"])
            if quantity < 0 or (quantity > 0 and latest_marks.get(str(row["symbol"])) != quantity):
                flag("latest_position_mismatch", row["symbol"])
        for symbol, quantity in latest_marks.items():
            if not any(
                str(row["symbol"]) == symbol and int(row["quantity"]) == quantity
                for row in holdings
            ):
                flag("orphan_latest_position_mark", symbol)
        latest_realized = sum(float(row["realized_pnl_base"]) for row in holdings)
        if not _matches(
            float(last["realized_pnl"]), latest_realized + cumulative_interest
        ):
            flag("latest_realized_pnl_mismatch", last_stamp)
        cash_row = connection.execute(
            "SELECT value FROM metadata WHERE key='cash'"
        ).fetchone()
        if cash_row is None:
            flag("missing_cash_metadata")
        else:
            future_credits = sum(
                value for stamp, value in credit_by_day.items() if stamp > last_stamp
            )
            if not _matches(
                float(json.loads(cash_row["value"])),
                float(last["cash"]) + future_credits,
            ):
                flag("latest_cash_metadata_mismatch", last_stamp)

    return LedgerAuditReport(
        nav_sessions=len(nav),
        fills=len(fills),
        position_marks=len(marks),
        cash_credits=len(credits),
        issues=tuple(issues),
    )
