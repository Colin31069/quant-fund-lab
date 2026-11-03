"""Risk diagnostics reconcile with engine fills and never realize open marked losses."""
import json
from dataclasses import replace

import pandas as pd
import pytest

from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import MarketData
from quant_fund_lab.market_calendar import expected_market_sessions
from quant_fund_lab.odd_lot_diagnostics import diagnose_odd_lot_account, inputs_from_result
from quant_fund_lab.odd_lot_diagnostics.capital import capital_utilization
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, run_odd_lot_research

SYMBOL = "2330.TW"


def _run(monkeypatch, *, end=35, fraction=1.0):
    dates = pd.DatetimeIndex(expected_market_sessions("TW", "2024-01-01", "2024-12-31").sessions)[:36]
    raw = pd.DataFrame(100.0, index=dates, columns=[SYMBOL])
    raw.loc[dates[31]] = 90
    raw.loc[dates[32]:] = 60
    opening = raw.copy()
    data = MarketData(opening, raw, raw * 100000, raw_open=opening, raw_close=raw)
    def targets(history, eligible, research, strategy, previous):
        value = 1.0 if len(history) <= 31 else 0.0
        return pd.Series(1.0, index=history.columns), pd.Series(value, index=history.columns)
    monkeypatch.setattr("quant_fund_lab.odd_lot_research._targets", targets)
    config = OddLotResearchConfig(strategy="momentum", max_positions=1, max_weight=1,
        rebalance_every=1, min_stop_distance=.05, max_stop_distance=.05,
        min_commission=0, commission_bps=0, slippage_bps=0, impact_coefficient=0,
        max_participation=1, fill_fraction=fraction,
        instrument_rules={SYMBOL: {"kind": "stock", "sell_tax_bps": 0, "price_limit_pct": None}})
    base = BacktestConfig(initial_cash=100000, base_currency="TWD", strategy=StrategyConfig(warmup_days=30))
    return run_odd_lot_research(data.slice(end=dates[end]), config, base), dates


def test_gap_stop_retries_then_realizes_hand_calculated_excess(monkeypatch):
    result, dates = _run(monkeypatch)
    before = result.fills.copy(deep=True)
    audit = diagnose_odd_lot_account(inputs_from_result(result))
    row = audit.episode_risk[0]
    assert result.fills.iloc[0].quantity == 400
    assert result.fills.iloc[0].entry_risk_budget == 2000
    assert row.entry_risk_budget == row.estimated_entry_risk == 2000
    assert row.realized_net_loss == 16000 and row.loss_over_budget == 14000
    assert row.loss_to_budget_ratio == 8 and row.risk_status == "available"
    assert row.first_stop_signal == dates[31].isoformat()
    assert row.share_exit == dates[33].isoformat() and row.stop_attempts == 2
    assert row.stop_delay_sessions == 2 and row.stop_delay_calendar_days == (dates[33]-dates[31]).days
    assert row.stop_status == "completed" and audit.closed_count == 1
    capital = audit.capital.set_index("timestamp")
    entry = capital.loc[dates[30].isoformat()]
    assert entry.holdings_value == 40000 and entry.invested_fraction == .4
    assert entry.available_cash_fraction == .6 and entry.unsettled_payables_fraction == .4
    assert capital.loc[dates[33].isoformat()].unsettled_receivables_fraction == pytest.approx(24000/84000)
    assert not audit.source_issues and not audit.to_dict()["sample_sufficient"]
    json.dumps(audit.to_dict(), allow_nan=False)
    pd.testing.assert_frame_equal(before, result.fills)


def test_unexited_stop_preserves_pending_without_realizing_marked_loss(monkeypatch):
    result, _ = _run(monkeypatch, end=32)
    row = diagnose_odd_lot_account(inputs_from_result(result)).episode_risk[0]
    assert result.episodes.iloc[0].pnl == -16000  # This includes the open mark.
    assert row.risk_status == row.stop_status == "pending"
    assert row.realized_net_loss is row.loss_over_budget is row.loss_to_budget_ratio is None
    assert row.stop_attempts == row.observed_sessions_since_stop == 1
    assert row.share_exit is row.stop_delay_sessions is None


def test_missing_or_changed_entry_budget_cannot_be_reconstructed(monkeypatch):
    result, _ = _run(monkeypatch)
    inputs = inputs_from_result(result)
    missing = replace(inputs, fills=inputs.fills.drop(columns="entry_risk_budget"))
    audit = diagnose_odd_lot_account(missing)
    row = audit.episode_risk[0]
    assert row.risk_status == "unavailable" and row.entry_risk_budget is None
    assert row.realized_net_loss == 16000 and row.loss_over_budget is None
    assert audit.closed_count == 1  # Budget availability does not change episode count.
    changed = diagnose_odd_lot_account(replace(inputs, configured_risk_budget=3000))
    assert "differs" in changed.episode_risk[0].risk_reason


def test_stop_execution_without_trigger_is_unavailable(monkeypatch):
    result, _ = _run(monkeypatch)
    inputs = inputs_from_result(result)
    signals = inputs.signals.loc[inputs.signals.reason.ne("stop")]
    audit = diagnose_odd_lot_account(replace(inputs, signals=signals))
    assert audit.episode_risk[0].stop_status == "unavailable"
    assert any("without recorded trigger" in issue for issue in audit.source_issues)


def test_partial_expired_and_missing_entry_orders_are_distinguished(monkeypatch):
    result, dates = _run(monkeypatch, end=31, fraction=.5)
    inputs = inputs_from_result(result)
    audit = diagnose_odd_lot_account(inputs)
    summary = audit.unfilled_orders.iloc[0]
    assert summary.status == "partial_expired"
    assert summary.requested_quantity == 400 and summary.filled_quantity == summary.expired_quantity == 200
    assert len(result.fills) == 1 and audit.episode_risk[0].entry_risk_budget == 2000
    missing = diagnose_odd_lot_account(replace(inputs, orders=pd.DataFrame()))
    assert missing.unfilled_orders.iloc[0].outcome == "unavailable_entry_signal_without_order"
    assert missing.unfilled_orders.iloc[0].requested_quantity is None
    pending_signal = pd.DataFrame([{"timestamp": dates[31], "symbol": SYMBOL, "reason": "entry"}])
    pending = diagnose_odd_lot_account(replace(inputs, orders=pd.DataFrame(), signals=pending_signal))
    assert pending.unfilled_orders.iloc[0].outcome == "pending_entry_signal_at_end"


@pytest.mark.parametrize("value,reason", [(0,"nonpositive"),(float("inf"),"nonfinite"),("invalid","nonfinite")])
def test_invalid_capital_never_creates_valid_allocation(value, reason):
    curve = pd.DataFrame([{"equity":value,"cash":100,"buy_payables":0,"sale_payables":0,
                          "sale_receivables":0,"receivable_value":0}], index=[pd.Timestamp("2024-01-02")])
    row = capital_utilization(curve).iloc[0]
    assert row.status == "unavailable" and reason in row.reason
    assert row.invested_fraction is row.available_cash_fraction is None


def test_missing_capital_and_episode_sources_are_explicit(monkeypatch):
    result, _ = _run(monkeypatch)
    inputs = inputs_from_result(result)
    audit = diagnose_odd_lot_account(replace(inputs, equity_curve=inputs.equity_curve.drop(columns="buy_payables"),
                                            episodes=pd.DataFrame()))
    assert audit.closed_count is None and not audit.episode_risk
    assert any("missing capital" in issue for issue in audit.source_issues)
    assert any("missing episode" in issue for issue in audit.source_issues)


def test_share_liquidation_can_finish_before_entitlement_cash(monkeypatch):
    result, dates = _run(monkeypatch)
    inputs = inputs_from_result(result)
    episodes = inputs.episodes.copy()
    episodes.loc[0, "status"] = "open"
    episodes.loc[0, "pending_receivables"] = 1
    audit = diagnose_odd_lot_account(replace(inputs, episodes=episodes))
    row = audit.episode_risk[0]
    assert row.share_exit == dates[33].isoformat() and row.stop_status == "completed"
    assert row.risk_status == "pending" and row.realized_net_loss is None
    assert audit.closed_count == 0


def test_passive_strategy_has_no_stop_budget_or_excess(monkeypatch):
    result, _ = _run(monkeypatch)
    inputs = replace(inputs_from_result(result), strategy="equal_weight")
    row = diagnose_odd_lot_account(inputs).episode_risk[0]
    assert row.risk_status == row.stop_status == "not_applicable"
    assert row.entry_risk_budget is row.loss_over_budget is row.loss_to_budget_ratio is None
    assert row.realized_net_loss == 16000


def test_completed_episode_archive_reconstructs_and_rejects_changed_budget(monkeypatch, tmp_path):
    from quant_fund_lab.odd_lot_diagnostics.types import StudyRiskDiagnostics
    from quant_fund_lab.odd_lot_protocol.diagnostics import (
        export_risk_diagnostics,
        verify_diagnostic_report,
    )
    from quant_fund_lab.odd_lot_protocol.types import canonical_json

    result, _ = _run(monkeypatch)
    diagnostics = diagnose_odd_lot_account(inputs_from_result(result))
    export_risk_diagnostics(tmp_path, StudyRiskDiagnostics({("validation", "momentum"): diagnostics}, {}))
    prefix = "validation_momentum"
    for name in ("equity_curve", "fills", "orders", "signals", "episodes", "corporate_actions", "terminal_events"):
        getattr(result, name).to_csv(tmp_path / f"{prefix}_{name}.csv", index=name == "equity_curve")
    pd.DataFrame([{"period": "validation", "strategy": "momentum"}]).to_csv(tmp_path / "execution_summary.csv", index=False)
    (tmp_path / "unavailable.json").write_text("{}")
    (tmp_path / "report_manifest.json").write_text(json.dumps({"files": {p.name: "test" for p in tmp_path.iterdir()}}))
    plan = canonical_json({"engine": "frozen_odd_lot_batch_v3", "risk_diagnostics": "odd_lot_risk_diagnostics_v1"})
    metadata = {"periods": {"validation": []}, "research_config": {"risk_budget": 2000}}
    verify_diagnostic_report(tmp_path, metadata, plan, None)
    fills = pd.read_csv(tmp_path / f"{prefix}_fills.csv")
    fills.loc[0, "entry_risk_budget"] = 3000
    fills.to_csv(tmp_path / f"{prefix}_fills.csv", index=False)
    with pytest.raises(ValueError, match="source-account reconstruction"):
        verify_diagnostic_report(tmp_path, metadata, plan, None)


def test_malformed_quantities_and_out_of_session_signals_report_source_issues(monkeypatch):
    result, _ = _run(monkeypatch)
    inputs = inputs_from_result(result)
    orders = inputs.orders.copy().astype({"filled_quantity": object})
    orders.loc[0, "filled_quantity"] = "unknown"
    audit = diagnose_odd_lot_account(replace(inputs, orders=orders))
    assert "invalid order quantity accounting" in audit.source_issues
    signals = inputs.signals.copy()
    signals.loc[0, "timestamp"] = pd.Timestamp("1999-01-01")
    audit = diagnose_odd_lot_account(replace(inputs, signals=signals))
    assert any("sequence is invalid" in issue for issue in audit.source_issues)
    assert audit.episode_risk[0].stop_status == "unavailable"


def test_partial_stop_fills_do_not_claim_complete_liquidation(monkeypatch):
    result, _ = _run(monkeypatch, fraction=.5)
    row = diagnose_odd_lot_account(inputs_from_result(result)).episode_risk[0]
    assert row.stop_attempts == 4 and row.stop_status == "pending"
    assert result.orders.query("side == 'SELL'").status.tolist() == ["expired", "partial_expired", "partial_expired", "partial_expired"]
    assert row.realized_net_loss is row.loss_over_budget is None


def test_split_can_liquidate_integer_shares_while_cash_entitlement_stays_pending(monkeypatch):
    from quant_fund_lab.trade_analytics import position_episodes

    result, dates = _run(monkeypatch, end=32)
    inputs = inputs_from_result(result)
    actions = pd.DataFrame([{"timestamp": dates[32], "symbol": SYMBOL, "action": "stock_split",
        "quantity_before": 400, "quantity_after": 0, "cash_value": 0,
        "fractional_quantity": .4, "cash_in_lieu_price_source": "pending_settlement",
        "cash_in_lieu_settlement_date": dates[33]}])
    episodes = position_episodes(inputs.fills, actions, pd.DataFrame(), pd.Series({SYMBOL: 60000}))
    orders = inputs.orders.loc[inputs.orders.side.eq("BUY")]
    audit = diagnose_odd_lot_account(replace(inputs, corporate_actions=actions, episodes=episodes, orders=orders))
    row = audit.episode_risk[0]
    assert row.stop_status == "completed" and row.share_exit == dates[32].isoformat()
    assert row.stop_attempts == 0 and row.stop_delay_sessions == 1
    assert row.pending_receivables == 1 and row.risk_status == "pending"
    assert row.realized_net_loss is None
