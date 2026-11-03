"""Run ready and blocked provider studies through the real Streamlit controls."""
import csv
import json
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_odd_lot_price_inputs import bundle as bundle  # noqa: PLC0414 -- pytest fixture re-export
from test_twse_readiness_frozen import _ready_official_bundle

import quant_fund_lab.odd_lot_study as study_module
from quant_fund_lab.twse_quality.types import fingerprint


def _run_provider_ui(tmp_path, bundle, monkeypatch, complete, *, halt_policy=False):
    app_path = Path(__file__).resolve().parents[1] / "src" / "quant_fund_lab" / "ui.py"
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    if not complete:
        path = root / "coverage_reviews.csv"
        with path.open() as file:
            reader = csv.DictReader(file)
            rows, fields = list(reader), reader.fieldnames
        with path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows[1:])
    monkeypatch.setattr(study_module, "PERIODS", {
        "validation": (str(dates[120].date()), str(dates[-1].date()))})
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    next(c for c in app.checkbox if c.label == "十萬元台股零股策略研究").set_value(True)
    app.run(timeout=30)
    next(c for c in app.selectbox if c.label == "資料來源").set_value("TWSE＋FinMind 本機資料")
    app.run(timeout=30)
    halt_control = next(c for c in app.checkbox if c.label == "依官方個股停牌證據核對無報價")
    assert halt_control.value is False
    halt_control.set_value(halt_policy)
    next(c for c in app.text_input if c.label == "TWSE 資料包目錄").set_value(str(root))
    next(c for c in app.text_input if c.label == "FinMind 資料包目錄").set_value(str(bundle))
    next(c for c in app.text_input if c.label == "交易標的").set_value(",".join(symbols[:2]))
    next(c for c in app.checkbox if c.label == "從官方索引補入純現金股利").set_value(False)
    app.run(timeout=30)
    next(c for c in app.date_input if c.label == "開始日").set_value(dates[120].date())
    next(c for c in app.date_input if c.label == "結束日").set_value(dates[-1].date())
    app.run(timeout=30)
    next(c for c in app.button if c.label == "執行模型").click()
    app.run(timeout=30)
    assert not app.exception and not app.error
    states = [d.value for d in app.dataframe if {"status", "warmup_verified"}.issubset(d.value.columns)]
    assert len(states) == 1
    assert states[0].iloc[0]["status"] == ("ready" if complete else "blocked")
    selected = list((tmp_path / "artifacts" / "odd_lot_studies").glob("*/reports/*/price_selection.csv"))
    assert len(selected) == 1
    report = selected[0].parent
    metadata = json.loads((report.parent.parent / "study.json").read_text())
    policy = json.loads(metadata["source_provenance"]["source_policy_json"])
    assert policy["schema_version"] == (2 if halt_policy else 1)
    assert policy["policy_id"] == ("reviewed_provider_v2" if halt_policy else "reviewed_provider_v1")
    readiness = json.loads((report / "readiness.json").read_text())
    assert readiness["periods"][0]["status"] == states[0].iloc[0]["status"]
    assert states[0].iloc[0]["blocking_count"] == len(readiness["periods"][0]["blocking_ids"])
    assert any(fingerprint(readiness) in item.value for item in app.caption)
    if not complete:
        displayed = next(frame.value for frame in app.dataframe if "finding_id" in frame.value.columns)
        ids = set(readiness["periods"][0]["blocking_ids"])
        assert set(displayed.finding_id) == ids
        assert any(row["code"] == "coverage_review" and row["finding_id"] in ids
                   for row in readiness["findings"])
    with sqlite3.connect(f"file:{report / 'study_ledger.sqlite'}?mode=ro", uri=True) as connection:
        accounts = connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    assert accounts == (3 if complete else 0)
    assert study_module.verify_odd_lot_study_report(report)


@pytest.mark.parametrize("complete", [True, False])
def test_provider_study_ui_uses_shared_ready_or_blocked_decision(tmp_path, bundle, monkeypatch, complete):
    _run_provider_ui(tmp_path, bundle, monkeypatch, complete)


@pytest.mark.parametrize("complete", [True, False])
def test_provider_ui_explicit_halt_policy_is_frozen_and_uses_shared_readiness(
    tmp_path, bundle, monkeypatch, complete
):
    _run_provider_ui(tmp_path, bundle, monkeypatch, complete, halt_policy=True)
