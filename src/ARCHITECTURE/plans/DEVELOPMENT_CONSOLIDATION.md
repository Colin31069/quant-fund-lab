# 發展收斂與下一階段交付

目前接續以[目前交付計畫](CURRENT_DELIVERY.md)為準（2026-10-29），包含較晚來源診斷的驗證範圍、23 筆 active coverage 與認購權模型退出條件；以下記錄保留歷史。


接續實際進度（2026-10-29）：先前 UI 逾時已在後一固定快照的兩環境完整各737項成功中收斂；v6實際未來行情不改保存開發選擇的整合各3項通過，匹配profile的25個舊包可讀。後加修復摘要與v2停牌選源已合入306檔新快照，session60767正驗完整兩環境，尚未放行發布。較新真實study c4de77c3feb3999aba0935f5阻擋為39／34／36；下方本輪基線與起始失敗保留原時點，不能當作最新終局。

更新：2026-10-29（Asia/Taipei）。版本維持 `0.12.3`。本輪為規劃與既有證據核對，未重新執行完整回歸或放行任何里程碑。
本文件為目前排程入口；各原計畫保留介面及案例契約，歷史估算不當作剩餘工期。

E05/session接續：既有run_odd_lot_session已在回傳前核對由實際events／fills／settlement重算的usable cash與持股；相關兩環境各129項通過，合法結果schema不變。這只完成真實session交接核驗，下一步仍是rights flow與現有持倉／stop／交割的同步、來源adapter及versioned SQL，不以此當作完整rights接線。詳見[執行紀錄](EXECUTION_STATUS.md)。

E05持倉連接接續：單一cash、實際lot、延後tradability、grant時持股basis、pending與delivered分開NAV及精確checkpoint連接已實作；連同核心／獨立稽核兩環境各90項通過。接續是既有session的交易／交割／stop整合與版本化SQL、真實來源，不把這個純邊界當作現有回測／帳本已完成接線。詳見[README](../../quant_fund_lab/odd_lot_rights/README.md)及[執行紀錄](EXECUTION_STATUS.md)。

E05 稽核接續：純認購權原命令已有獨立現金／數量／費用與inventory debit-credit重建，含既有純核心共兩環境各62項通過。外部initial cash與目前憑證持倉、source／market NAV仍需各自認證；session／SQL與實際事件接線待續。先前「獨立稽核尚待建立」僅保留舊狀態，剩餘應是外層整合，詳見[核心README](../../quant_fund_lab/odd_lot_rights/README.md)。

E05 工程接續（2026-10-30）：認購權分階段型別、不可變純帳務／估值／checkpoint 已有實作，假設案例兩環境各45項通過。接續工作是來源認證與參與／估值規則、session／持倉／現金及版本化 SQL／獨立稽核；不再將純核心排為從零開發，也不將其通過當作真實事件已 ready。具體邊界見[核心 README](../../quant_fund_lab/odd_lot_rights/README.md)及[執行紀錄](EXECUTION_STATUS.md)。

最新資料／規則接續：除權息逐筆對照與 0050 實際分割 coverage 已另建不可變資料；明確 opt-in 的 `reviewed_provider_v2` 只接受與官方個股停牌相符且無成交活動的 no-quote，舊 v1 預設與封存不變。新 v2 study `195e874e86026da7a9209f95` 三期 **28／23／23**、raw issues 27，全部 blocked。相關兩環境各 35 項通過，較晚 v2 不在舊雙環境各 733 項 inventory；後續統一工程來源時須納入。剩餘 coverage／認購權及完整發布仍未 accepted，詳見[最新執行紀錄](EXECUTION_STATUS.md)。

最新接續：原 292 檔固定 inventory 的雙環境完整一鍵驗證各 **733 passed** 已終局，較晚 coverage／新增案例另驗；發布尚未 accepted。第二批分類覆蓋另建 study `c4de77c3feb3999aba0935f5`，三期 findings **39／34／36**、raw issues 40，仍全部 blocked／績效空白。已交付範圍、未解類別與歷史基線見[執行紀錄](EXECUTION_STATUS.md)及[企業行動調查](EVENT_INVESTIGATION.md)。下方 50／55／56 是首批 study 的檢查點。

資料接續（2026-10-29）：CoverageReview 不可變發布與開發期減資類別審核已交付，相關兩環境各 27 項通過。新 study `b9b633c190f914bf72b53d05` 的三期阻擋為 **50／55／56**，仍全部 blocked；61／55／56 屬下方舊 study。C 交付包下一步接其餘類別與較晚年度，不能把 44 筆年度審核或 11 個開發期阻擋解除當作全部 coverage 完成。證據與來源範圍見[資料調查](EVENT_INVESTIGATION.md)。

## 接續核對與近期三個交付包

以下為接續盤點，優先於下方較早檢查點；沒有將執行中的回歸標為通過。

- 原 UI 逾時案例在原快照、原 30 秒限制下單獨重跑為 1 passed（3.63 秒）；完整 suite 的原失敗保留，根因仍未確認。真實 native-profile blocked 決策已完成唯讀瀏覽，重繪沒有新增 attempt。
- 舊 schema-1 collector 已修正為唯讀 registry；空檔與不相容 DB 拒絕且不改 bytes，兩環境各 10 項相關測試通過。其後的 **296 檔整合快照**由原 session **26804** 循序執行 3.13／3.9；目前紀錄仍為 running。以 `artifacts/acceptance/release/consolidation-20261029/` 的 inventory、logs 與 acceptance 為準。
- 較早 292 檔 M14 快照仍有自己的完整回歸程序；不同快照的成功不可拼成同一發布基線。durable events／settlements 新增全部 7 個 fixture 合法切點後，相關兩環境各 14 passed（19.13／24.32 秒），這次測試延伸另有來源範圍。
- 富邦權利事件已有新增官方文件事實表 `artifacts/acceptance/M12-5/fubon-underwriting/exchange-facts-review.json`；最終發行人付款通知、逐腿資格／交付與資訊時點仍需核對。取得文件不等於事件模型或 coverage 通過。

| 近期交付包 | 可立即執行的最小單元 | 交付物與退出條件 | 相依與後續 |
| --- | --- | --- | --- |
| A：工程整合結案 | 續追既有整合程序；逐檔比較固定 inventory 與預定發布來源；將後加變更列差異 | 同一來源的雙環境終局結果、失敗診斷、環境操作說明；必要 UI 案例通過。若有較晚程式變更，另凍結驗證，不能借用舊結果 | 不需等待真實資料；通過後才進工程發布審查 |
| B：J05／M14 案例結案 | 先逐列核對 J-A01–A11、L-A01–A13 的 assertion 與已保存 logs；只為缺口補最小案例 | 每列有命令、環境、來源身分、結果與剩餘缺口；區分 core／adapter／SQL／UI／真實資料範圍，缺任一必要範圍不 accepted | 證據整理可在 A 運算時進行；新增程式或測試須回到 A 核對來源差異 |
| C：開發期資料放行準備 | 先將 55 筆 coverage 按期間、標的與五類事件分組；兩個權利事件逐欄列已證實／未知及對應原始文件 | 可逐筆核驗的審核表與兩份事件事實表；如需新帳務能力，先交型別／介面及手算規格，再實作。不得用預定日期或其他股東類別規則補未知 | 不阻擋 fixture 工程；阻擋相依正式研究與實際前向啟用 |

下一個執行動作是 **A 的既有程序結果收斂＋B 的缺案盤點**；已有相關測試證據先複用，不重做已交付功能。C 持續按開發期及暖機優先調查。近期排程以交付退出條件估量，不承諾外部文件取得日或策略有效日。

工程發布候選包至少包含：來源 inventory／封存、雙環境完整 logs、80 案索引及逐案審查、操作與限制說明。資料放行後另交新衍生來源／study／協議／決策包；前向觀察再記實際註冊與合格新 session。三種交付各有自己的完成紀錄。

## 本輪核對後的基線

- R07 已有 v6 保存開發選擇、固定候選驗證、schema-2 決策包及研究 UI；接續 J05 案例收斂。
- M14 已有單日核心、SQL 原子性、來源封存、獨立稽核、歷史／前向虛擬帳戶 UI，以及保留原帳戶的歷史重建；接續 L-A01–A13 完整審查。
- 研究 UI 固定快照的 Python 3.13 完整回歸已終局：**703 passed、1 failed、16 warnings，1858.70 秒**。失敗為 `test_provider_study_ui_uses_shared_ready_or_blocked_decision[True]`，AppTest 超過既定 30 秒；原因尚待定位，不能直接認定只是負載。
- 這份結果只涵蓋 `/private/tmp/qfl-research-ui-20261029-b` 的 289 檔快照。較早 v6 雙環境各 629 passed、較晚 M14 局部成功，各保留自己的來源範圍。
- 最新真實研究 `23bb603a256b04cb87f472b3` 三期 findings 為 **61／55／56**，全部 blocked。2317 停牌個案已修訂；剩餘包含 55 筆 coverage 與兩個權利事件，正式績效仍不可用。
- 同一真實封存跨 3.13／3.9 profile 曾因日曆重建差異被拒絕；完整 fixture suite 成功不能替代封存可攜性驗收。

依據：[執行紀錄](EXECUTION_STATUS.md)、[資料調查](EVENT_INVESTIGATION.md)、`artifacts/acceptance/M13/research-ui/full313.log` 與 `artifacts/acceptance/B01/readiness-source-review-20261029/acceptance.json`。

## 交付順序與完成條件

| 順序／既有工作 | 下一個可審查產物 | 驗收與停止條件 |
| --- | --- | --- |
| 1：B01／B02，整合基線 | 最新來源 inventory、既有失敗診斷、兩環境回歸紀錄及環境操作說明 | 先在原快照單獨重現逾時案例，記錄冷／暖執行與耗時；若有缺陷則小步修復。完成後固定涵蓋所有預定發布變更的新快照，依序跑 3.13、3.9 的 Lint＋完整 suite；必要 UI 操作另驗。保留初次失敗，不 skip 或直接加長 timeout 作為完成條件 |
| 2：R07 J04／J05，研究程序結案 | J-A01–A11 逐案證據、真實匹配環境的唯讀瀏覽紀錄 | 核對 continue／return／少樣本／受阻、來源篡改、過期 capture、全部失敗、舊包及重繪不寫入；缺例補最小測試。UI 與後端同判定；相容性邊界須可見 |
| 3：M14，操作驗收 | L-A01–A13 矩陣、帳務手算與故障恢復／重建紀錄 | 一次完成與分段、SQL 故障重試、交割／權利款、缺尾端資料、來源替換、no-op、歷史新路徑重建均可核對。原帳戶 bytes 保留；forward 不自動當作 historical 重建；離線模擬未來日明列 fixture |
| 同期：B06／M12-5，真實資料 | 開發期及暖機的逐標的／五類 coverage 表、兩個權利事件事實表 | 來源 URL／原始 bytes／hash、審核範圍及未解欄位齊備；無依據不填無事件聲明。先驗收開發期，再驗證期，最後歷史探索期；每輪另建衍生資料及 study |
| 4：B07／M13，重凍結研究 | 最新資料的子協議、有限候選執行與決策包 | 資料有變即新身分；對應期間 readiness 通過才能產生有效績效。先保存開發選擇再驗證，失敗不補位；2025 年後維持已接觸歷史探索用途 |
| 5：M14 L-A13，實際前向觀察 | 可核驗決策所登記的 plan、未來開始日、逐日取得與帳務證據 | 只有有效 continue 決策才可註冊；新 session 通過收盤後取得時間、暖機、日曆及事件守門才啟用獨立虛擬帳戶。未達標維持 pending／blocked，不以歷史重播累積前向樣本 |

步驟 2、3 的證據整理可穿插於步驟 1 等待時進行；同機完整 suite 循序執行。步驟 4、5 依賴真實資料與決策，工程交付日不作其完成日承諾。

## 每個交付的最小切分

1. **B01／B02**：先保存失敗摘要與來源範圍；單案例定位；修復若有；統一最新快照；雙環境完整驗證；核對預設 `.venv` 異常與明確 interpreter 操作入口。跨 profile 日曆差異另查官方依據；目前用匹配凍結 profile 核驗，不隱藏新增 findings。
2. **J05**：逐列審查 `case-review.json`，把測試節點、實際 assertion、來源 hash 與執行結果連接；先補未覆蓋案例，再做真實 blocked 決策瀏覽，最後核對所有 UI 表單重繪無副作用。唯讀舊 schema-1 路徑需確認不會初始化 DB。
3. **M14**：先整併已存在的 durable events／settlements／read-only rebuild 證據，再補尚缺組合；每輪只改一個語義單元。既有真實決策＋模擬未來日案例可以驗工程，不當作實際前向執行。
4. **B06**：coverage 按標的及期間拆小單元；權利事件先固定每腿種類／對象／數量／成本／付款／憑證與股票交付／可交易日／資訊時點，未知逐項保留。若確認需要新模型，先定型別與介面，再以資金不足、多腿、延後交付的手算驗證歷史與 durable 路徑。

初始規劃的首個執行單元為原快照逾時案例定位與 B01 證據收斂；單案重跑與唯讀修正已有上述進度，接續以近期交付包 A／B 為準。本次規劃不啟動新的長時間完整 suite，以免與既有驗證重疊；實作輪先核對仍存活的程序及其來源範圍。

## 發布切點與交接規則

| 放行層次 | 必要證據 | 本輪狀態 |
| --- | --- | --- |
| 工程發布 | 同一最終來源 inventory 的雙環境 Lint／完整 suite、必要 UI 與案例逐項審查，差異逐檔核對 | 尚未通過；存在完整 suite 失敗及未結案例 |
| 正式歷史研究 | 對應期間資料 ready、協議／來源／全嘗試可重建、樣本與用途揭露完整 | 尚未通過；三期 blocked |
| 實際前向觀察 | 有效 continue 決策、事前註冊與合格新 session、逐日不可變來源及獨立帳務稽核 | 尚未通過；離線 fixture 不代替實際觀察 |

P0／Q／S／E／R／J／L 共 80 個案例保留原 ID。每列至少記 `case_id / scope / test_or_source / command / environment / source_identity / result / remaining_gap`；passed 與 milestone accepted 分開。總通過數不替代逐案審查。

驗證入口使用明確的 `QFL_PYTHON` 與 `./scripts/verify.sh -q`；來源身分敏感測試採保留 Git index 的固定快照，後續源碼變更不能沿用舊 suite 結果。每個實作單元先 Lint／相關單測，整合及發布跑完整雙環境閘門。修改前先固定型別與公開介面，保留註解與 docstring；新增程式檔超過 300 行即拆分。

通過工程與真實研究閘門後，才評估新策略／市場或部署。下一輪重估以實際缺案及權利模型範圍為基礎，不沿用從零開發的初始人日估算；外部證據等待與前向樣本累積分列。
