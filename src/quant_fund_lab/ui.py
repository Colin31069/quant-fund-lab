from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

# Ensure `src` directory is on sys.path when running `streamlit run src/quant_fund_lab/ui.py`
_SRC_ROOT = str(Path(__file__).resolve().parents[1])
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

import streamlit as st

from quant_fund_lab.config import BacktestConfig, DividendWithholdingConfig, StrategyConfig
from quant_fund_lab.data_quality import validate_corporate_actions
from quant_fund_lab.factors import research_factors
from quant_fund_lab.fx import validate_fx
from quant_fund_lab.odd_lot_research import OddLotResearchConfig
from quant_fund_lab.odd_lot_study import (
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    run_frozen_odd_lot_study,
)
from quant_fund_lab.paper import historical_vs_paper_replay
from quant_fund_lab.paper_workflow import plan_persistent_paper_run
from quant_fund_lab.provenance import AuditLog
from quant_fund_lab.robustness import build_robustness_report
from quant_fund_lab.ui_pipeline import (
    export_ui_report_if_requested,
    prepare_ui_market_data,
    run_ui_persistent_ledger,
)
from quant_fund_lab.ui_sidebar import render_sidebar
from quant_fund_lab.ui_views import (
    render_equity_charts,
    render_factor_laboratory,
    render_kpi_dashboard,
    render_odd_lot_study,
    render_persistent_ledger,
    render_risk_and_regime,
    render_robustness_and_walkforward,
    render_tax_and_settlement,
    render_trading_details,
)

st.set_page_config(page_title="Quant Fund Lab", layout="wide")
st.title("Quant Fund Lab")
st.caption("數學 Alpha → 風險模型 → 組合最佳化 → 模擬成交；僅虛擬資金，不連接券商。")

if st.sidebar.checkbox("零股研究協議與決策瀏覽", value=False):
    from quant_fund_lab.odd_lot_decisions.ui import render_research_browser

    render_research_browser(st, Path(__file__).resolve().parents[2])
    st.stop()

if st.sidebar.checkbox("零股前向虛擬觀察", value=False):
    from quant_fund_lab.odd_lot_paper.forward_ui import render_observation_panel

    render_observation_panel(st, Path(__file__).resolve().parents[2])
    st.stop()

if st.sidebar.checkbox("零股持久化歷史帳戶", value=False):
    from quant_fund_lab.odd_lot_paper.ui import render_account_panel

    render_account_panel(st, Path(__file__).resolve().parents[2])
    st.stop()

if st.sidebar.checkbox("權利事件帳戶唯讀核驗", value=False):
    from quant_fund_lab.odd_lot_rights.inspection_ui import render_rights_inspection

    render_rights_inspection(st)
    st.stop()

inputs = render_sidebar()

if inputs.run:
    requested_trade = [
        s.strip() if inputs.verified_mode else s.strip().upper()
        for s in inputs.symbols_text.split(",")
        if s.strip()
    ]
    requested_bmk = inputs.benchmark.strip() if inputs.verified_mode else inputs.benchmark.strip().upper()
    all_syms = list(dict.fromkeys(requested_trade + [requested_bmk]))
    if len(requested_trade) < 2:
        st.error("至少提供兩個交易標的，橫斷面模型才有意義。")
        st.stop()
    if inputs.odd_lot_study and inputs.persist_paper_ledger:
        st.error("零股策略研究使用獨立的凍結研究紀錄；目前不能續跑一般 persistent paper ledger。")
        st.stop()
    if inputs.odd_lot_study and (inputs.base_currency != "TWD" or inputs.execution_price_basis != "raw"):
        st.error("台股零股研究需要 TWD 基準幣別及 raw 成交價格。")
        st.stop()

    paper_ledger_reset = True
    if inputs.persist_paper_ledger:
        try:
            paper_ledger_reset = plan_persistent_paper_run(
                inputs.paper_ledger_path,
                inputs.paper_ledger_mode,
                confirmed_rebuild=inputs.paper_confirm_rebuild,
            )
        except (FileNotFoundError, ValueError) as exc:
            st.error(f"虛擬帳本操作已取消：{exc}")
            st.stop()

    try:
        with st.spinner("載入資料並執行 walk-forward paper replay..."):
            prep = prepare_ui_market_data(inputs, all_syms, requested_trade, requested_bmk)
            raw = prep.raw
            trade_data = prep.trade_data
            trade_symbols = prep.trade_symbols
            benchmark_symbol = prep.benchmark_symbol
            source_data_provenance = prep.source_data_provenance
            data_provider = prep.data_provider
            provider_attempts = prep.provider_attempts
            twse_inputs = prep.twse_inputs

            strategy = StrategyConfig(
                max_weight=inputs.max_weight,
                rebalance_every=inputs.rebalance_every,
                regime_enabled=inputs.regime_enabled,
                factor_neutralization=inputs.factor_neutralization,
                factor_neutralization_strength=inputs.factor_neutralization_strength,
                risk_budget_penalty=inputs.risk_budget_penalty,
                factor_alpha_enabled=inputs.enable_factor_alpha and not inputs.odd_lot_study,
                factor_alpha_weight=inputs.factor_alpha_weight,
                volatility_target_enabled=inputs.enable_vol_target and not inputs.odd_lot_study,
                target_annual_volatility=inputs.target_annual_volatility,
                cvar_control_enabled=inputs.enable_cvar_control and not inputs.odd_lot_study,
                max_daily_cvar=inputs.max_daily_cvar,
                drawdown_control_enabled=inputs.enable_drawdown_control and not inputs.odd_lot_study,
                drawdown_soft_limit=inputs.drawdown_soft_limit,
                drawdown_hard_limit=inputs.drawdown_hard_limit,
                drawdown_min_exposure=inputs.drawdown_min_exposure,
            )
            config = BacktestConfig(
                initial_cash=inputs.initial_cash,
                cash_annual_yield=float(inputs.cash_annual_yield_pct) / 100.0,
                base_currency=inputs.base_currency,
                execution_price_basis=inputs.execution_price_basis,
                dividend_withholding=DividendWithholdingConfig(
                    us_rate=float(inputs.us_dividend_withholding_pct) / 100.0,
                    tw_rate=float(inputs.tw_dividend_withholding_pct) / 100.0,
                ),
                strategy=strategy,
            )
            if inputs.odd_lot_study:
                if not inputs.twse_mode:
                    raw = raw.slice(start=inputs.start_date, end=inputs.end_date)
                assumptions = OddLotResearchConfig(
                    risk_budget=float(inputs.odd_lot_risk),
                    max_weight=float(inputs.max_weight),
                    rebalance_every=int(inputs.rebalance_every),
                    min_commission=float(inputs.odd_lot_fee),
                    commission_bps=float(inputs.odd_lot_commission),
                    slippage_bps=float(inputs.odd_lot_slippage),
                    limit_offset=float(inputs.odd_lot_limit) / 100,
                    fill_fraction=float(inputs.odd_lot_fill) / 100,
                    max_participation=float(inputs.odd_lot_participation) / 100,
                    impact_coefficient=float(inputs.odd_lot_impact),
                    fee_rounding=inputs.odd_lot_rounding,
                    instrument_rules=json.loads(inputs.instrument_rules_text),
                )
                frozen = freeze_odd_lot_study(
                    raw,
                    "artifacts/odd_lot_studies",
                    symbols=tuple(trade_symbols),
                    benchmark=benchmark_symbol,
                    research=assumptions,
                    base_config=config,
                    source=data_provider,
                    source_provenance=source_data_provenance,
                    holdout_untouched=inputs.holdout_untouched,
                    source_files=twse_inputs.source_files if twse_inputs else None,
                    source_hashes=twse_inputs.source_hashes if twse_inputs else None,
                    quality_issues=[asdict(issue) for issue in twse_inputs.issues] if twse_inputs else None,
                )
                study = run_frozen_odd_lot_study(frozen)
                report = export_odd_lot_study_report(frozen, study)
                st.session_state["odd_lot_study_result"] = (study, frozen, report, data_provider)
                render_odd_lot_study(study, frozen, report, data_provider)
                st.stop()

            comparison = historical_vs_paper_replay(
                trade_data, config, train_fraction=inputs.train_fraction
            )
            robustness = (
                build_robustness_report(
                    trade_data,
                    config,
                    inputs.train_fraction,
                    comparison.paper_replay,
                    cost_multipliers=(1.0, 1.5, 2.0),
                    bootstrap_iterations=300,
                    block_length=10,
                    seed=19,
                )
                if inputs.run_robustness
                else None
            )
            factor_research = (
                research_factors(
                    trade_data,
                    sampling_every=max(inputs.rebalance_every, 1),
                    horizons=(1, 5, 20),
                )
                if inputs.run_factor_research
                else None
            )
            action_report = validate_corporate_actions(trade_data)
            fx_report = validate_fx(trade_data, config.max_fx_staleness_days)
            audit = AuditLog("artifacts/audit.jsonl")
            audit.append(
                "DATA_PROVIDER_SELECTED",
                {
                    "provider": data_provider,
                    "attempts": [
                        {"provider": p, "success": ok, "error": error}
                        for p, ok, error in provider_attempts
                    ],
                    "symbols": all_syms,
                },
            )
            report_export = export_ui_report_if_requested(
                inputs, comparison, trade_data, config, source_data_provenance, audit
            )

            benchmark_close_base = (
                raw.close[benchmark_symbol] * raw.fx_to_base[benchmark_symbol]
            ).ffill().dropna()

            ledger_state = None
            if inputs.persist_paper_ledger:
                try:
                    ledger_state = run_ui_persistent_ledger(
                        inputs,
                        trade_data,
                        comparison.paper_replay.weights,
                        config,
                        benchmark_close_base,
                        paper_ledger_reset,
                    )
                except (FileNotFoundError, ValueError) as exc:
                    st.error(
                        f"虛擬帳本未變更：{exc}。安全續跑需要完整且相同的既有"
                        "市場資料、訊號、交易參數與快照；如需重建請先備份，再明確選擇新建。"
                    )
                    st.stop()

        st.success(
            f"切分日：{comparison.split_date.date()}；其後區段以重置虛擬資金做 paper replay。"
            f" NAV 基準幣別：{comparison.paper_replay.base_currency}。"
        )
        st.caption(
            f"FX 最大沿用天數：{fx_report.max_age_days:.0f} 日；"
            "換匯只允許使用當日或更早的匯率，不使用未來資料。"
        )
        provider_failed = [name for name, ok, _ in provider_attempts if not ok]
        st.caption(
            f"資料 Provider：{data_provider}。"
            + (f" Failover 前失敗：{', '.join(provider_failed)}。" if provider_failed else "")
        )
        if source_data_provenance:
            st.caption(
                "Verified provenance：market="
                f"{source_data_provenance['market_data_dataset_id'][:12]}…；lifecycle="
                f"{source_data_provenance['security_lifecycle_dataset_id'][:12]}…。"
            )
            if "cash_in_lieu_settlement_dataset_id" in source_data_provenance:
                st.caption(
                    "Cash-in-lieu provenance："
                    f"{source_data_provenance['cash_in_lieu_settlement_dataset_id'][:12]}…。"
                )
        if report_export is not None:
            report_run_id, report_path, report_verified = report_export
            st.success(
                f"M4 report 已匯出：{report_path}；run_id={report_run_id}；"
                f"integrity={'PASS' if report_verified else 'FAIL'}。"
            )
        session_reports = comparison.paper_replay.session_validations
        if not session_reports and comparison.paper_replay.session_validation is not None:
            legacy_report = comparison.paper_replay.session_validation
            session_reports = {legacy_report.market: legacy_report}
        if not action_report.is_valid:
            st.warning(
                "企業行動資料有可疑項目："
                f"負股利 {len(action_report.negative_dividend_events)}、"
                f"無效拆股 {len(action_report.invalid_split_events)}、"
                f"拆股後調整報酬異常 {len(action_report.suspicious_split_adjustments)}、"
                f"孤兒 settlement price {len(action_report.orphan_cash_in_lieu_prices)}、"
                "孤兒 settlement date "
                f"{len(action_report.orphan_cash_in_lieu_settlement_dates)}、"
                f"提前 settlement price {len(action_report.premature_cash_in_lieu_prices)}、"
                "到期缺 settlement price "
                f"{len(action_report.missing_cash_in_lieu_settlement_prices)}。"
            )
        for market, session_report in session_reports.items():
            if not (session_report.missing_sessions or session_report.off_calendar_sessions):
                continue
            missing_preview = ", ".join(str(x.date()) for x in session_report.missing_sessions[:3])
            extra_preview = ", ".join(
                str(x.date()) for x in session_report.off_calendar_sessions[:3]
            )
            st.warning(
                f"{market} 市場資料與第三方交易日曆存在差異。"
                f" 日曆有、資料無：{len(session_report.missing_sessions)} 日（{missing_preview or '無'}）；"
                f" 資料有、日曆無：{len(session_report.off_calendar_sessions)} 日（{extra_preview or '無'}）。"
                "可能是臨時休市、日曆版本落差或資料缺口；不自動補造價格。"
            )

        # 1. Executive Performance KPI Cards & Comparisons
        _, benchmark_equity = render_kpi_dashboard(
            comparison, benchmark_close_base, inputs.initial_cash
        )

        # 2. Interactive Equity Curves & Underwater Drawdowns
        render_equity_charts(comparison, benchmark_equity)

        # 3. Structured Quantitative Deep-Dive Workspaces
        t_risk, t_factor, t_tax, t_ledger, t_robust, t_details = st.tabs(
            [
                "🛡️ 風險控管與市場政權",
                "🔬 橫斷面因子實驗室",
                "💸 交易成本與稅務交割",
                "📜 持久化帳本與雙重記帳稽核",
                "🧪 穩健性壓力與 OOS 檢定",
                "📋 成交紀錄與訊號明細",
            ]
        )

        with t_risk:
            render_risk_and_regime(
                comparison,
                inputs.enable_vol_target,
                inputs.enable_cvar_control,
                inputs.enable_drawdown_control,
                inputs.factor_neutralization,
                inputs.factor_neutralization_strength,
                inputs.risk_budget_penalty,
            )

        with t_factor:
            render_factor_laboratory(
                factor_research,
                inputs.enable_factor_alpha,
                comparison,
                trade_symbols,
            )

        with t_tax:
            render_tax_and_settlement(comparison, config)

        with t_ledger:
            if ledger_state is not None:
                render_persistent_ledger(
                    ledger_state.persistent_nav,
                    ledger_state.persistent_orders,
                    ledger_state.persistent_fills,
                    ledger_state.persistent_positions,
                    ledger_state.persistent_snapshots,
                    ledger_state.persistent_actions,
                    ledger_state.persistent_receivables,
                    ledger_state.persistent_interest_credits,
                    ledger_state.persistent_session_commits,
                    ledger_state.persistent_replay_execution_config,
                    ledger_state.persistent_ledger_audit,
                    paper_ledger_reset,
                    inputs.base_currency,
                    config,
                )
            else:
                st.info("尚未啟用本機 persistent paper ledger。請在側邊欄勾選以啟用。")

        with t_robust:
            render_robustness_and_walkforward(
                robustness,
                inputs.run_walkforward,
                trade_data,
                config,
                strategy,
                inputs.walkforward_objective,
                comparison.paper_replay.base_currency,
            )

        with t_details:
            render_trading_details(comparison)

    except Exception as exc:  # noqa: BLE001 - UI boundary must surface provider/runtime errors.
        if inputs.twse_mode:
            st.error(f"TWSE 資料準備失敗：{exc}。請核對資料包及來源，已下載檔案可供重試。")
        elif inputs.odd_lot_study and "raw prices appear split-adjusted" in str(exc):
            st.error(
                "資料中的原始價格疑似已調整拆股，繼續計算會重複套用企業行動。"
                "請使用經確認的未調整價格與拆股資料，或先選合成資料測試流程。"
                f" 詳細資訊：{exc}"
            )
        else:
            st.exception(exc)
else:
    if inputs.odd_lot_study and "odd_lot_study_result" in st.session_state:
        render_odd_lot_study(*st.session_state["odd_lot_study_result"])
    else:
        st.info("設定標的後按「執行模型」。第一次可先選『離線合成資料』驗證整套引擎。")
