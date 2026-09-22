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
