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

MVP + M1 + M2 完成：除交易日曆、停牌/漲跌停、交易成本、point-in-time universe、terminal return、企業行動、可重現資料快照與 USD/TWD base-currency accounting 外，研究層已加入 leak-resistant walk-forward calibration、Deflated Sharpe Ratio、White Reality Check-style stationary bootstrap，以及 M2-3 regime detection、statistical factor neutralization 與 risk-contribution budgeting。Regime 只使用 trailing market returns 調整模型混合與 gross exposure；alpha 再對 market beta / idiosyncratic volatility 做可調強度的橫斷面部分殘差化，避免一次把有效 alpha 全部投影掉；optimizer 以 normalized risk contribution penalty 抑制風險集中。M3 persistent paper trading 也已完成：SQLite ledger 保存虛擬訂單、partial/pending 狀態、fills、positions、realized/unrealized PnL、NAV、benchmark 與 reconciliation；每日市場資料以 SHA-256 snapshot 留存，ledger 可關閉後重新開啟繼續處理未成交訂單。下一階段進入 M4 production hardening。
