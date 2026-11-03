"""Real Streamlit form runs the common read-only catalog audit once per action."""
from pathlib import Path

from streamlit.testing.v1 import AppTest
from test_rights_request_catalog_main import setup

from quant_fund_lab.odd_lot_rights.catalog_workflow import commit_catalog_day
from quant_fund_lab.odd_lot_rights.day_request_archive import archive_day_request
from quant_fund_lab.odd_lot_rights.request_catalog import append_request_catalog
from quant_fund_lab.odd_lot_rights.request_catalog_files import freeze_request_catalog


def app():
    return AppTest.from_string("""
import streamlit as st
from quant_fund_lab.odd_lot_rights.inspection_ui import render_rights_inspection
render_rights_inspection(st)
""").run(timeout=30)


def text(ui, label, value):
    next(row for row in ui.text_input if row.label == label).set_value(value)


def test_real_form_reads_existing_account_and_rerender_does_not_repeat_audit(tmp_path, monkeypatch):
    from quant_fund_lab.odd_lot_rights import inspection_ui

    _, ledger, catalog, day = setup(tmp_path, monkeypatch)
    archive = archive_day_request(tmp_path/"requests", day)
    child = append_request_catalog(catalog, archive, ledger.verify()[0])
    frozen = freeze_request_catalog(tmp_path/"catalogs", child, previous=catalog)
    commit_catalog_day(ledger, child, tmp_path/"requests")
    ledger.close()
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    ui = app()
    assert not ui.exception and not ui.success
    for label, value in (("權利帳戶 SQLite 路徑", tmp_path/"ledger.sqlite"),
        ("權利請求目錄檔案", frozen.path), ("外部保存的目錄 SHA-256", frozen.sha256),
        ("封存每日請求資料夾", tmp_path/"requests")):
        text(ui, label, str(value))
    ui.button[0].click().run(timeout=30)
    assert not ui.exception and any("本機封存核驗通過" in row.value for row in ui.success)
    assert any("仍須另行認證" in row.value for row in ui.info)
    assert any(row.label == "帳戶淨值（TWD）" and row.value == "1050" for row in ui.metric)
    def forbidden(*args, **kwargs):
        raise AssertionError("rerender repeated an explicit read action")
    monkeypatch.setattr(inspection_ui, "inspect_rights_catalog", forbidden)
    ui.run(timeout=30)
    assert not ui.exception and not ui.success
    assert before == {p: p.read_bytes() for p in before}


def test_incomplete_form_does_not_create_a_file(tmp_path):
    ui = app()
    missing = tmp_path/"missing.sqlite"
    text(ui, "權利帳戶 SQLite 路徑", str(missing))
    ui.button[0].click().run(timeout=30)
    assert not ui.exception and ui.error and not missing.exists()


def test_main_app_exposes_optin_readonly_entry_without_initializing_accounts():
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"src/quant_fund_lab/ui.py")).run(timeout=30)
    next(row for row in ui.checkbox if row.label == "權利事件帳戶唯讀核驗").check().run(timeout=30)
    assert not ui.exception
    assert any(row.value == "權利事件帳戶核驗" for row in ui.subheader)
    assert not ui.success and not ui.error
