"""Unsupported account formats remain intact through real backend and UI refusals."""
import sqlite3

import pandas as pd
import pytest
from test_odd_lot_account_ui import SOURCE, _app, _click, _text
from test_odd_lot_checkpoint_ledger import _initial
from test_odd_lot_durable_replay import _fixture

from quant_fund_lab.odd_lot_paper.inspection import inspect_account
from quant_fund_lab.odd_lot_paper.ledger import OddLotLedger
from quant_fund_lab.odd_lot_paper.rebuild import rebuild_registered_account
from quant_fund_lab.odd_lot_paper.replay import _replay_account
from quant_fund_lab.odd_lot_study import OddLotStudyResult, _write_account_archive
from quant_fund_lab.paper_live import PaperLedger


@pytest.fixture(params=["general_paper", "research_archive", "unsupported_checkpoint", "empty_sqlite"])
def incompatible_account(tmp_path, request):
    path = tmp_path / "preserved.sqlite"
    if request.param == "general_paper":
        with PaperLedger(path, initial_cash=1000, base_currency="TWD"):
            pass
    elif request.param == "research_archive":
        study = OddLotStudyResult("fixture", "dataset", pd.DataFrame(), pd.DataFrame(), {}, {}, False)
        _write_account_archive(path, study)
    elif request.param == "unsupported_checkpoint":
        ledger = OddLotLedger(path, config_json="{}", initial_state=_initial())
        ledger.close()
        with sqlite3.connect(path) as db:
            # An explicit unsupported-schema fixture, not a claimed historical archive migration.
            db.execute("UPDATE account_metadata SET value='odd_lot_checkpoint_v0' WHERE key='kind'")
    else:
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=7")
    return path


def _inventory(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_backend_never_migrates_or_rebuilds_incompatible_accounts(tmp_path, incompatible_account):
    path = incompatible_account
    before = _inventory(tmp_path)
    data, research, base, identity = _fixture()
    with pytest.raises((ValueError, sqlite3.Error)):
        inspect_account(path)
    with pytest.raises((ValueError, sqlite3.Error)):
        _replay_account(path, data, research, base, identity)
    target = tmp_path / "new.sqlite"
    with pytest.raises((ValueError, sqlite3.Error)):
        rebuild_registered_account(path, target, tmp_path / "protocol", "a" * 64,
            period="validation", strategy="momentum", studies_directory=tmp_path / "studies",
            source_directory=SOURCE, snapshot_root=tmp_path / "snapshots")
    assert not target.exists() and _inventory(tmp_path) == before


def test_ui_read_and_rebuild_refuse_without_changing_incompatible_account(tmp_path, incompatible_account):
    path = incompatible_account
    before = _inventory(tmp_path)
    app = _app().run(timeout=30)
    assert next(row for row in app.radio if row.label == "帳戶操作").value == "安全續跑既有帳戶"
    _text(app, "零股帳戶 SQLite 路徑", str(path))
    app = _click(app, "核驗並讀取帳戶")
    assert not app.exception and any("無法讀取帳戶" in row.value for row in app.error)
    assert not app.success and _inventory(tmp_path) == before
    _text(app, "凍結協議目錄", str(tmp_path / "protocol"))
    _text(app, "候選 ID", "a" * 64)
    _text(app, "重建目的帳戶（必須為新路徑）", str(tmp_path / "new.sqlite"))
    app = _click(app, "保留原帳戶並重建至新路徑")
    assert not app.exception and any("重建停止" in row.value for row in app.error)
    assert not app.success and _inventory(tmp_path) == before
    app.run(timeout=30)
    assert not app.exception and _inventory(tmp_path) == before
