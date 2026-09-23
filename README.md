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

M7-1 Dual Price Basis / Market-Cap Foundation 已完成：`MarketData` 同時保存 adjusted `open/close` 與 raw `raw_open/raw_close`，現有回測先維持 adjusted basis 以確保行為相容；Yahoo adapter 以同一 corporate-action factor 產生 adjusted Open，同時保留真實 raw OHLC basis。Snapshot schema 升為 v3 並可讀舊 v2。`market_cap.py` 用 point-in-time `shares_outstanding` × raw close 建立市值，持續沿用的舊股數會套用之後發生的 split ratio，新 filing 則重置有效股數；base market cap 再使用既有 FX layer 換算。

M7-2 Corporate-Action Position Accounting 已完成：`BacktestConfig.execution_price_basis` 可明確選擇 `adjusted` 或 `raw`。Adjusted 模式維持原 total-return basis，不額外入帳股息/拆股；raw 模式的 portfolio valuation、下單與 terminal reference 改用 raw basis，split 會在 ex-date 交易前先調整持股數量，reverse/non-integer split 的 fractional share 以 ex-date raw open 估算 cash-in-lieu，cash dividend 則按持股數以 gross cash 入帳。所有事件保存於 `BacktestResult.corporate_actions` 並輸出 report；在 M7-2 當時股息仍以 gross cash 入帳，後續已由 M9 補上可配置 withholding accounting。

M7-3 Persistent Raw Paper Ledger 已完成：SQLite ledger 會鎖定 adjusted/raw price basis；raw 模式每日在 open order 前處理 split/dividend，split 會同步重算持股 quantity 與 avg-cost/share，fractional cash-in-lieu 分配成本並計入 realized PnL，dividend 也計入 realized PnL；尚未成交的 NEW/PARTIAL order 會按 split ratio 重整 share units。UI 現已可直接選 raw/adjusted 並查看 persistent corporate-action ledger。M7 定版為 v0.7.0。

M8-1 Point-in-Time Security Master 已完成核心資料層：每個 symbol 對應穩定 `security_id`、exchange/currency、首末可交易日與明確 terminal event/return；membership 在最後交易日前保持可投資，不因已知未來下市而提前剔除，terminal return 只在事件日或其後第一個市場日期出現。缺少 requested symbol 時預設 fail closed，避免靜默退回 observation-based universe。Security master 可輸出 Parquet + SHA-256 manifest/dataset ID 並驗證竄改，亦可直接覆寫 `MarketData.membership` / `terminal_returns`。此階段先建立 provider-neutral 的 survivorship-control foundation；尚未聲稱已具備完整 CRSP/交易所歷史下市資料庫。Quant Fund Lab 版本升為 v0.8.0。

M8-2 Historical Security Lifecycle Ingestion 已完成：新增 provider-neutral lifecycle event layer，明確保存 `LISTED`、`TICKER_CHANGED`、`EXCHANGE_CHANGED`、`CURRENCY_CHANGED`、`DELISTED`，並要求 caller/provider 提供 stable `security_id`；系統不由 ticker 猜身份。Delisting 必須提供最後可交易日與 explicit terminal return，禁止從價格消失自行猜損益。US/TW CSV export 可用 explicit column mapping 正規化，US 預設 USD、台股依 TWSE/TPEX 對應 `.TW`/`.TWO`，多市場事件可合併。事件集可依 `as_of` deterministic materialize 成 M8-1 SecurityMaster，並保留 identity-history 的 exclusive effective interval，讓 ticker/exchange 變更不污染較早歷史。這仍是 ingestion foundation，不代表內建完整交易所歷史資料授權。版本升為 v0.8.1。

M8-3 Stable-Identity Market Data Stitching 已完成：`stitch_market_data_by_identity` 依 lifecycle interval 將舊/新 ticker 的價量、raw price、股息、拆股與 FX 欄位拼到同一 stable asset，並使用含 `security_id` 的內部 asset key 避免 ticker reuse 把不同公司合併。每個 alias 只在自己的 effective interval 取資料，且從該 interval 第一個真實 open/volume observation 後才允許 close 延續，避免前一家公司 ffill 價格洩漏到新公司。Membership 與 terminal return 直接由 lifecycle 建立，ticker change 邊界可保留前一日 reference continuity。現階段若 lifecycle 發生 exchange 或 currency transition 會 fail closed，待後續加入 per-date market/FX metadata 後再開放。版本升為 v0.8.2。

M8-4 Point-in-Time Asset Metadata Foundation 已完成：`MarketData` 新增與價格矩陣完全對齊的 `market_codes` / `currency_codes`，允許每個資產、每個日期保存 `US/TW` 與 `USD/TWD` 身份資訊，並對未知代碼 fail closed。Yahoo 與 synthetic provider 會建立 metadata；slice、snapshot provider subset、historical/paper split、UI symbol subset 與 stable-identity stitching 都會保留。Market-data snapshot schema 升為 v4 並保存兩個 metadata panel，loader 仍相容 v2/v3。此階段只建立資料契約；execution / FX 尚未改用時間變動 metadata，因此 exchange/currency transition 仍不會被 M8-3 stitching 放行。版本升為 v0.8.3。

M8-5 Point-in-Time Historical Execution / FX Integration 已完成：historical backtest 與共享 execution primitives 現在優先使用 execution date 的 `market_codes` / `currency_codes`，因此 stable internal asset key 即使沒有 `.TW`/`.TWO` 尾碼，也能套用正確的台股 1,000 股 lot、交易成本、locked-limit proxy，以及 Fill / terminal event / corporate-action 的 local currency。`attach_fx_rates` 改為逐日期讀取 currency panel，同一 stable asset 可由 USD 切換成 TWD（或反向）並重新套用只使用當下以前匯率的 USD/TWD conversion；active / terminal cell 缺 metadata 會 fail closed。M8-3 stitching 現可保留 exchange/currency transition，若 currency 發生變更則會丟棄來源舊 FX panel，要求重新依 lifecycle metadata attach FX，避免沿用錯誤匯率。未提供 metadata 的 legacy data 仍維持 ticker suffix fallback。Persistent `PaperLedger` 的直接 order-processing API 尚未切換到每日 metadata，留待下一階段。版本升為 v0.8.4。

M8-6 Persistent Paper Metadata Synchronization 已完成：SQLite `PaperLedger` 的 target sizing、pending-order open execution、raw corporate action 與 terminal return 都可接收當日 `market_codes` / `currency_codes`，`replay_targets_persistently` 會逐日傳入 metadata，並在啟動前驗證 active/terminal cell 的身份資料與 cross-currency FX 完整性。Internal stable asset 因此在 paper replay 也能使用正確的 US/TW lot、成本、漲跌停與 local currency。另新增 transition-safe local reference：若 execution date 的 market 或 currency 與前一日不同，前一日 local close 不再作當日 reference/fallback，避免把例如 100 USD 與 3,200 TWD 直接比較；transition 日只有真實當日 open 才能成交。Historical backtest 與 persistent paper 共用相同 guard。Legacy caller 未提供 metadata 時仍保留原 ticker fallback。版本升為 v0.8.5。

M8-7 Cross-Market Point-in-Time Session Validation 已完成：交易日曆驗證不再把 mixed US/TW 的 union index 當成每個市場都實際交易，而是依 `market_codes + membership` 分市場，只把該市場資產當日真的有 non-null open 或正 volume 的日期視為 observed session。如此台股開市、US 休市時，US 的 forward-filled close 不會製造假 session；但若 US 資產在 XNYS 非交易日真的出現 open/volume，仍會被列為 `off_calendar_sessions`，週末真實 bar 仍 hard reject。`BacktestResult` 新增 `session_validations` 保存每個市場報告，單一市場仍保留原 `session_validation` 相容介面；UI 會逐市場顯示 missing/off-calendar 差異。版本升為 v0.8.6。

M8-8 Lifecycle Snapshot / Research Provenance 已完成：historical security lifecycle events 可輸出 `security_lifecycle.parquet` + SHA-256 manifest，使用 schema version、row count、stable security IDs 與檔案 hash 產生 deterministic lifecycle dataset ID；loader 會驗證 schema、file hash、dataset ID、row count 與 identities，任何竄改都 fail closed。研究 provenance 同步新增 `data_provenance`，deterministic run ID 會納入 lifecycle / market-data dataset IDs，因此同一策略與市場價格、但 security lifecycle 不同時不會共用 run ID。Verified report 會輸出 `data_provenance.json` 與 per-market `session_validations.json`，HTML 亦顯示來源識別與 session quality；UI 匯出流程同步傳遞 market-data provenance。版本升為 v0.8.7。

M8-9 Verified Research Input Bundle 已完成：新增 `load_verified_identity_research_inputs()`，把已驗證 market snapshot 與 lifecycle snapshot 組成單一研究入口。流程固定為完整性驗證 → stable security-id stitching → optional base-currency FX attach → 回傳 `MarketData`、asset identity map、兩份 manifest 與 `data_provenance`。因此 batch research / 回測 caller 不需要再手動串 M8-3～M8-8，也不會漏掉 lifecycle dataset ID。跨幣別 identity 若要求 base currency 卻沒有 USD/TWD source 會 fail closed；若兩份 snapshot 的 symbols/date manifest 與實際資料不一致亦拒絕載入。版本升為 v0.8.8。

M8-10 Package / Run Version Integrity 已完成：修正 package runtime `__version__` 長期停留在 v0.7.0、但 `pyproject.toml` 已升版造成的 provenance 分岔。現在 `quant_fund_lab.__version__` 是唯一版本來源，setuptools 透過 dynamic version 直接讀取該值；`RunManifest.package_version` 與 deterministic run ID 因此與實際建置套件版本一致。新增 regression 驗證 runtime/run-manifest 版本同步，並用本機 wheel build 驗證 distribution metadata。版本升為 v0.8.9。

M8-11 UI Verified Lifecycle Research Mode 已完成：Streamlit 的資料來源新增 `M8 Verified Lifecycle Snapshot`，使用者直接輸入 market snapshot 目錄、lifecycle snapshot 目錄、交易 stable security IDs 與 benchmark security ID。UI 透過 M8-9 bundle 完成 hash/dataset-ID 驗證、identity stitching、日期切片與 base-currency FX 檢查，再把 security IDs 映射成 internal asset keys 送入既有 backtest / paper / robustness / walk-forward 流程。Verified report provenance 會保留原始 market/lifecycle dataset IDs，並另外記錄 derived trade snapshot ID；畫面同步顯示來源 ID 摘要。跨幣別 lifecycle 若 snapshot 無法提供可安全重用的 FX 仍 fail closed，不會默默改用即時外部匯率。版本升為 v0.8.10。

M9-1 Dividend Withholding Tax Accounting 已完成：raw-price corporate-action 模式新增可配置的 US/TW 股息預扣率，預設皆為 0%，不替使用者硬編任何稅務身分或法定稅率。每筆 cash dividend 會同時保存 gross cash、withholding tax 與實際入帳 net cash（local/base currency 各一組）；historical backtest 與 persistent paper ledger 共用同一計算邏輯，realized PnL 只計入 net cash。舊 SQLite paper ledger 開啟時會自動補齊 audit 欄位，既有事件按 gross=原 cash、withholding=0 的 legacy 語意遷移。Streamlit 可直接設定 US/TW 預扣率；adjusted-price 模式仍不額外入帳股息，避免 double count。版本升為 v0.9.0。

M9-2 Tax-Assumption Ledger Integrity 已完成：raw persistent paper ledger 現在會把 US/TW dividend withholding assumptions 寫入 metadata 並鎖定；同一 ledger 重新開啟時若稅率不同會直接拒絕，避免把不同稅務假設混在同一條 NAV/PnL 歷史。每筆 corporate-action event 新增 explicit `withholding_rate`。對 M9-1 已存在但尚未保存 tax metadata 的 ledger，系統會依既有 dividend rows 的 local currency、gross cash 與 withholding tax 反推出歷史稅率，只有與新設定一致才補鎖；更舊且市場不可辨識的 legacy dividend 若要切到非 0% 假設則 fail closed。直接呼叫 `PaperLedger.process_corporate_actions()` 也會執行同一檢查，不只 replay helper 受保護。版本升為 v0.9.1。

M9-3 Dividend Tax Drag Analytics 已完成：新增可重用的 tax analytics layer，對 historical backtest 或 persistent ledger 的 `corporate_actions` 統一計算 dividend event count、gross dividend cash、withholding tax、net dividend cash 與 effective withholding rate，並可依 local currency 拆解。分析前會驗證 `gross = withholding + net`，若 cashflow 不平衡直接 fail closed。Verified report 新增 `dividend_tax_summary.json` 與 `dividend_tax_by_currency.csv`，兩者納入 report hash manifest，HTML 也顯示 Dividend Tax Drag；report schema 升為 v3。Streamlit 會在 paper replay 顯示 gross/tax/net/effective rate，persistent ledger 區塊也顯示同一組稅務現金流摘要。版本升為 v0.9.2。

M9-4 Dividend Tax Sensitivity 已完成：Robustness Lab 在 raw-price 模式新增 dividend withholding sensitivity，不把單一稅率假設視為確定真值。預設以目前 US/TW 設定為基準，同時測試 -10pp / 0 / +10pp，所有 rate clamp 在 0–100%；0 shift 可直接重用 baseline paper replay。每個情境輸出 US/TW rate、total return、CAGR、volatility、Sharpe、MDD、Calmar，以及 gross dividend / withholding / net dividend / effective rate。Adjusted total-return basis 沒有獨立股息 cashflow，因此此診斷回傳空表而不製造假敏感度。Streamlit Robustness Lab 新增 Dividend Tax Sensitivity 分頁。版本升為 v0.9.3。

M10-1 Explicit Cash-in-Lieu Settlement Support 已完成：`MarketData` 新增 sparse `cash_in_lieu_prices` panel，reverse/non-integer split 若當日 provider 已提供可用 settlement price，fractional share cash 會優先用該值；沒有 explicit value 時才保留 ex-date raw open fallback。每筆 split corporate-action event 明確保存 `cash_in_lieu_price` 與 `cash_in_lieu_price_source`（`provider_settlement` / `raw_open_fallback`），historical backtest 與 persistent paper ledger 共用同一計算。Market snapshot schema 升為 v5 並維持 v2–v4 loader 相容；slice、provider subset、paper split、verified UI subset 與 stable-identity stitching 都會保留 settlement panel。Persistent SQLite ledger 會自動 migration 新 audit 欄位。**Point-in-time 限制：explicit price 只能代表 corporate-action processing date 當下已可用/可入帳的值；若實際 cash-in-lieu 是延後數日才結算，不應把日後價格倒填到 ex-date，延後 receivable timing 留給 M10-2。** 版本升為 v0.10.0。

M10-2 Delayed Cash-in-Lieu Receivable Accounting 已完成 historical 路徑：`MarketData` 新增 sparse `cash_in_lieu_settlement_dates`，snapshot schema 升為 v6 並維持 v2–v5 相容。若 reverse/non-integer split 的 settlement date 晚於 ex-date，系統不會提前把日後 settlement price 或 cash 倒填到 split 日，而是建立 fractional receivable；receivable 以當日 raw price × fractional quantity × FX mark-to-market 納入 NAV，但不進 `cash`，因此不能提前支用。`settlement_date` 定義為第一個「模擬開盤前金額已知且可支用」的 session；到該日才要求 explicit `cash_in_lieu_price`、把 receivable 轉成 cash，並新增 `cash_in_lieu_settlement` audit event。若券商實際入帳發生在盤中或收盤後，資料應填下一個可支用 session，而不是付款名義日期。Split event 會保存 fractional quantity、pending source 與 settlement date。若有人同時宣告 future settlement date卻又在 ex-date 填入 settlement price，直接 fail closed，避免 look-ahead。M10-2 當時 persistent replay 對 delayed settlement 採 fail closed；後續 M10-3 已補上 SQLite receivable lifecycle。版本升為 v0.10.1。

M10-3 Persistent Cash-in-Lieu Receivable Ledger 已完成：SQLite 新增 `cash_in_lieu_receivables` lifecycle table，保存 fractional quantity、created/settlement date、local currency、base-currency cost basis、OPEN/SETTLED status、實際 settlement price/FX/cash 與 realized PnL。Pending fractional entitlement 不在 split 日提前認列 realized loss；其 cost basis 留在 receivable，daily NAV 以 raw close/FX mark `receivable_value`，同時把 mark − basis 計入 unrealized PnL。Target sizing 以含 receivable 的總 NAV 計算，但成交 affordability 仍只看 cash。到 settlement session 開盤前先把 due receivable 轉成 cash，再處理當日 corporate actions / terminal / open orders；realized PnL = settlement cash − receivable cost basis。Ledger 關閉重開後 OPEN receivable 仍可延續並結算；舊 NAV schema 會自動補 `receivable_value=0`。Streamlit Persistent Paper Ledger 新增 receivable current NAV mark、open count 與 lifecycle tab。版本升為 v0.10.2。
