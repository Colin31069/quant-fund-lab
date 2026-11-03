"""The UI presents the runner's decision rather than deriving its own status."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


def readiness_app():
    import streamlit as st

    from quant_fund_lab.twse_quality.ui import render_readiness

    render_readiness(st, {
        "periods": [{"period": "validation", "start": "2024-01-01", "end": "2024-12-31",
                     "status": "unknown", "warmup": {"required": 120, "verified_sessions": []},
                     "blocking_ids": ["finding-1"]}],
        "findings": [{"finding_id": "finding-1", "code": "unknown", "symbol": "*",
                      "start": "2024-01-01", "end": "2024-12-31", "detail": "Calendar evidence missing",
                      "depends_on": [], "source_refs": []}],
    }, "frozen-decision-123")


def test_unknown_frozen_decision_is_visible_with_same_identity():
    app = AppTest.from_function(readiness_app).run(timeout=12)
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["status"] == "unknown"
    assert app.dataframe[0].value.iloc[0]["warmup_verified"] == 0
    assert any("frozen-decision-123" in item.value for item in app.caption)
    assert app.dataframe[1].value.iloc[0]["affected_periods"] == "validation"


def test_provider_source_is_explicit_and_automation_stays_disabled():
    path = Path(__file__).resolve().parents[1] / "src" / "quant_fund_lab" / "ui.py"
    app = AppTest.from_file(str(path)).run(timeout=12)
    app = next(item for item in app.checkbox if item.label == "十萬元台股零股策略研究").set_value(True).run(timeout=12)
    app = next(item for item in app.selectbox if item.label == "資料來源").set_value("TWSE＋FinMind 本機資料").run(timeout=12)
    assert not app.exception
    assert any(item.label == "FinMind 資料包目錄" for item in app.text_input)
    assert not next(item for item in app.checkbox if item.label == "使用已授權的 TWSE 自動下載").value
