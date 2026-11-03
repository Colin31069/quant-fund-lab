# 策略與可交易 ETF 的固定情境敏感度

`types.py` 先定義 `SensitivityScenario`、`SensitivityOutcome` 與 `MatchedSensitivity`。每個有限情境凍結最低費、滑價及成交比例，有穩定 scenario ID；矩陣依固定順序涵蓋 ensemble、momentum 與可交易 ETF。缺列、重複、錯誤成功帳戶清單、非有限成本或非法成交比例均拒絕。批次／情境數不能當作獨立統計試驗數。

## 執行語義

`run_matched_sensitivity()` 僅分析凍結 validation 期間，採與 primary account 相同的暖機、起迄、交易 sessions、初始資金、共用撮合／費用／交割模型。只改 scenario 指定的三個欄位；ETF 保留 `BenchmarkSpec` 的稅率、限價、一次進場、未成交到期及股利現金政策。其他設定逐項核對；基礎設定相同時可重用已完成 primary account，避免重算同一情境。

`succeeded` 表示該情境計算完成，不代表有成交、樣本足夠或策略有效。必要資料或 primary account 缺失為 `blocked`，不計算績效。單一情境例外記為 `failed`，保留類型與原因，繼續其他預定情境；無法正常完成的情境沒有虛構指標。必要情境失敗會讓整個 registered attempt 成為 failed，但報告與數值指紋仍保留，後續重試不覆寫。

`account_summaries()` 從已含成本的 NAV、fills、orders、episodes 計算績效、樣本、資金與費用摘要。commission／tax／slippage 欄位只是已發生成本的揭露，不再扣一次。分母不存在或非有限的摘要值為 null，名稱列在 `undefined_metrics`。實際模擬資料與零股撮合仍沿用研究模型的代理假設。

## 協議及報告

使用 `protocol_from_studies(..., benchmark_spec=..., risk_diagnostics=True, matched_sensitivity=True)` 明確建立 `frozen_odd_lot_batch_v4`。沿用既有有限成本／成交比例情境，新增 ETF 對照及 `matched_sensitivity_v1` 執行規則。情境集合在執行前寫入協議，不依結果刪情境或更換成本。Validation 的這份敏感度是診斷，沒有自動選參；真正選擇規則與開發／驗證用途另由後續決策功能處理。

V4 關閉 legacy batch 內的彙總敏感度分支，再執行完整 matched grid，避免同一情境重複搜尋；v1／v2／v3 保持原分析宣告與預設執行路徑。升級需要新協議／實驗身分，保存的舊報告仍可讀取。

輸出 `matched_sensitivity.json`、含全部成功／受阻／失敗列的 `sensitivity.csv`、HTML 說明，以及每個成功情境的 `scenario_<id>_<strategy>_account.json` 與 equity、fills、orders、settlements、signals、episodes、corporate_actions、terminal_events CSV。這些情境帳戶是獨立的研究證據，不是可續跑的 paper account；primary account 的研究 SQLite archive 保持原用途。

全部輸出進 report manifest 與數值指紋。`verify.py` 核對完整固定矩陣、帳戶設定、與 primary 相同 sessions、來源帳務重新計算的摘要及 CSV。刪除不利情境、只改設定／摘要再重算 hash 仍不能通過。已失敗例外本身不能從來源重新執行證明，會保留為失敗紀錄，不能提升為成功；此機制也不提供外部簽章或資料真實性認證。

## 驗證

`tests/test_odd_lot_sensitivity.py` 使用實際引擎：期初 100,000、200 元買 500／250 股，210 元時 NAV 為 105,000／102,500；另加最低費 20 與滑價後 NAV 為 102,455，費用只扣一次且不補單。還包含截斷未來的 prefix 一致、單一情境失敗後其餘保留、受阻不進撮合及非法假設。

`tests/test_protocol_sensitivity.py` 驗證 v4 全矩陣、重跑、來源／設定／摘要核對、blocked 清單、失敗 attempt 的完整報告與後續成功重試。真實資料 readiness 與完整 M13 驗收獨立處理。
