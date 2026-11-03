# 權利事件整合與下一輪交付

2026-10-30 最新：registered_source已核對原StudyProtocol／readonly registry／ready raw study與catalog所有行情／liquidity／候選設定，registered歷史SQL入口提交前重驗；418固定來源兩環境相關各73passed／Lint通過。證據 `M14/registered-source-20261030-main/`。此入口仍拒絕未由正式rights supplement認證的命令／marks／risk，不啟用future；完整真實事件、UI與最終驗收仍待。

2026-10-30 最新：RightsRequestCatalog已固定ledger root／config及每筆archive／input／predecessor身分，版本追加保留prefix，SQL只在完整歷史重播後接納下一筆；完成重試不重送。410固定來源兩環境相關各422passed／Lint通過；證據 `M14/request-catalog-20261030-main-b/`。這是本機內容凍結，正式protocol／trusted handoff、UI及最終整合與真實資料驗收仍待。

2026-10-30 最新：每日請求已有可攜完整codec／checksum-pinned archive loader，commit_archived_day及verify_archived_days實際串SQL提交／唯讀重播，七日案例可丟棄原Python請求後從檔案重建。403固定來源兩環境相關各404passed／Lint通過；證據 `M14/day-request-archive-20261030-main-c/`。外部checksum catalog與protocol／UI認證、增量prefix、真實事件與最終整合驗收仍待。

2026-10-30 最新：commit_rights_day已接共用day workflow到既有新版原子SQL，並有外部原請求逐日唯讀重播；395檔固定來源兩環境相關各353passed／Lint通過，含七日收據生命週期、8個中斷故障及重算NAV hash反例。證據 `M14/durable-day-workflow-20261030-main/`。仍待source/request archive與認證、獨立persisted risk／NAV audit、UI及最終整合驗證；真實資料／前向未放行。

2026-10-30 最新：收據部分賣出→剩餘轉換→final鎖定退出／解鎖再賣已有明確風險轉移，advance_rights_day共用授權封存、lot執行入帳、after-close命令及projection。389檔固定來源兩環境相關各311passed／Lint通過；證據 `M12-5/receipt-day-workflow-20261030-main/`。接續combined checkpoint／獨立durable audit／原子SQL與UI；after-close入口不能處理較早deadline或資格時點。350原full兩profile已失敗終局，J05 fixture日期anchor修正仍須另驗；真實研究／前向未解除。

2026-10-30 最新：公司行動lot投影已接共同入帳，new portfolio_lot_session獨立重建events／fills／cash，projection及NAV可續接新舊session。377檔固定來源兩環境相關各271passed／Lint通過，含T+2→認購→隔日BUY與CIL／NAV手算、重開及重算hash反例。證據 `M12-5/lot-session-posting-20261030-main-b/`；仍待自動階段編排、完整交付／轉換、combined durable／新版SQL／UI及來源認證，N3整體未accepted。

2026-10-30 最新：329固定來源兩環境完整各907passed／Lint通過且來源hash不變；350排程已轉running313，尚非終局。付款授權已共用canonical policy_election收據，最後367來源去除重複收集後兩環境相關各257passed；原必要case語句全保留。證據用 `M12-5/canonical-authorization-20261030-main-b/`，下方舊「原329仍running」等描述保留歷史。接續N3連續流程／新版SQL與最終來源完整驗證，真實研究／前向未放行。

2026-10-30 執行更新：N2已有post-event lot投影及真正session wrapper，分割／反分割保留鎖定限制，terminal可消滅鎖定持股；365檔固定來源兩環境20檔相關各252passed／Lint通過。回傳尚非已入帳inventory，N3／新版SQL仍待；政策授權同名檔衝突已以獨立測試及證據路徑保留雙方。最新證據用 `M12-5/opening-lot-projection-20261030-main/` 及原授權恢復 `explicit-authorization-20261030-main/`，不混用舊rights-payment-policy目錄目前metadata。詳見 EXECUTION_STATUS。

2026-10-30 執行更新：N1／RI-01已有明確參與、當日cutoff與付款授權API，356檔固定來源兩環境相關各207passed／Lint通過，含實際T+2早截止拒絕與晚截止付款。仍待外層原授權認證／原子保存、交易付款排程與連續workflow；N1整體不標accepted。詳見 EXECUTION_STATUS 及 `M12-5/rights-payment-policy/`；下方規劃保留其制定時點。

## 2026-10-30 下一個實作切片

已有 projection 與開盤 sale-cap 的定向證據，下一單元改以[下一輪 N1／N2](NEXT_DELIVERY_20261030.md#權利整合接下來六個可驗收單元)的參與／cutoff 政策及 post-event lot 契約為起點，再接連續日、NAV 與新版 SQL。下方「下一個實作單元 RI-00 → RI-01」等段落保留原輪時點；未滿足的 RI 退出條件仍有效。

更新：2026-10-30（Asia/Taipei）。本文件是接續規劃，未實作的介面與驗收項目均不代表已通過。
總排程見 [目前交付計畫](CURRENT_DELIVERY.md)；維持十萬元台股零股研究、虛擬資金及版本 `0.12.3`。

完整catalog封存更新：AuthorizedRightsAccount已合併完整凍結目錄、原授權與inventory，精確codec／獨立archive核驗及實際T+2逐日重開均有結果；378固定來源34檔兩環境各328passed。剩餘是將這份合併狀態與engine／lot／rights／NAV／risk連續流程在新版SQL同transaction保存，並完成註冊／來源錨點、UI及完整發布閘門；本輪codec不冒充durable writer。

政策命令更新：明確參與／每日cutoff／policy ID已寫policy_election原始receipt，支持獨立重建及codec重開，21新增案例通過。367-source相關29檔兩環境各319項執行通過，含authorization舊／新路徑重複執行；來源與恢復紀錄在rights-policy-receipts。RI-01尚須把真正凍結action／batch的原PaymentAuthorization綁進新receipt並連到registered protocol，才進連續／durable自動編排；不以兩個局部API代替這個退出條件。

NAV執行接續：RightsSessionNAV／value_session_nav已能將實際session的交割／碎股應收與current rights inventory估值合併，核對原engine equity及市場quote；355固定來源相關23檔兩環境各220passed／Lint通過。RI-03尚缺凍結估值政策、連續workflow與獨立持久化NAV重建，不能從此API推成整列完成；RI-01參與／cutoff為下一個契約單元，另與post-event lot來源線接續。

較晚執行：RI-02／03的開盤限額已由共用session／撮合消費，獨立session／inventory重建核對；350檔固定來源相關22檔兩環境各205passed／Lint通過。開盤當日重新核對解鎖日期，保留locked持股與stop重試；post-event lot轉換、完整編排／NAV／SQL等仍未完成。下段與表列退出條件保留，不把此局部結果推成整案accepted。

執行更新：RI-00證據與RI-01隔日projection已交付局部範圍，固定346檔來源的相關15檔兩環境各153passed／Lint通過，來源前後不變；見 EXECUTION_STATUS 及 `artifacts/acceptance/M12-5/rights-session-projection/`。下方介面提案中RightsSessionProjection已實作；政策、鎖定lot執行、連續編排、NAV／stop及SQL等退出條件仍待完成，不把整列RI-01標accepted。

## 已核對的起點

`odd_lot_rights/` 已有權利分腿、付款／交付／轉換、獨立重建、持股 lot 與精確序列化。
既有 session 回傳前會核驗現金、持股與交割；新增 `post_engine_session` 可將實際 engine 結果寫入同一權利帳戶。
此次讀取的兩套定向 log 各為 112 passed（3.13：1.32 秒；3.9：1.89 秒），範圍為 rights 與 session-link／flow 測試，並非最新來源完整回歸或正式事件驗收。
原紀錄位於 `/private/tmp/qfl-rights-flow-final313.log` 及 `/private/tmp/qfl-rights-flow-final39.log`；仍需封存命令、來源身分與案例對照後才作正式交接證據。

目前實例能證明賣款尚未 T+2 入帳時無法付款、入帳後才能認購；尚未證明付款或交付後能連續運行隔日 engine。
`post_engine_session` 尚未由持久化 workflow 自動呼叫；合法 SHA 字串也不證明事件事實或公告時點。
不再將上述既有核心排為從零開發，接續只補下列整合差異。

## 必須先固定的狀態與處理契約

先提交型別／公開介面及其測試，再寫 orchestration。以下名稱為提案，實作前與現有型別對齊。

| 提案契約 | 必須表達的內容 | 禁止隱含的假設 |
| --- | --- | --- |
| `RightsSessionPolicy` | 參與選擇、付款時點／現金優先序、未參與與碎股處置、估值規則、時區／cutoff、版本與指紋 | 不以現金足夠自動推定參與，不看未來價格決定認購 |
| `RightsSessionProjection` | 權利帳戶到 engine 的可用現金、整數持股、可交易數量；保留 obligations／stop／訊號狀態與來源 checkpoint | 不把未交割賣款當現金，不把未交付權利當股票，不另建可支用餘額 |
| `RightsSessionCommand` | session、日內階段、事件／leg、action ID、可得時點、已驗證來源、明確數量及費用 | 日期相同不代表可在開盤或付款截止前使用資訊 |
| `RightsAwareCheckpoint` | engine state、權利帳戶、當日命令／posting、估值來源、政策與 parent digest；獨立 schema | 不覆寫 checkpoint-v1 或靜默改讀舊帳戶 |

交易與公司行動順序沿用既有 engine；新增權利階段須明確選定插入點。
至少區分前一日收盤持有基礎、當日可得資訊、付款截止、交易／交割及收盤估值。
現有 session link 是收盤邊界，不能推定收盤才入帳的 T+2 賣款可支付當日較早截止的認購。
遇到只有日期、缺 cutoff 的真實條款，保持 unknown／blocked；fixture 可用明確聲明的時點驗證工程。

## 按相依順序交付

| 工作包 | 最小交付 | 退出條件 | 案例關聯 |
| --- | --- | --- | --- |
| RI-00／證據整理 | 封存既有 session-flow 的命令、兩套 logs、來源／測試 hash、失敗歷史及範圍 | 能辨識測試時來源；無法還原者明列不明並重跑固定來源，不補造身分 | B01、E-A07、L-A05／A07 |
| RI-01／政策與回接 | 先定上表契約；將權利命令結果投影到下一 session 的 engine 輸入 | 付款後隔日 cash 減少且不復原；交付後股數正確；未到可交易日不送可成交賣單；原 obligations／stop 不丟失 | E-A07、L-A01／A05 |
| RI-02／連續日核心 | 用一個明確入口串接 engine、session-flow、權利命令及獨立重建 | 買進→賣出→T+2→付款→交付→轉換→隔日交易連續一致；同日截止／資金競用依凍結政策處理；無命令時與舊路徑一致 | L-A03／A05／A07／A11 |
| RI-03／lot、風險與 NAV | 同一份持股來源處理可交易性、stop、事件與價值轉移 | 混合可交易／鎖定 lot、部分賣出、分割／反分割與碎股、receipt 已賣再轉換有直接案例；cash／rights／stock 不重算價值 | E-A06／A07、L-A07／A11 |
| RI-04／新 durable 格式 | 新 schema、純讀 loader、原子 SQL 提交、來源與政策綁定；明確新帳戶／另路徑重建 | rights／engine／posting／完成標記同 transaction；任一步故障重開無半套狀態；舊 v1 bytes 保留且不自動遷移 | L-A02／A04／A06／A10／A12 |
| RI-05／事件 adapter | 2881、2882 分別產生有來源與可得時點的命令；未知欄位阻擋 | 官方事實表、手算、來源驗證、歷史資訊時點、security identity、費用與政策齊備，才解除相應事件阻擋 | E-A05／A07、S-A02 |
| RI-06／操作與整體驗收 | UI 只呼叫共用 workflow；完整對照與篡改反例；最終來源完整驗證 | 一次／逐日／每個合法 checkpoint 重開結果一致；重送 no-op、換 payload 拒絕；兩環境 Lint／完整 suite 及舊包 reader 核驗有終局 | J05、L-A03／A06／A10／A12 |

RI-05 的官方調查可與 RI-01–04 的離線 fixture 工程交錯進行；真實事件啟用需兩條線都通過。
各列只提供案例關聯，沒有將整案標記 accepted。RI-01 與 RI-02 分開提交，先證明回接，再擴成連續日流程。

## 最小驗收資料集與反例

1. 資金：買款保留、負賣款費用、T+2 正賣款、利息、認購付款同時存在；逐日手算與獨立 audit 一致，費用／現金各只入帳一次。
2. 時點：付款截止前後、同日交割較晚入帳、available_at 在 cutoff 後、未來公告、非交易日交付，各依明確政策接受或拒絕。
3. 持股：同證券混合鎖定／可交易 lot、交付後部分賣出、receipt 轉換、bonus 碎股；持有數與可賣數各自核驗。
4. 風險：既有 stop／退出重試不因投影消失；新交付或 receipt 的風險身分與估值缺失不能靜默沿用母股價格或成本。
5. 故障：付款、交付、posting、NAV、SQL insert 與 commit 前分別注入中斷；恢復後 digest、cash、rights、lots、obligations、stop 與不中斷版本相同。
6. 篡改：重算 hash 後替換來源、資格基礎、可得時點、policy、mark 或 SQL linkage 仍拒絕；原帳戶 bytes 保留。

未知權利缺 mark 時不得以零值產生正式 NAV；實際拒絕或暫停估值的行為須寫入政策與 UI。
現有 Decimal 權利帳務與 engine float 邊界需列出轉換、精度與容忍度；不得以放寬 tolerance 掩蓋系統性差額。

## 真實資料與研究交接

現行研究 `195e874e86026da7a9209f95` 三期仍 blocked 28／23／23，active coverage 23；27 筆 raw issues 與 29 筆 active findings 的口徑分開。
先核對普通股 split 10 筆、other_rights 11 筆、0050 par_value 1 筆及 2024 年起 reduction 1 筆的來源範圍，再按開發期與暖機優先重凍結。
coverage 通過不替代兩個未建模權利的事件驗收；權利引擎通過也不證明 coverage 完整。

2881／2882 沿用 [事件調查](EVENT_INVESTIGATION.md) 的未知欄位，分腿列資格、最終比例、付款窗口、交付／可交易日、receipt 身分、費用及可得時點。
較晚年報可協助核對事實；不能直接充當除權當時已知的證明。若改池／改期間，另建 scope-change、協議與 study，保留資料接觸紀錄。

資料與事件條件通過後，才執行事前有限候選、先保存開發選擇再驗證。正式結果可以是退回或樣本不足；不以正報酬為驗收目標。
實際前向另需有效 continue、未來登記日及新 session 的合格取得證據；fixture／歷史重播不計入觀察樣本。

## 本輪排程與停止條件

下一個實作單元是 **RI-00 → RI-01**，不是直接改 SQL 或解除真實事件阻擋。
既有 329 檔完整驗證依原紀錄追蹤；凍結副本不修改，較晚 session／rights 變更列為差異，發布前另固定最終來源。
同機完整 suite 以明確 Python 3.13 → 3.9 循序執行；局部通過不替代完整終局。

每輪交付型別／介面、最小實作、Lint／相關單測、證據與剩餘缺口；共享引擎變更及發布候選再執行完整 gates。
工期在 RI-01 契約及 RI-05 事實表審查後重估；外部證據等待、完整回歸與實際前向觀察時間分列。
新策略、額外市場與部署於本主線具備可交接驗收結果後再排序。工程發布、真實歷史研究與實際前向三項各自放行。
