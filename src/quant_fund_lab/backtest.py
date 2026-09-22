from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .data import MarketData
from .execution import (
    PortfolioState,
    apply_terminal_returns,
    market_for_symbol,
    rebalance_at_open,
)
from .factors import (
    build_market_factor_panel,
    factor_alpha_from_precomputed,
    information_coefficient_series,
    orthogonalize_factor_panel,
)
from .fx import currency_for_symbol, validate_fx
from .market_calendar import SessionValidation, require_valid_daily_sessions
from .models import ensemble_alpha
from .portfolio import optimize_weights
from .research import detect_market_regime, neutralize_alpha, regime_adjusted_alpha
from .risk_controls import apply_portfolio_risk_controls


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    weights: pd.DataFrame
    alphas: pd.DataFrame
    cost_attribution: pd.DataFrame
    session_validation: SessionValidation | None
    terminal_events: pd.DataFrame
    base_currency: str
    max_fx_age_days: float
    regimes: pd.DataFrame
    factor_weights: pd.DataFrame
    risk_controls: pd.DataFrame


def run_backtest(data: MarketData, config: BacktestConfig | None = None) -> BacktestResult:
    config = config or BacktestConfig()
    markets = {market_for_symbol(symbol) for symbol in data.symbols}
    currencies = {currency_for_symbol(symbol) for symbol in data.symbols}
    session_validation: SessionValidation | None = None
    if len(markets) == 1 and data.exchange is not None:
        market = next(iter(markets))
        if data.exchange != market:
            raise ValueError("market-data exchange metadata does not match symbols")
        session_validation = require_valid_daily_sessions(data.close.index, market)

    requested_base = config.base_currency.upper() if config.base_currency else None
    if data.fx_to_base is None:
        if len(currencies) != 1:
            raise ValueError("mixed-currency portfolio requires attached FX conversion factors")
        local_currency = next(iter(currencies))
        base_currency = requested_base or data.base_currency or local_currency
        if base_currency != local_currency:
            raise ValueError(f"FX conversion is required for {local_currency}->{base_currency}")
        fx_to_base = pd.DataFrame(1.0, index=data.close.index, columns=data.symbols)
        fx_age_days = pd.DataFrame(0.0, index=data.close.index, columns=data.symbols)
    else:
        if data.base_currency is None:
            raise ValueError("base_currency metadata is required with attached FX factors")
        base_currency = data.base_currency.upper()
        if requested_base is not None and requested_base != base_currency:
            raise ValueError("BacktestConfig base_currency does not match attached FX data")
        fx_report = validate_fx(data, config.max_fx_staleness_days)
        if not fx_report.is_valid:
            raise ValueError("attached FX conversion factors failed validation")
        fx_to_base = data.fx_to_base
        fx_age_days = data.fx_age_days
    strategy = config.strategy
    dates = data.close.index
    if len(dates) < strategy.warmup_days + 2:
        raise ValueError(f"need at least {strategy.warmup_days + 2} bars")

    state = PortfolioState(cash=float(config.initial_cash))
    equity_rows: list[dict[str, float | pd.Timestamp]] = []
    weight_rows: list[pd.Series] = []
    alpha_rows: list[pd.Series] = []
    fill_rows: list[dict[str, object]] = []
    terminal_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []
    factor_weight_rows: list[pd.Series] = []
    risk_control_rows: list[dict[str, object]] = []
    target = pd.Series(0.0, index=data.symbols)
    factor_panel = pd.DataFrame()
    factor_ic = pd.DataFrame()
    if strategy.factor_alpha_enabled:
        factor_panel = build_market_factor_panel(data, sampling_every=1)
        if strategy.factor_orthogonalization:
            factor_panel = orthogonalize_factor_panel(factor_panel)
        factor_prices = data.close * fx_to_base
        factor_ic = information_coefficient_series(
            factor_panel,
            factor_prices,
            horizons=(strategy.factor_ic_horizon,),
        )

    start_i = strategy.warmup_days - 1
    initial_date = dates[start_i]
    running_peak = float(config.initial_cash)
    equity_rows.append({"timestamp": initial_date, "equity": config.initial_cash, "cash": state.cash})

    for i in range(start_i, len(dates) - 1):
        signal_date = dates[i]
        execution_date = dates[i + 1]
        close_now = data.close.loc[signal_date]
        open_next = data.open.loc[execution_date]
        close_next = data.close.loc[execution_date]
        volume_next = data.volume.loc[execution_date]
        reference_next = data.reference.loc[execution_date]
        fx_signal = fx_to_base.loc[signal_date]
        fx_next = fx_to_base.loc[execution_date]
        terminal_next = data.terminal_returns.loc[execution_date]
        signal_equity = state.equity(close_now, fx_signal)
        running_peak = max(running_peak, signal_equity)
        current_drawdown = max(0.0, 1.0 - signal_equity / max(running_peak, 1e-12))
        terminal_events = apply_terminal_returns(
            state=state,
            terminal_returns=terminal_next,
            reference_prices=reference_next,
            timestamp=pd.Timestamp(execution_date),
            fx_to_base=fx_next,
        )
        terminal_rows.extend(asdict(event) for event in terminal_events)

        if (i - start_i) % strategy.rebalance_every == 0:
            history = data.close.iloc[: i + 1] * fx_to_base.iloc[: i + 1]
            alpha_frame = ensemble_alpha(history, strategy)
            eligible = data.membership.loc[signal_date].reindex(data.symbols).fillna(False)
            if strategy.regime_enabled:
                regime = detect_market_regime(history, strategy.regime_lookback)
                raw_alpha = regime_adjusted_alpha(alpha_frame, strategy, regime)
            else:
                regime = detect_market_regime(history, strategy.regime_lookback)
                raw_alpha = alpha_frame["ensemble"]
            if strategy.factor_alpha_enabled:
                factor_signal = factor_alpha_from_precomputed(
                    factor_panel,
                    factor_ic,
                    pd.Timestamp(signal_date),
                    data.symbols,
                    horizon=strategy.factor_ic_horizon,
                    lookback=strategy.factor_ic_lookback,
                    min_observations=strategy.factor_ic_min_observations,
                )
                overlay = float(np.clip(strategy.factor_alpha_weight, 0.0, 1.0))
                if not factor_signal.weights.empty:
                    raw_alpha = (1.0 - overlay) * raw_alpha + overlay * factor_signal.score
                factor_weight_row = factor_signal.weights.copy()
                factor_weight_row.name = signal_date
                factor_weight_rows.append(factor_weight_row)
            factor_returns = history.pct_change(fill_method=None).tail(strategy.factor_lookback)
            if strategy.factor_neutralization:
                neutral_alpha, _ = neutralize_alpha(raw_alpha, factor_returns, eligible=eligible)
                strength = float(np.clip(strategy.factor_neutralization_strength, 0.0, 1.0))
                alpha = (1.0 - strength) * raw_alpha + strength * neutral_alpha
                alpha = alpha.where(eligible, 0.0)
            else:
                alpha = raw_alpha.where(eligible, 0.0)
            alpha = alpha.reindex(data.symbols).fillna(0.0)
            returns = history.pct_change(fill_method=None).tail(strategy.covariance_lookback)
            previous = state.weights(close_now, fx_signal).reindex(data.symbols).fillna(0.0)
            gross_limit = regime.gross_exposure_limit if strategy.regime_enabled else 1.0
            target = optimize_weights(
                alpha,
                returns,
                previous,
                strategy,
                eligible=eligible,
                gross_exposure_limit=gross_limit,
            )
            regime_rows.append(
                {
                    "timestamp": signal_date,
                    "label": regime.label,
                    "trend_z": regime.trend_z,
                    "annual_volatility": regime.annual_volatility,
                    "gross_exposure_limit": gross_limit,
                }
            )
            terminal_symbols = terminal_next[terminal_next.notna()].index
            target.loc[target.index.intersection(terminal_symbols)] = 0.0
            risk_result = apply_portfolio_risk_controls(
                target,
                returns,
                strategy.covariance_shrinkage,
                current_drawdown,
                target_annual_volatility=(
                    strategy.target_annual_volatility
                    if strategy.volatility_target_enabled
                    else None
                ),
                max_daily_cvar=(
                    strategy.max_daily_cvar if strategy.cvar_control_enabled else None
                ),
                cvar_confidence=strategy.cvar_confidence,
                drawdown_soft_limit=(
                    strategy.drawdown_soft_limit
                    if strategy.drawdown_control_enabled
                    else None
                ),
                drawdown_hard_limit=(
                    strategy.drawdown_hard_limit
                    if strategy.drawdown_control_enabled
                    else None
                ),
                drawdown_min_exposure=strategy.drawdown_min_exposure,
            )
            gross_before = float(target.sum())
            target = risk_result.weights
            risk_control_rows.append(
                {
                    "timestamp": signal_date,
                    "drawdown": current_drawdown,
                    "gross_before": gross_before,
                    "gross_after": float(target.sum()),
                    "forecast_annual_volatility_before": (
                        risk_result.forecast_annual_volatility_before
                    ),
                    "forecast_annual_volatility_after": (
                        risk_result.forecast_annual_volatility_after
                    ),
                    "historical_cvar_before": risk_result.historical_cvar_before,
                    "historical_cvar_after": risk_result.historical_cvar_after,
                    "volatility_scale": risk_result.volatility_scale,
                    "cvar_scale": risk_result.cvar_scale,
                    "drawdown_scale": risk_result.drawdown_scale,
                    "final_scale": risk_result.final_scale,
                }
            )

            alpha_row = alpha.copy()
            alpha_row.name = signal_date
            alpha_rows.append(alpha_row)
            weight_row = target.copy()
            weight_row.name = signal_date
            weight_rows.append(weight_row)

            fills = rebalance_at_open(
                state=state,
                target_weights=target,
                open_prices=open_next,
                volumes=volume_next,
                reference_prices=reference_next,
                timestamp=pd.Timestamp(execution_date),
                config=config,
                fx_to_base=fx_next,
            )
            fill_rows.extend(asdict(fill) for fill in fills)

        equity_rows.append(
            {
                "timestamp": execution_date,
                "equity": state.equity(close_next, fx_next),
                "cash": state.cash,
            }
        )

    equity_curve = pd.DataFrame(equity_rows).set_index("timestamp")
    fills_df = pd.DataFrame(fill_rows)
    weights_df = pd.DataFrame(weight_rows).sort_index() if weight_rows else pd.DataFrame(columns=data.symbols)
    alphas_df = pd.DataFrame(alpha_rows).sort_index() if alpha_rows else pd.DataFrame(columns=data.symbols)
    terminal_df = pd.DataFrame(terminal_rows)
    regimes_df = (
        pd.DataFrame(regime_rows).set_index("timestamp")
        if regime_rows
        else pd.DataFrame(columns=["label", "trend_z", "annual_volatility", "gross_exposure_limit"])
    )
    factor_weights_df = (
        pd.DataFrame(factor_weight_rows).sort_index()
        if factor_weight_rows
        else pd.DataFrame()
    )
    risk_controls_df = (
        pd.DataFrame(risk_control_rows).set_index("timestamp")
        if risk_control_rows
        else pd.DataFrame()
    )
    if fills_df.empty:
        costs_df = pd.DataFrame(columns=["gross_turnover", "fees", "slippage_cost", "total_cost", "turnover_rate"])
    else:
        grouped = fills_df.groupby("timestamp")[["gross_value", "fees", "slippage_cost"]].sum()
        costs_df = grouped.rename(columns={"gross_value": "gross_turnover"})
        costs_df["total_cost"] = costs_df["fees"] + costs_df["slippage_cost"]
        equity_on_trade = equity_curve["equity"].reindex(costs_df.index)
        costs_df["turnover_rate"] = costs_df["gross_turnover"] / equity_on_trade
    return BacktestResult(
        equity_curve=equity_curve,
        fills=fills_df,
        weights=weights_df,
        alphas=alphas_df,
        cost_attribution=costs_df,
        session_validation=session_validation,
        terminal_events=terminal_df,
        base_currency=base_currency,
        max_fx_age_days=float(fx_age_days.max().max()),
        regimes=regimes_df,
        factor_weights=factor_weights_df,
        risk_controls=risk_controls_df,
    )
