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
    regime_enabled: bool = True
    regime_lookback: int = 60
    factor_neutralization: bool = True
    factor_neutralization_strength: float = 0.50
    factor_lookback: int = 60
    risk_budget_penalty: float = 0.001
    factor_alpha_enabled: bool = False
    factor_alpha_weight: float = 0.30
    factor_ic_horizon: int = 5
    factor_ic_lookback: int = 60
    factor_ic_min_observations: int = 12
    factor_orthogonalization: bool = True
    volatility_target_enabled: bool = False
    target_annual_volatility: float = 0.12
    cvar_control_enabled: bool = False
    max_daily_cvar: float = 0.025
    cvar_confidence: float = 0.95
    drawdown_control_enabled: bool = False
    drawdown_soft_limit: float = 0.10
    drawdown_hard_limit: float = 0.20
    drawdown_min_exposure: float = 0.25


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    base_currency: str | None = None
    max_fx_staleness_days: int = 5
    execution_price_basis: str = "adjusted"
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
