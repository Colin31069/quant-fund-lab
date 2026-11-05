"""Agentic strategy evolution platform for quant_fund_lab."""

from .canary import LookAheadError, compute_max_warmup_bars, run_canary_test
from .compiler import (
    STATE_FEATURE_NAMES,
    ASTSanitizer,
    CompiledAlphaStrategy,
    PointInTimeView,
)
from .drift_monitor import (
    DriftReport,
    audit_ensemble_drift,
    check_strategy_drift,
    compute_rolling_sharpe,
)
from .evaluator import (
    RawDrawdownEpisode,
    build_compact_diagnostics,
    compute_composite_fitness_score,
    compute_stationary_bootstrap_sharpes,
    extract_top_drawdown_episodes,
    synthesize_drawdown_driver,
)
from .generators import (
    APIStrategyGenerator,
    EvolutionaryStrategyGenerator,
    FileBridgeGenerator,
    extract_json_payload,
)
from .orchestrator import (
    AgenticTournamentOrchestrator,
    TournamentResult,
)
from .personas import COMMON_DSL_SPEC, PERSONA_PROMPTS
from .primitives import (
    CANONICAL_LOOKBACKS,
    OPERATOR_REGISTRY,
    evaluate_primitive,
)
from .reflection_loop import (
    REFLECTION_PROMPT_TEMPLATE,
    ReflectionResult,
    run_reflection_loop,
)
from .runner_mvp import (
    compute_provenance_hash,
    run_strategy_pipeline,
)
from .schemas import (
    CompactBacktestDiagnostics,
    CorePerformance,
    DrawdownEpisode,
    ExecutionFrictionDecomposition,
    ExecutionOverlayConfig,
    GlobalDsrContext,
    PrimitiveConfig,
    RegimeConditionedSharpe,
    SkepticAuditVerdict,
    SkepticViolationCode,
    StrategyContract,
)
from .skeptic import (
    SKEPTIC_SYSTEM_PROMPT,
    audit_strategy,
    compute_structural_diff,
)
from .tournament import (
    DriftedSleeveBook,
    TemporalPartition,
    compute_hrp_weights,
    evaluate_tournament_ensemble,
    prune_correlated_strategies,
)
from .trials_registry import TrialsRegistry

__all__ = [
    "CANONICAL_LOOKBACKS",
    "COMMON_DSL_SPEC",
    "OPERATOR_REGISTRY",
    "PERSONA_PROMPTS",
    "REFLECTION_PROMPT_TEMPLATE",
    "SKEPTIC_SYSTEM_PROMPT",
    "STATE_FEATURE_NAMES",
    "APIStrategyGenerator",
    "ASTSanitizer",
    "AgenticTournamentOrchestrator",
    "CompactBacktestDiagnostics",
    "CompiledAlphaStrategy",
    "CorePerformance",
    "DrawdownEpisode",
    "DriftReport",
    "DriftedSleeveBook",
    "EvolutionaryStrategyGenerator",
    "ExecutionFrictionDecomposition",
    "ExecutionOverlayConfig",
    "FileBridgeGenerator",
    "GlobalDsrContext",
    "LookAheadError",
    "PointInTimeView",
    "PrimitiveConfig",
    "RawDrawdownEpisode",
    "ReflectionResult",
    "RegimeConditionedSharpe",
    "SkepticAuditVerdict",
    "SkepticViolationCode",
    "StrategyContract",
    "TemporalPartition",
    "TournamentResult",
    "TrialsRegistry",
    "audit_ensemble_drift",
    "audit_strategy",
    "build_compact_diagnostics",
    "check_strategy_drift",
    "compute_composite_fitness_score",
    "compute_hrp_weights",
    "compute_max_warmup_bars",
    "compute_provenance_hash",
    "compute_rolling_sharpe",
    "compute_stationary_bootstrap_sharpes",
    "compute_structural_diff",
    "evaluate_primitive",
    "evaluate_tournament_ensemble",
    "extract_json_payload",
    "extract_top_drawdown_episodes",
    "prune_correlated_strategies",
    "run_canary_test",
    "run_reflection_loop",
    "run_strategy_pipeline",
    "synthesize_drawdown_driver",
]
