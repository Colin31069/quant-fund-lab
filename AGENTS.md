# AGENTS.md (Agent 專案導覽手冊)

> 本手冊依據 Anthropic Agent-First 架構規範維護，全文嚴格控制在 200 行內。
> 各模組詳細規格與介面契約請參閱 `src/quant_fund_lab/README.md` 及 `src/ARCHITECTURE/README.md`。

## 1. 核心開發與驗證原則 (Hard Constraints)
1. **規格與型別先行**：編寫邏輯前先定義資料型態（Pydantic schemas / dataclasses）與公開介面。
2. **上下文鄰近性 (Context Colocation)**：文件、型別與測試盡可能與功能代碼置於同一資料夾，避免跨多層查找。
3. **單檔長度控制**：單一程式碼檔案行數建議控制在 **250~300 行** 內。若超過上限，必須拆分。
4. **確定性驗證**：任何修改後必須執行自動化檢查（Lint 與 Unit Test），禁止猜測性修改。
5. **負向約束 (絕對禁止)**：
   - ❌ 禁止刪除既有註解與文檔（docstrings、型別說明）。
   - ❌ 禁止一次性大規模無規劃重構：特別是 `paper_live.py` (1700行) 與 `ui.py` (1100行)，所有改動必須拆解為微小、可驗證的單元進行。
   - ❌ 禁止將未測試代碼推入版控。
   - ❌ 禁止串接真實券商 API 或送出真實訂單（本專案純為虛擬回測與研究平台）。

## 2. 標準確定性驗證指令 (Verification Gates)
- **一鍵驗證 (Lint + Test)**: `./scripts/verify.sh`
- **靜態檢查與代碼風格**: `ruff check .`
- **完整單元測試**: `pytest`
- **快速單元測試**: `pytest tests/test_<target>.py`
- **本機視覺化儀表板**: `streamlit run src/quant_fund_lab/ui.py`

## 3. 模組拓撲地圖 (Architecture Map)

| 子系統 | 涵蓋模組檔案 (`src/quant_fund_lab/`) | 職責與邊界 |
| :--- | :--- | :--- |
| **Data Layer** | `data.py`, `snapshot.py`, `providers.py`, `security_master*.py`, `identity_market_data.py`, `fundamentals*.py`, `market_cap.py`, `market_calendar.py`, `fx.py` | 點時市場數據、Security Master 生命週期、財報 XBRL/FinMind、多幣別匯率、資料快照與 SHA-256 完整性校驗。 |
| **Alpha & Research** | `models.py`, `factors.py`, `fundamental_factors.py`, `walkforward.py`, `robustness.py`, `research.py`, `research_inputs.py`, `diagnostics.py` | Kalman/OU/殘差動能 Alpha、價量/基本面因子實驗室、Walk-Forward 校準、DSR 與 Block Bootstrap 穩健性檢定。 |
| **Portfolio & Risk** | `portfolio.py`, `risk_controls.py` | 收縮共變異數最佳化、波動度目標控管、Expected Shortfall (CVaR) 限制與策略回撤去風險。 |
| **Execution & Accounting** | `execution.py`, `corporate_actions.py`, `cash_carry.py`, `tax_analytics.py`, `cash_in_lieu*.py`, `backtest.py` | 撮合引擎、股票分割與除權息、碎股折現款（Cash-in-Lieu）、股利扣繳稅與回測主迴圈。 |
| **TWSE Odd-Lot** | `twse_odd_lot.py`, `twse_preparation.py`, `odd_lot_execution.py`, `odd_lot_research.py`, `odd_lot_study.py`, `trade_analytics.py` | 證交所官方月價量與索引資料品質守門、十萬元零股策略研究、升降單位與撮合代理、凍結研究產物。 |
| **Paper & Audit** | `paper.py`, `paper_live.py`, `paper_workflow.py`, `ledger_audit.py`, `provenance.py`, `replay_provenance.py` | SQLite 持久化模擬下單帳本（`PaperLedger`）、訂單狀態機、Session 原子性防中斷與雜湊鏈稽核。 |
| **UI & Reporting** | `ui.py`, `ui_inputs.py`, `reporting.py`, `analytics.py`, `config.py` | Streamlit 互動平台、配置參數驗證、含 SHA-256 Manifest 的可驗證研究報告與績效統計指標。 |

## 4. 上下文檢索指引 (Progressive Disclosure)
- 模組詳細介面與職責請參閱 [`src/quant_fund_lab/README.md`](src/quant_fund_lab/README.md)。
- 系統演進歷史、各 Milestone 邊界與未來 Roadmap 請參閱 [`src/ARCHITECTURE/README.md`](src/ARCHITECTURE/README.md)。
- 測試套件架構與測試指引請參閱 [`tests/README.md`](tests/README.md)。

## 5. Git 提交規範 (Git Protocol)
- **格式規範**：遵循 Conventional Commits（`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`）。
- **提交前 SOP**：
  1. `git status`：檢查變更清單，確認無殘留垃圾與臨時檔案。
  2. `git diff`：仔細核對每一行改動。
  3. 執行 `./scripts/verify.sh`（或 `pytest` + `ruff check .`）確保全數通過。
  4. 精準執行 `git add <file>`，避免無差別的 `git add .`。
