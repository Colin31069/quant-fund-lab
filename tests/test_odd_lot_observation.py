"""Future intent requires a real saved decision; registration never opens an account."""
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
from decision_fixtures import run_candidate
from phased_fixtures import phased_fixture, publish, save_selection
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_paper.ledger import canonical
from quant_fund_lab.odd_lot_paper.observation import (
    ObservationPlan,
    load_observation_plan,
    register_forward_observation,
)
from quant_fund_lab.odd_lot_paper.observation_auth import authenticate_observation_plan
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry


def _plan():
    return ObservationPlan(*(["a" * 64] * 2), "ensemble", *(["b" * 64] * 3),
        "2026-10-30", "2026-10-29T00:00:00+00:00", "c" * 64, "{}", "{}",
        "Historical validation was already accessed.")


@pytest.mark.parametrize("change", [
    {"first_session":"2026-10-29"}, {"first_session":"2026-10-28"},
    {"recorded_at":"2026-10-29T00:00:00"},
    {"recorded_at":"2026-10-29T17:00:00+00:00"},
    {"strategy":"equal_weight"}, {"access_note":" "}, {"candidate_id":"abc"},
    {"research_config_json":"[]"}, {"execution_config_json":'{"x":NaN}'},
    {"schema_version":True},
])
def test_plan_rejects_backdating_implicit_time_and_invalid_settings(change):
    with pytest.raises(ValueError):
        replace(_plan(), **change)


def test_plan_readback_preserves_timestamp_and_rejects_changed_content(tmp_path):
    plan = _plan()
    path = tmp_path / "plan.json"
    value = {"plan_id":plan.plan_id, "plan":asdict(plan),
             "status":"registered_pending_verified_session"}
    path.write_text(canonical(value))
    assert load_observation_plan(tmp_path) == plan
    value["plan"]["first_session"] = "2026-10-31"
    path.write_text(canonical(value))
    with pytest.raises(ValueError, match="fingerprint"):
        load_observation_plan(tmp_path)


def _register(root, report):
    future = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    return register_forward_observation(report, first_session=future,
        access_note="Offline fixture: all historical validation was accessed.",
        registry_path=root / "registry.sqlite", studies_directory=root / "studies",
        source_directory=SOURCE, output_directory=root / "observations")


def test_real_continuing_decision_registers_intent_and_stale_history_refuses(tmp_path, monkeypatch):
    _, protocol, frozen, _, _ = phased_fixture(tmp_path, monkeypatch, positive=True)
    run = run_candidate(tmp_path, protocol, frozen)
    saved = save_selection(tmp_path, frozen)
    result = publish(tmp_path, saved)
    assert result.decision.status == "continue"
    sqlite_before = set(tmp_path.rglob("*.sqlite"))
    directory = _register(tmp_path, result.report)
    plan = load_observation_plan(directory)
    assert plan.decision_id == result.decision.decision_id
    assert plan.candidate_id == result.decision.selected_candidate
    assert plan.selection_id == saved.inputs.selection.selection_id
    assert plan.execution_id == protocol.execution.identity
    candidate = protocol.candidates[0]
    assert (plan.research_config_json, plan.execution_config_json) == (
        candidate.research_json, candidate.backtest_json)
    assert set(tmp_path.rglob("*.sqlite")) == sqlite_before
    assert json.loads((directory / "plan.json").read_text())["status"] == "registered_pending_verified_session"
    auth_args = {"registry_path":tmp_path / "registry.sqlite", "studies_directory":tmp_path / "studies",
                 "source_directory":SOURCE}
    authenticated = authenticate_observation_plan(directory, **auth_args)
    assert authenticated.plan == plan and authenticated.protocol == protocol
    # Rehashing a coherent plan edit does not make it match the original decision.
    path = directory / "plan.json"
    original = path.read_bytes()
    changed = replace(plan, research_config_json="{}")
    path.write_text(canonical({"plan_id":changed.plan_id,"plan":asdict(changed),
                              "status":"registered_pending_verified_session"}))
    with pytest.raises(ValueError, match="settings or choice"):
        authenticate_observation_plan(directory, **auth_args)
    path.write_bytes(original)
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.start_attempt(run.experiment.experiment_id)
    with pytest.raises(ValueError, match="stale"):
        _register(tmp_path, result.report)
    with pytest.raises(ValueError, match="stale"):
        authenticate_observation_plan(directory, **auth_args)
    assert list((tmp_path / "observations").iterdir()) == [directory]


def test_noncontinuing_decision_and_tampered_report_never_register(tmp_path, monkeypatch):
    _, _, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    result = publish(tmp_path, save_selection(tmp_path, frozen))
    with pytest.raises(ValueError, match="continuing"):
        _register(tmp_path, result.report)
    (result.report / "decision.json").write_text("{}")
    with pytest.raises(ValueError, match="verified"):
        _register(tmp_path, result.report)
    assert not (tmp_path / "observations").exists()
