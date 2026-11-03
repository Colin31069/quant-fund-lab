# M14：零股每日模擬、持久化與安全續跑

操作接續：已新增 `rebuild_registered_account` 及 UI 明確「保留原帳戶並重建至新路徑」。要求另一個不存在的目的路徑；原帳戶須完成結構／財務／來源及 snapshot prefix 核驗，候選設定與 origin 相符，重建途中 parent file／WAL 變動則回滾新帳戶當日。只讀 replay 不得 create 或 advance。兩環境 rebuild／UI／registered／replay 各 18 項、只讀／snapshot／audit 各 13 項通過；不自動修復受損或 forward 帳戶，不宣告完整發布矩陣已 accepted。

最新狀態：`in_progress`。L01–L07 的核心／持久化／稽核／來源守門／操作 UI 已有實作，下方「待實作」與人日數保留初始計畫。新增 durable 事件矩陣兩環境各 11 項通過：股利／反向分割／延後碎股款的手算、事件日 rollback、部分買單到期不補足、無報價止損退出重試、T+2 開盤資金限制及負賣款費用差額。證據見 `artifacts/acceptance/M14/durable-event-matrix/`；逐案仍按 scope 審查，不以測試總數宣告整案 accepted。

狀態：待實作；預定版本 `0.14.0`。預估 6–10 人日，分六個可驗證工作單元。
依賴 M13 已凍結的策略／執行協議與合格資料；前向營運不與實驗選參混用。

接續規劃（2026-10-29）：專用 package 尚未建立。離線 L01–L05 可用固定 fixture 推進，真實前向啟用才要求合格資料及固定觀察協議；原人日數保留為初始估算。本輪先細分 L01–L02，按下方歷史核心邊界交付，不一次搬動整個研究引擎。

## 目標與現況

現有一般 [PaperLedger](../../quant_fund_lab/paper_live.py) 已有日內 SQL 原子性、資料／設定指紋與獨立稽核；零股 [odd_lot_research.py](../../quant_fund_lab/odd_lot_research.py) 有自己的止損、當日到期委託及交割狀態。`study_ledger.sqlite` 是唯讀研究存檔，不能當成可續跑帳戶。

本版另建零股 ledger schema 與帳戶路徑，例如 `artifacts/odd_lot_paper/<account_id>/ledger.sqlite`；不對舊存檔推測性遷移。一般帳本如需共享小型元件，先抽出並用舊測試證明行為相同。

## 先定義的狀態與公開介面

建議建立 `src/quant_fund_lab/odd_lot_paper/`，拆 types/schema/session/replay/audit 並附 README；各程式檔不超過 300 行。

| 契約 | 必須持久保存的資訊 |
| --- | --- |
| `OddLotAccountConfig` | schema／execution／calendar revision、資金／貨幣、全部成本／限價／成交比例／交割／風險／策略假設與 protocol ID |
| `StopState` | symbol、entry basis、最高收盤、stop／trailing stop、退出中狀態、首次觸發日、未出清股數 |
| `DailyOrder` | 業務 ID、signal date、最早可成交日、side、requested／filled／remaining、limit、status、outcome；當日到期政策 |
| `TradeSettlement` | 買進應付／賣出應收／費用差額應付、trade date、amount、due session 或尚需 session 數、settled_at、狀態 |
| `OddLotCheckpoint` | session、前一 checkpoint、data／signal／config 指紋、snapshot linkage、日末狀態與完成標記 |
| `run_odd_lot_session()` | 一天的純狀態推進核心；歷史與 durable 路徑共用，避免維護兩套止損與交割計算 |
| `resume_odd_lot_account()` | 先驗證已完成 prefix、設定、快照與帳務，再處理新日；預設不得重建既有帳戶 |
| `audit_odd_lot_account()` | 從持久化業務資料獨立重建現金、持倉、應收應付與 NAV；只讀，不自動修差額 |

業務 ID 由帳戶／signal/session／symbol／事件種類等穩定鍵建立，重試不得產生重複交易。SQLite row ID 不作跨執行結果比較的唯一依據。

## 日內順序與資金不變量

1. 執行前先驗證資料品質、上次 checkpoint、prefix snapshot／訊號／設定及帳務；失敗時不建立當日帳務。
2. 以前收盤可支用現金計息，再依凍結規則處理到期 cash-in-lieu、拆股、股利與 terminal event。
3. 使用前一收盤已確定的目標／退出計畫，在次一 session 開盤撮合，先賣後買；普通交易價格與前期成交量仍是明列代理。
4. 沿用零股研究的 T+2 觀測 session 代理，買賣款在當日模擬開盤後處理；賣款不能於到期日開盤被提前支用。cash-in-lieu 的開盤前可用日契約與此不同，兩者不能混在同一結算階段。
5. 收盤估值、更新追蹤止損／退出重試及下一日計畫，保存 snapshot linkage 與完成標記，整個交易日一起 commit。

以上順序須先與現有歷史路徑逐項對照；若發現既有路徑有錯，另做具名修正與版本說明，不能在持久化時悄悄改語義。

NAV 的現有語義為：`可支用 cash + 持股市值 + 未收賣款 + cash-in-lieu 權利估值`。買款與費用差額應付已保留，不得再次從這個 NAV 扣除；帳面 settled cash 應等於 `可支用 cash + buy payables + sale payables`。尚未入帳權利不可當現金買股，股息仍依目前凍結的除息日代理處理。

資料尾端未知交割日保存尚需 session 數，不猜日曆日期；新資料抵達後按相同規則繼續。部分成交的買單剩餘量當日到期，不自動接續；退出中的賣單依後續收盤重新申報，持倉未清前不加碼。

## 執行工作包

| ID | 動作 | 交付／退出條件 |
| --- | --- | --- |
| L01 | 定義狀態、SQL schema、日內順序、獨立帳務等式與最小例題 | schema／公開介面先審查；舊帳戶拒絕誤用，新帳戶路徑獨立 |
| L02 | 從歷史零股迴圈抽出單日核心與可序列化狀態 | 原有 fixture 的訊號、orders/fills/settlements/NAV 與抽取前一致 |
| L03 | 實作 ledger、設定鎖、完成標記及日內 transaction | 當日任何步驟失敗可全數 rollback；重跑完成日是 no-op |
| L04 | 實作 snapshot／歷史指紋 preflight 與每日增量 | 新 delta 可由既有已驗證快照補足歷史；無法重建 prefix 時拒絕，不能猜訊號 |
| L05 | 實作只讀獨立稽核與故障注入驗證 | 篡改與重複入帳會被識別；一次完成與分段續跑相符 |
| L06 | 接入安全操作 UI 與前向觀察流程 | 既有帳戶預設 continue；重建是另一步明確操作；失敗不自動 reset |

SQLite 與外部 snapshot 不能組成單一交易；先寫不可變的 snapshot payload，再與當日 SQL checkpoint 鏈結。失敗日可能留孤兒檔，重試須檢查 hash／引用狀態；已提交 snapshot 不能覆寫，未引用檔列為隔離候選。

<a id="m14-core"></a>

## L01–L02：先固定歷史核心，再接資料庫

目前歷史迴圈以 `signal_date=dates[i]`、`execution_date=dates[i+1]` 成對處理；訊號計算先於次日利息／企業行動與撮合，再於開盤後處理 T+2，最後保存當日 NAV。再平衡使用 `(i-start_index) % rebalance_every`，不是每個續跑區段重新從零計算。
上方日內順序是概念規格；實作以這個已核對的歷史邊界為行為基線。若需把收盤計畫提前保存，須另定 transition revision 及對照，不在抽取時混入行為變更。

| 子單元 | 先交的契約／變更 | 具體退出條件 |
| --- | --- | --- |
| L01a | `OddLotSessionState`：cash／positions／成本、stops、pending、terminated、權利應收、未結算交易、passive_submitted、最後完成日與再平衡 origin／offset | 型別及完整 round-trip；零股股數、狀態／日期與 float 指紋不失真；未知值不填造 |
| L01b | `OddLotSessionInput`：前一收盤可見資料、當日價格／事件、歷史訊號窗口、前 20 日量、有效日曆／執行 revision；`OddLotSessionResult`：新狀態與業務事件 delta | 公開介面不依賴 SQLite／檔案；歷史只到 signal_date，不能把執行日全日量放入下單估量 |
| L01c | 固定手算 fixture 與抽取前基線；定義序列化、業務鍵及將來 SQL 表對照 | 訊號／orders／fills／actions／settlements／NAV 全量保存；fixture 及預期數字可獨立核對，不只比較共用同一核心的兩條路徑 |
| L02a | 抽出單次 `t 收盤 → t+1 收盤` 的純 transition，小步替換原迴圈呼叫 | 原歷史輸出與抽取前基線一致；不額外製作最後一日後的訊號／委託 |
| L02b | 單日結果串接與 checkpoint round-trip；以 session 餘數表示未知交割日期 | 任意合法日切分、序列化後接續與一次完成一致；不在每段重設 stop、再平衡起點或 ETF 首次委託旗標 |
| L02c | 全回歸、3.9 相容及只讀 blocked 真實資料守門 | 固定策略／基準／敏感度 fixture 通過；新程式身分另記，舊協議／報告不被重算或覆寫 |

初始 checkpoint 位於暖機完成且尚未執行第一個訊號的收盤；其後 checkpoint 位於當日 NAV 完成、下一次收盤訊號尚未計算的邊界。新增下一 session 時才由已凍結前一收盤輸入計算一次訊號，與下一日帳務一起推進。這可保留原歷史函式不產生尾端多餘訊號的行為。
明確保存前一收盤、完整模型所需歷史或其可驗證重建引用；不能假設模型只需一列價格，也不能用未來資料暖機。增量窗口不足時在 transition 前拒絕，不改變既有 origin。
進行中的交割保存 `remaining_sessions` 與 trade session，新增一日只推進一次；日內仍於開盤後結算。買款已保留、賣款與負賣款費用差額分別核對，NAV 不重扣。
Episode、診斷及績效由累積業務事件重建；不在每個分段重新起算持倉區間、已實現損益或樣本數。純 transition 回傳事件 delta，歷史及持久化組裝層沿用同一分析介面。

最小 fixture 集：滿額及部分買進／不補單、止損跳空／連續退出、同日股利拆股、碎股延後結算、T+2 尾端不足、賣款低於費用，以及 ETF 期初一次委託。每種至少選一個會切斷未結算或 pending 狀態的分段點；更改未來價格／量不能改變已完成 prefix。
L02 對照全部原始業務欄位與新增狀態，沿用下方浮點容忍度；不只比較最終 NAV。原研究 API 與一般 PaperLedger 回歸必須通過。L-A01／A04–A07 的核心範圍可先交證據，SQL 故障／續跑範圍等 L03–L05，不提前宣告整案 accepted。

建議在 `odd_lot_paper/` 新增 types／serialization／session／README；抽取前後每一步獨立 diff 及相關測試。L01a–c 完成前不新增可寫 SQLite 帳戶；L02c 通過後才進 L03 transaction，保持錯誤來源可定位。

## 驗收矩陣

| 案例 ID | 情境 | 通過標準 |
| --- | --- | --- |
| L-A01 | 同一 fixture 一次完成 vs 任意合法日切分續跑 | 全部業務 orders/fills/settlements/stops/NAV/checkpoints 一致，無多餘行 |
| L-A02 | 成交後／交割後／NAV 後／完成標記寫入前注入例外 | 當日 SQL 全 rollback；重開後可重試且結果與無故障相同 |
| L-A03 | 已完成日與完整輸入再次送入 | no-op；數量、現金、利息、事件、委託及完成標記不增加 |
| L-A04 | 部分成交、當日到期及退出重試 | 買進剩餘不自動補足；賣出重試有新日業務鍵，退出中不加碼，單筆不超過 999 股 |
| L-A05 | 賣出 T+2 與資料尾端不足兩日 | 當日開盤不能使用賣款；未知日期不猜測；後續 session 抵達只結算一次 |
| L-A06 | 止損、拆股／配息及延後 cash-in-lieu | 股數、成本、stop、權利估值與現金時點相符；不假觸發／提前結算 |
| L-A07 | 賣款小於費用、最低費與資金不足 | 費用差額保留應付，NAV 不雙扣；不得透支或提前用未收款買股 |
| L-A08 | 變更已完成日價格／volume／事件／訊號／benchmark | preflight 於當日寫入前拒絕，即使沒有新交易日亦拒絕 |
| L-A09 | 修改成本、成交比例、日曆／交割／風險／策略協議 | 既有帳戶拒絕混用，不能只靠相同 account path 沿用舊歷史 |
| L-A10 | snapshot 遺失／hash 改動／SQL linkage 被竄改 | 續跑拒絕；未引用孤兒檔不冒充已完成資料 |
| L-A11 | 直接竄改 cash、持倉、settlement、stop 或重複事件 | 獨立稽核指出業務問題；來源不足不能核對時明列失敗，不自動修復 |
| L-A12 | 建新／續跑／重建 UI 與不存在／舊 schema 帳戶 | 安全預設正確；失敗不退回 reset；舊研究／一般帳本不被改寫 |
| L-A13 | 固定協議的前向模擬以新行情更新 | 只增加未完成日，保留版本與資料來源；改參另建實驗／帳戶，歷史線不變 |

比較前按穩定業務鍵排序；數量、日期、狀態與指紋完全一致，cash／NAV 誤差使用 `1e-6 + 1e-12 * max(abs(a),abs(b))` TWD，stop 價格用 `atol=1e-8,rtol=1e-12`。同一核心計算的指紋精確一致，不能用浮點容忍度略過歷史指紋變動。

## 完成證據與前向觀察

交付 schema／日內順序文件、單日核心、SQLite 帳戶、snapshot linkage、獨立 audit、故障注入及 UI 測試。驗收紀錄含一次完成／分段／中斷恢復的業務表比較，以及舊一般帳本完整回歸。

前向觀察開始前凍結 protocol ID、account ID、資料取得時間與開始 session；每日產生完成標記及只讀稽核，缺資料時停在最後完整日並列修復項目。操作正確性先由上述測試驗收；策略有效性仍依累積樣本與事前規則評估，不能由系統能持續運作推論。

### 前向接續交付與契約

最新 L07c 接線：`source_archive.py` 已實作原始 inventory 的內容定址封存及唯讀核驗；`ForwardReplayBinding` 在 config 鎖 plan／來源根目錄／選源規則，逐日 observation 證據與 checkpoint 同 transaction。重建 raw archive 的期間 input prefix 另與 SQL 已提交指紋核對，不能以另一組仍合法來源替換當日資料。缺 archive、篡改重算 hash、交易內來源變更均拒絕；無自動修復。

`run_observation_account` 已接完整決策認證、候選設定／來源模式、未來開始日、新資料 readiness、source archive、shared replay 與 transaction sources recheck。回傳 pending／blocked／active；尾端缺資料只完成先前連續 ready prefix，不跳缺日。最初完整離線未來 session fixture 在 3.13／3.9 各 3 passed（261.71／294.24 秒）；後續 no-op／缺尾端及更嚴格 prefix 案例另驗證，不將此舊結果擴稱全部 L-A13。前向 UI、兩環境完整最新回歸及真實研究仍未通過。

執行更新：L07a 的註冊與認證、L07b 的 SessionEvidence／ForwardSessionAssessment／assess_forward_session 已有實作。重建官方／明確選源供應商原始資料，日曆、暖機、coverage 及逐日取得記錄共用現有守門；含較晚行情的資料包先截到指定 cutoff。這是來源記錄與內容的核對，非第三方可信時間戳；尚未建立前向帳戶。

L07c 接續先補不可變 raw-source archive，保留各完成日當時的 manifest／手動審核／原始 bytes；不能只留更新後的月檔或 normalized snapshot。帳戶 configuration 必須鎖 plan ID，取得證據與完成日同 SQL transaction 保存。續跑須核對舊來源 archive／snapshot／prefix，transaction 內重核當前來源與計畫。這些完成後才接 activate／continue 及前向 UI；下方最初「新 session evidence 尚未實作」保留為設計時點。

歷史帳戶路徑已有實作，前向路徑另拆以下單元。意向註冊不等於啟用，舊研究績效不併入前向期間。`ObservationPlan` 固定已核驗 v6 決策與執行身分、候選／策略／設定、實際登記時刻、未來開始日及歷史接觸註記；正式真實決策仍受資料阻擋。

| 單元 | 先固定的型別／公開介面 | 必要驗收 |
| --- | --- | --- |
| L07a 意向註冊 | ObservationPlan；register_forward_observation／load_observation_plan | 繼續決策才可註冊；當日／過去日期、過期實驗歷史、來源變更及篡改報告拒絕；不建 SQL 帳戶 |
| L07b 新資料守門 | 規劃 SessionEvidence：plan_id、session、acquired_at、source hashes、calendar ID、readiness fingerprint、snapshot ID；驗證函式先返回可核對的 ready／blocked 原因 | 取得時刻有可追溯依據，不能用檔案 mtime 冒充；實際交易日、所需暖機、價格／事件與 coverage 均就緒；缺日不跳過，未完成日不估造 |
| L07c 首日啟用與續跑 | 規劃 activate_observation／continue_observation；固定 plan／account／snapshot root，使用既有 shared session core 與 transaction audit | 只有核驗的新 session 才執行；首日不能早於註冊之未來日期；已完成 prefix 不變；改設定另開計畫，失敗不 reset；部分資料停在最後完整日 |
| L07d UI 與案例收斂 | pending／blocked／active 的唯讀狀態與顯式操作，共用後端守門 | 重繪無副作用，缺來源顯示修復項目；L-A13 有真實時間及來源證據，合成 fixture 只驗證操作正確性 |

新 session evidence 尚未實作，因此這一段是後續介面設計，不是已存在的 API。資料取得時點、研究決策、日曆與行情內容要分別核驗；只有價格日期落在未來，不能證明登記後取得或來源完整。驗收前不加入自動排程、不宣稱已開始前向觀察。
