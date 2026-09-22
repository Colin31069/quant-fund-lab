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

MVP + M1-1：日線、long-only、現金帳戶、可設定交易成本與滑價；已加入交易日曆品質檢查、停牌/零成交量不成交、台股普通交易 1,000 股單位與漲跌停鎖單代理模型，以及手續費/滑價/換手歸因。後續再加入 survivorship/delisting、FX、企業行動資料品質層與 walk-forward calibration。
