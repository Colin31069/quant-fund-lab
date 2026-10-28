"""Daily-bar Taiwan odd-lot research with explicit, conservative proxy assumptions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import floor, sqrt

import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .cash_carry import accrue_base_cash_interest
from .config import BacktestConfig, MarketCostConfig, StrategyConfig
from .corporate_actions import (
    CashInLieuReceivable,
    apply_cash_dividend_events,
    apply_stock_split_events,
    mark_cash_in_lieu_receivables,
    settle_cash_in_lieu_receivables,
)
from .data import MarketData
from .execution import (
    PortfolioState,
    _trade_costs,
    apply_terminal_returns,
    execute_market_order,
    prior_session_liquidity,
)
from .market_calendar import require_valid_daily_sessions
from .models import ensemble_alpha
from .portfolio import optimize_weights
from .research import detect_market_regime, neutralize_alpha, regime_adjusted_alpha
from .trade_analytics import position_episodes, summarize_episodes


@dataclass(frozen=True)
class OddLotResearchConfig:
    strategy: str = "ensemble"
    risk_budget: float = 2_000.0
    max_positions: int = 5
    max_weight: float = 0.20
    rebalance_every: int = 5
    momentum_lookback: int = 30
    volatility_lookback: int = 20
    volatility_multiplier: float = 2.0
    min_stop_distance: float = 0.05
    max_stop_distance: float = 0.12
    min_commission: float = 20.0
    slippage_bps: float = 5.0

    def __post_init__(self) -> None:
        if self.strategy not in {"ensemble", "momentum", "equal_weight"}:
            raise ValueError("unknown odd-lot research strategy")
        if not np.isfinite(self.risk_budget) or self.risk_budget <= 0:
            raise ValueError("risk_budget must be positive and finite")
        if self.max_positions < 1 or not 0 < self.max_weight <= 1:
            raise ValueError("invalid position limits")
        if min(self.rebalance_every, self.momentum_lookback, self.volatility_lookback) < 1:
            raise ValueError("research windows must be positive")
        if not 0 < self.min_stop_distance <= self.max_stop_distance < 1:
            raise ValueError("invalid stop distances")
        if self.volatility_multiplier <= 0 or self.min_commission < 0 or self.slippage_bps < 0:
            raise ValueError("invalid volatility or execution assumption")


@dataclass(frozen=True)
class OddLotResearchResult:
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    corporate_actions: pd.DataFrame
    terminal_events: pd.DataFrame
    signals: pd.DataFrame
    episodes: pd.DataFrame
    trade_summary: dict[str, float | int | None]
    metrics: dict[str, float]
    config: OddLotResearchConfig
    backtest_config: BacktestConfig


@dataclass
class _Stop:
    stop: float
    high_close: float
    distance: float


@dataclass
class _Order:
    side: str
    quantity: int
    reason: str
    stop: float = 0.0
    signal_price: float = 0.0
    distance: float = 0.0
    signal_volume: float = 0.0


def validate_raw_split_basis(data: MarketData) -> None:
    """Reject raw prices that appear to already include split adjustments.

    A raw-price account applies each declared split to shares; prices that have
    already been split adjusted would double count it. This diagnostic cannot
    establish completeness of the corporate-action source.
    """
    raw = data.raw_close
    if raw is None:
        raise ValueError("odd-lot research requires unadjusted raw close prices")
    for symbol in data.symbols:
        for index in range(1, len(raw)):
            ratio = float(data.stock_splits[symbol].iloc[index])
            if not np.isfinite(ratio) or ratio <= 0 or np.isclose(ratio, 1.0):
                continue
            values = (
                raw[symbol].iloc[index - 1], raw[symbol].iloc[index],
                data.close[symbol].iloc[index - 1], data.close[symbol].iloc[index],
            )
            if not all(pd.notna(value) and np.isfinite(value) and value > 0 for value in values):
                raise ValueError(f"missing split-basis observations for {symbol} on {raw.index[index].date()}")
            raw_before, raw_after, adjusted_before, adjusted_after = map(float, values)
            relative_change = (raw_after / raw_before) / (adjusted_after / adjusted_before)
            if abs(np.log(relative_change)) < abs(np.log(ratio)) * 0.5:
                raise ValueError(
                    f"raw prices appear split-adjusted for {symbol} on {raw.index[index].date()}; "
                    "use verified unadjusted prices before running raw corporate-action accounting"
                )


def odd_lot_backtest_config(
    base: BacktestConfig | None = None,
    research: OddLotResearchConfig | None = None,
) -> BacktestConfig:
    """Build an explicit research scenario; ordinary-lot defaults remain unchanged."""
    base = base or BacktestConfig(initial_cash=100_000.0, base_currency="TWD")
    research = research or OddLotResearchConfig()
    return replace(
        base,
        base_currency="TWD",
        execution_price_basis="raw",
        tw_costs=replace(
            base.tw_costs,
            lot_size=1,
            max_order_shares=999,
            min_commission=research.min_commission,
            slippage_bps=research.slippage_bps,
        ),
        strategy=replace(
            base.strategy,
            max_weight=research.max_weight,
            rebalance_every=research.rebalance_every,
        ),
    )


def _estimated_risk(
    quantity: int, price: float, stop: float, volume: float, costs: MarketCostConfig
) -> float:
    if quantity <= 0:
        return 0.0
    impact = costs.impact_coefficient * sqrt(quantity / max(volume, 1.0)) / 100.0
    slip = costs.slippage_bps / 10_000.0 + impact
    buy = quantity * price * (1.0 + slip)
    sell = quantity * stop * max(0.0, 1.0 - slip)
    return buy + _trade_costs("BUY", buy, costs) - sell + _trade_costs("SELL", sell, costs)


def _entry_quantity(
    price: float, stop: float, volume: float, equity: float, weight: float,
    research: OddLotResearchConfig, costs: MarketCostConfig,
) -> int:
    if not np.isfinite(price) or not np.isfinite(stop) or price <= stop or stop <= 0 or volume <= 0:
        return 0
    high = max(0, floor(equity * min(weight, research.max_weight) / price))
    high = min(high, costs.max_order_shares or high)
    low = 0
    while low < high:
        mid = (low + high + 1) // 2
        if _estimated_risk(mid, price, stop, volume, costs) <= research.risk_budget:
            low = mid
        else:
            high = mid - 1
    return low


def _targets(
    history: pd.DataFrame, eligible: pd.Series, research: OddLotResearchConfig,
    strategy: StrategyConfig, previous: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    symbols = history.columns
    eligible = eligible.reindex(symbols).fillna(False).astype(bool)
    if research.strategy == "equal_weight":
        scores = pd.Series(1.0, index=symbols).where(eligible, 0.0)
    elif research.strategy == "momentum":
        if len(history) <= research.momentum_lookback:
            return pd.Series(0.0, index=symbols), pd.Series(0.0, index=symbols)
        scores = (history.iloc[-1] / history.iloc[-research.momentum_lookback - 1] - 1.0)
        scores = scores.replace([np.inf, -np.inf], np.nan).fillna(0.0).where(eligible, 0.0)
    else:
        frame = ensemble_alpha(history, strategy)
        regime = detect_market_regime(history, strategy.regime_lookback)
        scores = regime_adjusted_alpha(frame, strategy, regime) if strategy.regime_enabled else frame["ensemble"]
        returns = history.pct_change(fill_method=None).tail(strategy.factor_lookback)
        if strategy.factor_neutralization:
            neutral, _ = neutralize_alpha(scores, returns, eligible=eligible)
            scores = (1.0 - strategy.factor_neutralization_strength) * scores + strategy.factor_neutralization_strength * neutral
        scores = scores.reindex(symbols).fillna(0.0).where(eligible, 0.0)
    ranked = sorted((str(s) for s in symbols if eligible[s] and scores[s] > 0), key=lambda s: (-float(scores[s]), s))
    selected = ranked if research.strategy == "equal_weight" else ranked[:research.max_positions]
    allowed = pd.Series(False, index=symbols)
    allowed.loc[selected] = True
    if research.strategy == "ensemble" and selected:
        returns = history.pct_change(fill_method=None).tail(strategy.covariance_lookback)
        regime = detect_market_regime(history, strategy.regime_lookback)
        limit = regime.gross_exposure_limit if strategy.regime_enabled else 1.0
        weights = optimize_weights(scores, returns, previous, strategy, eligible=allowed, gross_exposure_limit=limit)
    else:
        weights = pd.Series(0.0, index=symbols)
        if selected:
            denominator = len(selected) if research.strategy == "equal_weight" else research.max_positions
            weights.loc[selected] = min(research.max_weight, 1.0 / denominator)
    return scores, weights


def run_odd_lot_research(
    data: MarketData,
    research: OddLotResearchConfig | None = None,
    base_config: BacktestConfig | None = None,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> OddLotResearchResult:
    """Run a fresh, long-only account. Prices and volume are explicit proxies.

    Stops use close observations and are submitted for the next session. They are
    not an intraday stop order and cannot guarantee the modeled loss budget.
    """
    research = research or OddLotResearchConfig()
    config = odd_lot_backtest_config(base_config, research)
    if any((
        config.strategy.factor_alpha_enabled,
        config.strategy.volatility_target_enabled,
        config.strategy.cvar_control_enabled,
        config.strategy.drawdown_control_enabled,
    )):
        raise ValueError("factor overlay and portfolio risk controls are not supported in odd-lot research")
    if config.initial_cash <= 0 or not np.isfinite(config.initial_cash):
        raise ValueError("initial cash must be positive and finite")
    if not data.close.index.is_unique or not data.close.index.is_monotonic_increasing:
        raise ValueError("research sessions must be unique and chronological")
    if not data.close.columns.is_unique:
        raise ValueError("research symbols must be unique")
    validate_raw_split_basis(data)
    require_valid_daily_sessions(data.close.index, "TW")
    if data.base_currency not in (None, "TWD"):
        raise ValueError("odd-lot research requires TWD market data")
    if data.market_codes is not None:
        if bool((data.membership & data.market_codes.isna()).any().any()):
            raise ValueError("active security is missing market metadata")
        active_codes = data.market_codes.where(data.membership).stack().dropna()
        if not active_codes.eq("TW").all():
            raise ValueError("odd-lot research only supports TW securities")
    elif any(not s.upper().endswith((".TW", ".TWO")) for s in data.symbols):
        raise ValueError("odd-lot research requires TW symbols or market metadata")
    if data.fx_to_base is not None and not np.allclose(data.fx_to_base.fillna(1.0), 1.0):
        raise ValueError("odd-lot research requires TWD-denominated assets")
    if data.currency_codes is not None:
        if bool((data.membership & data.currency_codes.isna()).any().any()):
            raise ValueError("active security is missing currency metadata")
        if not data.currency_codes.where(data.membership).stack().dropna().eq("TWD").all():
            raise ValueError("odd-lot research requires TWD-denominated assets")
    dates = data.close.index
    start_index = config.strategy.warmup_days - 1
    if start is not None:
        start_index = max(start_index, int(dates.searchsorted(pd.Timestamp(start), side="left")) - 1)
    end_index = len(dates) - 1 if end is None else int(dates.searchsorted(pd.Timestamp(end), side="right")) - 1
    if start_index < 0 or end_index <= start_index or end_index >= len(dates):
        raise ValueError("insufficient observations for the requested research interval")
    raw_open, raw_close = data.raw_open, data.raw_close
    if raw_open is None or raw_close is None:
        raise ValueError("odd-lot research requires raw price panels")
    liquidity = prior_session_liquidity(data.volume)
    state = PortfolioState(cash=float(config.initial_cash))
    stops: dict[str, _Stop] = {}
    pending: dict[str, _Order] = {}
    terminated: set[str] = set()
    receivables: list[CashInLieuReceivable] = []
    fills: list[dict] = []
    actions: list[dict] = []
    terminal_events: list[dict] = []
    signal_rows: list[dict] = []
    equity_rows = [{"timestamp": dates[start_index], "equity": state.cash, "cash": state.cash, "receivable_value": 0.0}]
    passive_submitted = False

    for i in range(start_index, end_index):
        signal_date, date = dates[i], dates[i + 1]
        close_now = raw_close.loc[signal_date]
        equity = state.equity(close_now)
        # A stop has precedence over every model and is checked daily, not weekly.
        for symbol, stop in list(stops.items()):
            price = float(close_now.get(symbol, np.nan))
            observed = pd.notna(raw_open.at[signal_date, symbol])
            if not observed or not np.isfinite(price) or price <= 0:
                continue
            if price <= stop.stop:
                pending[symbol] = _Order("SELL", state.shares[symbol], "stop")
                signal_rows.append({"timestamp": signal_date, "symbol": symbol, "reason": "stop", "price": price, "stop": stop.stop, "score": np.nan, "weight": 0.0})
            else:
                stop.high_close = max(stop.high_close, price)
                stop.stop = max(stop.stop, stop.high_close * (1.0 - stop.distance))

        rebalance = (i - start_index) % research.rebalance_every == 0
        if rebalance and (research.strategy != "equal_weight" or not passive_submitted):
            history = data.close.iloc[: i + 1]
            eligible = data.membership.loc[signal_date].copy()
            eligible.loc[eligible.index.intersection(terminated)] = False
            previous = state.weights(close_now)
            scores, weights = _targets(history, eligible, research, config.strategy, previous)
            for symbol in data.symbols:
                held = state.shares.get(symbol, 0)
                if symbol in pending and pending[symbol].side == "SELL":
                    continue
                if held and weights[symbol] <= 0 and research.strategy != "equal_weight":
                    pending[symbol] = _Order("SELL", held, "model_exit")
                    signal_rows.append({"timestamp": signal_date, "symbol": symbol, "reason": "model_exit", "price": float(close_now[symbol]), "stop": stops[symbol].stop, "score": float(scores[symbol]), "weight": 0.0})
                elif not held and weights[symbol] > 0:
                    returns = history[symbol].pct_change(fill_method=None).dropna().tail(research.volatility_lookback)
                    if len(returns) < research.volatility_lookback:
                        continue
                    sigma = float(returns.std(ddof=1))
                    if not np.isfinite(sigma):
                        continue
                    distance = float(np.clip(sigma * research.volatility_multiplier, research.min_stop_distance, research.max_stop_distance))
                    price = float(close_now[symbol])
                    stop_price = price * (1.0 - distance)
                    known_volume = float(liquidity.at[date, symbol])
                    if research.strategy == "equal_weight":
                        qty = min(999, floor(equity * float(weights[symbol]) / price)) if price > 0 else 0
                    else:
                        qty = _entry_quantity(price, stop_price, known_volume, equity, float(weights[symbol]), research, config.tw_costs)
                    if qty:
                        pending[symbol] = _Order("BUY", qty, "entry", stop_price, price, distance, known_volume)
                        signal_rows.append({"timestamp": signal_date, "symbol": symbol, "reason": "entry", "price": price, "stop": stop_price, "score": float(scores[symbol]), "weight": float(weights[symbol])})
                elif not held and symbol in pending and pending[symbol].side == "BUY":
                    del pending[symbol]
            passive_submitted = True

        accrue_base_cash_interest(state, signal_date, date, config.cash_annual_yield)
        currencies = None if data.currency_codes is None else data.currency_codes.loc[date]
        settlement = settle_cash_in_lieu_receivables(
            state, receivables, date,
            None if data.cash_in_lieu_prices is None else data.cash_in_lieu_prices.loc[date],
            currency_codes=currencies,
        )
        actions.extend(asdict(event) for event in settlement)
        # Adjust model stop levels and cancel stale entry orders across split/dividend events.
        for symbol in data.symbols:
            ratio = float(data.stock_splits.at[date, symbol])
            dividend = float(data.dividends.at[date, symbol])
            if np.isfinite(ratio) and ratio > 0 and not np.isclose(ratio, 1.0):
                if symbol in stops:
                    stops[symbol].stop /= ratio
                    stops[symbol].high_close /= ratio
                if symbol in pending and pending[symbol].side == "BUY":
                    del pending[symbol]
            if np.isfinite(dividend) and dividend > 0 and symbol in stops:
                stops[symbol].stop = max(0.0, stops[symbol].stop - dividend)
                stops[symbol].high_close = max(0.0, stops[symbol].high_close - dividend)
        split_events = apply_stock_split_events(
            state, data.stock_splits.loc[date], raw_open.loc[date], date,
            currency_codes=currencies,
            cash_in_lieu_prices=None if data.cash_in_lieu_prices is None else data.cash_in_lieu_prices.loc[date],
            cash_in_lieu_settlement_dates=None if data.cash_in_lieu_settlement_dates is None else data.cash_in_lieu_settlement_dates.loc[date],
            receivables=receivables,
        )
        actions.extend(asdict(event) for event in split_events)
        dividend_events = apply_cash_dividend_events(
            state, data.dividends.loc[date], date, withholding=config.dividend_withholding,
            market_codes=None if data.market_codes is None else data.market_codes.loc[date],
            currency_codes=currencies,
        )
        actions.extend(asdict(event) for event in dividend_events)
        reference = close_now.copy()
        for symbol in data.symbols:
            ratio = float(data.stock_splits.at[date, symbol])
            dividend = float(data.dividends.at[date, symbol])
            if np.isfinite(ratio) and ratio > 0 and not np.isclose(ratio, 1.0):
                reference[symbol] /= ratio
            if np.isfinite(dividend) and dividend > 0:
                reference[symbol] = max(float(reference[symbol]) - dividend, 0.0)
        terminal = apply_terminal_returns(
            state, data.terminal_returns.loc[date], reference, date,
            currency_codes=currencies,
        )
        terminal_events.extend(asdict(event) for event in terminal)
        for symbol in data.terminal_returns.loc[date].dropna().index:
            terminated.add(symbol)
            stops.pop(symbol, None)
            pending.pop(symbol, None)
        for event in split_events:
            if event.quantity_after == 0:
                stops.pop(event.symbol, None)
                pending.pop(event.symbol, None)

        for side in ("SELL", "BUY"):
            for symbol in data.symbols:
                order = pending.get(symbol)
                if order is None or order.side != side:
                    continue
                if (
                    side == "BUY"
                    and research.strategy != "equal_weight"
                    and sum(qty > 0 for qty in state.shares.values()) >= research.max_positions
                ):
                    continue
                qty = state.shares.get(symbol, 0) if side == "SELL" else order.quantity
                fill = execute_market_order(
                    state, symbol, side, qty, float(raw_open.at[date, symbol]),
                    float(liquidity.at[date, symbol]), float(reference[symbol]), date, config,
                    market_code="TW", local_currency="TWD",
                )
                if fill is None:
                    continue
                record = asdict(fill)
                record["reason"] = order.reason
                record["planned_risk"] = 0.0
                if side == "BUY":
                    if research.strategy != "equal_weight":
                        record["planned_risk"] = _estimated_risk(fill.quantity, order.signal_price, order.stop, order.signal_volume, config.tw_costs)
                        stops[symbol] = _Stop(order.stop, order.signal_price, order.distance)
                    del pending[symbol]
                elif state.shares.get(symbol, 0) <= 0:
                    stops.pop(symbol, None)
                    del pending[symbol]
                fills.append(record)
        state.receivable_value = mark_cash_in_lieu_receivables(
            receivables, raw_close.loc[date], currency_codes=currencies
        )
        equity_rows.append({"timestamp": date, "equity": state.equity(raw_close.loc[date]), "cash": state.cash, "receivable_value": state.receivable_value})

    curve = pd.DataFrame(equity_rows).set_index("timestamp")
    fills_df, actions_df, terminal_df = pd.DataFrame(fills), pd.DataFrame(actions), pd.DataFrame(terminal_events)
    episodes = position_episodes(fills_df, actions_df, terminal_df, raw_close.loc[dates[end_index]])
    return OddLotResearchResult(
        equity_curve=curve,
        fills=fills_df,
        corporate_actions=actions_df,
        terminal_events=terminal_df,
        signals=pd.DataFrame(signal_rows),
        episodes=episodes,
        trade_summary=summarize_episodes(episodes),
        metrics=performance_metrics(curve["equity"]),
        config=research,
        backtest_config=config,
    )
