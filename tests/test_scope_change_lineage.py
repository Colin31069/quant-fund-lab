"""Avoiding a blocked symbol/day creates an explicit new study and child protocol."""
import csv
import hashlib
import json
from dataclasses import asdict

import pytest
from test_registered_odd_lot_study import SOURCE
from test_twse_odd_lot import _write_rows
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    ProtocolPeriod,
    SelectionRule,
    capture_execution_identity,
    freeze_protocol,
    load_protocol,
    protocol_from_studies,
)
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.twse_odd_lot import COVERAGE_CATEGORIES, import_twse_file, prepare_twse_odd_lot


def _scope_inputs(tmp_path, case):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path, start="2023-01-01", end="2023-12-31")
    if case == "symbols":
        # Add a third trade asset with one unexplained missing final-session price.
        for month in dates.to_period("M").unique():
            days = dates[(dates.to_period("M") == month) & (dates != dates[-1])]
            raw = tmp_path / "extra.json"
            raw.write_text(json.dumps({"stat": "OK", "title": "1301 fixture",
                "date": month.strftime("%Y%m01"), "fields": ["日期", "開盤價", "收盤價", "成交股數"],
                "data": [[str(day.date()), "100", "100", "1000000"] for day in days]}))
            import_twse_file(root, raw, kind="price", symbol="1301.TW", month=str(month),
                             source_url="https://www.twse.com.tw/price")
        path = root / "coverage_reviews.csv"
        with path.open() as file:
            reader = csv.DictReader(file)
            rows, columns = list(reader), reader.fieldnames
        ref = {"source_url": "https://www.twse.com.tw/review", "evidence_path": "evidence/review.txt"}
        rows.extend({"symbol": "1301.TW", "start": str(dates[0].date()),
                     "end": str(dates[-1].date()), "category": category, **ref}
                    for category in COVERAGE_CATEGORIES)
        _write_rows(path, columns, rows)
        parent_symbols = [*symbols[:2], "1301.TW", symbols[-1]]
    else:
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        entry = next(row for row in manifest["sources"] if row["kind"] == "price"
                     and row["symbol"] == symbols[-1] and row["month"] == str(dates[-1].to_period("M")))
        raw = root / entry["path"]
        payload = json.loads(raw.read_text())
        payload["data"] = [row for row in payload["data"] if row[0] != str(dates[-1].date())]
        raw.write_text(json.dumps(payload))
        entry["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        parent_symbols = symbols
    return root, parent_symbols, symbols, dates


def _freeze(tmp_path, root, symbols, dates):
    inputs = prepare_twse_odd_lot(root, symbols, str(dates[0].date()), str(dates[-1].date()))
    return freeze_odd_lot_study(inputs.data, tmp_path / "studies", symbols=tuple(symbols[:-1]),
        benchmark=symbols[-1], source="twse_official", source_provenance=inputs.provenance,
        source_files=inputs.source_files, source_hashes=inputs.source_hashes,
        quality_issues=[asdict(issue) for issue in inputs.issues])


@pytest.mark.parametrize("case", ["period", "symbols"])
def test_scope_change_records_reason_access_and_parent_without_rewriting_blocked_study(tmp_path, monkeypatch, case):
    import quant_fund_lab.odd_lot_study as module

    root, parent_symbols, child_symbols, dates = _scope_inputs(tmp_path, case)
    start, end = str(dates[120].date()), str(dates[-1].date())
    monkeypatch.setattr(module, "PERIODS", {"validation": (start, end)})
    parent_study = _freeze(tmp_path, root, parent_symbols, dates)
    _, parent_metadata = load_frozen_odd_lot_study(parent_study)
    assert parent_metadata["readiness"]["periods"][0]["status"] == "blocked"
    parent_result = run_frozen_odd_lot_study(parent_study)
    assert not parent_result.results and parent_result.comparison.empty
    parent_report = export_odd_lot_study_report(parent_study, parent_result)
    assert verify_odd_lot_study_report(parent_report)
    summary = SelectionRule("annual_return", "Offline explicit validation rule.", "Retain all blocked sources.")
    parent_protocol = protocol_from_studies((parent_study,),
        periods=(ProtocolPeriod("validation", start, end, "validation_check", "accessed",
                                "Original retrospective fixture; source data already accessed."),),
        selection=summary, execution=capture_execution_identity(SOURCE),
        declared_at="2026-10-29T00:00:00+00:00")
    parent_path = freeze_protocol(parent_protocol, tmp_path / "protocols")
    before = {p: p.read_bytes() for directory in (root, parent_study, parent_path)
              for p in directory.rglob("*") if p.is_file()}
    child_end = str(dates[-2].date()) if case == "period" else end
    monkeypatch.setattr(module, "PERIODS", {"validation": (start, child_end)})
    child_study = _freeze(tmp_path, root, child_symbols, dates)
    _, child_metadata = load_frozen_odd_lot_study(child_study)
    assert child_study != parent_study and child_metadata["study_id"] != parent_metadata["study_id"]
    assert child_metadata["readiness"]["periods"][0]["status"] == "ready"
    assert parent_metadata["holdout_untouched"] is child_metadata["holdout_untouched"] is False
    reason = ("Exclude final missing-price session" if case == "period" else "Remove unresolved1301.TW")
    access_note = (f"Scope change reason: {reason}. Parent study={parent_metadata['study_id']}; "
                   "all original data already accessed; this is a retrospective child, not unseen data.")
    child_protocol = protocol_from_studies((child_study,),
        periods=(ProtocolPeriod("validation", start, child_end, "validation_check", "accessed", access_note),),
        selection=summary, execution=parent_protocol.execution,
        declared_at=parent_protocol.declared_at, parent_protocol_id=parent_protocol.protocol_id)
    child_path = freeze_protocol(child_protocol, tmp_path / "protocols")
    assert child_protocol.protocol_id != parent_protocol.protocol_id
    assert child_protocol.candidates[0].study_id == child_metadata["study_id"]
    assert parent_protocol.candidates[0].study_id == parent_metadata["study_id"]
    if case == "symbols":
        assert "1301.TW" in parent_protocol.symbols and "1301.TW" not in child_protocol.symbols
    else:
        assert child_protocol.periods[0].end < parent_protocol.periods[0].end
    assert load_protocol(child_path) == child_protocol and load_protocol(parent_path) == parent_protocol
    assert child_protocol.periods[0].data_access == "accessed"
    assert reason in child_protocol.periods[0].access_note
    assert parent_metadata["study_id"] in child_protocol.periods[0].access_note
    assert child_protocol.parent_protocol_id == parent_protocol.protocol_id
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.register_protocol(parent_protocol)
        registry.register_protocol(child_protocol)
        assert registry.get_protocol(parent_protocol.protocol_id) == parent_protocol
        assert registry.get_protocol(child_protocol.protocol_id) == child_protocol
        assert not registry.experiments()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert verify_odd_lot_study_report(parent_report)
    assert json.loads((parent_study / "study.json").read_text())["readiness"] == parent_metadata["readiness"]
