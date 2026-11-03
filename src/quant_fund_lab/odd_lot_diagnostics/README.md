# 零股風險診斷

`RiskDiagnosticInputs` 明列 equity、fills、orders、signals、episodes、企業行動、終止事件及凍結設定。`inputs_from_result()` 轉接研究結果；`diagnose_odd_lot_account()` 純讀取來源，不下單、不改帳務。`types.py` 定義 `odd_lot_risk_diagnostics_v1` 輸出及 unavailable／pending 語義。

## 計算與來源

- `capital.py`：持股市值為 NAV 減可支用 cash、未收賣款及碎股應收估值；另列可支用現金、應付及應收比例。買款已保留，不重扣 NAV；應付比例是交割負擔，與配置比例重疊。來源缺欄位、非有限值、NAV 非正或計算溢位均不可用。
- `orders.py`：按 side／status／outcome 彙總未成交剩餘量，先核對 requested＝filled＋expired 與非負整數。entry 訊號缺下一 session 委託時明列來源缺口，最後訊號尚無可執行 session 則 pending。無法從未記錄資料推斷拒單或取消原因。
- `episodes.py`：使用建倉 fill 的 `entry_risk_budget` 並核對凍結設定；不從事後損失或目前設定回填舊預算。完全結束的 episode 才有已實現淨虧損、超額額度及損失／預算比例；仍持股或待收權利款則 pending。被動等權／ETF 不適用止損預算。
- `stops.py`：從首次 stop 訊號計數，列全部 stop 賣單嘗試與股份出清時間；按帳戶實際 session 序列計延遲，另列日曆日。出清須有 SELL fill、terminal event 或股數歸零的拆股證據。股份出清與碎股款結清分列，未退出不填完成延遲。

診斷的損益來自既有 episode 淨損益：成交價已含滑價，費用及股利不再重複扣加。缺建倉預算時可知道已完成交易的損失，但超額指標不可用；這不改寫已完成 episode 數。少於 30 筆已完成 episode 顯示樣本不足，達 30 筆也不證明策略有效。

## 協議與報告

`protocol_from_studies(..., benchmark_spec=..., risk_diagnostics=True)` 明確凍結 v3 分析協議。診斷加入數值指紋與 report manifest；v1／v2 不自動新增診斷。新增 fill 證據改變程式身分，新執行需新協議；保存的舊報告仍按原協議讀取。

`odd_lot_protocol/diagnostics.py` 接研究結果，輸出 `risk_diagnostics.json` 及每帳戶 `capital_utilization.csv`、`episode_risk_audit.csv`、`unfilled_order_summary.csv`，HTML 摘要列來源缺口及樣本提示。受阻研究沒有帳戶時，JSON 的 accounts 為空並保留 unavailable，不能解讀為零風險。

報告驗證讀回保存的來源 CSV 重建診斷，再比對 JSON、CSV、帳戶清單及協議；改診斷後重算 manifest hash 仍無法通過來源核對。此完整性機制不是外部簽章或來源真實性認證。

測試見 `tests/test_odd_lot_diagnostics.py` 與 `tests/test_protocol_diagnostics.py`：實際引擎跳空限價失敗／退出、部分成交、未平倉、碎股權利待結算、缺預算、非法資料、重跑及報告篡改。真實資料能否研究另由 readiness／事件／coverage 閘門決定。
