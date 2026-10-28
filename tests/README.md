# 測試套件導覽 (Test Suite Guide)

> 本目錄遵循 Anthropic Agent-First 確定性驗證原則維護。
> 所有程式碼修改必須伴隨自動化測試通過，嚴禁未經測試推入版控。

## 1. 執行方式

- **完整測試套件**：
  ```bash
  ./scripts/verify.sh
  # 或直接執行
  pytest
  ```
- **快速單模組測試**：
  ```bash
  pytest tests/test_core.py
  pytest tests/test_odd_lot_research.py
  pytest tests/test_twse_odd_lot.py
  ```
- **執行除耗時回測之外的快速測試**：
  ```bash
  pytest -m "not slow" (或排除 test_walkforward.py)
  ```

## 2. 測試分類與對應模組

| 測試檔 | 涵蓋模組 | 說明 |
| :--- | :--- | :--- |
| `test_core.py` | `backtest.py`, `execution.py`, `portfolio.py`, `models.py` | 核心回測流程、權重最佳化、模型訊號 |
| `test_factors.py` | `factors.py` | 價量因子庫、Rank IC、因子殘差化 |
| `test_fundamental_factors.py` | `fundamental_factors.py` | 財務指標衍生（ROE/ROA、營收成長等） |
| `test_fundamentals.py` | `fundamentals.py`, `sec_fundamentals.py` | 美股 SEC XBRL 與基礎架構 |
| `test_taiwan_fundamentals.py` | `taiwan_fundamentals.py` | 台股 FinMind / MOPS 財報與營收 |
| `test_security_master.py` | `security_master.py` | Point-in-time Security Master、下市處理 |
| `test_security_master_events.py` | `security_master_events.py` | 生命週期事件（LISTED, DELISTED, 代碼變更） |
| `test_identity_market_data.py` | `identity_market_data.py` | 跨生命週期代碼拼接與身份連續性 |
| `test_corporate_actions.py` | `corporate_actions.py`, `tax_analytics.py` | 股票分割、現金股利、扣繳稅率 |
| `test_cash_in_lieu_*.py` | `cash_in_lieu_*.py` | 分割碎股折現款（Cash-in-Lieu）會計與結算 |
| `test_cash_carry.py` | `cash_carry.py` | 閒置現金利率與計息入帳 |
| `test_odd_lot_*.py` | `odd_lot_*.py` | 十萬元零股策略、動能止損、升降單位與撮合代理 |
| `test_twse_odd_lot.py` | `twse_odd_lot.py` | 證交所官方月價量、除權息與停牌資料檢驗 |
| `test_twse_preparation.py` | `twse_preparation.py` | 證交所資料匯入與原子替換管線 |
| `test_paper_*.py` | `paper*.py` | SQLite 持久化帳本、模擬下單、Session 原子性 |
| `test_ledger_audit.py` | `ledger_audit.py` | 帳本對帳與 SHA-256 雜湊鏈稽核 |
| `test_walkforward.py` | `walkforward.py` | Walk-forward calibration 與多重假說檢定 (DSR) |
| `test_robustness.py` | `robustness.py` | 成本壓力測試、Block Bootstrap 與市場狀態歸因 |
| `test_production.py` | `providers.py`, `reporting.py` | 快照提供者、離線驗證與雜湊報告 |
| `test_ui_*.py` | `ui_inputs.py`, `ui.py` | UI 參數狀態與驗證 |

## 3. 測試撰寫慣例
1. **確定性**：使用固定隨機種子（如 `seed=11`）或合成市場資料，禁止依賴外部網路連線。
2. **無副作用**：涉及檔案寫入與 SQLite 帳本必須使用 pytest `tmp_path` fixture。
3. **無洩漏防護**：驗證 signal date 只取當下以前可得資料，防止 look-ahead bias。
