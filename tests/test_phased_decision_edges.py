"""All-failed finite budgets remain unranked, replayable and visible in both schemas."""
import json

import pytest
from phased_fixtures import phased_fixture, publish, save_selection
from test_registered_odd_lot_study import SOURCE
from test_research_browser import _app, _inventory, _read

from quant_fund_lab.odd_lot_decisions.phased_reporting import verify_phased_decision_report
from quant_fund_lab.odd_lot_decisions.workflow import (
    export_registered_decision,
    verify_registered_decision_report,
)
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry
from quant_fund_lab.odd_lot_protocol.storage import load_protocol


@pytest.mark.parametrize("phased", [True, False])
def test_all_failed_budget_preserves_retries_no_validation_or_ranking_and_readonly_ui(tmp_path, monkeypatch, phased):
    import quant_fund_lab.odd_lot_decisions.phased_evaluation as validation

    _, protocol, frozen, legacy, _ = phased_fixture(tmp_path, monkeypatch, count=2)
    if not phased:
        frozen, protocol = legacy, load_protocol(legacy)
    reasons = []
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        for number, candidate in enumerate(protocol.candidates):
            record = registry.register_experiment(protocol, candidate.candidate_id, protocol.execution)
            for retry in range(2):
                attempt = registry.start_attempt(record.experiment_id)
                reason = f"candidate {number} failed offline attempt {retry}"
                reasons.append(reason)
                registry.finish_attempt(record.experiment_id, attempt.attempt, status="failed", reason=reason)
    def forbidden(*args, **kwargs):
        raise AssertionError("all-failed search must not parse validation")
    monkeypatch.setattr(validation, "checked_report", forbidden)
    monkeypatch.setattr(validation, "report_candidate_evidence", forbidden)

    def export():
        if phased:
            return publish(tmp_path, save_selection(tmp_path, frozen))
        return export_registered_decision(frozen, registry_path=tmp_path / "registry.sqlite",
            studies_directory=tmp_path / "studies", output_directory=tmp_path / "decisions",
            source_directory=SOURCE)

    first = export()
    first_bytes = _inventory(first.report)
    second = export()
    assert second.report != first.report and second.decision.decision_id == first.decision.decision_id
    assert _inventory(first.report) == first_bytes
    assert first.decision.status == "incomplete_search" and first.decision.selected_candidate is None
    assert len(first.decision.candidates) == 4
    assert all(row.status == "unavailable" and row.development_score is None for row in first.decision.candidates)
    evidence = json.loads((first.report / "evidence.json").read_text())
    if phased:
        assert evidence is None
        selection = json.loads((first.report / "development_selection.json").read_text())
        assert selection["status"] == "incomplete_search"
        assert all(row["rank"] is None for row in selection["candidates"])
    verify = verify_phased_decision_report if phased else verify_registered_decision_report
    assert verify(first.report, registry_path=tmp_path / "registry.sqlite", studies_directory=tmp_path / "studies")
    sources = json.loads((first.report / "sources.json").read_text())
    histories = [json.loads(row["history_json"]) for row in sources]
    assert len(histories) == 2 and all(len(history) == 2 for history in histories)
    assert {row["reason"] for history in histories for row in history} == set(reasons)
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path, frozen, "保存的決策", first.report))
    assert not app.exception and not app.error
    candidates = next(frame.value for frame in app.dataframe if "latest_status" in frame.value.columns)
    assert len(candidates) == 2 and set(candidates.latest_status) == {"failed"}
    attempts = next(frame.value for frame in app.dataframe if "started_at" in frame.value.columns)
    assert len(attempts) == 4 and set(attempts.reason) == set(reasons)
    assert any("incomplete_search" in row.value for row in app.markdown)
    app.run(timeout=30)
    _read(app)
    assert _inventory(tmp_path) == before
