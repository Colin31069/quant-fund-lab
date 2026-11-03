# R07：候選判斷、來源核驗與研究 UI

接續工程（v6）：已接通明列分階段規則的新協議、引用已保存 capture 的固定候選驗證，以及含 selection 副本的 schema-2 決策包／讀回核驗。舊 v5 身分及入口維持，舊全證據入口拒絕 v6。獨立快照的相關 25 項及 Python 3.13 完整 629 項已通過；3.9 完整回歸與真實 v6 blocked 核驗仍在接續記錄。下方原「第二階段待接線」是歷史範圍；UI／完整 J05 與各案剩餘範圍仍未完成，詳見 EXECUTION_STATUS 與 `artifacts/acceptance/M13/phased-decisions/`。

驗收接續：固定快照 3.13／3.9 完整各 629 項及真實兩次 v6 incomplete_search 核驗均完成；23 個歷史產物在匹配 profile 下可讀、973 個既有檔案保留。跨 profile 真實讀回仍會被原品質守門拒絕（61 對 63 findings，差在兩筆 calendar findings），不能宣稱跨環境封存已相容。J04／J05、各案剩餘排列及正式資料仍未 accepted；每案 scope 與拒絕紀錄見最新 EXECUTION_STATUS。

更新：2026-10-29（Asia/Taipei）。狀態 `in_progress`；版本維持 `0.12.3`。
這是接續實作規格；以下最初介面規劃與歷史狀態保留，已有接線及尚缺項見後續工程更新。主線見 [DEVELOPMENT_NEXT](DEVELOPMENT_NEXT.md)。

工作區核對補充：規劃期間已出現 `odd_lot_protocol/decision.py`、build 的 v5 接線，以及 `source_types.py`／`report_evidence.py` 初稿，J01／J02 因此列 `in_progress`；尚無本輪完整接線驗收。已有檔案不改變下列退出條件，實際完成狀態依 acceptance 更新。

後續工程更新：v5 政策／期間綁定、registry 全部 attempt 前綴、帳戶／報告核對與不可變決策包已有可執行接線。整合測試涵蓋真實離線帳戶的完整／缺漏候選、running／failed 最新紀錄、舊快照與重算 hash 後篡改拒絕；另補同成本對照情境失敗不得提升為 continue 的守門。正式驗收仍未結案：目前 evidence adapter 先收集開發與驗證資料，再交純核心排名；**僅開發來源的 DevelopmentSelection／獨立 selection fingerprint 與先保存再讀驗證的分階段流程尚缺**，不能據此標 J-A02 或整個 J02／J03 通過。現有決策包採每次新捕捉目錄保留完整 audit；規劃中的 canonical decision／selection 產物及 UI 還要接續完成。

接續規劃：J02／J03 的剩餘工作已拆為 [開發選擇與驗證分階段交付](R07_SELECTION_STAGES.md) J02a–b／J03a–b，明列開發與 capture 指紋分離、保存先後、版本相容、儲存及測試。該規格目前 planned，不能視為已有實作。

分階段核心更新：DevelopmentPolicy／DevelopmentEvidence／DevelopmentSelection 已有可執行型別、純排名及重建序列化；33 個新案例與 3.13 完整 520 項通過、3.9 相關 65 項通過。這只解除 J02a 的純核心缺口；source adapter 仍一次收集兩期，SelectionCapture／落盤順序／新協議規則及 UI 未接通，上段 planned 是新增規格時的歷史狀態。

## 起點與這次要交付的結果

來源／保存更新：獨立開發 collector 已從原始來源認證的帳務重建指標，selection capture 可原子保存及來源讀回；實際未來行情變動不影響開發 ID。這仍是既有 v5 報告的獨立分析：**尚未有新版協議／第二階段 API 強制引用已保存選擇，再執行固定驗證**，不能把 collector 或 capture 單獨當作 J03 全案完成。完整／局部測試及真實 blocked 證據見 EXECUTION_STATUS 最新 R07 段與 `artifacts/acceptance/M13/development-sources/`。

`odd_lot_decisions/types.py`、`evaluate.py`、`validation.py` 已有純計算核心及專屬測試。它接受呼叫端提供的證據，不認證來源；任意填入一個 SHA-256 字串也不能證明績效真實。
目前 `SelectionRule` 的驗證／拒絕規則仍是文字，v4 `analysis_plan` 明列 `automatic_candidate_selection=False`。runner、registry、報告及 UI 尚無完整決策接線驗收；不能把核心或新協議初稿存在當成 R07 完成。

交付一份能回溯所有候選、來源 attempts、開發期選擇及驗證門檻的不可變決策報告。UI 使用同一後端核驗與判斷，不另外計算績效或選出候選。
`continue` 只代表依固定規則繼續研究／觀察；正式資料目前三期仍 blocked，不能產生可採用的策略結論。

## 先固定的決策語義

| 項目 | 本輪契約 |
| --- | --- |
| 選擇單位 | `candidate_id × strategy`；主動策略限 ensemble、momentum。等權及 ETF 是對照，不能因績效好而臨時加入候選 |
| 搜尋預算 | 凍結完整 batch 候選及每候選情境 ID；另列策略／情境總試驗數，不能只報 batch 數 |
| 排名 | 只取 development 的明列 objective；樣本門檻與零回撤／零波動的未定義值先處理，平手依 candidate ID、strategy 升序 |
| 開發證據缺漏 | 任一宣告候選缺可核驗開發結果為 `incomplete_search`，不先選已完成的好結果；已知少樣本列不合格及原因 |
| 驗證 | 開發期選定後才讀取其 validation／敏感度證據。失敗或不足不換第二名；探索期不參與排名、門檻或補位 |
| 風險／成本門檻 | 年化報酬、最大回撤、全情境報酬／回撤、基準比較及選用的止損門檻須明確凍結；不替正式協議填入測試 fixture 的數字 |
| 樣本 | 主動策略每個必要期間／情境至少 30 個完成 episode；未平倉不補數。ETF 買入持有無須 30 筆已平倉交易，但價格／帳務及比較期間必須完整 |
| 基準比較 | 同 candidate 的相同資金／sessions／成本政策之可交易 ETF；勝出用嚴格大於，平手不算超越。無成本參考不替代 |
| 缺值與失敗 | 不造零值；同時保存已知未通過門檻與未知／少樣本項。總狀態依目前核心採 unavailable → insufficient_sample → return → continue 優先序 |
| 風險證據 | 啟用止損門檻時，pending 退出列觀察不足；缺建倉預算列 unavailable。選擇不啟用某門檻也須明列，不能默認已通過 |

先保存僅含開發來源與排名的 `development_selection.json`，再建立驗證判斷；修改 validation 或探索期數值不能改變該選擇產物的 fingerprint。
既有歷史已被接觸，新規則必須保留其事後制定／歷史探索屬性。政策先於「新一輪執行」凍結，不等於證明過去未看資料；新協議不回填前向預註冊。

## 型別與儲存契約

下列是待新增介面；先交 schema／序列化測試，再接 runner。既有 `DecisionPolicy`／`ResearchDecision` 延用並檢查與協議一致。

| 契約 | 必要欄位／行為 |
| --- | --- |
| `AttemptReference` | protocol／candidate／experiment ID、attempt 編號、terminal status、result fingerprint、report manifest digest；路徑僅為 locator |
| `DecisionEvidenceBundle` | 來源 registry 截止位置及 digest、全候選來源清單、typed 開發／驗證證據、缺漏原因、來源與期間用途綁定 |
| `DevelopmentSelection` | 政策 ID、僅開發來源 fingerprint、全候選適格／排名及唯一選擇；不含 validation／探索期績效 |
| `DecisionArtifact` | schema／rule version、protocol／policy ID、selection ID、完整來源 inventory、逐門檻結果、限制及決策 fingerprint |
| `collect_decision_evidence()` | 純讀取 registry、已驗證凍結研究與報告，核對來源後重建 evidence；不接受任意 CSV 或自行填寫的績效 |
| `export_decision()/verify_decision()` | 原子發布新決策包；讀回依政策與來源重建，hash 正確但語義不符仍拒絕 |

新協議明確宣告 v5 analysis plan、canonical `DecisionPolicy`、策略／情境預算與證據收集規則；舊 `SelectionRule` 與 policy 重複的 objective／樣本門檻必須相符。
保留 v1–v4 讀取與原始 fingerprint；沒有 executable policy 的舊協議只可展示原報告。若另作事後分析，建立具名子協議／決策身分，清楚記錄原結果已存在，不補寫到舊協議。
v5 若需改 `StudyProtocol` schema，先另定版本讀取分支及相容測試，不讓舊 schema 接受額外欄位後悄悄換身分。

建議新檔置於 `odd_lot_decisions/` 的 `policy.py`、`sources.py`、`assemble.py`、`report.py`、`ui.py` 及 README；視職責拆分，每檔不超過 300 行。聚合邏輯不塞入既有大型 `ui.py`／`odd_lot_study.py`。
決策另存 `artifacts/odd_lot_decisions/<protocol_id>/<decision_id>/`，包含 protocol、來源 inventory、開發選擇、`decision.json`、候選／門檻 CSV、HTML 及 hash manifest；不改寫舊研究或 candidate 報告。

## 來源核驗與重試規則

1. 核對全候選同屬凍結 protocol、資料／日曆／程式環境身分與期間用途；scenario ID 及 BenchmarkSpec 必須與各候選的 analysis plan 相符。
2. 對每個候選核對 registry 的 experiment／attempt 與報告綁定，執行既有 study／report 驗證，再從保存的帳務重建必要指標。不能只信任報告摘要或來源 fingerprint 字串。
3. 開發證據收集先完成並保存 selection；再讀選定候選的驗證及風險／敏感度證據。探索期只在獨立展示區出現。
4. 保存全部失敗／受阻及重試歷史。初稿的 `latest_registered_attempt_prefix_v1` 採截止位置內最新 attempt；最新 failed／blocked 不回頭借用較早成功結果。成功重試可提供證據，但所有成功重試的業務 fingerprint 必須一致；來源明列 attempt，不能挑最有利數字。此規則須連同政策通過 J01／J02 驗收。
5. running attempt、未解的 nonreproducible failure 或候選缺漏阻擋完整決策。一般失敗後成功重試的失敗仍保留，不把失敗當績效為零。
6. 收集開始／結束核對 registry 的截止位置、報告及來源 inventory；變動時拒絕發布，重新收集。已發布包凍結該次歷史，不因後來新增 attempt 自動改寫。

這是本機完整性及來源一致性驗證；不宣稱能獨立認證行情真實性或防止所有來源與帳務被同步改寫。

## 可逐次交付的工作包

| ID／狀態 | 交付 | 退出條件 |
| --- | --- | --- |
| J00／已有工程證據 | 核對現有純核心、22 個測試及鄰近 README | 既有 3.13 完整 465 項、3.9 核心 22 項紀錄可追溯；尚不算來源接線完成 |
| J01／in_progress | 政策綁定、v5 協議與新型別；工作區已有接線初稿 | 改任一門檻產生新 ID，舊 v1–v4 不變；未提供完整政策不能啟用判斷 |
| J02／in_progress | registry／報告來源 adapter、開發選擇及聚合；已有來源型別／報告證據初稿 | 完整有限候選可核對；缺漏／外來／篡改／重試矛盾拒絕，開發選擇不受驗證影響 |
| J03／in_progress | 已有決策包匯出與讀回重建；接續獨立 selection 與兩階段產物 | 同來源重跑決策 ID 一致；修改決策後重算 manifest 仍遭語義核驗拒絕；保存選擇先於驗證解析 |
| J04／planned | UI 協議／實驗瀏覽、固定政策與判斷呈現 | 使用同一後端；不利／失敗／blocked 可見，修改政策另建子協議，無政策不默默套預設 |
| J05／planned | 全回歸與真實 blocked 守門驗收 | 兩環境、舊報告保留、案例對照及實際 acceptance 完整；真實受阻不生成虛構排名 |

順序 `J00 → J01 → J02 → J03 → J04 → J05`。每步獨立 diff／相關測試；J05 通過後才標 R07 工程完成。
J04 先交唯讀協議／attempt／決策瀏覽，再接「凍結新政策／執行已凍結研究」操作；不得由 UI rerun 自動重做搜尋或覆寫協議。

## 專屬驗收矩陣

| 案例 | 必須驗證的結果 | 上層案例 |
| --- | --- | --- |
| J-A01 | 門檻缺漏／非有限值或 SelectionRule 衝突拒絕；變更門檻形成新 ID | R-A02 |
| J-A02 | 全候選開發排名與平手可重現；改 validation／探索期只改檢查，不改 selection fingerprint | R-A03、R-A11 |
| J-A03 | 缺一候選、running 或不可重現紀錄皆不選部分最優；全部失敗及原因可見 | R-A11 |
| J-A04 | 開發第一名驗證失敗不換第二名；已知失敗與缺值／pending 同時保存 | R-A07、R-A11 |
| J-A05 | 29／30 完成 episode、零波動、零回撤、無成交與 ETF 未平倉分別符合定義 | R-A07 |
| J-A06 | 外來 protocol／candidate／scenario、錯期間或不同 sessions／基準設定拒絕 | R-A04、R-A12 |
| J-A07 | 刪除情境、修改政策／來源／診斷／決策並重算 hash，仍遭來源重建拒絕 | R-A12 |
| J-A08 | 失敗後成功重試可用且失敗保留；結果矛盾與收集期間 registry 變動拒絕 | R-A01、R-A11 |
| J-A09 | v1–v4 原協議／報告可讀，原 bytes／ID 不變；事後子協議不冒充先前凍結 | R-A02、R-A10 |
| J-A10 | UI 正常、blocked、無政策、少樣本及壞來源情境與後端一致，重繪不新增 attempt | R-A04、R-A10–A12 |
| J-A11 | 真實資料仍 blocked，全部候選原因可追溯、無可用排名；既有研究／報告 inventory 保留 | R-A04、R-A12 |

純核心既有測試可覆蓋部分 J-A02／A04／A05，不能代替 adapter／報告／UI 案例。每案記錄 test node 或證據路徑、命令、環境、exit code、revision／工作區及產物 hash。
J05 依 [驗證入口](README.md) 明確指定 3.13／3.9 interpreter，循序跑完整 Lint／pytest；失敗與重跑分列，不用放寬逾時或刪除案例取得通過。

## 交接 M14

R07 工程完成可交固定 fixture 的候選／策略／policy／execution 身分供 M14 比對。真實資料仍 blocked 時，M14 L01–L05 可用 fixture 驗證；前向啟用另需逐期合格輸入、獨立 protocol、account ID 與開始 session。
本次沒有制定正式策略門檻、啟動候選搜尋或提升任何資料狀態。M14 的第一個切分見 [L01–L02 詳細安排](M14_PAPER.md#m14-core)。
