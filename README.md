# Quant Fund Lab

本機量化研究、回測、模擬下單與視覺化平台，支援美股與台股。**不串接券商 API、不送真實訂單。**

## 核心設計

交易決策流程固定為：

`市場資料 -> 數學 Alpha 模型 -> 風險/共變異數模型 -> 投資組合最佳化 -> 成交/成本模擬 -> 績效分析`

第一版 Alpha 不是 RSI/MACD 類規則，而是：

- Kalman state-space 趨勢估計
- Ornstein–Uhlenbeck 均值回歸
- 橫斷面市場殘差動能
- Shrinkage covariance + constrained mean/variance allocation

回測與 paper replay 共用同一個 execution engine，訊號只使用當下以前資料，並在下一根 bar 開盤成交，以降低 look-ahead bias。

## 快速啟動

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
streamlit run src/quant_fund_lab/ui.py
```

## 目前階段

MVP + M1 + M2 完成：除交易日曆、停牌/漲跌停、交易成本、point-in-time universe、terminal return、企業行動、可重現資料快照與 USD/TWD base-currency accounting 外，研究層已加入 leak-resistant walk-forward calibration、Deflated Sharpe Ratio、White Reality Check-style stationary bootstrap，以及 M2-3 regime detection、statistical factor neutralization 與 risk-contribution budgeting。Regime 只使用 trailing market returns 調整模型混合與 gross exposure；alpha 再對 market beta / idiosyncratic volatility 做可調強度的橫斷面部分殘差化，避免一次把有效 alpha 全部投影掉；optimizer 以 normalized risk contribution penalty 抑制風險集中。M3 persistent paper trading 也已完成：SQLite ledger 保存虛擬訂單、partial/pending 狀態、fills、positions、realized/unrealized PnL、NAV、benchmark 與 reconciliation；每日市場資料以 SHA-256 snapshot 留存，ledger 可關閉後重新開啟繼續處理未成交訂單。M4 production hardening 已完成：市場資料使用 provider chain，Yahoo 失效時可回退到經 SHA-256 驗證的本機 snapshot；研究執行採 versioned config schema + dataset ID + run context 產生 deterministic run ID；JSONL audit log 使用 SHA-256 hash chain 偵測竄改；報告匯出包含 metrics、equity、fills、weights、alpha、regime、成本、run manifest 與 HTML，並附 report manifest 驗證所有檔案完整性。目前 roadmap M0–M4 已具備完整可執行骨架。

M5-1 Factor Laboratory 已完成：價量資料可產生 momentum 252-21 / 63-5、short reversal、low volatility、low beta、base-currency liquidity、volume surprise 等 point-in-time cross-sectional factors；研究層可計算 Pearson IC、Spearman Rank IC、IC IR、positive-IC rate、1/5/20 日 decay、平均 factor correlation 與 rank turnover。另保留 external point-in-time factor panel 介面供後續 Value / Quality / Profitability 等財務因子接入；在正式財務資料 provider 完成前，不虛構歷史基本面。

M5-2 Learned Factor Alpha 已完成：每個 timestamp 的候選因子依固定順序做 cross-sectional residualization，降低共線性；因子權重只使用 signal date 前已完整實現的 Rank IC，並以 horizon 間隔抽取非重疊樣本、可靠度 shrinkage、t-like score 與 L1 normalization 形成 signed weights。Factor composite 可作為原 Kalman/OU/residual-momentum Alpha 的可調 overlay，預設關閉；回測結果會保存每次 rebalance 的 learned factor weights，研究報告也一併輸出。

M5-3 Portfolio Risk Controls 已完成：optimizer 產生相對權重後，可選擇套用 annualized-volatility target、historical Expected Shortfall/CVaR cap 與策略自身 drawdown de-risking。三者都只把 risky sleeve 等比例縮小到現金，不增加槓桿；risk-control diagnostics 會保存縮放前後的預估波動、CVaR、gross exposure、drawdown 與各縮放因子，verified report 同步輸出。

M5-4 Robustness Lab 已完成：固定 paper split 下可執行 1.0x / 1.5x / 2.0x execution-cost stress、circular block bootstrap 績效分布與 regime return attribution。成本壓力只放大 commission、slippage 與 market-impact 模型，不任意放大法定稅費；bootstrap 產生 total return / CAGR / volatility / Sharpe / MDD / Calmar 的 P05/median/P95；regime attribution 顯示各市場狀態的報酬、波動、Sharpe、hit rate 與 log-return contribution。這些診斷不參與策略選參，避免把 robustness test 反過來變成另一層 data snooping。Quant Fund Lab M5 定版為 v0.5.0。

M6-1 Point-in-Time Fundamentals（US）已完成核心資料層：統一 fundamental event schema 明確區分 `period_end` 與 `filed_at`，as-of/panel 查詢一律以申報日作資訊可得時間；SEC adapter 使用官方 ticker→CIK mapping 與 CompanyFacts XBRL API，支援 revenue、net income、operating income、assets、equity、cash、shares outstanding 等標準概念，並要求使用者以 `QFL_SEC_USER_AGENT` 宣告聯絡資訊。此階段先建立可靠 raw facts，不直接把不同 duration/instant context 混成財務因子。

M6-2 Point-in-Time Fundamentals（TW）已完成核心資料層：FinMind 財報列若沒有外部歷史 `available_at` 對照表會直接拒絕進入回測，避免把財報期末日誤當公開日；月營收僅把 `create_time` 當 observed-availability proxy，並預設排除 FinMind 2026-04-21 初始化回填批次。支援財務報表、資產負債表、現金流量表與月營收 raw provider，normalized facts 與 US SEC 共用 `FundamentalDataset` / `filed_at` 語意。

M6-3 Fundamental Factor Derivation 已完成：raw facts 依 signal date 僅使用已 `filed_at` 的資訊；flow metrics 要求明確 `period_start/end`，annual filing 取完整年度 context，interim 同期若同時存在 YTD/單季則偏好最短有效 duration，不猜未知 duration。可產生 ROE/ROA、operating/gross margin、cash-to-assets、保守型 asset-growth、台股月營收 YoY；若另外提供明確的 base-currency market-cap panel 與 fundamental FX，才啟用 book-to-market / earnings-yield / small-size，避免用 adjusted price × historical shares 製造拆股失真。這些 panels 可直接餵入 M5 Factor Lab。Quant Fund Lab 版本升為 v0.6.0。
