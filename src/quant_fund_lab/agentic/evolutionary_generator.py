"""Evolutionary Strategy Generator producing 30-round mutation trajectories for trend and mean-reversion."""

from __future__ import annotations

import re

from quant_fund_lab.agentic.schemas import (
    ExecutionOverlayConfig,
    PrimitiveConfig,
    StrategyContract,
)


def _trend_contract(
    round_num: int,
    primitives: list[PrimitiveConfig],
    signal: str,
    regime: str | None,
    overlay: ExecutionOverlayConfig,
    hypothesis: str,
) -> StrategyContract:
    return StrategyContract(
        strategy_name=f"trend_gen{round_num:02d}",
        agent_archetype="trend",
        economic_hypothesis=hypothesis,
        market_universe="US_LIQUID_500",
        primitives=primitives,
        signal_expression=signal,
        regime_gate_expression=regime,
        execution_overlay=overlay,
    )


def _mr_contract(
    round_num: int,
    primitives: list[PrimitiveConfig],
    signal: str,
    regime: str | None,
    overlay: ExecutionOverlayConfig,
    hypothesis: str,
) -> StrategyContract:
    return StrategyContract(
        strategy_name=f"mean_reversion_gen{round_num:02d}",
        agent_archetype="mean_reversion",
        economic_hypothesis=hypothesis,
        market_universe="US_LIQUID_500",
        primitives=primitives,
        signal_expression=signal,
        regime_gate_expression=regime,
        execution_overlay=overlay,
    )


def build_trend_trajectory() -> list[StrategyContract]:
    """Build deterministic 30-round evolutionary trajectory for trend following."""
    p_k15 = PrimitiveConfig(primitive_id="k1", module_type="KalmanTrend", params={"lookback": 15, "half_life": 10})
    p_k21 = PrimitiveConfig(primitive_id="k1", module_type="KalmanTrend", params={"lookback": 21, "half_life": 10})
    p_k30 = PrimitiveConfig(primitive_id="k1", module_type="KalmanTrend", params={"lookback": 30, "half_life": 10})
    p_k30_hl15 = PrimitiveConfig(primitive_id="k1", module_type="KalmanTrend", params={"lookback": 30, "half_life": 15})
    p_rm60 = PrimitiveConfig(primitive_id="res_mom", module_type="ResidualMomentum", params={"lookback": 60})
    p_rm63 = PrimitiveConfig(primitive_id="res_mom", module_type="ResidualMomentum", params={"lookback": 63})
    p_rm126 = PrimitiveConfig(primitive_id="res_mom", module_type="ResidualMomentum", params={"lookback": 126})
    p_vol21 = PrimitiveConfig(primitive_id="vol_stat", module_type="RollingStat", params={"stat": "std", "window": 21, "field": "close"})
    p_vol63 = PrimitiveConfig(primitive_id="vol_stat", module_type="RollingStat", params={"stat": "std", "window": 63, "field": "close"})

    o_base = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.010, max_single_position_weight=0.20, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_b015 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.015, max_single_position_weight=0.20, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_b020 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.020, max_single_position_weight=0.20, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_w18 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.020, max_single_position_weight=0.18, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_lev95 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.020, max_single_position_weight=0.18, target_gross_leverage=0.95, odd_lot_execution_mode="avoid_odd_lots")
    o_b025 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.025, max_single_position_weight=0.18, target_gross_leverage=0.95, odd_lot_execution_mode="avoid_odd_lots")
    o_w16 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.025, max_single_position_weight=0.16, target_gross_leverage=0.95, odd_lot_execution_mode="avoid_odd_lots")

    r_none = "where(vol_21d > 0.0, 1.0, 0.0)"
    r_v85 = "where(mkt_vol_pct_252d <= 0.85, 1.0, 0.5)"
    r_ac05 = "where(mkt_autocorr_21d >= -0.05, 1.0, 0.3)"
    r_v80 = "where(mkt_vol_pct_252d <= 0.80, 1.0, 0.3)"
    r_disp = "where(mkt_disp_pct_252d >= 0.20, 1.0, 0.4)"
    r_v75 = "where(mkt_vol_pct_252d <= 0.75, 1.0, 0.25)"
    r_ac00 = "where(mkt_autocorr_21d >= 0.0, 1.0, 0.35)"

    h_base = "Capturing intermediate price trend continuation via state-space Kalman filter across liquid equities."

    steps = [
        (1, [p_k15], "cs_zscore(k1)", r_none, o_base, h_base),
        (2, [p_k15], "cs_zscore(k1)", r_none, o_b015, h_base + " Widening trade buffer to reduce turnover friction."),
        (3, [p_k15], "cs_rank(k1)", r_none, o_b015, h_base + " Uniform rank normalization to avoid outlier dominance."),
        (4, [p_k21], "cs_rank(k1)", r_none, o_b015, h_base + " Extending Kalman lookback to 21 bars for trend stability."),
        (5, [p_k21], "cs_rank(k1)", r_v85, o_b015, h_base + " Dampening gross exposure during high market volatility regimes."),
        (6, [p_k21], "ts_decay_linear(k1, 5)", r_v85, o_b015, h_base + " Linearly decaying trend momentum to smooth trade entries."),
        (7, [p_k21, p_rm60], "ts_decay_linear(k1, 5)", r_v85, o_b015, h_base + " Introducing residual momentum to capture idiosyncratic alpha."),
        (8, [p_k21, p_rm60], "cs_rank(k1) + cs_rank(res_mom)", r_v85, o_b015, h_base + " Ensembling state-space trend with ranked residual momentum."),
        (9, [p_k21, p_rm60], "cs_rank(k1) + cs_rank(res_mom)", r_ac05, o_b015, h_base + " De-risking during mean-reverting chop regimes with negative autocorrelation."),
        (10, [p_k21, p_rm60], "cs_rank(k1) + cs_rank(res_mom)", r_ac05, o_b020, h_base + " Adjusting trade buffer to 20bps to balance tracking and trading friction."),
        (11, [p_k21, p_rm63], "cs_rank(k1) + cs_rank(res_mom)", r_ac05, o_b020, h_base + " Aligning residual momentum lookback to canonical quarterly 63-bar window."),
        (12, [p_k21, p_rm63], "0.6 * k1 + 0.4 * res_mom", r_ac05, o_b020, h_base + " Applying optimal Bayesian weighting between Kalman filter and residual alpha."),
        (13, [p_k21, p_rm63], "0.6 * k1 + 0.4 * res_mom", r_v80, o_b020, h_base + " Tightening volatility ceiling to 80th percentile for tail protection."),
        (14, [p_k21, p_rm63, p_vol21], "0.6 * k1 + 0.4 * res_mom", r_v80, o_b020, h_base + " Adding realized volatility primitive to monitor asset-level risk state."),
        (15, [p_k21, p_rm63, p_vol21], "cs_demean(k1 + res_mom)", r_v80, o_b020, h_base + " Neutralizing cross-sectional mean to ensure dollar-neutral alpha positioning."),
        (16, [p_k21, p_rm63, p_vol21], "cs_demean(k1 + res_mom)", r_v80, o_w18, h_base + " Lowering max single position weight to 18% for diversification."),
        (17, [p_k30, p_rm63, p_vol21], "cs_demean(k1 + res_mom)", r_v80, o_w18, h_base + " Increasing Kalman trend lookback to 30 bars to filter transient noise."),
        (18, [p_k30, p_rm63, p_vol21], "cs_rank(k1) + cs_demean(res_mom)", r_v80, o_w18, h_base + " Combining ranked state-space trend with demeaned idiosyncratic residual alpha."),
        (19, [p_k30, p_rm63, p_vol21], "cs_rank(k1) + cs_demean(res_mom)", r_disp, o_w18, h_base + " Dynamically scaling exposure during high cross-sectional dispersion regimes."),
        (20, [p_k30, p_rm63, p_vol21], "cs_rank(k1) + cs_demean(res_mom)", r_disp, o_lev95, h_base + " Setting target gross leverage to 0.95 to maintain cash liquidity cushion."),
        (21, [p_k30, p_rm63, p_vol63], "cs_rank(k1) + cs_demean(res_mom)", r_disp, o_lev95, h_base + " Extending asset volatility window to 63 bars for robust normalization."),
        (22, [p_k30, p_rm63, p_vol63], "cs_zscore(k1) + cs_rank(res_mom)", r_disp, o_lev95, h_base + " Pairing Winsorized z-score Kalman trend with ranked residual momentum."),
        (23, [p_k30, p_rm63, p_vol63], "cs_zscore(k1) + cs_rank(res_mom)", r_v75, o_lev95, h_base + " Enhancing tail protection by capping market volatility percentile at 75%."),
        (24, [p_k30, p_rm63, p_vol63], "cs_zscore(k1) + cs_rank(res_mom)", r_v75, o_b025, h_base + " Raising trade buffer delta to 2.5% to suppress unnecessary rebalances."),
        (25, [p_k30_hl15, p_rm63, p_vol63], "cs_zscore(k1) + cs_rank(res_mom)", r_v75, o_b025, h_base + " Calibrating Kalman half life parameter to 15 bars for smoother tracking."),
        (26, [p_k30_hl15, p_rm63, p_vol63], "ts_decay_linear(k1, 10)", r_v75, o_b025, h_base + " Applying 10-bar linear decay filter on smoothed Kalman state estimate."),
        (27, [p_k30_hl15, p_rm63, p_vol63], "ts_decay_linear(k1, 10)", r_ac00, o_b025, h_base + " Enforcing positive autocorrelation regime requirement for trend validity."),
        (28, [p_k30_hl15, p_rm63, p_vol63], "ts_decay_linear(k1, 10)", r_ac00, o_w16, h_base + " Restricting single asset maximum weight to 16% for superior risk parity."),
        (29, [p_k30_hl15, p_rm126, p_vol63], "ts_decay_linear(k1, 10)", r_ac00, o_w16, h_base + " Extending residual momentum window to semi-annual 126 bars."),
        (30, [p_k30_hl15, p_rm126, p_vol63], "cs_rank(k1) + cs_zscore(res_mom)", r_ac00, o_w16, h_base + " Final production trend model combining ranked Kalman state and semi-annual residual alpha."),
    ]
    return [_trend_contract(*step) for step in steps]


def build_mean_reversion_trajectory() -> list[StrategyContract]:
    """Build deterministic 30-round evolutionary trajectory for mean reversion."""
    p_ou60 = PrimitiveConfig(primitive_id="ou1", module_type="OUMeanReversion", params={"lookback": 60})
    p_ou45 = PrimitiveConfig(primitive_id="ou1", module_type="OUMeanReversion", params={"lookback": 45})
    p_ou35 = PrimitiveConfig(primitive_id="ou1", module_type="OUMeanReversion", params={"lookback": 35})
    p_ou50 = PrimitiveConfig(primitive_id="ou1", module_type="OUMeanReversion", params={"lookback": 50})
    p_ou63 = PrimitiveConfig(primitive_id="ou1", module_type="OUMeanReversion", params={"lookback": 63})

    p_rz5 = PrimitiveConfig(primitive_id="r_stat", module_type="RollingStat", params={"stat": "zscore", "window": 5, "field": "close"})
    p_rz10 = PrimitiveConfig(primitive_id="r_stat", module_type="RollingStat", params={"stat": "zscore", "window": 10, "field": "close"})
    p_rz21 = PrimitiveConfig(primitive_id="r_stat", module_type="RollingStat", params={"stat": "zscore", "window": 21, "field": "close"})
    p_vol21 = PrimitiveConfig(primitive_id="vol_stat", module_type="RollingStat", params={"stat": "mean", "window": 21, "field": "volume"})

    o_base = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.015, max_single_position_weight=0.20, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_b020 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.020, max_single_position_weight=0.20, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_b025 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.025, max_single_position_weight=0.20, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_w18 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.025, max_single_position_weight=0.18, target_gross_leverage=1.0, odd_lot_execution_mode="avoid_odd_lots")
    o_lev90 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.025, max_single_position_weight=0.18, target_gross_leverage=0.90, odd_lot_execution_mode="avoid_odd_lots")
    o_b028 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.028, max_single_position_weight=0.18, target_gross_leverage=0.90, odd_lot_execution_mode="avoid_odd_lots")
    o_w16 = ExecutionOverlayConfig(rebalance_frequency="1W", trade_buffer_delta_weight=0.028, max_single_position_weight=0.16, target_gross_leverage=0.90, odd_lot_execution_mode="avoid_odd_lots")

    r_v90 = "where(mkt_vol_pct_252d <= 0.90, 1.0, 0.2)"
    r_v85 = "where(mkt_vol_pct_252d <= 0.85, 1.0, 0.2)"
    r_ac15 = "where(mkt_autocorr_21d <= 0.15, 1.0, 0.25)"
    r_disp = "where(mkt_disp_pct_252d >= 0.20, 1.0, 0.4)"
    r_v80 = "where(mkt_vol_pct_252d <= 0.80, 1.0, 0.15)"
    r_v78 = "where(mkt_vol_pct_252d <= 0.78, 1.0, 0.20)"
    r_ac10 = "where(mkt_autocorr_21d <= 0.10, 1.0, 0.3)"

    h_base = "Exploiting short-term Ornstein-Uhlenbeck mean-reversion dislocations in liquid equities with friction buffer."

    steps = [
        # 1: Initial baseline
        (1, [p_ou60], "cs_demean(-ou1)", r_v90, o_base, h_base),
        # 2: overlay -> buffer 0.020
        (2, [p_ou60], "cs_demean(-ou1)", r_v90, o_b020, h_base + " Widening trade buffer to damp execution friction on mean-reversion."),
        # 3: signal -> zscore reversal
        (3, [p_ou60], "-cs_zscore(ou1)", r_v90, o_b020, h_base + " Winsorizing cross-sectional reversal signal at extreme dislocations."),
        # 4: primitives -> ou lookback 45
        (4, [p_ou45], "-cs_zscore(ou1)", r_v90, o_b020, h_base + " Shortening OU lookback to 45 bars for faster mean-reversion capture."),
        # 5: regime -> vol gate 85%
        (5, [p_ou45], "-cs_zscore(ou1)", r_v85, o_b020, h_base + " Tightening volatility crash filter to prevent stepping in front of cascades."),
        # 6: signal -> tick liquidity gate
        (6, [p_ou45], "where(effective_tick_bps <= 20.0, -ou1, 0.0)", r_v85, o_b020, h_base + " Suppressing trading on names with wide effective tick spreads."),
        # 7: primitives -> add r_stat 5
        (7, [p_ou45, p_rz5], "where(effective_tick_bps <= 20.0, -ou1, 0.0)", r_v85, o_b020, h_base + " Adding fast 5-day return dislocation rolling statistic."),
        # 8: signal -> dual reversal
        (8, [p_ou45, p_rz5], "-ou1 - r_stat", r_v85, o_b020, h_base + " Combining structural OU alpha with short-horizon return exhaustion."),
        # 9: regime -> autocorr gate 15%
        (9, [p_ou45, p_rz5], "-ou1 - r_stat", r_ac15, o_b020, h_base + " De-risking when market exhibits persistent trending momentum cascades."),
        # 10: overlay -> buffer 0.025
        (10, [p_ou45, p_rz5], "-ou1 - r_stat", r_ac15, o_b025, h_base + " Expanding trade buffer delta to 2.5% to preserve net alpha."),
        # 11: primitives -> r_stat window 10
        (11, [p_ou45, p_rz10], "-ou1 - r_stat", r_ac15, o_b025, h_base + " Calibrating return z-score lookback to 10 bars for durable reversal."),
        # 12: signal -> cs_demean(-ou1)
        (12, [p_ou45, p_rz10], "cs_demean(-ou1)", r_ac15, o_b025, h_base + " Enforcing dollar neutrality across demeaned OU reversal components."),
        # 13: regime -> dispersion gate
        (13, [p_ou45, p_rz10], "cs_demean(-ou1)", r_disp, o_b025, h_base + " Increasing gross allocation during periods of wide cross-sectional dispersion."),
        # 14: primitives -> add vol_stat 21
        (14, [p_ou45, p_rz10, p_vol21], "cs_demean(-ou1)", r_disp, o_b025, h_base + " Monitoring trading volume moving average to confirm liquidity."),
        # 15: signal -> rank reversal
        (15, [p_ou45, p_rz10, p_vol21], "-cs_rank(ou1)", r_disp, o_b025, h_base + " Utilizing uniform rank scaling on OU dislocation signal."),
        # 16: overlay -> single cap 0.18
        (16, [p_ou45, p_rz10, p_vol21], "-cs_rank(ou1)", r_disp, o_w18, h_base + " Capping individual position sizing to 18% of portfolio equity."),
        # 17: primitives -> ou lookback 35
        (17, [p_ou35, p_rz10, p_vol21], "-cs_rank(ou1)", r_disp, o_w18, h_base + " Tuning OU lookback to 35 bars to isolate short-term liquidity shocks."),
        # 18: signal -> cs_rank(-ou1)
        (18, [p_ou35, p_rz10, p_vol21], "cs_rank(-ou1)", r_disp, o_w18, h_base + " Focusing on pure ranked inverted OU price dislocation."),
        # 19: regime -> vol gate 80%
        (19, [p_ou35, p_rz10, p_vol21], "cs_rank(-ou1)", r_v80, o_w18, h_base + " Restricting exposure when 252-day market volatility exceeds 80th percentile."),
        # 20: overlay -> leverage 0.90
        (20, [p_ou35, p_rz10, p_vol21], "cs_rank(-ou1)", r_v80, o_lev90, h_base + " Lowering target gross leverage to 0.90 for stress margin resilience."),
        # 21: primitives -> r_stat window 21
        (21, [p_ou35, p_rz21, p_vol21], "cs_rank(-ou1)", r_v80, o_lev90, h_base + " Adjusting secondary return lookback to canonical monthly 21-bar window."),
        # 22: signal -> cs_demean(-ou1)
        (22, [p_ou35, p_rz21, p_vol21], "cs_demean(-ou1)", r_v80, o_lev90, h_base + " Returning to cross-sectionally demeaned OU alpha with refreshed calibration."),
        # 23: regime -> vol gate 78%
        (23, [p_ou35, p_rz21, p_vol21], "cs_demean(-ou1)", r_v78, o_lev90, h_base + " Fine-tuning volatility cutoff to 78th percentile for drawdown avoidance."),
        # 24: overlay -> buffer 0.028
        (24, [p_ou35, p_rz21, p_vol21], "cs_demean(-ou1)", r_v78, o_b028, h_base + " Increasing trade buffer delta to 2.8% to minimize friction in sideways markets."),
        # 25: primitives -> ou lookback 50
        (25, [p_ou50, p_rz21, p_vol21], "cs_demean(-ou1)", r_v78, o_b028, h_base + " Updating OU lookback to 50 bars for balanced persistence and half life."),
        # 26: signal -> adv participation gate
        (26, [p_ou50, p_rz21, p_vol21], "where(adv_participation_bps <= 15.0, -ou1, 0.0)", r_v78, o_b028, h_base + " Filtering out securities where participation rate exceeds 15bps."),
        # 27: regime -> autocorr gate 10%
        (27, [p_ou50, p_rz21, p_vol21], "where(adv_participation_bps <= 15.0, -ou1, 0.0)", r_ac10, o_b028, h_base + " Enforcing strict autocorrelation ceiling to avoid counter-trend losses."),
        # 28: overlay -> single cap 0.16
        (28, [p_ou50, p_rz21, p_vol21], "where(adv_participation_bps <= 15.0, -ou1, 0.0)", r_ac10, o_w16, h_base + " Limiting max position size to 16% to cap idiosyncratic tail variance."),
        # 29: primitives -> ou lookback 63
        (29, [p_ou63, p_rz21, p_vol21], "where(adv_participation_bps <= 15.0, -ou1, 0.0)", r_ac10, o_w16, h_base + " Re-calibrating OU process over canonical 63-day horizon."),
        # 30: signal -> final production candidate
        (30, [p_ou63, p_rz21, p_vol21], "where(effective_tick_bps <= 20.0, -ou1, 0.0)", r_ac10, o_w16, h_base + " Final mean-reversion production alpha with quarterly OU calibration and tick liquidity gate."),
    ]
    return [_mr_contract(*step) for step in steps]


class EvolutionaryStrategyGenerator:
    """Specialist generator providing 30 rounds of single-mutation hypothesis evolution."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._trend_seq = build_trend_trajectory()
        self._mr_seq = build_mean_reversion_trajectory()
        self.call_history: dict[str, list[StrategyContract]] = {"trend": [], "mean_reversion": []}

    def __call__(self, system_prompt: str, user_prompt: str) -> StrategyContract:
        arch = "mean_reversion" if "mean_reversion" in user_prompt.lower() or "mean-reversion" in system_prompt.lower() else "trend"
        match = re.search(r"ROUND (\d+) OF", user_prompt)
        if match:
            round_idx = int(match.group(1)) - 1
        else:
            round_idx = len(self.call_history[arch])

        seq = self._mr_seq if arch == "mean_reversion" else self._trend_seq
        idx = min(round_idx, len(seq) - 1)
        contract = seq[idx]
        self.call_history[arch].append(contract)
        return contract
