"""Sidebar parameter configuration and input controls for Quant Fund Lab."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from quant_fund_lab.odd_lot_study import SAMPLE_BENCHMARK, SAMPLE_SYMBOLS
from quant_fund_lab.ui_sidebar_odd_lot import render_odd_lot_assumptions
from quant_fund_lab.ui_sidebar_paper import render_paper_ledger_controls
from quant_fund_lab.ui_sidebar_presets import render_sidebar_presets
from quant_fund_lab.ui_sidebar_risk import render_risk_and_factors
from quant_fund_lab.ui_sidebar_twse import render_twse_import_tools


@dataclass(frozen=True)
class UIInputs:
    """Consolidated input parameters gathered from the sidebar."""

    run: bool
    odd_lot_study: bool
    data_mode: str
    twse_mode: bool
    reviewed_mode: bool
    verified_mode: bool
    twse_directory: str
    provider_directory: str
    reviewed_no_quote: bool
    twse_download: bool
    twse_authorized: bool
    twse_cash_events: bool
    symbols_text: str
    benchmark: str
    market_snapshot_directory: str
    lifecycle_snapshot_directory: str
    cash_in_lieu_snapshot_directory: str
    base_currency: str
    start_date: object
    end_date: object
    initial_cash: float
    cash_annual_yield_pct: float
    execution_price_basis: str
    us_dividend_withholding_pct: float
    tw_dividend_withholding_pct: float
    max_weight: float
    rebalance_every: int
    train_fraction: float
    run_walkforward: bool
    walkforward_objective: str
    regime_enabled: bool
    factor_neutralization: bool
    factor_neutralization_strength: float
    risk_budget_penalty: float
    persist_paper_ledger: bool
    paper_ledger_path: Path
    paper_snapshot_root: Path
    paper_ledger_mode: str
    paper_confirm_rebuild: bool
    export_verifiable_report: bool
    run_factor_research: bool
    enable_factor_alpha: bool
    factor_alpha_weight: float
    enable_vol_target: bool
    target_annual_volatility: float
    enable_cvar_control: bool
    max_daily_cvar: float
    enable_drawdown_control: bool
    drawdown_soft_limit: float
    drawdown_hard_limit: float
    drawdown_min_exposure: float
    run_robustness: bool
    odd_lot_risk: float
    odd_lot_fee: float
    odd_lot_commission: float
    odd_lot_slippage: float
    odd_lot_limit: float
    odd_lot_fill: int
    odd_lot_participation: float
    odd_lot_impact: float
    odd_lot_rounding: str
    instrument_rules_text: str
    holdout_untouched: bool


def render_sidebar() -> UIInputs:
    """Render the structured sidebar and return validated UI inputs."""
    with st.sidebar:
        st.header("🔬 研究設定")

        render_sidebar_presets()

        st.markdown("**🎯 基礎宇宙與資金**")
        odd_lot_study = st.checkbox("十萬元台股零股策略研究", value=False)
        data_modes = (
            ["TWSE 官方歷史資料", "TWSE＋FinMind 本機資料", "離線合成資料"]
            if odd_lot_study
            else ["Yahoo 公開市場資料", "離線合成資料", "M8 Verified Lifecycle Snapshot"]
        )
        data_mode = st.selectbox("資料來源", data_modes)
        reviewed_mode = data_mode == "TWSE＋FinMind 本機資料"
        twse_mode = data_mode == "TWSE 官方歷史資料" or reviewed_mode
        twse_directory = ""
        provider_directory = ""
        reviewed_no_quote = False
        twse_download = False
        twse_authorized = False
        twse_cash_events = False
        if twse_mode:
            twse_directory = st.text_input("TWSE 資料包目錄", "artifacts/twse_odd_lot")
            if reviewed_mode:
                provider_directory = st.text_input(
                    "FinMind 資料包目錄", "artifacts/data_acquisition/2026-10-28"
                )
                reviewed_no_quote = st.checkbox(
                    "依官方個股停牌證據核對無報價",
                    value=False,
                    help="僅接受與有來源個股停牌相符的無報價紀錄；無證據或報價衝突仍阻擋，選擇會凍結在來源政策。",
                )
                st.caption("保留兩個來源的原始紀錄；事件、日曆與暖機仍須通過檢查。")
            twse_download = st.checkbox("使用已授權的 TWSE 自動下載", value=False)
            if twse_download:
                twse_authorized = st.checkbox(
                    "證交所已同意這種自動化存取方式", value=False
                )
                st.caption("證交所網站使用條款限制自動化下載；未獲同意時請匯入官方檔案。")
            twse_cash_events = st.checkbox("從官方索引補入純現金股利", value=True)
            st.caption("除權息明細、分割及停牌須提供官方佐證；尚未完成的期間不計算績效。")
            render_twse_import_tools(twse_directory)

        verified_mode = data_mode == "M8 Verified Lifecycle Snapshot"
        if verified_mode:
            symbols_text = st.text_input("交易 Security IDs", "")
            benchmark = st.text_input("比較基準 Security ID", "")
            market_snapshot_directory = st.text_input(
                "Market snapshot 目錄", "artifacts/provider_cache/latest"
            )
            lifecycle_snapshot_directory = st.text_input(
                "Lifecycle snapshot 目錄", "artifacts/security_lifecycle/latest"
            )
            cash_in_lieu_snapshot_directory = st.text_input(
                "Cash-in-lieu settlement snapshot 目錄（選填）", ""
            )
            st.caption(
                "此模式只接受 stable security_id；market/lifecycle 與選填 settlement snapshot 都會先做 hash / dataset-ID 驗證。"
            )
        else:
            symbols_text = st.text_input(
                "交易標的",
                ",".join(SAMPLE_SYMBOLS) if odd_lot_study else "AAPL,MSFT,NVDA,GOOGL",
            )
            benchmark = st.text_input(
                "比較基準", SAMPLE_BENCHMARK if odd_lot_study else "SPY"
            )
            market_snapshot_directory = ""
            lifecycle_snapshot_directory = ""
            cash_in_lieu_snapshot_directory = ""

        base_currency = st.selectbox("投資組合基準幣別", ["TWD", "USD"])
        taipei_now = datetime.now(timezone(timedelta(hours=8)))
        end_default = taipei_now.date()
        if odd_lot_study and taipei_now.hour < 18:
            end_default -= timedelta(days=1)
        if reviewed_mode:
            try:
                manifest_path = Path(provider_directory) / "provider_manifest.json"
                provider_manifest = json.loads(manifest_path.read_text())
                cutoff = provider_manifest["research_cutoff"]
                end_default = datetime.fromisoformat(cutoff).date()
            except (OSError, ValueError, KeyError):
                st.caption("執行時會核對 FinMind 資料包、日期範圍與來源。")
        end_date = st.date_input("結束日", value=end_default)
        start_default = (
            datetime(2021, 1, 1).date()
            if odd_lot_study
            else end_date - timedelta(days=365 * 4)
        )
        start_date = st.date_input("開始日", value=start_default)
        initial_default = 100_000.0 if odd_lot_study else 1_000_000.0
        initial_step = 10_000.0 if odd_lot_study else 100_000.0
        initial_cash = st.number_input(
            f"虛擬初始資金（{base_currency}）",
            min_value=10_000.0,
            value=initial_default,
            step=initial_step,
        )
        execution_price_basis = st.selectbox(
            "成交/持倉價格基準",
            ["adjusted", "raw"],
            index=1 if odd_lot_study else 0,
            help="adjusted 維持總報酬價格；raw 會另行入帳 split/dividend corporate actions。",
        )
        max_weight = st.slider(
            "單一標的最大權重", 0.05, 0.50, 0.20 if odd_lot_study else 0.25, 0.05
        )
        rebalance_every = st.slider("再平衡頻率（交易日）", 1, 20, 5)
        train_fraction = st.slider("回測 / paper replay 切分", 0.55, 0.90, 0.70, 0.05)
        run_walkforward = st.checkbox(
            "執行 M2 Walk-forward OOS", value=False, disabled=odd_lot_study
        )
        walkforward_objective = st.selectbox(
            "Walk-forward 選參指標", ["calmar", "sharpe", "annual_return"]
        )

        st.markdown("**💰 稅務與閒置收益**")
        cash_annual_yield_pct = st.number_input(
            "閒置現金年收益假設（%）",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
        )
        st.caption(
            "M11-2：基準幣別可支用現金以 ACT/365 計息；persistent SQLite ledger "
            "鎖定收益率並按結算日防重複入帳。"
        )
        us_dividend_withholding_pct = st.number_input(
            "US 股息預扣率（%）", min_value=0.0, max_value=100.0, value=0.0, step=1.0
        )
        tw_dividend_withholding_pct = st.number_input(
            "TW 股息預扣率（%）", min_value=0.0, max_value=100.0, value=0.0, step=1.0
        )
        st.caption(
            "僅 raw-price corporate-action 模式套用；預設 0%，不替使用者假定稅務身分。"
        )

        risk = render_risk_and_factors(odd_lot_study)
        paper = render_paper_ledger_controls(odd_lot_study)
        odd_lot = render_odd_lot_assumptions(odd_lot_study)

        run = st.button("執行模型", type="primary", use_container_width=True)

    return UIInputs(
        run=run,
        odd_lot_study=odd_lot_study,
        data_mode=data_mode,
        twse_mode=twse_mode,
        reviewed_mode=reviewed_mode,
        verified_mode=verified_mode,
        twse_directory=twse_directory,
        provider_directory=provider_directory,
        reviewed_no_quote=reviewed_no_quote,
        twse_download=twse_download,
        twse_authorized=twse_authorized,
        twse_cash_events=twse_cash_events,
        symbols_text=symbols_text,
        benchmark=benchmark,
        market_snapshot_directory=market_snapshot_directory,
        lifecycle_snapshot_directory=lifecycle_snapshot_directory,
        cash_in_lieu_snapshot_directory=cash_in_lieu_snapshot_directory,
        base_currency=base_currency,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        cash_annual_yield_pct=cash_annual_yield_pct,
        execution_price_basis=execution_price_basis,
        us_dividend_withholding_pct=us_dividend_withholding_pct,
        tw_dividend_withholding_pct=tw_dividend_withholding_pct,
        max_weight=max_weight,
        rebalance_every=rebalance_every,
        train_fraction=train_fraction,
        run_walkforward=run_walkforward,
        walkforward_objective=walkforward_objective,
        regime_enabled=risk.regime_enabled,
        factor_neutralization=risk.factor_neutralization,
        factor_neutralization_strength=risk.factor_neutralization_strength,
        risk_budget_penalty=risk.risk_budget_penalty,
        persist_paper_ledger=paper.persist_paper_ledger,
        paper_ledger_path=paper.paper_ledger_path,
        paper_snapshot_root=paper.paper_snapshot_root,
        paper_ledger_mode=paper.paper_ledger_mode,
        paper_confirm_rebuild=paper.paper_confirm_rebuild,
        export_verifiable_report=paper.export_verifiable_report,
        run_factor_research=risk.run_factor_research,
        enable_factor_alpha=risk.enable_factor_alpha,
        factor_alpha_weight=risk.factor_alpha_weight,
        enable_vol_target=risk.enable_vol_target,
        target_annual_volatility=risk.target_annual_volatility,
        enable_cvar_control=risk.enable_cvar_control,
        max_daily_cvar=risk.max_daily_cvar,
        enable_drawdown_control=risk.enable_drawdown_control,
        drawdown_soft_limit=risk.drawdown_soft_limit,
        drawdown_hard_limit=risk.drawdown_hard_limit,
        drawdown_min_exposure=risk.drawdown_min_exposure,
        run_robustness=risk.run_robustness,
        odd_lot_risk=odd_lot.odd_lot_risk,
        odd_lot_fee=odd_lot.odd_lot_fee,
        odd_lot_commission=odd_lot.odd_lot_commission,
        odd_lot_slippage=odd_lot.odd_lot_slippage,
        odd_lot_limit=odd_lot.odd_lot_limit,
        odd_lot_fill=odd_lot.odd_lot_fill,
        odd_lot_participation=odd_lot.odd_lot_participation,
        odd_lot_impact=odd_lot.odd_lot_impact,
        odd_lot_rounding=odd_lot.odd_lot_rounding,
        instrument_rules_text=odd_lot.instrument_rules_text,
        holdout_untouched=odd_lot.holdout_untouched,
    )
