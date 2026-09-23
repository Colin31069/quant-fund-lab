from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from .config import BacktestConfig
from .corporate_actions import apply_cash_dividend_events, apply_stock_split_events
from .data import MarketData
from .execution import (
    Fill,
    PortfolioState,
    apply_terminal_returns,
    desired_quantities,
    execute_market_order,
)
from .snapshot import SnapshotManifest, save_market_data_snapshot

_OPEN_ORDER_STATUSES = ("NEW", "PARTIAL")


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
                fx_to_base REAL NOT NULL,
                realized_pnl_delta REAL NOT NULL
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
                equity REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                cumulative_fees REAL NOT NULL,
                cumulative_slippage REAL NOT NULL,
                benchmark_close_base REAL,
                benchmark_equity REAL,
                reconciliation_error REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                timestamp TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                path TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

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

    def nav_history(self) -> pd.DataFrame:
        frame = pd.read_sql_query("SELECT * FROM nav ORDER BY timestamp", self.connection)
        if not frame.empty:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
            frame = frame.set_index("timestamp")
        return frame

    def snapshots(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM snapshots ORDER BY timestamp", self.connection)

    def cancel_open_orders(self, status: str = "CANCELLED") -> int:
        cursor = self.connection.execute(
            "UPDATE orders SET status = ? WHERE status IN ('NEW', 'PARTIAL')", (status,)
        )
        self.connection.commit()
        return int(cursor.rowcount)

    def submit_target_orders(
        self,
        signal_date: pd.Timestamp,
        target_weights: pd.Series,
        mark_prices: pd.Series,
        config: BacktestConfig,
        fx_to_base: pd.Series | None = None,
    ) -> list[int]:
        """Replace outstanding target orders after the signal-date close."""

        self.cancel_open_orders("CANCELLED_REPLACED")
        state = self.portfolio_state()
        factors = (
            fx_to_base.reindex(target_weights.index).astype(float)
            if fx_to_base is not None
            else pd.Series(1.0, index=target_weights.index, dtype=float)
        )
        desired = desired_quantities(state, target_weights, mark_prices, config, factors)
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
            )
            if fill is None:
                continue
            self._record_fill(int(order["order_id"]), fill)
            fills.append(fill)
        self._set_meta("cash", float(state.cash))
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

    def _record_corporate_action(self, event: object, realized_pnl_delta: float) -> None:
        self.connection.execute(
            "INSERT INTO corporate_actions(timestamp, symbol, action, quantity_before, quantity_after, "
            "ratio_or_amount, cash_value, cash_value_local, fx_to_base, realized_pnl_delta) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pd.Timestamp(event.timestamp).isoformat(),
                event.symbol,
                event.action,
                event.quantity_before,
                event.quantity_after,
                event.ratio_or_amount,
                event.cash_value,
                event.cash_value_local,
                event.fx_to_base,
                realized_pnl_delta,
            ),
        )

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
    ) -> int:
        """Apply raw-basis corporate actions before terminal events and open-order execution."""

        state = self.portfolio_state()
        processed = 0
        split_events = apply_stock_split_events(
            state,
            stock_splits,
            raw_open_prices,
            pd.Timestamp(timestamp),
            fx_to_base,
        )
        for symbol, ratio_value in stock_splits.astype(float).items():
            ratio = float(ratio_value)
            if pd.notna(ratio) and ratio > 0.0 and abs(ratio - 1.0) > 1e-12:
                self._rebase_open_orders_for_split(symbol, ratio)
        for event in split_events:
            row = self._position_row(event.symbol)
            prior_avg = float(row["avg_cost_base"]) if row is not None else 0.0
            prior_realized = float(row["realized_pnl_base"]) if row is not None else 0.0
            new_avg = prior_avg / event.ratio_or_amount if event.quantity_after > 0 else 0.0
            exact_after = event.quantity_before * event.ratio_or_amount
            fractional = max(exact_after - event.quantity_after, 0.0)
            realized_delta = event.cash_value - fractional * new_avg
            self.connection.execute(
                "INSERT INTO positions(symbol, quantity, avg_cost_base, realized_pnl_base) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET "
                "quantity=excluded.quantity, avg_cost_base=excluded.avg_cost_base, "
                "realized_pnl_base=excluded.realized_pnl_base",
                (
                    event.symbol,
                    event.quantity_after,
                    float(new_avg),
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
        self.connection.commit()
        return processed

    def process_terminal_returns(
        self,
        timestamp: pd.Timestamp,
        terminal_returns: pd.Series,
        reference_prices: pd.Series,
        fx_to_base: pd.Series | None = None,
    ) -> int:
        state = self.portfolio_state()
        events = apply_terminal_returns(
            state,
            terminal_returns,
            reference_prices,
            pd.Timestamp(timestamp),
            fx_to_base,
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
        self.connection.commit()
        return len(events)

    def mark_close(
        self,
        timestamp: pd.Timestamp,
        close_prices: pd.Series,
        fx_to_base: pd.Series | None = None,
        benchmark_close_base: float | None = None,
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

        equity = self.cash + market_value
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
            "INSERT OR REPLACE INTO nav(timestamp, cash, market_value, equity, realized_pnl, unrealized_pnl, "
            "cumulative_fees, cumulative_slippage, benchmark_close_base, benchmark_equity, reconciliation_error) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pd.Timestamp(timestamp).isoformat(),
                self.cash,
                market_value,
                equity,
                realized,
                unrealized,
                fees,
                slippage,
                benchmark_close_base,
                benchmark_equity,
                reconciliation_error,
            ),
        )
        self.connection.commit()
        return {
            "cash": self.cash,
            "market_value": market_value,
            "equity": equity,
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
    ) -> SnapshotManifest:
        day = pd.Timestamp(timestamp)
        directory = Path(snapshot_root) / day.strftime("%Y-%m-%d")
        manifest = save_market_data_snapshot(data.slice(day, day), directory, overwrite=True)
        self.connection.execute(
            "INSERT OR REPLACE INTO snapshots(timestamp, dataset_id, path) VALUES(?, ?, ?)",
            (day.isoformat(), manifest.dataset_id, str(directory)),
        )
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
    base_currency = config.base_currency or data.base_currency
    if base_currency is None:
        base_currency = "USD" if all(not s.upper().endswith((".TW", ".TWO")) for s in data.symbols) else "TWD"
    ledger = PaperLedger(
        ledger_path,
        initial_cash=config.initial_cash,
        base_currency=base_currency,
        reset=reset,
    )
    ledger.ensure_execution_price_basis(config.execution_price_basis)
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
    first_signal = pd.Timestamp(target_weights.index.min())
    dates = data.close.index[data.close.index >= first_signal]
    for timestamp in dates:
        fx = data.fx_to_base.loc[timestamp] if data.fx_to_base is not None else None
        if config.execution_price_basis == "raw":
            ledger.process_corporate_actions(
                timestamp,
                data.stock_splits.loc[timestamp],
                data.dividends.loc[timestamp],
                execution_open.loc[timestamp],
                fx,
            )
        ledger.process_terminal_returns(
            timestamp,
            data.terminal_returns.loc[timestamp],
            execution_reference.loc[timestamp],
            fx,
        )
        ledger.process_open(
            timestamp,
            execution_open.loc[timestamp],
            data.volume.loc[timestamp],
            execution_reference.loc[timestamp],
            config,
            fx,
        )
        benchmark_value = None
        if benchmark_close_base is not None and timestamp in benchmark_close_base.index:
            benchmark_value = float(benchmark_close_base.loc[timestamp])
        ledger.mark_close(timestamp, valuation_close.loc[timestamp], fx, benchmark_value)
        if snapshot_root is not None:
            ledger.record_snapshot(timestamp, data, snapshot_root)
        if timestamp in target_weights.index:
            ledger.submit_target_orders(
                timestamp,
                target_weights.loc[timestamp].reindex(data.symbols).fillna(0.0),
                valuation_close.loc[timestamp],
                config,
                fx,
            )
    return ledger
