"""Forward forms submit explicitly, preserve safe mode and show backend states."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from test_odd_lot_account_ui import _click, _text

from quant_fund_lab.odd_lot_paper.forward_workflow import ObservationAccountResult

SOURCE = Path(__file__).resolve().parents[1]


def _app():
    return AppTest.from_string(f"""
import streamlit as st
from quant_fund_lab.odd_lot_paper.forward_ui import render_observation_panel
render_observation_panel(st, {str(SOURCE)!r})
""")


def test_missing_plan_read_is_readonly_and_rerender_never_executes(tmp_path, monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError("rerender must not execute")
    monkeypatch.setattr("quant_fund_lab.odd_lot_paper.forward_ui.run_observation_account",forbidden)
    app = _app().run(timeout=30)
    assert next(row for row in app.radio if row.label == "前向帳戶操作").value == "安全續跑既有前向帳戶"
    _text(app,"前向計畫目錄",str(tmp_path / "missing"))
    app = _click(app,"讀取前向計畫")
    assert app.error and not app.exception and list(tmp_path.iterdir()) == []
    app.run(timeout=30)
    assert not app.exception


@pytest.mark.parametrize("status",["pending","blocked","active"])
def test_backend_state_and_explicit_submit_do_not_retry_on_rerender(tmp_path,monkeypatch,status):
    calls = []
    def run(*args,**kwargs):
        calls.append(kwargs)
        replay = SimpleNamespace(checkpoint=SimpleNamespace(session="2026-10-30"),committed_sessions=1) if status == "active" else None
        return ObservationAccountResult("a"*64,status,"2026-10-30",() if status == "active" else ("fixture_reason",),replay)
    monkeypatch.setattr("quant_fund_lab.odd_lot_paper.forward_ui.run_observation_account",run)
    app = _app().run(timeout=30)
    _text(app,"前向計畫目錄",str(tmp_path / "plan"))
    _text(app,"觀察截止日（YYYY-MM-DD）","2026-10-30")
    app = _click(app,"核驗資料並執行虛擬觀察")
    assert not app.exception and len(calls) == 1 and calls[0]["create"] is False
    assert app.success if status == "active" else app.info if status == "pending" else app.warning
    app.run(timeout=30)
    assert len(calls) == 1


def test_failure_never_falls_back_to_account_creation(tmp_path,monkeypatch):
    calls = []
    def fail(*args,**kwargs):
        calls.append(kwargs)
        raise ValueError("source prefix changed")
    monkeypatch.setattr("quant_fund_lab.odd_lot_paper.forward_ui.run_observation_account",fail)
    app = _app().run(timeout=30)
    _text(app,"前向計畫目錄",str(tmp_path / "plan"))
    _text(app,"觀察截止日（YYYY-MM-DD）","2026-10-30")
    app = _click(app,"核驗資料並執行虛擬觀察")
    assert not app.exception and any("prefix changed" in row.value for row in app.error)
    assert len(calls) == 1 and calls[0]["create"] is False


def test_main_ui_exposes_forward_forms():
    app = AppTest.from_file(str(SOURCE / "src/quant_fund_lab/ui.py")).run(timeout=30)
    app = next(row for row in app.checkbox if row.label == "零股前向虛擬觀察").set_value(True).run(timeout=30)
    assert not app.exception
    assert any(row.label == "核驗決策並註冊前向計畫" for row in app.button)
    assert any(row.label == "核驗資料並執行虛擬觀察" for row in app.button)
