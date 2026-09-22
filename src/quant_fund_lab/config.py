from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketCostConfig:
    """Configurable execution costs in basis points unless otherwise noted."""

    commission_bps: float
    sell_tax_bps: float = 0.0
    sec_fee_per_million: float = 0.0
    slippage_bps: float = 5.0
    impact_coefficient: float = 0.10
    max_participation: float = 0.05
    lot_size: int = 1
    price_limit_pct: float | None = None


@dataclass(frozen=True)
class StrategyConfig:
    warmup_days: int = 120
    covariance_lookback: int = 60
    ou_lookback: int = 60
    residual_momentum_lookback: int = 60
    kalman_weight: float = 0.45
    ou_weight: float = 0.30
    residual_momentum_weight: float = 0.25
    risk_aversion: float = 4.0
    turnover_penalty: float = 0.002
    covariance_shrinkage: float = 0.35
    alpha_daily_scale: float = 0.002
    max_weight: float = 0.25
    rebalance_every: int = 5


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    us_costs: MarketCostConfig = field(
        default_factory=lambda: MarketCostConfig(
            commission_bps=0.0,
            sell_tax_bps=0.0,
            sec_fee_per_million=20.60,
            slippage_bps=3.0,
        )
    )
    tw_costs: MarketCostConfig = field(
        default_factory=lambda: MarketCostConfig(
            commission_bps=14.25,
            sell_tax_bps=30.0,
            sec_fee_per_million=0.0,
            slippage_bps=5.0,
            lot_size=1_000,
            price_limit_pct=0.10,
        )
    )
