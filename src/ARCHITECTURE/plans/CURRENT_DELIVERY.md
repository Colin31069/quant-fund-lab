# 目前交付計畫

2026-10-30 最新：registered_source已核對原StudyProtocol／readonly registry／ready raw study與catalog所有行情／liquidity／候選設定，registered歷史SQL入口提交前重驗；418固定來源兩環境相關各73passed／Lint通過。證據 `M14/registered-source-20261030-main/`。此入口仍拒絕未由正式rights supplement認證的命令／marks／risk，不啟用future；完整真實事件、UI與最終驗收仍待。

2026-10-30 最新：RightsRequestCatalog已固定ledger root／config及每筆archive／input／predecessor身分，版本追加保留prefix，SQL只在完整歷史重播後接納下一筆；完成重試不重送。410固定來源兩環境相關各422passed／Lint通過；證據 `M14/request-catalog-20261030-main-b/`。這是本機內容凍結，正式protocol／trusted handoff、UI及最終整合與真實資料驗收仍待。

2026-10-30 最新：每日請求已有可攜完整codec／checksum-pinned archive loader，commit_archived_day及verify_archived_days實際串SQL提交／唯讀重播，七日案例可丟棄原Python請求後從檔案重建。403固定來源兩環境相關各404passed／Lint通過；證據 `M14/day-request-archive-20261030-main-c/`。外部checksum catalog與protocol／UI認證、增量prefix、真實事件與最終整合驗收仍待。

2026-10-30 最新：commit_rights_day已接共用day workflow到既有新版原子SQL，並有外部原請求逐日唯讀重播；395檔固定來源兩環境相關各353passed／Lint通過，含七日收據生命週期、8個中斷故障及重算NAV hash反例。證據 `M14/durable-day-workflow-20261030-main/`。仍待source/request archive與認證、獨立persisted risk／NAV audit、UI及最終整合驗證；真實資料／前向未放行。

2026-10-30 最新：收據部分賣出→剩餘轉換→final鎖定退出／解鎖再賣已有明確風險轉移，advance_rights_day共用授權封存、lot執行入帳、after-close命令及projection。389檔固定來源兩環境相關各311passed／Lint通過；證據 `M12-5/receipt-day-workflow-20261030-main/`。接續combined checkpoint／獨立durable audit／原子SQL與UI；after-close入口不能處理較早deadline或資格時點。350原full兩profile已失敗終局，J05 fixture日期anchor修正仍須另驗；真實研究／前向未解除。

2026-10-30 最新：公司行動lot投影已接共同入帳，new portfolio_lot_session獨立重建events／fills／cash，projection及NAV可續接新舊session。377檔固定來源兩環境相關各271passed／Lint通過，含T+2→認購→隔日BUY與CIL／NAV手算、重開及重算hash反例。證據 `M12-5/lot-session-posting-20261030-main-b/`；仍待自動階段編排、完整交付／轉換、combined durable／新版SQL／UI及來源認證，N3整體未accepted。

2026-10-30 最新：329固定來源兩環境完整各907passed／Lint通過且來源hash不變；350排程已轉running313，尚非終局。付款授權已共用canonical policy_election收據，最後367來源去除重複收集後兩環境相關各257passed；原必要case語句全保留。證據用 `M12-5/canonical-authorization-20261030-main-b/`，下方舊「原329仍running」等描述保留歷史。接續N3連續流程／新版SQL與最終來源完整驗證，真實研究／前向未放行。

2026-10-30 執行更新：N2已有post-event lot投影及真正session wrapper，分割／反分割保留鎖定限制，terminal可消滅鎖定持股；365檔固定來源兩環境20檔相關各252passed／Lint通過。回傳尚非已入帳inventory，N3／新版SQL仍待；政策授權同名檔衝突已以獨立測試及證據路徑保留雙方。最新證據用 `M12-5/opening-lot-projection-20261030-main/` 及原授權恢復 `explicit-authorization-20261030-main/`，不混用舊rights-payment-policy目錄目前metadata。詳見 EXECUTION_STATUS。

2026-10-30 執行更新：N1／RI-01已有明確參與、當日cutoff與付款授權API，356檔固定來源兩環境相關各207passed／Lint通過，含實際T+2早截止拒絕與晚截止付款。仍待外層原授權認證／原子保存、交易付款排程與連續workflow；N1整體不標accepted。詳見 EXECUTION_STATUS 及 `M12-5/rights-payment-policy/`；下方規劃保留其制定時點。

## 2026-10-30 下一輪工作單

[下一輪發展與交付順序](NEXT_DELIVERY_20261030.md) 已按最新 sale-cap 進度細分 N1–N6。先追 329 檔原程序與已等待的 350 檔完整排程，再循序安排 J05／native 重案例；不重複啟動 full。此為規劃更新，未新增測試通過或發布宣告。

## 2026-10-30 完成條件稽核

已建立 `artifacts/acceptance/release/completion-audit-20261030/acceptance.json`，將最終來源回歸、80案逐案審查、J05實際報告邊界、native舊包、rights整合、真實readiness與實際前向共七項完成條件分列。80案都有mapping，但不等同accepted。329檔3.13完整907passed／18warnings／Lint通過；原session35967的3.9本輪實際確認存活、尚未終局，以實際同路徑logs及verification-results為準。

相較329 inventory，本次觀測有4個已列入產品檔改動、24個新non-doc檔（含測試）；尤其opening／session已新增sale-cap與session-link路徑。舊907結果不覆蓋它們，最後整合來源仍須另驗。J05的332檔重型報告target與native重建待原完整程序終局後循序執行；不新開平行完整suite。

權利接線沿下方RI順序推進；範圍變更E-A10已有兩個離線直接case證據，不再當作尚缺整套新API。真實三期仍blocked28／23／23，23筆active coverage與兩個未支援事件未解除。完整完成證據仍不足，goal及發布保持in_progress。


## 2026-10-30 接續規劃（優先於下方歷史排程）

正式protocol本機綁定接續：新historical admission核對實際frozen StudyProtocol、readonly原生registry、current execution、calendar digest、候選／研究／engine設定、股票池及期間；各SQL邊界重核，forward period拒絕。419來源相關8檔兩環境各98passed／環境及Lint通過，見`M14/protocol-admission-root-20261030/`。這是本機協議一致性，仍非官方source／公告時點／有效continue認證；公開操作入口、來源review與最後full／native及真實事件仍待，原390full64978未重啟。

公開唯讀入口接續：主UI新增預設關閉的權利帳戶核驗頁，使用外部catalog SHA、既有SQLite與封存requests，實際共用獨立NAV／risk＋原請求重播，顯示完成／pending、cash／NAV，rerender不重跑、不初始化帳戶。首413來源廣相關兩環境各400passed，pending archive後續補強另413來源各14passed／Lint通過。見EXECUTION_STATUS及`M14/archive-inspection-pending-root-20261030/`；這是唯讀本機核驗，不是正式來源／協議或forward放行。原390full64978仍同程序進行，最終來源full／native與真實事件仍待。

獨立risk接續：提交前已獨立核對engine stop／pending與收據轉換後風險映射，封存後可唯讀逐日檢查SQL，不依production replay。新13直接case與404固定來源兩環境相關各379passed／環境及Lint通過；見`M14/independent-risk-root-20261030/`。來源／registered policy與外部risk假設仍須認證，公開UI／最終full／native與真實事件未放行；原390full64978沿同程序執行，不涵蓋404新風險核驗。

獨立NAV接續：提交前已從combined checkpoint／原session link／marks／settlement獨立重算，封存後另有唯讀SQL NAV核驗，不依賴production replay。新26直接case與397來源相關targets兩環境各361passed／環境及Lint通過，見`M14/independent-nav-root-20261030/`。已能攔截production協同漂移及SQL重算hash後的NAV改值；可信source／protocol錨點、完整risk、UI、最終來源full及真實事件仍待。390來源full64978沿原程序執行，不含本次397變更。

原子SQL接續：新RightsEngineCheckpoint／RightsEngineLedger已保存engine、完整authorized account、事件及完成digest，同transaction提交；390來源兩環境相關各326passed／Lint通過，新24例含實際逐日SQL重開續跑與付款日四點故障回滾。此為storage API，仍待自動workflow／UI與獨立source／NAV／risk precommit接線。原350完整兩套各1055pass2fail均為樣本fixture暖機裁切假設；日期錨點修正後schedule6例與registered report313三例通過，report39原44271接續；64978等待其成功後跑390-source完整兩套。詳見EXECUTION_STATUS與`M14/rights-engine-sql-root-20261030-b/`，未放行整體發布或真實事件。

完整授權封存接續：AuthorizedRightsAccount與canonical codec已把真正完整指令目錄、每筆原授權與單一inventory一起保存／重開，並有獨立archive verifier；新17例與相關34檔，378固定來源兩環境各328passed／環境及Lint通過。見`M12-5/rights-auth-catalog-root-20261030/`。下方「完整catalog仍待外層保存」為早期邊界；現在尚待連續lot／交易／rights／NAV／risk編排與versioned SQL原子提交、UI及註冊／來源認證。原82614仍沿350來源跑full313，不涵蓋新archive來源，也未放行整體或真實事件。

政策命令接續：policy_election已記錄policy ID、明確pay／decline、完整requests與cutoffs，獨立audit拒絕重算hash後的非法窗口、後續改policy或裸付款繞過。新增21例；367固定來源相關29檔兩環境各319項執行通過／環境及Lint通過（含重複authorization路徑，不當作319獨立案例）。見`M12-5/rights-policy-receipts/`；共享同名碰撞已恢復原測試與證據並逐hash核對。下一單元是把原RightsSessionPolicy／PaymentAuthorization的真正凍結batch綁進receipt，再接連續workflow與原子SQL；兩套API尚不可視為已完成的整體流程。

NAV接續：實際session與rights的顯式NAV API已實作，現金、權利、交付股、賣款／碎股應收各只計一次；355固定來源相關23檔兩環境各220passed／環境檢查及Lint通過，見 `M12-5/rights-session-nav/`。原350來源full排程82614仍等待前輪雙環境終局；不含本次NAV。接續優先固定參與／付款cutoff與估值政策，再整合post-event lot、連續workflow／獨立持久化audit與新版SQL；真實資料及整體accepted仍未放行。

最新執行：開盤限量已接真正session／撮合，混合lot先賣可交易1股、次日解鎖再賣2股；engine與inventory逐日重開、獨立risk audit及歷史扣股時點反例有直接結果。350檔固定來源相關22檔兩環境各205passed／環境及Lint通過，見 `M12-5/rights-sale-limits/`。下段「尚待開盤限制」為前輪時點；接續是完整來源gates、post-event lot轉換、參與／cutoff、連續編排、NAV與新版SQL，整體仍未accepted。

執行接續：RI-00／RI-01已有新的固定來源證據及隔日回接API，15檔兩環境各153passed／Lint通過；詳見 EXECUTION_STATUS 與 `M12-5/rights-session-projection/`。付款後290元確實控制隔日買進2股、餘90元；鎖定股份只列出可賣數，尚待開盤執行限制。下段「本輪是規劃」保留前輪時點；接續仍須政策、連續流程、NAV／stop、新SQL及最終完整驗證，未放行真實事件。

已核對最新程式與本機紀錄；本輪是規劃更新，沒有重新執行完整 suite，也沒有放行發布、真實研究或前向帳戶。
權利核心、inventory、session-link 與 `post_engine_session` 已存在；接續缺口是權利付款／交付後回接隔日引擎、連續流程、lot／stop／NAV、versioned SQL 及實際來源認證。
本機定向 logs 各 112 passed 只作既有範圍紀錄，須補固定來源交接證據；不延用為最新完整驗證。

| 優先 | 接續交付 | 退出條件 |
| --- | --- | --- |
| 1 | 原整合結果及必要案例收斂 | 沿原程序取得兩環境終局，逐案區分已驗／部分／缺漏；329 檔之後的變更另列，不在運行副本上修碼 |
| 2 | RI-00／RI-01：證據與權利狀態回接 | 封存 session-flow 證據；先定政策／projection 型別，再證明付款及交付狀態可供隔日 engine 使用；資金與可交易性不提前 |
| 3 | RI-02／RI-03：連續日與風險估值 | 交易→交割→付款→交付→轉換→再交易共用一份狀態；stop／lot／NAV 有手算、失敗及重開對照 |
| 4 | RI-04：獨立版本持久化 | 全部新狀態及完成標記原子提交；故障恢復一致；舊 checkpoint-v1 bytes 與讀取契約保留 |
| 同期 | 23 筆 coverage 與兩個權利事實表 | 逐項官方來源與可得時點可查；coverage 與事件能力各自驗收，未知維持 blocked |
| 5 | RI-05／RI-06 及最終發布候選 | 來源 adapter、UI、篡改反例、同一最終來源雙環境完整 gates／舊包相容通過，才評估對應範圍發布 |
| 6 | 研究重凍結 → 實際前向 | 相依期間 ready 後執行固定選擇驗證；有效 continue 後才登記未來觀察，歷史與 fixture 不計樣本 |

具體介面、時點語義、案例與相依見 [權利事件整合與下一輪交付](RIGHTS_INTEGRATION_NEXT.md)。
真實 study `195e874e86026da7a9209f95` 仍三期 blocked 28／23／23；版本維持 `0.12.3`。
外部資料未知不阻擋離線工程；新功能通過也不自動解除資料阻擋。以下保留各輪基線與歷史安排。

## 2026-10-29 基線與後續執行紀錄

更新：2026-10-29（Asia/Taipei）。範圍：十萬元台股零股研究與虛擬帳戶；版本維持 `0.12.3`。
本文件是目前排程入口；舊計畫及執行紀錄保留歷史，狀態變更須附新的來源與驗收證據。

## 本輪決策與核對基線

優先完成既有功能的驗收及資料缺口，再評估擴充策略、市場與部署。R07 v6、研究 UI、M14 單日核心／持久化／稽核／前向 workflow 已有實作，接續工作依實際差異安排。

| 層次 | 本次可核對的證據 | 對排程的影響 |
| --- | --- | --- |
| 工程完整回歸 | 296 檔固定來源，Python 3.13／3.9 各 737 passed、Lint 通過 | 作歷史基線；較晚程式及測試另驗 |
| 較晚整合來源 | integrated-20261029-b 封存 306 檔；session60767 的 3.13 終局 793 passed／Lint 通過；verification-results.json 已保存 exit0，3.9 原 handle 已缺失、部分 log 未終局 | 3.9 未取得終局，保留不完整結果；原來源未重跑。新329檔b快照另驗較晚整合來源 |
| R07 相容與反例 | 305 檔來源兩環境 target 各 3 passed；native 3.13 核驗 25 個舊包、1,031 個檔案 bytes 保留 | 可複用該範圍證據；預定發布 reader 若改變則重核 |
| 後加來源診斷 | PriceSourceError／原始檔與行號診斷已驗；兩環境相關各 53 passed，修改範圍 Lint 通過 | 不在上述 306 檔來源；已保存 source-error-context 證據，仍需最終整合快照 |
| 真實研究 | study `195e874e86026da7a9209f95`，政策 reviewed_provider_v2，三期 blocked：28／23／23，績效 0 | 以此版本安排資料工作；39／34／36、61／55／56 均屬舊版本 |
| 案例索引 | P0／Q／S／E／R／J／L 共 80 案；索引仍要求逐案審查 | 檔案存在、總測試數與 passed 宣告都不能直接變成 accepted |

主要證據：

- [雙環境完整結果](../../../artifacts/acceptance/release/consolidation-20261029/verification-results.json)。
- [306 檔整合狀態](../../../artifacts/acceptance/release/integrated-20261029-b/acceptance.json)。
- [25 包相容核驗](../../../artifacts/acceptance/M13/j05-consolidation/legacy-compatibility.json)。
- [v2 停牌政策與真實研究](../../../artifacts/acceptance/DATA-02/reviewed-halt-policy/acceptance.json)。
- [80 案證據索引](../../../artifacts/acceptance/release/case_index.json)。

## 接續工作包與完成標準

| 順序／工作包 | 最小可交付單元 | 完成標準 | 相依 |
| --- | --- | --- | --- |
| 1／整合狀態收斂 | 核對原完整回歸的實際程序、兩套 logs／exit code；列 306 檔與目前來源差異 | 每個 profile 有終局或明確未完成狀態，來源差異逐檔可查；不把 running 當成功 | 可立即執行 |
| 2／S-A02 來源診斷 | 保留原拒絕規則，驗證來源檔、manifest entry、raw row／CSV line 與原始 cause | 錯代號、重複、日期、非有限值、單位及檔案錯誤可定位；兩環境相關測試／Lint 通過，合法輸入與舊包行為有對照 | 來源碼已在工作區，先核對是否另有結果，避免重複作業 |
| 3／80 案驗收收斂 | 先審 S／R，再整併 Q／E／J／L；每案連結 assertion、實際命令、來源及剩餘缺口 | 形成工程必要案例清單；缺證據與缺功能分列，僅為真實缺口補最小案例；重建索引 | 可穿插於既有完整回歸等待時；同機重案例循序 |
| 4／工程發布候選 | 納入已完成修正，固定最終 inventory／Git identity／環境；循序跑兩套完整驗證及必要 UI／舊包核驗 | 同一預定發布來源的 Lint、Unit Test、操作案例與相容邊界均有證據；未結必要案例不放行 | 1–3 的必要變更完成；凍結後新增變更另列差異 |
| 同期／事件 coverage | 按標的、類別及期間整理以下 23 筆 active coverage；先開發期及暖機 | 每項明列來源適用範圍、原始 bytes／hash、審查理由；未知仍阻擋。每批另建資料及 study | 不需等待工程發布；不以其他類別名單替代 |
| 同期／認購權事實與模型 | 2881、2882 各交事件分腿事實表，再決定新增型別／帳務能力 | 資格、比例、成本、付款、交付、可交易日及資訊時點齊備；先手算與公開介面，再小步實作和歷史／durable 對照 | 必要官方事實未知時保留 blocked；E-A07 未覆蓋 |
| 5／研究重凍結 | 對 ready 的期間，以新來源／子協議執行有限候選與固定選擇驗證 | 開發選擇先保存；驗證失敗不補位；完整失敗歷史與成本／樣本限制保留；未達 continue 可正式記退回 | 相依期間 readiness 通過；資料或政策變動產生新身分 |
| 6／實際前向觀察 | 有效 continue 後登記未來開始日，逐新 session 驗來源取得時間及帳務 | pending／blocked／active 有實際證據；新 session 合格才啟用獨立虛擬帳戶；實際累積觀察結果 | 有效決策與新資料；歷史回播或 fixture 不充當前向樣本 |

## 真實資料的下一批範圍

直接重數上述 study 的 readiness.json：active findings 共 29，含 coverage 23、unsupported_event 2、event_conflict 2、invalid_derived_state 2。最後兩項是衍生狀態；原始 quality issues 為 27。各期與暖機有重疊，28／23／23 不相加。

| 範圍 | active coverage 筆數 | 下一項可審查產物 |
| --- | ---: | --- |
| 十檔普通股的 split | 10 | 確認適用於普通股的來源及固定期間；ETF-only 索引不作替代 |
| 十檔普通股與 0050 的 other_rights | 11 | 定義涵蓋事件及來源範圍，連結認購權個案；查無命中不自動證明完整 |
| 0050 的 par_value | 1 | ETF 適用規則及來源範圍審查 |
| 0050 的 reduction，自 2024 年起 | 1 | ETF 適用規則及指定期間審查 |

這是 active 項目數，不是「待下載檔案數」。完整 findings 還保留官方路徑的非阻擋背景項目，不能把它們全部重算為 v2 缺口。資料取得 405 個月份、adapter 接入、官方匯入與期間 ready 各自核銷。

事件能力與 coverage 各自驗收：補齊 coverage 不能解除兩個未建模權利。2881／2021-09-06、2882／2022-12-05 的日期與欄位調查沿用 [EVENT_INVESTIGATION](EVENT_INVESTIGATION.md)；本輪沒有重新核驗外部文件或放行新事件。

若考慮改股票池或期間，另立 scope-change 工作單：原因、父 study／協議、修改範圍、已接觸資料及新身分均保留，補 E-A10 直接案例後再採用；不得沿用原研究身分移除不利標的。

## 發布決策與執行節奏

工程發布、正式歷史研究、實際前向觀察分別放行。工程可先交付已驗功能及 blocked 診斷；真實資料受阻不必拖住所有離線工程，但必須隨交付揭露限制。研究沒有獲利或沒有 continue 也能形成有效結論，不以達成正績效作工程完成標準。

每輪只處理一個語義單元；先型別與公開介面，再實作、Lint／相關單測、證據記錄。單一新程式檔超過 300 行即拆分；保留既有註解與 docstring。共享來源凍結後不修改正在驗證的副本；同機完整 suite 依 3.13 → 3.9 循序執行。

證據每列至少含 `case_id / scope / test_or_source / command / environment / source_identity / result / remaining_gap`。復用舊證據前核對來源差異；新結果不抹去舊失敗。操作入口使用明確 `QFL_PYTHON` 與 `./scripts/verify.sh -q`。

工期在案例缺口及權利模型範圍確定後重估；外部文件等待、完整回歸耗時及實際前向樣本累積分列。下一輪立即動作是工作包 1、2 的結果核對及 3 的案例審查，資料線依上表分項推進。

接續實作已完成來源診斷定向驗證；R-A09 整合手算及 R-A07 樣本邊界已補，兩環境研究相關各 57＋7 passed。詳見 EXECUTION_STATUS 及 `artifacts/acceptance/M13/research-case-review-20261029/`。下一輪先追原完整回歸、其餘必要案例與最終來源整合；工程發布、正式研究及實際前向觀察仍未放行，沒有啟動新的完整回歸。


接續 DATA-02：已完成 S 矩陣逐案對照及實際 405-key adapter 重驗，並修正重算 report hash 可掩蓋選源表竄改的漏洞；兩環境相關各61項、主UI各4項通過。新修正需納入最終來源完整驗證；官方raw錯誤定位、provider split邊界手算與最終reader舊包相容仍有明列缺口。詳見 DATA_SOURCE_INTEGRATION 與 EXECUTION_STATUS；所有發布／研究／前向accepted仍未放行。


2026-10-30 接續：官方raw錯誤定位兩環境各48項通過，provider-selected split手算相關各8項通過，對應S02／S05的明確缺口已有直接scope證據。原306來源3.9 handle已缺失、沒有終局；新329檔a來源兩環境在SIM102 Lint終局失敗並保留現場，工作區該處修正後另凍結329檔b。新 session35967 依3.13→3.9循序完整驗證，證據在 `artifacts/acceptance/release/integrated-20261030-b/`；後續原handle狀態及最後reader相容另驗，不宣告發布通過。


2026-10-30 M14接續：L矩陣13案已有逐列assertion對照，補24個完成日契約／鎖定設定／合法另快照SQLlinkage／非零利息no-op直接案例。兩環境相關33項通過；後加明確chain assertion的最新24項亦通過，產品source仍匹配329檔快照，新增test不在原完整inventory。L06新rights持久化、L12舊schema完整操作及L13實際前向仍待結案；原完整session35967本輪確認存活，未終局。


2026-10-30 L-A12接續：四種不相容SQLite格式已經真實後端與AppTest拒絕讀取／重建且原始bytes保留；兩環境相關各18項通過，證據在 `M14/legacy-account-operations/`。此明確格式邊界已補，最終來源完整驗證、native歷史包相容及實際前向仍未accepted。
