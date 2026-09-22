from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .config import BacktestConfig
from .data import MarketData
from .execution import PortfolioState, market_for_symbol, rebalance_at_open
from .models import ensemble_alpha
from .portfolio import optimize_weights


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    weights: pd.DataFrame
    alphas: pd.DataFrame


def run_backtest(data: MarketData, config: BacktestConfig | None = None) -> BacktestResult:
    config = config or BacktestConfig()
    markets = {market_for_symbol(symbol) for symbol in data.symbols}
    if len(markets) != 1:
        raise ValueError("mixed US/TW portfolios require FX conversion; run one market per portfolio in MVP")
    strategy = config.strategy
    dates = data.close.index
    if len(dates) < strategy.warmup_days + 2:
        raise ValueError(f"need at least {strategy.warmup_days + 2} bars")

    state = PortfolioState(cash=float(config.initial_cash))
    equity_rows: list[dict[str, float | pd.Timestamp]] = []
    weight_rows: list[pd.Series] = []
    alpha_rows: list[pd.Series] = []
    fill_rows: list[dict[str, object]] = []
    target = pd.Series(0.0, index=data.symbols)

    start_i = strategy.warmup_days - 1
    initial_date = dates[start_i]
    equity_rows.append({"timestamp": initial_date, "equity": config.initial_cash, "cash": state.cash})

    for i in range(start_i, len(dates) - 1):
        signal_date = dates[i]
        execution_date = dates[i + 1]
        close_now = data.close.loc[signal_date]
        open_next = data.open.loc[execution_date]
        close_next = data.close.loc[execution_date]
        volume_next = data.volume.loc[execution_date]

        if (i - start_i) % strategy.rebalance_every == 0:
            history = data.close.iloc[: i + 1]
            alpha_frame = ensemble_alpha(history, strategy)
            alpha = alpha_frame["ensemble"].reindex(data.symbols).fillna(0.0)
            returns = history.pct_change(fill_method=None).tail(strategy.covariance_lookback)
            previous = state.weights(close_now).reindex(data.symbols).fillna(0.0)
            target = optimize_weights(alpha, returns, previous, strategy)

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
                timestamp=pd.Timestamp(execution_date),
                config=config,
            )
            fill_rows.extend(asdict(fill) for fill in fills)

        equity_rows.append(
            {
                "timestamp": execution_date,
                "equity": state.equity(close_next),
                "cash": state.cash,
            }
        )

    equity_curve = pd.DataFrame(equity_rows).set_index("timestamp")
    fills_df = pd.DataFrame(fill_rows)
    weights_df = pd.DataFrame(weight_rows).sort_index() if weight_rows else pd.DataFrame(columns=data.symbols)
    alphas_df = pd.DataFrame(alpha_rows).sort_index() if alpha_rows else pd.DataFrame(columns=data.symbols)
    return BacktestResult(equity_curve=equity_curve, fills=fills_df, weights=weights_df, alphas=alphas_df)
