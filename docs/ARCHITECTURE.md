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

**M2-3 待做：** regime detection、factor neutralization 與更完整的 risk budgeting。

### M3 — Persistent paper trading

每日資料快照、SQLite/DuckDB ledger、虛擬訂單狀態、pending/partial fills、PnL attribution、基準與實際 observed close 對帳。

### M4 — Production hardening

資料 provider failover、reproducible dataset snapshots、audit log、config version、deterministic run id、報告匯出。
