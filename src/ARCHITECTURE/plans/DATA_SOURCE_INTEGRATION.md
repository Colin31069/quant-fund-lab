# DATA-02：獨立價格來源接入與分期驗收

接續驗收（2026-10-30）：S-A01–A12 已逐案審查，實際證據見 `artifacts/acceptance/DATA-02/provider-guard-edges/acceptance.json`。新混合選源 v1／v2 直接驗證基準缺價、119 日暖機、未建模事件及只允許 ready 開發期產生結果；相關兩環境各 **61 passed**，主 UI 另各 **4 passed**，Lint 通過。發現並修正「選源 CSV 改 provider 後重算 hash 仍通過」漏洞：新 reporting.py 共用編碼，驗證器由凍結 raw／政策重建逐位元比對，遺漏選源表亦拒絕；修正前失敗 log／來源保留。新修正不在 306 檔完整快照內。

真實交接重核全部 405 個原始缺月 key：取得／adapter 驗證為 31／132／242 個月份，目標日資料 653／2662／4813 筆，共 8,128；原缺月 key 在現有官方 manifest 的命中數為 0。study `195e874e86026da7a9209f95` 三期仍 blocked28／23／23、績效0，58 個受檢來源／報告檔 bytes 不變。此輪只做該真實報告 metadata／readiness／file hashes 核對，沒有冒充 native 全來源語義重建。S02 官方 raw 診斷、S05 provider split 邊界手算與 S11 最終 reader 舊包相容範圍仍列 partial；milestone 未 accepted。以下為最初規劃與較早接線基線。


狀態：`planned`，尚未實作。工程預估 3–5 人日，包含離線 adapter、來源政策與研究接線；不含 CAL-02 人工日曆核對、新事件模型或外部資料等待。

執行更新（2026-10-29）：目前為 `in_progress`，上述 planned 為原始規劃基線。原始價格讀取、選源、共用事件／日曆準備及 provider freeze/load/run/report/UI 已接入，完整驗證 359 個測試通過。實際混合來源研究 `94ef4820b48f76d32fef5270` 的報告完整性通過，三期仍因必要資料問題受阻，尚未 accepted；CAL-02、事件審核及完整矩陣仍需完成。證據見 `artifacts/acceptance/DATA-02/prepared/`。
依賴 P0 的一致環境、M12-4 的共用就緒判定；本機 raw 價量已可用，不需等待官方缺漏檔全部取得。

## 為何新增這項工作

2026-10-28 的 [DATA-01](DATA_ACQUISITION.md) 進度記錄：FinMind obtained／validated 均為 405 個目標月份，33 份價格 raw 檔包含 8,128 筆目標日資料；官方數值抽查 1,897 個無不符。
本輪重核 33 份原始檔 hash 及 `normalized/finmind_prices.csv` hash，均與 `provider_manifest.json` 相符，`inventory.csv` 有 405 個唯一目標 key。
這些結果只證明已取得資料及所列檢查，不能推論全來源與官方相同，也沒有證明事件、日曆及歷史資訊可得時間完整。

目前 [run_frozen_odd_lot_study()](../../quant_fund_lab/odd_lot_study.py) 只接受 `twse_official`／`synthetic`，且正式期間守門只在 `twse_official` 分支執行。
所以只新增一個來源名稱到白名單會漏掉正式守門；本工作必須先接 M12-4 共用判定，再開放獨立來源模式。

## 來源政策與相容性決策

| 模式 | 允許來源與身分 | 驗收要求 |
| --- | --- | --- |
| 現有 `twse_official` | 沿用既有原始 TWSE 價格與官方證據 | 缺少官方月檔仍受阻；不得把 FinMind bytes 匯入此身分 |
| 擬新增 `provider_reviewed` | 政策 `reviewed_provider_v1` 明列 TWSE／FinMind 價格來源；事件、停牌及市場日曆另附證據 | 逐區間／逐日選源可追溯，與官方模式共用全部必要就緒規則；新 schema、新 study ID |
| 現有 `synthetic` | 明確標示的流程測試 | 延用合成資料語義，不據此宣稱真實資料通過 |

這是本輪規劃採用的設計，尚未更改現有行為。官方模式為既有預設；新增模式必須明確選擇並在報告顯示來源組成。
價格 fallback 僅能依凍結政策選擇，不能因下載失敗或績效不佳自動更換來源。

必要價格覆蓋依目前政策判定：官方模式要求官方檔，新模式要求已驗證且已選用的允許來源。原官方缺檔 findings 仍可追溯，但在新模式要明列適用政策及不構成本次價格阻擋的原因；不能靠刪除原問題得到 ready。每次評估綁定 policy ID，不沿用另一模式的通過狀態；事件／日曆等共同必要條件仍全部適用。

## 先定義的型別與公開介面

建議新增 `src/quant_fund_lab/odd_lot_inputs/`，以 `types.py,finmind.py,selection.py,prepare.py` 分開並附 README；每檔不超過 300 行。
沿用 `MarketData` 及既有快照完整性元件；以下都是待新增契約，不直接修改 `TWSEInput` 的既有語義。

| 契約 | 必要資訊／行為 |
| --- | --- |
| `PriceSourcePolicy` | policy ID／schema、允許 provider、資料集與 raw basis、覆蓋範圍、交界選源規則、精度／衝突規則、cutoff |
| `PriceSourceRef` | provider、dataset、真實 URL、retrieved_at、raw 相對路徑／SHA-256、轉換版本、單位、價格基準、使用條件參照 |
| `PriceObservation` | symbol/date、raw OHLC、股數量、原始 row locator、source ref、`quoted/no_quote`；保留前導零 |
| `PreparedOddLotInput` | MarketData、逐日價格來源關聯、事件／停牌／日曆／coverage 證據、全部 findings、政策／來源／轉換指紋 |
| `load_finmind_price_bundle()` | 純讀取本機 manifest 與 raw bytes，驗證 hash、來源身分／範圍與資料型別；不下載、不回填官方 manifest |
| `prepare_reviewed_odd_lot_input()` | 按凍結政策合併已驗證價格與證據；交給 M12-4 判定，未解問題全部保留 |

先讓官方 `TWSEInput` 透過小型 adapter 使用同一就緒契約，再接新型別；新 provider 不能另養一套期間／暖機判斷。
來源政策、實際選源、日曆 revision、事件與 coverage 證據、converter revision 都納入 input fingerprint；單純顯示文字不參與語義 ID。

## 正規化與交界規則

1. 以原始檔重建正規化結果；不只信任已產出的 CSV。檢查路徑、hash、symbol-date 唯一鍵、要求範圍及 `2026-10-27` cutoff。
2. 限用已聲明並核對的未調整價格與以股為單位成交量；不以價格外觀猜 raw／adjusted，不把張數誤當股數。
3. 先固定 symbol／日期區間的選源計畫，匯出 `price_selection.csv`；每個選用觀測都指向 raw source 與 row locator。重疊資料按來源精度核對，衝突不平均、不覆寫。
4. FinMind 全零 OHLC 保留為 no-quote 事件；進入 MarketData 時 open／當日 raw quote 不得為可成交的零價。估值延續須有明確規則及前值；no-quote 本身不構成官方停牌證據。
5. `0050.TW` 的 2025-06-11／12／13／16／17 保留已取得停牌佐證；`2317.TW / 2025-07-30` 的 no-quote 另作待核對事件，不能混為同一類。
6. 拆股與股利仍由事件證據建立總報酬代理；先核對價格基準再套事件，不能因抽樣相符就略過全期間事件審核。
7. 歷史來源若分段混用，交界前後暖機／報酬／成交量都驗證；無法證明一致時受阻，不任意捨棄交界日。

## CAL-02：台股預期交易日與事件證據

取得階段使用的 `exchange-calendars==4.5.6` 與 FinMind 交易日有 20 日差集；紀錄明示只是診斷，不是日曆認證。
年度資料解析亦已發現含「補假」文字的分類待核對。先在 P0 選定環境重算差集，再逐日分類：官方例假／補假、臨時休市、真實缺行情、未知或來源衝突。

每筆修正須有交易所證據、生效日、來源 bytes／hash 及具名解析規則；供應商沒有資料不能用來證明休市。
年度年曆與臨時休市證據的補充／衝突政策要明確記錄；一般市場驗證、TWSE 準備與 readiness 使用同一有效 session 集合。
停牌是標的層級，市場休市是市場層級，不得互相替代；新版本差集不一定仍為 20 日，原診斷結果保留。

## 執行工作包

| ID | 動作 | 交付／退出條件 |
| --- | --- | --- |
| S01 | 凍結來源政策／契約，盤點現有取得工具與輸出欄位 | 先定 dataclass／schema 與 fixture；取得工具留存為原交付，不以 artifacts 程式當正式套件依賴 |
| S02 | 實作 raw manifest／價格讀取 adapter | 可離線重建正規化資料，hash／範圍／基準與 no-quote 檢查完整 |
| S03 | 實作選源與官方資料 adapter | 逐日來源可追溯；重疊衝突阻擋；原 TWSE 行為有回歸對照 |
| S04 | CAL-02 重算差集、分類與必要最小修正 | 所需期間的每個日曆差異有證據或未解狀態；不以減少問題數作驗收 |
| S05 | 接新來源 freeze／load／readiness／run／report | 新來源走正式守門；全部證據與政策納入不可變研究，來源組成可辨識 |
| S06 | 本機整合驗收並交接 M12-5 | 先 A 批，再 B／C；交 readiness 與未解事件，不將來源接入完成當研究通過 |

S04 的差集盤點先交付，再估日曆修正／人工核對；新增事件建模沿用 M12-5，不能藏在 3–5 人日 adapter 估算內。

## 必要驗收案例

| 案例 ID | 情境 | 通過標準 |
| --- | --- | --- |
| S-A01 | manifest／raw／normalized 任一被改動 | hash 或重建比對失敗，無法沿用舊輸入身分 |
| S-A02 | 錯 symbol、前導零遺失、重複日、錯範圍、非有限數或單位未知 | 明確拒絕；錯誤可追溯至來源檔／row，不補猜值 |
| S-A03 | TWSE／FinMind 重疊一致與不一致兩例 | 依凍結選源計畫處理一致值；不一致保留衝突與阻擋 |
| S-A04 | 全零 OHLC、停牌、真實缺價各一例 | 無零價成交或虛構 open；no-quote 不自動變停牌，缺證據仍受阻 |
| S-A05 | ETF 拆股前後 raw 價格與事件 | 股數／總報酬／成交價基準符合手算，無重複還原 |
| S-A06 | 相同 raw／政策重跑，或更改來源／選源規則 | 前者身分穩定，後者新 input／study ID；既有資料不覆寫 |
| S-A07 | 補假、臨時休市及沒有證據的缺日 | 僅前兩者按具名官方證據修正；第三者不能被排除預期 sessions |
| S-A08 | 市場 session 由三個入口查詢 | market_calendar、官方準備、readiness 的有效 session 集合一致 |
| S-A09 | provider 模式缺五類 coverage／未知事件／基準／暖機 | 與官方模式同樣阻擋，不能因新增白名單繞過期間檢查 |
| S-A10 | freeze／load／export 後改來源選擇表或事件證據 | study／report manifest 驗證失敗；UI 與報告顯示同一來源政策及 readiness |
| S-A11 | 原官方／合成研究與舊凍結研究 | 原格式可讀可驗證，官方缺檔不因新來源存在而自動結案 |
| S-A12 | 405 份目標 key 分批交接，只有開發期通過 | 只列實際 accepted 的期別；obtained、adapter accepted、research ready 分別計數 |

數值核對使用來源精度與具名規則；現金／NAV 沿用 M12-5 容忍度，不用放大誤差容忍掩蓋來源差異。
單元測試使用自建 fixture；真實整合資料留在本機，不將供應商原始資料複製進 repo。

## 交付與進度相容

交付來源政策 JSON、正式套件 adapter、`price_selection.csv`、日曆差異核對、readiness JSON、來源組成報告、測試結果與 M12-5 交接清單。
`inventory.csv` 目前使用 obtained／validated／imported 等布林欄，與 DATA-01 原擬 status 欄不同；讀取時明確映射並保留原欄，不靜默改名或改寫原取得證據。
`official_imported` 及官方 remaining 仍以官方資料包計數；新模式另記 provider bundle／分期 acceptance，不把不同來源完成率相加。
本工作完成也不代表歷史資料未參與選參；2025 年後探索性標記及代理成交／交割限制繼續跟隨報告。
