# 先開發排名、再驗證的研究決策核心

`types.py` 定義 `DecisionPolicy`、有限 `CandidateBudget`、具名期間／情境證據及逐項 `DecisionCheck`。政策的驗證回撤、年化報酬、敏感度總報酬及回撤門檻必須明確輸入，沒有由結果推導的預設值。完成 episode 最少 30；達標不證明策略有效。建倉風險超額及止損延遲門檻可明確停用，啟用時必須有完整來源與已觀測退出資料。

`evaluate_research_decision(protocol_id, policy, budgets, evidence)` 是純計算介面：

1. 列出有限預算中每個 candidate 的 ensemble／momentum，不允許外來或重複候選、情境。缺少開發證據會保留全部候選列並回傳 `incomplete_search`，不從已到齊的部分先挑。
2. 只用開發期目標與已完成 episode 判斷可排名資格。已知樣本不足為不合格，缺少分數或 Calmar／Sharpe 的必要分母為 unavailable，不用零值替代。依目標降冪、candidate ID 及 strategy 升冪解同分。
3. 開發排名只選一次。後續驗證差、資料不足或成本情境失敗，都不改選另一候選；其他可排名者保留 `not_selected` 與原因。
4. `validation.py` 檢查已選候選的驗證樣本／報酬／回撤、同成本 ETF、全部預定敏感度及啟用的風險門檻。ETF 是被動基準，不要求 30 次已完成交易；仍須有可用的同成本報酬來源。
5. 每個門檻保留 passed／failed／unavailable／insufficient_sample、觀測值與界限。缺資料不掩蓋已知不利結果；彙總優先順序為 unavailable → insufficient_sample → return → continue。

`continue` 指繼續研究／觀察，`return` 指未通過預定門檻；兩者都不是實盤建議。尚未退出的止損不算完成觀測，啟用風險門檻時列樣本／觀測不足。風險預算來源不完整則 unavailable。敏感度是 validation 的診斷與拒絕條件，不是選參資料。

輸出包含政策、全部候選、逐項檢查、輸入證據指紋及確定性的 decision ID。候選與證據輸入順序不改變開發排名或決策身分；協議宣告的情境預算順序仍保留。指紋保留所有輸入證據，不能只刪不利來源。

## 目前邊界與接續接線

此節保留純核心交付時的邊界；後續 v5／登記來源／報告接線見下方更新，實際驗證結果以 EXECUTION_STATUS 為準。

目前僅完成純計算核心，沒有啟動真實候選選擇。呼叫方提供的 `protocol_id` 與 `source_fingerprint` 在此只驗證格式，不能當作來源已認證、協議已凍結或未見資料證明。既有 v1–v4 協議依然宣告沒有自動候選選擇。

R07 後續還需：把政策及期間用途凍結到新協議、從 registry 的全部宣告候選與有效報告重建證據、核對 code／資料／attempt lineage、輸出可重建的決策報告，再接安全 UI。實際策略排序必須等待這些接線；不能直接把 UI 字典交給純核心便宣稱完成研究驗收。

`tests/test_odd_lot_decisions.py` 涵蓋開發／驗證分離、未通過不改選、固定平手、缺候選、樣本不足、無分母指標、失敗／缺失情境、已知拒絕與未知同時揭露、未退出及缺風險證據、ETF 不需已平倉樣本、邊界與非法輸入。測試證據是離線構造，不代表真實研究通過。

## v5 接線更新

`protocol_from_studies(..., decision_policy=DecisionPolicy(...), benchmark_spec=..., risk_diagnostics=True, matched_sensitivity=True)` 明確建立 v5 分析協議。必須有順序正確的 `development_selection` 與 `validation_check` 期間，政策目標／最少交易數與 SelectionRule 一致。結構化政策控制執行，既有自由文字只是說明；v1–v4 不自動新增選擇。2025 年後已接觸的探索期不能借用 validation 名稱參與判斷。

`registry_evidence.collect_decision_inputs()` 預設讀取所有宣告候選的完整最新 attempt 歷史，不退回較早成功。每一份已登記報告均核對協議、實驗、attempt、數值指紋與 manifest；報告路徑限於該 frozen study 的 reports 目錄。主要帳戶還核對 SQLite 鎖定設定與 study／dataset，從 equity／episodes／診斷來源重建績效與樣本；comparison 值不能與實際 NAV 矛盾。敏感度從已核對的完整情境與來源 CSV 重建。失敗情境不影響開發排名資料的用途，但被選候選仍須接受全部驗證門檻；無報告或 nonreproducible failure 不可借較早結果提升資格。

同一 scenario ID 的必要策略／ETF 對照若有執行失敗或受阻，該 matched 情境不能用其中成功的一列宣稱完整。adapter 保留開發排名依據，將必要對照不完整列為驗證來源不足；原始研究報告仍保留各列績效與錯誤，成功重試可提供新證據且舊失敗保留。

`workflow.build_registered_decision()` 回傳決策與完整來源證據。`workflow.export_registered_decision()` 要求實際程式／環境身分與協議一致，重核來源未變，再原子發布新目錄。JSON 保存政策、所有候選證據、完整 attempt 前綴與結果；CSV／HTML 列逐項檢查及失敗／受阻紀錄，全部進 hash manifest。這個操作不執行候選研究，也不修改 registry；候選仍透過既有 registered runner 執行。

`workflow.verify_registered_decision_report()` 需要明確 registry／studies 路徑，從來源重新建立政策決策，不信任單獨修改的 decision JSON 或 CSV。每份報告保留確切 attempt 歷史前綴；後來新增嘗試或 running 轉為 terminal 不改寫舊決策。前綴 replay 證明已保存的內容與生命周期，不能證明外部認證時間或「目前仍是最新結果」；新的評估總是重新捕捉最新完整歷史。報告引用來源不複製全部研究資料，有引用的原始 study／registry 遺失或篡改時驗證會失敗。

`tests/test_registered_decisions.py` 使用實際離線帳戶測試完整候選、缺候選、樣本不足、running／failed 最新嘗試、歷史報告、設定／指標／attempt 篡改與相同來源重建。正向 fixture 使用刻意寬鬆的測試政策與人工目標，只證明流程可執行，不作策略效果證據。安全 UI、完整矩陣及真實資料驗收仍獨立待交付。

目前來源收集已實作完整快照，但尚未拆成「先保存僅開發來源的 DevelopmentSelection，再讀驗證」；純核心的排名不使用 validation，整份 evidence fingerprint 仍綁定全部證據。後續須依 M13_DECISION_UI 的 J-A02 補獨立 selection 產物與分階段 adapter，不能把現有 decision ID 當成 development-only fingerprint。

## 開發專用選擇型別與純核心

`development_types.py` 定義 `DevelopmentPolicy`／`DevelopmentEvidence`／`DevelopmentRank`，`development.py` 定義不可變 `DevelopmentSelection(policy, candidate_ids, evidence)`。公開型別從 package 匯出；此更新不替換既有 v5 collector 或舊決策序列化。

`DevelopmentPolicy.from_decision_policy(..., start=..., end=...)` 只投影開發日期、objective、最少完成 episode 與平手規則；驗證／敏感度／風險門檻不進入開發政策。`DevelopmentEvidence` 僅接受開發期指標及開發來源 fingerprint，不接受 validation 或探索欄位。source fingerprint 在純核心仍只驗證 SHA-256 格式，後續 adapter 必須證明其開發依賴，不能直接傳入既有全結果 proof。

`DevelopmentSelection` 正規化候選及證據順序，保留每個 candidate × ensemble／momentum 的資格、分數、原因及排名。缺任一必要證據會保持 incomplete_search／無選擇；仍列出的 rank 是暫定排名，不能當成選定結果。全數已知少樣本為 insufficient_sample；完整可用才是 selected，這個狀態不表示驗證通過。

`to_dict()` 是 schema 1／`development_selection_v1` 的 canonical 語義內容，`selection_id` 是該內容指紋；不含 protocol／完整 policy／attempt／時間／路徑／報告 manifest。追溯資訊待放獨立 SelectionCapture。`from_dict()` 重新計算全部排名與唯一選擇，拒絕不一致的衍生結果、未知欄位或版本；外層 hash 重算不能覆蓋此檢查。它不認證來源資料，也尚未證明已落盤。

`tests/test_development_selection.py` 驗證序列化重建、固定平手、缺候選／29–30／無分母、輸入順序、非法值、validation 政策排除、開發依賴變動與舊核心排名對照。這是 J02a 的純核心範圍；真實來源切片不變性、先保存再讀驗證及新協議規則仍屬 J02b／J03，不能據此標 J-A02 整案通過。

## 開發來源收集：獨立唯讀分析

`development_registry.collect_registered_development(protocol_directory, registry_path=..., studies_directory=..., snapshot=None)` 回傳 typed `DevelopmentInputs(sources, selection)`。它接受已有 v5 政策／研究來源作獨立開發分析，明列 `development_accounts_from_latest_prefix_v1`；不替換舊 v5 workflow、不寫 registry、不發布最終決策，也尚未保存 SelectionCapture。正式兩階段 workflow 必須另凍結收集規則及產物版本。

`development_report.py` 將報告完整 bytes／manifest／protocol／attempt／assumptions 綁定核對，與業務內容解析分開。完整凍結市場輸入及 readiness 仍由既有 loader 從 raw 重建認證；非開發報告 CSV／JSON 僅作不透明 bytes hash，不呼叫全報告 verifier，避免它提前解析 validation 診斷。這不宣稱過去或其他程式從未讀過那些資料。

開發依賴指紋只使用該期必要暖機及期間的市場資料；按歷史 runner 相同規則從 raw 重建區間總報酬、open／reference，避免把全資料調整序列混入。保存適用的暖機 sessions／verified、readiness 狀態及語義問題、研究／執行設定、歷史 engine 身分及來源規則。完整 dataset／study／protocol ID、跨期 raw 檔案 hash、全域 calendar revision、報告 manifest／attempt 時間均留在完整來源鏈結，不進 selection ID。此指紋綁定經認證的開發資料語義；完整原檔及來源取得稽核仍依 captured protocol／study／report inventory 核對。

`development_accounts.py` 只解析兩個主動策略的 development 八類帳務，核對 SQLite 的同一帳戶設定與業務列、日期／資金，再重建 episode 診斷與績效；不讀 comparison、validation／探索／scenario 帳務或彙總。CSV 與 SQL 僅日期的儲存表示作正規化，數值不以寬鬆容忍度掩蓋差異。缺開發檔案列 unavailable；來源不符拒絕收集，不能藉 rehash CSV 或修改 SQL 摘要提升排名。所有來源與帳務被一致改寫的外部真實性不在本機核驗能力內。

收集保留完整 attempts 前綴與報告 manifest；最新 running／無報告失敗不借舊成功。具有可核驗開發帳戶的 validation 情境失敗仍保留開發選擇，不由驗證結果反向排名。新收集規則會阻擋 captured history 中任何未解 nonreproducible 紀錄，即使後來一次重試相符也不抹除已觀察的矛盾；須另行調查／新協議，不改舊 v5 reader 的歷史語義。結束前再重建凍結輸入與 inventory；registry／報告或 protocol 變動拒絕回傳，歷史 snapshot replay 保留當時結果。

`tests/test_development_sources.py` 用實際官方格式離線原始資料及真實帳戶，驗證僅未來行情變動時完整結果 ID 改變但開發選擇 bytes／ID 不變、必要暖機變動會改指紋、解析 spy 未讀其他期、CSV／SQL／設定／context／路徑篡改、完整預算與 prefix replay、必要驗證對照失敗後重試、nonreproducible 歷史、收集中 registry／bytes 競態與 symlink 拒絕。後續 J03 仍要證明 selection 真正落盤先於驗證解析；這個 collector 本身不證明保存順序或最終決策合格。

### 不可變選擇捕捉

`selection_capture.export_development_selection(..., output_directory=..., source_directory=...)` 先檢查實際程式／環境與 protocol 一致，收集 development，再寫 `protocol.json`、`development_selection.json`、`sources.json`、`selection_context.json` 及 `selection_manifest.json`。暫存包經來源重建，重核最新 registry／資料／execution 未變後，以原子 rename 發布至 `<output>/<protocol_id>/selections/<selection_id>/<uuid>/`。不讀 validation 業務內容，不產生最終採用判斷。

`load_development_selection(..., registry_path=..., studies_directory=...)` 回傳 `SavedDevelopmentSelection(directory, inputs, capture_fingerprint)`，重建保存的歷史前綴；source inventory、完整政策 fingerprint、protocol execution 與 schema 另綁 capture，selection ID 維持只含開發語義。同業務結果重跑保留不同 capture；後來新增 attempts 不改寫舊 missing／running 或成功快照。來源遺失／篡改、未知欄位、重算 hash 的選擇／context／source 變造均拒絕。capture 時間是本機紀錄，沒有外部簽章。

目前這是現有 v5 報告的明確獨立開發分析與保存；不改舊 v5 workflow，不宣稱原 batch runner 是先開發後驗證。第二階段 workflow／新版協議仍待接線，須接受並核驗已保存 capture 的路徑，不能以記憶體字典取代，也不能重新選第二名；該流程完成前不標 J03 或 J-A02 全案通過。`tests/test_selection_capture.py` 覆蓋不可變路徑、相同選擇／不同捕捉、prefix 保留、篡改重建拒絕、錯 checkout 與發布前 registry 競態。

## V6 分階段分析與最終決策包

上節「第二階段待接線」保留前輪範圍。現在 `protocol_from_studies(..., phased_decisions=True, decision_policy=..., benchmark_spec=..., risk_diagnostics=True, matched_sensitivity=True)` 明列 v6 收集／保存／選擇規則；省略該 flag 的舊 v5 身分與讀取分支維持。所有門檻仍須顯式凍結，沒有新增正式策略預設值。

順序為 `export_development_selection()` → `phased_evaluation.evaluate_saved_selection(saved_path, ...)` 或 `phased_reporting.export_phased_decision(saved_path, ...)`。第二階段首先從磁碟 capture 重建來源、政策與全部開發排名，之後才核驗選定候選的完整報告並讀取固定策略的 validation／同成本 ETF／必要情境證據。必要 matched 對照及報告語義仍完整核驗，不信任摘要。沒有開發選擇時不呼叫 validation reader，保持 incomplete_search 或 insufficient_sample。

`selected_evaluation.evaluate_selected_development()` 不重新排名：它核對 frozen budget、開發政策與已保存選擇，拒絕不同候選／策略的驗證證據，以及與保存開發值矛盾的來源。驗證拒絕、少樣本或未知項仍列在原選擇；其他適格列明確 not_selected。純 evaluator 不驗證磁碟或來源，正式操作只由 saved-path workflow 進入。舊 `build_registered_decision()`／collector 明確拒絕 v6，不能沿舊入口先收集全證據再排名。

`export_phased_decision()` 要求執行 checkout／環境與協議一致；發布前重核當前完整來源仍等於保存前綴。輸出 `<output>/<protocol_id>/<decision_id>/<uuid>/`，含 protocol、context、selection_reference、development_selection、sources、固定候選 evidence、decision JSON、全部開發候選／門檻 CSV、HTML、完整 `selection/` 捕捉副本及 schema-2 manifest。同一業務結果保留相同 decision ID，不同捕捉 audit 各自保留；輸出不覆寫 selection，也不啟動候選研究。

`verify_phased_decision_report()` 重播包內原始 selection 前綴，再從來源核對固定驗證及 JSON／CSV／HTML；重算 hash 後竄改選擇、決策或 capture 參照仍拒絕。後續新增 attempt 不改寫舊報告；舊 capture 可以歷史讀回，但不能在最新 registry 已改變時發布為當前決策。第二階段例外不刪除原先 selection capture；失敗不會自動改選、重跑或 reset。

候選研究仍是完整 batch，分階段的是結果分析；既有歷史結果已存在，保存順序與本機時間不構成未見資料或外部預註冊證明。完整 J02–J05／UI／研究有效性與真實資料驗收仍按各自案例核對。

`tests/test_selected_evaluation.py` 驗證固定選擇不補位及已知失敗／未知項並存；`tests/test_phased_decisions.py` 用真實離線帳戶驗證落盤先於第一個 validation 核驗、全預算選擇、實際 return／continue／少樣本／缺候選、例外保留、過期 capture 拒絕當前發布、語義篡改及舊協議分支。這些 fixture 門檻刻意寬鬆，僅驗工程，不作策略採用依據。

## 研究瀏覽與明確操作 UI

主介面側欄的「零股研究協議與決策瀏覽」進入獨立面板；大型 ui.py 只接小型入口。`inspection.py` 的 typed ResearchOverview／SavedDecisionView 將核驗與呈現分開：協議須與唯讀 registry 一致，全宣告候選（含未嘗試）及全部 failed／blocked／running 歷史保留。保存 selection／schema-1 或 schema-2 決策使用既有來源重建器；失敗不回傳可展示的績效，外來協議拒絕。

預設只讀。表單送出「核驗並瀏覽研究」才讀取，重繪不跑研究、不建立 DB／attempt／報告。保存決策明列自己的前綴，不冒充最新；舊協議無政策時不套預設門檻。凍結 runtime／依賴及分析規則可展開查看；目前 profile 不同會提示使用匹配環境，來源核驗失敗會直接顯示停止原因，不切換環境或放寬品質守門。

「顯示凍結／執行操作」預設關閉。開啟後仍須按各自表單的送出按鈕：

- 「凍結新政策子協議」要求完整 DecisionPolicy JSON，連停用的 optional gate 都須明列；以父協議的資料、有限候選、期間用途及已接觸歷史建立新 v6 子協議，不覆寫父協議，不啟動搜尋。父協議必須已有明確可交易基準；指定新協議根目錄須可核驗父協議。
- 「執行已凍結候選」只傳入下拉選單中的凍結候選與既有 registered runner，保留失敗／受阻／重試；沒有由畫面重繪觸發的自動重試。
- 「保存開發選擇並產生決策」只接受 v6，沿先保存 selection 再固定驗證的後端。驗證例外保留已保存 selection，不改選、不重跑或 reset。

`actions.py` 隔離這些明確寫入動作；`ui.py`／`ui_actions.py` 處理呈現與表單，不另定排名／readiness／驗證政策。改參建立新協議；資料或程式身分不同仍由後端拒絕。頁面上的核驗成功指保存產物完整性，不代表資料已 ready 或策略有效。

`tests/test_research_browser.py` 用 AppTest 檢查候選／失敗與受阻歷史、舊無政策、保存選擇與決策、少樣本、continue／return、壞來源、缺 registry、profile 差異與主入口；讀取與重繪前後逐檔 hash／attempt 數維持。`tests/test_research_actions.py` 檢查完整政策、不可變子協議及原候選預算、明確按鈕與重繪不重送／失敗不重試。完整 J-A10／J05 仍依實際 scope review 與來源／環境證據結案。


### 舊版決策讀取的唯讀邊界

`collect_decision_inputs()` 與 v6 開發 collector 一樣使用
`ReadOnlyExperimentRegistry`，只讀既有 schema，不初始化、遷移或修復來源 DB。
空檔、其他用途 SQLite 與未知 schema 拒絕，原 bytes 及 sidecar inventory 不變；
合法失敗嘗試仍按原 history 語義收集。反例與正常路徑見
`tests/test_registry_read.py`；不變更舊決策包內容或 schema。


### 全候選失敗的保存與 UI 驗收

`tests/test_phased_decision_edges.py` 以兩個實際登記候選、各兩次失敗嘗試，
分別走 schema-1／v5 及 schema-2／v6 匯出與來源讀回。所有原因保留，開發分數
與排名不可用，不選部分最優；v6 無選擇時不得解析 validation。相同來源重發
的 decision ID 相同、目錄不同、舊 bytes 保留；研究 UI 顯示兩候選與四次失敗，
重繪／重新讀取均不新增 attempt 或改寫檔案。兩環境各 2 項通過。

`tests/test_phased_future_inputs.py` 另準備真實離線帳戶的 v6 未來行情變更案例，
含保存開發選擇時不解析其他期的 spy，以及固定選擇後的驗證／報告讀回。
此案例目前只完成程式準備及 Lint，尚未執行，不算 J-A02 通過；較重的執行
等待前一輪完整回歸終局。證據及固定來源在
`artifacts/acceptance/M13/j05-consolidation/`。


J05 後續執行更新：上述「未執行」是準備時檢查點。305 檔固定快照的
v6 future-input＋兩種全失敗包 target 已在 3.13／3.9 各 3 passed，Lint 通過；
同一 reader 在匹配 runtime 核驗 25 個實際歷史產物、1031 檔 bytes 保留。
完整證據在 j05-consolidation/；後加停牌政策的 306 檔完整整合回歸另追
session 60767，不把舊 target 結果延用到後來程式，也不解除真實資料阻擋。
