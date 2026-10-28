"""Read-only independent accounting checks over persistent SQLite paper ledgers."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


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
    return math.isfinite(actual) and math.isfinite(expected) and math.isclose(
        actual, expected, rel_tol=1e-12, abs_tol=1e-6
    )


def _audit_receivables(
    receivables: list[sqlite3.Row],
    actions: list[sqlite3.Row],
    nav_dates: set[str],
    last_nav: str | None,
    flag: Callable[[str, object], None],
) -> None:
    """Match persisted receivable states to their creation and settlement events."""

    pending_actions = [
        row for row in actions
        if row["action"] == "stock_split"
        and row["cash_in_lieu_price_source"] == "pending_settlement"
    ]
    settlement_actions = [row for row in actions if row["action"] == "cash_in_lieu_settlement"]
    used_pending: set[int] = set()
    used_settlements: set[int] = set()

    def same_quantity(left: float, right: float) -> bool:
        return math.isfinite(left) and math.isfinite(right) and math.isclose(
            left, right, rel_tol=0.0, abs_tol=1e-10
        )

    for row in receivables:
        identifier = row["receivable_id"]
        created = str(row["created_at"])
        due = str(row["settlement_date"])
        quantity = float(row["fractional_quantity"])
        basis = float(row["cost_basis_base"])
        try:
            dates_valid = pd.Timestamp(due) > pd.Timestamp(created)
        except (ValueError, TypeError):
            dates_valid = False
        if (
            created not in nav_dates
            or not dates_valid
            or not math.isfinite(quantity)
            or quantity <= 1e-12
            or not math.isfinite(basis)
            or basis < 0
        ):
            flag("invalid_receivable", identifier)

        pending = next(
            (
                event for event in pending_actions
                if int(event["event_id"]) not in used_pending
                and event["symbol"] == row["symbol"]
                and event["timestamp"] == created
                and event["cash_in_lieu_settlement_date"] == due
                and event["local_currency"] == row["local_currency"]
                and same_quantity(float(event["fractional_quantity"]), quantity)
                and _matches(float(event["realized_pnl_delta"]), 0.0)
            ),
            None,
        )
        if pending is None:
            flag("receivable_creation_mismatch", identifier)
        else:
            used_pending.add(int(pending["event_id"]))

        settlement_fields = (
            "settled_at", "settlement_price", "settlement_fx_to_base",
            "cash_value", "realized_pnl_delta",
        )
        if row["status"] == "OPEN":
            if any(row[field] is not None for field in settlement_fields) or (
                last_nav is not None and due <= last_nav
            ):
                flag("invalid_receivable_state", identifier)
            continue
        if row["status"] != "SETTLED" or any(row[field] is None for field in settlement_fields):
            flag("invalid_receivable_state", identifier)
            continue
        settled_at = str(row["settled_at"])
        if settled_at != due or settled_at not in nav_dates:
            flag("invalid_receivable_state", identifier)
        price = float(row["settlement_price"])
        factor = float(row["settlement_fx_to_base"])
        cash = float(row["cash_value"])
        realized = float(row["realized_pnl_delta"])
        if (
            not math.isfinite(price)
            or price <= 0
            or not math.isfinite(factor)
            or factor <= 0
            or not _matches(cash, quantity * price * factor)
            or not _matches(realized, cash - basis)
        ):
            flag("receivable_settlement_cashflow_mismatch", identifier)

        settlement = next(
            (
                event for event in settlement_actions
                if int(event["event_id"]) not in used_settlements
                and event["symbol"] == row["symbol"]
                and event["timestamp"] == settled_at
                and event["local_currency"] == row["local_currency"]
                and event["cash_in_lieu_price_source"] == "provider_settlement"
                and event["cash_in_lieu_settlement_date"] == settled_at
                and same_quantity(float(event["fractional_quantity"]), quantity)
                and _matches(float(event["cash_in_lieu_price"]), price)
                and _matches(float(event["fx_to_base"]), factor)
                and _matches(float(event["cash_value"]), cash)
                and _matches(float(event["realized_pnl_delta"]), realized)
            ),
            None,
        )
        if settlement is None:
            flag("receivable_settlement_event_mismatch", identifier)
        else:
            used_settlements.add(int(settlement["event_id"]))

    for event in pending_actions:
        if int(event["event_id"]) not in used_pending:
            flag("orphan_receivable_creation", event["event_id"])
    for event in settlement_actions:
        if int(event["event_id"]) not in used_settlements:
            flag("orphan_receivable_settlement", event["event_id"])


def audit_paper_ledger(connection: sqlite3.Connection) -> LedgerAuditReport:
    """Verify persisted accounting independently of replay's in-memory state.

    Only reads the SQLite connection. The snapshot file hashes and external
    market-data provenance are checked separately by the replay preflight.
    A single incomplete cash-interest credit after the final NAV is permitted
    if its interval, calculation and metadata cash are consistent. Replay also
    requires that credit to belong to the next supplied session.
    """

    issues: list[str] = []

    def flag(code: str, identifier: object = "") -> None:
        if len(issues) < 100:
            issues.append(f"{code}: {identifier}" if identifier != "" else code)

    def metadata_number(key: str, *, required: bool = True) -> float | None:
        row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        if row is None:
            if required:
                flag("missing_ledger_metadata", key)
            return None
        try:
            value = float(json.loads(row["value"]))
        except (TypeError, ValueError, OverflowError):
            flag("invalid_ledger_metadata", key)
            return None
        if not math.isfinite(value):
            flag("invalid_ledger_metadata", key)
            return None
        return value

    initial_cash = metadata_number("initial_cash")
    if initial_cash is not None and initial_cash <= 0:
        flag("invalid_ledger_metadata", "initial_cash")
    cash_metadata = metadata_number("cash")

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
        "SELECT * FROM cash_interest_credits ORDER BY timestamp"
    ).fetchall()
    credit_by_day = {str(row["timestamp"]): float(row["interest_base"]) for row in credits}
    # Sort each day's flows in the same order as the documented session:
    # interest, corporate actions (including settlements), terminals, fills.
    cash_flows: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    for row in credits:
        if math.isfinite(float(row["interest_base"])):
            cash_flows[str(row["timestamp"])].append((0, 0, float(row["interest_base"])))

    # Every session after the first starts with a durable interest credit, even
    # when the locked yield is zero. One credit after the last NAV is the legacy
    # recoverable interruption between accrual and the rest of a session.
    previous_nav = {
        str(nav[index]["timestamp"]): nav[index - 1] for index in range(1, len(nav))
    }
    for stamp in previous_nav:
        if stamp not in credit_by_day:
            flag("missing_cash_interest_credit", stamp)
    rate = metadata_number("cash_annual_yield", required=bool(credits))
    if rate is not None and not 0.0 <= rate <= 1.0:
        flag("invalid_ledger_metadata", "cash_annual_yield")
        rate = None
    future_credit_count = 0
    for row in credits:
        stamp = str(row["timestamp"])
        previous = previous_nav.get(stamp)
        if previous is None and nav and stamp > str(nav[-1]["timestamp"]):
            future_credit_count += 1
            previous = nav[-1]
            if future_credit_count > 1:
                flag("multiple_uncommitted_cash_interest_credits", stamp)
        if previous is None:
            flag("orphan_cash_interest_credit", stamp)
            continue

        prior_stamp = str(previous["timestamp"])
        prior_cash = float(previous["cash"])
        if str(row["previous_close"]) != prior_stamp:
            flag("cash_interest_previous_close_mismatch", stamp)
        if not _matches(float(row["eligible_cash_base"]), prior_cash):
            flag("cash_interest_eligible_cash_mismatch", stamp)
        if rate is not None and float(row["annual_yield"]) != rate:
            flag("cash_interest_rate_mismatch", stamp)
        try:
            days = (
                pd.Timestamp(stamp).date() - pd.Timestamp(prior_stamp).date()
            ).days
        except ValueError:
            days = 0
        if days <= 0 or row["accrual_days"] != days:
            flag("cash_interest_interval_mismatch", stamp)
        if rate is not None and days > 0:
            expected_interest = max(prior_cash, 0.0) * rate * days / 365.0
            if not _matches(float(row["interest_base"]), expected_interest):
                flag("cash_interest_formula_mismatch", stamp)
            if not _matches(float(row["cash_after_base"]), prior_cash + expected_interest):
                flag("cash_interest_cash_after_mismatch", stamp)

    fills = connection.execute(
        "SELECT f.*, o.symbol AS order_symbol, o.side AS order_side "
        "FROM fills AS f LEFT JOIN orders AS o ON o.order_id=f.order_id "
        "ORDER BY f.timestamp, f.fill_id"
    ).fetchall()
    for row in fills:
        if str(row["timestamp"]) not in nav_dates:
            flag("incomplete persistent session", f"fill {row['fill_id']}")
        if row["order_symbol"] is None or (
            row["symbol"] != row["order_symbol"] or row["side"] != row["order_side"]
        ):
            flag("fill_order_mismatch", row["fill_id"])
        if int(row["quantity"]) <= 0 or float(row["fx_to_base"]) <= 0:
            flag("invalid_fill_quantity_or_fx", row["fill_id"])
        if row["side"] not in {"BUY", "SELL"}:
            flag("invalid_fill_side", row["fill_id"])
        gross, fees = float(row["gross_value"]), float(row["fees"])
        if not math.isfinite(gross) or not math.isfinite(fees) or gross < 0 or fees < 0:
            flag("invalid_fill_cashflow", row["fill_id"])
        elif row["side"] in {"BUY", "SELL"}:
            gross_local = float(row["gross_value_local"])
            fees_local = float(row["fees_local"])
            factor = float(row["fx_to_base"])
            if all(math.isfinite(value) for value in (gross_local, fees_local, factor)):
                amount = (
                    -(gross_local + fees_local) * factor
                    if row["side"] == "BUY"
                    else (gross_local - fees_local) * factor
                )
                cash_flows[str(row["timestamp"])].append((3, int(row["fill_id"]), amount))
        if not _matches(
            float(row["gross_value_local"]), int(row["quantity"]) * float(row["fill_price"])
        ) or not _matches(
            float(row["slippage_cost_local"]),
            int(row["quantity"]) * abs(float(row["fill_price"]) - float(row["reference_price"])),
        ):
            flag("fill_price_accounting_mismatch", row["fill_id"])
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

    actions = connection.execute(
        "SELECT * FROM corporate_actions ORDER BY timestamp, event_id"
    ).fetchall()
    for row in actions:
        event_id = row["event_id"]
        if str(row["timestamp"]) not in nav_dates:
            flag("incomplete persistent session", f"corporate action {event_id}")
        if row["action"] not in {"stock_split", "cash_dividend", "cash_in_lieu_settlement"}:
            flag("invalid_corporate_action", event_id)
        cash = float(row["cash_value"])
        if not math.isfinite(cash) or cash < 0:
            flag("invalid_corporate_action_cashflow", event_id)
        else:
            # Settlement cash is recorded in corporate_actions as well as in
            # receivables; count the former only to avoid double counting.
            cash_flows[str(row["timestamp"])].append((1, int(event_id), cash))
        factor = float(row["fx_to_base"])
        cash_local = float(row["cash_value_local"])
        gross_local = float(row["gross_cash_value_local"])
        tax_local = float(row["withholding_tax_local"])
        withholding_rate = float(row["withholding_rate"])
        if (
            not math.isfinite(factor)
            or factor <= 0
            or not 0.0 <= withholding_rate <= 1.0
            or any(
                not math.isfinite(value) or value < 0
                for value in (cash_local, gross_local, tax_local)
            )
            or not _matches(gross_local, cash_local + tax_local)
            or not _matches(tax_local, gross_local * withholding_rate)
            or not _matches(cash, cash_local * factor)
            or not _matches(float(row["gross_cash_value"]), gross_local * factor)
            or not _matches(float(row["withholding_tax"]), tax_local * factor)
            or (row["action"] != "cash_dividend" and withholding_rate != 0.0)
        ):
            flag("corporate_action_cashflow_mismatch", event_id)
        if row["cash_in_lieu_price_source"] == "pending_settlement" and cash != 0.0:
            flag("pending_receivable_cashflow_mismatch", event_id)
        if row["action"] == "cash_dividend" and not _matches(
            gross_local, int(row["quantity_before"]) * float(row["ratio_or_amount"])
        ):
            flag("dividend_gross_mismatch", event_id)
        if row["action"] in {"stock_split", "cash_in_lieu_settlement"} and row[
            "cash_in_lieu_price_source"
        ] in {"provider_settlement", "raw_open_fallback"}:
            fractional = float(row["fractional_quantity"])
            price = float(row["cash_in_lieu_price"])
            if (
                not math.isfinite(fractional)
                or fractional <= 1e-12
                or not math.isfinite(price)
                or price <= 0
                or not _matches(cash_local, fractional * price)
            ):
                flag("cash_in_lieu_cashflow_mismatch", event_id)

    terminals = connection.execute(
        "SELECT event_id, timestamp, proceeds FROM terminal_events ORDER BY timestamp, event_id"
    ).fetchall()
    for row in terminals:
        if str(row["timestamp"]) not in nav_dates:
            flag("incomplete persistent session", f"terminal event {row['event_id']}")
        proceeds = float(row["proceeds"])
        if not math.isfinite(proceeds) or proceeds < 0:
            flag("invalid_terminal_cashflow", row["event_id"])
        else:
            cash_flows[str(row["timestamp"])].append((2, int(row["event_id"]), proceeds))

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
        "SELECT * FROM cash_in_lieu_receivables ORDER BY receivable_id"
    ).fetchall()
    _audit_receivables(
        receivables,
        actions,
        nav_dates,
        None if not nav else str(nav[-1]["timestamp"]),
        flag,
    )
    credit_index = 0
    fill_index = 0
    cumulative_interest = 0.0
    cumulative_fees = 0.0
    cumulative_slippage = 0.0
    cash_flow_dates = sorted(cash_flows)
    cash_flow_index = 0
    reconstructed_cash = initial_cash
    for row in nav:
        stamp = str(row["timestamp"])
        while credit_index < len(credits) and str(credits[credit_index]["timestamp"]) <= stamp:
            cumulative_interest += float(credits[credit_index]["interest_base"])
            credit_index += 1
        while fill_index < len(fills) and str(fills[fill_index]["timestamp"]) <= stamp:
            cumulative_fees += float(fills[fill_index]["fees"])
            cumulative_slippage += float(fills[fill_index]["slippage_cost"])
            fill_index += 1
        while cash_flow_index < len(cash_flow_dates) and cash_flow_dates[cash_flow_index] <= stamp:
            if reconstructed_cash is not None:
                for _, _, amount in sorted(cash_flows[cash_flow_dates[cash_flow_index]]):
                    reconstructed_cash += amount
            cash_flow_index += 1

        if reconstructed_cash is not None and not _matches(float(row["cash"]), reconstructed_cash):
            flag("nav_cashflow_mismatch", stamp)

        equity = float(row["cash"]) + float(row["market_value"]) + float(
            row["receivable_value"]
        )
        if not _matches(float(row["equity"]), equity):
            flag("nav_equity_mismatch", stamp)
        if initial_cash is not None and not _matches(
            float(row["equity"]),
            initial_cash + float(row["realized_pnl"]) + float(row["unrealized_pnl"]),
        ):
            flag("nav_pnl_mismatch", stamp)
        if not _matches(
            float(row["equity"]) + float(row["reconciliation_error"]), float(row["equity"])
        ):
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
        if cash_metadata is not None:
            future_credits = sum(
                value for stamp, value in credit_by_day.items() if stamp > last_stamp
            )
            if not _matches(
                cash_metadata,
                float(last["cash"]) + future_credits,
            ):
                flag("latest_cash_metadata_mismatch", last_stamp)
    elif not cash_flows and cash_metadata is not None and initial_cash is not None:
        if not _matches(cash_metadata, initial_cash):
            flag("initial_cash_metadata_mismatch")

    return LedgerAuditReport(
        nav_sessions=len(nav),
        fills=len(fills),
        position_marks=len(marks),
        cash_credits=len(credits),
        issues=tuple(issues),
    )
