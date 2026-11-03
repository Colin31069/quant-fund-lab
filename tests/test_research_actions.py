"""Explicit forms freeze immutable child policies; reruns never repeat mutations."""
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from phased_fixtures import phased_fixture
from test_registered_odd_lot_study import SOURCE
from test_research_browser import _app, _inventory, _read

from quant_fund_lab.odd_lot_decisions.actions import explicit_policy, freeze_policy_child
from quant_fund_lab.odd_lot_protocol import ExperimentRegistry
from quant_fund_lab.odd_lot_protocol.decision import policy_from_plan
from quant_fund_lab.odd_lot_protocol.storage import load_protocol


def test_child_policy_freeze_preserves_finite_budget_parent_bytes_and_no_attempts(tmp_path, monkeypatch):
    _, parent, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    before = (frozen / "protocol.json").read_bytes()
    value = asdict(policy_from_plan(parent.analysis_plan_json))
    value["maximum_validation_drawdown"] = .7
    result = freeze_policy_child(frozen,json.dumps(value),registry_path=tmp_path / "registry.sqlite",
        studies_directory=tmp_path / "studies",protocols_directory=tmp_path / "protocols",source_directory=SOURCE)
    assert result.protocol.parent_protocol_id == parent.protocol_id
    assert result.protocol.protocol_id != parent.protocol_id
    assert result.protocol.candidates == parent.candidates and result.protocol.periods == parent.periods
    assert (frozen / "protocol.json").read_bytes() == before
    assert load_protocol(result.directory) == result.protocol
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        assert not registry.experiments(parent.protocol_id)
        assert not registry.experiments(result.protocol.protocol_id)
    value.pop("maximum_stop_delay_sessions")
    before_invalid = _inventory(tmp_path)
    with pytest.raises(ValueError,match="every field"):
        freeze_policy_child(frozen,json.dumps(value),registry_path=tmp_path / "registry.sqlite",
            studies_directory=tmp_path / "studies",protocols_directory=tmp_path / "protocols",source_directory=SOURCE)
    assert _inventory(tmp_path) == before_invalid


@pytest.mark.parametrize("value", ["", "[]", '{"development_objective":"annual_return"}'])
def test_no_implicit_or_partial_policy_is_accepted(value):
    with pytest.raises((ValueError,TypeError)):
        explicit_policy(value)


def test_ui_operation_buttons_are_explicit_and_reruns_never_repeat_execution(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.ui_actions as module

    _, protocol, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    calls = []
    def execute(directory,candidate,**kwargs):
        calls.append((directory,candidate))
        return SimpleNamespace(attempt=SimpleNamespace(status="blocked"),report="explicit-test-report")
    monkeypatch.setattr(module,"execute_frozen_candidate",execute)
    before = _inventory(tmp_path)
    app = _read(_app(tmp_path,frozen))
    next(widget for widget in app.checkbox if widget.label == "顯示凍結／執行操作").set_value(True)
    app.run(timeout=30)
    assert not app.exception and not calls
    assert any(widget.label == "完整 DecisionPolicy JSON（所有欄位明列）" for widget in app.text_area)
    app.run(timeout=30)
    assert not calls
    next(button for button in app.button if button.label == "執行已凍結候選").click()
    app.run(timeout=30)
    assert calls == [(str(frozen),protocol.candidates[0].candidate_id)]
    app.run(timeout=30)
    assert len(calls) == 1
    assert _inventory(tmp_path) == before


def test_ui_blank_policy_cannot_create_child_and_failure_does_not_retry(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_decisions.ui_actions as module

    _, _, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    calls = []
    def fail(*args,**kwargs):
        calls.append("explicit")
        raise ValueError("injected registered failure")
    monkeypatch.setattr(module,"execute_frozen_candidate",fail)
    app = _read(_app(tmp_path,frozen))
    next(widget for widget in app.checkbox if widget.label == "顯示凍結／執行操作").set_value(True)
    app.run(timeout=30)
    before = _inventory(tmp_path)
    next(button for button in app.button if button.label == "凍結新政策子協議").click()
    app.run(timeout=30)
    assert not app.exception and any("不得留空" in text.value for text in app.error)
    assert _inventory(tmp_path) == before
    next(button for button in app.button if button.label == "執行已凍結候選").click()
    app.run(timeout=30)
    assert calls == ["explicit"] and app.error
    app.run(timeout=30)
    assert calls == ["explicit"] and _inventory(tmp_path) == before


def test_ui_complete_policy_creates_one_child_without_starting_attempts(tmp_path, monkeypatch):
    _, parent, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    app = _read(_app(tmp_path,frozen))
    next(widget for widget in app.checkbox if widget.label == "顯示凍結／執行操作").set_value(True)
    app.run(timeout=30)
    policy = asdict(policy_from_plan(parent.analysis_plan_json))
    policy["maximum_validation_drawdown"] = .4
    app.text_area[0].set_value(json.dumps(policy))
    next(widget for widget in app.text_input if widget.label == "新協議根目錄（須已有父協議）").set_value(str(tmp_path / "protocols"))
    before = {path.parent.name for path in (tmp_path / "protocols").glob('*/protocol.json')}
    next(button for button in app.button if button.label == "凍結新政策子協議").click()
    app.run(timeout=30)
    assert not app.exception and not app.error and app.success
    after = {path.parent.name for path in (tmp_path / "protocols").glob('*/protocol.json')}
    assert len(after-before) == 1
    child = load_protocol(tmp_path / "protocols" / (after-before).pop())
    assert child.parent_protocol_id == parent.protocol_id and child.candidates == parent.candidates
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        assert not registry.experiments()
    inventory = _inventory(tmp_path)
    app.run(timeout=30)
    assert _inventory(tmp_path) == inventory


def test_ui_decision_publication_uses_saved_selection_once_without_running_candidates(tmp_path, monkeypatch):
    _, _, frozen, _, _ = phased_fixture(tmp_path,monkeypatch)
    app = _read(_app(tmp_path,frozen))
    next(widget for widget in app.checkbox if widget.label == "顯示凍結／執行操作").set_value(True)
    app.run(timeout=30)
    next(widget for widget in app.text_input if widget.label == "決策產物根目錄").set_value(str(tmp_path / "decisions"))
    registry_before = (tmp_path / "registry.sqlite").read_bytes()
    next(button for button in app.button if button.label == "保存開發選擇並產生決策").click()
    app.run(timeout=30)
    assert not app.exception and not app.error and app.success
    assert len(list((tmp_path / "decisions").rglob('selection_manifest.json'))) == 2  # Published plus embedded copy.
    reports = list((tmp_path / "decisions").rglob('report_manifest.json'))
    assert len(reports) == 1
    decision = json.loads((reports[0].parent / "decision.json").read_text())["decision"]
    assert decision["status"] == "incomplete_search" and decision["selected_candidate"] is None
    inventory = _inventory(tmp_path)
    app.run(timeout=30)
    assert _inventory(tmp_path) == inventory
    assert (tmp_path / "registry.sqlite").read_bytes() == registry_before
