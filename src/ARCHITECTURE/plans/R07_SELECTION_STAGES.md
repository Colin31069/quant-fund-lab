# R07 接續：開發選擇與驗證分階段交付

v6 接續：J03 已有新協議規則、saved-path 固定驗證與 schema-2 不可變決策包實作；正向、無選擇、樣本不足、實際驗證退回、例外保留、過期 capture 及篡改案例通過相關驗證。完整回歸與實際來源核驗按 EXECUTION_STATUS 的分輪範圍記錄；J04／J05 及完整矩陣未因單元實作存在而 accepted。下方前輪「新協議／第二階段尚缺」保留其歷史時間與實作切分。

更新：2026-10-29（Asia/Taipei）。狀態 `in_progress`；本文件是實作規格，本次未新增策略執行。純核心進度見下方，完整分階段流程尚未驗收。
上層契約與案例沿用 [J00–J05／J-A01–A11](M13_DECISION_UI.md)，不另外建立重複的里程碑案例 ID。

## 已核對的接縫與本輪目標

現有 `workflow.build_registered_decision()` 先呼叫 `collect_decision_inputs()`，再呼叫純決策核心。
collector 會驗證完整報告，並從 `report_candidate_evidence()` 一次取得開發、驗證與敏感度資料。
因此「純核心只用開發排名」已成立，但「先保存選擇，再讀驗證」尚未成立。
既有來源 proof 含完整 result fingerprint；把它改名為 development fingerprint 仍會受其他期間影響。

工程接續：已新增 DevelopmentPolicy／DevelopmentEvidence／DevelopmentRank 及可重建的 DevelopmentSelection，33 個新案例通過；3.13 完整 520 passed、Lint 通過，3.9 相關 65 passed。這僅覆蓋 J02a 純核心；capture 型別、開發來源 adapter、新協議規則、落盤順序及 UI 仍待接線，J-A02 不標整案通過。

來源／保存接續：已有獨立 `collect_registered_development()`、唯讀 registry reader 及 `export_development_selection()`／`load_development_selection()`。collector 只解析 development 帳戶，CSV 與 SQLite 交叉核對，完整其他期報告僅核對 bytes；capture 先保存開發選擇與完整來源前綴，重建及再次核對後原子發布。這些是既有 v5 報告的獨立分析，不把舊 batch 重新標成分階段執行。新協議規則及引用已保存選擇的第二階段 validation workflow 尚缺；來源／保存及完整回歸證據依 EXECUTION_STATUS 後續紀錄，不由本段宣告 J02／J03 全案完成。

下一個交付讓執行順序可測：捕捉來源截止位置 → 重建全候選開發證據 → 保存不可變選擇 → 只評估固定選擇的驗證 → 發布決策包。
這是對已存在歷史報告的分階段分析，不宣稱報告中的驗證資料從未被人或舊程式讀過。
現有 v5／schema 1 決策包保留原讀取分支、bytes 與 ID；新流程用明確版本與規則分支，不能悄悄改舊協議語義。

## 先交的型別與指紋邊界

下列為交付契約；開發政策／證據／選擇純核心已有型別與序列化，SelectionCapture／ValidationDecision 及來源接線仍待新增。

| 契約 | 語義內容 | 排除的依賴 |
| --- | --- | --- |
| `DevelopmentPolicy` | objective、最少完成 episode、未定義值處理、平手規則、開發日期與規則版本 | 驗證門檻及探索期設定 |
| `DevelopmentEvidence` | candidate × strategy、可用性／原因、樣本、排名所需指標、開發來源 fingerprint | validation／探索績效、完整 result fingerprint |
| `DevelopmentSelection` | schema／rule、開發政策、完整宣告預算、全候選適格與排序、唯一選擇或無選擇理由 | 時間、路徑、attempt 編號及完整報告 manifest digest |
| `SelectionCapture` | protocol／完整 policy ID、registry 前綴、來源 inventory、selection ID、實際保存時間 | 不作為純開發 selection ID 的雜湊內容 |
| `ValidationDecision` | selection ID、固定選擇、驗證／ETF／必要情境及風險檢查、來源與限制 | 不可重新排名、補位或擴大候選預算 |

`selection_id` 是 DevelopmentSelection 語義內容的 canonical fingerprint；完整來源與稽核身分放在 capture envelope，另算 manifest digest。
完整 protocol／study／dataset／policy ID 可能因驗證或探索資料而改變，保留追溯鏈結，但不能直接混入純開發雜湊。
開發來源 fingerprint 應涵蓋實際使用的暖機／訊號歷史、sessions／日曆修訂、事件、帳戶設定與開發業務輸出；依賴範圍要明列。
跨期 raw 檔與全域日曆 revision 的完整 hash 放 capture；開發雜湊使用經核驗後的開發依賴切片及適用修訂，避免檔案中僅未來部分變動也污染 selection ID。
只截取 comparison 的開發列不算來源認證；必須從開發帳務重建，並核對該期來源與設定。
同樣的開發輸入與規則，即使新增相同結果的重試或改變驗證／探索值，selection ID 必須相同；capture digest 可以不同。
改變開發資料、候選預算或排名政策則應改變 selection ID，即使最後仍選同一候選。

## 收集、保存與失敗語義

1. 先以同一 registry read transaction 捕捉完整宣告候選及所有 attempts 前綴；檢查 protocol／candidate 綁定與路徑安全，不挑最好的一次。
2. 第一階段僅反序列化開發期業務證據。完整來源檔可以作不透明 bytes 的 hash／inventory 核對，不能計算或讀入 validation／探索績效供選擇使用。
3. 將目前全報告 verifier 拆出可驗證開發依賴的路徑；只靠 monkeypatch 掉 verifier 或把先讀到的驗證資料丟棄，不滿足分階段要求。
4. 全候選開發證據到齊才選擇；missing／running／無可核驗開發報告或不可重現狀態繼續阻擋。已知少樣本保留不合格原因。
5. 全局 failed 若源自驗證情境失敗，而開發結果本身可核驗，保留開發結果與後續失敗；不得讓驗證表現反向改變開發排名。開發證據不完整的 failed 不借用較早成功補齊。
6. 先以原子 rename 保存並讀回核對 selection capture。第二階段 API 必須接受已保存的 capture 參照，不能只接受記憶體中的選擇或任意 candidate ID。
7. 選擇不存在時，仍發布 incomplete／少樣本及全部開發原因；不執行驗證排名。已有選擇時，才取得該候選的驗證與全部必要策略／ETF 對照情境。
8. 驗證失敗、缺來源或少樣本均不換第二名；已知失敗與未知項一起保存。探索期獨立展示，不影響任何採用門檻。
9. 發布前重核 registry 截止位置、來源 bytes、protocol 與 execution identity。收集期間變動則拒絕發布，保留已保存的 selection capture 與失敗證據；重新執行使用新 capture。

完整舊報告語義驗證可以放在第二階段，但任何未通過來源核驗的結果不能發布為有效最終決策。
若來源損壞位於非開發期間，已保存的開發選擇不改寫；最終狀態明列來源失敗，也不能展示為 continue。
不可重現守門沿用 registry 契約；不因這次拆階段而放寬既有失敗或改寫 terminal attempts。

## 不可變儲存與相容分支

規劃使用以下布局，避免相同業務決策重跑時覆蓋不同稽核歷史：

```text
artifacts/odd_lot_decisions/<protocol_id>/
  selections/<selection_id>/<capture_id>/
    development_selection.json
    selection_context.json
    selection_manifest.json
  <decision_id>/<capture_id>/
    development_selection.json
    selection_reference.json
    protocol.json / context.json / sources.json / evidence.json
    decision.json / candidates.csv / checks.csv / report.html
    report_manifest.json
```

`capture_id` 僅識別一次捕捉，不影響 selection／decision 的業務 ID。同內容重跑仍保留不同完整歷史；不建立可被靜默改寫的 latest 決策。
第二階段中斷後 selection capture 保留；失敗另存該次 capture 的獨立失敗紀錄，不回寫 selection manifest。
原 `<protocol_id>/<uuid>/` schema 1 包按原規則核驗；新 schema 明列 selection 參照與兩階段規則，不用目錄名稱猜格式。
新協議的 analysis plan 明列新收集規則；既有 v5 的 `latest_registered_attempt_prefix_v1` 原樣保留。新引擎／規則字串須在第一個實作單元一併定稿並測試拒絕未知版本。
讀回核驗必須從捕捉的歷史前綴重建開發選擇，再重建固定選擇的驗證，不因日後新增 attempt 把舊 incomplete 包升級。

## 可審查的實作順序

| 順序 | 交付範圍 | 退出條件／案例 |
| --- | --- | --- |
| J02a | 開發型別、語義／capture 分離、版本分支與純選擇函式 | 序列化有限值、排序／平手／29–30 邊界；舊 schema fixture bytes／ID 不變；J-A01／A02／A05／A09 |
| J02b | 開發專用 source adapter 與必要來源核驗 | 全預算、缺漏、running、failed 分類、來源篡改及非開發變動測試；J-A02／A03／A06–A08 |
| J03a | selection 原子保存及固定選擇的第二階段 API | spy 證明第一個 validation 解析發生前，selection 已落盤且可驗證；失敗不補位；J-A02／A04 |
| J03b | 新決策包、歷史重建、截止位置競態與相容 | 重算 hash 篡改仍拒絕；前後捕捉變動拒絕；舊包與舊 inventory 保留；J-A07–A09 |
| J04a | 唯讀協議／attempt／selection／決策瀏覽 | empty／舊版／blocked／少樣本／壞來源與後端一致；UI rerun 不寫 registry；J-A10 |
| J04b | 明確凍結新政策與執行固定協議的 UI 操作 | 無隱藏預設政策、按鈕外不啟動搜尋、失敗與重試可見；J-A01／A08／A10 |
| J05 | 逐案例矩陣、雙環境完整回歸及真實 blocked 驗收 | J-A01–A11 範圍完整、保留失敗／重跑、真實無假排名；再判斷 R07 工程是否完成 |

每個單元先相關測試，再按共享元件影響擴大；身分敏感測試或真實執行期間不改 source／tests／scripts。
3.13／3.9 完整回歸循序執行；沿用 [驗證入口](README.md)，不調寬既有 UI timeout。
新增模組放 `odd_lot_decisions/` 並更新鄰近 README；不把聚合邏輯加入大型 UI 或研究迴圈。

## 必做的獨立驗證

- 使用可核驗的兩候選 fixture，僅修改 validation／探索輸入並建立合法新來源，開發選擇 bytes／ID 相同；驗證判斷或 capture digest 依變動改變。不能僅改呼叫端已組好的字典。
- 修改開發暖機／資料／候選設定，selection ID 應改變；確保沒有為通過不變性而漏綁真正的開發依賴。
- 在 selection 保存前嘗試開啟 validation 業務資料時測試應失敗；保存後第二階段例外，已落盤的選擇仍可獨立核驗。
- 開發第一名驗證不通過而第二名更好，結果仍是原選擇的失敗；必要 ETF 情境失敗保留既有守門。
- 同數值重試選擇 ID 一致、完整 audit 不同；收集期間新增 attempt／修改來源拒絕發布；舊 prefix 包保持原判斷。
- 新版與 schema 1 真實 blocked 包均可讀；新程式身分另凍結子協議，原研究與報告不覆寫。

## 交接及完成邊界

這份切分完成後先交唯讀 UI，再交顯式操作及 J05；完成 R07 工程才交 [M14 L01a–L02c](M14_PAPER.md#m14-core) 的固定對照。
B01 同期先補 Q-A03／A07／A11 的缺例，再核對 P0／S 的證據；B06 逐期資料審核持續，不阻擋離線 fixture 開發。
正式研究仍受三期 blocked 與事件／coverage 來源限制；本規劃不設定新的正式策略門檻、改版號或宣告發布。
