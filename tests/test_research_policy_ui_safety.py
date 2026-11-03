"""Real policy forms reject invalid declarations before creating child/attempt artifacts."""
import json
from dataclasses import asdict

import pytest
from phased_fixtures import phased_fixture
from test_research_browser import _app, _inventory, _read

from quant_fund_lab.odd_lot_protocol.decision import policy_from_plan


@pytest.mark.parametrize("case", ["missing_optional", "nonfinite", "unknown_field", "not_object", "missing_parent"])
def test_invalid_policy_form_preserves_all_research_bytes_and_never_retries(tmp_path, monkeypatch, case):
    _, parent, frozen, _, _ = phased_fixture(tmp_path, monkeypatch)
    app = _read(_app(tmp_path, frozen))
    next(widget for widget in app.checkbox if widget.label == "顯示凍結／執行操作").set_value(True)
    app.run(timeout=30)
    policy = asdict(policy_from_plan(parent.analysis_plan_json))
    if case == "missing_optional":
        policy.pop("maximum_stop_delay_sessions")
    elif case == "nonfinite":
        policy["minimum_validation_annual_return"] = float("nan")
    elif case == "unknown_field":
        policy["unstated_gate"] = True
    elif case == "not_object":
        policy = []
    app.text_area[0].set_value(json.dumps(policy))
    output = tmp_path / ("absent-parent-root" if case == "missing_parent" else "protocols")
    next(widget for widget in app.text_input if widget.label == "新協議根目錄（須已有父協議）").set_value(str(output))
    before = _inventory(tmp_path)
    next(button for button in app.button if button.label == "凍結新政策子協議").click()
    app.run(timeout=30)
    assert not app.exception and not app.success
    assert any("研究操作停止" in item.value for item in app.error)
    assert _inventory(tmp_path) == before
    assert not list((tmp_path / "decisions").glob("**/report_manifest.json"))
    assert not list((tmp_path / "decisions").glob("**/selection_manifest.json"))
    if case == "missing_parent":
        assert not output.exists()
    app.run(timeout=30)
    assert not app.exception and _inventory(tmp_path) == before
