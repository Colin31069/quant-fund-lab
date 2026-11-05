"""Unit tests for TrialsRegistry, Empirical Bayes shrinkage, and DSR hurdle tracking."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from quant_fund_lab.agentic.trials_registry import (
    KAPPA_0,
    SHARPE_CLIP_MAX,
    SHARPE_CLIP_MIN,
    SIGMA_PRIOR_SQ,
    TRIAL_COLUMNS,
    TrialsRegistry,
)


def _make_sample_trial_dict(
    lineage_id: str = "lin_1",
    round_num: int = 0,
    strategy_name: str = "kalman_trend_v0",
    net_sharpe: float = 1.25,
    gross_sharpe: float = 1.45,
    dsr: float = 0.85,
    fitness_j: float = 1.10,
    max_drawdown_pct: float = 0.12,
    turnover: float = 1.80,
    market_universe: str = "US_LIQUID_500",
    is_start: str = "2020-01-01",
    is_end: str = "2022-12-31",
    failure_note: str | None = None,
) -> dict[str, object]:
    """Helper creating a valid trial dictionary for insertion."""
    return {
        "market_universe": market_universe,
        "is_start_date": is_start,
        "is_end_date": is_end,
        "lineage_id": lineage_id,
        "round_num": round_num,
        "strategy_name": strategy_name,
        "contract_json": json.dumps({"strategy_name": strategy_name}),
        "ast_hash": "ast_hash_dummy_123",
        "net_sharpe": net_sharpe,
        "gross_sharpe": gross_sharpe,
        "bootstrap_p05": net_sharpe - 0.4,
        "bootstrap_p25": net_sharpe - 0.2,
        "bootstrap_p50": net_sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "turnover": turnover,
        "fitness_j": fitness_j,
        "dsr": dsr,
        "failure_note": failure_note,
    }


def test_table_initialization_and_trial_insertion():
    """Verify table schema, constraints, index creation, and trial insertion."""
    with TrialsRegistry(":memory:") as reg:
        cursor = reg._conn.cursor()
        cursor.execute("PRAGMA table_info(evolution_trials);")
        columns = [row[1] for row in cursor.fetchall()]
        assert set(columns) == set(TRIAL_COLUMNS)
        assert len(columns) == 20

        # Insert trial using keyword args
        t_id = reg.record_trial(
            market_universe="US_LIQUID_500",
            is_start_date="2020-01-01",
            is_end_date="2022-12-31",
            lineage_id="lin_alpha",
            round_num=0,
            strategy_name="trend_v1",
            contract_json='{"name": "trend_v1"}',
            ast_hash="hash_abc",
            net_sharpe=1.5,
            gross_sharpe=1.8,
            bootstrap_p05=0.9,
            bootstrap_p25=1.2,
            bootstrap_p50=1.5,
            max_drawdown_pct=0.10,
            turnover=2.0,
            fitness_j=1.4,
            dsr=0.92,
        )
        assert isinstance(t_id, str)
        assert t_id.startswith("trial_")

        # Verify inserted row
        cursor.execute("SELECT * FROM evolution_trials WHERE trial_id = ?", (t_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["strategy_name"] == "trend_v1"
        assert row["net_sharpe"] == 1.5
        assert row["winsorized_sharpe"] == 1.5

        # Test winsorizing on extreme insertion
        t_id_extreme = reg.record_trial(
            market_universe="US_LIQUID_500",
            is_start_date="2020-01-01",
            is_end_date="2022-12-31",
            lineage_id="lin_alpha",
            round_num=1,
            strategy_name="trend_v2",
            net_sharpe=10.0,
        )
        cursor.execute("SELECT winsorized_sharpe FROM evolution_trials WHERE trial_id = ?", (t_id_extreme,))
        ext_row = cursor.fetchone()
        assert ext_row["winsorized_sharpe"] == SHARPE_CLIP_MAX


def test_file_persistence(tmp_path: Path):
    """Verify that file-backed database persists records across registry instances."""
    db_file = tmp_path / "subdir" / "trials.db"
    with TrialsRegistry(db_file) as reg1:
        reg1.record_trial(_make_sample_trial_dict(lineage_id="lin_persist", round_num=0))

    with TrialsRegistry(db_file) as reg2:
        history = reg2.get_lineage_history("lin_persist")
        assert len(history) == 1
        assert history[0]["round_num"] == 0


def test_cold_start_hurdle_progression():
    """Verify hurdle progression for N=0, 1, 2, 10, 50."""
    with TrialsRegistry(":memory:") as reg:
        univ = "US_LIQUID_500"
        start_d = "2020-01-01"
        end_d = "2022-12-31"

        # N = 0
        n, v_post, sr0 = reg.get_universe_stats(univ, start_d, end_d)
        assert n == 0
        assert v_post == SIGMA_PRIOR_SQ
        assert sr0 == pytest.approx(0.50 * 1.5388, rel=1e-5)

        # N = 1
        reg.record_trial(_make_sample_trial_dict(round_num=0, net_sharpe=1.2))
        n1, v_post1, sr0_1 = reg.get_universe_stats(univ, start_d, end_d)
        assert n1 == 1
        assert v_post1 == SIGMA_PRIOR_SQ
        assert sr0_1 > 0.78  # n_eff = 10, v_post = 0.25 -> ~0.7873

        # N = 2
        reg.record_trial(_make_sample_trial_dict(round_num=1, net_sharpe=1.4))
        n2, v_post2, _sr0_2 = reg.get_universe_stats(univ, start_d, end_d)
        assert n2 == 2
        # Sample variance of [1.2, 1.4] is (0.2)^2 / 2 = 0.02
        expected_s2 = float(np.var([1.2, 1.4], ddof=1))
        expected_v2 = (KAPPA_0 * SIGMA_PRIOR_SQ + 1 * expected_s2) / (KAPPA_0 + 1)
        assert v_post2 == pytest.approx(expected_v2, rel=1e-6)

        # Insert up to N = 10
        for r in range(2, 10):
            reg.record_trial(_make_sample_trial_dict(round_num=r, net_sharpe=1.3))
        n10, v_post10, _sr0_10 = reg.get_universe_stats(univ, start_d, end_d)
        assert n10 == 10
        assert v_post10 > 0.0

        # Insert up to N = 50
        for r in range(10, 50):
            reg.record_trial(_make_sample_trial_dict(round_num=r, net_sharpe=1.3))
        n50, _v_post50, sr0_50 = reg.get_universe_stats(univ, start_d, end_d)
        assert n50 == 50
        assert sr0_50 > 0.0


def test_empirical_bayes_variance_shrinkage_outlier():
    """Verify that Bayesian shrinkage pulls extreme single outliers strongly toward the prior."""
    with TrialsRegistry(":memory:") as reg:
        univ = "TWSE_TOP_150"
        start_d = "2021-01-01"
        end_d = "2023-12-31"

        # Insert two trials with extreme opposite Sharpe values
        reg.record_trial(
            _make_sample_trial_dict(
                market_universe=univ,
                is_start=start_d,
                is_end=end_d,
                round_num=0,
                net_sharpe=-10.0,  # clipped to -1.5
            )
        )
        reg.record_trial(
            _make_sample_trial_dict(
                market_universe=univ,
                is_start=start_d,
                is_end=end_d,
                round_num=1,
                net_sharpe=10.0,  # clipped to +3.5
            )
        )

        n, v_post, _sr0 = reg.get_universe_stats(univ, start_d, end_d)
        assert n == 2

        # Raw sample variance of [-1.5, 3.5] with ddof=1 is 12.5
        raw_s2 = float(np.var([SHARPE_CLIP_MIN, SHARPE_CLIP_MAX], ddof=1))
        assert raw_s2 == pytest.approx(12.5, rel=1e-6)

        # Expected shrunk posterior variance: (10 * 0.25 + 1 * 12.5) / 11 = 15.0 / 11 ~ 1.3636
        expected_v = (KAPPA_0 * SIGMA_PRIOR_SQ + 1 * raw_s2) / (KAPPA_0 + 1)
        assert expected_v == pytest.approx(15.0 / 11.0, rel=1e-6)
        assert v_post == pytest.approx(expected_v, rel=1e-6)

        # Verify shrinkage magnitude: posterior variance is shrunk by >89% relative to raw sample variance!
        assert v_post < raw_s2 * 0.15


def test_lineage_history_retrieval_and_markdown_formatting():
    """Verify lineage ordering, history dictionary content, and markdown report table."""
    with TrialsRegistry(":memory:") as reg:
        # Record rounds out of order
        reg.record_trial(
            _make_sample_trial_dict(
                lineage_id="lin_evo",
                round_num=2,
                strategy_name="trend_v2",
                net_sharpe=1.65,
                dsr=0.91,
                fitness_j=1.45,
                max_drawdown_pct=0.08,
                turnover=2.2,
                failure_note="Promoted to OOS candidate",
            )
        )
        reg.record_trial(
            _make_sample_trial_dict(
                lineage_id="lin_evo",
                round_num=0,
                strategy_name="trend_v0",
                net_sharpe=-0.2,
                dsr=0.10,
                fitness_j=-0.5,
                max_drawdown_pct=0.25,
                turnover=4.5,
                failure_note="Negative Sharpe and high friction",
            )
        )
        reg.record_trial(
            _make_sample_trial_dict(
                lineage_id="lin_evo",
                round_num=1,
                strategy_name="trend_v1",
                net_sharpe=0.85,
                dsr=0.42,
                fitness_j=0.60,
                max_drawdown_pct=0.15,
                turnover=3.1,
            )
        )
        # Record another lineage that should not appear
        reg.record_trial(
            _make_sample_trial_dict(
                lineage_id="lin_other",
                round_num=0,
                strategy_name="other_strat",
            )
        )

        history = reg.get_lineage_history("lin_evo")
        assert len(history) == 3
        assert [h["round_num"] for h in history] == [0, 1, 2]
        assert history[0]["strategy_name"] == "trend_v0"
        assert history[0]["failure_note"] == "Negative Sharpe and high friction"
        assert history[2]["failure_note"] == "Promoted to OOS candidate"

        # Round 1 did not have explicit failure_note, should have auto-inferred note (DSR < 0.50)
        assert "DSR" in history[1]["failure_note"]

        # Generate markdown table
        table = reg.format_lineage_markdown_table("lin_evo")
        lines = table.strip().split("\n")
        assert len(lines) == 5  # header + separator + 3 rows
        assert lines[0] == "| Round | Strategy Name | Net Sharpe | DSR | Fitness J | Max DD% | Turnover | Failure / Note |"
        assert "trend_v0" in lines[2]
        assert "-0.20" in lines[2]
        assert "25.0%" in lines[2]
        assert "trend_v2" in lines[4]
        assert "1.65" in lines[4]
        assert "8.0%" in lines[4]

        # Test empty lineage formatting
        empty_table = reg.format_lineage_markdown_table("non_existent")
        empty_lines = empty_table.strip().split("\n")
        assert len(empty_lines) == 2  # header + separator
