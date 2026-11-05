from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PrimitiveConfig(BaseModel):
    """Configuration for an individual signal primitive within a strategy."""

    model_config = ConfigDict(frozen=True)

    primitive_id: str
    module_type: Literal[
        "KalmanTrend",
        "OUMeanReversion",
        "ResidualMomentum",
        "RollingStat",
        "FundamentalRatio",
    ]
    params: dict[str, float | int | str]


class ExecutionOverlayConfig(BaseModel):
    """Execution parameters and risk overlays applied on generated signals."""

    model_config = ConfigDict(frozen=True)

    rebalance_frequency: Literal["1D", "1W", "2W", "1M"]
    trade_buffer_delta_weight: float = Field(
        ge=0.0,
        le=0.05,
        description="Minimum weight change required to trade",
    )
    max_single_position_weight: float = Field(ge=0.01, le=0.20)
    target_gross_leverage: float = Field(ge=0.1, le=1.0)
    odd_lot_execution_mode: Literal["avoid_odd_lots", "allow_with_liquidity_cap"]


class StrategyContract(BaseModel):
    """Formal specification of an agentic quantitative strategy."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str
    agent_archetype: Literal[
        "trend",
        "mean_reversion",
        "quality_fundamental",
        "low_beta_defensive",
    ]
    economic_hypothesis: str = Field(
        ...,
        min_length=80,
        description="Falsifiable market mechanism being exploited",
    )
    market_universe: Literal["US_LIQUID_500", "TWSE_TOP_150", "TWSE_MIDCAP"]
    primitives: list[PrimitiveConfig]
    signal_expression: str = Field(
        ...,
        description="Restricted Python expression combining primitive_id outputs",
    )
    regime_gate_expression: str | None = Field(
        None,
        description="Causal scaling expression in [0.0, 1.0]",
    )
    execution_overlay: ExecutionOverlayConfig


class SkepticViolationCode(str, Enum):
    """Violation codes flagged during skeptic audit."""

    NONE = "NONE"
    MULTI_FACTOR_MUTATION = "MULTI_FACTOR_MUTATION"
    EXCESSIVE_COMPLEXITY = "EXCESSIVE_COMPLEXITY"
    FRICTION_UNVIABLE = "FRICTION_UNVIABLE"
    BOOTSTRAP_FRAGILITY = "BOOTSTRAP_FRAGILITY"
    HYPOTHESIS_MISMATCH = "HYPOTHESIS_MISMATCH"
    AD_HOC_PATCHING = "AD_HOC_PATCHING"


class SkepticAuditVerdict(BaseModel):
    """Audit evaluation result produced by the skeptic reviewer agent."""

    model_config = ConfigDict(frozen=True)

    decision: Literal["APPROVE_FOR_OOS", "REVISE", "HARD_REJECT"]
    violation_codes: list[SkepticViolationCode]
    structural_diff_summary: str
    economic_coherence_score: int = Field(ge=1, le=5)
    overfitting_risk_critique: str = Field(..., max_length=600)
    prescribed_single_modification: str | None = None


class GlobalDsrContext(BaseModel):
    """Global Deflated Sharpe Ratio context tracking multiple testing penalty."""

    model_config = ConfigDict(frozen=True)

    universe_total_trials_N: int
    expected_null_max_sharpe_SR0: float
    strategy_deflated_sharpe_DSR: float
    status: str


class CorePerformance(BaseModel):
    """Core risk-adjusted performance metrics."""

    model_config = ConfigDict(frozen=True)

    net_sharpe: float
    gross_sharpe: float
    bootstrap_sharpe_p05: float
    bootstrap_sharpe_p50: float
    max_drawdown_pct: float
    calmar_ratio: float
    annualized_turnover_one_way: float


class RegimeConditionedSharpe(BaseModel):
    """Sharpe ratios conditioned on various market regimes."""

    model_config = ConfigDict(frozen=True)

    volatility_terciles: dict[str, float]
    dispersion_terciles: dict[str, float]
    market_trend_state: dict[str, float]


class DrawdownEpisode(BaseModel):
    """Characteristics of a specific drawdown episode."""

    model_config = ConfigDict(frozen=True)

    id: str
    depth_pct: float
    duration_days: int
    recovery_days: int
    regime_state: str
    driver: str


class ExecutionFrictionDecomposition(BaseModel):
    """Annualized friction and cost drag decomposition in basis points."""

    model_config = ConfigDict(frozen=True)

    gross_alpha_bps: float
    commission_and_tax_drag_bps: float
    slippage_and_tick_quantization_bps: float
    net_alpha_bps: float
    stress_1_5x_cost_net_sharpe: float


class CompactBacktestDiagnostics(BaseModel):
    """Compact backtest diagnostics payload for agentic iterative improvement."""

    model_config = ConfigDict(frozen=True)

    iteration: int
    global_dsr_context: GlobalDsrContext
    core_performance: CorePerformance
    regime_conditioned_sharpe: RegimeConditionedSharpe
    worst_anonymized_drawdown_episodes: list[DrawdownEpisode]
    execution_friction_decomposition_annual_bps: ExecutionFrictionDecomposition
