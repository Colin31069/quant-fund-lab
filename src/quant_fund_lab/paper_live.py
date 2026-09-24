from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import nullcontext
from pathlib import Path

import pandas as pd

from .cash_carry import accrue_base_cash_interest
from .config import BacktestConfig, DividendWithholdingConfig
from .corporate_actions import (
    CashInLieuReceivable,
    apply_cash_dividend_events,
    apply_stock_split_events,
    mark_cash_in_lieu_receivables,
    settle_cash_in_lieu_receivables,
)
from .data import MarketData
from .execution import (
    Fill,
    PortfolioState,
    apply_terminal_returns,
    desired_quantities,
    execute_market_order,
    transition_safe_reference,
)
from .fx import currency_for_symbol, validate_fx
from .replay_provenance import replay_session_data_fingerprint
from .snapshot import SnapshotManifest, save_market_data_snapshot

_OPEN_ORDER_STATUSES = ("NEW", "PARTIAL")


def _signal_fingerprint(weights: pd.Series) -> str:
    """Stable hash of close-signal weights, including zero-order target sessions."""

    payload = {str(symbol): float(weight) for symbol, weight in weights.items()}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class PaperLedger:
    """Persistent SQLite ledger for virtual orders, fills, positions, marks and NAV."""

    def __init__(
        self,
        path: str | Path,
        initial_cash: float | None = None,
        base_currency: str | None = None,
        reset: bool = False,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reset and self.path.exists():
            self.path.unlink()
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()
        existing_cash = self._get_meta("cash")
        if existing_cash is None:
            if initial_cash is None or base_currency is None:
                raise ValueError("initial_cash and base_currency are required for a new paper ledger")
            if initial_cash <= 0.0:
                raise ValueError("initial_cash must be positive")
            self._set_meta("initial_cash", float(initial_cash))
            self._set_meta("cash", float(initial_cash))
            self._set_meta("base_currency", base_currency.upper())
            self.connection.commit()
        elif base_currency is not None and self.base_currency != base_currency.upper():
            raise ValueError("base_currency does not match the existing paper ledger")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> PaperLedger:  # noqa: PYI034 - Python 3.9 project, no typing.Self.
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL,
                avg_cost_base REAL NOT NULL,
                realized_pnl_base REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                requested_qty INTEGER NOT NULL,
                remaining_qty INTEGER NOT NULL,
                status TEXT NOT NULL,
                target_weight REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fills (
                fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                reference_price REAL NOT NULL,
                fill_price REAL NOT NULL,
                gross_value REAL NOT NULL,
                fees REAL NOT NULL,
                slippage_cost REAL NOT NULL,
                local_currency TEXT NOT NULL,
                fx_to_base REAL NOT NULL,
                gross_value_local REAL NOT NULL,
                fees_local REAL NOT NULL,
                slippage_cost_local REAL NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(order_id)
            );
            CREATE TABLE IF NOT EXISTS corporate_actions (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity_before INTEGER NOT NULL,
                quantity_after INTEGER NOT NULL,
                ratio_or_amount REAL NOT NULL,
                cash_value REAL NOT NULL,
                cash_value_local REAL NOT NULL,
                local_currency TEXT NOT NULL DEFAULT '',
                fx_to_base REAL NOT NULL,
                gross_cash_value REAL NOT NULL DEFAULT 0,
                gross_cash_value_local REAL NOT NULL DEFAULT 0,
                withholding_tax REAL NOT NULL DEFAULT 0,
                withholding_tax_local REAL NOT NULL DEFAULT 0,
                withholding_rate REAL NOT NULL DEFAULT 0,
                cash_in_lieu_price REAL NOT NULL DEFAULT 0,
                cash_in_lieu_price_source TEXT NOT NULL DEFAULT '',
                realized_pnl_delta REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cash_in_lieu_receivables (
                receivable_id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                created_at TEXT NOT NULL,
                fractional_quantity REAL NOT NULL,
                settlement_date TEXT NOT NULL,
                local_currency TEXT NOT NULL,
                cost_basis_base REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                settled_at TEXT,
                settlement_price REAL,
                settlement_fx_to_base REAL,
                cash_value REAL,
                realized_pnl_delta REAL
            );
            CREATE TABLE IF NOT EXISTS terminal_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                reference_price REAL NOT NULL,
                terminal_return REAL NOT NULL,
                proceeds REAL NOT NULL,
                realized_pnl_base REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS position_marks (
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                avg_cost_base REAL NOT NULL,
                close_price REAL NOT NULL,
                fx_to_base REAL NOT NULL,
                market_value_base REAL NOT NULL,
                unrealized_pnl_base REAL NOT NULL,
                PRIMARY KEY(timestamp, symbol)
            );
            CREATE TABLE IF NOT EXISTS nav (
                timestamp TEXT PRIMARY KEY,
                cash REAL NOT NULL,
                market_value REAL NOT NULL,
                receivable_value REAL NOT NULL DEFAULT 0,
                cash_interest REAL NOT NULL DEFAULT 0,
                cumulative_cash_interest REAL NOT NULL DEFAULT 0,
                equity REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                cumulative_fees REAL NOT NULL,
                cumulative_slippage REAL NOT NULL,
                benchmark_close_base REAL,
                benchmark_equity REAL,
                reconciliation_error REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cash_interest_credits (
                timestamp TEXT PRIMARY KEY,
                previous_close TEXT NOT NULL,
                eligible_cash_base REAL NOT NULL,
                annual_yield REAL NOT NULL,
                accrual_days INTEGER NOT NULL,
                interest_base REAL NOT NULL,
                cash_after_base REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                timestamp TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_commits (
                timestamp TEXT PRIMARY KEY REFERENCES nav(timestamp),
                had_signal INTEGER NOT NULL CHECK(had_signal IN (0, 1)),
                signal_fingerprint TEXT NOT NULL,
                snapshot_dataset_id TEXT,
                data_fingerprint TEXT NOT NULL DEFAULT ''
            );
            """
        )
        self._migrate_corporate_action_schema()
        self._migrate_nav_schema()
        self._migrate_session_commit_schema()
        self.connection.commit()

    def _migrate_corporate_action_schema(self) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(corporate_actions)").fetchall()
        }
        additions = {
            "local_currency": "TEXT NOT NULL DEFAULT ''",
            "gross_cash_value": "REAL NOT NULL DEFAULT 0",
            "gross_cash_value_local": "REAL NOT NULL DEFAULT 0",
            "withholding_tax": "REAL NOT NULL DEFAULT 0",
            "withholding_tax_local": "REAL NOT NULL DEFAULT 0",
            "withholding_rate": "REAL NOT NULL DEFAULT 0",
            "cash_in_lieu_price": "REAL NOT NULL DEFAULT 0",
            "cash_in_lieu_price_source": "TEXT NOT NULL DEFAULT ''",
            "fractional_quantity": "REAL NOT NULL DEFAULT 0",
            "cash_in_lieu_settlement_date": "TEXT NOT NULL DEFAULT ''",
        }
        added: set[str] = set()
        for column, declaration in additions.items():
            if column not in columns:
                self.connection.execute(
                    f"ALTER TABLE corporate_actions ADD COLUMN {column} {declaration}"
                )
                added.add(column)
        if "gross_cash_value" in added:
            self.connection.execute(
                "UPDATE corporate_actions SET gross_cash_value=cash_value"
            )
        if "gross_cash_value_local" in added:
            self.connection.execute(
                "UPDATE corporate_actions SET gross_cash_value_local=cash_value_local"
            )
        if "withholding_rate" in added:
            self.connection.execute(
                "UPDATE corporate_actions SET withholding_rate="
                "CASE WHEN gross_cash_value_local > 0 "
                "THEN withholding_tax_local / gross_cash_value_local ELSE 0 END"
            )

    def _migrate_nav_schema(self) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(nav)").fetchall()
        }
        if "receivable_value" not in columns:
            self.connection.execute(
                "ALTER TABLE nav ADD COLUMN receivable_value REAL NOT NULL DEFAULT 0"
            )
        if "cash_interest" not in columns:
            self.connection.execute(
                "ALTER TABLE nav ADD COLUMN cash_interest REAL NOT NULL DEFAULT 0"
            )
        if "cumulative_cash_interest" not in columns:
            self.connection.execute(
                "ALTER TABLE nav ADD COLUMN cumulative_cash_interest REAL NOT NULL DEFAULT 0"
            )

    def _migrate_session_commit_schema(self) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(session_commits)").fetchall()
        }
        if "data_fingerprint" not in columns:
            self.connection.execute(
                "ALTER TABLE session_commits ADD COLUMN data_fingerprint TEXT NOT NULL DEFAULT ''"
            )

    def _get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _set_meta(self, key: str, value: object) -> None:
        serialized = json.dumps(value, separators=(",", ":"))
        self.connection.execute(
            "INSERT INTO metadata(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, serialized),
        )

    def _meta_value(self, key: str) -> object | None:
        raw = self._get_meta(key)
        return None if raw is None else json.loads(raw)

    @property
    def cash(self) -> float:
        return float(self._meta_value("cash"))

    @property
    def initial_cash(self) -> float:
        return float(self._meta_value("initial_cash"))

    @property
    def base_currency(self) -> str:
        return str(self._meta_value("base_currency"))

    def portfolio_state(self) -> PortfolioState:
        rows = self.connection.execute(
            "SELECT symbol, quantity FROM positions WHERE quantity != 0"
        ).fetchall()
        shares = {str(row["symbol"]): int(row["quantity"]) for row in rows}
        return PortfolioState(cash=self.cash, shares=shares)

    def positions(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT symbol, quantity, avg_cost_base, realized_pnl_base FROM positions ORDER BY symbol",
            self.connection,
        ).set_index("symbol")

    def orders(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM orders ORDER BY order_id", self.connection)

    def fills(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM fills ORDER BY fill_id", self.connection)

    def corporate_actions(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM corporate_actions ORDER BY event_id", self.connection
        )

    def cash_in_lieu_receivables(self) -> pd.DataFrame:
        frame = pd.read_sql_query(
            "SELECT * FROM cash_in_lieu_receivables ORDER BY receivable_id",
            self.connection,
        )
        for column in ("created_at", "settlement_date", "settled_at"):
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
        return frame

    def cash_interest_credits(self) -> pd.DataFrame:
        frame = pd.read_sql_query(
            "SELECT * FROM cash_interest_credits ORDER BY timestamp", self.connection
        )
        for column in ("timestamp", "previous_close"):
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
        return frame

    def nav_history(self) -> pd.DataFrame:
        frame = pd.read_sql_query("SELECT * FROM nav ORDER BY timestamp", self.connection)
        if not frame.empty:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
            frame = frame.set_index("timestamp")
        return frame

    def snapshots(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM snapshots ORDER BY timestamp", self.connection)

    def session_commits(self) -> pd.DataFrame:
        frame = pd.read_sql_query(
            "SELECT * FROM session_commits ORDER BY timestamp", self.connection
        )
        if not frame.empty:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
            frame = frame.set_index("timestamp")
        return frame

    def verify_completed_sessions(
        self,
        data: MarketData,
        target_weights: pd.DataFrame,
        *,
        execution_reference: pd.DataFrame,
        benchmark_close_base: pd.Series | None = None,
    ) -> pd.Timestamp | None:
        """Verify all historical prices, FX, corporate actions and signals before continuation."""

        rows = self.connection.execute(
            "SELECT timestamp, had_signal, signal_fingerprint, data_fingerprint "
            "FROM session_commits ORDER BY timestamp"
        ).fetchall()
        nav_rows = self.connection.execute(
            "SELECT timestamp FROM nav ORDER BY timestamp"
        ).fetchall()
        nav_dates = [pd.Timestamp(row["timestamp"]) for row in nav_rows]
        commit_dates = [pd.Timestamp(row["timestamp"]) for row in rows]
        if nav_dates != commit_dates:
            raise ValueError(
                "paper ledger NAV is missing session completion markers; "
                "legacy or incomplete sessions require manual recovery"
            )
        missing_history = [stamp for stamp in nav_dates if stamp not in data.close.index]
        if missing_history:
            raise ValueError(
                "replay data is missing completed sessions required for provenance verification: "
                f"{missing_history[0].date()}"
            )
        for row in rows:
            timestamp = pd.Timestamp(row["timestamp"])
            fingerprint = str(row["data_fingerprint"])
            if not fingerprint:
                raise ValueError(
                    "legacy paper ledger has no replay data fingerprint for "
                    f"{timestamp.date()}; manual provenance audit is required"
                )
            benchmark_value = (
                None
                if benchmark_close_base is None or timestamp not in benchmark_close_base.index
                else float(benchmark_close_base.loc[timestamp])
            )
            observed = replay_session_data_fingerprint(
                data, timestamp, execution_reference.loc[timestamp], benchmark_value
            )
            if fingerprint != observed:
                raise ValueError(
                    f"replay data fingerprint mismatch on {timestamp.date()}; "
                    "completed session inputs have changed"
                )
            had_signal = bool(row["had_signal"])
            supplied_signal = timestamp in target_weights.index
            if had_signal != supplied_signal:
                raise ValueError(
                    "completed session target schedule conflicts with replay inputs"
                )
            if supplied_signal:
                weights = target_weights.loc[timestamp].reindex(data.symbols).fillna(0.0)
                if _signal_fingerprint(weights) != str(row["signal_fingerprint"]):
                    raise ValueError(
                        "completed session target weights conflict with replay inputs"
                    )
        return None if not nav_dates else nav_dates[-1]

    def record_session_commit(
        self,
        timestamp: pd.Timestamp,
        target_weights: pd.Series | None,
        *,
        data_fingerprint: str,
    ) -> None:
        """Commit the close signal and canonical market-data provenance with the daily NAV."""

        if len(data_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in data_fingerprint):
            raise ValueError("session data_fingerprint must be a SHA-256 hexadecimal digest")
        stamp = pd.Timestamp(timestamp).isoformat()
        if self.connection.execute(
            "SELECT 1 FROM nav WHERE timestamp=?", (stamp,)
        ).fetchone() is None:
            raise ValueError("session cannot commit without a daily NAV")
        snapshot = self.connection.execute(
            "SELECT dataset_id FROM snapshots WHERE timestamp=?", (stamp,)
        ).fetchone()
        self.connection.execute(
            "INSERT INTO session_commits("
            "timestamp, had_signal, signal_fingerprint, snapshot_dataset_id, data_fingerprint"
            ") VALUES(?, ?, ?, ?, ?)",
            (
                stamp,
                int(target_weights is not None),
                "" if target_weights is None else _signal_fingerprint(target_weights),
                None if snapshot is None else str(snapshot["dataset_id"]),
                data_fingerprint,
            ),
        )

    def cancel_open_orders(self, status: str = "CANCELLED", *, commit: bool = True) -> int:
        cursor = self.connection.execute(
            "UPDATE orders SET status = ? WHERE status IN ('NEW', 'PARTIAL')", (status,)
        )
        if commit:
            self.connection.commit()
        return int(cursor.rowcount)

    def submit_target_orders(
        self,
        signal_date: pd.Timestamp,
        target_weights: pd.Series,
        mark_prices: pd.Series,
        config: BacktestConfig,
        fx_to_base: pd.Series | None = None,
        market_codes: pd.Series | None = None,
        currency_codes: pd.Series | None = None,
        *,
        commit: bool = True,
    ) -> list[int]:
        """Replace outstanding target orders after the signal-date close."""

        self.cancel_open_orders("CANCELLED_REPLACED", commit=False)
        state = self.portfolio_state()
        state.receivable_value = self._mark_open_receivables(
            mark_prices,
            fx_to_base,
            currency_codes,
        )[0]
        factors = (
            fx_to_base.reindex(target_weights.index).astype(float)
            if fx_to_base is not None
            else pd.Series(1.0, index=target_weights.index, dtype=float)
        )
        desired = desired_quantities(
            state,
            target_weights,
            mark_prices,
            config,
            factors,
            market_codes,
        )
        created: list[int] = []
        for symbol in target_weights.index:
            current = state.shares.get(symbol, 0)
            delta = int(desired[symbol]) - current
            if delta == 0:
                continue
            side = "BUY" if delta > 0 else "SELL"
            quantity = abs(delta)
            cursor = self.connection.execute(
                "INSERT INTO orders(created_at, symbol, side, requested_qty, remaining_qty, status, target_weight) "
                "VALUES(?, ?, ?, ?, ?, 'NEW', ?)",
                (
                    pd.Timestamp(signal_date).isoformat(),
                    symbol,
                    side,
                    quantity,
                    quantity,
                    float(target_weights[symbol]),
                ),
            )
            created.append(int(cursor.lastrowid))
        if commit:
            self.connection.commit()
        return created

    def _position_row(self, symbol: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT symbol, quantity, avg_cost_base, realized_pnl_base FROM positions WHERE symbol = ?",
            (symbol,),
        ).fetchone()

    def _record_fill(self, order_id: int, fill: Fill) -> None:
        row = self._position_row(fill.symbol)
        prior_qty = int(row["quantity"]) if row is not None else 0
        prior_avg = float(row["avg_cost_base"]) if row is not None else 0.0
        prior_realized = float(row["realized_pnl_base"]) if row is not None else 0.0

        if fill.side == "BUY":
            new_qty = prior_qty + fill.quantity
            total_cost = prior_qty * prior_avg + fill.gross_value + fill.fees
            new_avg = total_cost / new_qty if new_qty > 0 else 0.0
            realized = prior_realized
        else:
            new_qty = prior_qty - fill.quantity
            realized = prior_realized + (fill.gross_value - fill.fees - prior_avg * fill.quantity)
            new_avg = prior_avg if new_qty > 0 else 0.0

        self.connection.execute(
            "INSERT INTO positions(symbol, quantity, avg_cost_base, realized_pnl_base) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, "
            "avg_cost_base=excluded.avg_cost_base, realized_pnl_base=excluded.realized_pnl_base",
            (fill.symbol, new_qty, float(new_avg), float(realized)),
        )
        self.connection.execute(
            "INSERT INTO fills(order_id, timestamp, symbol, side, quantity, reference_price, fill_price, "
            "gross_value, fees, slippage_cost, local_currency, fx_to_base, gross_value_local, fees_local, "
            "slippage_cost_local) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                pd.Timestamp(fill.timestamp).isoformat(),
                fill.symbol,
                fill.side,
                fill.quantity,
                fill.reference_price,
                fill.fill_price,
                fill.gross_value,
                fill.fees,
                fill.slippage_cost,
                fill.local_currency,
                fill.fx_to_base,
                fill.gross_value_local,
                fill.fees_local,
                fill.slippage_cost_local,
            ),
        )
        order = self.connection.execute(
            "SELECT remaining_qty FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        remaining = max(int(order["remaining_qty"]) - fill.quantity, 0)
        status = "FILLED" if remaining == 0 else "PARTIAL"
        self.connection.execute(
            "UPDATE orders SET remaining_qty = ?, status = ? WHERE order_id = ?",
            (remaining, status, order_id),
        )

    def process_open(
        self,
        timestamp: pd.Timestamp,
        open_prices: pd.Series,
        volumes: pd.Series,
        reference_prices: pd.Series,
        config: BacktestConfig,
        fx_to_base: pd.Series | None = None,
        market_codes: pd.Series | None = None,
        currency_codes: pd.Series | None = None,
        *,
        commit: bool = True,
    ) -> list[Fill]:
        """Retry all NEW/PARTIAL orders; unfilled quantities remain persistent."""

        state = self.portfolio_state()
        orders = self.connection.execute(
            "SELECT * FROM orders WHERE status IN ('NEW','PARTIAL') "
            "ORDER BY CASE side WHEN 'SELL' THEN 0 ELSE 1 END, order_id"
        ).fetchall()
        fills: list[Fill] = []
        for order in orders:
            symbol = str(order["symbol"])
            factor = 1.0 if fx_to_base is None else float(fx_to_base.get(symbol, float("nan")))
            fill = execute_market_order(
                state=state,
                symbol=symbol,
                side=str(order["side"]),
                quantity=int(order["remaining_qty"]),
                open_price=float(open_prices.get(symbol, float("nan"))),
                volume=float(volumes.get(symbol, 0.0)),
                reference_price=float(reference_prices.get(symbol, float("nan"))),
                timestamp=pd.Timestamp(timestamp),
                config=config,
                fx_to_base=factor,
                market_code=None if market_codes is None else market_codes.get(symbol),
                local_currency=None if currency_codes is None else currency_codes.get(symbol),
            )
            if fill is None:
                continue
            self._record_fill(int(order["order_id"]), fill)
            fills.append(fill)
        self._set_meta("cash", float(state.cash))
        if commit:
            self.connection.commit()
        return fills

    def ensure_execution_price_basis(self, basis: str) -> None:
        if basis not in {"adjusted", "raw"}:
            raise ValueError("execution_price_basis must be 'adjusted' or 'raw'")
        existing = self._meta_value("execution_price_basis")
        if existing is None:
            self._set_meta("execution_price_basis", basis)
            self.connection.commit()
        elif str(existing) != basis:
            raise ValueError("execution_price_basis does not match the existing paper ledger")

    def ensure_cash_annual_yield(self, annual_yield: float) -> None:
        """Lock a reproducible cash-carry assumption before replaying ledger sessions."""

        rate = float(annual_yield)
        if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
            raise ValueError("cash_annual_yield must be finite and between 0 and 1")
        existing = self._meta_value("cash_annual_yield")
        if existing is not None:
            if float(existing) != rate:
                raise ValueError(
                    "cash_annual_yield does not match the existing paper ledger"
                )
            return

        if self.connection.execute(
            "SELECT 1 FROM cash_interest_credits LIMIT 1"
        ).fetchone() is not None:
            raise ValueError("paper ledger cash-interest metadata is missing")
        activity = any(
            self.connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            is not None
            for table in (
                "nav",
                "orders",
                "fills",
                "corporate_actions",
                "terminal_events",
                "cash_in_lieu_receivables",
            )
        )
        if activity and rate != 0.0:
            raise ValueError(
                "legacy paper ledger cannot adopt nonzero cash_annual_yield "
                "after trading or NAV history exists"
            )
        self._set_meta("cash_annual_yield", rate)
        self.connection.commit()

    def ensure_replay_session_is_restartable(self, timestamp: pd.Timestamp) -> None:
        """Fail closed if a previous attempt posted non-interest activity without NAV."""

        stamp = pd.Timestamp(timestamp).isoformat()
        already_marked = self.connection.execute(
            "SELECT 1 FROM nav WHERE timestamp=?", (stamp,)
        ).fetchone()
        if already_marked is not None:
            return
        for table in ("fills", "corporate_actions", "terminal_events"):
            if self.connection.execute(
                f"SELECT 1 FROM {table} WHERE timestamp=? LIMIT 1", (stamp,)
            ).fetchone() is not None:
                raise ValueError(
                    "incomplete persistent session contains posted trading or "
                    "corporate-action events; manual recovery is required"
                )

    def accrue_cash_interest(self, timestamp: pd.Timestamp, *, commit: bool = True) -> float:
        """Post a single durable ACT/365 credit before the session's open events.

        The credit and updated spendable cash commit atomically. An existing credit
        is returned without modifying cash, including after an interrupted replay.
        """

        locked = self._meta_value("cash_annual_yield")
        if locked is None:
            raise ValueError("cash_annual_yield must be locked before accrual")
        rate = float(locked)
        stamp = pd.Timestamp(timestamp)
        latest = self.connection.execute(
            "SELECT timestamp, cash FROM nav ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        last_mark = None if latest is None else pd.Timestamp(latest["timestamp"])
        if last_mark is not None and last_mark > stamp:
            raise ValueError("cash interest cannot be credited before the last NAV")

        existing = self.connection.execute(
            "SELECT * FROM cash_interest_credits WHERE timestamp=?",
            (stamp.isoformat(),),
        ).fetchone()
        if existing is not None:
            if float(existing["annual_yield"]) != rate:
                raise ValueError("cash-interest credit rate conflicts with ledger assumptions")
            if (
                last_mark is not None
                and last_mark < stamp
                and pd.Timestamp(existing["previous_close"]) != last_mark
            ):
                raise ValueError("cash-interest credit interval conflicts with last NAV")
            return float(existing["interest_base"])

        if last_mark is None or last_mark == stamp:
            return 0.0

        prior_cash = float(latest["cash"])
        if not math.isclose(self.cash, prior_cash, rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError(
                "cash balance changed after last NAV before cash-interest accrual"
            )
        state = PortfolioState(cash=prior_cash)
        interest = accrue_base_cash_interest(state, last_mark, stamp, rate)
        days = (stamp.date() - last_mark.date()).days
        with self.connection if commit else nullcontext():
            self.connection.execute(
                "INSERT INTO cash_interest_credits("
                "timestamp, previous_close, eligible_cash_base, annual_yield, "
                "accrual_days, interest_base, cash_after_base"
                ") VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    stamp.isoformat(),
                    last_mark.isoformat(),
                    prior_cash,
                    rate,
                    days,
                    interest,
                    float(state.cash),
                ),
            )
            self._set_meta("cash", float(state.cash))
        return interest

    def ensure_dividend_withholding(
        self, config: DividendWithholdingConfig, *, commit: bool = True
    ) -> None:
        expected = {"US": float(config.us_rate), "TW": float(config.tw_rate)}
        existing = self._meta_value("dividend_withholding")
        if existing is not None:
            observed = {str(key): float(value) for key, value in dict(existing).items()}
            if observed != expected:
                raise ValueError(
                    "dividend withholding assumptions do not match the existing paper ledger"
                )
            return

        rows = self.connection.execute(
            "SELECT local_currency, gross_cash_value_local, withholding_tax_local, "
            "withholding_rate FROM corporate_actions WHERE action='cash_dividend'"
        ).fetchall()
        observed_by_market: dict[str, list[float]] = {"US": [], "TW": []}
        has_unknown_legacy_dividend = False
        for row in rows:
            gross_local = float(row["gross_cash_value_local"])
            if gross_local <= 0.0:
                continue
            currency = str(row["local_currency"]).upper().strip()
            market = {"USD": "US", "TWD": "TW"}.get(currency)
            if market is None:
                has_unknown_legacy_dividend = True
                continue
            rate = float(row["withholding_rate"])
            if rate == 0.0 and float(row["withholding_tax_local"]) != 0.0:
                rate = float(row["withholding_tax_local"]) / gross_local
            observed_by_market[market].append(rate)

        if has_unknown_legacy_dividend and any(value != 0.0 for value in expected.values()):
            raise ValueError(
                "legacy dividend withholding assumptions cannot be verified for this paper ledger"
            )
        for market, rates in observed_by_market.items():
            if any(abs(rate - expected[market]) > 1e-12 for rate in rates):
                raise ValueError(
                    "dividend withholding assumptions do not match existing dividend history"
                )

        self._set_meta("dividend_withholding", expected)
        if commit:
            self.connection.commit()

    def _record_corporate_action(self, event: object, realized_pnl_delta: float) -> None:
        self.connection.execute(
            "INSERT INTO corporate_actions(timestamp, symbol, action, quantity_before, quantity_after, "
            "ratio_or_amount, cash_value, cash_value_local, local_currency, fx_to_base, "
            "gross_cash_value, gross_cash_value_local, withholding_tax, withholding_tax_local, "
            "withholding_rate, cash_in_lieu_price, cash_in_lieu_price_source, "
            "fractional_quantity, cash_in_lieu_settlement_date, realized_pnl_delta) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pd.Timestamp(event.timestamp).isoformat(),
                event.symbol,
                event.action,
                event.quantity_before,
                event.quantity_after,
                event.ratio_or_amount,
                event.cash_value,
                event.cash_value_local,
                event.local_currency,
                event.fx_to_base,
                event.gross_cash_value,
                event.gross_cash_value_local,
                event.withholding_tax,
                event.withholding_tax_local,
                event.withholding_rate,
                event.cash_in_lieu_price,
                event.cash_in_lieu_price_source,
                event.fractional_quantity,
                event.cash_in_lieu_settlement_date,
                realized_pnl_delta,
            ),
        )

    def _open_receivable_rows(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM cash_in_lieu_receivables "
            "WHERE status='OPEN' ORDER BY settlement_date, receivable_id"
        ).fetchall()

    def _mark_open_receivables(
        self,
        prices: pd.Series,
        fx_to_base: pd.Series | None = None,
        currency_codes: pd.Series | None = None,
    ) -> tuple[float, float]:
        rows = self._open_receivable_rows()
        receivables = [
            CashInLieuReceivable(
                symbol=str(row["symbol"]),
                fractional_quantity=float(row["fractional_quantity"]),
                settlement_date=pd.Timestamp(row["settlement_date"]),
                local_currency=str(row["local_currency"]),
            )
            for row in rows
        ]
        value = mark_cash_in_lieu_receivables(
            receivables,
            prices,
            fx_to_base,
            currency_codes,
        )
        cost_basis = sum(float(row["cost_basis_base"]) for row in rows)
        return float(value), float(value - cost_basis)

    def process_cash_in_lieu_settlements(
        self,
        timestamp: pd.Timestamp,
        settlement_prices: pd.Series | None,
        fx_to_base: pd.Series | None = None,
        currency_codes: pd.Series | None = None,
        *,
        commit: bool = True,
    ) -> int:
        timestamp = pd.Timestamp(timestamp)
        rows = self._open_receivable_rows()
        overdue = [
            row for row in rows if pd.Timestamp(row["settlement_date"]) < timestamp
        ]
        if overdue:
            raise ValueError(
                "cash-in-lieu receivable settlement date was skipped in persistent replay"
            )
        due = [
            row for row in rows if pd.Timestamp(row["settlement_date"]) == timestamp
        ]
        if not due:
            return 0

        state = self.portfolio_state()
        processed = 0
        for row in due:
            pending = [
                CashInLieuReceivable(
                    symbol=str(row["symbol"]),
                    fractional_quantity=float(row["fractional_quantity"]),
                    settlement_date=timestamp,
                    local_currency=str(row["local_currency"]),
                )
            ]
            events = settle_cash_in_lieu_receivables(
                state,
                pending,
                timestamp,
                settlement_prices,
                fx_to_base,
                currency_codes,
            )
            event = events[0]
            position = self._position_row(event.symbol)
            prior_realized = (
                float(position["realized_pnl_base"]) if position is not None else 0.0
            )
            realized_delta = event.cash_value - float(row["cost_basis_base"])
            if position is None:
                self.connection.execute(
                    "INSERT INTO positions(symbol, quantity, avg_cost_base, realized_pnl_base) "
                    "VALUES(?, 0, 0, ?)",
                    (event.symbol, float(realized_delta)),
                )
            else:
                self.connection.execute(
                    "UPDATE positions SET realized_pnl_base=? WHERE symbol=?",
                    (float(prior_realized + realized_delta), event.symbol),
                )
            self._record_corporate_action(event, realized_delta)
            self.connection.execute(
                "UPDATE cash_in_lieu_receivables SET status='SETTLED', settled_at=?, "
                "settlement_price=?, settlement_fx_to_base=?, cash_value=?, "
                "realized_pnl_delta=? WHERE receivable_id=?",
                (
                    timestamp.isoformat(),
                    event.cash_in_lieu_price,
                    event.fx_to_base,
                    event.cash_value,
                    realized_delta,
                    int(row["receivable_id"]),
                ),
            )
            processed += 1

        self._set_meta("cash", float(state.cash))
        if commit:
            self.connection.commit()
        return processed

    def _rebase_open_orders_for_split(self, symbol: str, ratio: float) -> None:
        orders = self.connection.execute(
            "SELECT order_id, requested_qty, remaining_qty FROM orders "
            "WHERE symbol=? AND status IN ('NEW','PARTIAL')",
            (symbol,),
        ).fetchall()
        for order in orders:
            requested = max(int(order["requested_qty"] * ratio), 0)
            remaining = max(int(order["remaining_qty"] * ratio), 0)
            status = "FILLED" if remaining == 0 else ("PARTIAL" if requested != remaining else "NEW")
            self.connection.execute(
                "UPDATE orders SET requested_qty=?, remaining_qty=?, status=? WHERE order_id=?",
                (requested, remaining, status, int(order["order_id"])),
            )

    def process_corporate_actions(
        self,
        timestamp: pd.Timestamp,
        stock_splits: pd.Series,
        dividends: pd.Series,
        raw_open_prices: pd.Series,
        fx_to_base: pd.Series | None = None,
        currency_codes: pd.Series | None = None,
        market_codes: pd.Series | None = None,
        dividend_withholding: DividendWithholdingConfig | None = None,
        cash_in_lieu_prices: pd.Series | None = None,
        cash_in_lieu_settlement_dates: pd.Series | None = None,
        *,
        commit: bool = True,
    ) -> int:
        """Apply raw-basis corporate actions before terminal events and open-order execution."""

        tax_config = dividend_withholding or DividendWithholdingConfig()
        self.ensure_dividend_withholding(tax_config, commit=commit)
        state = self.portfolio_state()
        processed = 0
        new_receivables: list[CashInLieuReceivable] = []
        split_events = apply_stock_split_events(
            state,
            stock_splits,
            raw_open_prices,
            pd.Timestamp(timestamp),
            fx_to_base,
            currency_codes,
            cash_in_lieu_prices,
            cash_in_lieu_settlement_dates,
            new_receivables,
        )
        for symbol, ratio_value in stock_splits.astype(float).items():
            ratio = float(ratio_value)
            if pd.notna(ratio) and ratio > 0.0 and abs(ratio - 1.0) > 1e-12:
                self._rebase_open_orders_for_split(symbol, ratio)
        for event in split_events:
            row = self._position_row(event.symbol)
            prior_avg = float(row["avg_cost_base"]) if row is not None else 0.0
            prior_realized = float(row["realized_pnl_base"]) if row is not None else 0.0
            post_split_avg = prior_avg / event.ratio_or_amount
            position_avg = post_split_avg if event.quantity_after > 0 else 0.0
            fractional_basis = event.fractional_quantity * post_split_avg
            if event.cash_in_lieu_price_source == "pending_settlement":
                realized_delta = 0.0
                self.connection.execute(
                    "INSERT INTO cash_in_lieu_receivables("
                    "symbol, created_at, fractional_quantity, settlement_date, "
                    "local_currency, cost_basis_base, status"
                    ") VALUES(?, ?, ?, ?, ?, ?, 'OPEN')",
                    (
                        event.symbol,
                        pd.Timestamp(timestamp).isoformat(),
                        event.fractional_quantity,
                        event.cash_in_lieu_settlement_date,
                        event.local_currency,
                        float(fractional_basis),
                    ),
                )
            else:
                realized_delta = event.cash_value - fractional_basis
            self.connection.execute(
                "INSERT INTO positions(symbol, quantity, avg_cost_base, realized_pnl_base) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET "
                "quantity=excluded.quantity, avg_cost_base=excluded.avg_cost_base, "
                "realized_pnl_base=excluded.realized_pnl_base",
                (
                    event.symbol,
                    event.quantity_after,
                    float(position_avg),
                    float(prior_realized + realized_delta),
                ),
            )
            self._record_corporate_action(event, realized_delta)
            processed += 1

        dividend_events = apply_cash_dividend_events(
            state,
            dividends,
            pd.Timestamp(timestamp),
            fx_to_base,
            currency_codes,
            market_codes,
            tax_config,
        )
        for event in dividend_events:
            row = self._position_row(event.symbol)
            prior_avg = float(row["avg_cost_base"]) if row is not None else 0.0
            prior_realized = float(row["realized_pnl_base"]) if row is not None else 0.0
            self.connection.execute(
                "INSERT INTO positions(symbol, quantity, avg_cost_base, realized_pnl_base) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET "
                "quantity=excluded.quantity, avg_cost_base=excluded.avg_cost_base, "
                "realized_pnl_base=excluded.realized_pnl_base",
                (
                    event.symbol,
                    event.quantity_after,
                    prior_avg,
                    float(prior_realized + event.cash_value),
                ),
            )
            self._record_corporate_action(event, event.cash_value)
            processed += 1
        self._set_meta("cash", float(state.cash))
        if commit:
            self.connection.commit()
        return processed

    def process_terminal_returns(
        self,
        timestamp: pd.Timestamp,
        terminal_returns: pd.Series,
        reference_prices: pd.Series,
        fx_to_base: pd.Series | None = None,
        currency_codes: pd.Series | None = None,
        *,
        commit: bool = True,
    ) -> int:
        state = self.portfolio_state()
        events = apply_terminal_returns(
            state,
            terminal_returns,
            reference_prices,
            pd.Timestamp(timestamp),
            fx_to_base,
            currency_codes,
        )
        for event in events:
            row = self._position_row(event.symbol)
            prior_avg = float(row["avg_cost_base"]) if row is not None else 0.0
            prior_realized = float(row["realized_pnl_base"]) if row is not None else 0.0
            realized_delta = event.proceeds - prior_avg * event.quantity
            self.connection.execute(
                "INSERT INTO positions(symbol, quantity, avg_cost_base, realized_pnl_base) VALUES(?, 0, 0, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET quantity=0, avg_cost_base=0, "
                "realized_pnl_base=excluded.realized_pnl_base",
                (event.symbol, prior_realized + realized_delta),
            )
            self.connection.execute(
                "UPDATE orders SET status='CANCELLED_TERMINAL' "
                "WHERE symbol=? AND status IN ('NEW','PARTIAL')",
                (event.symbol,),
            )
            self.connection.execute(
                "INSERT INTO terminal_events(timestamp, symbol, quantity, reference_price, terminal_return, "
                "proceeds, realized_pnl_base) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    pd.Timestamp(timestamp).isoformat(),
                    event.symbol,
                    event.quantity,
                    event.reference_price,
                    event.terminal_return,
                    event.proceeds,
                    realized_delta,
                ),
            )
        self._set_meta("cash", float(state.cash))
        if commit:
            self.connection.commit()
        return len(events)

    def mark_close(
        self,
        timestamp: pd.Timestamp,
        close_prices: pd.Series,
        fx_to_base: pd.Series | None = None,
        benchmark_close_base: float | None = None,
        currency_codes: pd.Series | None = None,
        *,
        commit: bool = True,
    ) -> dict[str, float]:
        state = self.portfolio_state()
        positions = self.connection.execute(
            "SELECT symbol, quantity, avg_cost_base, realized_pnl_base FROM positions"
        ).fetchall()
        market_value = 0.0
        unrealized = 0.0
        realized = 0.0
        for row in positions:
            symbol = str(row["symbol"])
            quantity = int(row["quantity"])
            realized += float(row["realized_pnl_base"])
            if quantity == 0:
                continue
            price = float(close_prices.get(symbol, float("nan")))
            factor = 1.0 if fx_to_base is None else float(fx_to_base.get(symbol, float("nan")))
            if not pd.notna(price) or price <= 0.0 or not pd.notna(factor) or factor <= 0.0:
                raise ValueError(f"missing close/FX mark for held symbol {symbol}")
            price_base = price * factor
            value = quantity * price_base
            position_unrealized = quantity * (price_base - float(row["avg_cost_base"]))
            market_value += value
            unrealized += position_unrealized
            self.connection.execute(
                "INSERT OR REPLACE INTO position_marks(timestamp, symbol, quantity, avg_cost_base, close_price, "
                "fx_to_base, market_value_base, unrealized_pnl_base) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pd.Timestamp(timestamp).isoformat(),
                    symbol,
                    quantity,
                    float(row["avg_cost_base"]),
                    price,
                    factor,
                    value,
                    position_unrealized,
                ),
            )

        receivable_value, receivable_unrealized = self._mark_open_receivables(
            close_prices,
            fx_to_base,
            currency_codes,
        )
        unrealized += receivable_unrealized
        state.receivable_value = receivable_value
        equity = self.cash + market_value + receivable_value
        interest_row = self.connection.execute(
            "SELECT interest_base FROM cash_interest_credits WHERE timestamp=?",
            (pd.Timestamp(timestamp).isoformat(),),
        ).fetchone()
        cash_interest = 0.0 if interest_row is None else float(interest_row["interest_base"])
        cumulative_cash_interest = float(
            self.connection.execute(
                "SELECT COALESCE(SUM(interest_base), 0) AS value "
                "FROM cash_interest_credits WHERE timestamp<=?",
                (pd.Timestamp(timestamp).isoformat(),),
            ).fetchone()["value"]
        )
        realized += cumulative_cash_interest
        fees = float(
            self.connection.execute("SELECT COALESCE(SUM(fees), 0) AS value FROM fills").fetchone()["value"]
        )
        slippage = float(
            self.connection.execute(
                "SELECT COALESCE(SUM(slippage_cost), 0) AS value FROM fills"
            ).fetchone()["value"]
        )
        benchmark_equity: float | None = None
        if benchmark_close_base is not None and pd.notna(benchmark_close_base) and benchmark_close_base > 0.0:
            units = self._meta_value("benchmark_units")
            if units is None:
                units = self.initial_cash / float(benchmark_close_base)
                self._set_meta("benchmark_units", float(units))
            benchmark_equity = float(units) * float(benchmark_close_base)

        factors = (
            fx_to_base.reindex(close_prices.index).fillna(1.0)
            if fx_to_base is not None
            else pd.Series(1.0, index=close_prices.index)
        )
        state_equity = state.equity(close_prices, factors)
        reconciliation_error = state_equity - equity
        self.connection.execute(
            "INSERT OR REPLACE INTO nav(timestamp, cash, market_value, receivable_value, equity, "
            "cash_interest, cumulative_cash_interest, realized_pnl, unrealized_pnl, "
            "cumulative_fees, cumulative_slippage, benchmark_close_base, "
            "benchmark_equity, reconciliation_error) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pd.Timestamp(timestamp).isoformat(),
                self.cash,
                market_value,
                receivable_value,
                equity,
                cash_interest,
                cumulative_cash_interest,
                realized,
                unrealized,
                fees,
                slippage,
                benchmark_close_base,
                benchmark_equity,
                reconciliation_error,
            ),
        )
        if commit:
            self.connection.commit()
        return {
            "cash": self.cash,
            "market_value": market_value,
            "receivable_value": receivable_value,
            "equity": equity,
            "cash_interest": cash_interest,
            "cumulative_cash_interest": cumulative_cash_interest,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "benchmark_equity": float("nan") if benchmark_equity is None else benchmark_equity,
            "reconciliation_error": reconciliation_error,
        }

    def record_snapshot(
        self,
        timestamp: pd.Timestamp,
        data: MarketData,
        snapshot_root: str | Path,
        *,
        commit: bool = True,
    ) -> SnapshotManifest:
        day = pd.Timestamp(timestamp)
        directory = Path(snapshot_root) / day.strftime("%Y-%m-%d")
        manifest = save_market_data_snapshot(data.slice(day, day), directory, overwrite=True)
        self.connection.execute(
            "INSERT OR REPLACE INTO snapshots(timestamp, dataset_id, path) VALUES(?, ?, ?)",
            (day.isoformat(), manifest.dataset_id, str(directory)),
        )
        if commit:
            self.connection.commit()
        return manifest


def replay_targets_persistently(
    data: MarketData,
    target_weights: pd.DataFrame,
    config: BacktestConfig,
    ledger_path: str | Path,
    snapshot_root: str | Path | None = None,
    benchmark_close_base: pd.Series | None = None,
    reset: bool = True,
) -> PaperLedger:
    """Replay signal-date targets through a persistent ledger with retryable partial orders."""

    if target_weights.empty:
        raise ValueError("target_weights cannot be empty")
    if not target_weights.index.is_unique or not data.close.index.is_unique:
        raise ValueError("persistent replay requires unique session and target timestamps")
    if not data.close.columns.is_unique:
        raise ValueError("persistent replay requires unique symbol identifiers")
    required_metadata = data.membership.fillna(False) | data.terminal_returns.notna()
    if data.market_codes is not None and bool(
        (required_metadata & data.market_codes.isna()).any().any()
    ):
        raise ValueError("market_codes missing for active/terminal asset cells")
    if data.currency_codes is not None:
        if bool((required_metadata & data.currency_codes.isna()).any().any()):
            raise ValueError("currency_codes missing for active/terminal asset cells")
        observed_currencies = set(data.currency_codes.stack().astype(str))
    else:
        observed_currencies = {currency_for_symbol(symbol) for symbol in data.symbols}

    base_currency = config.base_currency or data.base_currency
    if base_currency is None:
        base_currency = "USD" if observed_currencies == {"USD"} else "TWD"
    base_currency = base_currency.upper()
    if data.fx_to_base is None:
        if any(currency != base_currency for currency in observed_currencies):
            raise ValueError("persistent replay requires attached FX for cross-currency assets")
    else:
        if data.base_currency is None or data.base_currency.upper() != base_currency:
            raise ValueError("persistent replay base currency does not match attached FX data")
        if not validate_fx(data, config.max_fx_staleness_days).is_valid:
            raise ValueError("attached FX conversion factors failed validation")

    ledger = PaperLedger(
        ledger_path,
        initial_cash=config.initial_cash,
        base_currency=base_currency,
        reset=reset,
    )
    try:
        if not math.isclose(
            ledger.initial_cash, config.initial_cash, rel_tol=0.0, abs_tol=1e-8
        ):
            raise ValueError("initial_cash does not match the existing paper ledger")
        ledger.ensure_cash_annual_yield(config.cash_annual_yield)
        ledger.ensure_execution_price_basis(config.execution_price_basis)
        if config.execution_price_basis == "raw":
            ledger.ensure_dividend_withholding(config.dividend_withholding)
    except Exception:
        ledger.close()
        raise
    if config.execution_price_basis == "raw":
        if data.raw_open is None or data.raw_close is None:
            ledger.close()
            raise ValueError("raw persistent replay requires raw_open/raw_close")
        execution_open = data.raw_open
        valuation_close = data.raw_close
        execution_reference = valuation_close.shift(1)
    elif config.execution_price_basis == "adjusted":
        execution_open = data.open
        valuation_close = data.close
        execution_reference = data.reference
    else:
        ledger.close()
        raise ValueError("execution_price_basis must be 'adjusted' or 'raw'")
    execution_reference = transition_safe_reference(
        execution_reference,
        data.market_codes,
        data.currency_codes,
    )
    try:
        first_signal = pd.Timestamp(target_weights.index.min())
        pending_row = ledger.connection.execute(
            "SELECT MIN(settlement_date) AS value FROM cash_in_lieu_receivables "
            "WHERE status='OPEN'"
        ).fetchone()
        pending_date = (
            None
            if pending_row is None or pending_row["value"] is None
            else pd.Timestamp(pending_row["value"])
        )
        replay_start = first_signal if pending_date is None else min(first_signal, pending_date)
        completed_at = ledger.verify_completed_sessions(
            data,
            target_weights,
            execution_reference=execution_reference,
            benchmark_close_base=benchmark_close_base,
        )
        if completed_at is None:
            dates = data.close.index[data.close.index >= replay_start]
        else:
            dates = data.close.index[data.close.index > completed_at]
        for timestamp in dates:
            ledger.ensure_replay_session_is_restartable(timestamp)
            target_weights_today = (
                target_weights.loc[timestamp].reindex(data.symbols).fillna(0.0)
                if timestamp in target_weights.index
                else None
            )
            benchmark_value = (
                None
                if benchmark_close_base is None or timestamp not in benchmark_close_base.index
                else float(benchmark_close_base.loc[timestamp])
            )
            data_fingerprint = replay_session_data_fingerprint(
                data, timestamp, execution_reference.loc[timestamp], benchmark_value
            )
            with ledger.connection:
                ledger.accrue_cash_interest(timestamp, commit=False)
                fx = data.fx_to_base.loc[timestamp] if data.fx_to_base is not None else None
                market_codes = (
                    data.market_codes.loc[timestamp] if data.market_codes is not None else None
                )
                currency_codes = (
                    data.currency_codes.loc[timestamp] if data.currency_codes is not None else None
                )
                if config.execution_price_basis == "raw":
                    settlement_prices = (
                        data.cash_in_lieu_prices.loc[timestamp]
                        if data.cash_in_lieu_prices is not None
                        else None
                    )
                    ledger.process_cash_in_lieu_settlements(
                        timestamp,
                        settlement_prices,
                        fx,
                        currency_codes,
                        commit=False,
                    )
                    ledger.process_corporate_actions(
                        timestamp,
                        data.stock_splits.loc[timestamp],
                        data.dividends.loc[timestamp],
                        execution_open.loc[timestamp],
                        fx,
                        currency_codes,
                        market_codes,
                        config.dividend_withholding,
                        settlement_prices,
                        (
                            data.cash_in_lieu_settlement_dates.loc[timestamp]
                            if data.cash_in_lieu_settlement_dates is not None
                            else None
                        ),
                        commit=False,
                    )
                ledger.process_terminal_returns(
                    timestamp,
                    data.terminal_returns.loc[timestamp],
                    execution_reference.loc[timestamp],
                    fx,
                    currency_codes,
                    commit=False,
                )
                ledger.process_open(
                    timestamp,
                    execution_open.loc[timestamp],
                    data.volume.loc[timestamp],
                    execution_reference.loc[timestamp],
                    config,
                    fx,
                    market_codes,
                    currency_codes,
                    commit=False,
                )
                ledger.mark_close(
                    timestamp,
                    valuation_close.loc[timestamp],
                    fx,
                    benchmark_value,
                    currency_codes,
                    commit=False,
                )
                if snapshot_root is not None:
                    ledger.record_snapshot(timestamp, data, snapshot_root, commit=False)
                if target_weights_today is not None:
                    ledger.submit_target_orders(
                        timestamp,
                        target_weights_today,
                        valuation_close.loc[timestamp],
                        config,
                        fx,
                        market_codes,
                        currency_codes,
                        commit=False,
                    )
                ledger.record_session_commit(
                    timestamp, target_weights_today, data_fingerprint=data_fingerprint
                )
        return ledger
    except BaseException:
        ledger.close()
        raise
