"""UI view modules for Quant Fund Lab human-centric dashboard."""
from __future__ import annotations

from .charts import render_equity_charts, render_odd_lot_equity_chart
from .execution_tax_view import render_tax_and_settlement, render_trading_details
from .factor_view import render_factor_laboratory
from .kpi_cards import render_kpi_dashboard
from .ledger_view import render_persistent_ledger
from .odd_lot_view import render_odd_lot_study
from .risk_view import render_risk_and_regime
from .robustness_view import render_robustness_and_walkforward

__all__ = [
    "render_equity_charts",
    "render_factor_laboratory",
    "render_kpi_dashboard",
    "render_odd_lot_equity_chart",
    "render_odd_lot_study",
    "render_persistent_ledger",
    "render_risk_and_regime",
    "render_robustness_and_walkforward",
    "render_tax_and_settlement",
    "render_trading_details",
]
