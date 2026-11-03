# M12-4：統一研究就緒檢查與修復清單

2026-10-29 接續：已補共用分期修復摘要與語義核驗，UI／CSV／HTML 分列期內缺月及暖機依賴；兩環境相關各 31 項、後續整合各 23 項通過。Q-A01–A12 現均有明確離線 assertion 對應，案例審查見 `artifacts/acceptance/B01/readiness-repair-summary-20261029/consolidated-review.json`。整體仍待包含最新變更的完整回歸／發布審查與真實資料驗收；下方待實作及估算保留最初時點。

狀態：待實作；預定版本 `0.12.4`。預估 3–5 人日，含測試、相容驗證與 Streamlit 接入。
核心型別／fixture 工作可先開始，整合驗收需 P0 通過。

## 目標與既有能力

既有 [twse_preparation.py](../../quant_fund_lab/twse_preparation.py) 已有批次匯入預覽、問題分類、期間摘要及缺檔清單；[odd_lot_study.py](../../quant_fund_lab/odd_lot_study.py) 另外做正式期間守門。本版把正式判定及其證據集中成純讀取核心，讓 UI、研究執行及報告使用同一結果。

不以修改顯示文字或減少錯誤筆數當驗收；驗收對象是「必要條件未滿足時不能執行或顯示相依績效」。

## 先定義的資料契約

建議放 `src/quant_fund_lab/twse_quality/`，拆 `types.py,readiness.py,legacy.py` 並附 README；各程式檔不超過 300 行。以下均為擬新增契約：

| 型別／介面 | 必要欄位／語義 |
| --- | --- |
| `FindingCode` | 穩定 enum：月檔、交易日、來源完整性、分項審核、未建模事件、暖機、標的／基準缺漏；未知代碼亦阻擋 |
| `ReadinessFinding` | ID、code、symbol、start/end、source refs、depends_on、detail；ID 由語義鍵產生，不包含翻譯文字 |
| `WarmupEvidence` | 日曆來源與 revision、要求日期、預期 session、真實行情或合法停牌解釋、驗證結果 |
| `PeriodReadiness` | period、要求／實際起迄、warmup required/verified、blocking IDs、`ready/blocked/unknown` |
| `StudyReadiness` | schema version、input fingerprint、rule version、findings、periods、研究限制 |
| `assess_study_readiness()` | 接受 TWSEInput、期間設定與暖機規則；無下載、SQLite 建立、檔案修改或績效計算副作用 |

資料不足與明確錯誤分別用 `unknown`／`blocked`；兩者都阻擋相依期間。基準以同樣規則檢查。來源完整性失敗若無法安全建構 TWSEInput，先以明確錯誤中止，不需要勉強回傳 ready/blocked 表。

本版先以官方來源完成上述契約；後續 [DATA-02](DATA_SOURCE_INTEGRATION.md) 透過明確 adapter 接入來源中立輸入，不將 provider 判斷散落到 UI／報告。input fingerprint 須可容納來源政策、實際逐日選源與轉換 revision；原官方缺檔規則保持，新增來源模式按其明列政策檢查必要價格，兩者共用事件／日曆／暖機等必要判定。

問題的適用政策及阻擋原因須明列；來源模式變更時重新評估，保留原始 findings 與適用性說明，不沿用另一模式的 ready，也不刪掉官方缺檔紀錄。

## 判定順序與暖機規則

1. 驗證來源 hash、身分、日期與唯一鍵；不能先信任已正規化數值而略過來源。
2. 從要求的期間起點往前找至少 `max(120, strategy.warmup_days)` 個經核對市場 session；不能只數現有 DataFrame 列數。
3. 每個所需 session／symbol 檢查價格，或有來源的停牌／休市解釋；停牌不能補造開盤價與成交量。無法證明預期 session 集合時回傳 unknown。
4. 在研究及暖機窗口檢查五類連續覆蓋、企業行動一致性、未建模事件、基準資料。
5. 產生不刪減原始問題的結構化結果，再推導分期修復工作清單。相依關係只解釋原因，不能消除必要阻擋。

## 執行工作包

| ID | 動作 | 產物／退出條件 |
| --- | --- | --- |
| Q01 | 列出現有品質守門、期間與暖機判斷，對應穩定代碼 | 規則表完整覆蓋既有拒絕條件；未知 legacy 問題仍保守阻擋 |
| Q02 | 定義 dataclass/schema、語義 ID、序列化與 rule version | 最小有效／無效輸入可離線驗證，不改寫舊凍結 metadata |
| Q03 | 實作純讀取判定及暖機證據 | 完整、整日缺漏、停牌、覆蓋不足等案例得到預期期間狀態 |
| Q04 | 研究執行與報告接入同一判定；新 schema 明確升版 | 同一次準備結果不會在 UI 可用、執行卻不可用；舊來源變動仍會被攔下 |
| Q05 | 加入可操作期間狀態、問題篩選與修復清單匯出 | 可看到缺項、受影響期、相依原因、需補佐證與重新檢查結果 |
| Q06 | 跑舊資料相容、AppTest、凍結研究與全套回歸 | 雜湊／守門條件未弱化，新增 schema 及操作有完整說明 |

Q01–Q03 為第一個可獨立審查單元，Q04 為第二個，Q05–Q06 為第三個；避免把大型 UI／parser 重寫綁入同一變更。

## 驗收矩陣

| 案例 ID | 情境 | 通過標準 |
| --- | --- | --- |
| Q-A01 | 同一輸入重複評估 | findings ID、期間狀態、fingerprint 完全一致；磁碟 bytes 與 DB 均無修改 |
| Q-A02 | 只改顯示文字 | 問題語義 ID 與阻擋狀態不變；不能靠文字改動讓問題消失 |
| Q-A03 | 缺一份月檔，再補入該月行情 | 重查只移除已確實解決的缺價；分項審核／未建模事件仍阻擋 |
| Q-A04 | 全部標的同日缺 bar；觀測列數仍達 120 | 依經核對預期 sessions 找到缺漏，不能宣告暖機完整 |
| Q-A05 | 119／120／自訂較長暖機 | 邊界判定與要求一致；有效停牌說明不產生虛構 open |
| Q-A06 | 交易標的完整但 0050 缺價／缺審核 | 相依期間不可用，不忽略基準，也不先輸出局部排名 |
| Q-A07 | 跨期暖機缺口 | 缺少前期資料會阻擋相依下一期；分期缺檔數與暖機相依數分開呈現 |
| Q-A08 | 同一資料走 UI、研究執行與匯出 | 使用相同 readiness fingerprint、blocking IDs 及狀態；受阻時無績效計算 |
| Q-A09 | 原始來源被改動、未知 issue／legacy 覆蓋資料 | 來源失敗明確中止；未知問題不當成通過，舊 coverage 不自動升級五類審核 |
| Q-A10 | 載入舊凍結研究／新 readiness 被竄改 | 舊資料按舊 schema 正常驗證；新 study/report 的新增檔案 hash 檢查能發現竄改 |
| Q-A11 | 匯出缺口清單後重新匯入再評估 | key 可去重且來源衝突仍拒絕；新結果綁定新 input fingerprint |
| Q-A12 | 完整 fixture 與受阻 fixture 的 AppTest | 前者允許執行、後者顯示具體修復項目並阻擋；不另寫 UI 判定規則 |

擬新增 `tests/test_twse_readiness.py` 與相關 AppTest；延用現有 `test_twse_preparation.py,test_twse_odd_lot.py,test_odd_lot_research.py` 做回歸。驗收輸出含規則表、readiness JSON、修復 CSV、畫面／AppTest 證據與完整測試摘要。
