"""Test visual polish and executive KPI metrics in odd-lot study view."""
from __future__ import annotations

import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    run_frozen_odd_lot_study,
)


def test_odd_lot_study_view_renders_executive_kpis_and_tabs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        data = synthetic_market_data(("2330.TW", "2317.TW", "0050.TW"), periods=300, seed=42)
        root = freeze_odd_lot_study(
            data,
            tmp_path / "studies",
            symbols=("2330.TW", "2317.TW"),
            benchmark="0050.TW",
            source="synthetic",
        )
        study = run_frozen_odd_lot_study(root)
        report = export_odd_lot_study_report(root, study)

        script = f"""
import streamlit as st
from pathlib import Path
from quant_fund_lab.odd_lot_study import run_frozen_odd_lot_study
from quant_fund_lab.ui_views.odd_lot_view import render_odd_lot_study

root = Path({str(root)!r})
report = Path({str(report)!r})
study = run_frozen_odd_lot_study(root)
render_odd_lot_study(study, root, report, "synthetic")
"""
        app = AppTest.from_string(script).run(timeout=15)
        assert not app.exception and not app.error

        # 1. Executive KPI Metrics verification
        metric_labels = [m.label for m in app.metric]
        assert "累積總報酬" in metric_labels
        assert "年化報酬率" in metric_labels
        assert "夏普比率" in metric_labels
        assert "最大回撤 (MaxDD)" in metric_labels
        assert "交易勝率" in metric_labels
        assert "交易次數" in metric_labels

        # 2. Selectbox for details verification
        assert any(s.label == "研究明細" for s in app.selectbox)

        # 3. 5 Tabs verification
        tab_labels = [t.label for t in app.tabs]
        expected_tabs = ["完整與未平倉交易", "進出場訊號", "成交紀錄", "限價委託", "交割明細"]
        assert all(t in tab_labels for t in expected_tabs)

        # 4. Warnings and captions
        assert any("存活者偏差" in w.value for w in app.warning)
        assert any("合成測試資料" in w.value for w in app.warning)


def test_odd_lot_study_view_empty_comparison_graceful():
    script = """
from pathlib import Path
import pandas as pd
import streamlit as st
from quant_fund_lab.odd_lot_study import OddLotStudyResult
from quant_fund_lab.ui_views.odd_lot_view import render_odd_lot_study

empty_study = OddLotStudyResult(
    study_id="empty-id",
    dataset_id="empty-ds",
    comparison=pd.DataFrame(),
    sensitivity=pd.DataFrame(),
    results={},
    unavailable={"validation/ensemble": "insufficient data"},
    holdout_untouched=True,
)
render_odd_lot_study(empty_study, Path("/tmp/frozen"), Path("/tmp/report"), "synthetic")
"""
    app = AppTest.from_string(script).run(timeout=10)
    assert not app.exception and not app.error
    assert len(app.metric) == 0


def test_render_odd_lot_equity_chart_edge_cases():
    script = """
import pandas as pd
import streamlit as st
from quant_fund_lab.ui_views.charts import render_odd_lot_equity_chart

# Empty frame
render_odd_lot_equity_chart(pd.DataFrame())

# Single observation
dates = pd.date_range("2024-01-01", periods=1)
render_odd_lot_equity_chart(pd.DataFrame({"equity": [100000.0]}, index=dates))

# Valid series
dates_multi = pd.date_range("2024-01-01", periods=5)
curve = pd.DataFrame(
    {"equity": [100000.0, 102000.0, 99000.0, 101000.0, 103000.0],
     "settled_cash": [50000.0, 50000.0, 48000.0, 48000.0, 52000.0]},
    index=dates_multi,
)
render_odd_lot_equity_chart(curve)
"""
    app = AppTest.from_string(script).run(timeout=10)
    assert not app.exception and not app.error
    assert any("無足夠淨值數據" in info.value for info in app.info)
    assert any("淨值數據點不足兩筆" in info.value for info in app.info)
