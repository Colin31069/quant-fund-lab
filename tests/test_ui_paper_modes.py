"""Streamlit-level smoke tests for the explicit paper-ledger mode controls."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_FILE = Path(__file__).resolve().parents[1] / "src" / "quant_fund_lab" / "ui.py"


def _enabled_app():
    app = AppTest.from_file(str(APP_FILE)).run(timeout=12)
    assert not app.exception
    enable = next(c for c in app.checkbox if c.label == "啟用本機 persistent paper ledger")
    app = enable.set_value(True).run(timeout=12)
    assert not app.exception
    assert app.radio[0].label == "虛擬帳本操作"
    return app


def test_streamlit_new_ledger_defaults_to_rebuild_without_destructive_prompt(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    app = _enabled_app()
    assert app.radio[0].value == "rebuild"
    assert not any("覆寫" in c.label for c in app.checkbox)
    assert not (tmp_path / "artifacts" / "paper_trading.sqlite").exists()


def test_streamlit_existing_ledger_defaults_to_safe_continuation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ledger_path = tmp_path / "artifacts" / "paper_trading.sqlite"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_bytes(b"prior virtual ledger")

    app = _enabled_app()
    assert app.radio[0].value == "continue"
    assert not any("覆寫" in c.label for c in app.checkbox)
    assert ledger_path.read_bytes() == b"prior virtual ledger"


def test_streamlit_rebuild_requires_visible_confirmation_before_any_work(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    ledger_path = tmp_path / "artifacts" / "paper_trading.sqlite"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_bytes(b"do not delete")

    app = _enabled_app()
    app = app.radio[0].set_value("rebuild").run(timeout=12)
    confirm = next(c for c in app.checkbox if "覆寫" in c.label)
    assert confirm.value is False
    button = next(b for b in app.button if b.label == "執行模型")
    app = button.click().run(timeout=12)
    assert not app.exception
    assert any("requires explicit confirmation" in str(item.value) for item in app.error)
    assert ledger_path.read_bytes() == b"do not delete"


def test_streamlit_resume_with_missing_ledger_stops_before_data_load(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    app = _enabled_app()
    app = app.radio[0].set_value("continue").run(timeout=12)
    button = next(b for b in app.button if b.label == "執行模型")
    app = button.click().run(timeout=12)
    assert not app.exception
    assert any("no existing paper ledger" in str(item.value) for item in app.error)
    assert not (tmp_path / "artifacts" / "paper_trading.sqlite").exists()
