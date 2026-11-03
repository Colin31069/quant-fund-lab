"""An individual halt must preserve market sessions and contradictory quote checks."""
import hashlib
from dataclasses import replace

import pytest
from test_twse_odd_lot import _bundle

from quant_fund_lab.twse_amendments import SymbolSuspensionEvidence, derive_closure_bundle
from quant_fund_lab.twse_calendar import official_calendar
from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot


def test_symbol_halt_is_immutable_and_does_not_remove_market_session(tmp_path):
    root, symbols = _bundle(tmp_path)
    evidence = tmp_path / "halt.txt"
    evidence.write_text("offline reviewed suspension fixture")
    item = SymbolSuspensionEvidence("2025-06-11", "2025-06-10",
        "https://www.twse.com.tw/halt", evidence,
        hashlib.sha256(evidence.read_bytes()).hexdigest(), "Individual halt reviewed.", symbols[0])
    before = (root / "suspensions.csv").read_bytes()
    derived = derive_closure_bundle(root, tmp_path / "derived", (item,))
    assert (root / "suspensions.csv").read_bytes() == before
    assert derive_closure_bundle(root, tmp_path / "derived", (item,)) == derived
    inputs = prepare_twse_odd_lot(derived, symbols, "2025-06-09", "2025-06-20")
    assert any(issue.detail == "停牌紀錄與官方成交價量衝突" for issue in inputs.issues)
    calendar = official_calendar(inputs, "2025-06-09", "2025-06-20")
    assert "2025-06-11" in {str(day.date()) for day in calendar.sessions}
    assert not any(issue.detail == "休市紀錄與官方成交價量衝突" and issue.start == item.session
                   for issue in inputs.issues)
    with pytest.raises(ValueError, match="individual"):
        derive_closure_bundle(root, tmp_path / "derived", (replace(item, symbol="*"),))
