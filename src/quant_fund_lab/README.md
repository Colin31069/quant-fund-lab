# quant_fund_lab 核心模組架構導覽

> 本文件依據 Anthropic Agent-First 架構規範維護，提供 AI Agent 與工程師專案子系統的快速檢索與介面指引。

## 1. 系統分層地圖 (Architecture Layers)

```
[Presentation & UI] (ui.py, ui_inputs.py, reporting.py)
       │
[Odd-Lot Strategy Lab] (odd_lot_research.py, odd_lot_study.py)
       │
[Alpha & Factor Lab] (models.py, factors.py, walkforward.py, robustness.py)
       │
[Portfolio & Risk] (portfolio.py, risk_controls.py)
       │
[Execution Engine] (execution.py, odd_lot_execution.py, corporate_actions.py)
       │
[Paper & Audit Ledger] (paper_live.py, ledger_audit.py, provenance.py)
       │
[Data & Market Infrastructure] (data.py, security_master.py, twse_odd_lot.py, fundamentals.py)
```

---

## 2. 子系統詳細劃分與模組職責

### A. 市場資料與標的架構 (Data Infrastructure)
- **`data.py`**: `MarketData` 核心容器（Open, Close, Volume, Raw Open/Close, FX, 遮罩）。
- **`data_quality.py`**: 資料品質檢核、缺漏值與跳空檢查。
- **`snapshot.py`**: Parquet 資料快照的序列化、載入與 SHA-256 驗證。
- **`providers.py`**: 資料提供者責任鏈（Yahoo Finance、本機已驗證 Snapshot 回退）。
- **`security_master.py` & `security_master_events.py`**: 具備穩定 `security_id` 的點時主檔（Security Master），管理上市、下市（Delisting）與代碼變更事件，防範存活者偏差。
- **`identity_market_data.py`**: 跨生命週期代碼拼接，防止同一代碼重複使用導致資產混淆。
- **`fundamentals.py`, `sec_fundamentals.py`, `taiwan_fundamentals.py`**: 點時財務資料（US SEC XBRL、台股 FinMind / MOPS），嚴格要求 `filed_at <= signal_date`。
- **`market_cap.py`**: 點時歷史市值面板計算（結合流通在外股數與 Raw Close）。
- **`market_calendar.py` & `fx.py`**: 多市場交易日曆（XNYS, XTAI）與多幣別換匯因子。

### B. Alpha 模型與因子研究 (Alpha & Research)
- **`models.py`**: 數學 Alpha 模型（Kalman 趨勢狀態空間、OU 均值回歸、橫斷面殘差動能、Ensemble 混合）。
- **`factors.py`**: 價量因子實驗室（動能、反轉、低波動、低 Beta、流動性）、Rank IC 與因子殘差化。
- **`fundamental_factors.py`**: 衍生基本面因子（ROE/ROA、營業利益率、資產成長率、月營收成長）。
- **`walkforward.py`**: 防洩漏 Walk-forward 參數尋優、候選網格產生、Deflated Sharpe Ratio (DSR)。
- **`robustness.py`**: 穩健性檢驗（交易成本壓力測試、Block Bootstrap 績效分佈、市場狀態歸因）。
- **`research.py` & `research_inputs.py`**: 市場狀態偵測（Regime）、Alpha 統計中性化、輸入資料凍結與雜湊。
- **`diagnostics.py`**: 策略健康度指標。

### C. 投資組合與風險控制 (Portfolio & Risk)
- **`portfolio.py`**: Shrinkage Covariance + 帶約束均值變異數二次最佳化（Long-only、個股權重上限）。
- **`risk_controls.py`**: 最佳化後風險層（波動度目標控制、歷史 CVaR/Expected Shortfall 限制、策略回撤去風險）。

### D. 訂單撮合與會計結算 (Execution & Accounting)
- **`execution.py`**: 共享撮合引擎（開盤市價單、整張與零股整數取整、滑價模型、市場衝擊、交易稅費）。
- **`corporate_actions.py`**: 股票分割與除權息持倉調整、碎股折現款（Cash-in-Lieu）計算。
- **`cash_carry.py`**: 基礎貨幣閒置現金年化收益計息（ACT/365）。
- **`tax_analytics.py`**: 跨市場股利扣繳稅（Withholding Tax）追蹤與報表分析。
- **`cash_in_lieu_data.py` & `cash_in_lieu_analytics.py`**: 碎股折現款生命週期與結算延遲分析。
- **`backtest.py`**: 歷史回測主迴圈，整合資料、Alpha、最佳化與撮合引擎。

### E. 證交所官方零股專題 (TWSE Odd-Lot Trading)
- **`twse_odd_lot.py`**: 證交所官方月價量、除權息、減資與開休市資料解析與嚴格品質守門。
- **`twse_coverage_amendments.py`**: 顯式逐標的／類別／期間 CoverageReview；核對證據 bytes 後發布不可變衍生資料，保留原 coverage／manifest，不從舊 coverage 自動推定五類審核完成。
- **`odd_lot_rights/`**: E05 認購權純核心：分階段資訊、共用持股基礎的多腿權利、明確付款／費用、待交付資產、碎股淨款、憑證換發與精確估值／checkpoint；真實來源、session／SQL／獨立稽核尚待接線，未解除現有 unsupported 事件。

  接續已有 `audit.py`／`audit_reconstruction.py` 獨立重建原命令的現金、費用、逐腿數量及 inventory debit／credit；實際來源、外層 cash flows／持倉與 NAV 連結仍待整合，不以純核心稽核通過放行真實事件。
- **`odd_lot_event_dates.py`、`twse_event_amendments.py`**: 逐案核對全市場休市的純現金股利日期映射；保留原訂索引與原資料包，修訂證據進入 freeze／報告 hash，不支援以此方式處理認股權。
- **`twse_preparation.py`**: 官方檔案批次預覽、原子替換與匯入管線。
- **`odd_lot_execution.py`**: 零股升降單位（Tick size）、限價撮合代理、委託比例與交割規則。
- **`odd_lot_research.py`**: 十萬元台股零股策略獨立研究引擎（動能、均值回歸、動態止損與風險預算）。
- **`odd_lot_benchmarks.py`**: 明確 ETF 規則的單一可交易基準；期初一次零股委託、未成交到期、股利保留現金，與策略共用撮合及帳務。
- **`odd_lot_diagnostics/`**: 純讀取資金／未成交／episode 風險及止損退出診斷；建倉預算有 fill 證據，未平倉與權利待收款分列，缺來源不造有效數值；v3 協議輸出及重建核對報告。
- **`odd_lot_sensitivity/`**: v4 協議的固定策略／ETF 成本與成交比例矩陣；逐情境保存設定、帳務與成功／受阻／失敗結果，來源摘要可重建，不以驗證期敏感度自動選參。
- **`odd_lot_decisions/`**: R07 純計算決策核心；只依開發期排名，固定選擇後檢查驗證／敏感度／風險，逐項保留失敗與缺資料，沒有驗證後改選。協議、登記來源與 UI 接線尚待完成。
- **`odd_lot_study.py`**: 零股研究批次執行、報告與 SQLite 唯讀帳戶凍結。
- **`odd_lot_protocol/`**: 有限候選協議、程式／環境身分、不可覆寫的協議及 SQLite 實驗重試紀錄；接既有守門執行與雜湊報告，保留受阻／失敗與重現性差異。
- **`trade_analytics.py`**: 持倉 Episode 重建、勝率、Profit Factor 與期望值分析。

### F. 模擬實盤與帳本稽核 (Paper Trading & Audit)
- **`paper.py`**: 歷史回測與 Paper Replay 時間切分。
- **`paper_live.py`**: SQLite 持久化模擬帳本（`PaperLedger`），管理訂單生命週期、未成交保留與結算。
- **`paper_workflow.py`**: Paper Trading 高階排程與工作流。
- **`ledger_audit.py`**: 帳本對帳、Session 原子性保證與 SHA-256 雜湊鏈防竄改日誌。
- **`provenance.py` & `replay_provenance.py`**: 執行環境 Provenance 與 Run ID 生成。

### G. 視覺化儀表板與產物報表 (Presentation & Reporting)
- **`ui.py`**: Streamlit 本機量化研究與視覺化平台。
- **`ui_inputs.py`**: UI 輸入參數解析、驗證與狀態管理。
- **`reporting.py`**: 產出包含雜湊 Manifest 的 HTML、CSV 與 JSON 研究報告。
- **`analytics.py`**: 核心財務績效統計（CAGR、Sharpe、Max Drawdown、Calmar）。
- **`config.py`**: 核心配置 Dataclasses（`BacktestConfig`, `StrategyConfig`, `ExecutionConfig` 等）。

---

## 3. 開發規範與負向約束
1. **單檔長度控制**：新功能應控制在 250~300 行以內。
2. **大型歷史檔案守門**：`paper_live.py` (1700 行) 與 `ui.py` (1100 行) 為既有大型檔案，任何更動必須遵循微小、可獨立驗證的原子提交，嚴禁大規模未規劃重構。
3. **不可破壞現有測試**：任何改動必須通過全數 311 筆測試（`./scripts/verify.sh`）。
