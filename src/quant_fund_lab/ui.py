from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_fund_lab.analytics import buy_and_hold_equity, metric_frame
from quant_fund_lab.cash_in_lieu_analytics import cash_in_lieu_by_source, summarize_cash_in_lieu
from quant_fund_lab.config import (
    BacktestConfig,
    DividendWithholdingConfig,
    StrategyConfig,
)
from quant_fund_lab.data import MarketData, synthetic_market_data
from quant_fund_lab.data_quality import validate_corporate_actions
from quant_fund_lab.diagnostics import diagnose_walk_forward
from quant_fund_lab.factors import research_factors
from quant_fund_lab.fx import attach_fx_rates, attach_yahoo_fx, validate_fx
from quant_fund_lab.odd_lot_execution import default_instrument_rules
from quant_fund_lab.odd_lot_research import OddLotResearchConfig
from quant_fund_lab.odd_lot_study import (
    PERIODS,
    SAMPLE_BENCHMARK,
    SAMPLE_SYMBOLS,
    OddLotStudyResult,
    export_odd_lot_study_report,
    freeze_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from quant_fund_lab.paper import historical_vs_paper_replay
from quant_fund_lab.paper_live import replay_targets_persistently
from quant_fund_lab.paper_workflow import plan_persistent_paper_run
from quant_fund_lab.provenance import AuditLog, build_run_manifest
from quant_fund_lab.providers import SnapshotProvider, YahooProvider, load_with_failover
from quant_fund_lab.reporting import export_research_report, verify_research_report
from quant_fund_lab.robustness import build_robustness_report
from quant_fund_lab.snapshot import save_market_data_snapshot
from quant_fund_lab.tax_analytics import dividend_tax_by_currency, summarize_dividend_tax
from quant_fund_lab.twse_odd_lot import (
    download_twse_bundle,
    import_twse_file,
    populate_cash_dividends,
    prepare_twse_odd_lot,
)
from quant_fund_lab.twse_preparation import (
    batch_import_twse,
    missing_source_manifest,
    read_batch_manifest,
    summarize_period_issues,
    summarize_quality_issues,
)
from quant_fund_lab.ui_inputs import load_verified_ui_inputs
from quant_fund_lab.walkforward import (
    WalkForwardSpec,
    generate_candidate_grid,
    run_walk_forward,
)

st.set_page_config(page_title="Quant Fund Lab", layout="wide")
st.title("Quant Fund Lab")
st.caption("數學 Alpha → 風險模型 → 組合最佳化 → 模擬成交；僅虛擬資金，不連接券商。")

with st.sidebar:
    st.header("研究設定")
    odd_lot_study = st.checkbox("十萬元台股零股策略研究", value=False)
    data_modes = (["TWSE 官方歷史資料", "離線合成資料"] if odd_lot_study else
                  ["Yahoo 公開市場資料", "離線合成資料", "M8 Verified Lifecycle Snapshot"])
    data_mode = st.selectbox("資料來源", data_modes)
    twse_mode = data_mode == "TWSE 官方歷史資料"
    twse_directory = ""
    twse_download = False
    twse_authorized = False
    twse_cash_events = False
    if twse_mode:
        twse_directory = st.text_input("TWSE 資料包目錄", "artifacts/twse_odd_lot")
        twse_download = st.checkbox("使用已授權的 TWSE 自動下載", value=False)
        if twse_download:
            twse_authorized = st.checkbox("證交所已同意這種自動化存取方式", value=False)
            st.caption("證交所網站使用條款限制自動化下載；未獲同意時請匯入官方檔案。")
        twse_cash_events = st.checkbox("從官方索引補入純現金股利", value=True)
        st.caption("除權息明細、分割及停牌須提供官方佐證；尚未完成的期間不計算績效。")
        with st.expander("匯入已下載的證交所檔案"):
            import_path = st.text_input("官方 JSON／CSV 檔案路徑")
            import_kind = st.selectbox("檔案類型", ["price", "ex_right_index", "etf_split_index", "par_change_index", "reduction_index", "holiday_index"])
            import_url = st.text_input("證交所來源網址", "https://www.twse.com.tw/")
            import_symbol = st.text_input("價格股票代碼", "2330.TW")
            import_month = st.text_input("價格月份（YYYY-MM）", "2025-06")
            import_year = st.number_input("企業行動索引年度", min_value=2010, max_value=2100, value=2025)
            if st.button("匯入官方檔案"):
                try:
                    imported = import_twse_file(twse_directory, import_path, kind=import_kind,
                                                source_url=import_url, symbol=import_symbol,
                                                month=import_month, year=int(import_year))
                    st.success(f"已匯入：{imported}")
                except (OSError, ValueError, KeyError) as exc:
                    st.error(f"匯入失敗：{exc}")
        with st.expander("批次匯入官方檔案"):
            st.caption("準備 CSV 清單：file,kind,source_url,symbol,month,year；相對路徑以清單所在目錄為準。")
            batch_path = st.text_input("批次清單 CSV 路徑")
            preview_batch = st.button("預覽批次匯入")
            import_batch = st.button("執行批次匯入")
            if preview_batch or import_batch:
                try:
                    rows = read_batch_manifest(batch_path)
                    result = batch_import_twse(twse_directory, rows, dry_run=not import_batch)
                    st.dataframe(result, use_container_width=True)
                    st.caption("相同來源可重試；衝突檔案不會覆寫。請先預覽並確認來源網址。")
                except (OSError, ValueError, KeyError) as exc:
                    st.error(f"批次清單無法處理：{exc}")
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
            "交易標的", ",".join(SAMPLE_SYMBOLS) if odd_lot_study else "AAPL,MSFT,NVDA,GOOGL"
        )
        benchmark = st.text_input("比較基準", SAMPLE_BENCHMARK if odd_lot_study else "SPY")
        market_snapshot_directory = ""
        lifecycle_snapshot_directory = ""
        cash_in_lieu_snapshot_directory = ""
    base_currency = st.selectbox("投資組合基準幣別", ["TWD", "USD"])
    taipei_now = datetime.now(timezone(timedelta(hours=8)))
    end_default = taipei_now.date()
    if odd_lot_study and taipei_now.hour < 18:
        end_default -= timedelta(days=1)
    end_date = st.date_input("結束日", value=end_default)
    start_date = st.date_input(
        "開始日", value=datetime(2021, 1, 1).date() if odd_lot_study else end_date - timedelta(days=365 * 4)
    )
    initial_cash = st.number_input(
        f"虛擬初始資金（{base_currency}）",
        min_value=10_000.0,
        value=100_000.0 if odd_lot_study else 1_000_000.0,
        step=10_000.0 if odd_lot_study else 100_000.0,
    )
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
    execution_price_basis = st.selectbox(
        "成交/持倉價格基準",
        ["adjusted", "raw"],
        index=1 if odd_lot_study else 0,
        help="adjusted 維持總報酬價格；raw 會另行入帳 split/dividend corporate actions。",
    )
    st.markdown("**M9 股息稅務假設**")
    us_dividend_withholding_pct = st.number_input(
        "US 股息預扣率（%）", min_value=0.0, max_value=100.0, value=0.0, step=1.0
    )
    tw_dividend_withholding_pct = st.number_input(
        "TW 股息預扣率（%）", min_value=0.0, max_value=100.0, value=0.0, step=1.0
    )
    st.caption("僅 raw-price corporate-action 模式套用；預設 0%，不替使用者假定稅務身分。")
    max_weight = st.slider("單一標的最大權重", 0.05, 0.50, 0.20 if odd_lot_study else 0.25, 0.05)
    rebalance_every = st.slider("再平衡頻率（交易日）", 1, 20, 5)
    train_fraction = st.slider("回測 / paper replay 切分", 0.55, 0.90, 0.70, 0.05)
    run_walkforward = st.checkbox("執行 M2 Walk-forward OOS", value=False, disabled=odd_lot_study)
    walkforward_objective = st.selectbox("Walk-forward 選參指標", ["calmar", "sharpe", "annual_return"])
    st.markdown("**M2-3 風險研究**")
    regime_enabled = st.checkbox("Regime detection", value=True)
    factor_neutralization = st.checkbox("Factor neutralization", value=True)
    factor_neutralization_strength = st.slider(
        "Factor neutralization strength", 0.0, 1.0, 0.50, 0.10
    )
    risk_budget_penalty = st.slider(
        "Risk-budget penalty", 0.0, 0.010, 0.001, 0.001, format="%.3f"
    )
    st.markdown("**M3 Persistent Paper Trading**")
    persist_paper_ledger = st.checkbox("啟用本機 persistent paper ledger", value=False, disabled=odd_lot_study)
    paper_ledger_path = Path("artifacts/paper_trading.sqlite")
    paper_snapshot_root = Path("artifacts/paper_snapshots")
    paper_ledger_mode = "continue"
    paper_confirm_rebuild = False
    if persist_paper_ledger:
        existing_paper_ledger = paper_ledger_path.is_file()
        paper_ledger_mode = st.radio(
            "虛擬帳本操作",
            ["continue", "rebuild"],
            index=0 if existing_paper_ledger else 1,
            format_func=lambda mode: (
                "安全續跑現有帳本（不得覆寫）"
                if mode == "continue"
                else "建立新帳本（可能覆寫原始交易紀錄）"
            ),
        )
        if paper_ledger_mode == "continue":
            st.caption(
                "續跑前核對舊交易日的價格、FX、目標權重、成交設定和 snapshot；"
                "不一致時停止，不會自動清除 SQLite。"
            )
        else:
            st.caption(
                "新建模式會重設 SQLite 並覆寫相同日期的 snapshots。"
                "若已有帳本，請先備份整個 artifacts/paper_trading.sqlite "
                "及 artifacts/paper_snapshots/。"
            )
            if existing_paper_ledger:
                paper_confirm_rebuild = st.checkbox(
                    "我已備份或明確接受既有虛擬交易紀錄被覆寫"
                )
    st.markdown("**M4 Production Hardening**")
    export_verifiable_report = st.checkbox("匯出可驗證研究報告", value=False)
    st.markdown("**M5 Factor Laboratory**")
    run_factor_research = st.checkbox("執行因子 IC / Decay 研究", value=False, disabled=odd_lot_study)
    enable_factor_alpha = st.checkbox("啟用 trailing-IC Factor Alpha overlay", value=False, disabled=odd_lot_study)
    factor_alpha_weight = st.slider("Factor Alpha overlay 權重", 0.0, 0.60, 0.30, 0.05)
    enable_vol_target = st.checkbox("Volatility targeting", value=False, disabled=odd_lot_study)
    target_annual_volatility = st.slider("目標年化波動", 0.05, 0.30, 0.12, 0.01)
    enable_cvar_control = st.checkbox("CVaR / Expected Shortfall cap", value=False, disabled=odd_lot_study)
    max_daily_cvar = st.slider("最大日 CVaR", 0.005, 0.050, 0.025, 0.005, format="%.3f")
    enable_drawdown_control = st.checkbox("Drawdown de-risking", value=False, disabled=odd_lot_study)
    drawdown_soft_limit = st.slider("Drawdown soft limit", 0.05, 0.20, 0.10, 0.01)
    drawdown_hard_min = min(drawdown_soft_limit + 0.05, 0.40)
    drawdown_hard_limit = st.slider(
        "Drawdown hard limit", drawdown_hard_min, 0.50, max(0.20, drawdown_hard_min), 0.01
    )
    drawdown_min_exposure = st.slider("Hard-limit 最低風險曝險", 0.0, 0.75, 0.25, 0.05)
    run_robustness = st.checkbox("執行 M5-4 Robustness Lab", value=False, disabled=odd_lot_study)
    odd_lot_risk = 2_000.0
    odd_lot_fee = 20.0
    holdout_untouched = False
    if odd_lot_study:
        st.markdown("**台股零股研究假設**")
        odd_lot_risk = st.number_input("單筆預估風險預算（TWD）", min_value=1.0, value=2_000.0, step=100.0)
        odd_lot_fee = st.number_input("最低手續費情境（每筆 TWD）", min_value=0.0, value=20.0, step=1.0)
        odd_lot_commission = st.number_input("手續費率（bps）", min_value=0.0, value=14.25, step=0.25)
        odd_lot_slippage = st.number_input("滑價情境（bps）", min_value=0.0, value=5.0, step=1.0)
        odd_lot_limit = st.number_input("限價距權息調整參考價（%）", min_value=0.0, max_value=99.0, value=1.0, step=0.5)
        odd_lot_fill = st.slider("單筆委託模擬成交比例（%）", 1, 100, 50)
        odd_lot_participation = st.number_input("歷史普通成交量參與率上限（%）", min_value=0.01, max_value=100.0, value=5.0, step=1.0)
        odd_lot_impact = st.number_input("市場衝擊係數", min_value=0.0, value=0.10, step=0.01)
        odd_lot_rounding = st.selectbox("手續費與證交稅進位假設", ["fractional", "floor", "nearest"],
                                        format_func=lambda x: {"fractional": "保留小數", "floor": "捨去至元", "nearest": "四捨五入至元"}[x])
        instrument_rules_text = st.text_area(
            "交易標的規則（JSON）", value=json.dumps(default_instrument_rules(), ensure_ascii=False, indent=2),
            help="每個交易標的須明確指定 kind（stock/etf）、sell_tax_bps、price_limit_pct；null 表示無漲跌幅限制。這是全研究期間的情境假設，不會自動辨識歷史例外。",
        )
        holdout_untouched = st.checkbox("確認 2025 年後資料尚未用於此策略調參", value=False)
        st.caption("整股開盤及歷史成交量僅為零股代理，成交比例並非真實成交機率；收盤觸發止損，次交易日嘗試退出。T+2 以資料交易日代理，賣款在當日開盤後入帳。")
        st.caption("進階 Factor / CVaR / Walk-forward 設定不套用於此研究；帳本存檔只供稽核，無法續跑。")
    run = st.button("執行模型", type="primary", use_container_width=True)


@st.cache_data(show_spinner=False)
def load_data(
    mode: str, symbols: tuple[str, ...], start: str, end: str
) -> tuple[MarketData, str, tuple[tuple[str, bool, str | None], ...]]:
    if mode == "離線合成資料":
        return synthetic_market_data(symbols=symbols, periods=800), "synthetic", (("synthetic", True, None),)
    result = load_with_failover(
        [YahooProvider(), SnapshotProvider(("artifacts/provider_cache",))],
        list(symbols),
        start,
        end,
    )
    attempts = tuple((item.provider, item.success, item.error) for item in result.attempts)
    return result.data, result.provider, attempts


def render_odd_lot_study(study: OddLotStudyResult, frozen: Path, report: Path, provider: str) -> None:
    st.subheader("台股零股策略研究")
    st.warning(
        "價格與成交量是普通交易資料的代理，不能保證零股成交或止損；"
        "現存股票示例池有存活者偏差。"
    )
    if provider == "synthetic":
        st.warning("目前為合成測試資料，不代表真實市場或策略績效。")
    if not study.holdout_untouched:
        st.warning("2025 年後資料是否已用於調參未確認；歷史評估應視為探索性結果。")
    st.caption(f"研究 ID：{study.study_id}；資料 ID：{study.dataset_id}。")
    st.caption(f"凍結資料：{frozen}；報告：{report}；報告校驗：{'PASS' if verify_odd_lot_study_report(report) else 'FAIL'}。")
    st.dataframe(study.comparison, use_container_width=True)
    st.caption("完整交易少於 30 筆標示樣本不足；30 筆以上也不代表策略已獲證實。市場基準是未扣交易成本的總報酬代理。")
    st.caption("供應商價格是否為真實未調整價格、股息實際入帳時間與零股歷史成交價尚未獨立驗證。")
    if study.unavailable:
        st.info("部分期間資料不足：" + "; ".join(f"{key}: {value}" for key, value in study.unavailable.items()))
    st.subheader("手續費、滑價與成交比例敏感度（2024 驗證期）")
    st.dataframe(study.sensitivity, use_container_width=True)
    keys = list(study.results)
    if keys:
        selected = st.selectbox("研究明細", keys, format_func=lambda item: f"{item[0]} / {item[1]}")
        detail = study.results[selected]
        st.line_chart(detail.equity_curve["equity"])
        a, b, c, d, e = st.tabs(["完整與未平倉交易", "進出場訊號", "成交紀錄", "限價委託", "交割明細"])
        with a:
            st.dataframe(detail.episodes, use_container_width=True)
        with b:
            st.dataframe(detail.signals, use_container_width=True)
        with c:
            st.dataframe(detail.fills, use_container_width=True)
        with d:
            st.dataframe(detail.orders, use_container_width=True)
        with e:
            st.dataframe(detail.settlements, use_container_width=True)
            st.dataframe(detail.equity_curve[["cash", "settled_cash", "buy_payables", "sale_receivables", "sale_payables"]], use_container_width=True)


if run:
    requested_trade_assets = [
        s.strip() if verified_mode else s.strip().upper()
        for s in symbols_text.split(",")
        if s.strip()
    ]
    requested_benchmark = benchmark.strip() if verified_mode else benchmark.strip().upper()
    all_symbols = list(dict.fromkeys(requested_trade_assets + [requested_benchmark]))
    if len(requested_trade_assets) < 2:
        st.error("至少提供兩個交易標的，橫斷面模型才有意義。")
        st.stop()
    if odd_lot_study and persist_paper_ledger:
        st.error("零股策略研究使用獨立的凍結研究紀錄；目前不能續跑一般 persistent paper ledger。")
        st.stop()
    if odd_lot_study and (base_currency != "TWD" or execution_price_basis != "raw"):
        st.error("台股零股研究需要 TWD 基準幣別及 raw 成交價格。")
        st.stop()
    paper_ledger_reset = True
    if persist_paper_ledger:
        try:
            paper_ledger_reset = plan_persistent_paper_run(
                paper_ledger_path,
                paper_ledger_mode,
                confirmed_rebuild=paper_confirm_rebuild,
            )
        except (FileNotFoundError, ValueError) as exc:
            st.error(f"虛擬帳本操作已取消：{exc}")
            st.stop()

    try:
        with st.spinner("載入資料並執行 walk-forward paper replay..."):
            source_data_provenance: dict[str, str] = {}
            twse_inputs = None
            if twse_mode:
                warmup_start = start_date - timedelta(days=250)
                if twse_download:
                    download_twse_bundle(twse_directory, all_symbols, str(warmup_start), str(end_date),
                                         authorized=twse_authorized)
                if twse_cash_events:
                    populate_cash_dividends(twse_directory, all_symbols)
                twse_inputs = prepare_twse_odd_lot(twse_directory, all_symbols, str(warmup_start), str(end_date))
                raw = twse_inputs.data
                trade_data = raw
                trade_symbols = requested_trade_assets
                benchmark_symbol = requested_benchmark
                source_data_provenance = twse_inputs.provenance
                data_provider = "twse_official"
                provider_attempts = ((data_provider, True, None),)
                if twse_inputs.issues:
                    st.warning(f"官方資料檢查發現 {len(twse_inputs.issues)} 項問題；受影響期間不計算績效。")
                    summary, details = summarize_quality_issues(twse_inputs.issues, symbols=raw.symbols)
                    period_quality = summarize_period_issues(
                        twse_inputs.issues, raw.close.index, PERIODS,
                        warmup=max(120, StrategyConfig().warmup_days),
                        coverage_end=twse_inputs.provenance["coverage_end"],
                    )
                    st.caption("各期暖機起點依目前觀測值估計，缺失交易日可能改變估計；正式守門仍以研究結果為準。")
                    st.dataframe(period_quality, use_container_width=True)
                    st.dataframe(summary, use_container_width=True)
                    checklist = missing_source_manifest(twse_inputs.issues)
                    if not checklist.empty:
                        st.caption("缺檔清單的網址僅供核對；填入本機檔案及實際來源網址後才可匯入。")
                        st.download_button("下載缺檔匯入清單", checklist.to_csv(index=False).encode("utf-8-sig"),
                                           file_name="twse_missing_sources.csv", mime="text/csv")
                    with st.expander("完整資料問題與關聯"):
                        st.dataframe(details, use_container_width=True)
                else:
                    st.success("資料包檢查通過；歷史發布與修訂時間仍未獨立驗證。")
            elif verified_mode:
                verified_inputs = load_verified_ui_inputs(
                    market_snapshot_directory,
                    lifecycle_snapshot_directory,
                    requested_trade_assets,
                    requested_benchmark,
                    cash_in_lieu_snapshot_directory=cash_in_lieu_snapshot_directory or None,
                    start=start_date,
                    end=end_date,
                    base_currency=base_currency,
                )
                raw = verified_inputs.raw
                trade_data = verified_inputs.trade_data
                trade_symbols = list(verified_inputs.trade_assets)
                benchmark_symbol = verified_inputs.benchmark_asset
                source_data_provenance = verified_inputs.data_provenance
                data_provider = "verified_identity_snapshots"
                provider_attempts = ((data_provider, True, None),)
            else:
                trade_symbols = requested_trade_assets
                raw, data_provider, provider_attempts = load_data(
                    data_mode,
                    tuple(all_symbols),
                    str(start_date),
                    str(end_date + timedelta(days=1)),
                )
                if data_mode == "Yahoo 公開市場資料":
                    if raw.fx_to_base is None:
                        try:
                            raw = attach_yahoo_fx(raw, base_currency=base_currency)
                        except Exception:  # noqa: BLE001 - retry through verified local fallback.
                            fallback = load_with_failover(
                                [SnapshotProvider(("artifacts/provider_cache",))],
                                all_symbols,
                                str(start_date),
                                str(end_date + timedelta(days=1)),
                            )
                            raw = fallback.data
                            data_provider = fallback.provider
                            provider_attempts = provider_attempts + tuple(
                                (item.provider, item.success, item.error)
                                for item in fallback.attempts
                            )
                    if data_provider == "yahoo":
                        save_market_data_snapshot(
                            raw, "artifacts/provider_cache/latest", overwrite=True
                        )
                else:
                    synthetic_usd_twd = pd.Series(32.0, index=raw.close.index, dtype=float)
                    raw = attach_fx_rates(raw, base_currency, usd_twd=synthetic_usd_twd)
                trade_data = MarketData(
                    open=raw.open[trade_symbols],
                    close=raw.close[trade_symbols],
                    volume=raw.volume[trade_symbols],
                    raw_open=raw.raw_open[trade_symbols] if raw.raw_open is not None else None,
                    raw_close=raw.raw_close[trade_symbols] if raw.raw_close is not None else None,
                    reference=raw.reference[trade_symbols] if raw.reference is not None else None,
                    membership=raw.membership[trade_symbols] if raw.membership is not None else None,
                    terminal_returns=(
                        raw.terminal_returns[trade_symbols]
                        if raw.terminal_returns is not None
                        else None
                    ),
                    dividends=raw.dividends[trade_symbols] if raw.dividends is not None else None,
                    stock_splits=(
                        raw.stock_splits[trade_symbols] if raw.stock_splits is not None else None
                    ),
                    cash_in_lieu_prices=(
                        raw.cash_in_lieu_prices[trade_symbols]
                        if raw.cash_in_lieu_prices is not None
                        else None
                    ),
                    cash_in_lieu_settlement_dates=(
                        raw.cash_in_lieu_settlement_dates[trade_symbols]
                        if raw.cash_in_lieu_settlement_dates is not None
                        else None
                    ),
                    fx_to_base=raw.fx_to_base[trade_symbols] if raw.fx_to_base is not None else None,
                    fx_age_days=(
                        raw.fx_age_days[trade_symbols] if raw.fx_age_days is not None else None
                    ),
                    market_codes=(
                        raw.market_codes[trade_symbols] if raw.market_codes is not None else None
                    ),
                    currency_codes=(
                        raw.currency_codes[trade_symbols]
                        if raw.currency_codes is not None
                        else None
                    ),
                    base_currency=raw.base_currency,
                    exchange=raw.exchange,
                )
                benchmark_symbol = requested_benchmark
            strategy = StrategyConfig(
                max_weight=max_weight,
                rebalance_every=rebalance_every,
                regime_enabled=regime_enabled,
                factor_neutralization=factor_neutralization,
                factor_neutralization_strength=factor_neutralization_strength,
                risk_budget_penalty=risk_budget_penalty,
                factor_alpha_enabled=enable_factor_alpha and not odd_lot_study,
                factor_alpha_weight=factor_alpha_weight,
                volatility_target_enabled=enable_vol_target and not odd_lot_study,
                target_annual_volatility=target_annual_volatility,
                cvar_control_enabled=enable_cvar_control and not odd_lot_study,
                max_daily_cvar=max_daily_cvar,
                drawdown_control_enabled=enable_drawdown_control and not odd_lot_study,
                drawdown_soft_limit=drawdown_soft_limit,
                drawdown_hard_limit=drawdown_hard_limit,
                drawdown_min_exposure=drawdown_min_exposure,
            )
            config = BacktestConfig(
                initial_cash=initial_cash,
                cash_annual_yield=float(cash_annual_yield_pct) / 100.0,
                base_currency=base_currency,
                execution_price_basis=execution_price_basis,
                dividend_withholding=DividendWithholdingConfig(
                    us_rate=float(us_dividend_withholding_pct) / 100.0,
                    tw_rate=float(tw_dividend_withholding_pct) / 100.0,
                ),
                strategy=strategy,
            )
            if odd_lot_study:
                if not twse_mode:
                    raw = raw.slice(start=start_date, end=end_date)
                assumptions = OddLotResearchConfig(
                    risk_budget=float(odd_lot_risk),
                    max_weight=float(max_weight),
                    rebalance_every=int(rebalance_every),
                    min_commission=float(odd_lot_fee),
                    commission_bps=float(odd_lot_commission),
                    slippage_bps=float(odd_lot_slippage),
                    limit_offset=float(odd_lot_limit) / 100,
                    fill_fraction=float(odd_lot_fill) / 100,
                    max_participation=float(odd_lot_participation) / 100,
                    impact_coefficient=float(odd_lot_impact),
                    fee_rounding=odd_lot_rounding,
                    instrument_rules=json.loads(instrument_rules_text),
                )
                frozen = freeze_odd_lot_study(
                    raw, "artifacts/odd_lot_studies", symbols=tuple(trade_symbols),
                    benchmark=benchmark_symbol, research=assumptions, base_config=config,
                    source=data_provider, source_provenance=source_data_provenance,
                    holdout_untouched=holdout_untouched,
                    source_files=twse_inputs.source_files if twse_inputs else None,
                    source_hashes=twse_inputs.source_hashes if twse_inputs else None,
                    quality_issues=[asdict(issue) for issue in twse_inputs.issues] if twse_inputs else None,
                )
                study = run_frozen_odd_lot_study(frozen)
                report = export_odd_lot_study_report(frozen, study)
                st.session_state["odd_lot_study_result"] = (study, frozen, report, data_provider)
                render_odd_lot_study(study, frozen, report, data_provider)
                st.stop()
            comparison = historical_vs_paper_replay(trade_data, config, train_fraction=train_fraction)
            robustness = (
                build_robustness_report(
                    trade_data,
                    config,
                    train_fraction,
                    comparison.paper_replay,
                    cost_multipliers=(1.0, 1.5, 2.0),
                    bootstrap_iterations=300,
                    block_length=10,
                    seed=19,
                )
                if run_robustness
                else None
            )
            factor_research = (
                research_factors(
                    trade_data,
                    sampling_every=max(rebalance_every, 1),
                    horizons=(1, 5, 20),
                )
                if run_factor_research
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
                    "symbols": all_symbols,
                },
            )
            report_export = None
            if export_verifiable_report:
                input_snapshot = save_market_data_snapshot(
                    trade_data, "artifacts/report_input/latest", overwrite=True
                )
                run_context = {
                    "mode": "paper_replay",
                    "train_fraction": float(train_fraction),
                    "split_date": str(comparison.split_date.date()),
                }
                data_provenance = dict(source_data_provenance)
                if data_provenance:
                    data_provenance["derived_trade_dataset_id"] = input_snapshot.dataset_id
                else:
                    data_provenance["market_data_dataset_id"] = input_snapshot.dataset_id
                run_manifest = build_run_manifest(
                    config,
                    input_snapshot.dataset_id,
                    run_context=run_context,
                    data_provenance=data_provenance,
                )
                report_directory = f"artifacts/reports/{run_manifest.run_id}"
                exported_run, _ = export_research_report(
                    comparison.paper_replay,
                    config,
                    input_snapshot.dataset_id,
                    report_directory,
                    run_context=run_context,
                    data_provenance=data_provenance,
                )
                report_verified = verify_research_report(report_directory)
                audit.append(
                    "REPORT_EXPORTED",
                    {
                        "run_id": exported_run.run_id,
                        "dataset_id": input_snapshot.dataset_id,
                        "data_provenance": data_provenance,
                        "path": report_directory,
                        "verified": report_verified,
                    },
                )
                report_export = (exported_run.run_id, report_directory, report_verified)
            benchmark_close_base = (
                raw.close[benchmark_symbol] * raw.fx_to_base[benchmark_symbol]
            ).ffill().dropna()
            persistent_nav = None
            persistent_orders = None
            persistent_fills = None
            persistent_positions = None
            persistent_snapshots = None
            persistent_actions = None
            persistent_receivables = None
            persistent_interest_credits = None
            persistent_session_commits = None
            persistent_replay_execution_config = None
            persistent_ledger_audit = None
            if persist_paper_ledger:
                try:
                    ledger = replay_targets_persistently(
                        trade_data,
                        comparison.paper_replay.weights,
                        config,
                        paper_ledger_path,
                        snapshot_root=paper_snapshot_root,
                        benchmark_close_base=benchmark_close_base,
                        reset=paper_ledger_reset,
                    )
                except (FileNotFoundError, ValueError) as exc:
                    st.error(
                        f"虛擬帳本未變更：{exc}。安全續跑需要完整且相同的既有"
                        "市場資料、訊號、交易參數與快照；如需重建請先備份，再明確選擇新建。"
                    )
                    st.stop()
                try:
                    persistent_nav = ledger.nav_history()
                    persistent_orders = ledger.orders()
                    persistent_fills = ledger.fills()
                    persistent_positions = ledger.positions()
                    persistent_snapshots = ledger.snapshots()
                    persistent_actions = ledger.corporate_actions()
                    persistent_receivables = ledger.cash_in_lieu_receivables()
                    persistent_interest_credits = ledger.cash_interest_credits()
                    persistent_session_commits = ledger.session_commits()
                    persistent_replay_execution_config = ledger.replay_execution_config()
                    persistent_ledger_audit = ledger.audit_integrity()
                finally:
                    ledger.close()

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

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("回測 vs Paper Replay")
            display = comparison.metrics.copy()
            pct_cols = ["total_return", "annual_return", "annual_volatility", "max_drawdown"]
            for c in pct_cols:
                display[c] = display[c].map(lambda x: f"{x:.2%}")
            for c in ["sharpe", "calmar"]:
                display[c] = display[c].map(lambda x: f"{x:.2f}")
            st.dataframe(display, use_container_width=True)

        with col2:
            st.subheader("Paper Replay 與市場基準")
            paper_equity = comparison.paper_replay.equity_curve["equity"]
            benchmark_close = benchmark_close_base.reindex(paper_equity.index).ffill().dropna()
            benchmark_equity = buy_and_hold_equity(benchmark_close, initial_cash)
            comparison_frame = metric_frame({"paper_replay": paper_equity, "benchmark": benchmark_equity})
            st.dataframe(comparison_frame, use_container_width=True)

        tax_summary = summarize_dividend_tax(comparison.paper_replay.corporate_actions)
        st.caption(
            "M11-1 現金收益（paper replay）："
            f"{float(comparison.paper_replay.equity_curve['cash_interest'].sum()):,.2f} "
            f"{comparison.paper_replay.base_currency}；"
            f"設定年收益率 {float(config.cash_annual_yield):.2%}。"
        )
        st.subheader("M9-3 Dividend Tax Drag")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Gross dividend", f"{float(tax_summary['gross_dividend_cash']):,.2f}")
        t2.metric("Withholding tax", f"{float(tax_summary['withholding_tax']):,.2f}")
        t3.metric("Net dividend", f"{float(tax_summary['net_dividend_cash']):,.2f}")
        t4.metric(
            "Effective withholding",
            f"{float(tax_summary['effective_withholding_rate']):.1%}",
        )
        tax_currency = dividend_tax_by_currency(comparison.paper_replay.corporate_actions)
        if not tax_currency.empty:
            st.dataframe(tax_currency, use_container_width=True)

        cil_summary = summarize_cash_in_lieu(comparison.paper_replay.corporate_actions)
        st.subheader("M10-6 Cash-in-Lieu Settlement")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fractional splits", str(int(cil_summary["fractional_split_event_count"])))
        c2.metric("Delayed", str(int(cil_summary["delayed_receivable_count"])))
        c3.metric("Fallback", str(int(cil_summary["raw_open_fallback_count"])))
        c4.metric("Settled cash", f"{float(cil_summary['cash_in_lieu_cash']):,.2f}")
        st.caption(
            "Settlement lag：avg "
            f"{float(cil_summary['average_settlement_lag_days']):.1f} days；max "
            f"{float(cil_summary['max_settlement_lag_days']):.1f} days；"
            f"unresolved {int(cil_summary['unresolved_receivable_count'])}。"
        )
        cil_sources = cash_in_lieu_by_source(comparison.paper_replay.corporate_actions)
        if not cil_sources.empty:
            st.dataframe(cil_sources, use_container_width=True)

        fig = go.Figure()
        bt = comparison.backtest.equity_curve["equity"]
        pp = comparison.paper_replay.equity_curve["equity"]
        fig.add_trace(go.Scatter(x=bt.index, y=bt / bt.iloc[0], name="Historical backtest"))
        fig.add_trace(go.Scatter(x=pp.index, y=pp / pp.iloc[0], name="Paper replay"))
        fig.update_layout(title="標準化淨值曲線", yaxis_title="Growth of 1", height=450)
        st.plotly_chart(fig, use_container_width=True)

        if factor_research is not None:
            st.subheader("M5-1 Factor Research")
            if factor_research.summary.empty:
                st.warning("目前資料不足以形成可用的 cross-sectional IC 統計。")
            else:
                st.caption(
                    "IC / Rank IC 使用 factor timestamp 之後的 forward return；"
                    "factor 本身只由當下與更早資料計算。正值代表因子排序方向與未來報酬同向。"
                )
                st.dataframe(factor_research.summary, use_container_width=True, height=360)
                f1, f2 = st.columns(2)
                with f1:
                    st.markdown("**Rank IC Decay**")
                    st.dataframe(factor_research.decay, use_container_width=True, height=300)
                with f2:
                    st.markdown("**Factor Rank Turnover**")
                    st.dataframe(
                        factor_research.turnover.rename("rank_turnover").to_frame(),
                        use_container_width=True,
                        height=300,
                    )
                st.markdown("**Average Cross-sectional Factor Correlation**")
                st.dataframe(
                    factor_research.factor_correlation,
                    use_container_width=True,
                    height=320,
                )

        if enable_factor_alpha:
            st.subheader("M5-2 Learned Factor Alpha")
            learned = comparison.paper_replay.factor_weights
            if learned.empty:
                st.info("尚未累積足夠已實現 IC 樣本；Factor overlay 暫時不改變原始 Alpha。")
            else:
                st.caption(
                    "權重由 signal date 前已完整實現的 Rank IC 學習；5 日 horizon 使用非重疊樣本，"
                    "並以 L1 正規化。正權重代表順向使用，負權重代表反向使用。"
                )
                st.dataframe(learned.tail(40), use_container_width=True, height=320)
            if len(trade_symbols) < 6:
                st.warning("目前股票數少於 6 檔，cross-sectional IC 估計會非常不穩定；較適合研究較大 universe。")

        if enable_vol_target or enable_cvar_control or enable_drawdown_control:
            st.subheader("M5-3 Portfolio Risk Controls")
            controls = comparison.paper_replay.risk_controls
            if controls.empty:
                st.info("目前沒有 risk-control observation。")
            else:
                latest_control = controls.iloc[-1]
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Final risk scale", f"{float(latest_control['final_scale']):.1%}")
                q2.metric(
                    "Forecast vol after",
                    f"{float(latest_control['forecast_annual_volatility_after']):.1%}",
                )
                q3.metric(
                    "Daily CVaR after",
                    f"{float(latest_control['historical_cvar_after']):.2%}",
                )
                q4.metric("Strategy drawdown", f"{float(latest_control['drawdown']):.1%}")
                st.caption(
                    "Risk-control scale = min(volatility scale, CVaR scale, drawdown scale)，"
                    "只縮小 risky sleeve，剩餘配置為現金，不做槓桿放大。"
                )
                st.dataframe(controls.tail(40), use_container_width=True, height=320)

        st.subheader("M2-3 Regime / Risk Budget")
        regimes = comparison.paper_replay.regimes
        if regimes.empty:
            st.info("目前沒有 regime observation。")
        else:
            latest_regime = regimes.iloc[-1]
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Current regime", str(latest_regime["label"]))
            r2.metric("Trend z", f"{float(latest_regime['trend_z']):.2f}")
            r3.metric("Annualized market vol", f"{float(latest_regime['annual_volatility']):.1%}")
            r4.metric("Gross exposure cap", f"{float(latest_regime['gross_exposure_limit']):.0%}")
            st.caption(
                f"Factor neutralization={'ON' if factor_neutralization else 'OFF'} "
                f"(strength={factor_neutralization_strength:.0%})；"
                f"risk-budget penalty={risk_budget_penalty:.3f}。"
                "Regime 與 factor exposure 每次只使用 signal date 當下以前的資料。"
            )
            st.dataframe(regimes.tail(30), use_container_width=True, height=260)

        if persistent_nav is not None and not persistent_nav.empty:
            st.subheader("M3 Persistent Paper Ledger")
            st.success(
                "M11-6 虛擬帳本："
                + ("已建立新帳本" if paper_ledger_reset else "已核對並安全續跑既有帳本")
                + f"；目前共 {len(persistent_nav)} 個已完成交易日。"
            )
            latest_nav = persistent_nav.iloc[-1]
            open_order_count = int(
                persistent_orders["status"].isin(["NEW", "PARTIAL"]).sum()
                if persistent_orders is not None and not persistent_orders.empty
                else 0
            )
            p1, p2, p3, p4 = st.columns(4)
            p1.metric(
                f"Ledger NAV ({base_currency})",
                f"{float(latest_nav['equity']):,.2f}",
            )
            p2.metric("Realized PnL", f"{float(latest_nav['realized_pnl']):,.2f}")
            p3.metric("Unrealized PnL", f"{float(latest_nav['unrealized_pnl']):,.2f}")
            p4.metric("Open / Partial Orders", str(open_order_count))
            open_receivable_count = int(
                persistent_receivables["status"].eq("OPEN").sum()
                if persistent_receivables is not None and not persistent_receivables.empty
                else 0
            )
            st.caption(
                "Cash-in-lieu receivables：open "
                f"{open_receivable_count}；current NAV mark "
                f"{float(latest_nav.get('receivable_value', 0.0)):,.2f} {base_currency}。"
            )
            st.caption(
                "M11-2 Cash carry：today "
                f"{float(latest_nav['cash_interest']):,.2f}；cumulative "
                f"{float(latest_nav['cumulative_cash_interest']):,.2f} "
                f"{base_currency}；locked annual yield {config.cash_annual_yield:.2%}。"
            )
            st.caption(
                "M11-3 Atomic sessions：committed "
                f"{len(persistent_session_commits)} / {len(persistent_nav)} NAV sessions；"
                "每日利息、成交、企業行動、NAV 與收盤目標訂單同筆 SQLite 交易提交。"
            )
            st.caption(
                "M11-4 Replay data lock：每個完成日保存價格、成交量、FX、"
                "企業行動、執行參考價及 benchmark 的 SHA-256 指紋；"
                "續跑前逐日核對，細節請見 Session Commits 分頁。"
            )
            st.caption(
                "M11-5 Execution / Snapshot audit：固定交易成本、撮合及 FX 假設；"
                "續跑前校驗已提交 snapshot 的 SQLite 連結、manifest、檔案 hash "
                "及每日重播輸入指紋。"
            )
            if persistent_ledger_audit.is_valid:
                st.success(
                    "M11-8 Independent ledger audit：PASS；"
                    f"已核對 {persistent_ledger_audit.nav_sessions} 個 NAV、"
                    f"{persistent_ledger_audit.fills} 筆成交及 "
                    f"{persistent_ledger_audit.cash_credits} 筆現金入息，"
                    "並重建逐日現金流與損益。"
                )
            else:
                st.error(
                    "M11-8 Independent ledger audit：FAIL；"
                    + persistent_ledger_audit.issues[0]
                )
            persistent_tax = summarize_dividend_tax(persistent_actions)
            st.caption(
                "Dividend cashflow：gross "
                f"{float(persistent_tax['gross_dividend_cash']):,.2f}；withholding "
                f"{float(persistent_tax['withholding_tax']):,.2f}；net "
                f"{float(persistent_tax['net_dividend_cash']):,.2f}；effective rate "
                f"{float(persistent_tax['effective_withholding_rate']):.1%}。"
            )
            ledger_fig = go.Figure()
            ledger_fig.add_trace(
                go.Scatter(x=persistent_nav.index, y=persistent_nav["equity"], name="Paper ledger NAV")
            )
            if persistent_nav["benchmark_equity"].notna().any():
                ledger_fig.add_trace(
                    go.Scatter(
                        x=persistent_nav.index,
                        y=persistent_nav["benchmark_equity"],
                        name="Benchmark",
                    )
                )
            ledger_fig.update_layout(
                title="Persistent paper NAV vs benchmark",
                yaxis_title=base_currency,
                height=380,
            )
            st.plotly_chart(ledger_fig, use_container_width=True)
            st.caption(
                "SQLite: artifacts/paper_trading.sqlite；每日可重現 market snapshots: "
                "artifacts/paper_snapshots/。未成交數量會保持 NEW/PARTIAL 並在後續交易日重試。"
            )
            pt1, pt2, pt3, pt4, pt5, pt6, pt7, pt8, pt9, pt10 = st.tabs(
                [
                    "Persistent Orders",
                    "Persistent Fills",
                    "Positions",
                    "Corporate Actions",
                    "Cash-in-Lieu Receivables",
                    "Cash Interest Credits",
                    "Session Commits",
                    "Daily Snapshots",
                    "Execution Assumptions",
                    "Ledger Accounting Audit",
                ]
            )
            with pt1:
                st.dataframe(persistent_orders, use_container_width=True, height=300)
            with pt2:
                st.dataframe(persistent_fills, use_container_width=True, height=300)
            with pt3:
                st.dataframe(persistent_positions, use_container_width=True, height=300)
            with pt4:
                st.dataframe(persistent_actions, use_container_width=True, height=300)
            with pt5:
                st.dataframe(persistent_receivables, use_container_width=True, height=300)
            with pt6:
                st.dataframe(persistent_interest_credits, use_container_width=True, height=300)
            with pt7:
                st.dataframe(persistent_session_commits, use_container_width=True, height=300)
            with pt8:
                st.dataframe(persistent_snapshots, use_container_width=True, height=300)
            with pt9:
                st.json(persistent_replay_execution_config)
            with pt10:
                st.json(
                    {
                        "passed": persistent_ledger_audit.is_valid,
                        "nav_sessions": persistent_ledger_audit.nav_sessions,
                        "fills": persistent_ledger_audit.fills,
                        "position_marks": persistent_ledger_audit.position_marks,
                        "cash_credits": persistent_ledger_audit.cash_credits,
                        "issues": list(persistent_ledger_audit.issues),
                    }
                )

        if robustness is not None:
            st.subheader("M5-4 Robustness Lab")
            st.caption(
                "Robustness 結果只作診斷，不參與參數選擇：成本壓力固定為 1.0x / 1.5x / 2.0x；"
                "block bootstrap 保留短期報酬相依；regime attribution 只使用當時已知的最新 regime；"
                "raw 模式另測 dividend withholding 基準 ±10 個百分點。"
            )
            rb1, rb2, rb3, rb4 = st.tabs(
                [
                    "Execution Cost Stress",
                    "Block Bootstrap",
                    "Regime Attribution",
                    "Dividend Tax Sensitivity",
                ]
            )
            with rb1:
                st.dataframe(robustness.cost_stress, use_container_width=True, height=320)
            with rb2:
                st.dataframe(robustness.bootstrap_summary, use_container_width=True, height=320)
            with rb3:
                st.dataframe(robustness.regime_attribution, use_container_width=True, height=320)
            with rb4:
                if robustness.dividend_tax_sensitivity.empty:
                    st.info("Dividend tax sensitivity 僅適用 raw-price corporate-action 模式。")
                else:
                    st.dataframe(
                        robustness.dividend_tax_sensitivity,
                        use_container_width=True,
                        height=320,
                    )

        if run_walkforward:
            st.subheader("Walk-forward Out-of-Sample")
            if len(trade_data.close) < 420:
                st.warning("Walk-forward 至少需要約 420 個交易日；目前資料不足。")
            else:
                with st.spinner("執行 walk-forward calibration / OOS test..."):
                    candidates = generate_candidate_grid(
                        strategy,
                        risk_aversion=(2.0, 4.0, 8.0),
                        covariance_shrinkage=(strategy.covariance_shrinkage,),
                        rebalance_every=(5, 10),
                    )
                    wf = run_walk_forward(
                        trade_data,
                        config,
                        candidates,
                        WalkForwardSpec(
                            train_bars=252,
                            validation_bars=84,
                            test_bars=84,
                            step_bars=84,
                            expanding=True,
                            objective=walkforward_objective,
                            max_validation_drawdown=0.35,
                        ),
                    )
                    diagnostics = diagnose_walk_forward(
                        wf,
                        bootstrap_iterations=500,
                        mean_block_length=10.0,
                        seed=11,
                    )
                wf_metrics = pd.DataFrame([wf.oos_metrics], index=["walk_forward_oos"])
                st.dataframe(wf_metrics, use_container_width=True)
                st.dataframe(wf.folds, use_container_width=True, height=300)
                st.markdown("**Multiple-testing / Overfitting diagnostics**")
                d1, d2, d3, d4 = st.columns(4)
                dsr = diagnostics.deflated_sharpe
                reality = diagnostics.reality_check
                d1.metric("Deflated Sharpe 機率", f"{dsr.probability:.1%}")
                d2.metric("OOS Sharpe", f"{dsr.observed_sharpe_annualized:.2f}")
                d3.metric(
                    "Selection-adjusted Sharpe 門檻",
                    f"{dsr.expected_max_sharpe_annualized:.2f}",
                )
                d4.metric("Reality Check p-value", f"{reality.p_value:.3f}")
                st.caption(
                    f"DSR 使用 {dsr.num_trials} 個候選策略的 Validation Sharpe 分布修正 selection bias；"
                    f"Reality Check 對 {reality.candidate_count} 個候選、{reality.sample_size} 個 Validation 報酬"
                    f"做 {reality.bootstrap_iterations} 次 stationary bootstrap。"
                    "這些是研究診斷，不代表未來報酬保證。"
                )
                wf_fig = go.Figure()
                wf_fig.add_trace(
                    go.Scatter(x=wf.oos_equity.index, y=wf.oos_equity, name="OOS equity")
                )
                wf_fig.update_layout(
                    title="Walk-forward 純 OOS 淨值",
                    yaxis_title=f"NAV ({comparison.paper_replay.base_currency})",
                    height=380,
                )
                st.plotly_chart(wf_fig, use_container_width=True)

        tab1, tab2, tab3, tab4 = st.tabs(["成交紀錄", "成本與換手", "目標權重", "Alpha 訊號"])
        with tab1:
            st.dataframe(comparison.paper_replay.fills, use_container_width=True, height=420)
        with tab2:
            costs = comparison.paper_replay.cost_attribution
            if costs.empty:
                st.info("此區段沒有成交，因此沒有交易成本。")
            else:
                c1, c2, c3 = st.columns(3)
                currency = comparison.paper_replay.base_currency
                c1.metric(f"總手續費/稅費（{currency}）", f"{costs['fees'].sum():,.2f}")
                c2.metric(f"估計滑價成本（{currency}）", f"{costs['slippage_cost'].sum():,.2f}")
                c3.metric("累積單向換手", f"{costs['turnover_rate'].sum():.2f}x")
                st.dataframe(costs.tail(50), use_container_width=True, height=360)
        with tab3:
            st.dataframe(comparison.paper_replay.weights.tail(50), use_container_width=True, height=420)
        with tab4:
            st.dataframe(comparison.paper_replay.alphas.tail(50), use_container_width=True, height=420)

    except Exception as exc:  # noqa: BLE001 - UI boundary must surface provider/runtime errors.
        if twse_mode:
            st.error(f"TWSE 資料準備失敗：{exc}。請核對資料包及來源，已下載檔案可供重試。")
        elif odd_lot_study and "raw prices appear split-adjusted" in str(exc):
            st.error(
                "資料中的原始價格疑似已調整拆股，繼續計算會重複套用企業行動。"
                "請使用經確認的未調整價格與拆股資料，或先選合成資料測試流程。"
                f" 詳細資訊：{exc}"
            )
        else:
            st.exception(exc)
else:
    if odd_lot_study and "odd_lot_study_result" in st.session_state:
        render_odd_lot_study(*st.session_state["odd_lot_study_result"])
    else:
        st.info("設定標的後按「執行模型」。第一次可先選『離線合成資料』驗證整套引擎。")
