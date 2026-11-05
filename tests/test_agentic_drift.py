"""Tests for live drift monitoring and automated retirement triggers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_fund_lab.agentic.drift_monitor import (
    DriftReport,
    audit_ensemble_drift,
    check_strategy_drift,
    compute_rolling_sharpe,
)


def test_compute_rolling_sharpe_short_or_constant() -> None:
    # Insufficient length
    short_returns = pd.Series([0.01, -0.01, 0.02])
    assert compute_rolling_sharpe(short_returns, window=60) == 0.0

    # Constant return (zero std)
    constant_returns = np.full(60, 0.01)
    assert compute_rolling_sharpe(constant_returns, window=60) == 0.0


def test_compute_rolling_sharpe_positive_and_negative() -> None:
    rng = np.random.default_rng(42)
    # Generate positive drift series
    pos_ret = rng.normal(loc=0.01, scale=0.005, size=100)
    sharpe_pos = compute_rolling_sharpe(pos_ret, window=60)
    assert sharpe_pos > 0.0

    # Generate negative drift series
    neg_ret = rng.normal(loc=-0.01, scale=0.005, size=100)
    sharpe_neg = compute_rolling_sharpe(neg_ret, window=60)
    assert sharpe_neg < 0.0


def test_check_strategy_drift_statuses() -> None:
    # Set bootstrap thresholds
    p01 = -0.50
    p05 = 0.20

    # Healthy scenario (Sharpe >= p05)
    healthy_ret = np.full(60, 0.002)
    # Add slight variation so std > 0
    healthy_ret[0] = 0.001
    healthy_ret[1] = 0.003
    rep_healthy = check_strategy_drift(
        "trend_alpha",
        healthy_ret,
        bootstrap_p01=p01,
        bootstrap_p05=p05,
        window=60,
        as_of_date="2026-06-01",
    )
    assert isinstance(rep_healthy, DriftReport)
    assert rep_healthy.status == "HEALTHY"
    assert rep_healthy.rolling_sharpe_60d >= p05

    # Warning scenario (p01 <= Sharpe < p05)
    warning_ret = np.full(60, 0.0001)
    warning_ret[::2] = -0.0001
    warning_ret[0] = 0.001
    warning_ret[1] = -0.001
    rep_warn = check_strategy_drift(
        "mean_rev_alpha",
        warning_ret,
        bootstrap_p01=-1.0,
        bootstrap_p05=1.5,
        window=60,
    )
    assert rep_warn.status == "WARNING"

    # Retire scenario (Sharpe < p01)
    retire_ret = np.full(60, -0.005)
    retire_ret[0] = -0.004
    retire_ret[1] = -0.006
    rep_retire = check_strategy_drift(
        "failing_alpha",
        retire_ret,
        bootstrap_p01=0.0,
        bootstrap_p05=0.5,
        window=60,
    )
    assert rep_retire.status == "RETIRE"
    assert "CRITICAL" in rep_retire.message


def test_audit_ensemble_drift() -> None:
    rng = np.random.default_rng(123)
    ensemble = {
        "sleeve_a": rng.normal(0.001, 0.01, 100),
        "sleeve_b": rng.normal(-0.005, 0.01, 100),
    }
    thresholds = {
        "sleeve_a": (-0.2, 0.5),
        "sleeve_b": (0.0, 0.8),
    }

    reports = audit_ensemble_drift(ensemble, thresholds, window=60)
    assert len(reports) == 2
    status_map = {r.strategy_name: r.status for r in reports}
    assert "sleeve_a" in status_map
    assert "sleeve_b" in status_map
    assert status_map["sleeve_b"] == "RETIRE"
