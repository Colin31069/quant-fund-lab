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

MVP + M1 + M2-1 + M2-2 完成：除交易日曆、停牌/漲跌停、交易成本、point-in-time universe、terminal return、企業行動、可重現資料快照與 USD/TWD base-currency accounting 外，現已加入 leak-resistant walk-forward calibration、Deflated Sharpe Ratio 與 White Reality Check-style stationary bootstrap。參數只能由 Validation 區間選擇，Test 完全不參與選參；統計診斷再針對多重測試與 data snooping 修正「幸運冠軍」問題。下一階段 M2-3 加入 regime detection、factor neutralization 與 risk budgeting。
