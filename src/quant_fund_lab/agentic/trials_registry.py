"""SQLite persistence for the global trial counter N, Empirical Bayes shrinkage, and DSR hurdle tracking."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import numpy as np
from scipy.stats import norm

EULER_MASCHERONI: float = 0.5772156649
KAPPA_0: float = 10.0
SIGMA_PRIOR_SQ: float = 0.25
SHARPE_CLIP_MIN: float = -1.5
SHARPE_CLIP_MAX: float = 3.5

TRIAL_COLUMNS: tuple[str, ...] = (
    "trial_id", "market_universe", "is_start_date", "is_end_date",
    "lineage_id", "round_num", "strategy_name", "contract_json", "ast_hash",
    "net_sharpe", "winsorized_sharpe", "gross_sharpe",
    "bootstrap_p05", "bootstrap_p25", "bootstrap_p50",
    "max_drawdown_pct", "turnover", "fitness_j", "dsr", "created_at",
)


class TrialsRegistry:
    """Registry managing trial history, Empirical Bayes variance shrinkage, and DSR hurdles."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = Path(db_path) if isinstance(db_path, str) and db_path != ":memory:" else db_path
        if str(self.db_path) != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        else:
            self._conn = sqlite3.connect(":memory:", isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Create evolution_trials table and lookup indices."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_trials (
                trial_id TEXT PRIMARY KEY, market_universe TEXT NOT NULL,
                is_start_date TEXT NOT NULL, is_end_date TEXT NOT NULL,
                lineage_id TEXT NOT NULL, round_num INTEGER NOT NULL,
                strategy_name TEXT NOT NULL, contract_json TEXT NOT NULL,
                ast_hash TEXT NOT NULL, net_sharpe REAL NOT NULL,
                winsorized_sharpe REAL NOT NULL, gross_sharpe REAL NOT NULL,
                bootstrap_p05 REAL NOT NULL, bootstrap_p25 REAL NOT NULL,
                bootstrap_p50 REAL NOT NULL, max_drawdown_pct REAL NOT NULL,
                turnover REAL NOT NULL, fitness_j REAL NOT NULL,
                dsr REAL NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_trials_univ_dates "
            "ON evolution_trials (market_universe, is_start_date, is_end_date);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_trials_lineage "
            "ON evolution_trials (lineage_id, round_num);"
        )

    def close(self) -> None:
        """Close SQLite database connection."""
        if self._conn:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def get_universe_stats(
        self, universe: str, is_start: str, is_end: str
    ) -> tuple[int, float, float]:
        """Compute trial count N, Empirical Bayes posterior variance V_post, and expected null max Sharpe SR0."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT net_sharpe FROM evolution_trials "
            "WHERE market_universe = ? AND is_start_date = ? AND is_end_date = ?",
            (universe, is_start, is_end),
        )
        rows = cursor.fetchall()
        n = len(rows)
        if n == 0:
            return (0, SIGMA_PRIOR_SQ, float(0.50 * 1.5388))

        raw_sharpes = np.array([r["net_sharpe"] for r in rows], dtype=float)
        winsorized = np.clip(raw_sharpes, SHARPE_CLIP_MIN, SHARPE_CLIP_MAX)
        s_n_sq = float(np.var(winsorized, ddof=1)) if n >= 2 else 0.0
        v_post = SIGMA_PRIOR_SQ if n <= 1 else (KAPPA_0 * SIGMA_PRIOR_SQ + (n - 1) * s_n_sq) / (KAPPA_0 + n - 1)

        n_eff = max(n, 10)
        extreme = (
            (1.0 - EULER_MASCHERONI) * norm.ppf(1.0 - 1.0 / n_eff)
            + EULER_MASCHERONI * norm.ppf(1.0 - 1.0 / (n_eff * np.e))
        )
        sr0 = float(np.sqrt(v_post) * extreme)
        return (n, float(v_post), sr0)

    def record_trial(
        self,
        market_universe: str | dict[str, Any] = "",
        is_start_date: str = "",
        is_end_date: str = "",
        lineage_id: str = "",
        round_num: int = 0,
        strategy_name: str = "",
        contract_json: str = "{}",
        ast_hash: str = "",
        net_sharpe: float = 0.0,
        gross_sharpe: float = 0.0,
        bootstrap_p05: float = 0.0,
        bootstrap_p25: float = 0.0,
        bootstrap_p50: float = 0.0,
        max_drawdown_pct: float = 0.0,
        turnover: float = 0.0,
        fitness_j: float = 0.0,
        dsr: float = 0.0,
        *,
        winsorized_sharpe: float | None = None,
        created_at: str | None = None,
        trial_id: str | None = None,
        failure_note: str | None = None,
        **extra_kwargs: Any,
    ) -> str:
        """Insert trial record into evolution_trials and return trial_id."""
        if isinstance(market_universe, dict):
            d = dict(market_universe)
            d.update(extra_kwargs)
        else:
            d = {
                "market_universe": market_universe, "is_start_date": is_start_date,
                "is_end_date": is_end_date, "lineage_id": lineage_id, "round_num": round_num,
                "strategy_name": strategy_name, "contract_json": contract_json, "ast_hash": ast_hash,
                "net_sharpe": net_sharpe, "gross_sharpe": gross_sharpe,
                "bootstrap_p05": bootstrap_p05, "bootstrap_p25": bootstrap_p25,
                "bootstrap_p50": bootstrap_p50, "max_drawdown_pct": max_drawdown_pct,
                "turnover": turnover, "fitness_j": fitness_j, "dsr": dsr,
                "winsorized_sharpe": winsorized_sharpe, "created_at": created_at,
                "trial_id": trial_id, "failure_note": failure_note,
            }
            d.update(extra_kwargs)

        t_id = str(d.get("trial_id") or f"trial_{uuid.uuid4().hex[:12]}")
        net_s = float(d.get("net_sharpe", 0.0))
        win_s = float(
            d.get("winsorized_sharpe")
            if d.get("winsorized_sharpe") is not None
            else np.clip(net_s, SHARPE_CLIP_MIN, SHARPE_CLIP_MAX)
        )
        c_at = str(d.get("created_at") or datetime.now(timezone.utc).isoformat())
        c_json = str(d.get("contract_json", "{}"))
        note = d.get("failure_note")
        if note:
            try:
                cj = json.loads(c_json)
                if isinstance(cj, dict):
                    cj["failure_note"] = note
                    c_json = json.dumps(cj)
            except (json.JSONDecodeError, TypeError):
                pass

        row = (
            t_id, str(d.get("market_universe", "")), str(d.get("is_start_date", "")),
            str(d.get("is_end_date", "")), str(d.get("lineage_id", "")), int(d.get("round_num", 0)),
            str(d.get("strategy_name", "")), c_json, str(d.get("ast_hash", "")),
            net_s, win_s, float(d.get("gross_sharpe", 0.0)),
            float(d.get("bootstrap_p05", 0.0)), float(d.get("bootstrap_p25", 0.0)),
            float(d.get("bootstrap_p50", 0.0)), float(d.get("max_drawdown_pct", 0.0)),
            float(d.get("turnover", 0.0)), float(d.get("fitness_j", 0.0)),
            float(d.get("dsr", 0.0)), c_at,
        )
        cols = ", ".join(TRIAL_COLUMNS)
        placeholders = ", ".join(["?"] * len(TRIAL_COLUMNS))
        self._conn.cursor().execute(f"INSERT INTO evolution_trials ({cols}) VALUES ({placeholders})", row)
        return t_id

    def get_lineage_history(self, lineage_id: str) -> list[dict[str, Any]]:
        """Retrieve all rounds for a lineage ordered by round_num ascending."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM evolution_trials WHERE lineage_id = ? ORDER BY round_num ASC",
            (lineage_id,),
        )
        records: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            d = dict(row)
            note = ""
            try:
                cj = json.loads(d.get("contract_json", "{}"))
                if isinstance(cj, dict):
                    note = str(cj.get("failure_note") or cj.get("note") or cj.get("critique") or "")
            except (json.JSONDecodeError, TypeError):
                pass
            if not note:
                if d.get("dsr", 1.0) < 0.5:
                    note = f"DSR {d.get('dsr', 0.0):.2f} < 0.50"
                elif d.get("bootstrap_p05", 1.0) < 0.0:
                    note = "Bootstrap p05 < 0"
                elif d.get("net_sharpe", 1.0) < 0.0:
                    note = "Net Sharpe < 0"
                else:
                    note = "-"
            d["failure_note"] = note
            records.append(d)
        return records

    def count_trials(self) -> int:
        """Count total trials recorded in the registry."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM evolution_trials")
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def format_lineage_markdown_table(self, lineage_id: str) -> str:
        """Produce compact Markdown table for reflection prompt."""
        history = self.get_lineage_history(lineage_id)
        headers = [
            "Round", "Strategy Name", "Net Sharpe", "DSR",
            "Fitness J", "Max DD%", "Turnover", "Failure / Note",
        ]
        lines = [f"| {' | '.join(headers)} |", f"| {' | '.join(['---'] * len(headers))} |"]
        if not history:
            return "\n".join(lines)

        for r in history:
            rnd = r.get("round_num", 0)
            strat = r.get("strategy_name", "")
            net_sr = f"{r.get('net_sharpe', 0.0):.2f}"
            dsr_val = f"{r.get('dsr', 0.0):.2f}"
            fit_j = f"{r.get('fitness_j', 0.0):.2f}"
            dd = r.get("max_drawdown_pct", 0.0)
            pct = dd * 100.0 if abs(dd) <= 1.0 and dd != 0.0 else dd
            turnover_str = f"{r.get('turnover', 0.0):.2f}"
            note = r.get("failure_note", "-").replace("\n", " ").strip() or "-"
            lines.append(f"| {rnd} | {strat} | {net_sr} | {dsr_val} | {fit_j} | {pct:.1f}% | {turnover_str} | {note} |")
        return "\n".join(lines)
