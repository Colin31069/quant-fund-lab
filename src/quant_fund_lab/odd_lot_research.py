"""Daily-bar Taiwan odd-lot research with explicit, conservative proxy assumptions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .config import BacktestConfig
from .corporate_actions import (
    CashInLieuReceivable,
)
from .data import MarketData
from .execution import (
    PortfolioState,
    prior_session_liquidity,
)
from .market_calendar import require_valid_daily_sessions
from .odd_lot_execution import (
    default_instrument_rules,
    validate_instrument_rules,
)
from .odd_lot_paper import strategy as _research_strategy
from .odd_lot_paper.bridge import HistoricalSessionState
from .odd_lot_paper.engine_records import EngineOrder as _Order
from .odd_lot_paper.engine_records import EngineStop as _Stop
from .odd_lot_paper.session import OddLotSessionInput, run_odd_lot_session
from .trade_analytics import position_episodes, summarize_episodes

# Preserve existing helper lookup and test injection points after colocation.
_entry_quantity = _research_strategy._entry_quantity
_estimated_risk = _research_strategy._estimated_risk
_targets = _research_strategy._targets


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
    commission_bps: float = 14.25
    limit_offset: float = 0.01
    fill_fraction: float = 0.50
    fee_rounding: str = "fractional"
    max_participation: float = 0.05
    impact_coefficient: float = 0.10
    instrument_rules: dict[str, dict] = field(default_factory=default_instrument_rules)

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
        if not all(np.isfinite(x) for x in (self.volatility_multiplier, self.min_commission,
                   self.slippage_bps, self.commission_bps, self.limit_offset, self.fill_fraction,
                   self.max_participation, self.impact_coefficient)):
            raise ValueError("execution assumptions must be finite")
        if self.commission_bps < 0 or not 0 <= self.limit_offset < 1 or not 0 < self.fill_fraction <= 1:
            raise ValueError("invalid limit, fill or commission assumption")
        if not 0 < self.max_participation <= 1 or self.impact_coefficient < 0:
            raise ValueError("invalid liquidity or impact assumption")
        if self.fee_rounding not in {"fractional", "floor", "nearest"}:
            raise ValueError("invalid fee rounding assumption")
        if not isinstance(self.instrument_rules, dict):
            raise TypeError("instrument rules must be a mapping")
        validate_instrument_rules(list(self.instrument_rules), self.instrument_rules)


@dataclass(frozen=True)
class OddLotResearchResult:
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    orders: pd.DataFrame
    settlements: pd.DataFrame
    corporate_actions: pd.DataFrame
    terminal_events: pd.DataFrame
    signals: pd.DataFrame
    episodes: pd.DataFrame
    trade_summary: dict[str, float | int | None]
    metrics: dict[str, float]
    config: OddLotResearchConfig
    backtest_config: BacktestConfig


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
            commission_bps=research.commission_bps,
            max_participation=research.max_participation,
            impact_coefficient=research.impact_coefficient,
        ),
        strategy=replace(
            base.strategy,
            max_weight=research.max_weight,
            rebalance_every=research.rebalance_every,
        ),
    )


def run_odd_lot_research(
    data: MarketData,
    research: OddLotResearchConfig | None = None,
    base_config: BacktestConfig | None = None,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    _passive_without_risk_estimate: bool = False,
) -> OddLotResearchResult:
    """Run a fresh, long-only account. Prices and volume are explicit proxies.

    Stops use close observations and are submitted for the next session. They are
    not an intraday stop order and cannot guarantee the modeled loss budget.
    """
    research = research or OddLotResearchConfig()
    if _passive_without_risk_estimate and (research.strategy != "equal_weight" or len(data.symbols) != 1):
        raise ValueError("passive benchmark entry requires one asset and the passive strategy")
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
    validate_instrument_rules(data.symbols, research.instrument_rules)
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
    orders: list[dict] = []
    settlements: list[dict] = []
    actions: list[dict] = []
    terminal_events: list[dict] = []
    signal_rows: list[dict] = []
    equity_rows = [{"timestamp": dates[start_index], "equity": state.cash, "cash": state.cash,
                    "settled_cash": state.cash, "buy_payables": 0.0,
                    "sale_receivables": 0.0, "sale_payables": 0.0, "receivable_value": 0.0}]
    passive_submitted = False

    for i in range(start_index, end_index):
        transition = run_odd_lot_session(OddLotSessionInput(
            HistoricalSessionState(state, stops, pending, terminated, receivables, settlements,
                                   passive_submitted),
            data, research, config, i, start_index, liquidity, _passive_without_risk_estimate))
        runtime = transition.runtime
        state, stops, pending = runtime.portfolio, runtime.stops, runtime.pending
        terminated, receivables = runtime.terminated, runtime.receivables
        settlements, passive_submitted = runtime.settlements, runtime.passive_submitted
        signal_rows.extend(transition.signals)
        orders.extend(transition.orders)
        fills.extend(transition.fills)
        actions.extend(transition.actions)
        terminal_events.extend(transition.terminal_events)
        equity_rows.append(transition.nav)

    curve = pd.DataFrame(equity_rows).set_index("timestamp")
    fills_df, actions_df, terminal_df = pd.DataFrame(fills), pd.DataFrame(actions), pd.DataFrame(terminal_events)
    episodes = position_episodes(fills_df, actions_df, terminal_df, raw_close.loc[dates[end_index]])
    return OddLotResearchResult(
        equity_curve=curve,
        fills=fills_df,
        orders=pd.DataFrame(orders),
        settlements=pd.DataFrame([
            {**{key: value for key, value in item.items() if key != "due_session_index"},
             "status": "settled" if item["settled_at"] is not None else "pending_end_of_data",
             "sessions_remaining": max(0, item["due_session_index"] - end_index)}
            for item in settlements
        ]),
        corporate_actions=actions_df,
        terminal_events=terminal_df,
        signals=pd.DataFrame(signal_rows),
        episodes=episodes,
        trade_summary=summarize_episodes(episodes),
        metrics=performance_metrics(curve["equity"]),
        config=research,
        backtest_config=config,
    )
