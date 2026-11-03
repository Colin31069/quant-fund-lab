"""Pure diagnostics from frozen simulation evidence; no order or account mutation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .capital import capital_utilization
from .episodes import episode_risk_audits
from .orders import unfilled_order_summary
from .types import OddLotDiagnostics, RiskDiagnosticInputs

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchResult


def inputs_from_result(result: OddLotResearchResult) -> RiskDiagnosticInputs:
    return RiskDiagnosticInputs(
        result.equity_curve, result.fills, result.orders, result.signals, result.episodes,
        result.corporate_actions, result.terminal_events, result.config.strategy, result.config.risk_budget)


def diagnose_odd_lot_account(inputs: RiskDiagnosticInputs) -> OddLotDiagnostics:
    capital = capital_utilization(inputs.equity_curve)
    episodes, episode_issues = episode_risk_audits(inputs)
    orders, order_issues = unfilled_order_summary(inputs)
    capital_issues = tuple(sorted(set(capital.loc[capital.status.eq("unavailable"), "reason"])))
    closed = sum(row.episode_status == "closed" for row in episodes)
    if (any(row.risk_reason == "inconsistent episode position/entitlement state" for row in episodes)
            or len(episodes) != len(inputs.episodes) or episode_issues and not episodes):
        closed = None
    if "status" not in inputs.episodes.columns:
        closed = None
    return OddLotDiagnostics(capital, episodes, orders,
                             tuple(sorted(set(episode_issues + order_issues + capital_issues))), closed)


__all__ = ["OddLotDiagnostics", "RiskDiagnosticInputs", "diagnose_odd_lot_account", "inputs_from_result"]
