import numpy as np
import pandas as pd

from quant_fund_lab.diagnostics import (
    deflated_sharpe_ratio,
    reality_check_bootstrap,
)


def test_deflated_sharpe_penalizes_wider_trial_search():
    rng = np.random.default_rng(5)
    returns = pd.Series(rng.normal(0.0010, 0.01, size=500))
    tight_trials = pd.Series([0.02, 0.025, 0.03, 0.035])
    wide_trials = pd.Series([-0.10, -0.02, 0.05, 0.15])
    tight = deflated_sharpe_ratio(returns, tight_trials)
    wide = deflated_sharpe_ratio(returns, wide_trials)
    assert wide.expected_max_sharpe_daily > tight.expected_max_sharpe_daily
    assert wide.probability < tight.probability


def test_deflated_sharpe_strong_signal_exceeds_weak_signal():
    rng = np.random.default_rng(6)
    noise = rng.normal(0.0, 0.01, size=600)
    weak = pd.Series(noise + 0.0001)
    strong = pd.Series(noise + 0.0010)
    trials = pd.Series([-0.02, 0.0, 0.02, 0.04, 0.06])
    weak_result = deflated_sharpe_ratio(weak, trials)
    strong_result = deflated_sharpe_ratio(strong, trials)
    assert strong_result.probability > weak_result.probability
    assert strong_result.observed_sharpe_annualized > weak_result.observed_sharpe_annualized


def test_reality_check_is_deterministic_and_detects_strong_candidate():
    rng = np.random.default_rng(7)
    n = 600
    null_matrix = pd.DataFrame(
        rng.normal(0.0, 0.01, size=(n, 4)),
        columns=["a", "b", "c", "d"],
    )
    null_result = reality_check_bootstrap(
        null_matrix, bootstrap_iterations=500, mean_block_length=8, seed=21
    )
    null_repeat = reality_check_bootstrap(
        null_matrix, bootstrap_iterations=500, mean_block_length=8, seed=21
    )
    assert null_result == null_repeat
    assert null_result.p_value > 0.01

    signal_matrix = null_matrix.copy()
    signal_matrix["d"] += 0.0020
    signal_result = reality_check_bootstrap(
        signal_matrix, bootstrap_iterations=500, mean_block_length=8, seed=21
    )
    assert signal_result.best_candidate_id == "d"
    assert signal_result.p_value < 0.05
