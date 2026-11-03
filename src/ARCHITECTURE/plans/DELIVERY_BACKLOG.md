# 接續交付清單與發布閘門

本輪核對與可執行排程見[發展收斂計畫](DEVELOPMENT_CONSOLIDATION.md)。研究 UI 3.13 完整回歸已終局為 703 passed／1 failed，失敗是既有 ready UI 的 30 秒逾時；不能列為全綠或仍在執行。M14 已有歷史重建與前向流程，接續驗收，保留下方早期 planned 列作歷史。

M14 最新工程補充：專用 state／session core／SQL／snapshot／獨立 audit、歷史與前向虛擬帳戶 workflow／UI 已有實作；下方 L01–L06 尚待開工的列是早期盤點。前向來源另有不可變 raw archive、plan/config／逐日取得證據 transaction 綁定；完整啟用 fixture、no-op 及缺尾端守門在固定來源 3.13 通過，兩環境相關與 UI 測試另有證據。最新完整回歸與逐案發布矩陣仍執行，M14 不標 accepted。取得日內時間需不早於 frozen XTAI 收盤，新修正另跑雙環境回歸；實際進度見 [EXECUTION_STATUS](EXECUTION_STATUS.md)。

最新資料接續（2026-10-29）：2317／2025-07-30 已據官方停牌及復牌公告完成個股停牌修訂。新衍生包 `23ca14c7733df93d5a47fc45`、新凍結研究 `23bb603a256b04cb87f472b3` 及報告已核驗；原始問題 60、三期 findings **61／55／56**，三期仍 blocked、績效為空。下方 `44e3...`／`d307...` 及 61／55／58 保留為上一基線；具體證據與待辦見 [事件調查](EVENT_INVESTIGATION.md)。新資料的 M13 子協議尚待交付，舊協議／決策不自動沿用。

更新：2026-10-29（Asia/Taipei）。版本仍為 `0.12.3`，工作區有未提交實作。
本檔只排剩餘工作；實際歷程見 [EXECUTION_STATUS](EXECUTION_STATUS.md)，完整案例沿用各里程碑計畫。
`in_progress` 表示已有實作或證據，並不等於整張驗收矩陣通過。

## 本輪核對的基線

| 範圍 | 已有產物 | 尚缺的完成證據 |
| --- | --- | --- |
| P0 | 同一 interpreter 驗證、3.13／3.9 獨立環境與版本清單；P0 原紀錄各 372 項、R05 各 443 項，R07 接線雙環境各 487 項；開發核心新增後 3.13 完整 520 項、3.9 相關 65 項 | 預設環境異常處置、P0 全矩陣發布審查及接續變更的回歸證據；465／核心 22 項紀錄保留於歷程 |
| M12-4 | 型別／純讀取 readiness、schema 3、研究／報告／UI 共用判定、正反 fixtures | Q-A01–A12 逐案對應實際證據及發布審查 |
| DATA-02 | 本機 FinMind reader、raw/CSV 交叉驗證、選源 lineage、provider_reviewed 完整接線 | CAL-02、S-A01–A12 全矩陣結案；來源取得不等於正式研究通過 |
| CAL-02 | 官方公告衍生資料包、差集逐日核對、三入口同為 1,582 sessions；舊資料 hash 保留 | 完整案例矩陣與發布審查 |
| M12-5 | 新來源已走共用事件／停牌／覆蓋檢查 | 真實 coverage 審核、事件解釋／模型、逐期 acceptance |
| M13 | 協議／實驗登記、基準、診斷及敏感度；R07 v5 政策、registry 來源核對與決策包已有接線 | 開發專用 selection 產物／分階段收集、UI、完整矩陣及研究驗收；整體 M13 尚未 accepted |
| M14 | 專用狀態、帳務順序與故障驗收規劃 | L01–L06 待實作；一般帳本不能代替零股持久化驗收 |

目前真實來源為衍生包 `44e3c80317da54e4b54f7fcd`，凍結研究 `d307f4636baad1a1c970953e`；原始品質問題 61 筆。原官方政策 context 1,422 筆另保留，不混入新政策阻擋數。
readiness 按語義再產生／連結 findings，與原始問題不是一對一；各期暖機及相依窗口亦重疊，數量不可相加。

| 期間 | 狀態 | 已驗證暖機 | 阻擋 findings |
| --- | --- | ---: | ---: |
| 開發期 2021–2023 | blocked | 120 | 61 |
| 驗證期 2024 | blocked | 120 | 55 |
| 歷史探索期 2025–2026-10-27 | blocked | 120 | 58 |

最新 v5 子協議 `8dc054b5ad73449a13c063feab5dcd347d856ed868f493dc1cee7a003f0b5f8a` 的兩次執行均 blocked；決策均為 incomplete_search，沒有候選採用結論。績效列數 0、原 15 個不可用組合及 18 個 blocked 情境保留。證據見 `artifacts/acceptance/M13/decision-binding/`；v2–v4 原始紀錄保留。
較早基線為 `DATA-02/prepared/summary.json` 的 66 筆問題及研究 `94ef4820b48f76d32fef5270` 的 12 個不可用組合，僅供歷史比較。
截止日固定為 2026-10-27。此清單沒有重新執行候選搜尋，也沒有修改任何舊研究。

## 第一段：收斂現有工程與真實資料缺口

下列順序是共享核心的修改順序；離線協議與事件來源調查可先準備，每次只合併一個可驗證單元。

| ID／狀態 | 下一個具體動作 | 退出條件與證據 | 依賴 |
| --- | --- | --- | --- |
| B01／in_progress | 核對現有差異；將 P0、Q、S 案例逐一對應測試或真實產物，缺例列出 | 每案有 case ID、命令／資料、環境、結果及 hash；不以總測試數代替全矩陣 | 現有工作區 |
| B02／in_progress | 3.9 相容性與 2025-01-09 修正已有證據；接續預設環境入口失效處置及完整發布回歸 | P0-A01–A09 全有證據，明確使用可重建且一致的驗證／UI interpreter | B01 |
| B03／in_progress | 三份公告衍生資料與原 20 日差集已完成；將現有來源／hash 證據加入驗收索引 | 每個差異有分類、來源、hash 或明列未解；衍生 bundle 可重建且重試不覆寫 | B01；選定的 3.13 環境 |
| B04／in_progress | 共用日曆工程已完成，補齊整體矩陣簽核 | 相同 revision／證據下三入口 sessions 一致；市場休市與個股停牌分開；反例仍辨識真缺價 | B03；S-A07、S-A08 |
| B05／in_progress | 衍生資料及新 study/report 已完成，納入 B01 驗收索引 | hash／readiness 一致；舊官方及混合研究維持原 bytes；受阻期間績效仍為空 | B03、B04 |
| B06／in_progress | 現金股利日期修訂已交付，接續兩個權利事件及五類 coverage 審核 | 開發期必要 unknown／blocking 為零才 accepted；資料不足交精確缺欄位清單 | B05；E01–E06 |

B02 先驗證現有 Python 支援宣告。若相容依賴無法解決，依 P0 的有來源例外方案處理；提高最低 Python 版本須有明確相容性決策與遷移說明，不暗中修改宣告。
目前可用的驗證環境是 `artifacts/environments/p0-clean313`；不以反覆覆寫 `.venv` 作為問題解法。

### B03–B06 的具體調查範圍

| 問題 | 已有資訊／需補的事實 | 驗收方式 |
| --- | --- | --- |
| 日曆三日 | 2024-10-31、2026-07-10、2026-10-23 已據公告完成衍生資料與三入口核對 | 保留證據／差集及 hash，納入 CAL-02 整體驗收 |
| 事件落在休市日 | 1216／2023-08-03、2891／2026-07-10 已逐案審核映射至下一 session | 保留原來源與審核表；既有修訂不推廣為所有事件自動順延 |
| 未建模權利 | 2881／2021-09-06、2882／2022-12-05 | 確認種類、權利數量／成本、可得時點及款項可用日；資料完整後先寫手算例題，再決定模型 |
| 供應商無報價 | 2317／2025-07-30 全零輸入已正規化為 no-quote | 取得可核對行情或合法停牌佐證；維持不可交易，不將 no-quote 自動解釋為休市 |
| 分項覆蓋 | 現有 55 筆 coverage 問題；11 標的（含基準）×5 類 | 先覆蓋開發期及暖機，再延伸驗證／探索期；每一段均有來源與實際審核，不批次填造無事件聲明 |

三份公告的本機來源紀錄為 `artifacts/acceptance/CAL-02/evidence/provenance.json`。
0050 的拆股／停牌原始證據已存在；先檢查是否被正確採用，避免重複事件入帳。
新資料可能改變或新增 findings；歷次修復前數量保留在下方執行更新。

本輪執行更新：B03 已產出 `artifacts/twse_derived/5bc3befefd9363a8897d1e28`，三期暖機均 120、原始問題 63 筆、阻擋 findings 62／56／59，仍全數 blocked。新研究 `4674007563cdd7faf7693ae6` 的報告完整性通過且沒有績效列。日曆 4.13.2 配合已核對官方休市後，與原 provider calendar 的差集為空；原 20 日逐案對照已存 `artifacts/acceptance/CAL-02/derived-closures/`。B03 的資料產物已完成，整個 CAL-02 仍須 B04 及完整矩陣才能 accepted；表中原 baseline 保留供前後比較。

後續工程更新：B04 已完成明確的 `CalendarClosures`／共用 session 介面，7 個新案例及完整 369 項測試通過。真實三入口同為 1,582 日，兩份既有研究重新載入／守門後檔案及 readiness 指紋不變；證據在 `artifacts/acceptance/CAL-02/shared-contract/`。這解除 S-A08 的已知介面缺口，整體矩陣仍需逐項結案；接續 B02 的獨立 Python 3.9 相容驗證及 B06 事件／coverage。

B02 相容驗證更新：已乾淨安裝獨立 Python 3.9.6，重現並以官方 NYSE 休市例外修正舊套件問題；Python 3.9／3.13 的完整 Lint 與 372 項測試均通過，repo 外匯入及舊研究驗證通過。版本集合與 P0-A01–A09 證據對照見 `artifacts/acceptance/P0/compatibility39/`；整體 P0 尚待最後證據審查與預設環境異常處置，不重建覆寫 `.venv`。

B06 局部交付：已加入逐案休市日現金股利映射與不可變來源版本，修復 1216／2023-08-03、2891／2026-07-10 的有效交易日；事件日前報酬不變，修訂表進報告 hash。完整驗證 383 項通過，三期仍 blocked（61／55／58），原始問題 61 筆。新研究 `d307f4636baad1a1c970953e` 與剩餘認股權／coverage 工作見 [EVENT_INVESTIGATION](EVENT_INVESTIGATION.md)，不將此單一事件能力標為全部 E05 或 M12-5 accepted。

## 第二段：讓研究與每日模擬可重現

| ID／狀態 | 工程單元 | 可提前完成的部分 | 正式驗收閘門 |
| --- | --- | --- | --- |
| B07／in_progress | M13 協議與不可覆寫實驗登記 | typed schema、有限候選、資料接觸紀錄、成功／失敗 lineage；用離線 fixture 驗證 | 新搜尋前凍結 protocol；真實績效另需對應期間 ready |
| B08／in_progress | 可交易 0050 基準與風險診斷 | 同成本／部分成交／交割手算、episode／資金／退出延遲測試 | R-A01–A12；與無成本參考分列，少樣本如實標記 |
| B09／planned | 零股單日狀態與純計算核心 | 型別先行；小步抽取既有歷史迴圈，逐步比較訊號／成交／帳務 | L01–L02；離線一次完成與分段一致，既有引擎回歸通過 |
| B10／planned | SQLite 原子性、續跑、snapshot、獨立稽核與 UI | 按 L03→L04→L05→L06 拆成獨立修改；故障注入不依賴真實資料 | L-A01–A13 全通過；真實前向觀察另需 protocol、合格輸入與開始 session |

B07 不必等待全部 coverage；B08 的 fixture 也可提前。B09 需固定執行語義及歷史對照；B10 的前向啟用等待研究／資料閘門。

B07 執行更新：協議型別／不可變凍結、來源／程式／環境身分、SQLite 重試歷史及既有 runner／報告接線已實作。完整 402 項測試、Python 3.9 針對性 19 項通過。真實受阻研究已凍結父／子協議並各重跑兩次，所有結果為 blocked、績效為空，數值指紋相同；新程式身分產生新實驗 ID。證據在 `artifacts/acceptance/M13/protocol-registry/` 及 `report-binding/`。自動候選選擇／決策報告與 UI 尚待完成；接續 B08 的同成本可交易 0050 基準與風險診斷。

B08 基準交付：已加入獨立單一 ETF 介面與 v2 協議，沿用共享帳務而不放寬研究股票池守門；期初一次委託、不補單、不設止損、股利保留現金。報告區分無成本參考／可交易基準，另輸出投資及現金比例與受 hash／協議核對的 BenchmarkSpec。完整 413 項測試、Python 3.9 相關 35 項通過；真實資料兩次 v2 執行均受阻且結果一致，原 669 個研究／報告檔案保留。證據在 `artifacts/acceptance/M13/tradable-benchmark/`；接續風險診斷、R05 基準敏感度及自動判斷，B08／M13 尚未全部 accepted。
外部佐證暫缺時，留下阻擋項目並繼續可獨立驗證的工程工作。
2025 年後資料仍是已接觸的歷史探索樣本，凍結新協議不能改稱未見資料。

B08／R04 交付：建倉預算、資金／未成交／episode／止損診斷與 v3 報告已完成，來源帳務可重建並拒絕重算 hash 後的診斷篡改。Python 3.13／3.9 完整 Lint 與 431 項均通過；3.9 首輪 UI 逾時及後續重跑保留原紀錄。真實資料兩次仍 blocked，數值一致、診斷帳戶為空，709 個先前研究檔案及七份舊報告保留。證據見 `artifacts/acceptance/M13/risk-diagnostics/`；B08 接續 R05，整體 M13 不標 accepted。

## 發布與實際研究分開驗收

| 交付 | 可以完成的條件 | 不能據此宣稱的事 |
| --- | --- | --- |
| M12-4／預定 0.12.4 | P0 發布閘門與 Q-A01–A12 通過、舊研究相容、UI 正反案例、完整 Lint／pytest | 真實資料或策略已合格；工程可正確交付 blocked 狀態 |
| DATA-02 工程驗收 | S-A01–A12 含有效日曆／來源邊界全部通過，來源政策與報告可追溯 | FinMind 已成官方來源、官方 imported 已增加、所有期間可跑 |
| M12-5／預定 0.12.5 | E-A01–A11；逐期有 input/readiness 指紋及真實資料 acceptance | 開發期通過不等於驗證／探索期通過 |
| M13／預定 0.13.0 | 固定協議、完整候選紀錄、基準與診斷、數值重現及必要案例通過 | 系統測試或獲利數字可證明策略有效 |
| M14／預定 0.14.0 | 離線持久化與稽核案例通過；前向啟用有獨立記錄 | 一般 paper ledger 或研究 SQLite 存檔已可安全當零股帳戶續跑 |

版本僅在對應發布閘門完成後調整。已跨里程碑開發的工作應以明確範圍逐項交付，不一次發布整個未驗收工作區。
所有程式／文件變更保留既有說明，新增檔案以 250–300 行為界；提交前檢查 status/diff、執行完整驗證、精準 stage。

## 排程與交接

最新 v6 後端：保存選擇後的固定驗證、schema-2 不可變決策包及來源重建已接通；固定來源兩環境完整各 629 項／Lint 通過，真實兩次均 incomplete_search，未採用候選。接續 J04a 唯讀瀏覽 → 明確操作 → J05 逐案驗收。匹配 3.13 profile 的真實封存可核驗；不同 3.9 profile 多出兩筆 calendar findings 時保持拒絕，環境／來源差異另交 B02／資料審核，不自動吞掉。完整證據及剩餘案例在 EXECUTION_STATUS 最新 R07 段。

R07 最新：開發來源核驗及不可變 selection capture 已有獨立實作；固定來源快照的 3.13 完整 569 項／3.9 相關 59 項及真實兩次 blocked capture 證據見 EXECUTION_STATUS 最上方。下一步是新協議的分階段規則與引用已落盤選擇的 validation API，而非再重建純核心。既有 v5 batch／最終決策 workflow 維持原契約，UI／J05 與完整研究發布仍未完成。

最新可直接開工的規格是 [R07 開發選擇分階段交付](R07_SELECTION_STAGES.md)：J02a–b 開發專用型別／adapter → J03a–b 保存選擇／固定驗證／相容 → J04a–b 唯讀 UI／顯式操作 → J05。B01 先補 Q-A03／A07／A11 缺例；M14 在 R07 固定對照後接 L01–L02。以下排程敘述保留各次歷史範圍，當前入口以 DEVELOPMENT_NEXT 的最新表為準。

J02a 純核心已交付 DevelopmentPolicy／Evidence／Selection 及序列化重建；來源 proof 仍待 J02b 從實際開發依賴取得。新核心不取代現有 v5 workflow，也不把來源 SHA-256 字串當成認證；完整 J-A02／R07／資料發布狀態不提升。

R04 診斷與 R05 固定敏感度已交付，R05 的雙環境 443 項、R07 的 3.13 完整 465 項及 3.9 相關 22 項各保留原驗證範圍；接續工作區驗證另記 EXECUTION_STATUS。下一個交付先補 B01 證據索引，再依 [R07 J00–J05](M13_DECISION_UI.md) 完成政策／來源核驗／決策報告與 UI，其後交 [M14 L01–L02](M14_PAPER.md#m14-core)，詳見[下一階段執行計畫](DEVELOPMENT_NEXT.md)。

R07 已先交純計算型別／開發排名及逐項驗證核心，新增 22 個案例；最新 3.13 完整 Lint 與 465 項通過、3.9 新核心 22 項通過。下一個具體動作是將政策與期間用途凍結到新協議、從 registry 及有效報告重建全部候選證據，再接決策報告／UI；尚未將呼叫方字典當成正式來源驗收。

R07 接線更新：v5 政策與期間用途、registry／報告來源核對、完整歷史前綴及不可變決策包已接通；補上必要同成本對照失敗不得通過的守門。兩環境完整 Lint 與 487 項均通過；真實兩次結果一致、839 個舊研究檔案／13 份研究報告及兩份較早決策保留。下一個具體單元是 DevelopmentSelection 獨立 fingerprint／先保存開發選擇再讀 validation，再交 UI；現有 whole-evidence decision ID 不能代替 J-A02。B01 已產出 80 案索引並留下 Q-A01–A12 的完整／局部／缺口審查，未由測試總數批准發布。
B01 案例證據索引與 B06 來源審核另有工作包；正式研究依對應期間 ready 放行。B03–B05 的已有產物直接核驗，不重新開工重建。
舊計畫的人日數是實作前估算，不能當作目前剩餘工期相加；事件來源及新模型確認前不承諾完成日期。

每單元交接附 `work_id / case_id / revision / workspace_diff_hash / environment / status / evidence_path / checked_at`。
真實資料另附 source policy、來源集合、input/readiness fingerprint、study/report ID 與受阻期間。
完整命令使用明確 interpreter，範例：

```bash
rtk proxy env QFL_PYTHON="$PWD/artifacts/environments/p0-clean313/bin/python" ./scripts/verify.sh -q
```

自動化、雲端部署、新市場及額外策略搜尋待此主線驗收後另排；不接券商 API 或真實訂單。
