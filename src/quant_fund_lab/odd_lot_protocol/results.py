"""Fingerprint numerical business outputs independently of report UUIDs and timestamps."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from numbers import Integral, Real

import pandas as pd

from ..odd_lot_study import OddLotStudyResult
from ..twse_quality.types import fingerprint


def _value(value: object) -> object:
    if value is None:
        return ["none"]
    if value is pd.NA:
        return ["pd.NA"]
    if value is pd.NaT:
        return ["NaT"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, Integral):
        return ["int", str(value)]
    if isinstance(value, Real):
        return ["float", float(value).hex()]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return ["date", value.isoformat()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (tuple, list)):
        return ["sequence", [_value(v) for v in value]]
    if isinstance(value, dict):
        return ["mapping", [[str(k), _value(v)] for k, v in sorted(value.items())]]
    raise TypeError(f"unsupported numerical result value: {type(value).__name__}")


def _frame(frame: pd.DataFrame) -> dict:
    return {"columns": [_value(c) for c in frame.columns],
            "index_names": list(frame.index.names), "index": [_value(v) for v in frame.index],
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            "rows": [[_value(v) for v in row] for row in frame.itertuples(index=False, name=None)]}


def numerical_result_fingerprint(study: OddLotStudyResult) -> str:
    """Preserve exact float values and missing-value kinds, excluding output locations."""
    payload = {"schema_version": 1, "study_id": study.study_id, "dataset_id": study.dataset_id,
               "readiness_fingerprint": study.readiness_fingerprint,
               "comparison": _frame(study.comparison), "sensitivity": _frame(study.sensitivity),
               "unavailable": study.unavailable, "results": []}
    for (period, strategy), result in sorted(study.results.items()):
        payload["results"].append({
            "period": period, "strategy": strategy,
            "frames": {name: _frame(getattr(result, name)) for name in (
                "equity_curve", "fills", "orders", "settlements", "corporate_actions",
                "terminal_events", "signals", "episodes",
            )},
            "metrics": _value(result.metrics), "trade_summary": _value(result.trade_summary),
            "research_config": asdict(result.config), "backtest_config": asdict(result.backtest_config),
        })
    if study.benchmark_specs is not None:
        payload["benchmark_specs"] = study.benchmark_specs
    if study.risk_diagnostics is not None:
        payload["risk_diagnostics"] = _value(study.risk_diagnostics.to_dict())
    if study.matched_sensitivity is not None:
        payload["matched_sensitivity"] = _value(study.matched_sensitivity.to_dict())
        payload["scenario_accounts"] = [
            {"scenario_id": key[0], "strategy": key[1],
             "frames": {name: _frame(getattr(result, name)) for name in (
                 "equity_curve", "fills", "orders", "settlements", "corporate_actions",
                 "terminal_events", "signals", "episodes")},
             "research_config": asdict(result.config), "backtest_config": asdict(result.backtest_config)}
            for key, result in sorted(study.matched_sensitivity.accounts.items())]
    return fingerprint(payload)
