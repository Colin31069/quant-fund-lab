# 下一輪發展與交付順序

2026-10-30 最新：registered_source已核對原StudyProtocol／readonly registry／ready raw study與catalog所有行情／liquidity／候選設定，registered歷史SQL入口提交前重驗；418固定來源兩環境相關各73passed／Lint通過。證據 `M14/registered-source-20261030-main/`。此入口仍拒絕未由正式rights supplement認證的命令／marks／risk，不啟用future；完整真實事件、UI與最終驗收仍待。

2026-10-30 最新：RightsRequestCatalog已固定ledger root／config及每筆archive／input／predecessor身分，版本追加保留prefix，SQL只在完整歷史重播後接納下一筆；完成重試不重送。410固定來源兩環境相關各422passed／Lint通過；證據 `M14/request-catalog-20261030-main-b/`。這是本機內容凍結，正式protocol／trusted handoff、UI及最終整合與真實資料驗收仍待。

2026-10-30 最新：每日請求已有可攜完整codec／checksum-pinned archive loader，commit_archived_day及verify_archived_days實際串SQL提交／唯讀重播，七日案例可丟棄原Python請求後從檔案重建。403固定來源兩環境相關各404passed／Lint通過；證據 `M14/day-request-archive-20261030-main-c/`。外部checksum catalog與protocol／UI認證、增量prefix、真實事件與最終整合驗收仍待。

2026-10-30 最新：commit_rights_day已接共用day workflow到既有新版原子SQL，並有外部原請求逐日唯讀重播；395檔固定來源兩環境相關各353passed／Lint通過，含七日收據生命週期、8個中斷故障及重算NAV hash反例。證據 `M14/durable-day-workflow-20261030-main/`。仍待source/request archive與認證、獨立persisted risk／NAV audit、UI及最終整合驗證；真實資料／前向未放行。

2026-10-30 最新：收據部分賣出→剩餘轉換→final鎖定退出／解鎖再賣已有明確風險轉移，advance_rights_day共用授權封存、lot執行入帳、after-close命令及projection。389檔固定來源兩環境相關各311passed／Lint通過；證據 `M12-5/receipt-day-workflow-20261030-main/`。接續combined checkpoint／獨立durable audit／原子SQL與UI；after-close入口不能處理較早deadline或資格時點。350原full兩profile已失敗終局，J05 fixture日期anchor修正仍須另驗；真實研究／前向未解除。

2026-10-30 最新：公司行動lot投影已接共同入帳，new portfolio_lot_session獨立重建events／fills／cash，projection及NAV可續接新舊session。377檔固定來源兩環境相關各271passed／Lint通過，含T+2→認購→隔日BUY與CIL／NAV手算、重開及重算hash反例。證據 `M12-5/lot-session-posting-20261030-main-b/`；仍待自動階段編排、完整交付／轉換、combined durable／新版SQL／UI及來源認證，N3整體未accepted。

2026-10-30 最新：329固定來源兩環境完整各907passed／Lint通過且來源hash不變；350排程已轉running313，尚非終局。付款授權已共用canonical policy_election收據，最後367來源去除重複收集後兩環境相關各257passed；原必要case語句全保留。證據用 `M12-5/canonical-authorization-20261030-main-b/`，下方舊「原329仍running」等描述保留歷史。接續N3連續流程／新版SQL與最終來源完整驗證，真實研究／前向未放行。

2026-10-30 執行更新：N2已有post-event lot投影及真正session wrapper，分割／反分割保留鎖定限制，terminal可消滅鎖定持股；365檔固定來源兩環境20檔相關各252passed／Lint通過。回傳尚非已入帳inventory，N3／新版SQL仍待；政策授權同名檔衝突已以獨立測試及證據路徑保留雙方。最新證據用 `M12-5/opening-lot-projection-20261030-main/` 及原授權恢復 `explicit-authorization-20261030-main/`，不混用舊rights-payment-policy目錄目前metadata。詳見 EXECUTION_STATUS。

2026-10-30 執行更新：N1／RI-01已有明確參與、當日cutoff與付款授權API，356檔固定來源兩環境相關各207passed／Lint通過，含實際T+2早截止拒絕與晚截止付款。仍待外層原授權認證／原子保存、交易付款排程與連續workflow；N1整體不標accepted。詳見 EXECUTION_STATUS 及 `M12-5/rights-payment-policy/`；下方規劃保留其制定時點。

更新：2026-10-30（Asia/Taipei）。本輪只更新規劃；以下未執行項目不是完成證據。
本文件補充 [目前交付計畫](CURRENT_DELIVERY.md)，將最新實作差異拆成下一輪工作單；舊排程保留作歷史。
範圍維持十萬元台股零股研究與虛擬帳戶，版本維持 `0.12.3`。

## 本輪核對基線

| 可核對狀態 | 規劃含義 |
| --- | --- |
| 329 檔固定來源：3.13 完整 907 passed；原 session35967 本輪 poll 仍存活，3.9 尚無終局紀錄 | 保留原程序，不重啟；907 不覆蓋較晚 shared engine 與新測試 |
| 350 檔 rights-sale-limits：兩環境定向各 205 passed；full-job.json 為 waiting_for_prior_terminal | 已有等待中的完整排程；先查它的狀態，再安排其他重案例，不另開同範圍 full |
| 已有付款後隔日 cash 回接、交付後持股投影、混合 lot 開盤可賣數及獨立核對 | 接續補政策與連續編排，毋須重做核心 |
| 80 案都有 evidence mapping，accepted 尚未完成逐案審查 | 依 assertion、來源及必要範圍審查；測試總數不作自動驗收 |
| 真實 study `195e874e86026da7a9209f95` 三期 blocked 28／23／23，績效 0 | 先完成資料與事件條件，才安排正式研究 |

原完整結果見 `artifacts/acceptance/release/integrated-20261030-b/verification-results.json`；
等待排程見 `artifacts/acceptance/M12-5/rights-sale-limits/full-job.json`。
排程檔不證明程序存活或測試通過；每次接續均核對原 handle、實際 logs、exit code 及來源 inventory。

## 先收斂已在進行的驗證

1. 追原 329 檔兩環境終局。若 handle 缺失，保留部分結果並標明未終局，不推定成功。
2. 核對已等待的 350 檔 runner：它會在兩個原 profile 都留下終局後循序執行 3.13 → 3.9。
   等待逾時只表示未取得前置紀錄；先核對原排程與副本完整性，再決定恢復方式，不直接另開重複程序。
3. 同機 full 終局後，循序執行已封存 332 檔的 J-A05 三個 registered 報告案例：29／30、30／29、30／30。
   collect-only 與 schedule 測試不替代報告案例；失敗先定位，修正後另立來源身分。
4. 以預定交付 reader 核驗 native 舊包；保存舊包 bytes。若後續修改 reader，重新評估相關相容證據。
5. 逐案審 80 案，列出本次工程交付必需項、已驗範圍與延後範圍。350 檔只證明該 inventory，之後新增內容另列。

以上重型工作共用一條執行順序；等待 full 時可進行文件、來源調查與必要的輕量定向核對。
本輪未啟動或修改任何驗證 runner。

## 權利整合：接下來六個可驗收單元

各單元先定型別與公開介面，再做最小實作、Lint／單測、證據與缺口登記。
提案名稱須與既有型別對齊；不要求為了名稱另建重複 API。

| 順序 | 最小交付與邊界 | 必須通過的退出條件 |
| --- | --- | --- |
| N1 政策與日內時點 | 完成 `RightsSessionPolicy`／command 契約；明列參與選擇、時區、cutoff、現金優先序、費用及未知處理 | 未明確選擇不得自動認購；同日較晚 T+2 入帳不能支付較早截止；截止前後、未來 available_at 與資金競用均有反例；政策改動形成新身分 |
| N2 公司行動與 lot | 在開盤 cap 前完成 split／反分割／終止／receipt 轉換後的 inventory 轉換，沿用同一持股來源 | 股數、可交易數、碎股及現金守恆；receipt 已部分賣出再轉換不多交股；開盤 cap 與實際 post-event 持股一致；原帳戶狀態不改寫 |
| N3 連續 session | 單一入口依明確階段串接既有 engine、權利命令、projection、session posting 與獨立重建 | 買進→賣出→T+2→付款→交付→轉換→再交易逐日手算一致；無權利命令與舊路徑對照；同 action 重送 no-op、變更 payload 拒絕 |
| N4 NAV 與風險 | 凍結 rights／receipt／stock 估值與 stop 規則，明列 Decimal／float 邊界 | 價值轉移不重複；未交付權利不當股票；缺 mark 阻擋正式 NAV；混合 lot 部分退出後 stop 重試保留；價格身分不沿用母股猜測 |
| N5 新版 durable | 先定 `RightsAwareCheckpoint` 與獨立 schema／loader，再原子寫入 engine、rights、lots、posting、完成標記 | 各寫入與 commit 故障重開同結果；SQL linkage 與重算 hash 篡改拒絕；舊 checkpoint-v1 純讀及 bytes 保留；不靜默遷移 |
| N6 操作與整合驗收 | UI 呼叫同一 workflow，明列來源阻擋及錯誤；封存預定交付的最終來源 | 一次跑、逐日跑、合法 checkpoint 重開一致；讀取與 rerender 不寫入；同一來源兩環境完整 gates、必要 UI 與舊包核驗皆有終局 |

N1、N2 先固定消費契約，再接 N3；N4 的估值型別可先設計，實際案例接 N3；N5 依完整狀態契約落地，N6 收斂交付。
詳細 RI 編號與原案例對照沿用 [權利整合計畫](RIGHTS_INTEGRATION_NEXT.md)，本表不是新的驗收矩陣。

## 資料線：分項核銷，依期間交接

23 筆 active coverage 分為普通股 split 10、other_rights 11、0050 par_value 1、2024 年起 reduction 1。
先處理開發期與暖機所需範圍，再交驗證期及後續歷史期；每項保留適用證券／事件／期間、原始 bytes／hash、來源及審查理由。
查無事件不自動等於完整 coverage；405 個取得月份、adapter 接入及官方匯入分開記錄。

2881／2021-09-06、2882／2022-12-05 各交分腿事實表：資格、最終比例、價格、付款窗口／cutoff、交付日、可交易日、receipt 身分、碎股／費用及資訊可得時點。
二手資料可提供查找線索；正式事實連結第一手原文、頁碼及 bytes。較晚年報不直接證明歷史當時可得。
缺欄位保留 unknown；N1–N6 的 fixture 通過不解除真實事件阻擋。

來源 adapter 必須同時驗證事實與可得時點，再依凍結政策產生命令；有效 SHA 字串本身不能認證事件。
coverage 與事件能力各自通過後，以新來源／study 身分重新產生 readiness，不手改舊報告。

## 三個交付切點

| 切點 | 放行條件 | 可交付結果 |
| --- | --- | --- |
| 工程版本 | 預定範圍的最終來源雙環境完整驗證、必要案例逐案審查、UI／相容證據通過 | 可重現的研究與虛擬帳戶工具，隨版列明仍阻擋的資料／事件；版本升級於驗收後決定 |
| 正式歷史研究 | 相依期間 ready、來源／政策／候選預算事前凍結、開發選擇先保存、驗證失敗不補位 | 可重現的研究結論；退回、樣本不足與不獲利都是有效結果；既有已接觸資料保留探索性標記 |
| 實際前向 | 有效 continue、未來開始日登記、新 session 的來源取得與帳務證據合格 | 獨立虛擬觀察帳戶及實際累積樣本；歷史重播與 fixture 不計入 |

外部資料仍未知時，可先交已驗的工程範圍；不得以工程結果代替研究或前向放行。
本階段先完成上述主線；新策略、新市場、部署與視覺改版在主線驗收後另排，真實券商與真實訂單不在範圍內。

## 下一次交接清單

- 一份最新狀態表：原 329／等待 350 的實際終局或未完成原因、J05 與 native 結果，各綁來源 inventory。
- N1 型別／介面與 cutoff／資金競用的最小案例；N2 的 post-event lot 轉換契約。
- 23 筆 coverage 與兩事件事實表各自列已知／未知／下一來源，禁止只列總完成百分比。
- 每個新增單元附命令、runtime、exit code、來源身分、assertion、剩餘缺口；未滿足必要條件不標 accepted。

工程工作量待 N1／N2 契約與必要案例審查後重估；外部證據等待、完整回歸耗時及前向樣本累積分列，不承諾尚無依據的完成日期。
