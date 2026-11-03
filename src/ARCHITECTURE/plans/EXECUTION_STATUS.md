# 執行進度

## 2026-10-30 接續：真正StudyProtocol／原生registry與catalog admission綁定

- 先定RightsProtocolAdmission，再新增verify_rights_protocol與commit_protocol_catalog_day。讀實際frozen StudyProtocol及enforced read-only ExperimentRegistry，必須已登記且內容相同；catalog.protocol_sha為實際protocol_id，execution_sha為目前執行checkout／runtime的identity，source_directory必須是執行package根。calendar_sha核對protocol修訂清單的canonical digest，不冒充第二份官方日曆認證。
- 每個原archive重讀expected SHA，核對session／day input／settings、候選完整research及由凍結base轉出的engine config、declared universe及period；候選／期間不在預定協議即拒絕。此入口明確historical-only，不接受forward_observation，不能拿本機registered成功冒充有效continue、實際前向或issuer readiness。
- 真正commit走既有catalog prefix／三層audit／atomic workflow；各SQL fault邊界重查protocol／registry／current code與原protocol envelope bytes。checkpoint及before_commit替換合法recorded_at envelope亦整日rollback；相同全完成catalog重送保持no-op。缺registry不初始化，成功後原protocol／registry bytes不改。
- 新15直接case以原生freeze_protocol／ExperimentRegistry fixture執行，錯protocol／execution／calendar／candidate／period、未registered、真協議但settings／universe／日期不符及forward誤用均有實際拒絕。419檔固定副本8檔相關targets兩環境各 **98passed（37.90／48.72秒）**、verify.sh環境／Lint通過，419份前後hash不變；snapshot Git僅供source identity，原checkout未commit。證據在`M14/protocol-admission-root-20261030/`；不是完整repo回歸。
- 原64978本輪actual poll仍存活，390-source full313未終局，未改副本／重啟，不含本次419變更。接續將本機protocol admission與可信source／reviewed事件契約及公開操作入口完整結合，最後來源full／native／80案逐案結案；不以新wrapper或98測試數宣告大里程碑accepted。
- 官方source／公告當時可得、真實事件、coverage、有效決策及實際forward仍須各自核驗；本機protocol／registry integrity不證明歷史preregistration。真實28／23／23 blocked與整體未完成狀態不變。

## 2026-10-30 接續：原協議／registry／frozen raw驗證接歷史目錄入帳

- 新RegisteredRightsSource／RegisteredRightsAssessment先定型別，再交authenticate_registered_catalog，真正load原StudyProtocol、ReadOnlyExperimentRegistry及raw-backed candidate study；核對目前執行package與source identity、catalog protocol／execution／calendar、declared candidate／historical period、ready source及clean cash-only root。每筆archive完整行情／prior liquidity、research／engine設定、origin／session與frozen study精確對照。
- commit_registered_catalog_day已接public catalog admission，在preflight／SQL fault邊界重驗來源／協議／registry／code；原raw於before_commit被改即整日rollback。verify_registered_catalog同時做純讀source authentication及catalog完整歷史重播；缺registry不初始化，既有registry bytes保留。
- 現有StudyProtocol精確固定analysis_plan，不可偷偷加入rights政策沿舊ID。本輪入口因此明確拒絕selected rights elections、未認證grant／pay／deliver命令、new stop／conversion risk及rights mark；它不是完整真實事件入口的替代品。後續須正式權利supplement／adapter與新研究身分，才能解除對應缺口。原historical／exploratory標記保留，future unseen protocol也無法由本入口啟用forward。
- 新16直接case使用真正ready native study／frozen protocol／registered registry及SQL正例，另有missing registry、undeclared候選／period、wrong execution／protocol／calendar、raw tamper及合法重算archive後改volume／liquidity／research的反例。額外未認證grant／risk／mark全部拒絕；真正註冊2027 unseen fixture也被historical入口拒絕，未造前向樣本。
- 固定418檔 `/private/tmp/qfl-main-registered-source-jmwrbcj3`，六檔相關targets兩環境各73passed／環境／Lint通過，418份前後hash不變；實際秒數列下方。來源tar、命令／exit0、runtime／snapshot import probes與partial案例scope在 `M14/registered-source-20261030-main/`；不是最新repo完整回歸。
- 接續權利政策正式supplement／來源可得時點認證與操作UI，再收斂final-source full／native／80逐案。390原完整排程仍另行運行，不覆蓋418本輪；實際2881／2882、coverage／readiness28／23／23及真正前向觀察均未放行，goal／accepted維持in_progress／false。

實際結果：73 passed in 42.28s；73 passed in 58.41s。


## 2026-10-30 接續：共用封存三層核驗與主UI唯讀權利帳戶

- verify_archived_days現必須先跑獨立persisted NAV及risk，再跑原請求行為重播；catalog prefix驗證沿同一入口，不會只重播而漏掉獨立方程。新4例證明正例三層全執行，重算hash後的NAV／stop／missing risk evidence均在production replay前拒絕，唯讀ledger／archive bytes不變。
- 新RightsCatalogInspection／inspect_rights_catalog以外部保存的catalog SHA載入目錄，唯讀開啟既有regular SQLite，核驗完整prefix並列cash／NAV／held units／完成與pending日數。缺帳戶不建立，錯SHA、symlink、被改archive拒絕；後續補強連pending archive也驗session／input／settings與內容，不以「尚未完成」略過檔案檢查。
- 主Streamlit新增預設關閉的「權利事件帳戶唯讀核驗」入口，獨立inspection_ui表單僅明確submit才呼叫共用backend；不暴露建立／commit動作。真AppTest使用實際catalog／SQL，顯示本機NAV／risk／重播核驗與來源／正式協議仍待認證。rerender不重跑／不寫入，空表單不建檔；主頁入口也實際點選驗證。
- 首413固定來源較廣相關targets兩環境各 **400passed（47.93／63.60秒）**、環境／Lint通過，所有413檔前後不變，證據在`M14/archive-inspection-root-20261030/`。其中不含較晚pending reference補強；該補強另凍結413來源，3個直接test檔兩環境各 **14passed（6.73／8.50秒）**、環境／Lint通過且來源不變，證據在`M14/archive-inspection-pending-root-20261030/`。兩輪來源分列，不把後改範圍硬套原400結果。
- 改動主ui.py僅新增optional branch，未重構原大檔／刪文檔。新inspection與tests皆低於300行。原390 full64978本輪actual poll仍存活，full313已推進約六成未終局，沒有修改來源／重啟；不含目前413的新code。新局部結果不當完整發布證據。
- 下一步正式protocol／registration與可信source review接catalog admission，收斂最終full／native／UI操作矩陣及真實資料。唯讀頁核驗成功不代表實際事件或forward啟用，catalog checksum仍須外部認證；真實28／23／23 blocked與整體accepted false不變。

## 2026-10-30 接續：每日請求目錄綁定帳戶與歷史前綴

- 先定RequestCatalogEntry／RightsRequestCatalog，再交append／extension check及canonical codec。完整六項ledger config與initial checkpoint固定在目錄ID；每entry明列session、archive SHA、day input SHA與predecessor checkpoint SHA。append先完整prepare核對當日請求／marks／前態，保留原entries並指向parent catalog ID。
- freeze_request_catalog只允許空root或一筆extension，temporary flush／fsync及exclusive link發布，不覆蓋原版本；load需外部expected catalog SHA，schema／duplicate／unknown拒絕。此為本機內容凍結，不認證正式StudyProtocol、reviewer批准或歷史可得時點。
- verify_catalog_ledger與真正ledger root／settings核對，逐completed entry比對input／前checkpoint並由原archives重播完整前綴；commit_catalog_day只接一個pending next entry。全部完成再操作只驗證回None，不自動新執行；舊catalog不可漏已完成歷史。transaction各fault階段重查catalog身分與所有原archive，前一已完成archive被改亦rollback新day。
- 新11例含七版目錄freeze／load／逐日SQL進入，共同receipt生命週期最終cash550、每次NAV1050，舊catalog全部bytes保留。root／protocol／settings、已完成source／predecessor、缺歷史、父版本、stale append及合法重寫archive均拒絕；改前archive於新day before_commit仍恢復原SQL前態。
- 首409固定副本兩profile在共享新增catalog_inspection缺future annotations的Lint失敗，沒有pytest，原來源／logs保存；該處由原工作流補好後才取新410副本，未回寫失敗快照。410副本 `/private/tmp/qfl-main-request-catalog-b-bk03zg98` 相關targets兩環境各422passed／Lint／環境檢查通過，秒數見下列實際result；410份前後hash不變。包含共享readonly inspection direct tests，不宣稱完成UI。
- 證據 `M14/request-catalog-20261030-main-b/` 保存source tar、命令／exit0、runtime／snapshot import probes與case scope。原有390-source完整gates另在運行，不覆蓋本輪410；80案仍逐案accepted false。
- 接續正式protocol／registry／trusted catalog handoff與UI。整份market frame指紋仍非增量prefix，較早銀行deadline／pre-opening資格及真實事件來源認證未放行；最終full／native／逐案審查及真實28／23／23、實際forward仍未完成。

本輪實際結果：422 passed in 40.63s；422 passed in 56.99s。


## 2026-10-30 接續：提交前／封存後的獨立止損與收據風險核驗

- 先定DayRiskAudit與PersistedRiskAudit，再新增day_risk_audit／persisted_risk_audit。先沿既有獨立reconcile_risk_state核對engine close的stop／pending／terminated／passive flag，再獨立由原convert commands、持股與明列mapping重建收據／final的stop與exit；不呼叫production signal planner／conversion transfer。映射缺失、final退出quantity／reason錯、遺失stop／exit、任意改retained settlements／offset／terminated均拒絕。
- prepare_durable_day實際接獨立risk gate，在NAV及SQL record前執行；注入production projection stop+1後拒絕，原ledger與完成日數不變。新events保存pre-rights engine_close checkpoint；verify_persisted_risk唯讀使用SQL原signals／fills／actions與外部原observations／mapping，逐日核對，不重跑production workflow。改final stop並重算state／completion hash後，financial／storage仍可通過，但獨立risk核驗拒絕，唯讀bytes保持。
- 新13直接case包含真實receipt部分賣出、轉換後final退出3股；禁止production signal／transfer／workflow replay函式後獨立正例仍通過。先前新persisted test首跑1fail／12pass源於漏import payload_digest helper，已補測試import、不改產品守門，原console觀測／無完整redirected log邊界在initial-checks.json。
- 404檔固定副本相關targets兩環境各 **379passed（23.37／31.42秒）**、verify.sh環境／Lint通過，404檔前後hash不變；產品接線與新test亦核對當前bytes同snapshot。來源、命令／exit0、局部scope在`M14/independent-risk-root-20261030/`，不代替整repo完整回歸。安裝preflight仍main editable，pytest明列snapshot/src。
- 原64978本輪actual poll仍存活，390-source full313未終局，未修改副本／重啟；本次404來源不在其inventory。下步來源／完整request封存認證與protocol／registration接公開操作入口，收斂最終full／native／UI；策略alpha與新instrument stop仍是聲明輸入，不把方程核對當獨立策略有效性證明。
- 舊記錄缺engine_close風險evidence時此audit明確不足，不自動修復／遷移。真實研究仍28／23／23 blocked，官方事件／coverage與實際前向各自未accepted，整體未完成。

## 2026-10-30 接續：原始每日請求可攜封存／載入與SQL重播

- 新request_values_codec用封閉型別registry保存精確Decimal／scalar kinds、tuple／dict、明確frame values／dtype／DatetimeIndex metadata；不從輸入名稱import任意class。day_request_codec保存完整prior engine checkpoint、AuthorizedRightsAccount、market／liquidity／settings、commands／clocks／corporate events／risk mappings／marks，載入後重新canonical編碼比對。extra／duplicate／unknown／missing／version及不支援dtype拒絕。
- DayRequestArchive明列path與外部expected checksum。archive_day_request先重建驗證，temporary sibling flush／fsync後exclusive link publication，existing file驗原bytes不覆蓋，拒絕symlink路徑；load_day_archive前後驗bytes。檔案checksum不是自我來源認證，reviewed catalog仍需外部保存／認證。
- commit_archived_day載入原請求再走public atomic SQL workflow，SQL各fault階段重查archive；verify_archived_days從整份外部pin的catalog重新載入原請求做唯讀重播。新13例逐日del原Python請求、檔案載入、SQL commit／close／reopen共七日receipt生命週期，cash最終550、各日NAV1050；readonly全歷史replay不改ledger bytes。合法但重寫的valuation時點仍被原expected SHA拒絕，checkpoint／before_commit改archive整日rollback。
- CIL日期NaT／timestamp、currency object frame、float NaN、exact fees與revision／expire／fraction／conversion risk型別可roundtrip；codec不執行也不認證那些未使用command的時點合法性。不支援complex等dtype明確拒絕，第一版不以默默cast改來源。
- 首401-source與次402-source兩profile均在Lint終局失敗、沒有pytest：分別共享新增day_risk_audit未用asdict與其新test未用inputs。各patch送達前已由原工作流修正，未修改失敗副本、未覆蓋對方內容；失敗logs／inventory保留。第三403-source `/private/tmp/qfl-main-day-archive-c-46uu2iy8`兩環境相關各 **404passed（22.90／31.82秒）**、環境／Lint通過，403份前後hash不變，包含共享獨立risk／NAV targets；不是完整suite。
- 來源tar、實際命令／exit0、runtime／snapshot import probe與scope在 `M14/day-request-archive-20261030-main-c/`。目前四個新增code／test bytes仍匹配該固定來源；80案索引重建，不自動accepted。
- 接續reviewed request catalog／protocol註冊綁定及UI；source／公告歷史可得時點仍待認證。完整frames指紋不等於增量prefix契約，pre-opening資格與early bank deadline也不由after-close入口放行。390來源原full仍另排程執行、不覆蓋403本輪變更；最終full／native／逐案審查、真實readiness28／23／23與實際前向仍未結。


## 2026-10-30 接續：SQL提交前與封存後的獨立NAV方程核驗

- 新CheckpointNAVAudit／audit_checkpoint_nav先定介面，獨立從combined checkpoint、原session link、完整rights positions、lots、外部raw／mark與未結settlements重算11個數值欄。cash、held、unpaid、pending、positive sale／fractional receivable各一次；buy／fee-shortfall payables只披露不再扣NAV。每筆mark檢查完整性、當期、available_at、SHA引用與市場quote／TWD；外部資料真實性仍須來源認證。
- prepare_durable_day現實際在準備commit前呼叫獨立核驗；注入production NAV及held同時+1，獨立方程拒絕，SQL沒有完成日、原帳戶不變。不是只新建無接線的工具。新verify_persisted_nav對SQL的joined NAV讀回，以外部原day marks核驗，不呼叫production engine／workflow replay／valuation；重算event／completion hash後，ledger.verify可通過但此獨立核驗拒絕，唯讀bytes保留。
- 新26直接案例含每個numeric component單獨改值、wrong session/action、future／stale／missing／duplicate marks、錯quote／幣別、float冒充Decimal；實際engine買賣／T+2／認購的每個checkpoint通過，反分割＋股利的碎股應收98及NAV420也獨立重建。monkeypatch禁止production NAV／inventory／book valuation與workflow replay後，獨立核驗仍通過正例。
- 397檔固定副本相關targets兩環境各 **361passed（18.88／26.28秒）**、verify.sh環境／Lint通過，397檔前後hash不變；新核驗與接線產品檔對照snapshot一致。來源、完整命令／exit0及partial case mapping在`M14/independent-nav-root-20261030/`。安裝preflight檢查main editable install，pytest明列snapshot/src；不是整個repo完整驗證。
- 原64978本輪實際poll仍存活，390-source full313約三成未終局，未重啟或修改副本；不包含本次397-source新核驗。下一步把持久化workflow的原始來源／固定protocol認證及risk檢查接完整precommit／操作入口，收斂最後完整來源、native／UI與真實事件；此NAV audit不是完整獨立matching／risk引擎，coherent外部原始資料替換仍需可信錨點。
- 真實研究仍28／23／23 blocked，官方事件、coverage與實際forward各自未accepted；不以新361項通過宣告整體完成。

## 2026-10-30 接續：共用day入口接新版SQL與外部請求重播

- 已核對另一工作流既有RightsEngineCheckpoint／RightsEngineLedger，沿用其新schema／atomic writer，不重做儲存層。新DurableRightsDay／DurableRightsDayResult先定型別，commit_rights_day再將advance_rights_day、明確marks／joinedNAV及全部business/workflow事件接到該ledger。核對完整上一engine checkpoint（含stop／pending／obligations／fractional receivables）與AuthorizedRightsAccount，設定SHA綁research／engine／rounding政策。
- 每日input指紋涵蓋所有提供的market frames、prior liquidity、索引、commands／clocks／mapping／marks；執行前後及transaction各fault邊界再比對，來源競態rollback。此第一版綁全部提供frame（含提供的未來rows），不是可直接延長來源的prefix契約；增量frame-extension另驗，不靜默放行。
- verify_durable_days以外部原始請求目錄逐日重跑，精確比對checkpoint／input／events／NAV／digest，純讀不改bytes。直接反例把SQL rightsNAV改999999並重算completion hash：storage.verify仍可通過，但外部原請求重播拒絕。此為共用engine行為重播，下層finance／lot是獨立等式，不宣稱獨立實作execution engine或來源真實性認證。
- 新18例含七日parent／receipt／final真正交易，每天從SQL重開combined state產生下一日請求；cash50／50／50／250／250／550／550，明確marks的NAV1050各日，restart與不中斷相同。四SQL phase×RuntimeError／KeyboardInterrupt共8故障，付款／交付／risk／NAV整批rollback，重開retry只付一次。另有settings、prior stop、source volume、mark、缺原day及checkpoint／before_commit來源競態拒絕。
- 固定395檔 `/private/tmp/qfl-main-durable-day-v8eemx5t`，相關targets兩環境各 **353passed（14.93／20.89秒）**、環境／Lint通過，395份前後hash不變。來源tar、實際命令／exit0、runtime／snapshot import probes在 `M14/durable-day-workflow-20261030-main/`，不是最終full。首輪15pass／1fail是test以int99造mark在constructor即被正確拒絕，改合法Decimal99後驗實際replay guard；原console觀測明列，未補造raw log。
- J05日期anchor修正後registered三案例兩profile已有exit0紀錄（69.98／79.26秒），見rights-engine-sql-root-20261030-b/sample-report-results。該390來源另有full-job為running313，不重啟、不可延伸覆蓋本輪395變更。原350失敗終局保留。
- 接續外部source／request archive loader與認證、protocol／registration／UI及獨立persisted risk／NAV audit；pre-opening資格與更早intraday deadline仍不在after-close phase。真實資料28／23／23與實際前向未解除，最終來源full／native／80案逐案審查仍待，整體accepted false。


## 2026-10-30 接續：收據風險映射與共用單日入口

- 先定ReceiptRiskTransfer／RightsCloseCommand／RightsDayRequest／RightsDayResult，再交conversion_risk、close_commands、day_workflow。advance_rights_day共用lot engine、posting、AuthorizedRightsAccount、原授權封存、明確close commands與隔日projection；不是只在test串接。grant／revise／pay／deliver／convert／fraction／expire沿既有純transition及audit，整批錯誤不發布部分值。
- 此第一個phase明確只接受最新engine close同日之後的命令，ordered／unique actions。不能把較早付款cutoff或pre-opening資格移到after-close；未來需要早時段的真實事件仍阻擋。原帳戶與runtime不變，SQL原子性不由純函式宣稱。
- 收據轉換風險映射須連到最新engine anchor之後的實際convert，明列新證券StopState與carry_receipt_exit政策；原SELL reason保留，final exit數量取實際final持股。只轉部分時receipt與final各保留正確exit與stop；被移除的receipt BUY需明確cancel，既有final BUY在明列receipt exit優先下轉成SELL。缺映射、錯數量／reason／identity、stale／mutable／duplicate映射與捏造退出拒絕；多段chain需分次ordered projection。
- 新23直接case：持parent5，付50認購5，交付free2＋locked3；實際只SELL receipt2，其餘3轉成final。新stop95／high100與receipt105／110分開，final locked開盤退出失敗仍retry、解鎖再真正SELL3；各T+2後cash50／250／250／550、明確marks下NAV1050各日。不中斷／逐日inventory與engine各自codec重開相同；partial conversion2保留receipt1／final2兩退出。
- 共用day入口與獨立staged operations的inventory／projection完全一致；授權目錄與原authorization保留，當日付款／轉換重送no-op。測試含before-close／wrong-day／unordered／duplicate、batch最後一步不足交付、缺stop／轉換退出及過早projection，原輸入不改，沒有半套新值。
- 固定389檔副本 `/private/tmp/qfl-main-receipt-day-cqca7d5g`，相關targets兩環境各 **311passed（3.76／4.87秒）**、環境／Lint通過，389份前後hash不變。實際命令／exit0、來源tar、runtime／snapshot import probes在 `M12-5/receipt-day-workflow-20261030-main/`，非完整repo regression。
- 原350 full已兩profile終局失敗，3.13為1055pass／2fail，3.9亦exit1；原logs及來源保留。J05 29／30兩失敗來自fixture按history長度識別period，而正式study按各期warmup裁切；目前共享樹已有明確日期anchor修正與trim測試，尚需新固定來源重案例證明，不能將修正存在當作通過。本輪未修改其修正或重啟full。
- 接續合併engine／授權inventory／命令／risk mapping的versioned checkpoint、獨立重建與原子SQL／故障恢復，再接UI、final-source full／native及實際來源。現有after-close入口不取代完整日內時序與真實資格認證；真實研究28／23／23及實際前向仍未放行，整體accepted保持false。


## 2026-10-30 接續：新版合併engine／rights原子SQL與樣本排程修復

- 最終target核對：修正後兩環境實際registered report均 **3passed／3warnings／exit0**（wrapper69.98／79.26秒），未編造完成交易數。原44271已終局，64978實際poll存活且開始390-source full313；之後同程序3.9。下方「等待report39」為較早時點，完整suite尚未終局，不以target成功覆蓋原350full失敗。

- 較晚進度：修正後實際registered report的3.13三案已終局 **3passed／3warnings／69.55秒，exit0**，同session44271接續3.9。另啟動 **session64978** 排程，等兩profile report都exit0才於同一390固定來源循序執行完整verify.sh3.13→3.9；目前尚待report39，不算full通過。runner／job／results在同一SQL-b證據目錄；續追原handle，不改固定來源、不因等待重啟。下方report313未終局為早期時點。

- 新RightsEngineCheckpoint先綁engine與AuthorizedRightsAccount的cash／持股／完成日，codec保留兩個原component字串。RightsLedgerConfig由外部固定完整初始checkpoint、policy、execution、calendar、settings及protocol SHA。新RightsEngineLedger採rights_engine_checkpoint_v1及獨立tables；舊odd_lot_checkpoint_v1不改、不自動遷移。
- engine／inventory／完整授權、events與完成digest同SQL transaction寫入；immutable financial／authorization prefix、origin／offset、唯一新session receipt核對。相同重送no-op，變更已完成結果／stale parent拒絕。付款日checkpoint／events／completion／before_commit四點各注入RuntimeError及KeyboardInterrupt，重開全部回到原狀、重送只付一次。precommit callback拒絕亦rollback；callback改event並重算hash也不能偷偷替換submitted record。
- 實際共用engine連續六日買進→除權前持股basis grant→賣出→T+2→canonical認購→隔日再買：cash0／0／0／290／90／90。每一天先SQL commit／close，再用唯讀重開取得的engine與完整account跑下一日，逐checkpoint／events與不中斷reference精確相同。初始root被有效替換、engine cash重算hash、兩writer過期前綴、改calendar／policy、舊SQLite格式均有直接拒絕，唯讀原bytes保留。
- 新24ledger案例及相關targets在390固定來源兩環境各 **326passed（12.78／17.86秒）**、環境／Lint通過，390檔前後hash不變。證據在`M14/rights-engine-sql-root-20261030-b/`。較早389副本兩套在新close_commands.py import排序Lint失敗，未進pytest，原副本／logs保留；工作區import-only修正後另凍結390，沒有修改失敗副本。這是storage API驗收，來源／marks／NAV／risk獨立持久化audit及自動public workflow／UI仍待接。
- 原350-source full82614已終局，兩環境各1055passed／2failed（29／30實際report樣本案例），不能標完整通過。fixture原用len(history)辨別period，但registered runner每期裁切120暖機，validation實際會用development schedule。現改為顯式signal日期anchors，full-frame與trimmed-frame各29／30組合共6個真engine案例通過，未改報告count或放寬gate。
- 修正後實際registered report兩profile循序target已在同一390副本啟動 **session44271**，本輪poll仍存活，3.13已至少一案完成；尚未終局，不計成功。原350失敗logs／來源保留，未重啟原full。目標完成後才按結果安排最後整合full來源；工程／真實資料／前向仍未accepted。

## 2026-10-30 接續：公司行動 lots／成交／現金共同入帳

- 先定LotSessionFill／PostedLotSession，再交lot_close、lot_flow及獨立lot_flow_audit。新portfolio_lot_session記錄原lots、明確事件／rounding政策、成交價／gross／fees與最終lots；真正engine結果以原來源重跑核對，再單一回傳RightsInventory。公司行動可轉換／移除鎖定股，交易只扣當日已解鎖lots；沒有第二個cash accumulator。
- 獨立audit不呼叫入帳或lot轉換函式，逐事件／fill重建stock與release、核對gross／executioncash，再走既有session現金組件等式。inventory replay逐筆比對journal initial_lots與重建prefix；projection／NAV均支援舊portfolio_session及新kind，舊路徑保留。新命令與同session重複／亂序也共用原audit守門。
- 新14直接case含實際6股分割→12、先賣4／保留鎖定8、隔日release再賣8；反分割6→3、先賣1／隔日賣2；terminal直接處分鎖定持股且無虛構SELL。JSON重開一致。舊session重送必須供應經原history核對的recorded_before，來源重跑及payload核對後no-op，後來帳戶bytes保留。
- 實際連續split退出→下一日pre-event8股授權2個假設權利→T+2 cash200→canonical認購10變190→投影回engine只BUY1。最後第二筆賣款400入帳後cash490，held100＋pending明確mark10＋unpaid明確mark0，joinedNAV600；不中斷及逐日分別engine／inventory codec重開均一致，不把分開codec稱新版SQL。
- 額外反分割3×0.5＋股利＋CIL案例：只餘1股鎖定整股與0.5engine碎股claim，cash106／126／226／226、joinedNAV420／420／422／422；碎股不造現金、不提前使用。重算hash後改比例、release、fill數量／gross、opening時點、prefix或executioncash仍拒絕，偽造result及變更重送不改原帳戶。
- 最後377檔固定副本 `/private/tmp/qfl-main-lot-posting-b-q5lf6l2g`，25檔相關targets兩環境各 **271passed（2.60／3.60秒）**、環境／Lint通過，377份前後hash相同；實際命令／exit0、source tar及runtime／import probes在 `M12-5/lot-session-posting-20261030-main-b/`。前一377快照未含最後CIL新case，各270pass的來源與結果保留原main目錄，不混用。
- N3已能顯式共用一份狀態入帳，但自動command-phase編排、完整交付／receipt轉換／再交易、combined durable checkpoint、SQL／UI及原始來源認證仍待。Inventory JSON本身不保存全部engine未交割obligations／fractional receivables／raw bars，不能獨立冒充完整durable證據。真實28／23／23與實際前向仍未放行；377定向不代替350或最終full／J05／native。


## 2026-10-30 接續：完整指令目錄／原授權與庫存的合併封存

- 先定AuthorizedRightsAccount（單一inventory、完整RightsSessionPolicy、原PaymentAuthorization tuple），再實作apply_account_authorization：取封存原授權作retry比對，財務inventory與授權一起產生新不可變狀態或一起拒絕，cash仍只有book.cash。record_account_decline可記未列指令的不參與，不消耗權利／已付claim，不可覆蓋事前選定付款，也不當法律不可撤回放棄。
- 新authorization_archive_codec保存完整目錄（含未執行指令）、精確terms／fees／每日interval與原inventory字串；不是只保存catalog SHA。獨立authorization_archive_audit不呼叫production constructor／authorization／payment，逐項核對凍結時可得條款、完整batch、付款時點、每筆原授權與canonical receipt精確一致；遺漏／重複授權、改未用指令並連動改原授權policy、future未用terms、替換interval或request仍拒絕。
- 實際共用engine的買進→賣出→T+2每日均重開完整archive：入帳前cash0無法付10，due close入帳300後仍不能倒填14:00；有17:00區間的16:01授權可付10、cash290，整體codec重開一致。另有預定兩指令先付10、重開再付20→cash70，舊action重送不改狀態，未執行指令不會自動付款。
- 既有bare subscribe在明確提供原授權後可封存／重送，原inventory bytes不改；其歷史完整政策身分仍不能僅由bare receipt證明，需要外部原始授權／註冊認證，沒有宣稱archive建立會認證歷史。新三個模組及獨立test均使用先檢查不存在的唯一名稱／證據目錄，未覆寫共享既有檔案。
- 新17例及相關34檔在378檔固定副本循序執行verify.sh，兩環境各 **328passed（17.76／23.97秒）**、環境檢查／Lint通過，378檔前後hash不變；pytest的snapshot package path probe亦通過。命令、exit0、來源與case scope在 `M12-5/rights-auth-catalog-root-20261030/`。安裝preflight仍檢查main editable install，pytest另明確使用snapshot/src，不混稱scope；不是整個repo完整回歸。
- 本輪多次實際poll原82614仍存活；350-source full313 log已推進約六成，未終局，未重啟。其範圍不含較晚archive／policy／NAV等；最終來源完整gates仍待收斂。
- 此為完整授權的合併狀態／codec，不是SQL transaction writer。接續連續corporate-lot／交易／權利／NAV／risk workflow與版本化原子帳本，再接UI、註冊及原始來源認證；舊checkpoint-v1不改，真實28／23／23 blocked與實際前向仍未解除，整體未accepted。

## 2026-10-30 接續：329雙環境完整終局與授權統一記錄

- 原session35967已實際終局exit0。329檔3.13為907passed／18warnings／1745.99秒；3.9為907passed／18warnings／2030.85秒（wrapper2031.56秒）。兩份log SHA及329來源hash均核對相符，更新 integrated-20261030-b 的terminal／completed_profiles及source-terminal-check。這是該固定來源完整通過，不覆蓋較晚shared engine與rights變更。
- 原等待350排程的full-job.json已轉running313，full313 log持續推進；本context沒有跨chat原handle，僅記錄已觀測的排程及log，不捏造handle存活或完整終局。未啟動另一full，J05／native重案例仍不與其並行。
- apply_authorized_subscription的新付款已統一走elect_subscription，單一policy_election收據保存實際整批選擇／cutoff；canonical政策name綁完整凍結RightsSessionPolicy SHA，含尚未執行指令。第一次付款後改後續指令產生不同帳戶政策並拒絕。既有bare subscribe只在提供已認證原授權的相同重送時保留原bytes，不靜默升級。
- 新5項bridge case證明同一預定政策先付10、重開再付20、cash70／獨立audit通過；改後續fee拒絕；即使呼叫端把變更後interval也冒充recorded，canonical payload仍拒絕；舊bare收據byte-preserving no-op；零長度付款區間拒絕。原實際T+2 cutoff案例也已走新canonical路徑。
- 共享另一工作流恢復了原payment_policy測試，同時保有本輪explicit_authorization測試，首367來源22檔targets各283pass含重複26案。保留舊檔全部函式／註解／docstring與歷史引用，以module __test__=False避免重複收集；AST逐函式驗證原statement序列全包含於新增canonical assertion的正式收集模組，不減原覆蓋、不skip原必要案例。
- 最後367檔固定副本 `/private/tmp/qfl-main-auth-b-rmsyehsb`，兩環境相關各 **257passed（2.27／2.94秒）**、環境／Lint通過，367份前後hash不變。來源tar、實際命令／exit0、runtime／snapshot import probe及duplicate-case-review在 `M12-5/canonical-authorization-20261030-main-b/`；前283結果及來源另存原main目錄供追溯，不作更多獨立覆蓋宣告。
- canonical付款現已有本機policy綁定；完整原指令catalog、歷史freeze、來源及原授權認證仍需外層保存。N3連續corporate-lot／交易／rights編排、原子新版SQL、UI與最終整合來源gates仍未完成；真實研究28／23／23 blocked與實際前向未解除，整體accepted保持false。


## 2026-10-30 接續：政策／付款窗口寫入原始命令與獨立重建

- 本輪最後核對：原329的verification-results.json現已含兩profile終局，82614實際poll仍存活且full-job.json已進入running313，開始350-source完整3.13回歸，之後同程序跑3.9。下方「仍等待」保留較早時點，不另重啟；350來源仍不涵蓋較晚NAV／政策命令，最終發布範圍另驗。

- 新RightsParticipationPolicy／PaymentCutoff先定明確參與語義與每日窗口；elect_subscription再寫單一policy_election原始命令，內含完整policy／ID、pay或decline、rights scope、requests與cutoffs。inclusive／exclusive明確形成不同身分；整批不足拒絕，不自動縮單／改選腿。第一個policy ID綁同帳戶後續election，獨立posting audit也拒絕之後繞過policy的裸subscribe命令；原先未啟用政策的legacy history不改。
- 明確decline保留unpaid及已付pending，不當作不可撤回的法律放棄或自動expiry。實際engine的T+2 close入帳後，14:00截止仍拒絕；倒填14:00亦被completed clock拒絕；有已知17:00窗口才可16:02再付10。低Decimal precision6下兩腿費用與delta仍精確，cash_delta=-90.246913578。
- 新payment_policy_audit不呼叫production policy constructor／election／subscribe，依原commands獨立核驗授權再重建財務；重新hash的非法cutoff／fractional rule、改decision與同帳戶後續合法但不同policy ID均拒絕。原RightsSessionPolicy／PaymentAuthorization另外固定真正action與完整batch，本輪receipt API固定參與語義及已執行batch；兩者尚須archive bridge，不能互相替代或宣告durable已接線。
- 本輪同名寫入曾覆蓋共享測試與驗證摘要，已從不可變356-source tar恢復原測試，依既有acceptance SHA恢復原source／terminal record；原證據所有hash完全吻合。新增21例已移至獨立test_odd_lot_rights_policy_receipts.py與`M12-5/rights-policy-receipts/`。碰撞／恢復依據在collision-recovery.json；較早365-source／267執行只留pre-reconciliation歷史，不作目前來源驗收。來源另有已移名的authorization測試路徑，因此下述總數含原路徑／移名路徑重複執行，不當319個獨立驗收案。
- 修復後367檔固定副本相關29檔，兩環境各 **319項執行通過（16.74／23.58秒）**、verify.sh環境檢查／Lint通過，367檔前後hash不變。原26授權＋2cutoff與新增21receipt測試另聯跑49passed；opening-lot測試一處dict()已改語義相同literal以通過C408，相關案例通過。所有case mapping仍partial／accepted false。
- 原排程82614本輪實際poll仍存活，仍等待329兩profile終局；350來源不修改、不重啟。本次367來源含政策／授權兩條API及其具體scope，仍需最終完整來源閘門。原始授權與receipt綁定、註冊協議、來源認證、連續編排、新SQL／獨立持久化audit與實際事件／前向均未結；真實28／23／23 blocked不變。

## 2026-10-30 接續：公司行動 lot 與實際開盤接線

- 新 OpeningLotEvent／LotRoundingPolicy 先定介面；project_opening_lots 對已稽核帳戶投影分割、反分割與終止事件。原lot的整股保留原解鎖日；採明確保守政策，跨lot碎數合成的整股取所有碎數貢獻者最晚解鎖日。每lot碎數與合計剩餘碎股保留精確Decimal，不虛構折現款；此為工程政策，不認證發行人拼湊規則。
- 新 run_lot_projected_session 真正核對engine cash／持股anchor、當日資料比例／terminal與limits，再呼叫共用session；不是只在test接線。來源0／1均為無分割；若精確股數與engine float邊界不一致，開跑前拒絕。執行後公司行動股數再核對投影。
- 新24項直接案例：6股分割2倍→12股、可賣4、保留8股；反分割0.5→3股、可賣1、保留2股。兩者真實engine賣款各200尚未T+2入帳、stop與退出重試保留。全部鎖定6股terminal仍可公司行動消滅、現金300，無SELL／交割；原帳戶與runtime不改。錯比例、缺事件、future、日期、cash／cap及浮點邊界均有拒絕。
- 共享同名policy test與證據metadata出現其他工作流寫入；保留其現有檔案，從原356固定副本／source tar恢復本輪26個授權test為 test_odd_lot_rights_explicit_authorization.py。原207結果的初輪logs／hash與356份tar仍一致，另存 `M12-5/explicit-authorization-20261030-main/`。舊rights-payment-policy目錄的目前metadata不再作本輪原356證據入口，沒有覆寫或混用另一工作流紀錄。
- 重凍結365檔 `/private/tmp/qfl-main-opening-lots-u9v1my__`，20檔相關targets含新24與恢復26，兩環境各 **252passed（2.14／2.87秒）**、環境／Lint通過，365份前後hash相同。來源tar、實際命令／exit0、runtime／snapshot import probe在 `M12-5/opening-lot-projection-20261030-main/`；較早364來源各226pass仍保留，不冒充包含恢復後26項。
- 首21直接case因test helper Decimal(None)有6fail／15pass；wrapper初輪2fail／19pass，一為test誤造禁止ratio1，另一為新增bridge未對齊既有no-split0。原因及原console觀測已記錄，無原完整redirected logs的部分明列，不補造。
- 回傳是projection／session result，尚未將corporate lot movements與fills寫回權利帳戶；舊post_engine_session不能完整表示此轉換。下一步合併授權與canonical policy_election記錄，再做N3連續日、獨立重建及新版原子帳本。原始來源／開盤時點認證、receipt轉換整合及真實2881／2882仍各過閘門；研究仍blocked28／23／23，accepted不變。
- 原完整329 session35967本輪多次實際poll仍存活，3.9尚未終局；未重啟full或平行開J05／native重案例。本次365定向不代替原329／等待350或最終來源完整驗證。


## 2026-10-30 接續：明確參與與付款 cutoff 授權

- 新 `session_policy.py` 先定 SubscriptionElection／RightsSessionPolicy／PaymentInterval；`payment_authorization.py` 再提供 authorize_subscription／apply_authorized_subscription。凍結政策綁完整 batch、terms、股數與費用，未列 action 不參與，不依可用現金自動認購；未來 terms、政策與 interval／缺截止時間拒絕。每腿需明確當日區間，邊界含端點，支援等價 UTC 時刻。
- 原子付款沿用真實 core；不足90.25而只有90時整批拒絕。重送需提供已存原授權，policy／interval改動形成新授權身分並拒絕變更重送；外層仍須認證該原紀錄，舊 book codec 本身不能證明政策綁定。
- 新28項直接案例含實際 engine T+2：cash依次0／0／0／300；尚未入帳不能付款，16:00 close已入帳亦不能倒填14:00截止；17:00截止則16:01可付款10、餘290，inventory重開一致。另有兩腿金額／費用手算、未選擇但現金充足、未來資訊、缺腿及payload反例。
- 固定356檔副本 `/private/tmp/qfl-rights-payment-policy-ht6rvmve` 的17檔相關targets，兩環境各 **207passed（1.95／2.75秒）**、環境／Lint通過，356檔前後hash不變。實際命令、exit0、source tar、runtime與snapshot import probe在 `artifacts/acceptance/M12-5/rights-payment-policy/`。初輪亦各207pass；補明確import probe後重驗，保留首輪logs，不改產品。verify.sh的isolated安裝檢查讀main editable package，pytest另以snapshot/src及設定執行，兩者範圍明列。
- 此為N1／RI-01局部API交付，未自動接durable workflow；交易與付款排程優先序、來源認證、post-event lot、連續流程、新SQL與最終來源完整gates仍待完成。舊checkpoint-v1不改，真實2881／2882未放行，研究仍blocked28／23／23。80案索引已重建，accepted不變。
- 原329完整session35967本輪實際poll仍存活，3.9未終局。等待350的82614在本context回覆Unknown handle，而狀態檔仍waiting，不能據此宣稱他處程序已終止；未重啟任何full。新356定向證據不覆蓋或替代329／350完整來源範圍。


## 2026-10-30 接續：RI-03 真正session結果與權利NAV整合

- 先定RightsSessionNAV，再實作value_session_nav：核對最新已記錄portfolio_session與實際engine link，組合current cash、held securities、unpaid rights、pending claims、positive sale receivables及fractional receivables。buy／negative-sale payables為已保留cash的披露，不再次從NAV扣除；settled_cash另列。權利命令可在當日engine close後改cash／持股，原engine_equity保留為獨立重建基線，不覆寫既有result／NAV schema。
- 由實際engine買進3股、次日賣出、T+2收款及假設權利條款手算：NAV570跨交易／交割／認購／交付保持；認購10後cash290＋未付權利180＋pending100，交付變held100，收據1:1轉換費1後NAV569。鎖定交付股同樣需mark；receipt與final各用自己的證券mark，不猜母股價格或以認購成本替代。
- 真正最低費用案例NAV980→960，buy payable30與sale-fee payable10不重扣，settled_cash披露1000；真實共用engine的反分割／股利／CIL fixture NAV420／420／422／422，碎股應收98／98／0／0，cash106／126／226／226，沒有把應收提前當現金。
- 新15項包含engine equity +1、同時改receivable_value與equity、錯anchor、缺／未來／過期／重複mark、與raw close不符及非TWD等拒絕案例，原inventory不變。355檔固定副本相關23檔兩環境各 **220passed（17.36／24.07秒）**、verify.sh環境檢查／Lint通過，所有355檔前後hash相同。證據／命令／局部scope在 `artifacts/acceptance/M12-5/rights-session-nav/`；不是整個repo完整回歸。
- 原完整排程 **session82614** 本輪actual write_stdin仍存活，仍等待原329兩profile終局紀錄；未重啟。該排程固定350來源不含本次NAV，來源不回寫；最後完整發布來源須另收斂本次差異。
- 這是顯式joined-NAV API，並非durable／UI自動編排或外部mark經濟真實性的認證。凍結估值／參與／cutoff政策、post-event lot轉換、連續生命週期、獨立持久化NAV audit、新版SQL、官方2881／2882事實、資料readiness及真正前向仍待完成；真實28／23／23 blocked不變。

## 2026-10-30 接續：RI-02／03 開盤可賣數與獨立重建

- 本輪後續已啟動 **session82614** 的完整gates排程，實際poll仍存活，目前full-job.json為waiting_for_prior_terminal：等原329兩環境在verification-results.json留下終局，再於同一350檔固定副本循序跑完整3.13→3.9。此刻尚未開始新full suite，不能稱完整通過。副本另建Git身分僅供source-identity驗證，未改350份bytes或原工作區Git；runner與狀態在同一rights-sale-limits證據目錄。續追原82614，不因觀測逾時另開程序。

- 新OpeningSaleLimits先定完整post-event持股的當日開盤限額，optional欄位接到真正OddLotSessionInput與opening撮合。每個持股身分須有明確整數cap且不超過實際股數；None維持舊路徑。SELL只成交允許數量，orders仍列原requested／filled／expired；全部鎖定列not_tradable、只成交允許部分列tradability_limited。鎖定股仍是資產，止損／退出pending保留重試。
- rights的opening_sale_limits在實際開盤日重新核對已知lot release；不沿用前一日tradable0。認購／交付後投影的1股在隔日解鎖可真正SELL1及BUY2，cash90；混合3股則先SELL1、隔日解鎖再SELL2，各產生100／200賣款及各自T+2到期，當下cash仍0。engine checkpoint與inventory逐日重開同結果，既有獨立risk audit逐日通過。
- 獨立session link不呼叫opening helper也會拒絕超cap fill。RightsInventory重新載入時逐command核對原lot可交易數；即使改初始解鎖日後cash／command／final holdings仍平衡，歷史提前扣股仍拒絕，不能只靠最終庫存重建繞過。
- 新17項與既有相關22檔，在350檔固定副本循序執行verify.sh定向閘門，兩環境各 **205passed（17.28／23.76秒）**、環境檢查／Lint通過，350檔前後hash相同。證據、完整命令／exit0、局部case mapping在 `artifacts/acceptance/M12-5/rights-sale-limits/`。首啟動copyfile未帶執行權限，兩profile尚未進入檢查即exit1；原logs保留，再以Bash執行同一腳本，來源bytes未改。
- 既有329來源3.13已有907passed終局（另輪紀錄）；本輪ps查詢未執行，因自動核准審查用量限制失敗，不能以此宣告其3.9結束。局部205項不代替新shared-engine來源的完整suite。
- 本輪已接真實共用session API，尚非durable workflow自動編排。開盤cap需post-event inventory；split／terminal／receipt等lot轉換、付款cutoff／參與政策、rights-aware NAV／marks、versioned SQL、實際來源與最終完整gates仍待完成。研究28／23／23 blocked、既有checkpoint-v1與真實訂單禁制不變。

## 2026-10-30 接續：七項完成條件與最新來源差異

- 完成狀態以本機實際檔案／logs與原handle核對。329來源3.13完整907passed／18warnings／1745.99秒有exit0及SHA；session35967本輪write_stdin仍存活、3.9約三成且未終局。其他context的Unknown handle或較早未終局敘述，不取代此實際結果；原副本未修改、不重啟。
- 80案例現全部有evidence mapping，但所有index accepted仍false，逐案來源scope與必要發布範圍仍待最後審查。新完成稽核不以「沒有缺mapping」當作完成。
- 對329份inventory逐檔比較最新shared worktree，發現4個non-doc產品檔改動：opening.py、session.py、rights audit_reconstruction.py、rights types.py；另24個新non-doc檔，包含rights庫與較晚直接測試。保存兩側SHA／新檔SHA於`release/completion-audit-20261030/acceptance.json`，不是另一份完整快照。
- 最新opening已接post-event sell caps，session另呼叫session-link核對；既有rights projection153項與其他定向證據各有其scope，不把907項通過延伸為最新共享engine通過。最後來源須涵蓋這些變更再驗。
- 七項要求逐一標出未完成證據：最終雙profile完整回歸、80案個別發布審查、J05三個實際29／30報告、最後reader native包、rights session/NAV/versioned SQL/source整合、真實資料ready、實際有效決策與新session觀察。332-source J05重案例與native重建仍待原完整終局，不與同機full並行。
- 最新真實研究report所有manifest檔hash再次核對相符，active findings為coverage23／unsupported2／event_conflict2／derived_state2；三期blocked28／23／23，績效0。本次只是metadata／file-hash事實核對，不冒充native全raw語義重建或來源時點認證。整體完成仍未證明，goal保持active。


## 2026-10-30 接續：907項完整3.13終局與E-A10範圍變更

- 原329來源完整3.13 **907passed／18既有warnings，1745.99秒**、Lint通過，wrapper wall1746.81秒／exit0／logSHA實際保存。**同一session35967已接續3.9**，仍未終局；驗證scope不包含後加新測試。較重的J05報告及native舊包仍等此程序終局才執行。
- E-A10既有freeze／protocol／registry介面已足以保留範圍變更，不另新增產品API。新`test_scope_change_lineage.py`實際造兩種source-backed受阻研究：基準最後日缺價而縮短期間、第三標的1301缺價而另建較小股票池。父study／run／report原本blocked且沒有績效；child較窄scope可ready，但必須是新study／candidate／protocol身分。
- 子協議明列parent_protocol_id，immutable access_note保存具體排除理由、父study ID及已接觸資料；data_access維持accessed、父／子holdout_untouched皆false。registry保留兩協議且沒有啟動experiment。父來源／study／report／protocol全部bytes及原readiness保持，舊報告仍可驗證；沒有改真實股票池或取代正式研究。
- 兩環境各2項直接案例通過，Lint通過，最終命令／秒數與source/test hashes在`M12-5/scope-change-lineage/`；首跑及前一輪logs保留，產品code未改。workflow說明鄰近protocol README；理由為顯式填入的access_note，不冒充自動判讀人類理由或判定不存在事後選擇偏誤。
- E-A10從缺直接scope證據補為此離線流程passed_within_scope，accepted仍false；真實資料／權利模型／實際前向與最後來源完整驗證繼續各過閘門。


## 2026-10-30 接續：RI-00 證據封存與 RI-01 隔日狀態回接

- 新 RightsSessionProjection／project_rights_session 先定不可變介面，再實作：核對最新 portfolio_session 的 cash／holdings anchor，將權利付款／交付後的單一 cash 與持股投影到既有 session checkpoint。保留 settlements、receivables、pending、stop 與其他 engine 歷史；新證券需要明確 StopState，不從母股猜測。未來知識、舊 anchor、已終止證券、無政策的消失持股賣單及 Decimal→float 精度損失拒絕。
- 實際 engine 的 T+2 可用現金300，明確認購10後投影290，下一日實際買進由3股改為2股、餘cash90；inventory序列化重開同樣結果。已可交易的交付1股可在下一日實際賣出；未可交易的交付仍列持股，另列tradable0，不宣稱已完成其開盤限量執行。原runtime／inventory不被修改。
- 新12項與既有rights／session／durable settlement／audit／benchmark共15檔，在新346檔固定副本循序跑兩環境，各 **153 passed（14.43／19.47秒）**、Lint通過；副本所有檔案前後hash相同。來源inventory、實際命令、兩套exit0／logs、局部case mapping在 `artifacts/acceptance/M12-5/rights-session-projection/`，仍非整個repo完整回歸。
- 初輪2failed／8passed是測試要求已結清obligation的unused due index在restore後不變；既有bridge刻意重設該index。改核對持久化settlement、經濟欄位與未結清obligation，不改bridge產品語義；首輪結果與原因明列，無完整原console log。較早session-flow的111passed／1failed fixture logs及112passed終局logs也封存；後者未補造舊來源身分，本輪固定副本重驗才提供新證據。
- 原329檔session35967本chat呼叫回覆Unknown process id，現有full313 log未終局且無full39 log；不能報完整通過，未重啟原full suite。新346檔只驗上述target，較晚來源的完整發布閘門仍待執行。
- 下一步RI-01剩參與／cutoff與projection消費契約，接RI-02／03開盤可交易數限制、連續流程及rights-aware NAV／stop，再接新版SQL。來源認證、真實2881／2882與研究28／23／23 blocked均未解除；原checkpoint-v1與broker邊界不改。

## 2026-10-30 接續：J-A05 真實29／30筆 fixture 與待驗報告

- 原329完整 **session35967** 本輪實際poll仍存活，full313約七成、未終局；不重啟，不與新的重型registered正例同時執行。
- 先交`phased_sample_boundaries.py`的明確target schedule與實際engine測試，開發／驗證29–30、30–29、30–30各只交易第一資產，買進次session賣出。兩環境各 **3passed（1.16／1.44秒）**、Lint通過，精確核對closed episodes／2×fills、sample_sufficient與cash。沒有改episode摘要或將假count塞進報告。
- fixture保留30bps股票賣稅，每次10000×1賣出扣30；期末cash=1000000−count×30。首稿3failed1.02秒是測試誤以為零稅，已改獨立手算，不改產品。30筆虧損也能滿足數量門檻，不能因此說策略有效。
- `test_phased_sample_reports.py`三個完整registered v6／保存selection／publish／report驗證案例已寫好並collect成功，但 **尚未執行**。預期29開發無選擇、30開發29驗證保留原選擇且樣本不足、雙30保持全部情境與ETF零closed數處理；預期不算驗收結果。
- 固定 `/private/tmp/qfl-v6-sample-boundaries-20261030-a` 為原329來源加三個fixture/test檔，共332份，source inventory／execution及pending明確命令保存`M13/phased-sample-boundaries/`。新重案例不在原完整inventory，J-A05仍partial。等原程序終局才循序跑兩profile的重target，不能將測試收集當通過。


## 2026-10-30 接續：J-A06／A07 實際 v6 報告來源反例

- 新`test_phased_report_source_contract.py`六個實際registered v6報告案例，各先通過checked_report並由CSV／SQLite重建validation evidence（明確0完成交易），再分別改外來協議、primary sessions、基準SQL settings、刪情境、政策或diagnostic。改檔均重算manifest hash／report ID；政策亦重算protocol ID、SQL settings亦更新自身hash。
- 外來協議與改情境／政策／diagnostic由完整report verifier／checked_report拒絕；sessions及benchmark settings由實際report_candidate_evidence的frozen-session／account-settings gate拒絕。每案凍結protocol、raw sources與registry bytes保留，未改產品邏輯或放寬驗證。
- 固定 `/private/tmp/qfl-v6-report-contract-20261030-a` 為原329來源加新test，共330檔；兩環境各 **6passed（22.82／27.98秒）**、Lint通過，全部330inventory前後不變。五個執行中的report／phase／binding／study產品檔亦核對與目前worktree相同。scope與records在`M13/v6-report-source-contract/`，不宣稱覆蓋較晚共享樹。
- 首跑2failed／4passed23.24秒為測試ISO日期混入時間字尾、benchmark帳戶name前綴假設錯誤；改為純ISO日期與由BenchmarkSpec讀實際result_name，沒有修產品。新import排序亦整理；全域Lint及diff check通過。
- J-A06／A07的具體source-adapter範圍與既有foreign候選／scenario核心、最後決策／selection篡改證據已對照；剩最終來源完整／positive fixed-choice／native包驗證，不以0成交報告當成有效決策。J-A05實際29／30經report adapter仍獨立待驗。
- 原完整329來源 **session35967** 本輪多次實際poll確認存活，full313約六成，未終局、不重啟。新test不在其inventory。完整程序結束後才安排重的30-trade／native驗證；真實研究與前向閘門均未accepted。


## 2026-10-30 接續：J-A04–A08 證據與固定來源 target

- 原完整session35967實際poll仍存活，329檔full313已推進約六成，未終局；沒有重啟或修改固定來源。
- 已逐函式審查v6 evaluate_saved_selection → checked_report／report_candidate_evidence → evaluate_selected_development → validation_checks，並核對protocol report binding／matched scenario重建。精確file／AST hash與呼叫位置在`M13/j04-j08-assertion-review/reviewed-call-paths.json`；六個adapter產品檔均匹配329 inventory。靜態審查沒有當作測試執行。
- 實際重跑fixed-choice／validation core／development boundaries、registry collection競態、source bytes／symlink、publication競態及readonly failed/running/missing UI歷史。原共享工作區3.13為61passed，3.9為1failed／60passed15.66秒，在進入collection race前被protocol/source/environment changed守門拒絕；exact changingfile未捕捉，保留原logs，不過度宣稱根因定位。
- 相同target改在既有未修改329副本循序執行，兩環境各 **61passed（12.53／15.87秒）**、Lint通過，全部329份inventory在執行前後hash一致；未放寬來源guard。此為輕量獨立target，原完整suite繼續同一handle。
- J-A04既有共同validation核心保留已知失敗、缺情境與pending-risk，固定winner不替換；J-A08 collection／publication race拒絕與實際UI失敗歷史保留已有直接結果。完整v6正例／retry／report篡改整合沿原執行範圍，不宣稱本次61項覆蓋全部。
- J-A05精確29／30經實際v6報告adapter、J-A06外來來源／sessions／benchmark與J-A07刪情境／policy／diagnostic篡改的執行範圍仍明列partial。無開發選擇時刻意不解析validation；不能為了無條件攔截未使用未來值而破壞開發來源分離契約。
- 五案scope與剩餘必要證據已寫回j05 case-review、acceptance及80案索引；所有accepted仍false。接續等原完整終局後安排重的實際adapter／native包驗證，真實資料與前向閘門維持。


## 2026-10-30 接續：J-A01／A10 政策 UI 的實際拒絕與單次操作

- 原完整 **session35967** 本輪write_stdin仍確認存活，full313約四成、未終局；來源不修改、不重啟。新測試保持獨立scope。
- 新`test_research_policy_ui_safety.py`五個真實AppTest表單反例：缺optional明列欄、NaN、未知欄、非object JSON及輸出根目錄沒有父協議。實際freeze_policy_child／parser／freezer／registry路徑拒絕，沒有mock新案例後端；完整research目錄inventory／bytes保持，沒有selection／decision產物或新父root，rerender不重送。
- 與既有合法子協議／明確候選執行／保存selection後發布決策測試整合，兩環境各 **13passed（10.55／11.97秒）**，範圍Lint通過；首跑新5項5.21秒通過。sources/test hashes前後一致，產品邏輯未改；全域Lint亦通過。原既有候選錯誤測試使用明列mock，沒有當作真實候選成功執行。
- 證據在`M13/policy-ui-safety/`；J-A01的UI政策入口範圍已有直接結果，剩最後來源完整／compatibility與發布審查。J-A10另連此action/UIscope，不覆蓋較早browser狀態證據或正式資料。原Jcase-review與80案索引已更新，accepted仍false。
- 接續J-A04–A08的具體assertion及source-verifier對照，收斂既有案例的實際覆蓋；同時追原完整結果，終局後再執行native歷史包核驗，避免同機重驗證爭用。


## 2026-10-30 接續：既有 session 的可用現金／持股交接核驗

- 先定 SessionPortfolioLink，再新增 reconcile_session_portfolio：獨立由prior runtime及當日actions／terminal／fills／settlement重算cash與整數持股，明列interest、event cash、execution cash、settled sales與unsettled sales。買款已保留、負賣款費用當日扣，T+2不重扣；正賣款只在應到close入帳。
- 既有run_odd_lot_session於回傳前直接呼叫此核驗，結果欄位／合法事件數值不變；並非只新增孤立API。原obligation的trade／side／amount／due不許改寫，新obligation與實際fill逐一對照，完成時點與NAV cash／settledcash／payables／receivables均核對。
- 十項新案例真正經共用engine，股利＋反分割＋CIL／T+2重算cash106→126→226→226；小額負費用970→960且不再扣；正賣款可用cash0／0／0／300／0／0。利息只按prior usable cash100×0.0365/365＝0.01，不對當日股利或應收提前計息。實際close注入runtime／NAV同步+1仍被拒絕，輸入runtime不變。
- 新核驗與既有rights核心／inventory、session、durable events／settlements、financial audit、benchmark相關13檔兩環境各 **129 passed（15.79／21.39秒）**，全域Lint通過。證據／原命令／hash與E-A07／L-A05／A07／A11局部scope在`M12-5/rights-session-boundary/`；新檔均低於300行。
- 這是實際session的after-close交接驗證，尚未把rights付款／交付或外層session cashflow同步進RightsInventory，未建立平行現金帳戶。原checkpoint-v1不改，來源認證／策略參與規則、stop／lot、versioned SQL與完整發布仍待驗；真實v2研究28／23／23 blocked不變。較早完整source inventory不涵蓋本次session改動。


## 2026-10-30 接續：J-A01 完整政策欄位與 v6 子協議身分

- 原329檔完整 **session35967** 本輪實際poll仍存活，full313約四成、尚未終局，未重啟或改來源。新增測試在該inventory之後，不能沿用其結果。
- 新`test_phased_policy_identity.py`共20個案例：九種門檻／開發目標／樣本要求，各先比較沒有parent linkage的協議ID，確認是政策本身形成新身分；再實際凍結v6子協議並load，parent與child各讀回、舊bytes保留、候選／情境預算不變。
- 七種驗證／風險門檻各自改變完整protocol，development-only policy與selection內容／ID精確相同；開發objective與minimum_completed_trades則改開發身分。全部11個serialized政策欄位逐一刪除均拒絕，包含明確None／boolean的選擇，不能靜默使用預設值冒充原聲明。
- 兩環境相關四檔各 **85passed**、範圍Lint通過；最後結果與秒數／命令／hash在`M13/phased-policy-identity/`，source/test hashes前後相同。首次5failed／15passed是測試把必填dataclass欄缺失的TypeError硬要求ValueError，現接受既有兩種拒絕型態，產品未改。新測試import已排序，全域Lint通過。
- J-A01具體後端scope與J-A02開發分離scope補入80案索引，原j05 case-review連到較晚證據；UI政策入口／最終來源完整驗證與真實研究仍分別未結，不因本次85項通過放行J05或發布。


## 2026-10-30 接續：L-A12 舊帳戶格式安全操作

- 原329檔完整 **session35967** 透過write_stdin確認仍存活，full313約四成、未終局；不重啟，不修改固定副本。本輪新test在其inventory之後。
- 新`test_odd_lot_legacy_account_safety.py`用實際PaperLedger writer及研究archive writer建立兩種原生SQLite；另有明列不支援的checkpoint kind fixture與空SQLite，共四格式。不是把捏造v0宣稱實際歷史產物或承諾遷移。
- 四格式均實際執行inspection、internal resume、historical rebuild，明確拒絕，整個目錄檔案inventory／bytes完全不變、新target不存在；後端不修復或初始化舊檔。真正AppTest逐一檢查安全續跑預設、讀取與重建錯誤及rerender不寫入，沒有mock這兩個操作後端。
- 連同既有supported account UI／checkpoint creation／locked settings，兩環境各 **18passed（3.05／3.21秒）**、範圍Lint通過；新直接8項首跑1.64秒通過。source/test hashes前後相同，產品邏輯未改。證據在`M14/legacy-account-operations/`；L-A12此離線格式邊界scope通過，整體發布／M14尚未accepted。
- consolidated L矩陣已連接新證據，不再把此四格式的安全拒絕列為未測；新rights durable接線、實際新session、最終來源完整驗證與native歷史包仍各有自己的完成條件。J-A01–A11逐案審查接續，沒有因同名測試存在就自動放行。


## 2026-10-30 接續：M14 完成日契約與 L 矩陣收斂

- 原 **session35967** 實際write_stdin確認仍存活；329檔固定快照full313約四成、尚無終局，來源不修改、不重啟。下述新增測試在此inventory之後；replay／ledger／snapshots產品source hashes仍精確匹配329快照。
- 新`test_odd_lot_completed_input_contract.py`補12項no-op歷史資料反例：暖機或已完成日的raw_open／raw_close／close／volume／股利／拆股改動，無新日也拒絕，整個帳戶目錄inventory與bytes保留。另10項成本／滑價／成交比例／風險／再平衡／稅／利息／日曆／協議／程式身分變更，均以configuration錯誤拒絕，不重建或reset。
- L-A10直接替換SQL snapshot linkage為另一份合法暖機快照並重算帳本chain。先驗證新快照可讀、唯讀OddLotLedger.verify通過、獨立財務audit通過，再核對續跑因snapshot input prefix不符拒絕，全部檔案不改；不只依賴stale hash測試。
- L-A03加入非零年利率0.0365的三session純現金案例，獨立ACT/365逐日手算，一次完成與1＋2分段的checkpoint／digest相同，財務audit通過；完成歷史重送committed0，cash不再加利息且全部檔案bytes不變。
- 兩環境相關三檔各 **33passed（6.38／10.06秒）**、範圍Lint通過；新增明確chain驗證assertion後，最新24direct案例再各 **24passed（2.82／3.97秒）**、Lint通過，前後source hashes保留各scope。初始22／23與32相關結果保留；新增test曾有unused import已清理，產品邏輯未改。全域Lint及diff check也通過。
- `M14/completed-contract-review/acceptance.json`記L-A03／A08–A10直接範圍；`consolidated/acceptance.json`另逐列審查全部13個L案例，連結既有故障／事件／交割／稽核／重建／forward證據。此次沒有重新執行所有被引用舊測試，不把assertion存在當成執行。L-A06較新subscription rights未接durable、L-A12完整舊schema操作及L-A13實際前向仍明列未結；全部accepted維持false。
- 接續先等原完整profile終局，再用對應reader核驗實際舊包／最新資料；J逐案與最終必要來源範圍繼續收斂。真實研究仍blocked28／23／23，沒有有效實際continue／前向觀察完成證據。


## 2026-10-30 接續：認購權與單一現金／實際持倉連接邊界

- 先定 RightsInventory／SecurityLot／SecurityMark／InventoryValuation，再新增 post_rights_transition；單一可用現金僅為book.cash，initial cash只作稽核錨。每次只接受從目前原命令prefix新增一個action，驗現金delta、獨立方程式及精確debit／credit後，整體回傳book／lots／postings。失敗不更動原物件；no-op不可夾帶現金或資產變動。
- 交付從pending claim移至具security_id／tradable_session的lot；換發同時消耗同權利腿的實際憑證並credit新證券。授權股數必須等於事件當時持倉，constructor／decode也逐命令重建，防止跳過posting函式或用後來股數偽造原始basis。可交易量不早於lot日期，不從未來checkpoint回查過去持股。
- 新value_inventory只計一次cash，pending／unpaid用權利marks，已交付（即使未可交易）用held-security marks；缺漏、過期、未來、重複或外來marks拒絕。假設100個parent各mark1加上原權利／cash，授權→付款→三腿交付逐步NAV皆460，沒有double-counting。
- 新inventory_codec使用獨立schema，checkpoint load重驗financial／postings／actual lots／grant basis。每一步序列化重開與一次完成的全部frames、cash、lots、commands與postings精確相同；偽造quantity／security／tradability／anchor／lostposting／boolschema／duplicate JSON key皆拒絕。
- 新增28項連接／重開案例，與純核心／獨立稽核合計兩環境各 **90 passed（0.41／0.73秒）**，全域Lint通過；初稿import排序已修正。新code/test檔均低於300行；命令／logs／source hashes與E-A07／L-A01／A03／A11局部scope在`M12-5/rights-inventory/`。
- 此為純連接邊界，尚未被既有historical/session／SQLite workflow呼叫，也未接一般交易賣出、settlement cashflow、stop或外部來源初始持倉。舊checkpoint-v1不改；真實研究／正式前向與完整發布仍未accepted。下一步把現有session的現金／持股與這個邊界統一，另接版本化durable state與來源驗證，而非增加平行現金帳戶。


## 2026-10-30 接續：官方錯誤定位、provider split 手算與新整合來源

- 舊 **session60767 已回 Unknown process id**；306 檔 3.9 log停約六成，verification-results僅有3.13 exit0／793passed。已將acceptance改為handle_missing_without_39_terminal_evidence，原部分log與快照保留；不把缺handle、舊running或無F輸出當作通過。本輪沒有重跑原306來源。
- 官方adapter也接既有PriceSourceError(ValueError)：manifest／raw JSON／schema／hash為檔案層；無效日期、月份、重複、量數／缺欄、價格為原始來源path與parsed data[index]，保留cause。CSVfooter跳過行為及合法輸入／政策／序列化身分不變；此offset不是CSV實體行號。11個direct反例與provider整合兩環境各 **48passed（16.35／23.34秒）**、Lint通過，來源bytes與受檢source/test hashes不變。證據`DATA-02/official-error-context/`；S-A02記此範圍通過，整體未accepted。
- 新`test_provider_split_arithmetic.py`：v1／v2均真正選用FinMind的188.65／47.57原價與row locator，4:1只套一次，回報factor手算4×47.57/188.65；停牌open缺席、volume0。共用distribution純轉移10股→40股、原state保留，NAV=40×47.57；零成本matching買1股仍按raw47.57。兩環境相關各 **8passed（2.46／3.01秒）**、範圍Lint通過；首次新測試import已整理，外部新rights-audit檔未擅改。之後全域Lint重查通過。S-A05此scope已有直接證據；不冒充整段durable或真實零股成交。
- 固定329檔`/private/tmp/qfl-source-integrated-20261030-a`時，恰含較新rights audit_reconstruction的SIM102；兩環境verify.sh均在Lint以exit1終局、未進pytest。保存完整source archive／identity／兩份log與results，該來源不覆寫。工作區隨後已有對應條件合併修正、全域Lint通過。
- 另固定 **329檔 `/private/tmp/qfl-source-integrated-20261030-b`**，copy前後bytes、Git index／source／execution identity完全相同，tar與inventory存`release/integrated-20261030-b/`。涵蓋來源診斷、選源表語義修正、R費用／樣本、provider guards／split及當時rights稽核；後續共享變更不延伸scope。**session35967**循序3.13→3.9完整verify.sh已啟動，未終局；接續追原handle，不平行另開完整suite。
- 下一步收斂此來源終局與最新reader真實舊包相容、J／L必要案例；資料仍沿最新v2 study三期blocked28／23／23與23筆active coverage／兩個rights事件。工程發布、正式研究與實際前向觀察均未accepted。


## 2026-10-30 接續：認購權原命令獨立帳務稽核

- 新增 RightsAudit／audit_rights，先定外部 initial usable cash 與可選外層 inventory posting log 介面，再以獨立方程式重建。新 reducer 不呼叫 grant／付款／交付／到期／碎股／換發／配額修訂轉移函式；測試逐一 monkeypatch 為禁止呼叫以核對獨立性。
- 重算 cash、每腿 entitled／unpaid／pending／delivered／expired／settled fraction、付款本金／費用與最後付款日；原始 grant／後續 revision 保留資訊時間與未消耗檢查。付款／交付／換發／碎股各按原命令的日期、數量、價格／淨款與明列費用核對，固定80位Decimal局部精度。
- 稽核回傳完整 expected movements；提供外層紀錄時，每個 action／debit-credit／權利腿／security／quantity／tradable day 逐一精確比對。缺筆、重複、替代證券／日期，以及布林數量遭拒絕；沒有傳入外層紀錄時不宣稱已驗 inventory 入帳。
- 補17項直接稽核案例，結構合法但 cash／paid／fee／pending／expired／付款日篡改，以及重算 hash 的無效付款窗，均被獨立重建指出；錯 initial cash 不能由最終checkpoint倒推出通過。原始物件／編碼bytes保持，低caller精度不改結果。純核心與新稽核合計兩環境各 **62 passed（0.11／0.22 秒）**，全域Lint通過；三個新code/test檔均低於300行。
- 證據／命令／實際秒數與source hashes在 `artifacts/acceptance/M12-5/rights-independent-audit/`，E-A07／E-A06／L-A11分列範圍。這是原命令財務稽核，不等同官方事實、目前憑證持倉、外層交易交割cash flows或market NAV的來源認證。session／SQL／真實adapter仍未接線；三期實際v2研究維持28／23／23 blocked。後續整合須以新來源再驗完整套件，不能延用舊完整733項。


## 2026-10-30 接續：S 矩陣、真實 405 key 與選源表語義漏洞

- 原 **session60767** 已確認循序推進：306 檔固定來源 Python3.13完整 **793 passed／18 warnings，1692.75秒**、Lint通過；verification-results.json已實際寫入exit0。現在同一程序執行3.9，原快照不修改、不重啟。此結果只涵蓋當時 inventory，不延伸到較晚來源診斷、研究57＋7或本次修正。
- 抽出既有 ready provider fixture 設定供新案例共用，保留原正例。v1／v2各測真實混合選源的基準缺價、整個暖機缺一日、未支援 reduction事件；每例先證 ready，再修改有hash的原始來源並重準備。兩筆FinMind選用仍在，ready變blocked／119 warmup，凍結／load／run／report指紋完全一致，forbidden績效callback未被呼叫。
- 補 v1／v2 分期交接：只有開發期ready、驗證期基準缺價時，只產生三個開發帳戶及開發比較列；驗證期四個策略／基準組合明確unavailable，不匯出驗證曲線。原始來源bytes保留。
- **真實漏洞已重現並修正**：將price_selection.csv的FinMind替換TWSE，再重算合法manifest hash／report ID，原驗證器仍回True。修正前兩版本各失敗、event byte兩反例通過，合計2failed／2passed4.35秒；保存before-selection-verification.py及redirected before log。新25行reporting.py先定公開介面，共用原CSV編碼；provider報告須列入manifest，並與凍結raw／政策重建選源逐位元一致。重算hash或連CSV／manifest entry一同刪除均拒絕；舊格式輸出bytes與原metadata／source policy欄位不變。
- 最終相關六檔兩環境各 **61 passed（16.68／23.55秒）**、全域Lint通過；主Streamlit v1／v2 ready／blocked另各 **4 passed（8.11／11.07秒）**。關鍵source/test hashes於相關執行前後及UI後一致，列明檔案範圍封存reviewed-scope.tar.gz，並非完整repo快照。此前53／55項分輪logs保留原scope；初稿測試unavailable少算benchmark、事件年份及JSON/Enum比較錯誤均明列，未放寬產品守門。
- 真實離線交接已由正式adapter重新讀取33份來源，405個唯一key與原缺檔清單、provider manifest、inventory精確一致。分期31／132／242，原始目標日653／2662／4813，共8128；原缺月key在目前官方manifest仍0。核對最新v2研究metadata／readiness／report files hashes，三期blocked28／23／23、ready清單空、績效0；**58檔bytes保留**，沒有宣稱全native語義重建或資訊可得時間已證實。
- S-A01–A12逐案map已補；S02的官方raw定位、S05的provider-selected split數值手算及S11新reader全舊包相容仍partial。全部accepted維持false。證據與可重跑真實交接script在`DATA-02/provider-guard-edges/`；不將adapter已驗405升格為正式研究完成。
- 下一步追原3.9終局，續補上述明確缺口、J／L必要範圍，再以含本次語義修正的最後來源完整驗證。真實coverage／認購權與實際前向觀察各過自己的閘門。


## 2026-10-30 接續：E05 認購權純帳務核心

- 新增鄰近文件的 `odd_lot_rights/`，先定 EntitlementEvent／PaymentTerms／DeliveryTerms／FractionalCashTerms／ReceiptConversionTerms，再實作不可變純轉移。除權當時的權利與後來付款／交付資訊分開；所有條件有獨立 available_at／證據 SHA，未來資訊拒絕使用。新模組未接歷史／paper 入口，既有資料仍 blocked。
- 多腿權利共用凍結的事件前持股；無償整股成為不可交易的待交付權利，碎股保留精確數量。認購數量及各項費用均明列；批次資金不足整批拒絕，不自動選腿或改數量。付款後待交付、到期未付及後續憑證轉換分開；轉換同時輸出 debit／credit，僅採外層已核驗的實際剩餘憑證，保留新單位的可交易日起點。
- 明確淨額碎股款只按已知條件於結算日入帳；付款、交付及轉換費用不默認為零、不可透支。尚未消耗權利前可依較晚的新證據修訂配額，保留原命令／持股基礎；付款／交付後修訂須另有更正／退款流程，目前拒絕悄悄改寫。
- Decimal／80 位局部運算及 canonical checkpoint 保留精確現金／數量。原命令 receipt 與 hash、逐事件完整腿集合及原持股基礎皆核對；同 action 相同 payload 為 no-op，改 payload／漏腿／一致改配額卻無新命令／重算 hash 的未來條件均拒絕。Codec 是結構／命令一致性，尚不冒充獨立財務稽核或官方資料認證。
- 假設手算：100 cash，10 bonus＋5 ordinary＋2 preferred；付款 5×10＋2×20＝90 後 cash10，示例總值 360 前後守恆；明列費用0.25 後359.75。15×0.1＝1整股待交付＋0.5碎股，後續已知淨款8只入帳一次。已交付5張憑證而外層僅剩3時，只轉換3；交付及換發費用另扣一次。
- Python3.13／3.9 純核心相關各 **45 passed（0.08／0.14 秒）**，全域 Lint 通過；每個新 code/test 檔均低於300行。首批39項與後加配額修訂／跨腿原始命令一致性範圍分列，logs／hash／手算在 `artifacts/acceptance/M12-5/rights-core/`。E-A07／E-A06／L-A03 僅記此純核心範圍，不宣稱 session／SQL 已驗收。
- 下一步認證真實逐腿事實與參與／估值規則，接 source adapter、同一 session 與持倉／現金、版本化 durable state、獨立稽核及 fault/retry；現有 checkpoint-v1 不改。實際最新 v2 study 仍為 `195e874e86026da7a9209f95`、三期 28／23／23，沒有以 hypothetical terms 放行真實事件或績效。


## 2026-10-29 接續：來源診斷與研究 R 案例直接驗收

- 原完整回歸 **session 60767** 本輪經實際 write_stdin 確認存活；306 檔快照 full313 約六成，未取得終局，不重啟、不修改其來源。較晚下述修正與測試均不在該 inventory。
- DATA-02 新增 PriceSourceError(ValueError) 型別，保留來源 path、manifest entry／raw offset／CSV 實體行號與原始 cause；檔案 hash／response shape 失敗不捏造 row。raw／normalized hash 失敗直接指向實際檔案，合法資料及原拒絕規則不變。無效輸入反例保留來源 bytes。
- 來源診斷與既有 provider／停牌／UI 相關兩環境各 **53 passed（9.04／12.20 秒）**，修改範圍 Lint 通過；較早各 49 passed 保留原來源範圍。首次後續全域 Lint 曾因共享工作區新 rights settlement 測試的 import 排序失敗，未擅改該檔；之後全域重查通過，前後 logs 均在 `DATA-02/source-error-context/`。沒有宣稱新的完整 suite 通過。
- R-A09 補同次交易直接整合手算：100 股買入／股利／賣出、滑價與升降單位、佣金及稅同時存在，Decimal 手算淨損益 **-109.21**、期末 cash **99890.79**；T+2 前保留 sale receivable **9750.84**，到期一次入帳，episode／NAV 與來源不變均核對。最初預期漏計既有 tick rounding 而失敗；修正測試手算，沒有改撮合產品邏輯。
- R 相關七檔輕量案例兩環境各 **57 passed（4.77／6.50 秒）**；另補 R-A07 無成交、僅未平倉、只有贏／虧／平手及 29／30 筆已完成邊界，各 **7 passed（0.29／0.31 秒）**。30 筆虧損只解除樣本數提示，負報酬及無勝利不被改寫；未平倉獲利不充當已完成樣本。
- R-A01–A12 已逐列審查 assertions；`M13/research-case-review-20261029/acceptance.json` 區分本次 57＋7、舊固定 737 的 registered 報告整合及未結範圍，不從同測試 bytes 推論最新全部 imports 已驗。R01／R04／R11／R12 仍需最終來源整合，所有 case／milestone accepted 維持 false。
- 接續仍為原完整結果收斂、S／R／J／L 剩餘必要範圍與最後整合來源驗證；真實 study `195e874e86026da7a9209f95` 三期 blocked28／23／23、23 筆 active coverage 及兩個權利事件各自處理。規劃入口為 CURRENT_DELIVERY；本次工程進展未放行正式研究或實際前向觀察。


## 2026-10-29 接續：雙環境 737 終局、v6 未來輸入與歷史 25 包

- 原 296 檔固定來源已完整終局：3.13／3.9 各 **737 passed**，各 16 項既有 pandas warnings、Lint 通過；pytest 分別 1842.21／1812.34 秒。原 session 26804 完成，兩份 log／實際命令／scope 已寫回 consolidation-20261029，不再列執行中。
- 305 檔快照循序 target 完成：兩環境各 **3 passed（141.63／158.21 秒）**，各 2 個既有 warnings、兩套 Lint 通過。真實離線帳戶的 v6 validation／exploration 價格改動，使實際驗證曲線及完整數值結果改變，但保存開發選擇內容／ID 相同；capture context 不同、舊 bytes 保留、固定候選／策略不更換，兩包均可來源讀回。保存階段 spy 僅允許開發績效帳務業務解析；原 candidate batch 仍生成已接觸的歷史全期報告，不宣稱未見驗證資料。
- 匹配 3.13 runtime、305 檔 reader 另核驗 **25 個實際歷史產物**（v1–v6 research、舊 schema-1 決策、v5 selection、schema-2 決策），全部通過；**1,031 個舊檔 bytes** 保留。verifier 使用 mode=ro 原 registry 的一致 SQLite backup；mirror 與原 registry bytes 均未變。實際每包／inventory／runtime 證據在 j05-consolidation/legacy-compatibility.json。跨 profile 限制不因這次 matching-profile 成功解除。
- 較新實際資料基線為 study `c4de77c3feb3999aba0935f5`，三期仍 blocked（**39／34／36**），暖機各 120；原始 issues 40、績效表空。已直接核對 metadata、readiness 與 report manifest SHA 一致，本檢查點沒有重新跑全部 raw-source 語義重建。較早 61／55／56 屬前一來源，保持歷史對照。
- B01 的 E-A01–A11 已另作來源／assertion 對照；新 subscription 能力 E-A07 及 scope-change workflow E-A10 明列 not_covered，完整真實資料仍未 accepted。來源不變的舊測試對應雙環境 737 結果，較晚功能引用各自證據，未將 test-node 存在當作執行。
- 工作區後續加入 v2 合法個股停牌選源（保留 v1 serialized fields／identity）。已新建 `/private/tmp/qfl-release-integrated-20261029-b` **306 檔**固定來源，複製前後 bytes、Git／source／execution identity 完全相同，封存在 `artifacts/acceptance/release/integrated-20261029-b/`。**session 60767** 現循序執行 3.13／3.9 完整 verify.sh；3.13 Lint 已過、測試未終局。這份涵蓋最新 Q／J／停牌政策；原 737 或 305 target 均不自動延伸其 scope。
- 接續追同一 60767，不重啟；終局後以 306 reader 重核歷史相容及逐案發布審查。正式事件來源、未知 rights、研究範圍變更及實際前向啟用各有剩餘條件，整體 goal／發布仍未完成。


## 2026-10-29 接續：除權息／0050 審查與明確 v2 停牌規則

- 補 v1／v2 註冊候選的前向 source-rule 直接反例：end／cutoff 可增加，schema／policy_id 不可互換。最終相關兩環境各 **37 passed（9.29／12.32 秒）**；先前 35 項 logs 保留，較後 `bound313.log`／`bound39.log` 及 source/test hashes 在 `DATA-02/reviewed-halt-policy/`。這是候選規則守門的範圍，沒有冒充已啟用真實前向帳戶。

- 逐筆核對七年除權息索引內固定股票池的 111 筆事件：105 現金股利與原 actions 金額一致，4 筆股票配發保留既有 proxy 及生命週期限制，2 筆認購權明列 unsupported。兩筆休市日期映射及全部原始列／hash 一併保存；77 筆 coverage 發布到新資料 `c14a41bed54875509d78b193`，study `825a481acfb4fc5bafc5afef` 的三期 blocked 為 28／23／25，績效空白。
- 再目視核對 0050 官方一頁分割公告、年度索引、4:1 action 及五個停牌 session；執行資料仍是 NaN open、0 volume、前收估值，僅恢復日有一次 split。新增 2025 年 split coverage 的資料 `1dd6777dbcfb171323a55c87`、study `904a4a43f3a603c91ffa353d`，三期 28／23／24、raw issues 28。初次核對腳本把 0 無事件當 split 計數，已保留失敗 log／script 並修正為正且非 1 的事件；未改產品或來源。
- 發現最後 no-quote finding 在已有獨立官方個股停牌證據時仍由 v1 保守政策阻擋；新增明確 `reviewed_provider_v2`／schema2。僅精確 symbol/date 的已載入官方停牌、0 成交量且無已報告成交額／筆數可略去重複 no-quote finding。無證據、報價與停牌矛盾、全零 OHLC 卻有正 volume／turnover／trades 仍阻擋；prior close、日曆、事件、暖機仍由共用規則處理。
- v1 保持預設、原欄位／已知 fingerprint 與原嚴格行為；v2 以既有 schema／policy_id 組合另凍結身分，拒絕交叉版本。UI 新增預設不勾選的「依官方個股停牌證據核對無報價」。原兩個 UI 案例 ID 保留，另驗 v2 ready／blocked 與實際凍結政策。兩環境相關各 **35 passed（10.07／13.35 秒）**、Lint 通過；初次 v2 正例 1 failed／3 passed、活動矛盾反例 3 failed／4 passed 留存 before logs，未把反例移除。
- 同一 raw／行情與資料 `1dd...` 下另建 v2 study `195e874e86026da7a9209f95`、報告 `58e2d92cdf1a4bb887cce77fd67a5f8b`，完整性通過；三期 findings **28／23／23**、raw issues **27**、績效 0。保留 2317 原無報價來源 ID；原 v1 study 於發布前後均以 native profile 重建，bytes／readiness 指紋保持。
- 證據分別在 `M12-5/ex-rights-review/`、`M12-5/0050-split-review/`、`DATA-02/reviewed-halt-policy/`。新 v2 程式／UI 不在舊 733 項完整 inventory；S-A04／A06／A09–A11 只記已核對範圍，不提升發布、跨 profile 或正式前向狀態。下一步處理普通股 split／other_rights 與 ETF 類別適用範圍，並補齊認購權事實／型別與帳務能力。


## 2026-10-29 接續：J05 全失敗預算與新固定快照

- 新增 `test_phased_decision_edges.py`：v6／schema-2 與 v5／schema-1 各以兩個候選、每候選兩次 failed 歷史驗證。完整四次原因隨來源保存，不讀 v6 validation、不產生開發分數／排名／候選；同來源兩次發布 ID 相同且各有新目錄，舊 bytes 保留。兩種 UI 都顯示兩候選、四次失敗，重繪與再次讀取沒有寫入。
- 兩環境各 **2 passed（12.34／15.74 秒）**；全域 Lint／diff check 通過。這是獨立 target 範圍，不延伸先前 737 項完整快照。J-A03 的 dedicated all-failed v6 export 缺例已補，整體 J05 尚待最後來源驗收。
- 準備 `test_phased_future_inputs.py`：將真正 validation／exploration 價格改變的 fixture 接 v6 save-selection／publish；保存時只允許開發帳務業務解析，後續仍固定同一選擇，並比較實際 validation 曲線。phased fixture 增明列 prices／exploration 測試參數，預設語義維持。此重案例目前 **尚未執行**，不能列通過；等待原完整 3.9 終局後循序執行。
- 新 `/private/tmp/qfl-j05-final-20261029-a` 固定快照共 **305 檔**，複製前後檔案 bytes、Git diff／revision 與 execution identity 完全一致，來源 inventory 與 tar 已保存 `artifacts/acceptance/M13/j05-consolidation/`。名稱是後續驗收用途，不代表已驗證。較晚工作區或外部 durable-event 變更不自動延用其結果。
- 原完整 verify.sh 仍是 **session 26804**，目前 3.9 約七成、未終局；原 3.13 已有 737 passed。繼續追原程序，不重啟、不與重的 future-input／真實 archive audit 同時執行。接續命令、pending case、兩個 target 結果及 source hashes 在 j05-consolidation/acceptance.json，80 案索引已重建；發布與真實資料仍未 accepted。


## 2026-10-29 接續：737 項整合回歸與共用修復摘要

- 296 檔固定快照 Python 3.13 完整 verify.sh 已終局：**737 passed、16 既有 pandas warnings，1842.21 秒**，Lint 通過。原先 ready UI 逾時案例包含於這次完整成功結果。相同 **session 26804** 已循序進入 3.9，應追同一程序；新摘要不在此快照，未借用此結果覆蓋較晚工作。
- 找到 Q-A07 的實際顯示缺口，新增 `PeriodRepairSummary` 與 repairs.py 共用介面，分列期內／暖機缺月來源鍵、預期／已驗證／未驗證 sessions 及 required shortfall。只取正式 blockers，按標的月份去重；同月雙窗口不加總，未知暖機窗口不造零。UI、CSV、HTML 同源，不重新決定 readiness。
- 新報告明列 period_repairs_v1 規則、hash 保護 readiness_repairs.csv，讀回另由原 readiness 重建 CSV；竄改數字後重算 manifest hash 仍拒絕。舊無此宣告／檔案的報告維持原驗證，未知規則拒絕。大型 study 模組只接匯出／核驗呼叫，其餘邏輯與型別鄰近新模組。
- 兩環境相關各 **31 passed（6.08／6.94 秒）**、Lint 通過；後補重算身分的新 study 篡改與主 AppTest 精確核對後，兩環境整合各 **23 passed（7.56／9.19 秒）**。主 AppTest ready／blocked 的指紋、blocking IDs／count 與報告相同，實際 SQLite 帳戶數為 3／0；blocked performance 計算另以 forbidden callback 證明未被呼叫。UI 重繪保留 frozen/report bytes。
- 初次 10 案 target 為 3 failed／7 passed：測試直接比 Python tuples 與 JSON lists，且跨期案例 calendar cutoff 比 freeze 多出來源尾段；已按正式 cutoff／canonical JSON 核對修正，未放寬來源身分或判定。新增 helper 的 loop closure／import Lint 已整理。分輪結果與 limitations 保存在 `artifacts/acceptance/B01/readiness-repair-summary-20261029/acceptance.json`。
- 重新審查 Q-A05 的合法停牌／120 session 與 Q-A09 的 legacy coverage 既有直接 assertions；Q-A01–A12 現全有離線案例證據。Q-A11 延用已核對未變依賴的原匯入修復紀錄；案例 passed 與里程碑 accepted 分開，後者仍 false。80 案索引已重建，沒有從總數自動放行。
- 下一步先收斂原 3.9 完整結果，再以最後整合來源安排新完整快照，處理 J05／舊 schema-1 真實包相容與其餘發布證據。共享工作區另有 durable-event 測試變動，保留且不宣稱本輪已覆蓋。真實 coverage／rights 與實際前向資料仍分別驗收。


## 2026-10-29 接續：分類覆蓋第二批與原固定雙環境終局

- 原 292 檔副本的兩環境一鍵驗證均終局：3.13 **733 passed、16 warnings（1847.05 秒）**；3.9 **733 passed、16 warnings（2107.18 秒）**，exit0、isolated import／版本、Lint 通過。兩份完整 logs／SHA 與固定 inventory 已保存 `M14/latest-review/`；涵蓋當時 durable matrix／重建／benchmark 修正，不涵蓋後加 coverage、fault／tampering 或其他共享工作區變更，accepted 仍 false。
- 第二批逐份檢視 16 份原始年度索引，共 63 筆。普通股面額變更限固定 10 股、2020–2026；普通股減資限固定 10 股、2024–2026；ETF 分割限 0050 的 2020–2024／2026。每份保留完整 ID／原列、URL／hash、類別與標的集合；2026 截至原截止日 10/27，沒有認證未來日期。
- 發布 106 筆分類／年度 CoverageReview 的新資料 `088645c5d846879a65ec30e8`，父包與前研究 inventory 不變；新 study `c4de77c3feb3999aba0935f5`、報告 `5d0065040643414581b53f9fa51df45a` 完整性通過。三期 findings **39／34／36**，raw quality issues **40**，三期均 blocked、績效列數 0。原 50／55／56 與 61／55／56 結果各保留其 study 身分。
- 普通股 split 未從 ETF-only 索引推定完成；0050 的 2025 實際分割、ETF 其他類別適用範圍、ex_rights／other_rights 與兩個認購權事件繼續分項核對。這批沒有改策略、成本、股票池、日期或價格政策。
- 增補 E-A06 直接案例：用 2881 真實數值 fixture 明列五類 coverage 後，覆蓋缺口消失但未建模認購權仍阻擋，價格與父 bytes 不變。相關兩環境各 **28 passed（1.43／1.65 秒）**、Lint 通過。來源審查、可重跑程式、結果與 E-A06／A09／A11 範圍見 `artifacts/acceptance/M12-5/coverage-index-followup/`。


## 2026-10-29 接續：顯式 coverage 發布與開發期減資首批

- 原 292 檔固定副本 session 76077 已終局，Python 3.13 一鍵驗證 **733 passed、16 warnings（1847.05 秒）**，isolated import／版本與 Lint 同樣通過。完整 log／exit0／SHA 已存 `M14/latest-review/full313.log` 及 acceptance；3.9 session 5121 本輪仍 live。本次新 coverage、較晚 durable fault／tampering 與其他共享工作區變更不在此完整 inventory，不將 733 項通過升格為最新發布通過。

- 新增 CoverageReview／derive_coverage_bundle：固定標的、類別、期間、官方 URL、審核時刻／說明與證據 SHA；保留父 bundle、舊 coverage／manifest 及 registry 缺席標記，原子發布新內容身分。不自動升級 legacy coverage，不用一類審核替代其他類；來源競態／既存產物篡改拒絕。
- 新增 13 個案例，連同 closure／readiness 回歸兩環境各 **27 passed（1.81／2.01 秒）**、Lint 通過。案例實際核對只補一類仍有其他 14 個缺口、單日中斷仍阻擋、parent bytes、審核證據進入 source hashes、壞來源與來源複製競態、篡改後拒絕覆寫。
- 已逐份檢視 2020–2023 四份官方減資恢復買賣索引的全部代號與原列，共 112 筆；固定十檔股票＋0050 無命中。發布 44 筆明確年度審核的新資料 `706eb52897928c221904a08f`，只涵蓋 2020-04-27 至 2023-12-31 的 reduction。新凍結 study `b9b633c190f914bf72b53d05`、報告 `041c3b9aa2244278b01827412cfeefbe` 完整性通過；舊 study inventory 不變。
- 三期 blocked findings **50／55／56**，開發期下降 11；全期間 raw issues 仍 60，因 reduction 缺口改從 2024 年起。績效列數 0，沒有放行策略或前向帳戶。四份逐年原列／hash 審查、可重跑程式與 logs 在 `artifacts/acceptance/M12-5/development-reduction/`，E-A02／A09／A11 範圍分列；不宣稱 E03 或 M12-5 全完成。
- 富邦官方三重副檔名年報另保存為獨立 bytes 版本；第 382 頁補核對無償配股增資基準日 2021-09-12，與除權日、配股交付及現增腿分列。已確認的上市時序不重算為新缺口解決；新證據及 metadata／刊印日限制見 EVENT_INVESTIGATION。
- 本次新 module／tests 不在先前執行中的完整 suite inventories，後續整合須核對差異；原固定副本不修改或重啟。


## 2026-10-29 接續：四個 Q 驗收缺口已有直接案例

- 新增 `tests/test_readiness_acceptance_edges.py`（143 行，產品邏輯未變）。Q-A01 核對實際重複準備／評估的完整 findings／期間／指紋，以及整個 fixture 目錄含 sentinel SQLite／sidecars 的 bytes；Q-A02 將已評估 findings 的顯示文字翻譯，兩份 UI 保留相同語義 ID／blocked／count，無磁碟變動。
- Q-A03 實際移除月價量來源，再經清單匯出與 batch import 修復：input fingerprint 改變、缺月消失，獨立減資索引的未建模事件 blocking IDs 與缺 split coverage 均保留。Q-A06 只有 ETF split 審核缺漏、全部報價完整時，正式凍結 runner 與直接 assessment 的 readiness 指紋相同，帳戶結果與比較績效為空。
- Python 3.13／3.9 各 **4 passed（2.24／2.66 秒）**，全域 Lint 通過。初次缺審核 fixture 未傳實際 quality_issues，frozen-source guard 正確拒絕；已修正測試傳入真實 issues，沒有改產品守門。初稿 import 排序已修正。
- 證據與四案 scope 在 `artifacts/acceptance/B01/readiness-acceptance-edges-20261029/`，合併 Q 審查另存 consolidated-review.json，原檢查點保留。80 案索引已重建，四案記離線 scope passed，里程碑 accepted 仍 false。此新測試檔不在正在執行的 296 檔快照，不能延伸其完整回歸範圍。
- 原完整 verify.sh 仍按 **session 26804** 循序兩環境；最新約六成無失敗輸出，未終局，不重啟。接續追終局、舊 schema-1 相容性及剩餘 Q／J 案例；真實資料另過來源閘門。


## 2026-10-29 接續：實際業務中斷與重算 hash 篡改驗證

- 新增 `test_odd_lot_durable_fault_boundaries.py`：先執行並斷言真正成交、賣款 T+2 入帳、股利／反向分割後 NAV，再拋出 RuntimeError 或 KeyboardInterrupt；另涵蓋 SQL checkpoint、events 與提交前獨立稽核。12 個案例均確認完成 prefix／SQLite bytes 不變，重開後可重試，最終 state／全部業務事件與一次完成一致；最後 no-op 不改 bytes。
- 新增 `test_odd_lot_durable_tampering.py`：持倉股數、交割金額與重複成交各自竄改，重新計算合法 chain digest；重複成交使用合法 ordinal／business ID。先證實結構驗證通過，再確認獨立帳務稽核指出 positions／settlement 問題，續跑拒絕且不修復、不改 bytes。雙環境各 3 passed（1.28／1.51 秒）。
- 前述中斷矩陣兩環境各 12 passed（13.76／18.78 秒）；全部 7 個合法切點擴充的 events／settlements 各 14 passed（19.13／24.32 秒）。三組分開執行，每環境合計 29 項，並非完整 suite。六份終局 logs、L-A01／A02／A11 assertion 審查及測後 source hashes 已保存 `artifacts/acceptance/M14/durable-fault-review/acceptance.json`；B01 80 案索引已重建，不自動 accepted。
- 原 M14 完整回歸 session 76077／5121 本輪輪詢仍 live；較晚整合 session 26804 在此工具上下文回傳 Unknown process id，不能依舊 acceptance 的 running 推定仍活躍或終局，不重啟。後續須核對該整合程序的實際狀態及終局 log。新增測試不在較早固定 inventories；發布／資料與實際前向觀察仍未放行。


## 2026-10-29 接續：權利事件原始來源補存

- 完整整合 verify.sh 的原 **session 26804** 已重新輪詢確認仍活躍；3.13 約四成，未終局，之後循序 3.9。未重新啟動或修改其 296 檔快照。
- 等待期間補取富邦官方 2021 年報 572 頁，PDF 第 144／183 頁（印刷 142／181）擷取、渲染及目視核對。確認 58.9／60 元兩種股發行價、10-26 收足款項、10-29 憑證上市及 12-06 憑證下市／增資新股上市；另將 10-29 資本公積配股發放分列。原始 SHA、圖片、欄位與未證實資訊時點在 `artifacts/acceptance/M12-5/fubon-2021-annual-review/source-review.json`；10 個 evidence hashes 核對通過。未完成 9-06 各腿權利／個人認購條件的全部連結，unsupported 維持。
- 國泰官方 2022 年報及 111 股東會年報原檔已存，但目標換發公告頁未定位／目視核驗；未因關鍵字搜尋無命中推定無事件。2023-02-10 換發日期僅列第三方轉載線索，待原公告。
- 官方現增頁原先逾時的 raw HTML 現已取得，SHA `53afde9b64a25b736a57ca0124af4558f61a59bca7d5f00d2d6d66f02e067ba0`。原股東公告認購比例保留「依基準日名簿」限定，繳款批次及畸零處置條件已逐欄核對；`cathay-2022-annual-review/capital-source-review.json` 保存原 bytes／文字及缺欄位。未將網站公告日期當作歷史版本證明或直接變成模擬政策。
- 本輪沒有改程式、正式資料包或舊研究；hash／欄位斷言與 diff check 通過。工程完整驗證仍循原 session；事件與 readiness 不放行。下一步在完整 suite 結束後核驗舊決策相容性及病例矩陣，資料面接原始認股／換發公告與 coverage。


## 2026-10-29 接續：唯讀修正、真實瀏覽及整合回歸

- 原研究 UI 快照逾時案例在同一 `/private/tmp/qfl-research-ui-20261029-b`、同一 30 秒限制單獨重跑 **1 passed（3.63 秒）**。未定位原整套逾時的根因；原 703 passed／1 failed 紀錄保留，單案成功不替代完整閘門。
- `real_browser.py` 已在匹配 3.13 profile 及原固定快照核驗真實 v6 包：UI 顯示 incomplete_search，兩次 blocked 歷史；重繪前後 registry／report bytes 不變，attempts_added=0。證據為 `artifacts/acceptance/M13/research-ui/real_browser.json`；J-A11_ui_real 已記此範圍 passed，整體 J05 未 accepted。
- 新增反例確認舊 schema-1 共用 collector 的可寫 registry constructor 會將空檔初始化後才拒絕。`registry_evidence.py` 現改用既有 ReadOnlyExperimentRegistry，不改舊包 schema 或歷史語義。空檔、foreign／unsupported DB 拒絕且 bytes／sidecars 不變；合法失敗歷史正常收集。雙環境各 **10 passed（3.33／3.94 秒）**，3.13 全域 Lint 通過。初次測試 fixture 少 execution 參數、import 排序與 runtime symlink 誤選已校正，紀錄保留於 legacy-readonly/acceptance.json。
- 新整合固定快照 `/private/tmp/qfl-consolidation-20261029-a` 共 **296 檔**，複製前後 bytes、Git diff／revision 及 execution identity 全一致，封存在 `artifacts/acceptance/release/consolidation-20261029/`。**session 26804** 依序執行 3.13、3.9 的 verify.sh；3.13 Lint 已過，完整 suite 尚在執行。快照不再修改，後來共享工作區變動另驗；輪詢原 session，不因等待無輸出重啟。
- 下一步收斂同一來源的完整雙環境結果，核驗唯讀修正對既有 schema-1 真實包的相容性，補 J05／發布案例證據。資料三期、跨 profile 與實際前向閘門維持未放行。


## 最新接續：完整回歸終局、前向基準 prefix 修正及權利證據

- 原固定來源 3.13 full session 86681 已終局：**694 passed、14 warnings（1760.04 秒）**；收盤修正 3.9 full session 60335：**696 passed、14 warnings（1917.10 秒）**。logs 已存 M14/forward-accounts/full313.log 與 close-full39.log。它們不涵蓋後續 durable matrix／重建／基準修正；沒有提升整個工作區或發布狀態。
- L-A08 審查發現 incoming forward 資料的歷史 benchmark 未與舊原始封存相比：新增 3 個反例，修改暖機期 open、已完成 close／volume，原 no-op 均沒有拒絕（3 failed，6.88 秒）。修正 verify_ledger，同時重建 trading-only SQL prefix 與全部 trading＋benchmark panels prefix，逐完成日比較當前輸入；保留舊財務 input digest 語義。
- 兩環境 benchmark／binding／readonly 回歸各 **14 passed（28.24／39.83 秒）**，含未完成日期的 benchmark 變更仍可續跑之正例。SQLite 拒絕前後 bytes 相同，Lint 通過；before/after logs、2 份 source hashes 與局部 L-A08 scope 在 M14/benchmark-prefix/。
- 292 檔最新固定來源 `/private/tmp/qfl-m14-review-source-20261029` 已保存，涵蓋前述重建、durable matrix 與 benchmark 修正。初次複製漏 verify.sh executable mode，兩次命令 exit126，未跑測試；已保留原 script mode 後重試。兩環境一鍵驗證的 isolated import／版本與 Lint 通過，完整 pytest session 76077／5121、logs `/private/tmp/qfl-m14-review-full313.log`／`qfl-m14-review-full39.log` 正在執行；不修改該副本或借用舊完整結果。
- 資料並行補查：由臺銀證券官方站取得富邦金普通股現增承銷 PDF，正常 TLS 下載、原 bytes／SHA、全文與兩頁 PNG 已保存及視覺核對。原股東分配、普通股定價、兩腿及畸零規則更明確；預定上市不當作實際交付，公開申購繳款不當作原股東繳款。prospectus 另一 URL 404、sandbox DNS 失敗與 font-cache warning 皆分列。正式 actions／coverage／readiness 未改；仍須逐腿實際公告、資訊時點與執行模型。

## 2026-10-29 規劃核對：完整回歸已終局

研究 UI 固定快照的 `artifacts/acceptance/M13/research-ui/full313.log` 已記錄 **1 failed、703 passed、16 warnings，1858.70 秒**。失敗節點為 `tests/test_reviewed_odd_lot_ui.py::test_provider_study_ui_uses_shared_ready_or_blocked_decision[True]`，AppTest 超過 30 秒，尚未定位原因。本輪僅核對既有 log，沒有重跑完整 suite，也未因逾時放寬守門或認定環境負載為根因。下方 session 60353 執行中的段落是較早檢查點。接續依[發展收斂計畫](DEVELOPMENT_CONSOLIDATION.md)定位失敗、整合最新來源驗證及逐案驗收；此紀錄不涵蓋較晚 M14 變更。

## M14 最新接續：保留原帳戶的明確歷史重建

- 新增 HistoricalRebuildResult／rebuild_registered_account：拒絕相同／既存目的路徑；先核驗 parent 結構及財務，再按相同 protocol／候選設定／期間 origin 用 mode=ro replay 核驗原始來源、snapshot 與完成 prefix。parent 至少有一個完成日；未知 schema、損壞／缺 snapshot 或 forward 帳戶不自動轉換／修復。
- Replay 內部新增只讀模式，拒絕 create 及超過最後已完成日的資料推進，失敗／成功核驗 SQLite bytes 均保持。歷史 workflow 可接 rebuild parent guard，於新帳戶 SQL checkpoint／events stages 重核 parent file／WAL hash；外部變動使新當日全 rollback，產品不還原外部改動。
- UI 增單獨目的路徑與「保留原帳戶並重建至新路徑」提交；來源仍為已選協議／候選／期間，普通操作預設續跑。成功顯示 parent 路徑／hash／completion digest 及新帳戶；重繪不重送，失敗不 reset 或自動改建帳。父參照由 API 回傳及 UI 呈現；新帳戶之後獨立按凍結來源續跑，不宣稱有依賴父檔的隱藏遷移。
- 補來源唯讀核驗前首輪兩環境各 14 passed（18.64／21.79 秒）；補強後 rebuild／UI／registered／durable replay 各 **18 passed**（25.94／31.60 秒），另 readonly／snapshot／financial 各 **13 passed**（5.61／7.55 秒）。Lint／diff check 通過；命令、logs、7 個 source/test hashes、L-A12／A02／A10 局部 scope 在 M14/historical-rebuild/acceptance.json。未把舊完整 suite 結果套給本次延伸。
- 原 3.13 full session 86681 與 close-refined 3.9 full session 60335 持續以各自固定 inventory 執行；本次 rebuild、read-only 與新 durable event tests 另有證據。下一步收斂固定來源完整回歸、逐案工程審查及真實來源閘門；整體 M14／發布／正式前向觀察仍未 accepted。

## R07／J04：研究瀏覽與明確操作 UI 檢查點（2026-10-29）

- 主 Streamlit 側欄新增「零股研究協議與決策瀏覽」。inspection.py 先定 ResearchOverview／SavedDecisionView，再接唯讀 registry、保存 selection 與 schema-1／schema-2 決策的既有來源核驗；完整候選、未嘗試／failed／blocked／running 歷史與凍結政策可見。來源不符不展示決策績效，profile 不同提示使用凍結環境，不自動切換或放寬判定。
- 預設只讀；「顯示凍結／執行操作」另需使用者開啟，各自表單送出才可建立 v6 政策子協議、執行已凍結候選、保存 selection 後產生決策。完整 JSON 門檻／optional 選擇須明列，改政策保留父協議、原候選預算與歷史用途；失敗／重繪不自動重試、改選或 reset。寫入邏輯另置 actions.py／ui_actions.py，未將聚合判斷加入大型 UI。
- AppTest 初稿 8 項通過（17.69 秒），瀏覽／操作 15 項通過（22.73 秒）；獨立快照含實際 continue／return 畫面來源核驗的 17 項通過（180.05 秒），再補實際 UI 凍結／決策發布 2 項通過（5.48 秒）。初次 Lint 的 import／型別例外／未使用 import 已修正，最終 Lint 通過；所有新檔低於 300 行。
- 每次唯讀及重繪前後核對檔案 hash；未新增 DB／attempt／協議／報告。實際政策表單只新增一個子協議且沒有嘗試；決策表單只建立一次 selection 與最終包，重繪不重送。UI 直接顯示後端 continue／return／insufficient_sample／incomplete_search，沒有第二套排名或門檻。
- 最終固定快照 `/private/tmp/qfl-research-ui-20261029-b` 複製時與工作區 execution identity 完全一致，289 個檔案及封存 hash 在 `artifacts/acceptance/M13/research-ui/`。Python 3.13 完整回歸程序 **session 60353** 仍在執行，log 為該目錄 `full313.log`；目前已超過一半、尚未出現失敗，不能宣稱完整通過。稍早較長的既有 forward-workflow 整合案例已持續產出模擬帳戶／快照，未因無輸出重啟或略過。
- 下一步先續等同一 live handle，完成後再循序跑同快照 3.9 完整回歸及 `real_browser.py` 真實 native-profile blocked 決策瀏覽。19 個相關案例分輪紀錄，不當成整個 J04／J05／發布矩陣 accepted；真實資料與跨 profile 品質限制維持。

## M14 最新接續：SQL 事件與交割手算矩陣

- 新增兩份測試檔，產品邏輯未在本單元變更。真正從空帳戶建倉，再於買進 T+2、同日股利＋反向分割、碎股應收／延後現金日切分、序列化與重開 SQL；state／input digest／各業務事件完全一致。Snapshot linkage 合理反映完整或 prefix capture 的不同，沒有假稱產物 hash 一律相同。
- 手算：1000 元買 3 股×100→cash 700；股利 3×2→706；0.5 反向分割剩 1 股＋0.5 權利，估值 98；權利以 200 結算 100，cash 806＋股值 196＝NAV 1002。事件插入後故障，當日 shares／cash／rights／checkpoint／events 全 rollback；重試結果與完整執行相同。
- 交割手算：300 元賣股的正應收，T+2 開盤仍不可支用，close 才 credit，因此下一日開盤才買進另一標的。小額賣出 gross 10、minimum fee 20 產生 -10 obligation；cash 970→960，T+2 不重扣。另核對 999 requested／499 filled／500 expired，重開 SQL 不補買；每日 stop 跳空到 90 遇無報價 opening，SELL retry 保留並於次日出清，270 應收只結算一次。
- Python 3.13／3.9 各 **11 passed**（13.90／17.01 秒），Lint／diff check 通過；完整 logs、兩份 source hash、手算與 L-A01–A07 局部 mapping 在 `M14/durable-event-matrix/acceptance.json`。初次 settlement fixture 漏 price_limit_pct，正式驗證拒絕；已補 fixture 必要欄位，未放寬 production guard。
- B01 80 案索引已重建，仍須逐案審查。這兩份新增測試不在目前執行中的早期固定副本；原 3.13 full session 86681、收盤修正 3.9 full session 60335 均以原 source inventory 追蹤，未重啟。前向重建操作完整矩陣、發布審查與真實來源仍有剩餘工作。

## M14 最新接續：前向來源封存、交易綁定及操作 UI

- 後續 3.9 fixed public workflow 也終局：3 passed、1 項既有 warning（600.18 秒），與 3.13 同樣涵蓋首日啟用、公開 no-op 及尾端缺價停留最後完整日；log 已保存 workflow-fixed39.log。前述 case mapping 的公開 no-op pending 已改成通過該固定範圍，L-A13 仍 partial，未解除真實來源閘門。收盤修正副本共收集 696 項；collection 不是執行通過，完整 suites 仍按原 handles 追蹤。

- 固定副本 public workflow 3.13 已終局：3 passed、1 項既有 warning（536.95 秒），涵蓋真實決策認證＋模擬未來首日啟用、重送 no-op／SQLite bytes 不變、請求尾端缺行情時 blocked 且最後完整日不變。log 已保存 forward-accounts/workflow-fixed313.log；3.9 同組 session 58987 仍在運算，read-only process 診斷確認 CPU 活躍，未終止或重啟。
- 檢查取得時點發現同日盤中記錄可被誤當成完整日資料；observation_gate 現改核對凍結 XTAI calendar 的 session_close，而非只比日期。新增收盤前一分鐘拒絕、收盤邊界接受；與 gate／binding／archive 回歸兩環境各 24 passed（24.28／32.29 秒），Lint 通過。其後修正範圍與兩份 hash 另列 session_close_refinement，不借用前一副本完整套件結果。
- 最新收盤修正副本 `/private/tmp/qfl-forward-close-source-20261029` 以先前固定來源加上這兩檔建立，283 檔 inventory 已保存；3.9 Lint 通過，完整 pytest session 60335、log `/private/tmp/qfl-forward-close-full39.log` 正在執行。先前 3.13 full session 86681 繼續驗證原 inventory；舊副本不宣稱涵蓋收盤修正或共用工作區後續 R07 變更。

- 最新固定來源 3.9 archive／binding／replay／snapshot／financial／UI 相關回歸 36 passed（32.50 秒），log 已存 forward-accounts/related39.log。36 個本次 package／forward／archive Python 檔與固定副本 hash 相符；README 其後更新，因此沒有宣稱所有文件 bytes 相同。B01 80 案索引已重建，新增 L-A02／03／08／09／10／12／13 局部 scope，沒有自動 accepted；索引工具 4 passed（0.35 秒）。最新 Lint／diff check 通過。
- 固定來源 public workflow session 42406／58987 與 3.13 full suite session 86681 仍活躍，分別 logs `/private/tmp/qfl-forward-fixed313.log`、`qfl-forward-fixed39.log`、`qfl-forward-full313.log`。結果未終局前不宣稱通過，不因觀測等待重啟；下次延續原 handles。相關命令／inventory／案例 mapping 保存在 M14/forward-accounts/acceptance.json。

- 新增 SourceArchiveLink／publish_source_archive／verify_source_archive，完整原始 manifest、審核表及來源 bytes 以內容定址保存；精確 inventory、hash、symlink／非法路徑與新舊來源版本分別核驗。來源與 SQL 無跨檔原子性，未引用孤兒 archive 不算已完成日。
- ForwardReplayBinding 鎖 plan／設定／來源根目錄／選源規則，observation 證據與業務事件、checkpoint 及完成指紋同 transaction。每個已完成日的 archived raw rebuild 必須重建 readiness／acquisitions，且期間 prefix 等於 SQL input_digest；獨立財務／風險與 normalized snapshot 核驗仍共用。改設定／identity 不建帳；重算 hash 的 plan／來源替換、交易內 archive 篡改及缺舊 archive 拒絕。
- 兩環境來源封存／binding／replay／snapshot／financial 相關各 25 passed（21.72／29.31 秒）；後加「合法但非原輸入的替代來源」prefix 案例 3.13 binding 7 passed（13.89 秒）。不同輪次範圍分列，不推論最新全部相同。
- run_observation_account 已接真正決策認證及虛擬帳戶；最初兩環境完整離線模擬未來日 fixture 各 3 passed（261.71／294.24 秒）。後加 no-op／缺尾端案例在共用來源遇到決策發布前 execution/source guard 拒絕（3.13：2 passed／1 failed，52.37 秒）；未弱化守門，改固定 `/private/tmp/qfl-forward-source-20261029` 副本追蹤，283 個來源檔 inventory 已保存，3.13／3.9 session 42406／58987 仍執行。
- 前向 UI 新增註冊／唯讀 plan／顯式建帳或續跑；主 sidebar 獨立入口，不改預設歷史操作。UI 共用 backend statuses，重繪不重送、失敗不 reset；兩環境連同歷史 UI 各 10 passed（3.26／3.15 秒）。先前新測試的 import／unused／dict-style Lint 已整理；最新工作區與固定副本 Lint 皆通過，後續完整 suite 仍須核對。
- 正向未來日／取得時間皆為明示離線模擬，不是真實前向觀察；三期正式研究維持 blocked（61／55／56），coverage 與兩個 rights、完整案例與發布門檻尚未完成。下一步收斂固定來源回歸、前向故障／缺資料矩陣，並與 B01／R07 UI 案例逐案對照。

## R07 最新接續：v6 保存選擇後固定驗證與 schema-2 決策包（2026-10-29）

- 新增明列的 `phased_decisions=True`／v6 analysis plan，固定 `saved_development_selection_then_validation_v1`、`persist_before_validation_v1` 與 `development_selection_v1`。缺政策、未知規則、舊 v5 注入 capture 欄位均拒絕；預設 v1–v5 計畫維持原身分。舊全證據 collector 明確拒絕 v6，不能繞過保存步驟。
- `evaluate_saved_selection()` 先從已落盤 capture 重建全部開發證據／政策／前綴，再核驗固定候選的完整來源、讀取固定策略與必要 ETF／情境證據。無選擇不解析 validation；`evaluate_selected_development()` 不重新排名，拒絕替代候選或與保存開發值矛盾的來源。驗證未通過、未知項及例外都保留原選擇。
- `export_phased_decision()` 原子發布 `<protocol>/<decision>/<capture UUID>/`，含 selection 副本、參照、全來源歷史、固定候選 evidence、決策／CSV／HTML 與 schema-2 manifest。讀回重建政策／來源／固定判斷；重算 hash 的選擇、參照或結果篡改仍拒絕。舊前綴可歷史核驗，但 registry 有新嘗試後不能發布為當前結果；失敗不刪除先前 selection。
- 新檔 selected_evaluation／phased_evaluation／phased_reporting 分別為 71／57／145 行，測試拆檔均低於 300 行；既有大 UI／研究迴圈未在本單元改寫。舊文件中的「第二階段尚缺」保留前輪範圍，現有介面以鄰近 README 的 v6 段為準。
- 初次共用工作區相關測試 5 passed／1 failed（30.45 秒），原 source/protocol/execution guard 在其他檔案變動時拒絕正向執行；未弱化守門。改用保留 HEAD index 的獨立 Git 快照，複製時 source bytes、Git diff、revision 與 execution identity 全相符。先前快照相關 11 項通過（160.11 秒）；補完整 return／錯 manifest 案例後，最後相關 25 項通過（230.94 秒）。
- 最後快照兩環境循序完整驗證皆通過：**Python 3.13 為 629 passed（919.30 秒），Python 3.9 為 629 passed（1019.72 秒）**，兩套 Lint 通過；各 12 項既有 pandas concat warnings，未 skip 或放寬 timeout。260 個來源檔已封存，37 個本次後端／測試檔與快照逐檔相符。這是固定快照的驗證，不宣稱涵蓋共用工作區後來的其他變更。
- 真實資料另凍結 v6 子協議 `722e18ab0bfc45a3e1dc1408370085b87801e5ab57b473bc00ba863acdfc09a6`，兩次均 blocked／incomplete_search，沒有選定候選或 validation 業務數值。selection ID 均為 `bb8e384b7826ae678d33735b2b62e630348589a96c2e7f697b30ec5979fea9d5`，decision ID 均為 `d3b74aa6f4678e094f73cd69a53c1b0866e1ed5ff058a6bc2867ffa1c67b97d7`；原研究數值指紋仍為 `058b00628e373d80352ac147c9dcc5cb2722177881c7ba0505f72a8edccf8e00`。兩個捕捉 audit 不同，973 個先前研究／決策檔案 bytes 保留。
- 在匹配的 3.13 profile 下，另核驗 23 個既存產物，包括 v1–v6 研究報告、schema-1 決策及較早 v5 selection capture，核驗前後 bytes 不變。**跨 profile 不宣稱相容**：3.9 讀這兩份 3.13 凍結的真實包時，既有 frozen-quality guard 拒絕；重建為 63 findings，相對保存的 61 多出 2024-10-02／10-03 兩筆 calendar findings，並非篡改 selection。差異已保存，未把新增 findings 隱藏或放寬為通過；真實封存目前用匹配凍結環境核驗。這與兩套各自 629 項完整測試結果分列。
- 全部 log、快照／程式 hash、真實兩次結果、native-profile 舊包相容、跨 profile 拒絕及 J-A01–J-A11 逐案 scope 在 `artifacts/acceptance/M13/phased-decisions/`。J-A10 UI 尚未覆蓋，其餘完整排列／來源範圍仍按 case-review 記錄，沒有從測試總數自動批准 R07／M13。
- 下一步接 J04 唯讀研究瀏覽，再加入明確凍結／執行操作，並補完整 J05／發布矩陣。UI 應呈現凍結環境與不相容原因，不在 rerun 新增 attempt，也不自動更換 profile 或放寬來源。若要跨 profile 核驗真實資料，另以官方來源／日曆依據及新驗收處理兩筆差異；M14 與真實資料放行仍依各自紀錄。

## 前輪 R07 來源與捕捉紀錄（保留原範圍）

## 最新接續：前向意向契約與發展順序收斂

- 最新認證／守門整合已終局：Python 3.13／3.9 各 22 passed、1 項既有 warning（248.54／278.45 秒）。真實離線 v6 決策可註冊並讀回認證；重算 plan hash 但改設定、過期 experiment history 皆拒絕。此輪 gate 尚未包含後加的 cutoff／tuple refinement。
- 其後修正供應商 archive 超過請求 cutoff 的邊界：回傳 panels 先複製並截斷，來源完整 hash 鏈保留；SessionEvidence 要求不可變 tuple 且 assessment 與來源／readiness 綁定。最新 gate／readiness／reviewed inputs 回歸兩環境各 23 passed（3.79／5.07 秒），Lint／diff check 通過。完整 logs、來源 hashes、分輪範圍與限制在 M14/observation-session-gate/acceptance.json。
- 下一步為不可變逐日 raw-source archive、plan ID 的帳戶 configuration 綁定、取得證據同 SQL transaction 保存及舊來源續跑核驗，再交前向啟用／UI。來源 manifest 的記錄時間不等同第三方可信時間戳；尚無實際前向帳戶或正式策略放行。

- 進一步新增 observation_auth、SessionEvidence／ForwardSessionAssessment 與 observation_gate 初稿：實際重建決策及新行情來源，核對當前實驗 prefix、設定與執行身分、日曆／暖機／coverage、逐 session／標的取得記錄及來源變動。首輪純官方 gate 兩環境各 7 passed（2.35／2.42 秒）；非交易日 fixture 最初越過 cutoff 的測試錯誤已修正。供應商初次 8 passed／1 failed 是錯誤假設完整官方來源必有 context finding，改核對實際選用 provider source ID 與官方 manifest；整合回歸執行中，不將初稿視為正式啟用。
- account-ui 固定來源完整回歸已終局：639 passed、12 warnings（947.67 秒）；保存於 M14/account-ui/full313.log，acceptance 已更新。只覆蓋該輪固定來源，不包含較晚 source_checks／前向模組；下方仍執行的文字保留歷史時點。

- DEVELOPMENT_NEXT 與 ROADMAP 首頁已按實際接線更新：R07 v6 決策包、M14 單日核心／SQL／獨立稽核／歷史 UI 不再當作尚未開工；下一步為固定來源與逐案矩陣、分階段研究 UI、前向註冊／新 session 守門及啟用。較早排程保留供追溯。
- M14 新增 ObservationPlan／register_forward_observation／load_observation_plan，核對真實 v6 決策包、繼續狀態、當前實驗歷史與執行身分，再固定候選設定、決策 manifest、實際時間及未來日期並原子發布。狀態僅 registered_pending_verified_session，不建立帳戶或績效；M14_PAPER 明列 L07a–d 的資料取得時點、日曆／readiness、首日啟用及 UI 後續契約。
- Python 3.13／3.9 新註冊案例各 13 passed、1 項既有 pandas concat warning（150.44／163.99 秒），涵蓋正向真實來源決策、過期歷史拒絕、日期／設定與篡改案例。命令、來源 hash 及限制保存於 M14/observation-registration/acceptance.json；Lint、git diff --check 通過，三份發展文件 31 個相對連結均存在。
- 先前固定 registered/history 來源完整回歸已終局：630 passed、12 warnings（910.06 秒）；原 session 4873 結果保存在 M14/registered-history/full313.log 及 acceptance。只覆蓋原 source inventory，不包含較晚風險／UI／來源綁定及 observation。另一份 account-ui 固定來源完整回歸 session 29945 仍執行。
- 真實凍結研究三期仍 blocked（61／55／56 findings）；55 筆事件 coverage 與兩項權利事件未完成。前向註冊 fixture 的寬鬆門檻不是正式策略政策；正式候選與實際前向觀察未放行，整體目標保持未完成。

## R07 最新接續：開發來源核驗與不可變 selection capture（2026-10-29）

- 新增 DevelopmentInputs、development_registry／report／accounts 與 selection_capture。先認證凍結 raw／snapshot／readiness；完整報告核對 bytes／protocol／attempt，但只解析兩個主動策略的 development 帳務。CSV 與 SQLite 同帳戶設定／業務列交叉核對，重建樣本與績效；validation／探索／scenario 報告業務內容不先解析。
- 開發來源指紋按必要暖機及期間重建 raw 總報酬／open／reference，綁定設定、實際適用 sessions／readiness 及 engine。全資料／報告／attempt 身分另留完整來源鏈結，不混入 selection ID。實際離線來源測試確認未來行情變更會改完整研究身分，但開發選擇 bytes／ID 不變；改暖機則改 selection ID。
- 新 ReadOnlyExperimentRegistry 以 mode=ro／query_only 開啟既存資料庫，拒絕空白／外來／未知 schema／symlink 而不初始化。保留全歷史；最新失敗不借舊成功，有可核驗開發帳戶的驗證情境失敗不改開發選擇；未解 nonreproducible 歷史持續阻擋。收集前後來源／registry／protocol 變動拒絕。
- `export_development_selection()` 將 selection、context、protocol、sources 與 manifest 暫存並讀回重建，重核來源／執行身分後原子發布至 protocol／selections／selection_id／capture UUID。`load_development_selection()` 重播保存前綴；後來補跑不提升舊 incomplete，重算 hash 的語義篡改拒絕。相同業務選擇保留不同捕捉；這是獨立 v5 開發分析，不宣稱舊 batch 是分階段執行。
- 初次正向來源測試因 CSV Timestamp／SQL 字串表示不同失敗（11.95 秒），修正日期正規化後來源 10 項通過（89.17 秒）；再補不可重現／來源變動 2 項（9.21 秒）、reader／驗證篡改 8 項（9.11 秒）、capture／reader 12 項（14.76 秒）通過。保留數值精確比較，未放寬來源守門。
- 接入 reader 前完整 532 passed（514.98 秒）；接入後共用工作區完整 539 passed／3 failed（397.06 秒），3.9 相關 58 passed／1 failed（155.18 秒）。失敗均為 source identity guard 拒絕；直接核對協議 execution，變動欄位為 source_tree_sha256，Git revision／runtime 相同。工作區同時新增／修改其他模組，未弱化守門或偷偷重寫協議。
- 因共用工作區持續變動，改用逐檔驗證的獨立 source snapshot。該快照 Python 3.13 完整 **569 passed**（603.42 秒）、Lint 通過；Python 3.9 相關 **59 passed**（150.27 秒）、Lint 通過。8／4 項既有 pandas concat warnings 保留。沒有宣稱 3.9 完整 569 項，也沒有將結果套用到工作區後續變更。快照複製時 source bytes 相符；no-checkout clone 的 Git index／diff 身分不同，已明列，快照以自己的完整 execution 身分執行。
- 快照、逐檔 hash、兩環境與分輪失敗／成功範圍保存在 `artifacts/acceptance/M13/development-sources/`；220 個已驗證來源檔另存 verified-source-snapshot.tar.gz。此次 22 個來源／測試檔與通過快照逐檔一致；M14 等其他接續工作按自己的 execution／紀錄驗收，不混稱全工作區最新通過。
- 使用該固定快照另凍結子協議 `b5a27420c1a401e8b2f92f886bf8e18cfcc64876e1e7b68f9ad23fd77d8cc52f`。真實兩次均 blocked，數值指紋均為 `058b00628e373d80352ac147c9dcc5cb2722177881c7ba0505f72a8edccf8e00`；開發選擇均 incomplete_search／無候選，selection ID 同為 `715bf0f519b3f2b7b681ead16379578eceb367ddaf6961dfeef2fd5339a16067`，capture 指紋不同。883 個先前研究檔案及 36 個先前決策檔案 bytes 保留，兩份新 capture 讀回重建通過；沒有正式績效排名或解除資料阻擋。
- 下一個交付是新版協議明列分階段規則，第二階段必須引用已保存 capture，再對固定選擇收集 validation／必要對照，不補位；之後完成最終決策包、UI 與完整 J05。J-A02／A03／A07／A08／A11 僅列本次局部來源／保存範圍，R07／M13 不標 accepted。

## 先前規劃快照（下方紀錄保留原範圍）

最新接續規劃（2026-10-29，Asia/Taipei）：已依 R07 純核心交付重新安排 B01 證據索引 → R07 J01–J05 政策／來源核驗／決策報告與 UI → M14 L01–L02，再接原子持久化與獨立稽核。新增 [R07 詳細規格](M13_DECISION_UI.md) 與 11 個接線／報告／UI 案例；M14 補狀態、再平衡起點、尾端訊號及分段交割的六個子單元。下方早期 413／443 項紀錄與診斷初稿只屬歷史範圍，R07 最新既存證據為 3.13 完整 465 項及 3.9 核心 22 項。本輪只更新發展文件，三期真實研究仍 blocked（61／55／58）；發布、正式研究及前向啟用分別驗收。

本輪規劃驗證：16 份架構 Markdown 的 75 個相對連結及 5 個錨點核對通過，`git diff --check` 通過。明確以 p0-clean313 執行一鍵驗證，隔離匯入／版本檢查通過，但 Lint 因正在接線的 `odd_lot_protocol/build.py:133` import 排序（I001）退出；未修改該初稿。另獨立執行 pytest，465 passed（124.76 秒），Lint 重查仍同一問題。驗證期間新增／變動的 `odd_lot_decisions/source_types.py`、`report_evidence.py` 有 before／after inventory，該次測試不能當作這兩份新初稿的專屬驗收。Python 3.9 本輪未重跑，保留既存 22 項範圍；紀錄在 `artifacts/acceptance/PLANNING/2026-10-29-development/`，未宣告全工作區或新接線通過發布閘門。

更新：2026-10-28。整體目標仍為完成 NEXT_ITERATION、M12-5、M13 與 M14；尚未完成。

規劃更新（2026-10-29）：[下一階段執行計畫](DEVELOPMENT_NEXT.md) 已依目前工作區與 acceptance 紀錄重排：R04 診斷 D01–D04 → R05 基準敏感度 → R07 判斷／UI → M14 L01–L02；B01 證據矩陣及 B06 資料來源工作另列。診斷三份初稿尚未整合或專屬驗收，不計為 R04 完成。DELIVERY_BACKLOG 首頁已改列最新三期 61／55／58 findings、暖機各 120，以及 v2 的 15 個不可用組合；較早基線保留供追溯。此次為文件規劃，沒有新增交易邏輯或執行候選搜尋。

本輪規劃驗證：明確使用 `artifacts/environments/p0-clean313/bin/python` 執行 `./scripts/verify.sh -q`，隔離匯入與版本檢查、Lint 通過，413 passed（102.10 秒）。六份規劃文件的相對連結均存在，`git diff --check` 通過。Python 3.9 本輪未重跑；既有 35 項紀錄保留原日期與範圍。完整測試通過不補足診斷初稿尚缺的專屬案例。

最新接續規劃與發布閘門見 [DELIVERY_BACKLOG](DELIVERY_BACKLOG.md)（2026-10-29）；本檔保留各輪實際紀錄，以下較早結果不是最新資料狀態。

## P0 — in_progress

- 修正本機 `.venv/bin/python`／`python3`，與 pyvenv.cfg 宣告的 Python 3.13 一致；原連結記錄保存在 `artifacts/acceptance/P0/runtime-repair/`，保留 python3.9 入口。
- 重裝 editable 專案為 0.12.3；產出的 .pth 含 literal `\\n`，重建後仍觀察到問題，已修復本機 .pth 換行與 RECORD。建置版本本身尚不能證明根因，保留原建置依賴範圍；乾淨安裝重現與根因調查仍待完成。
- verify.sh 使用同一 Python 的 `-m ruff`／`-m pytest`，接受 QFL_PYTHON 明確覆寫；先以 isolated 模式檢查安裝版本，防止 pytest 的 src 路徑掩蓋損壞安裝。
- 新增 CalendarSessions／expected_market_sessions，兩條日曆驗證路徑共用顯式期間及日曆版本；新增邊界、觀測缺列及時區案例。
- 完整回歸結果以實際命令輸出為準；乾淨環境重建、Python 3.9 相容性、官方證據與全部 P0 矩陣仍待驗收，不將本機修復等同整項 accepted。
- 本輪 `./scripts/verify.sh -q`：Lint 通過、315 passed（101.99 秒）。另從 `/private/tmp` 執行 isolated import 仍失敗，即使 .pth bytes 尾端已確認為 LF；工作區內通過不能作 P0-A09 完成證據。接續先調查 repo 外匯入及乾淨重建，再驗收 P0。

## 接續工作

完成 P0 剩餘驗收後，依 NEXT_ITERATION 的 R1–R3、S1／CAL-02／S2、E1 推進；M13 協議在新候選搜尋之前凍結，再進入 M14。DATA-01 的價格取得與正式研究驗收保持分列。

## 後續核對與 R1 型別交付

- 已定位專案外匯入根因：原 `.pth` 的 `st_flags=32832` 含 `UF_HIDDEN=32768`；Python 3.13 的 `site.addpackage` 會略過。只清除該旗標後，從 `/private/tmp` 的 isolated import 通過；先前換行／建置版本猜測不足以解釋失敗，以本次因果驗證為準。
- 新建獨立 `artifacts/environments/p0-clean313`，依 61 個記錄版本安裝，未修改 .pth 即可在 repo 外 isolated import 0.12.3。追蹤版依賴集合為 `requirements/python313-macos-arm64.txt`；完整乾淨環境測試另核對。
- R1 已先交付 `twse_quality/types.py`：穩定問題代碼、語義 ID、暖機證據、期間及研究結果契約；3 個契約測試通過。評估核心、legacy mapping、研究／UI 整合尚未完成，M12-4 不標 accepted。
- 乾淨環境完整驗證：Lint 通過、原 315 個測試通過（116.79 秒）；新增 R1 契約測試另跑 3 個通過。專案外 isolated package／version 檢查及 UI 模組匯入通過；UI server 啟動及完整矩陣仍待驗收。紀錄在 `artifacts/acceptance/P0/clean313/acceptance.json`。

## 本輪核心評估與預設環境重建

- 新增 `twse_quality/readiness.py` 與 `legacy.py`：每次核對來源 hash，依顯式期間及日曆覆蓋判斷，檢查全部股票／基準的逐日價量、估值與暖機；未知規則／缺日曆為 unknown，必要缺項為 blocked。原始 legacy 問題保留，重複項保留 occurrences，缺日與缺月相依可追溯。
- 追加完整、共同缺日但觀測列仍超過 120、基準缺漏、較長暖機、未知問題、來源篡改、事件覆蓋、重複紀錄與非有限估值案例。就緒契約與核心共 11 個測試通過，尚未宣稱 Q01–Q03 全矩陣完成。
- 原 `.venv` 隱藏旗標問題再次出現，已完整移至 `artifacts/environments/p0-original-mixed/` 保留，預設 `.venv` 以 Python 3.13 和固定依賴乾淨重建。重建後專案外 isolated import 通過；不以反覆修旗標替代重建。
- 本機 Streamlit 伺服器成功啟動，`/_stcore/health` 回傳 200／ok，檢查後已停止；證據為 `artifacts/acceptance/P0/canonical313/health.json`。
- 預設環境執行 `./scripts/verify.sh -q`：Lint 通過、326 passed（110.01 秒）；核心與契約另重跑 11 個通過。包含 revision、工作區差異 hash 及環境的紀錄在 `artifacts/acceptance/M12-4/core/acceptance.json`。
- 下一步是官方有效日曆 adapter、剩餘核心矩陣及研究／報告／UI 接入；P0 的 Python 3.9 相容性與凍結資料驗收也仍保留。整體 M12-4／M12-5／M13／M14 尚未完成。

## 本輪 schema 3 與共用判定整合

- 新官方研究預設 schema 3：以凍結原始來源重新準備資料，比對 normalized data、來源清單及全部 quality findings，再凍結 explicit periods、readiness 與 fingerprint；載入時重核，不能用任意 MarketData 搭配別份來源 hash。
- 官方有效日曆 adapter 驗證年度資料與全市場休市佐證，與資料準備共用補假分類；標的停牌不從市場 sessions 刪除，年度證據不足為 unknown。一般市場／歷史例外及 CAL-02 剩餘驗收仍需完成。
- Runner、報告與 UI 接上同一份已驗證判定。受阻期間不算績效，完整問題與依賴保留；顯示理由限 20 筆，其餘可下載清單。報告新增 readiness JSON／CSV 並納入 hash manifest。
- 修正 JSON 讀回後期間字典排序造成的指紋差異；評估按期間起日穩定排序。原始價格存在但權息轉換／估值無效時另列 derived-state 問題，不誤導使用者重新下載行情。
- 正反整合案例均通過：完整官方格式離線 fixture 可跑三策略及敏感度；缺資料 fixture 在績效前受阻；normalized data 不符來源、readiness 檔篡改及錯誤結果指紋皆遭拒。
- 真實舊研究 `bfc2860d15435d56874eb036` 的 schema 2 與既有報告完整性再驗證通過，未改寫舊檔。既有 legacy 測試改為明確構造 v2 fixture，沒有新增關閉新守門的公開開關。
- 完整一鍵驗證 332 passed（101.31 秒）、Lint 通過；derived-state／整合／UI 相關 14 個另重跑通過，顯示理由改動後 frozen 相關 5 個通過。
- 本機官方資料就緒 preflight 三期皆 blocked；開發期 verified warmup 120、驗證期 57、歷史評估期 0。這不是資料接受或策略驗收；DATA-02、事件覆蓋及後續里程碑仍需完成。

## DATA-02：原始價格讀取與選源

- 已新增 `odd_lot_inputs/types.py,finmind.py,validation.py,twse.py,selection.py`，各檔小於 300 行。原始 provider／dataset／URL／取得時間／bytes hash／row locator 保留，no-quote 明確轉成缺少價格，未轉成停牌或零價成交。
- FinMind manifest、33 份 raw 及 normalized CSV 均驗證；CSV 除 hash 外還逐欄對照 raw 及月份聲明。實際重建 8,388 筆（包含重疊／額外月份資料），目標月份仍是原 8,128 筆，唯一 no-quote 保留。
- 官方原始資料 reader 重建 9,445 筆；以明確起訖／cutoff／TWSE 優先政策選出 17,397 筆，重疊價格／量衝突 0。產物為 `artifacts/acceptance/DATA-02/raw-selection/price_selection.csv` 與 summary；不把此結果標為研究通過或官方匯入完成。
- 17 個新測試通過，包含欄位／單位、來源身分、原始 hash、重算 hash 後的 CSV 不符、非法數值／代碼／日期、no-quote 衝突、選源排序、重複鍵與值變動指紋。
- 本輪後段發現 `.venv` 的 pyvenv.cfg 及 Python 入口已不存在，原因尚未查明；未反覆覆寫此目錄，使用仍可隔離匯入的 `artifacts/environments/p0-clean313` 明確指定 QFL_PYTHON 驗證。P0 環境驗收仍未完成。
- 下一步是保留官方問題適用性的 provider prepared input、事件／日曆共用計算及新來源 freeze/readiness/report/UI；官方原始來源缺檔數與新來源完成數繼續分列。
- 2026-10-29（Asia/Taipei）核對本輪驗證：明確使用 p0-clean313 的一鍵腳本，Lint 通過、349 passed（96.88 秒）。DATA-02 原始價格與選源驗收紀錄含實際環境、程式 hash 及選源 CSV hash，位於 `artifacts/acceptance/DATA-02/raw-selection/acceptance.json`；研究截止日仍固定 2026-10-27，沒有隨日期自動延長。

## DATA-02：共用準備與原生研究模式（2026-10-29）

- `PreparedOddLotInput` 與 `overlay.py` 將選定價量交給共用企業行動／停牌／覆蓋／總報酬計算；只切換 quote input，沒有將 FinMind bytes 改標 TWSE。官方全期無價量時也能保留原判定失敗原因並重新檢查 provider 資料。
- 原官方 findings 保留 policy、nonblocking context 與適用說明，新政策重新計算的必要問題仍阻擋。Readiness rule 升為 v2；v1 研究保留可讀及完整性核對，不能默默按新規則重跑。
- 原生 provider_reviewed freeze、load、run、report 及 UI 已接入；來源政策／namespace／選源指紋進 provenance，來源 CSV 進報告 manifest。混合輸入以官方模式凍結會被拒絕。
- 直接後端與完整 Streamlit 流程均有 ready／blocked fixtures，包含實際選用 FinMind 報價的可執行案例、缺一類審核的阻擋、原來源 bytes 不變、no-quote 及來源 CSV 篡改。
- 實際價量範圍為 2020-04-27 至固定截止日 2026-10-27；本政策重算 66 筆原始問題，原官方 1,422 筆判定另保留。三期仍 blocked，暖機 verified 依序 120／120／119；不能以問題數下降宣稱資料 accepted。
- 已另建凍結研究 `94ef4820b48f76d32fef5270`，報告 `8434740cb8334e16bdb189fa8dcd42c3` 完整性通過，績效列數 0、不可用組合 12。此為資料守門驗證，沒有執行候選績效搜尋；舊研究未覆寫。
- p0-clean313 一鍵驗證：Lint 通過、359 passed（92.15 秒）。P0 相容性、CAL-02 三個市場日曆缺口、事件與五類 coverage 審核、剩餘矩陣及 M13／M14 仍待完成。

## CAL-02：官方公告衍生資料版本（2026-10-29）

- 已核對並保存三份證交所原始公告：2024-10-31、2026-07-10、2026-10-23 全市場休市。來源 URL、取得時間及 PDF hash 見 `artifacts/acceptance/CAL-02/evidence/provenance.json`，沒有以供應商缺日推定休市。
- 新增 `twse_amendments.py`，用明確 `ClosureEvidence` 建立不可變衍生 bundle；原 registry／manifest 保存，修訂審核紀錄加入來源 hash inventory。相同修訂可重試，已存在版本被改動則拒絕；宣告休市仍有真實成交的矛盾繼續被偵測。
- 真實新資料包：`artifacts/twse_derived/5bc3befefd9363a8897d1e28`。原始問題 66→63；readiness 的 calendar 3→0、missing_session 36→3，三期暖機均 120。企業行動日期及 no-quote 不自動修正，55 筆分項 coverage 問題仍在。
- 三期阻擋 findings 依序 62／56／59，全部仍 blocked。新研究 `4674007563cdd7faf7693ae6`，報告 `b6bf164d50934c0091b81143deed21df` 的完整性驗證通過，績效 CSV 為空、不可用組合 12。新 readiness 指紋 `10c09c504af26dda29487ebdfc08be83a60552d8ccecb560ade7010808791b38`；舊研究未覆寫。
- 以已保存且 hash 驗證的 FinMind TaiwanStockTradingDate 重算 2023-10-01 至 2026-10-27：4.13.2 基礎日曆 746 日、provider 743 日，基礎日曆僅多上述三日；套用官方證據後為 743 日，差集為空。原 20 個差異日逐一記錄於 `calendar_difference_review.csv`；供應商相符只是診斷，不等於獨立證明全部開市日。
- 本輪完整驗證：p0-clean313 一鍵腳本 Lint 通過、361 passed（98.91 秒）。其後新增修訂審核紀錄被篡改的來源 inventory 回歸，該檔 3 passed（1.17 秒），Lint 再通過；不將後加案例算入先前完整測試數。
- 最終盤點原始資料包 542 個檔案 hash 與修訂前 inventory 全相符，兩份既有研究報告與新報告共 3 份再驗證通過；紀錄見 `artifacts/acceptance/CAL-02/derived-closures/acceptance.json`。資料／報告保留與研究 ready 是獨立驗收項目。
- CAL-02 尚未 accepted：帶證據的有效日曆與一般 market calendar／官方準備／readiness 三入口契約仍待收斂。P0 相容性、事件及 coverage、驗收矩陣對照與 M13／M14 保持未完成。

## CAL-02：三入口有效日曆契約（2026-10-29）

- 新增不可變 `CalendarClosures`，明列市場、證據 revision、覆蓋期間及休市日期。一般 expected／daily／point-in-time 查詢接受明確證據，市場或覆蓋不符時拒絕；未傳證據維持原套件日曆語義，不從缺價推定休市。
- `official_closure_evidence()` 共同驗證來源 bytes／年度範圍／全市場佐證，官方資料準備、`official_calendar()` 與 readiness 均經同一 expected-session 入口；個股停牌保留為市場交易日。缺年度證據仍保留 preparation 問題及 readiness unknown。
- 7 個新案例涵蓋補假＋臨時休市＋個股停牌的相同 session 集合、真正整日缺價仍受阻、證據市場／期間／hash 不符及非正規日期。完整一鍵驗證 Lint 通過、369 passed（97.71 秒）。
- 真實 2020-04-27 至 2026-10-27 的查詢均為 1,582 日；兩次 preparation 查詢與一般／official effective calendar 完全相同，daily／point-in-time 檢查有效。readiness 指紋仍為 `10c09c504af26dda29487ebdfc08be83a60552d8ccecb560ade7010808791b38`。
- 既有混合研究 `94ef4820b48f76d32fef5270`（578 檔）與衍生研究 `4674007563cdd7faf7693ae6`（584 檔）重新載入及執行守門均通過，全部檔案 hash 不變，績效仍為空。此為介面收斂，不變更 `twse-closures-v1` 或 readiness-v2 的既有判定語義。
- S-A08 具體證據在 `artifacts/acceptance/CAL-02/shared-contract/real_consistency.json`。B04 工程單元完成；CAL-02／DATA-02 的整體矩陣、P0 Python 3.9 相容性及實際事件／coverage 驗收尚未結案。

## P0：獨立 Python 3.9 相容驗證（2026-10-29）

- 使用 `/usr/bin/python3`（3.9.6）新建 `artifacts/environments/p0-clean39`，與 3.13 完全獨立。原生 pip 21.2.4 不支援本專案 editable pyproject 安裝，僅升級新環境內 pip 至 25.3 後安裝成功；沒有複用舊 site-packages 或改最低 Python 宣告。
- 乾淨 resolver 選到 exchange-calendars 4.5.6；修正前完整測試 368 passed／1 failed（138.26 秒），同原 NYSE 2025-01-09 缺日案例。3.9 的 repo 外 `-I` 套件／版本檢查、UI 模組匯入均成功。
- 依已閱讀的 ICE／NYSE 官方公告，新增 typed `OfficialClosureCorrection`，在共用 session 供應層排除該休市日，僅在套件仍錯列為交易日時加入具名修訂 digest；新版 4.13.2 已正確排除，日期與原 revision 維持不變。公告日期與生效日分列，不當作訊號預知未來休市。
- 官方網頁經 web 工具可閱讀，直接 urllib 存原始 HTML 回傳 HTTP 403；`artifacts/acceptance/P0/nyse-evidence/review.json` 明列此限制，沒有宣稱已保存公告原始 bytes。來源仍是官方公告，不用第三方文章替代。
- 新增 3 個回歸：舊／新 provider 一般及 point-in-time 一致、已修正不重複覆蓋、scope／重試正確；真缺日 01-08 與休市日異常 bar 繼續辨識。
- 修正後完整一鍵驗證兩套環境均通過：Python 3.9.6 為 372 passed（129.93 秒），Python 3.13.13 為 372 passed（103.16 秒）；兩套 Lint 皆通過。新增 62 個已安裝依賴版本紀錄 `requirements/python39-macos-arm64.txt` 與重建說明。
- P0-A06 的空值／未知市場／逆序／時區實際檢查兩環境都通過；3.9 另載入真實 schema 2 舊研究 `bfc2860d15435d56874eb036`（859 列）並驗證既有報告成功。案例對照與環境／code hash 記錄於 `artifacts/acceptance/P0/compatibility39/acceptance.json`。
- Python 3.9 相容工程已通過；P0 整體發布驗收仍需最後證據審查與預設環境異常的處置紀錄。明確 QFL_PYTHON 的獨立環境為目前可驗證入口，不再次覆寫已失效的 `.venv`。整體 M12-5／M13／M14 尚未完成。

## M12-5：逐案休市日現金股利修訂（2026-10-29）

- 核對證交所災害問答第 5 題及原官方股利索引；另取得 2023-08-02 的全市場休市公告。原訂休市當日參考價延用至下一 session，但其他事件不一律順延。未從價格變動反推事件，也未宣稱已取得發行人歷史更正公告。
- `CashDividendDateReview` 先定原訂／有效日、金額、規則／索引 URL 與 SHA-256，再由小型 helper 驗證閉市佐證、下一 session、純現金股利與原金額。認股權／免費配股／無佐證日期／衝突／不安全路徑均拒絕；舊資料無 registry 時行為不變。
- 新衍生資料包 `44e3c80317da54e4b54f7fcd` 保留原始 actions／索引 bytes，只新增明確審核表及修訂稽核來源。1216／2023-08-03 映射至 08-04，2891／2026-07-10 映射至 07-13；有效日前報酬逐一比較不變。股利仍按有效除息日模擬入帳，並非實際付款日。
- 新研究 `d307f4636baad1a1c970953e`、報告 `9870d6914c1f460a8c0cbc58471a9c06` 驗證通過；報告新增可核對的 `action_date_reviews.csv` 並進 hash manifest。績效列數 0、不可用組合 12，沒有候選搜尋。
- 原始品質問題 63→61，三期暖機皆 120、阻擋 findings 61／55／58，仍全部 blocked。55 筆 coverage、兩個權利事件與 2317／2025-07-30 no-quote 維持必要阻擋；三筆 missing_session findings 均指向該同一缺價日期的不同檢查。
- 發行人頁已確認 2882／2022-12-05 為現金認購權，並列認購率、價格與繳款窗；交付／可交易日、資金不足、估值及資訊時間仍待補。2881 同日權利結構與現有股利頁日期差異尚待原公告核對。逐案範圍見 [EVENT_INVESTIGATION](EVENT_INVESTIGATION.md)，國泰金原 HTML 下載逾時限制有明列。
- 完整一鍵驗證 Lint 通過、383 passed（94.40 秒）；獨立 Python 3.9 的新事件日期測試 11 passed（3.16 秒）。真實資料／報告完整性與父資料版本保留證據見 `artifacts/acceptance/M12-5/reviewed-event-dates/acceptance.json`。M12-5／M13／M14 尚未完成。

## M13：凍結協議與持久化實驗登記（2026-10-29）

- 新增 `odd_lot_protocol/`，各檔小於 300 行。先定不可變 `StudyProtocol`／candidate／period／execution／attempt 型別；完整設定用 canonical finite JSON，綁定來源、資料、日曆、暖機、期間用途、有限 batch 候選、固定策略／敏感度情境及種子。原資料接觸未知或已接觸的 2025 年後期間不能改標未見樣本。
- `capture_execution_identity()` 同時涵蓋 tracked code diff、untracked source/test bytes、Git revision 與實際 runtime／依賴；報告輸出及 Markdown 進度不影響執行身分。wrapper 核對實際 executing package 的目錄，執行前後重核程式／環境，不借用另一個 checkout 的身分。
- `freeze_protocol()` 原子發布、重試重核原 bytes，父子協議保留；實際記錄時間與使用者宣告時間分列，不能以回填宣告把歷史資料變成前向預註冊。
- 獨立 SQLite registry 拒絕誤用一般帳本；協議／實驗定義與已完成 attempts 不可覆寫／刪除。失敗／受阻紀錄及重試編號保留；並行啟動只能有一個 running attempt，中斷需明確標記失敗後再試。相同實驗完成結果不一致時，保留觀察到的指紋並記為 nonreproducible failure。
- `run_registered_study()` 接既有來源／readiness 守門，報告新增 protocol／experiment 與資料用途，進 manifest。數值業務指紋保留精確 float／缺值種類，排除 UUID、輸出路徑及 attempt 時間。report verifier 額外核對協議與候選／資料／實驗語義綁定，重算 sidecar hash 仍不能讓不相符實驗通過；最初 local v1 context 保持可讀。
- 真實研究 `d307f4636baad1a1c970953e` 在父協議 `320787cd51de3ef2e4fe6ceaa67a4eb6b79e19a5d55691be997fa28634c95868` 下兩次 blocked，數值指紋同為 `d632ebeb94e3fd2cb21be0974b8f3914efc983c341a9834694fe0c3ada6e752e`。新增報告綁定驗證後，另建子協議 `86f4c9e8046849f20dce3d1bc334025c3f4d59d62d084d3dca64bd328b71eb69`，實驗 ID 改變而兩次受阻數值指紋不變；先前 631 個研究／報告檔案 hash 保留，績效列數仍為 0。
- 完整驗證 Lint 通過、402 passed（104.66 秒）；獨立 Python 3.9 的 19 個新協議／registry／整合案例通過（8.25 秒）。包含 ready 正常重跑、blocked 不計算績效、失敗後重試、程式身分不符、併發、改參／資料／種子新身分、terminal immutable、數值不重現與報告篡改。
- 證據在 `artifacts/acceptance/M13/protocol-registry/` 及 `artifacts/acceptance/M13/report-binding/`。目前 candidate 是完整 batch 設定，三策略與各敏感度試驗全部明列；後續統計不能以 batch 數代替試驗總數。自動選參／判斷、同成本可交易基準、風險診斷、UI、正式資料／M13 驗收及 M14 均未完成。

## M13：可交易 ETF 基準與 v2 分析協議（2026-10-29）

- 先新增不可變 `BenchmarkSpec`，明列 ETF、初始資金、稅率／限價情境、期初一次委託、未成交到期、股利保留現金與既有 T+2 代理。稅率／限價有明確研究假設說明，沒有冒充全歷史規則認證。
- `run_tradable_benchmark()` 以單一 ETF 視圖共用零股撮合、費用、現金、企業行動及交割主迴圈；研究 study 的至少兩檔交易股票＋獨立基準要求保持。被動基準沒有止損／風險選股，新增受限的內部被動進場路徑，避免無關的波動視窗不足使基準不下單；舊預設研究路徑仍照原規則。
- 手算驗證：100,000／200 元、零成本滿額買 500 股、210 元收盤 NAV 105,000；50% 成交只買 250 股，不補單；費用／滑價各只計一次，低價單次委託最多 999 股。同日股利先按舊股數入帳再拆股；反向拆股碎股權利保持應收並只結算一次。新案例也核對未結算買款及相同評估 sessions。
- 新 `frozen_odd_lot_batch_v2` 在協議中凍結 BenchmarkSpec；每期共用 readiness 守門與暖機，並將基準 orders／fills／settlements／actions／episodes／equity 存入同一報告與研究帳戶 archive。無成本參考和成本口徑分列，報告增加投資／現金比例及 `benchmark_specs.json`；重算 hash 仍不能讓規格與協議不符。
- v1 協議／報告保持原分析內容與數值指紋語義，不自動加入新基準。真實資料另建 v2 子協議 `e63eedc20897902a2febefd4f1f385ae01c7b91574190ac21b086292abdacd92`、實驗 `52a8c1fb9db9e6e13e7297adb1601e90c5f85df38fc0a59cdb25faa9e7f4b73d`，兩次結果皆 blocked、指紋同為 `ddfa6c61844c0894765dfc1831fa6327e45130b84c2f639a5d239a35e0b2130f`。新增基準後不可用組合 15（含三期新基準），不是新增缺價日期；績效列數仍為 0。
- 原 669 個研究／既有報告檔案 hash 保留，前一 v1 報告仍驗證通過。證據在 `artifacts/acceptance/M13/tradable-benchmark/`。
- 完整一鍵驗證 Lint 通過、413 passed（108.96 秒）；獨立 Python 3.9 的基準／協議／共享研究及撮合回歸 35 passed（11.53 秒）。R03 工程已交付；風險診斷、基準逐成本敏感度、自動選參／決策、UI、資料驗收與 M14 保持未完成。

## M13：R04 風險診斷與 v3 報告（2026-10-29）

- `odd_lot_diagnostics/` 由型別初稿補成純讀取帳戶診斷：資金／交割比例、未成交原因、建倉風險預算超額、首次 stop 至股份出清的延遲及嘗試次數。新 fill 保存建倉時預算；舊 fill 缺證據列 unavailable，不以目前設定補造。未平倉與權利待收款保持 pending，被動等權／ETF 無止損預算。
- 實際引擎手算：100 元買進 400 股、預算 2,000；跳空限價失敗後 60 元退出，淨虧損 16,000、超額 14,000、比率 8、兩次嘗試及兩個 sessions 延遲。另驗證部分退出、尚未退出、拆股整數股歸零但碎股款待收、缺預算、錯誤數量／日期及無效 NAV。
- v3 analysis plan 明確凍結 `risk_diagnostics=True` 及規則版本；新增 JSON、每帳戶三份診斷 CSV、HTML 說明及數值指紋。報告從保存的 equity／fills／orders／signals／episodes／actions／terminal sources 重建診斷，比對帳戶清單、JSON 與 CSV；只改診斷再重算 hash 仍拒絕。v1／v2 舊報告保持可讀。
- 新子協議 `24a1f3a9a0e2b7ceb9d043804ac033ff4b44a545ff29227685184e4e3bff7a86`、實驗 `4f1607c010be6bbd278a93a73500dc923304931a226df6d67c56aff58328b2f9` 兩次均 blocked；結果指紋同為 `5545c64490511a9cd14f48a96235abfba89aa229abc7842677ba90993158a902`。績效列數／診斷帳戶均 0，不可用組合 15；709 個先前研究檔案 hash 不變，七份舊報告驗證仍通過。沒有正式候選績效搜尋。
- Python 3.13 完整驗證 Lint 通過、431 passed（115.31 秒）。Python 3.9 相關 45 項通過；首輪完整測試 430 passed／1 個既有 Streamlit blocked 案例逾時（146.87 秒），單獨 UI 重跑 2 passed（5.28 秒），再單獨完整驗證 Lint 通過、431 passed（130.54 秒）。未修改逾時門檻或刪除案例；同時執行其他驗證可能相關，但原因未證明，原失敗保留。
- D01–D04 工程驗證與 R-A07 局部／R-A08／R-A12 診斷範圍對照見 `artifacts/acceptance/M13/risk-diagnostics/acceptance.json`，含程式／證據 hash 與原始失敗。R04 工程已交付，M13 整體仍 `in_progress`；接續 R05 基準敏感度、R07 判斷與 UI、完整矩陣及真實事件／coverage 驗收，再進 M14。

## M13：R05 固定策略／ETF 敏感度與 v4 報告（2026-10-29）

- `odd_lot_sensitivity/` 先定不可變 scenario／outcome 契約，按既有有限情境矩陣評估 ensemble、momentum 與可交易 ETF。相同初始資金、暖機及 sessions，只變最低費、滑價與成交比例；ETF 稅率／限價等 `BenchmarkSpec` 假設保留。V4 明確啟用 matched sensitivity，略過 legacy 彙總分支，避免重複計算相同情境；v1–v3 宣告及既有報告可讀性保留。
- 每個成功情境保存設定與八類帳務 CSV，含未成交、交割、現金／投資比例、成本、淨績效與樣本摘要；null 指標有 undefined_metrics 清單。失敗／受阻情境保留原因與空指標；單一例外後仍完成其餘矩陣，完整報告保存後 attempt 記 failed，後續成功重試不改寫前報告。Validation 敏感度不作自動選參。
- 手算 100,000／200 元、滿額／半額成交 500／250 股，210 元時 NAV 105,000／102,500；再加最低費 20 及滑價後為 102,455，沒有重扣成本或補單。另核對截斷未來的既有訊號／委託／成交一致、全矩陣重現、受阻不進撮合、失敗重試與重算 hash 後的刪情境／設定／摘要篡改拒絕。
- 兩個環境完整一鍵驗證均 Lint 通過：Python 3.13 為 443 passed（110.87 秒），Python 3.9 為 443 passed（141.15 秒）；後者單獨執行，沒有放寬 UI 逾時或略過案例。
- 真實 v4 子協議 `ee4b2325274b6abd39f2b7392fb5a124c032328becf765dba17cf559605e10a9`、實驗 `2125d16d2a9d6f4b59a99c4a4e022ca46064a5a8c782fd4cc0cf5f7cd7762e59` 兩次均 blocked；結果指紋同為 `058b00628e373d80352ac147c9dcc5cb2722177881c7ba0505f72a8edccf8e00`。18 個情境結果均明列 blocked，執行情境帳戶／績效列／診斷帳戶均 0；原 15 個不可用組合保留，沒有新增缺價日。751 個先前研究檔案 hash 與九份舊報告驗證保持。
- 驗收及 R-A03／R-A06／R-A11／R-A12 的敏感度範圍證據在 `artifacts/acceptance/M13/matched-sensitivity/`。R05 工程已交付；R07 可執行決策與 UI、全矩陣結案、真實資料及 M14 尚未完成，不將整體 M13 標 accepted。

## M13：R07 型別與純計算決策核心（2026-10-29）

- `odd_lot_decisions/` 先定顯式政策、有限候選／情境預算、期間證據、逐項 DecisionCheck 與決策輸出；各檔少於 250 行。門檻由呼叫方明列，不從既有結果推導，最少完成 episode 保持 30。缺值使用 null 與理由，禁止 NaN／Inf、假造 blocked 的數值或外來候選／情境。
- 開發期單獨排名；缺宣告候選的開發證據時回傳 incomplete_search，不先比較已到齊的一部分。已知樣本不足按事前規則列不合格。分數同值按 candidate ID、strategy 固定排序；無 drawdown 的 Calmar、零波動 Sharpe 不造零分。
- 開發選擇只做一次，驗證失敗不替換為次佳候選；逐項保存 validation／同成本 ETF／全部敏感度／啟用風險門檻結果。已知拒絕與資料未知一起揭露；未退出的 stop 保留觀測不足，缺預算／退出來源為 unavailable。ETF 不要求 30 次平倉，但仍需可用同成本報酬證據。
- 新核心 22 個測試通過；Python 3.9 針對性 22 passed（0.07 秒）。最新 Python 3.13 完整一鍵驗證 Lint 通過、465 passed（129.56 秒）。R05 的雙環境 443 項紀錄保留原範圍，不當成本輪 3.9 全部 465 項驗證。
- 證據在 `artifacts/acceptance/M13/decision-core/acceptance.json`。目前是純計算核心，輸入 protocol ID／source fingerprint 僅驗證格式，沒有真實來源認證或新協議凍結，未啟動正式候選選擇。接續先交新協議政策／期間用途綁定及 registry／報告證據 adapter，再交決策報告與 UI；R07／M13／M14 均尚未完成。

## M13：v5 政策、registry 來源與決策包接線（2026-10-29）

- v5 明列完整 DecisionPolicy、排名／驗證期間、策略與來源規則；拒絕缺門檻、不同 SelectionRule 目標／樣本數或錯用期間。V1–v4 不新增可執行選擇；舊研究及決策保留原檔。
- 新 adapter 讀完整最新 attempt 前綴，逐份核對報告／protocol／candidate／attempt／數值 fingerprint 與 manifest。主要帳戶核對 SQLite 設定及 study／dataset，從保存 NAV／episodes／診斷重建數值，拒絕與來源矛盾的 comparison。未完成、無報告或不可重現的最新紀錄不退回舊成功；同成本情境必要對照失敗也不能宣稱 continue。
- 決策包原子寫入新捕捉目錄，含政策、全部來源／候選、門檻 CSV／HTML 與 hash manifest；讀回重建語義，修改結果再重算 hash 仍拒絕。歷史前綴可在後來新增 attempt 或 running 完成後驗證，不能解讀為仍代表最新狀態或外部簽章。
- 初次整合 5 passed／2 failed（55.84 秒），因共用工作區加入其他檔案時觸發既有身分守門；未放寬守門。來源穩定後，登記決策／政策／索引 21 項通過（285.16 秒），第一輪完整 486 passed（381.41 秒）；覆核後新增必要 ETF 對照失敗案例，該案例通過（38.35 秒）。最終完整一鍵驗證兩環境均 Lint 通過：3.13 為 487 passed（407.51 秒），3.9 為 487 passed（470.32 秒）。各有四項既有 pandas concat FutureWarning，未 skip 或放寬逾時。
- 真實資料先凍結 v5 `d1529bde199450ff9e9a9a888b9aec04aa689c0c985db6212096611aacc57d6c`，補強後另建子協議 `8dc054b5ad73449a13c063feab5dcd347d856ed868f493dc1cee7a003f0b5f8a`。政策是明列的回溯研究假設，驗證／敏感度回撤上限沿既有設定 0.2、最少完成交易 30，沒有把寬鬆測試門檻拿來採用策略。
- 最終子協議的兩次實驗皆 blocked，數值指紋同為 `058b00628e373d80352ac147c9dcc5cb2722177881c7ba0505f72a8edccf8e00`；決策同為 incomplete_search、沒有選定候選，decision ID 同為 `0f48a7262799670ede41f3fa57e5b1aa73094ed137850ef01f742c47849fc6b7`。839 個先前研究檔案、13 份舊研究報告與兩份較早決策均保留且可核對。
- 證據與分輪失敗／重跑在 `artifacts/acceptance/M13/decision-binding/`。**尚未完成僅開發來源的 DevelopmentSelection／獨立 selection fingerprint，也尚未做到先保存該產物再讀 validation**；目前全 evidence ID 不能冒充開發選擇 ID。依 [R07 詳規](M13_DECISION_UI.md) 接續此分階段流程、canonical 產物、UI 與完整 J02–J05 矩陣。R07／M13 不標 accepted，M14 與真實資料驗收仍待完成。

## B01：驗收索引與 readiness 案例審查（2026-10-29）

- 已使用 `scripts/build_acceptance_index.py` 產出 `artifacts/acceptance/B01/case_index.json`，收錄 80 個規劃案例、既有證據 claims 與 test-node 存在性；所有案例仍需逐案審查，沒有由總測試數推定 accepted。
- 另逐行核對 Q-A01–A12 的測試／規格，記錄 1 案完整離線案例通過、8 案局部證據及 3 案尚缺完整對照（Q-A03／Q-A07／Q-A11）；partial 與 not_covered 保留原範圍。記錄在 B01/acceptance.json，不代表 M12-4 發布驗收已完成。
- 等待回歸期間補存兩份發行人官方 HTML：國泰金股東會執行情形確認 2022-12-30 是股款繳納憑證上市日；富邦董事會回溯頁確認 2021-04-29 普通股及丙種特別股現增案。普通股交付／換發、最終權利腿及資訊時點仍未知，沒有改動事件輸入或 readiness。原始 bytes／hash 與取得限制在 `artifacts/acceptance/M12-5/issuer-rights-followup/`，見 EVENT_INVESTIGATION。

## 全面執行接續：B01 索引與 R07 政策綁定防護（2026-10-29）

- 建立 `artifacts/acceptance/release/case_index.json`，涵蓋 80 個案例；17 項找到既存證據、63 項缺明確對應。16 個測試引用的檔案與函式均存在，尚不據此提升案例為 accepted。
- 新增政策綁定測試，並修正 v5 政策讀取未檢查排名期間、驗證期間、策略集合及來源規則的缺口；拒絕以驗證期排名或挑選最佳重試。舊協議拒絕注入政策、門檻變更身分及期間／摘要不符均有回歸。
- Python 3.13／3.9 相關測試各 41 passed；最終 Python 3.13 一鍵驗證 Lint 通過、475 passed（125.66 秒），`git diff --check` 通過。證據在 `artifacts/acceptance/M13/decision-policy-binding/`。
- 本輪完成具體工程與證據索引，完整目標仍 active；R07 來源 adapter／決策報告／UI、B01 全矩陣、M14 及真實資料審核仍需接續，未宣告整體完成。

## 接續發展規劃：R07 兩階段與交接順序（2026-10-29）

- 本次依使用者「繼續規劃專案發展」核對現有 workflow／collector 與規劃，不變更執行程式、策略門檻、registry 或研究資料。最新既有完整工程紀錄採雙環境各 487 passed；上方 475／465 等紀錄保留各自歷史範圍。
- 新增 `R07_SELECTION_STAGES.md`，細分 J02a–b／J03a–b：開發依賴與完整稽核指紋分離、全候選開發重建、原子保存 selection 後才解析 validation、固定選擇不補位、截止位置競態、舊 schema 1 相容及不可變 capture。這些仍為 planned，沒有宣稱 J-A02 已通過。
- 更新 DEVELOPMENT_NEXT 最新排程、DELIVERY_BACKLOG 基線及文件入口；J03 調整為已有部分實作的 in_progress。順序是分階段選擇 → 唯讀 UI → 顯式操作及 J05 → M14 狀態／單日核心；B01 先補 Q-A03／A07／A11，B06 按期審核。
- 本次 Python 3.13 Lint 通過，`tests/test_acceptance_index.py` 為 4 passed（0.23 秒），`git diff --check` 通過；索引腳本重建 80 案至 `/tmp/quant-fund-lab-planning-case-index-20261029.json`，未覆寫既有 acceptance 索引。這是文件／索引相關驗證，未重跑完整 487 項或啟動新研究。
- 版本仍 0.12.3；真實三期 blocked、工程完整案例及正式研究驗收狀態不因本次規劃調整而提升。

## M13：開發專用 selection 型別與純核心（2026-10-29）

- 新增 `development_types.py`／`development.py`，先定 DevelopmentPolicy／Evidence／Rank，再交 DevelopmentSelection；分別 103／92 行，測試檔 167 行。開發政策只包含日期、目標、最少完成 episode 與固定平手規則；驗證／敏感度／風險門檻及完整 protocol／報告／attempt 身分不混入 selection ID。
- 輸出完整宣告候選 × ensemble／momentum 的資格、原因、分數與排名；缺證據不選部分最優，已知少樣本與未知分開。schema 1／development_selection_v1 讀回重算全部衍生結果，修改選擇、排名、狀態、版本或額外欄位再重算 hash 仍拒絕。純核心 fingerprint 不能單獨認證來源。
- 新增 33 案例：序列化／平手／順序、開發依賴變動、驗證政策排除、29／30／零成交、無分母、非法數值與舊核心三種目標對照。初次 Lint 因 __all__ 未排序失敗，修正後 Lint 通過；3.13 相關 55 passed（0.07 秒），3.9 相關 65 passed（1.12 秒）。
- Python 3.13 明確 interpreter 的完整一鍵驗證 Lint 通過、520 passed（399.06 秒）；4 項既有 pandas concat FutureWarning，未 skip 或放寬逾時。此次 Python 3.9 只做 65 項相關驗證，未宣稱完整 520 項通過。
- 另外讀回核驗 v5 `8dc054...` 的兩份真實 schema 1 決策包：均仍 incomplete_search／無選擇，全部檔案 bytes 保持；僅有 Arrow 在受限環境探測 CPU cache 的 stderr，核驗退出碼 0。沒有執行新候選或回寫舊包。
- 驗收與程式／環境／舊包 hash 在 `artifacts/acceptance/M13/development-selection-core/`；B01 新索引快照為 `artifacts/acceptance/B01/development-selection-core/case_index.json`，80 案不自動 accepted。J-A02／A03／A05／A07／A09 僅列本次局部範圍。
- 下一步 J02b：重建並認證實際開發依賴切片，避免全結果 fingerprint 混入 selection；其後才接 SelectionCapture／新協議規則、先保存再解析 validation、固定選擇的報告與 UI。現有 collector 仍一次收集兩期，J02／J03／R07／M13 尚未完成，M14 及正式資料驗收仍待交付。

## B01／M12-5：修復流程驗證與 2317 個股停牌（2026-10-29）

- 新增可重跑索引工具、4 個索引防護測試與操作文件；相關獨立 Python 3.9 測試通過。原 486 項完整紀錄保存於 B01/index-tool，後續來源變動另驗收。
- 補 Q-A03／A07／A11 的實際缺月匯出→補檔→重查、重複／衝突匯入及跨期暖機案例。補價格後 coverage 仍 blocked；跨期少一天不造完整暖機。
- 保存並逐頁擷取／渲染核對 TWSE 2025-07-29 鴻海停牌公告與 2025-07-30 復牌公告；確認 2317 自 07-30 停牌、07-31 復牌。初次 sandbox DNS 失敗與獲准下載後 PDF bytes／hash 均保留。
- 新增 SymbolSuspensionEvidence，沿用不可變衍生及來源 inventory，個股停牌不刪市場 session；真有成交的衝突仍阻擋，重試與父資料保留已驗證。新衍生包 23ca14c7733df93d5a47fc45，原問題 61→60，三期 findings 61／55／56，全部仍 blocked。
- Python 3.13／3.9 相關 10 項均通過、Lint 通過。最新完整回歸在 session 1082、log `/private/tmp/qfl-suspension-full313.log` 執行，尚不可宣告通過；新研究 freeze／report 及整體資料驗收待接續。證據在 `artifacts/acceptance/M12-5/2317-suspension/`。

### 2317 接續凍結與報告

新研究 `23bb603a256b04cb87f472b3`／報告 `58dda4f432a744819694c367216052cd` 已完成來源重建、執行守門及完整性驗證，績效 0 列、不可用組合 12；新 readiness 指紋 `ec50c42df6329ebb85699c39f14a21bb68228a2dad9672ab9d898baa4e4e880d`。相關 10 項再跑通過（2.52 秒），完整回歸 session 1082 仍活躍，未重啟或宣告通過。M13 新資料子協議、R07 分階段接線／UI、M14、coverage／權利模型及發布矩陣仍待完成。

## M14：L01a 不可變狀態與序列化（2026-10-29）

- 新增 `odd_lot_paper/types.py`／`serialization.py` 與鄰近 README；先交 session、origin／offset、cash／shares、stop、pending、terminated、碎股應收及買賣交割型別。負賣款保留費用差額，未知未來交割日期以 remaining_sessions 保存。
- Canonical JSON 保留有限數值與狀態，拒絕重複 JSON 鍵、未知欄位、非有限值、可變位置資料、未來已結算歷史及不一致交割狀態。沒有為原引擎缺少的成本基礎補造欄位；episode 待累積事件重建。
- 3.13 狀態／既有引擎／停牌回歸 27 passed（2.47 秒），3.9 狀態 15 passed（0.04 秒）；Lint 與 diff check 通過。證據在 `artifacts/acceptance/M14/session-state/`。
- L01a 尚待歷史狀態 adapter 驗證，L01b–L06 仍未完成，沒有 SQL 帳戶或 durable resume。既有完整回歸 session 1082 仍執行，log 出現失敗案例但尚無終局摘要；不以此次局部通過掩蓋完整驗證失敗。

### 完整回歸失敗與固定來源重跑

Session 1082 終局為 541 passed／2 failed（293.91 秒），原始 log 保存於 `M12-5/2317-suspension/full313-first.log`。兩案均因測試期間工作區程式身分改變而拒絕完成，沒有放寬既有 identity guard。已停止程式／測試檔修改，以 session 69316 單獨重跑兩個 registered decision 案例；Lint 通過，測試仍活躍，log `/private/tmp/qfl-source-stable-retry.log`。結果及後續穩定工作區完整回歸仍待接續。

## M14 歷史狀態 bridge 與隔離來源驗證

- 新增 `bridge.py`，捕捉／還原 PortfolioState、stop、pending、terminated、碎股應收及交割；未結算 due index 轉為剩餘 sessions，還原時可重設窗口索引，已結算日期保持。新物件不 alias 原狀態；過期未結算義務拒絕。
- Python 3.13 狀態／bridge／既有研究回歸 31 passed（2.27 秒），3.9 狀態與 bridge 20 passed（0.76 秒），Lint 通過。尚未接歷史日迴圈，不能宣告 L02 或持久化完成。
- 共用來源的兩案重跑 1 passed／1 failed（185.04 秒），仍是執行身分不符，未修改 guard。已建立 `/private/tmp/qfl-stable-source-20261029` 的實際程式／測試隔離副本與 SHA-256 inventory，session 78887 重跑兩案；目前程序活躍。隔離副本不隨後續工作區實作變更，避免再將移動中的來源當作固定基線。

## M14：首個單日核心接縫—開盤後交割與收盤估值

- 先保存三策略抽取前完整輸出，再新增 AccountCloseInput／Result 與純 close step；歷史迴圈已接入，無改變開盤後 T+2、應付保留或 NAV 語義。原有 T+2 說明註解保留。
- 90 sessions／seed 7／warmup 30 的 ensemble、momentum、equal_weight 所有 DataFrame 及其餘結果欄位精確相同，baseline 保存於 `artifacts/acceptance/M14/closing-core/pre_extraction.pkl`。獨立手算驗證賣款只入一次、買款與負賣款費用差額不重扣、估值失敗不部分改動輸入。
- Python 3.13 相關 29 passed（2.38 秒）、3.9 29 passed（3.06 秒），Lint 通過。第一次命令指定不存在的 settlement 測試檔退出 4，修正檔案清單後通過，未改守門。
- 本次固定來源 full suite 在 `/private/tmp/qfl-close-source-20261029`、session 18447 執行，log `/private/tmp/qfl-close-full313.log`；舊兩案隔離重跑 session 78887 尚活躍。兩份來源 inventory 分別保存，不因後續工作區變動重啟。單日核心其他階段、持久化與整體驗收尚未完成。

## M14：權息價格轉換核心

- 新增 EventPriceInput／Result 及純 adjust_event_prices；將止損／最高收盤與撮合參考價的股利先扣、拆股再除接回歷史迴圈。未知事件不補造參考價，拆股取消未成交買單；實際事件帳務及完整單日 transition 仍待抽取。
- 手算含同日每股股利 4、2:1 拆股：前收 100→48，止損 90→43，high 110→53；另測反向拆股、零值、無事件與未知值。三策略所有輸出欄位再與抽取前 baseline 精確比對通過。
- 3.13／3.9 相關回歸各 40 passed（2.73／3.56 秒）；初次 Lint 發現漏 future annotations，已修正後通過。證據在 `artifacts/acceptance/M14/event-prices/`。
- 固定來源的舊失敗兩案 session 78887 及 closing 全套 session 18447 仍活躍；後者只驗證其原始來源快照，不涵蓋本次新增價格步驟，最終仍需穩定工作區全套回歸。

## M14：股利／拆股帳務步驟與固定來源重跑結果

- 已抽出 DistributionInput／Result 及 apply_session_distributions，先複製 portfolio／receivables，再按股利→拆股計算，例外不部分改動輸入。歷史迴圈接上相同順序；原說明註解保留。
- 手算 10 股、每股股利 2、2:1 拆股得到股利 20 與新持股 20；另測未來碎股結算價格矛盾的錯誤原子性。三策略全部輸出再與最初 baseline 精確一致。
- Python 3.13 相關 33 項及 3.9 相關 21 項通過，Lint 通過；初次錯誤案例假設／不存在測試檔命令已修正，未改引擎既有未知 split 行為。證據在 `artifacts/acceptance/M14/distributions/`。
- 隔離來源兩案 session 78887 已終局通過：2 passed、4 個既有 warnings（315.68 秒），無放寬身份守門。完整 closing 快照 suite session 18447 仍執行，尚不宣告完整通過。

## M14：開盤撮合核心

- 抽取 OpeningExecutionInput／Result 與純撮合步驟（126 行），明列 portfolio、stops、pending、symbols、策略／執行設定、session／index、價格、流動性與 reference；回傳新的狀態及 orders／fills／settlements delta。歷史迴圈已接入，所有原 expiry、T+2 與風險預算註解隨程式保留。
- 原 `_Stop`／`_Order` 型別移至 engine_records，舊名稱保留 alias；bridge 共用，未建立第二套定義。撮合仍先 SELL 後 BUY、單筆最多 999、部分買單不補單、賣款不得資助當日買單。
- 三策略全部欄位再對最初 baseline 精確一致。3.13／3.9 相關回歸各 47 passed（2.97／3.78 秒），新手算各 2 passed（0.70／0.78 秒）；Lint 通過。證據在 `artifacts/acceptance/M14/opening/`。
- 下一步抽取訊號及完整 session orchestration、串接 checkpoint／分段一致性，再進 durable SQL；現有 closing 全套固定來源 session 18447 仍活躍，未宣告涵蓋後加 extraction。

## M14：訊號規劃與單日核心正式接入歷史迴圈

- 新增 SignalPlanInput／Result（128 行），顯式 signal_date、截止歷史、原始 rebalance offset、pending／stops、passive_submitted 與已知流動性；每日 stop 優先，拒絕未來／未對齊歷史與無效 origin。
- 新增 OddLotSessionInput／Result 與 run_odd_lot_session（150 行），複製 runtime 後按原階段順序推進至次日收盤。歷史回測已改呼叫該核心；訊號／成交／事件為 delta，交割保留累積狀態。原有註解隨抽取保留。
- 每一日結束序列化 checkpoint 再還原的續跑，與不中斷執行逐日訊號／orders／fills／actions／terminal／NAV 完全一致。最初三策略 baseline 全欄位精確相同；手算及既有事件回歸另保留。
- Python 3.9 session 與相關 38 passed（3.77 秒），3.13 先前訊號與相關 37 passed、獨立 checkpoint 案例通過，最新整合 38 項結果另記 acceptance；Lint 通過。證據在 `artifacts/acceptance/M14/session-core/`。
- 整體仍 in_progress：checkpoint 事件矩陣、單日來源契約與完整穩定來源回歸需補強，L03–L06、真實資料／M13／發布閘門仍未完成。

## M14：事件續跑矩陣與原子 checkpoint store

- 新增同日股利／反向拆股、T+2 買賣義務與延後碎股款的逐日 checkpoint 手算：cash 106／126／226／226，NAV 420／420／422／422；續跑與不中斷相同。缺碎股結算價不部分改動輸入。
- 新增 SessionCommit 與獨立 odd_lot_checkpoint_v1 SQLite schema（162 行），明確建立、拒絕覆寫、設定鎖、穩定 event ID、狀態／事件／完成指紋同筆交易。checkpoint 後及 events 後故障全 rollback；重開可重試，相同完成日 verified no-op。事件／鏈結變更拒絕，不自動修補。
- 3.13／3.9 atomic＋events＋core 各 8 passed（0.85／0.92 秒），Lint 通過；L-A02／A03／A06 僅列局部 scope，尚未據此接受整案。證據在 `artifacts/acceptance/M14/atomic-ledger/`。
- 較早 closing source 完整套件 session 18447 已通過：571 passed、8 warnings（598.75 秒），log 已保存於 closing-core/full313.log。這不涵蓋後加 core／ledger；最新固定來源 `/private/tmp/qfl-ledger-source-20261029` 的 full suite 為 session 82155、log `/private/tmp/qfl-ledger-full313.log`，正在執行。
- L03 仍 in_progress：完整 runner、來源／訊號 prefix、snapshot linkage、事件編碼、獨立帳務稽核與 UI 尚待，尚不能當可啟用的持久化帳戶。真實資料、R07 與發布矩陣也未結案。

## M14：內部 SQLite 續跑 runner 與無損事件編碼

- 新增 ReplayIdentity／Result 與 `_replay_account`，鎖定原始 origin、protocol／execution／calendar、研究／執行設定與暖機起始資料。每個交易日 fingerprint 串成 prefix chain；任何已完成輸入改動或缺失，甚至沒有新日也在寫入前拒絕。
- 新增 tagged business event codec，區別 NaN／NA／NaT／None，float 用 hex、時間保留 timestamp；缺值不造零。單日 delta 與 checkpoint 同 transaction 入帳，故障後重開續跑與一次完成的 metadata／checkpoints／events 三表精確相同；重送完整輸入 no-op。
- 3.13／3.9 replay、codec、atomic store、events、session 與既有研究／基準／訊號回歸各 35 passed（3.79／4.93 秒），Lint 通過。L-A01／A02／A08 記局部 scope，驗收在 `artifacts/acceptance/M14/internal-replay/`。
- 順功能接縫將既有 targets／sizing 移至 strategy.py（90 行），原 lookup／測試注入位置保留，odd_lot_research.py 降至 278 行；沒有新增另一套策略計算。初次 Lint alias 排序及多餘 alias 已修正，未壓制規則。
- 仍須正式 frozen study readiness 與實際 code identity 認證、snapshot／prefix reconstruction、獨立帳務 audit、並行輸入變動檢查及 UI；目前僅內部 replay，不能據 identity 字串啟用真實前向帳戶。完整固定來源 session 82155 仍追蹤其原始 snapshot，較晚改動另驗收。

## M14：獨立財務重建及 transaction 內稽核

- 新增只讀 audit.py，從事件重建利息、股利、拆股、terminal、fills、交割義務與碎股權利，核對 checkpoint cash／positions／receivables 及 NAV 各會計欄位，不呼叫 execution 函式。日期／TWD 幣別／fill 數量與 gross 另檢查，缺 NAV／估值證據即失敗。
- 內部 replay 於新日寫入前核對既有財務，並在 SQL transaction 中完成結構／hash 及財務驗證後才 commit。事件編碼新增 valuation marks，transition 升 odd_lot_session_v2_marks，舊內部帳戶不推測補值或自動遷移。
- 同時改 checkpoint cash、NAV 再重算 hash 仍遭事件重建拒絕；錯 NAV 於 commit 前拒絕且 checkpoint／event 全 rollback，重試成功。只讀 audit 前後 SQLite bytes 相同。
- Python 3.13／3.9 audit／replay／store／events 各 14 passed（3.04／3.67 秒），Lint 通過；證據在 `artifacts/acceptance/M14/accounting-audit/`。L-A02／L-A11 只列財務局部 scope。
- 止損／pending 風險重建、費率獨立重算、來源及 snapshot、正式研究／code identity 及 UI 尚待，不能宣告 L05 或 M14 全部 accepted。固定來源 full suite session 82155 仍活躍，只涵蓋其較早 source inventory。

## M14：獨立費率重算與不可變行情快照連結

- audit_fees 獨立重算佣金最低費、逐標的股票／ETF 稅、floor／nearest／fractional 逐項取整，檢查 fills／orders、opening reference、local/base gross／fees 與滑價。股利 withholding rate 綁定凍結設定，費用欄位相互一致卻不符 policy 仍拒絕。3.13／3.9 相關各 17 passed（2.82／3.89 秒），Lint 通過。
- 前輪固定來源完整回歸 session 83922 已終局：617 passed、11 warnings（669.44 秒）；log 保存於 audit-fees/full313.log。它不涵蓋本輪 snapshot 變更。
- 新 snapshots.py 以邏輯輸入 digest 建立不可變 snapshot 目錄，鎖定 manifest／dataset、拒絕 symlink／非法檔名，檢查全部 payload hash 與解碼後身份。內部 replay 鎖 snapshot root，逐日 SQL 存 linkage，續跑核對每個已提交日的 snapshot prefix。沒有新日也驗證，缺檔／篡改／換根目錄拒絕。
- Transaction 內重核輸入 prefix 與 snapshot，事件插入後來源變動則全 rollback。首次四項失敗因 audit 把 provenance link 當財務 codec，已修正為專屬 snapshot 核驗；3.13 snapshot／replay／audit 13 passed（7.26 秒），3.9 重跑另記 acceptance。
- 公開 frozen-study readiness／actual code identity、delta prefix 重建、風險稽核與 UI 仍需實作；snapshot 外部檔與 SQL 非同一交易，孤兒 payload 不算已完成。整體 M14 尚未 accepted。

## M14：來源認證歷史帳戶入口與 delta prefix 重建

- 新增 replay_registered_account，核對 executing package root／execution identity、protocol／candidate／period、source-backed frozen study、readiness 及 TWD，必須 snapshot root；於 SQL stages 重核協議／程式及來源。僅 historical replay，拒絕 forward_observation 與超出凍結期間 cutoff，未宣告候選不建帳。
- 3.13／3.9 registered workflow 各 2 passed（3.71／4.33 秒），含正常建帳／no-op、原始來源篡改及越界候選／期間拒絕。
- 新增只讀 reconstruct_account_history，以最後完成日 snapshot 補回歷史，丟棄未提交未來快照值、保留新 delta，核對 overlap／market／schema；再交 runner 驗證全部 SQL prefix。新行情續跑結果與完整輸入一致。3.13／3.9 history＋snapshots 各 7 passed（2.38／2.92 秒），Lint 通過。初次失敗僅 Parquet 不保留 pandas freq hint，已明列只排除此提示，所有日期／數值照核。
- 證據在 `artifacts/acceptance/M14/registered-history/`。新固定來源 full suite session 4873、log `/private/tmp/qfl-registered-full313.log` 執行；source inventory 保存，未宣告通過。公開 registered 歷史路徑仍使用凍結 study，delta 只交內部 runner；前向啟用、風險稽核／完整案例及 UI 尚待。

## M14：獨立 recorded-risk lifecycle 稽核

- 新增 audit_risk，無 signal／matching／session 函式依賴，按前一 checkpoint 與 close/open／權息／terminal inputs 重建 stop trailing、stop trigger、股利→拆股、退出重試、entry stop／budget、full exit 清理、pending／terminated／passive flag。模型分數及 target weights 仍為訊號證據，不宣稱獨立重算 alpha。
- 財務 audit 串入風險結果；replay 存 risk_inputs，transition 升 v3_risk，舊缺風險證據帳戶不補造或自動遷移。重算 hash 後改 stop／pending／flag 仍於續跑前拒絕。手算 trailing close 110→stop 99，再扣股利 2／2:1 拆股為 stop 48.5、high 54；stop 未成交保持 SELL retry。
- Python 3.13／3.9 risk／financial／replay 各 12 passed（8.89／13.95 秒），3.13 snapshot／history 回歸 7 passed（2.86 秒），Lint 通過。正式 registered workflow＋risk 另重跑，結果保存其 log。證據在 `artifacts/acceptance/M14/risk-state-audit/`。
- 仍須廣泛風險／事件案例、來源快照證據對應、前向啟用與 UI；M14 整體尚未 accepted。固定來源 full suite session 4873 仍活躍，僅驗證原 inventory，不涵蓋本次風險延伸。

## M14：只讀帳戶檢視與歷史建帳／續跑 UI

- OddLotLedger 增 read_only，inspection 僅 mode=ro 開帳戶並核結構／事件鏈及共用財務／風險 audit；source status 明列未在此檢查外部來源。真實讀取前後 SQLite bytes 保持。
- 主 sidebar 新增「零股持久化歷史帳戶」入口，呈現獨立表單、checkpoint／digest、cash、session count、事件及稽核問題。執行動作呼叫 replay_registered_account，不另算 readiness／會計。預設續跑，明確選新建才 create，失敗不 reset／重建，rerender 不自動重送。
- Python 3.13／3.9 AppTest 各 4 passed（2.58／3.17 秒），含真實 account 檢視、缺檔無副作用、失敗不切新建、主 UI 入口；Lint 通過。證據在 `artifacts/acceptance/M14/account-ui/`。L-A12 僅歷史 UI scope，不是全 M14 accepted。
- 新固定副本 `/private/tmp/qfl-account-ui-source-20261029` 完整 suite session 29945、log `/private/tmp/qfl-account-ui-full313.log` 執行，含最新風險與 UI；先前 registered/history 副本 session 4873 仍依原 inventory 追蹤。前向啟用、完整風險／來源對應矩陣與真實 coverage／rights／發布驗收尚待。

## M14：帳戶事件與核驗行情的精確綁定

- 新增 source_checks，risk_inputs／valuation 與已核對 MarketData 逐欄 exact tagged encoding 對比；每個完成日續跑前及 transaction commit 前皆核對。訊號日期／價格必須對應前日收盤，主動策略 entry stop 按當時 volatility window／multiplier／bounds 獨立重算。
- 案例同時重算帳本 hash、微改 observed_open 的有限值，使既有財務／風險內部公式仍通過；新 source binding 仍拒絕且 SQLite bytes 不變。另測 entry stop 不符凍結波動規則拒絕。未聲稱獨立重算 alpha scores／weights。
- Python 3.13／3.9 source binding、risk、snapshot、replay、financial audit 各 20 passed（14.92／20.80 秒），Lint／diff check 通過。完整 logs、source hashes 與 scope 見 `artifacts/acceptance/M14/source-event-binding/`。
- 先前固定來源 full suites session 4873／29945 仍按各自原 inventory 追蹤；本次延伸不借用舊 snapshot 的完整通過聲明。前向啟用、完整 UI／發布矩陣及真實 coverage／rights 尚未完成。
