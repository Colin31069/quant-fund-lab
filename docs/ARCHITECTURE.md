# Quant Fund Lab — Architecture Plan

## 1. 目標與邊界

本專案只處理**虛擬資金**，不接券商 API、不送真實訂單。標的為美股與台股，第一階段使用日線資料，交易策略與成交模擬完全分離。

核心原則：

1. 訊號不是單一技術指標規則，而是由統計/狀態空間模型產生可比較的 alpha。
2. 模型只決定預期報酬；最終倉位由風險模型與組合最佳化決定。
3. 回測與 paper trading 必須共用同一 execution/cost engine。
4. 訊號在 t 日收盤後計算，最早只能於 t+1 開盤成交，防止 look-ahead。
5. 所有交易成本、稅、滑價、流動性上限都可設定，不能把零成本績效當真實績效。

## 2. 系統分層

### Data Layer

- `MarketData`：統一 Open / Close / Volume 寬表介面。
- Yahoo adapter：MVP 公開資料源；使用同一 adjusted price basis。
- 後續：Parquet/DuckDB cache、FinMind/TWSE/付費資料 provider、下市與企業行動資料品質層。

### Alpha Layer

- **Kalman local linear trend**：估計 latent level/trend，將 trend 對近期報酬波動標準化。
- **OU mean reversion**：對去趨勢殘差擬合 AR(1) / OU，估計回歸速度與偏離程度。
- **Cross-sectional residual momentum**：以全市場平均報酬作單因子，對各股票 beta 去市場化，再比較殘差動能。
- Ensemble：模型分數加權組合，後續可改成 walk-forward 權重學習。

## 3. Risk / Portfolio Layer

以 shrinkage covariance 降低小樣本共變異數噪音，解以下 constrained utility：

`max_w  alpha^T w - lambda * w^T Sigma w - gamma * ||w - w_prev||^2`

約束：

- long-only（MVP）
- `0 <= w_i <= max_weight`
- `sum(w) <= 1`，剩餘保留現金

後續加入 sector/country/FX exposure、CVaR、volatility targeting、Kelly fraction cap。

## 4. Execution Layer

成交模型：

- 訊號：t close
- 成交：t+1 open
- sells before buys
- commission / sell tax / SEC fee
- fixed slippage + sqrt(participation) market impact
- volume participation cap
- integer share/lot handling
- local-currency execution + base-currency cash/NAV accounting
- FX conversion factor 定義固定為 `local value × fx_to_base = base value`

這一層由 historical backtest 與 paper replay 共用。

## 5. Backtest / Paper Replay

### Historical backtest

前段資料做歷史回測。每次再平衡只看當日以前的資料。

### Paper replay

在時間切分點重置虛擬資金，保留 warm-up 歷史但不保留前段持倉，以未見的尾段資料逐日 replay。這是 live paper trading 上線前的 out-of-sample proxy。

### 核心指標

- Total return / CAGR
- Annualized volatility
- Sharpe
- Max drawdown
- Calmar
- Turnover / fees / slippage（下一階段 UI 顯示）
- 與 benchmark buy-and-hold 比較

## 6. UI

Streamlit local dashboard：

- 標的、基準、期間、資金、權重上限、再平衡頻率
- Historical backtest vs paper replay metrics
- normalized equity curve
- paper fills
- target weights
- alpha history

## 7. 里程碑

### M0 — 可運行核心（目前）

資料介面、三類 alpha、風險最佳化、execution、backtest、paper replay、基本 UI、單元測試。

### M1 — 回測可信度

**M1-1 已完成：** exchange-calendar mismatch report、週末資料硬拒絕、停牌/零成交量不成交、台股普通交易 1,000 股單位、10% locked-limit 保守代理、fee/slippage/turnover attribution。

注意：Yahoo 不提供 TWSE 正式開盤競價基準價，M1-1 的台股漲跌停判斷以前一調整後收盤價作 proxy；第三方交易日曆也可能落後臨時休市/新年度行事曆，因此 calendar mismatch 只作資料品質警告，不自動補造價格。

**M1-2 已完成：** point-in-time membership mask 讓每個 signal date 只能配置當時 eligible 的股票；terminal return event 明確將下市/清算持股轉為現金或損失，不再無限沿用最後價格；Yahoo adapter 保存 dividend / stock-split metadata 並驗證 corporate-action adjustment；市場資料可輸出 Parquet snapshot，所有檔案以 SHA-256 驗證並產生 deterministic dataset ID，確保研究資料可重現。

限制：Yahoo 的歷史可交易 universe 仍不是完整的交易所 constituent/delisting database；membership 目前由每個 ticker 的首末可觀測資料建立，真正 institutional-grade survivorship control 仍需要 point-in-time security master / delisted-security provider。terminal return 因此採 explicit input，不猜測未知下市報酬。

**M1-3 已完成：** USD/TWD FX conversion、base-currency accounting 與跨市場組合。Yahoo `USDTWD=X` 作為 canonical「1 USD = 幾 TWD」來源；系統只 forward-fill 已知匯率，不 backfill 未來匯率，並驗證最大 stale age。股票成交價、手續費、證交稅與滑價保留 local currency；現金、NAV、權重、turnover 與績效統一換成 base currency。Alpha 與 covariance 也改用 base-currency price history，因此跨市場研究會納入 FX 變動。混合市場使用各市場觀測日期的 union；休市標的因 Open 缺值/Volume=0 不成交。FX factors 與 age metadata 也納入 snapshot hash。

### M2 — Model research

**M2-1 已完成：Walk-forward calibration / OOS harness。** 每個 fold 明確切為 Train → Validation → Test；Train 僅提供歷史狀態與 warm-up，候選參數只能用 Validation 指標選擇，Test 完全未見。Test 以重置本金執行，並把每個 fold 的純 test returns 串接成單一 OOS equity。支援 expanding/rolling train window、deterministic candidate ID、Calmar/Sharpe/annual-return objective、validation drawdown constraint，UI 可查看 fold 邊界、入選參數與 OOS 指標。

**M2-2 已完成：Multiple-testing / data-snooping diagnostics。** Walk-forward 現在保留同步的 candidate Validation return matrix；Deflated Sharpe Ratio 以純 OOS winner returns 做觀測 Sharpe，並用所有候選 Validation Sharpe 的橫斷面分散度建立 selection-adjusted expected-max Sharpe 門檻，同時修正樣本長度、偏態與峰度。另實作 White Reality Check-style stationary bootstrap：先將每個候選 Validation return differential 去均值，再以相同 bootstrap index 同步重抽所有候選以保留橫斷面相依性，估計 best-model family-wise p-value。方法論依 Bailey / López de Prado 等人的 Deflated Sharpe Ratio 與 Halbert White (2000) Reality Check；目前 Reality Check 實作採 max-mean stationary-bootstrap diagnostic，明確標示為 White-style，而非聲稱重現所有原論文擴充版本。

重要邊界：Test returns 只用於最終 OOS DSR 的 winner performance，不參與 candidate selection；Reality Check 使用的是 Validation 搜尋集合，避免拿 Test 區間回頭挑策略。

**M2-3 已完成：Regime detection / factor neutralization / risk budgeting。** 每個 signal date 只用 trailing equal-weight market returns 計算 trend z-score 與 annualized volatility，分類為 trend / neutral / high-volatility / risk-off / stress，據此調整 Kalman、OU、residual-momentum 的 ensemble 權重與 portfolio gross-exposure cap。接著以 trailing returns 估計每檔 market beta 與 idiosyncratic volatility，對 alpha 做 eligible-universe 內的橫斷面 OLS residualization，再以 configurable strength 將 raw alpha 與 residual alpha 混合（預設 50%）；這可降低非預期 factor exposure，又避免 hard neutralization 把策略本身的有效 alpha 一併刪除。樣本不足時 fail-safe 保留原 alpha，不用未來資訊。最後 optimizer 在原 mean-variance/turnover objective 上加入 normalized variance risk-contribution 對 equal-risk target 的 penalty，並確保正常解與 fallback 都遵守 regime gross-exposure cap。UI 顯示當前 regime、trend z、market vol 與 gross cap。

### M3 — Persistent paper trading

**M3 已完成。** `PaperLedger` 使用 SQLite 持久化 cash、positions、orders、fills、terminal events、daily position marks、NAV 與 snapshots。Target-weight 訂單在 signal close 後建立，最早下一根 open 執行；NEW/PARTIAL 未成交數量會跨交易日保留重試，新 rebalance 會以 `CANCELLED_REPLACED` 明確取代舊 target。Historical backtest 與 persistent paper trader 共用 `execute_market_order`，因此 commission / tax / SEC fee / slippage / participation cap / TW lot / locked-limit 規則一致。每日 close 以 observed close + FX 標記持倉，分離 realized / unrealized PnL、累積 fees/slippage，並保存 benchmark equity 與 ledger-vs-position reconciliation error。每個交易日可輸出 SHA-256 market-data snapshot 並把 dataset ID/path 寫入 ledger；SQLite 關閉後可重新開啟，延續 pending orders。UI 可選擇建立 `artifacts/paper_trading.sqlite` 與 `artifacts/paper_snapshots/` 的可視化 replay。

### M4 — Production hardening

**M4 已完成。** `MarketDataProvider` chain 將外部 provider failure 隔離，預設可由 Yahoo 回退到完整性驗證通過的本機 snapshot；Snapshot fallback 明確回報 provider attempts，不把失敗靜默吞掉。`CONFIG_SCHEMA_VERSION` 與完整 dataclass config 以 canonical JSON 序列化，deterministic run ID 同時 hash dataset ID、package version 與 run context（例如 paper split），避免不同研究條件碰撞。`AuditLog` 為 append-only JSONL，每筆事件鏈接前一筆 SHA-256，任何內容、順序或前鏈竄改都會驗證失敗。`export_research_report` 匯出 equity/fills/weights/alpha/regime/cost CSV、metrics/run manifest JSON 與 HTML，`report_manifest.json` 再 hash 所有輸出並產生 report ID，可離線驗證研究產物完整性。UI 可選擇建立 verified report，並顯示實際 data provider / failover 狀態。


### M5 — Strategy Research & Portfolio Laboratory

**M5-1 已完成：Factor library / IC diagnostics。** `factors.py` 對 base-currency price/volume 做 point-in-time 滾動計算，提供 momentum 252-21、momentum 63-5、5 日 short reversal、60 日 low-volatility、126 日 low-beta、20 日 base-currency dollar-volume liquidity 與 5/20 volume-surprise；每個 timestamp 只在當時 eligible universe 做 winsorized cross-sectional z-score。Factor research 以未來 1/5/20 日 return 僅作評估 label，不回流到因子計算，輸出 Pearson IC、Spearman Rank IC、IC/Rank-IC IR、positive-IC rate、decay、平均 factor rank-correlation 與 percentile-rank turnover。External factors 必須與 MarketData 完全 point-in-time 對齊且不自動 forward-fill，作為未來 Value/Quality/Profitability/Investment/Size provider 的安全入口；目前沒有正式財務歷史 provider，因此不聲稱已有這些基本面因子。

**M5-2 已完成：Orthogonalized multi-factor Alpha / trailing IC learning。** Factor panel 先用 deterministic sequential cross-sectional residualization 將後續因子對已完成因子去共線；每筆 IC 額外保存 `realized_at`，因此 signal date 只允許使用 `realized_at <= signal_date` 的 label。Factor learner 對指定 horizon 從最新往回抽非重疊 IC observation，對 Rank IC 的 t-like evidence 做 sample-size shrinkage 與 clipping，再以 L1 norm 形成 signed factor weights；資料不足時回傳空權重，原策略完全不受影響。當 `factor_alpha_enabled=True`，factor composite 與 regime-adjusted Kalman/OU/residual-momentum Alpha 依 `factor_alpha_weight` 混合，之後仍會經既有 statistical factor neutralization、risk-budget optimizer 與 execution engine。`BacktestResult.factor_weights` 與 verified report 都保存每次實際學到的權重。完整/截斷資料在同一 signal date 的 factor weights 與 score 有 regression test 保證一致，防止 unrealized future labels 洩漏。

**M5-3 已完成：Volatility target / CVaR cap / drawdown de-risking。** 新的 post-optimizer risk-control layer 不改變 Alpha 排序，只對 optimizer 的 risky sleeve 做 `0..1` 等比例縮放。Volatility target 使用 shrinkage covariance 預估年化組合波動，超過 target 時按比例降曝險；CVaR 使用 trailing base-currency portfolio returns 的 historical Expected Shortfall，超過每日上限時利用風險對權重的線性尺度降到 cap；drawdown control 以策略自身 close-to-close NAV 的 running peak 計算 drawdown，在 soft/hard threshold 間線性降曝險，hard limit 後維持 configurable minimum exposure。最終 scale 取三者最小值，從不把曝險放大超過 optimizer 輸出。`BacktestResult.risk_controls` 記錄 gross before/after、vol/CVaR before/after、drawdown 與各 scale，report 匯出 `risk_controls.csv`。

**M5-4 已完成：Robustness Lab。** `run_paper_cost_stress` 在完全相同的 paper split、策略參數與市場資料下，只倍增可估計的 execution frictions（commission / slippage / impact），法定 sell tax / SEC fee 保持原值，避免不合理壓力假設；`block_bootstrap_performance` 以 circular block bootstrap 重抽 paper daily returns，保留短期序列相依並輸出每次模擬的 total return、annual return/volatility、Sharpe、MDD、Calmar，再以 P05/median/P95 摘要路徑不確定性；`regime_return_attribution` 將每日實現策略報酬配對到當時最新已知 rebalance regime，輸出 days、mean return、annualized vol、Sharpe、hit rate 與 log-return contribution。UI 可選擇執行 Robustness Lab；其結果明確只作診斷，不進入 candidate selection 或參數調整。M5 完成後 package version 升為 `0.5.0`。


### M6 — Point-in-Time Fundamental Data

**M6-1 已完成：US SEC CompanyFacts event layer。** `FundamentalDataset` 使用長表保存 symbol/metric/value/unit/period_start/period_end/`filed_at`/form/accession/fiscal metadata/source；所有 `asof()` 與 `metric_panel()` 都以 `filed_at <= signal_date` 查詢，絕不以財報期末日提前曝光資訊，並保留 amendment 後續覆寫語意。`SecCompanyFactsProvider` 使用 SEC 官方 `company_tickers.json` 解 ticker→CIK，再讀 `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`；adapter 只接受 10-K/10-Q/20-F/40-F 及 amendment，對常見 US-GAAP concepts 建立 normalized metric 名稱。Provider 強制 `QFL_SEC_USER_AGENT` 含聯絡資訊並以至少 0.12 秒 request interval 控制速率。Raw facts 可 Parquet round-trip；財務因子 derivation 留到 M6-3，避免先混淆 quarterly/annual duration 與 instant balance-sheet contexts。

**M6-2 已完成：Taiwan FinMind event layer。** 台股 statement normalization 不接受 `period_end` 直接當資訊可得時間；`TaiwanStockFinancialStatements` / balance-sheet / cash-flow rows 必須由外部歷史 availability table 提供 `stock_id + period_end -> available_at`，缺任何一筆即 fail closed。月營收的 `create_time` 僅作 observed-availability proxy，source 明確標記 `create_time_proxy`，且預設排除 FinMind 2026-04-21 初始化回填批次，除非呼叫端明確允許作非回測用途。`FinMindFundamentalProvider` 支援環境變數 `FINMIND_TOKEN` 與四類 raw dataset；TW/US 最終共用相同 `FundamentalDataset` point-in-time 查詢介面。

**M6-3 已完成：Point-in-time fundamental factor derivation。** `fundamental_factors.py` 不以「最新 filed row」直接代表最新經濟期間，而是先依 `filed_at <= signal_date` 篩選，再以最新 `period_end` 解決 amendment 與較舊期間晚補件的衝突。Flow context 必須有 `period_start/end` 且 duration 在 45–400 日；FY/10-K/20-F/40-F 選最長 annual context，interim 同期若同時有 YTD/單季則選最短有效 context，再 annualize，未知 duration 一律回傳 NaN。衍生因子包含 profitability ROE/ROA、operating/gross margin、cash/assets、負向 asset growth（偏好保守投資）、monthly revenue YoY。估值類 book-to-market / earnings-yield 僅在 caller 明確提供 base-currency market-cap panel 與 fundamental FX 時產生，small-size 直接由該 market cap 計算；因此不會把 adjusted historical price 與 contemporaneous shares 強乘成錯誤市值。TW schema 若 provider type 未被內建辨識，normalizer 支援 caller-supplied explicit metric map，不猜語意。所有輸出 panel 與 M5 `external_factors` 介面完全對齊。M6 完成後 package version 為 `0.6.0`。

### M7 — Dual Price Basis / Corporate-Action Accounting

**M7-1 已完成：Raw-price storage / market-cap foundation。** `MarketData` 新增與 adjusted research basis 平行的 `raw_open/raw_close`；legacy/synthetic data 若沒有 raw basis 會顯式 fallback 為原本 open/close，維持相容。Yahoo adapter 維持 adjusted `open/close` 給既有模型與回測，同時保存交易所實際 raw price。Snapshot schema v3 保存 raw basis，loader 仍接受 v2 並 fallback。`estimate_market_cap_from_fundamentals` 使用 filing-time `shares_outstanding` panel 與 raw close；在新 share filing 尚未到來期間，`split_adjusted_reported_shares` 會按已觀測 stock-split event 機械調整 carry-forward 股數，新 filing 出現時重置，避免普通拆股造成 raw-price market cap 突然腰斬/倍增。FX 若已附著，另輸出 base-currency market cap。M7-1 尚未切換 execution 到 raw basis；必須先完成 M7-2 split/dividend position accounting。
