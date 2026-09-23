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

**M7-2 已完成：Raw execution corporate-action accounting。** `BacktestConfig.execution_price_basis` 預設 `adjusted`，確保既有 adjusted total-return research/backtest 行為不變；選 `raw` 時，模型與 covariance 仍使用 adjusted `data.close`，但 portfolio signal valuation、open execution、close NAV mark 與 terminal reference 改用 `raw_open/raw_close`。在每個 execution date 開盤前先套用 split event 到實際持股，再處理 cash dividend；split fractional share 以 ex-date raw open 作 cash-in-lieu approximation，事件中明確保存原/新股數、ratio、local/base cash 與 FX。Adjusted 模式完全不執行這些事件，避免 adjusted price 與 cash/share action 雙重計算。Verified report 新增 `corporate_actions.csv`。M7-2 當時 dividend 僅處理 gross cash，跨市場 withholding-tax model 之後由 M9 補上；persistent paper ledger 的 raw-mode corporate action 則於 M7-3 完成同步。

**M7-3 已完成：Persistent paper raw-basis synchronization。** `PaperLedger` metadata 會持久保存 execution price basis，同一 ledger 重新開啟時不得從 adjusted 切成 raw 或反向切換。Raw replay 每日依序處理 split/dividend → terminal event → pending/new orders → raw close mark；split 更新 SQLite position quantity，avg-cost/share 依 ratio 反向調整，fractional cash-in-lieu 的分配成本與 realized PnL 明確入帳，cash dividend 也進 realized PnL。跨 split 尚未成交的 NEW/PARTIAL order 會將 requested/remaining share units 依 ratio 重整，避免舊股數單位穿越 corporate action。新增 persistent `corporate_actions` table，UI 可選擇 adjusted/raw 並檢視事件。M7 完成後 package version 升為 `0.7.0`。

### M8 — Survivorship-Control Data Foundation

**M8-1 已完成：Point-in-time security master。** `SecurityMaster` 使用 stable `security_id` 對應 symbol / exchange / currency、`tradable_from`、`tradable_until`、`terminal_event_at` 與 explicit `terminal_return`。Membership 只依歷史交易有效期間生成，因此未來會下市的股票在最後交易日前仍保持 eligible，不因完整歷史資料而提前排除；terminal return 僅在事件日或之後第一個資料日期注入。Terminal event 必須同時具備最後交易日與明確 terminal return，缺少 requested symbol 時預設 fail closed。Security-master snapshot 使用 Parquet + SHA-256 manifest 與 deterministic dataset ID，loader 會驗證 hash、schema、row count 與 symbols，避免研究資料被靜默改寫。`apply_to_market_data()` 可直接用正式 security master 取代 Yahoo observation-based membership/terminal-return proxy。此階段是 provider-neutral foundation；若沒有可信的歷史 listing/delisting provider，系統不會宣稱已消除所有 survivorship bias。M8-1 完成後 package version 升為 `0.8.0`。

**M8-2 已完成：Historical security lifecycle ingestion。** `SecurityMasterEventDataset` 把身份生命週期拆成 `LISTED` / `TICKER_CHANGED` / `EXCHANGE_CHANGED` / `CURRENCY_CHANGED` / `DELISTED` 事件；stable `security_id` 是必填欄位，不允許用可能重複使用的 ticker 當永久身份替代品。每個 security 必須恰有一個 LISTED、最多一個 DELISTED，且 DELISTED 必須是最後 lifecycle event、攜帶 `last_tradable_at` 與 explicit `terminal_return`。`materialize(as_of=...)` 只套用 cutoff 當下已生效事件，可產生 M8-1 SecurityMaster；`identity_history()` 以 `[effective_from, effective_until_exclusive)` 表示 ticker/exchange/currency 歷史，不猜前一交易日。`SecurityEventCSVProvider` 使用 caller-specified column mapping ingest 外部歷史 export；US/TW normalizer 只做明確市場格式正規化（USD/TWD 與 TWSE/TPEX ticker suffix），不猜 missing delisting date、terminal return 或 stable ID。此層讓未來可接授權交易所/資料商歷史檔，同時避免把 current-symbol directory 誤當完整歷史 universe。M8-2 後 package version 為 `0.8.1`。

**M8-3 已完成：Stable-identity market-data stitching。** `identity_market_data.py` 將 lifecycle identity intervals 套到既有 `MarketData`：ticker change 前後的 open/close/raw price/volume/dividend/split/FX 只從當時有效 alias 取值，再輸出含 stable `security_id` 的 internal asset key。這使相同 ticker 在不同年代被兩個 security 重複使用時仍會產生兩條不同資產序列，而不是被 DataFrame column 名稱誤合併。為防止 provider 已 forward-fill 的舊公司 close 洩漏到新 listing，新的 interval 會先尋找第一個 open 或正 volume observation，之前的 close 保持 NaN。Reference 由 stitched close 重新 shift，因此純 ticker change 可跨 alias 保留前一日估值；membership / terminal return 則完全由 lifecycle event 重建。Internal key 對台股保留 `.TW`/`.TWO` 尾碼，讓既有 execution/FX market inference 仍能運作。Exchange/currency transition 目前明確拒絕，因現有 `MarketData` 還沒有 per-date asset market/currency metadata；這是下一階段要解的邊界。M8-3 後 package version 為 `0.8.2`。

**M8-4 已完成：Point-in-time asset market/currency metadata foundation。** `MarketData` 增加 optional `market_codes` 與 `currency_codes` panel，兩者必須與 close 的 index/columns 完全對齊；非空 market 僅允許 `US/TW`、currency 僅允許 `USD/TWD`，並正規化為大寫。Yahoo adapter 與 synthetic fixture 會建立固定 metadata；M8-3 stable-identity output 也會附上對應 panel。`slice()`、snapshot provider subset、historical/paper split 與 UI trade-symbol subset 都傳遞 metadata，避免研究切片時身份資訊消失。Market snapshot schema 從 v3 升為 v4，新增 `market_codes.parquet` / `currency_codes.parquet` 並維持 v2/v3 loader 相容性。此階段刻意不修改 execution/FX 的決策路徑：成本、交易日曆與換匯仍沿用既有 symbol inference；因此 exchange/currency lifecycle transition 仍由 M8-3 fail closed，直到下一階段完成 per-date execution integration。M8-4 後 package version 為 `0.8.3`。

**M8-5 已完成：Point-in-time historical execution / FX integration。** Shared execution functions 新增 optional daily `market_code` / `currency_code` override，legacy caller 未提供時才退回 ticker suffix inference。`desired_quantities`、`execute_market_order` 與 `rebalance_at_open` 因此可依 execution-date market metadata 選 US/TW cost model、lot size 與 TW locked-limit guard；Fill、terminal return 與 raw corporate-action event 的 local currency 同樣由當日 currency metadata 決定。`attach_fx_rates` 不再假設每個 column 永遠同幣別，而是對 `currency_codes` panel 逐 cell 建立 local→base factor；同一 stable asset 的 USD→TWD transition 可在同一 history 內正確換匯，且 active membership / terminal-event cell 若缺 currency metadata 直接拒絕。`identity_market_data` 現允許 exchange/currency lifecycle transition；每個 identity interval 寫入自己的 market/currency code，terminal date 也補上最後有效身份。若 currency 曾變更，來源已附著的 FX panel 不再被直接拼接，caller 必須依 stitched metadata 重新 attach FX，避免 stale currency semantics。Cross-market history 因使用 union dates，global single-market calendar validation 會略過；個別市場 session-quality refinement 留待後續。Persistent `PaperLedger` direct APIs 仍沿用 fallback，將於 M8-6 同步。M8-5 後 package version 為 `0.8.4`。

**M8-6 已完成：Persistent paper metadata synchronization / transition-safe reference。** `PaperLedger.submit_target_orders()` 會以 signal-date market metadata 做 lot-rounded target sizing；`process_open()` 則以 execution-date metadata 選 cost model、price-limit rule 與 Fill local currency，因此跨 identity transition 的 pending order 不會沿用建立訂單時的市場規則。`process_corporate_actions()` / `process_terminal_returns()` 同步接收當日 currency metadata。`replay_targets_persistently()` 在建立 ledger 前檢查 active/terminal metadata 完整性；若 observed currency 與 base currency 不同但沒有 attached FX 直接拒絕，已有 FX 時也要求 `data.base_currency` 相符並通過 stale/missing validation。新增 `transition_safe_reference()`：local reference price 只有在前後兩日 market 與 currency 都相同時才有效；identity transition 當天 reference 會變 NaN，避免 previous local close 被拿來做跨幣別 open fallback 或 TW locked-limit 比較。Historical backtest 與 persistent replay 都使用此 guard。Focused test 以 100 USD → 3,200 TWD 的 US→TW transition 驗證：transition-day TW 買單必須使用實際 open 成交、Fill 標示 TWD 且 quantity 遵守 1,000 股 lot。M8-6 後 package version 為 `0.8.5`。

**M8-7 已完成：Cross-market point-in-time session validation。** `validate_point_in_time_market_sessions()` 以 `membership & market_codes` 建立每個市場的 active mask，再以 non-null open 或正 volume 判定真正 observed local session；close 因估值需求可能 forward-fill，但不被拿來證明市場當日有開盤。每個 market 的 expected sessions 仍由 exchange-calendars（US=XNYS、TW=XTAI）產生，回報 missing 與 off-calendar 日期；`require_point_in_time_market_sessions()` 對真實 weekend bar 保持 hard reject。這解決 mixed-market union calendar 的核心歧義：例如 XTAI 開市而 XNYS 休市的日期，只要 US 欄位沒有實際 open/volume，就不會被誤列成 US off-calendar；若真的出現 US bar 則會被抓出。`BacktestResult.session_validations` 保存 per-market report；單一市場時 `session_validation` 仍指向同一份 report，維持 UI/既有 caller 相容。Streamlit UI 改為逐市場顯示日曆差異。M8-7 後 package version 為 `0.8.6`。

**M8-8 已完成：Lifecycle snapshot integrity / research provenance。** `save_security_lifecycle_dataset()` 將 normalized lifecycle event table 寫成 compressed Parquet，manifest 保存 schema version、row count、stable `security_ids`、file SHA-256 與 deterministic dataset ID；`load_security_lifecycle_dataset()` 依序驗證 schema → file hash → dataset ID → round-trip row/identity content，避免 listing/delisting/ticker-change 歷史被靜默替換。`RunManifest` 新增 `data_provenance`，且 `deterministic_run_id()` 把它納入 hash；因此 market snapshot 相同但 lifecycle dataset 不同的研究會得到不同 run ID。`export_research_report()` 同步輸出 `data_provenance.json` 與 `session_validations.json`，並把兩者摘要加入 HTML/report hash manifest；UI 目前至少記錄 market-data dataset ID，caller 若使用 M8 lifecycle snapshot 可傳入 `security_lifecycle_dataset_id`，確保完整來源鏈。M8-8 後 package version 為 `0.8.7`。

**M8-9 已完成：Verified research-input composition。** `research_inputs.py` 提供單一 `load_verified_identity_research_inputs()` API：先用 market snapshot loader 驗證所有 file hashes / dataset ID，再核對 manifest symbols/start/end 與實際 loaded data；同時載入並驗證 lifecycle snapshot，接著依 requested stable `security_id` 執行 M8-3 identity stitching。Caller 可指定 base currency；若 stitched data 沒有可重用的 matching FX，就使用 M8-5 `attach_fx_rates()` 重新建立 point-in-time conversion，跨幣別但缺 USD/TWD source 直接失敗。回傳的 `VerifiedResearchInputs` 同時包含 stitched `MarketData`、asset identity table、market/lifecycle manifests 與可直接餵給 run/report provenance 的兩個 dataset IDs。這把 M8 的資料可信度元件收斂成可重複的 batch-research entry point。M8-9 後 package version 為 `0.8.8`。

**M8-10 已完成：Package / run-version integrity。** 先前 `pyproject.toml` milestone version 已前進，但 `quant_fund_lab.__version__` 仍固定為 `0.7.0`；由於 provenance 直接 import `__version__`，這會讓新程式產生的 RunManifest / deterministic run ID 誤帶舊 package version。現在改成單一 canonical runtime version，`[project]` 使用 dynamic version，`[tool.setuptools.dynamic]` 直接引用 `quant_fund_lab.__version__`；每次升版只需更新單一來源。Regression test 明確要求 RunManifest package version 與 runtime version 相同，並以 PEP 517 isolated wheel build 驗證 distribution metadata 可解析該 dynamic version。M8-10 後 package version 為 `0.8.9`。

**M8-11 已完成：Streamlit verified lifecycle research mode。** UI 新增第三種 data mode，不再把 stable `security_id` 當 ticker：交易 universe 與 benchmark 先由 `ui_inputs.py` 呼叫 M8-9 verified bundle，依 asset identity table 映射為 internal asset keys，再切 requested date range 並建立只含 trade assets 的 `MarketData`。因此 downstream historical/paper replay、factor lab、robustness、walk-forward 與 persistent paper ledger 不需另寫一套 execution path。Report export 若來自 verified mode，`data_provenance` 保留 source `market_data_dataset_id` + `security_lifecycle_dataset_id`，並增加 `derived_trade_dataset_id` 對應實際報告輸入 snapshot；普通 Yahoo/synthetic mode 維持原 provenance 行為。Verified UI 刻意不偷偷下載 FX：若 stitched cross-currency history 沒有 matching FX，仍由 M8-9 fail closed，避免『verified』模式混入未標記的外部即時資料。M8-11 後 package version 為 `0.8.10`。

### M9 — Tax-Aware Cashflow Accounting

**M9-1 已完成：Dividend withholding accounting。** `DividendWithholdingConfig` 提供 US/TW market-level rate，強制限制於 0–1，預設 0 以維持既有結果；此參數代表研究者的稅務假設，不宣稱是任何使用者的實際適用稅率。Raw execution 的 `apply_cash_dividend_events()` 依 point-in-time `market_codes`（缺少 metadata 時才沿用 symbol fallback）計算 gross dividend → withholding → net cash，再以當日 FX 換成 base currency。`CorporateActionEvent.cash_value*` 明確代表 net credited cash，另保存 `gross_cash_value*` 與 `withholding_tax*` 供 report/ledger 稽核；stock split cash-in-lieu 的 gross=net、withholding=0。Persistent SQLite corporate-actions schema 新增 local currency、gross 與 withholding 欄位，舊 ledger 會以 guarded ALTER TABLE migration 補欄並把舊 cash 回填為 gross，保持 backward compatibility。Historical backtest、persistent replay 與 Streamlit config 已同步接入；adjusted execution 完全不套用此 cashflow 層。M9-1 後 package version 為 `0.9.0`。

**M9-2 已完成：Persistent tax-assumption integrity。** `CorporateActionEvent` 與 SQLite `corporate_actions` 增加 explicit `withholding_rate`；schema migration 會在缺欄時以 `withholding_tax_local / gross_cash_value_local` 回填既有 M9-1 event。`PaperLedger.ensure_dividend_withholding()` 把 `{US, TW}` rates 寫入 metadata，raw replay 啟動時必須一致；`process_corporate_actions()` 直接 API 也先執行同一 guard。若 M9-1 ledger 尚未有 metadata，會從既有 cash-dividend rows 依 USD→US、TWD→TW 的現行兩市場資料契約推回歷史 rate，再與新設定比對後才補鎖；若是更舊、`local_currency` 不可辨識的 legacy dividend history，只有全 0% assumption 可安全沿用，任何非 0% 切換直接 fail closed。這避免 persistent NAV/PnL 在不同研究批次間混入不一致的稅務現金流假設。M9-2 後 package version 為 `0.9.1`。

**M9-3 已完成：Dividend tax-drag analytics / reporting。** `tax_analytics.py` 將任意 historical / persistent corporate-action table 正規化為一組可稽核稅務現金流指標：dividend event count、base-currency gross dividend、withholding tax、net dividend 與 weighted effective withholding rate；另以 `local_currency` groupby 輸出 currency breakdown。非空 dividend rows 必須具備 action/net/gross/tax/currency 欄位，且每筆 base-currency cashflow 都必須滿足 `gross ≈ withholding + net`，否則分析層直接拒絕。Verified report 新增 `dividend_tax_summary.json`、`dividend_tax_by_currency.csv` 與 HTML tax-drag section，兩個新 artifact 都加入 SHA-256 report manifest，因此 report schema 升為 3。Streamlit paper replay 與 persistent ledger 都重用相同 helper 顯示稅務拖累，不另外重寫計算公式。M9-3 後 package version 為 `0.9.2`。

**M9-4 已完成：Dividend withholding sensitivity。** `run_dividend_tax_sensitivity()` 只在 `execution_price_basis='raw'` 時執行，避免 adjusted total-return price 在沒有獨立股息現金流的情況下產生偽稅務結果。預設 shift set 為 `(-10pp, 0, +10pp)`，對 US/TW configured rate 分別 clamp 到 `[0, 1]`；零 shift 若已提供 baseline paper result 則直接重用，其他 scenario 重新跑固定 train/paper split。輸出同時保存 rate assumptions、完整 performance metrics 與 M9-3 dividend cashflow summary，因此可觀察 tax assumption 對 return/risk 的邊際影響。`RobustnessResult` 新增 `dividend_tax_sensitivity`，Streamlit M5-4 Robustness Lab 增加專屬 tab；和既有 cost/bootstrap/regime diagnostics 一樣只作 robustness evidence，不回饋策略選參。M9-4 後 package version 為 `0.9.3`。
