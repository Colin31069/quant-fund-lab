"""AST compiler, PointInTimeView, and CompiledAlphaStrategy for agentic quant fund lab."""

from __future__ import annotations

import ast
from types import CodeType
from typing import Any

import numpy as np
import pandas as pd

from quant_fund_lab.agentic.primitives import (
    CANONICAL_LOOKBACKS,
    OPERATOR_REGISTRY,
    clip,
    evaluate_primitive,
)
from quant_fund_lab.agentic.schemas import PrimitiveConfig, StrategyContract
from quant_fund_lab.data import MarketData

STATE_FEATURE_NAMES: frozenset[str] = frozenset({
    "ret_1d", "vol_21d", "turnover_ratio_21d", "effective_tick_bps",
    "adv_participation_bps", "odd_lot_adv_ratio", "mkt_vol_pct_252d",
    "mkt_disp_pct_252d", "mkt_autocorr_21d",
})

_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call,
    ast.Name, ast.Constant, ast.Compare, ast.Load, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.BitAnd, ast.BitOr, ast.USub,
    ast.UAdd, ast.Not, ast.Invert, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)

_ALLOWED_NODE_TYPES = frozenset(_ALLOWED_NODES)
_TS_OPERATORS = frozenset({"ts_mean", "ts_std", "ts_zscore", "ts_delta", "ts_decay_linear"})


class ASTSanitizer:
    """Validates and compiles signal and regime expressions under strict security boundaries."""

    @staticmethod
    def _ast_depth(node: ast.AST) -> int:
        children = list(ast.iter_child_nodes(node))
        return 1 + max((ASTSanitizer._ast_depth(c) for c in children), default=0)

    @classmethod
    def validate(cls, expr: str, allowed_names: set[str] | frozenset[str] | None = None) -> ast.Expression:
        try:
            tree = ast.parse(expr.strip())
        except SyntaxError as exc:
            raise ValueError(f"Invalid syntax in expression: {exc}") from exc

        # Check hard bans and node whitelist
        for node in ast.walk(tree):
            node_type = type(node)
            if node_type in (ast.Import, ast.ImportFrom):
                raise ValueError("Imports are forbidden in alpha expressions")
            if node_type is ast.Attribute:
                raise ValueError("Attribute access is forbidden in alpha expressions")
            if node_type is ast.Subscript:
                raise ValueError("Subscript/slicing is forbidden in alpha expressions")
            if node_type in (ast.For, ast.While, ast.AsyncFor):
                raise ValueError("Loops are forbidden in alpha expressions")
            if node_type not in _ALLOWED_NODE_TYPES:
                raise ValueError(f"Forbidden AST node: {node_type.__name__}")

            if isinstance(node, ast.Constant):
                val_type = type(node.value)
                if val_type is str:
                    raise ValueError(f"String/date literals are forbidden: {node.value!r}")
                if val_type not in (int, float, bool):
                    raise ValueError(f"Literal {node.value!r} of type {val_type} is forbidden")

            if isinstance(node, ast.Call):
                if type(node.func) is ast.Attribute:
                    raise ValueError("Attribute access is forbidden in alpha expressions")
                if type(node.func) is not ast.Name:
                    raise ValueError("Only direct whitelisted function calls are allowed")
                fn_name = node.func.id
                if fn_name not in OPERATOR_REGISTRY:
                    raise ValueError(f"Function '{fn_name}' is not in the operator whitelist")
                if fn_name in _TS_OPERATORS:
                    d_val: int | None = None
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and type(node.args[1].value) is int:
                        d_val = node.args[1].value
                    for kw in node.keywords:
                        if kw.arg == "d" and isinstance(kw.value, ast.Constant) and type(kw.value.value) is int:
                            d_val = kw.value.value
                    if d_val is None or d_val not in CANONICAL_LOOKBACKS:
                        raise ValueError(f"Lookback 'd' in '{fn_name}' must be an integer in CANONICAL_LOOKBACKS: {sorted(CANONICAL_LOOKBACKS)}")

        if len(tree.body) != 1 or type(tree.body[0]) is not ast.Expr:
            raise ValueError("Expression must be a single expression")

        expr_node = ast.Expression(body=tree.body[0].value)
        # Distinct primitive/feature names (excluding function names)
        var_names = {
            n.id for n in ast.walk(expr_node) if type(n) is ast.Name and n.id not in OPERATOR_REGISTRY
        }
        if len(var_names) > 3:
            raise ValueError(f"Expression has {len(var_names)} distinct primitive names; maximum allowed is 3: {sorted(var_names)}")

        depth = cls._ast_depth(expr_node.body)
        if depth > 4:
            raise ValueError(f"AST depth {depth} exceeds maximum allowed depth of 4")

        if allowed_names is not None:
            disallowed = var_names - set(allowed_names)
            if disallowed:
                raise ValueError(f"Variables {sorted(disallowed)} are not in allowed primitives/features")

        return expr_node

    @classmethod
    def compile(cls, expr: str, allowed_names: set[str] | frozenset[str] | None = None) -> CodeType:
        tree = cls.validate(expr, allowed_names=allowed_names)
        return compile(tree, filename="<alpha_expression>", mode="eval")

    @classmethod
    def validate_contract(cls, contract: StrategyContract) -> bool:
        """Validate all signal and regime expressions within a strategy contract."""
        allowed = {p.primitive_id for p in contract.primitives} | STATE_FEATURE_NAMES
        cls.validate(contract.signal_expression, allowed_names=allowed)
        if contract.regime_gate_expression:
            cls.validate(contract.regime_gate_expression, allowed_names=allowed)
        return True


class PointInTimeView:
    """Pre-evaluation causal state builder and operator namespace container."""

    def __init__(self, data: MarketData, primitives: list[PrimitiveConfig]) -> None:
        close_ffill = data.close.ffill(limit=5)
        volume_ffill = data.volume.ffill(limit=5).fillna(0.0)
        self.tradable_mask: pd.DataFrame = np.isfinite(data.close) & (data.volume > 0)

        # 1. Evaluate configured primitives
        self.namespace: dict[str, Any] = dict(OPERATOR_REGISTRY)
        for prim in primitives:
            self.namespace[prim.primitive_id] = evaluate_primitive(
                prim.module_type, prim.params, close_ffill, volume_ffill
            )

        # 2. Compute stationary state features
        ret_1d = (close_ffill / close_ffill.shift(1) - 1.0).fillna(0.0)
        vol_21d = (ret_1d.rolling(21, min_periods=2).std(ddof=1) * np.sqrt(252)).fillna(0.0)
        med_vol = volume_ffill.rolling(21, min_periods=2).median()
        turnover_ratio_21d = (volume_ffill / np.maximum(med_vol, 1e-8)).fillna(1.0)

        # Effective tick bps
        is_twse = (data.exchange == "TWSE" or data.base_currency == "TWD")
        if is_twse:
            conds = [close_ffill < 10.0, close_ffill < 50.0, close_ffill < 100.0, close_ffill < 500.0, close_ffill < 1000.0]
            choices = [0.01, 0.05, 0.10, 0.50, 1.0]
            tick_size = pd.DataFrame(np.select(conds, choices, default=5.0), index=close_ffill.index, columns=close_ffill.columns)
        else:
            tick_size = pd.DataFrame(0.01, index=close_ffill.index, columns=close_ffill.columns)
        effective_tick_bps = (tick_size / np.maximum(close_ffill, 1e-8) * 10000.0).fillna(0.0)

        # ADV participation bps (100,000 standard notional / median ADV)
        med_adv = (close_ffill * volume_ffill).rolling(21, min_periods=2).median()
        adv_participation_bps = (100_000.0 / np.maximum(med_adv, 1.0) * 10_000.0).fillna(0.0)

        # Odd lot ADV ratio
        odd_lot_vol = getattr(data, "odd_lot_volume", None)
        if odd_lot_vol is not None:
            odd_lot_adv_ratio = (odd_lot_vol / np.maximum(volume_ffill, 1.0)).fillna(1.0)
        else:
            odd_lot_adv_ratio = pd.DataFrame(1.0, index=close_ffill.index, columns=close_ffill.columns)

        # Market-wide aggregates
        mkt_ret = ret_1d.mean(axis=1)
        mkt_vol = (mkt_ret.rolling(21, min_periods=2).std(ddof=1) * np.sqrt(252)).fillna(0.0)
        n_bars = len(close_ffill)
        mkt_vol_pct_s = mkt_vol.rolling(252, min_periods=min(21, n_bars)).apply(
            lambda w: float(np.mean(w[-1] >= w)), raw=True
        ).fillna(0.5)
        mkt_vol_pct_252d = pd.DataFrame(
            np.tile(mkt_vol_pct_s.to_numpy()[:, None], (1, close_ffill.shape[1])),
            index=close_ffill.index,
            columns=close_ffill.columns,
        )

        mkt_disp = ret_1d.std(axis=1, ddof=1).fillna(0.0)
        mkt_disp_pct_s = mkt_disp.rolling(252, min_periods=min(21, n_bars)).apply(
            lambda w: float(np.mean(w[-1] >= w)), raw=True
        ).fillna(0.5)
        mkt_disp_pct_252d = pd.DataFrame(
            np.tile(mkt_disp_pct_s.to_numpy()[:, None], (1, close_ffill.shape[1])),
            index=close_ffill.index,
            columns=close_ffill.columns,
        )

        mkt_ac_s = mkt_ret.rolling(21, min_periods=min(5, n_bars)).corr(mkt_ret.shift(1)).fillna(0.0)
        mkt_autocorr_21d = pd.DataFrame(
            np.tile(mkt_ac_s.to_numpy()[:, None], (1, close_ffill.shape[1])),
            index=close_ffill.index,
            columns=close_ffill.columns,
        )

        self.namespace.update({
            "ret_1d": ret_1d,
            "vol_21d": vol_21d,
            "turnover_ratio_21d": turnover_ratio_21d,
            "effective_tick_bps": effective_tick_bps,
            "adv_participation_bps": adv_participation_bps,
            "odd_lot_adv_ratio": odd_lot_adv_ratio,
            "mkt_vol_pct_252d": mkt_vol_pct_252d,
            "mkt_disp_pct_252d": mkt_disp_pct_252d,
            "mkt_autocorr_21d": mkt_autocorr_21d,
        })


class CompiledAlphaStrategy:
    """Compiled, ready-to-evaluate agentic strategy contract."""

    def __init__(self, contract: StrategyContract) -> None:
        self.contract = contract
        allowed = {p.primitive_id for p in contract.primitives} | STATE_FEATURE_NAMES
        self.signal_code = ASTSanitizer.compile(contract.signal_expression, allowed_names=allowed)
        self.regime_gate_code = (
            ASTSanitizer.compile(contract.regime_gate_expression, allowed_names=allowed)
            if contract.regime_gate_expression
            else None
        )
        self._cached_weights: pd.DataFrame | None = None

    @classmethod
    def from_contract(cls, contract: StrategyContract) -> CompiledAlphaStrategy:
        """Construct a CompiledAlphaStrategy from a validated contract."""
        return cls(contract)

    def precompute_panel(self, data: MarketData) -> pd.DataFrame:
        view = PointInTimeView(data, self.contract.primitives)
        raw_signal = eval(self.signal_code, {"__builtins__": {}}, view.namespace)
        if not isinstance(raw_signal, pd.DataFrame):
            raw_signal = pd.DataFrame(raw_signal, index=data.close.index, columns=data.close.columns)

        if self.regime_gate_code is not None:
            gate = eval(self.regime_gate_code, {"__builtins__": {}}, view.namespace)
            gate_clipped = clip(gate, 0.0, 1.0)
            if isinstance(gate_clipped, pd.Series):
                raw_signal = raw_signal.mul(gate_clipped, axis=0)
            else:
                raw_signal = raw_signal * gate_clipped

        # 3-stage missingness protocol: any NaN or non-tradable asset set to 0.0
        signal = raw_signal.where(np.isfinite(raw_signal), 0.0)
        signal = signal.where(view.tradable_mask, 0.0)

        # Portfolio weight normalization and clipping
        l1 = signal.abs().sum(axis=1)
        tgt_lev = self.contract.execution_overlay.target_gross_leverage
        max_pos = self.contract.execution_overlay.max_single_position_weight

        norm_weights = signal.div(l1.replace(0.0, np.nan), axis=0).fillna(0.0) * tgt_lev
        weights = norm_weights.clip(lower=-max_pos, upper=max_pos)
        self._cached_weights = weights
        return weights

    def __call__(self, data: MarketData, as_of_date: pd.Timestamp) -> pd.Series:
        if self._cached_weights is not None and as_of_date in self._cached_weights.index:
            return self._cached_weights.loc[as_of_date]
        sub = data.slice(end=as_of_date)
        panel = self.precompute_panel(sub)
        return panel.loc[as_of_date]


__all__ = [
    "STATE_FEATURE_NAMES",
    "ASTSanitizer",
    "CompiledAlphaStrategy",
    "PointInTimeView",
]
