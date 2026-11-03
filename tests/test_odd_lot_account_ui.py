"""Read-only account inspection and explicit UI actions never silently reset accounts."""
from pathlib import Path

from streamlit.testing.v1 import AppTest
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.inspection import inspect_account
from quant_fund_lab.odd_lot_paper.replay import _replay_account

SOURCE = Path(__file__).resolve().parents[1]


def _app():
    return AppTest.from_string(f"""
import streamlit as st
from quant_fund_lab.odd_lot_paper.ui import render_account_panel
render_account_panel(st, {str(SOURCE)!r})
""")


def _text(app, label, value):
    next(row for row in app.text_input if row.label == label).set_value(value)


def _click(app, label):
    return next(row for row in app.button if row.label == label).click().run(timeout=30)


def test_real_account_inspection_is_readonly_and_ui_displays_shared_audit(tmp_path):
    data, research, base, identity = _fixture()
    path = tmp_path / "account.sqlite"
    _replay_account(path,data,research,base,identity,create=True)
    before = path.read_bytes()
    report = inspect_account(path)
    assert report.audit.passed and report.committed_sessions == 35
    assert report.source_status == "not_checked_by_read_only_inspection"
    app = _app().run(timeout=30)
    assert next(row for row in app.radio if row.label == "帳戶操作").value == "安全續跑既有帳戶"
    _text(app,"零股帳戶 SQLite 路徑",str(path))
    app = _click(app,"核驗並讀取帳戶")
    assert not app.exception and any("稽核通過" in row.value for row in app.success)
    assert any(row.value == "35" for row in app.metric)
    assert path.read_bytes() == before


def test_missing_account_inspection_never_creates_a_file(tmp_path):
    path = tmp_path / "missing.sqlite"
    app = _app().run(timeout=30)
    _text(app,"零股帳戶 SQLite 路徑",str(path))
    app = _click(app,"核驗並讀取帳戶")
    assert app.error and not app.exception and not path.exists()


def test_failed_resume_does_not_retry_as_creation_or_run_on_rerender(tmp_path,monkeypatch):
    calls = []
    def fail(*args,**kwargs):
        calls.append(kwargs)
        raise ValueError("fixture source changed")
    monkeypatch.setattr("quant_fund_lab.odd_lot_paper.ui.replay_registered_account",fail)
    app = _app().run(timeout=30)
    _text(app,"凍結協議目錄",str(tmp_path / "protocol"))
    _text(app,"候選 ID","a"*64)
    app = _click(app,"執行凍結歷史重播")
    assert len(calls) == 1 and calls[0]["create"] is False
    assert any("source changed" in row.value for row in app.error)
    app.run(timeout=30)
    assert len(calls) == 1


def test_main_ui_exposes_account_panel_without_launching_research():
    app = AppTest.from_file(str(SOURCE / "src/quant_fund_lab/ui.py")).run(timeout=30)
    app = next(row for row in app.checkbox if row.label == "零股持久化歷史帳戶").set_value(True).run(timeout=30)
    assert not app.exception
    assert any(row.label == "核驗並讀取帳戶" for row in app.button)


def test_rebuild_requires_new_path_and_does_not_run_on_rerender(tmp_path,monkeypatch):
    calls = []
    def fail(*args,**kwargs):
        calls.append((args,kwargs))
        raise ValueError("rebuild parent differs")
    monkeypatch.setattr("quant_fund_lab.odd_lot_paper.ui.rebuild_registered_account",fail)
    app = _app().run(timeout=30)
    _text(app,"凍結協議目錄",str(tmp_path/"protocol"))
    _text(app,"候選 ID","a"*64)
    app = _click(app,"保留原帳戶並重建至新路徑")
    assert not calls and any("全新帳戶路徑" in row.value for row in app.error)
    _text(app,"零股帳戶 SQLite 路徑",str(tmp_path/"parent.sqlite"))
    _text(app,"重建目的帳戶（必須為新路徑）",str(tmp_path/"new.sqlite"))
    app = _click(app,"保留原帳戶並重建至新路徑")
    assert len(calls) == 1 and calls[0][0][:2] == (str(tmp_path/"parent.sqlite"),str(tmp_path/"new.sqlite"))
    assert any("parent differs" in row.value for row in app.error)
    app.run(timeout=30)
    assert len(calls) == 1 and not app.exception
