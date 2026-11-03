# P0：交易日曆測試與可重建環境

狀態：待實作。預估 1–2 人日。此工作的必要案例全數通過，才解除後續發布的基線阻擋。

執行更新（2026-10-29）：以上保留最初規劃狀態；目前 `in_progress`。獨立 3.13 環境、隔離匯入、共用日曆及完整測試已交付；現另建獨立 Python 3.9.6 環境，乾淨安裝／repo 外匯入與 UI 模組匯入通過，原日曆失敗重現。相容 resolver 選到 4.5.6，採下述方案 B 補有官方依據的休市；不提高最低 Python 版本。完整結果及未解矩陣見 [EXECUTION_STATUS](EXECUTION_STATUS.md)，依賴重建見 [scripts/README](../../../scripts/README.md)。

## 問題與已核對依據

現有環境 `exchange-calendars==4.5.6` 將 `2025-01-09` 列為 XNYS 交易日，導致 [test_core.py](../../../tests/test_core.py) 的 `test_calendar_missing_session_is_reported_but_not_fatal` 失敗。官方已公告該日美股市場因卡特全國哀悼日休市，因此此案例的預期有依據。[ICE／NYSE 2024-12-30 公告](https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx)

本輪另查出同一 `.venv` 混用兩套 Python，這是優先要消除的環境差異：

| 入口 | 實際 Python | exchange-calendars | 觀察 |
| --- | --- | --- | --- |
| `.venv/bin/python -m pytest` | 3.9.6 | 4.5.6 | 初次完整測試 310 通過、1 個日曆失敗 |
| `./scripts/verify.sh` → `.venv/bin/pytest` | shebang 指向 `.venv/bin/python3.13`，版本 3.13.13 | 4.13.2 | 本輪完整測試 311 通過，Lint 通過 |

同一 prefix 並不能證明同一 runtime。P0 應先選定並乾淨重建執行環境、統一測試入口，再判斷是否需要日曆例外；不能為已正確的 Python 3.13 日曆重複加特判。專案仍宣告支援 Python 3.9，若保留此支援須驗證相容方案；若調整最低版本，另列明確相容性決策。

續規劃另核對安裝狀態：原始碼 `__version__` 為 `0.12.3`，兩個 runtime 的 `importlib.metadata.version("quant-fund-lab")` 卻都是 `0.11.6`。3.9 可直接匯入工作區原始碼，3.13 的 `find_spec("quant_fund_lab")` 為 `None`、直接 import 失敗；pytest 透過 `pyproject.toml` 的 `pythonpath=["src"]` 仍能測試原始碼。故測試通過不能代替乾淨安裝與匯入驗收。

目前 [market_calendar.py](../../quant_fund_lab/market_calendar.py) 的兩條驗證路徑都直接讀套件日曆：一般市場序列與逐日期市場 metadata。修正必須同時覆蓋，且保留真正缺交易日與週末資料的檢查。

## 先定義的介面與修正選擇

現有 `SessionValidation` 與 `require_*()` 公開行為保持相容。先將「預期交易日」定義為單一入口，兩個驗證路徑共用。

| 項目 | 契約／決策準則 |
| --- | --- |
| `CalendarEvidence`（如需新增） | exchange、effective date、事件類型、公告日期、source URL、evidence hash；未知來源不可套用 |
| 預期交易日入口 | 固定 market/start/end/calendar revision，回傳唯一、遞增、正規化日期及可記錄的日曆識別 |
| 方案 A：更新相容依賴 | 在暫存環境驗證支援專案 Python、該休市與既有 XTAI／XNYS 行為，再固定依賴集合 |
| 方案 B：有依據的例外層 | 若相容更新無法解決，以版本化官方休市例外覆蓋；修正在日曆供應層，避免散落多處特判 |

選擇能以最小改動通過所有必要案例的方案；記錄另一方案未採用的實際理由。Python 支援範圍維持專案宣告，除非另有版本升級決策。套件能力以[維護者發布資料](https://pypi.org/project/exchange_calendars/)及實際相容測試判定。

## 執行工作包

| ID | 動作 | 產物／退出條件 |
| --- | --- | --- |
| P01 | 保存兩條入口的 sys.executable／Python／套件版本、shebang、安裝版本／import 路徑與原始失敗；取得公告證據 | 可重現入口及 packaging 差異的最小輸入、環境紀錄與來源 hash |
| P02 | 在乾淨暫存環境驗證 runtime、依賴或例外方案，列出受影響日期與市場 | 修正決策紀錄；選定執行版本、最低支援版本與重建方式，無未解相容問題 |
| P03 | 先定義單一日曆入口及型別，再接兩條驗證路徑 | 一般與 metadata 驗證對相同市場／日期有相同預期日集合 |
| P04 | 補必要離線回歸，固定可重建環境與日曆版本 | 測試不依賴線上 API；新環境重建後套件版本可核對 |
| P05 | 跑完整 Lint／pytest，檢查資料切片與 snapshot 行為 | 原 311 個測試全部通過，加上新增必要回歸亦零失敗 |

## 驗收矩陣

| 案例 ID | 輸入／操作 | 預期結果 |
| --- | --- | --- |
| P0-A01 | US 觀測日只有 2025-01-07、2025-01-10 | missing 含 01-08，排除已確認休市的 01-09；仍可回傳品質報告 |
| P0-A02 | 相同日期透過 point-in-time US metadata 驗證 | 與一般驗證的 expected／missing 集合一致 |
| P0-A03 | 觀測日含週六 2026-01-03 | 既有 `require_*()` 仍拒絕週末 bar |
| P0-A04 | 混合 US／TW union，只有另一市場當日開市 | 不因 forward-filled close 將休市市場認作有 bar |
| P0-A05 | 未列在官方例外的真正缺漏交易日 | 仍出現在 missing；不能把所有缺價都當休市 |
| P0-A06 | 空日期、未知 market、時區與日期邊界 | 保留既有明確拒絕／正規化語義，不靜默回退至工作日曆 |
| P0-A07 | 乾淨環境分別經一鍵腳本及 python -m 執行 | 兩路實際 interpreter／套件一致且所有測試 exit code 0；宣告保留支援的版本亦通過，不混用 site-packages |
| P0-A08 | 既有 snapshot／凍結研究驗證 | 可照原格式讀取與驗證；不重寫舊 manifest／ledger |
| P0-A09 | 乾淨環境安裝後從 repo 外直接 import，再啟動 UI 模組匯入 | 不借用 pytest pythonpath／臨時 PYTHONPATH；匯入定位與安裝目標相符、原始碼及 distribution version 一致；同一環境可執行 Streamlit 入口 |

修正若使新研究使用的有效日曆改變，將日曆版本納入新研究 context；既有完成日不能事後重算覆蓋。例外的市場生效日與公告可得日分開記錄，後者不能用來在當時未知的訊號中預知未來休市。

## 完成證據與交接

交付最小程式差異、離線測試、可重建環境檔、官方公告及修正決策。驗收紀錄放 `artifacts/acceptance/P0/<run_id>/`，包含測試完整摘要與依賴版本。完成後 M12-4 使用這個單一日曆供應入口判斷暖機覆蓋。

## Python 3.9 修正決策

2026-10-29 在 `artifacts/environments/p0-clean39` 乾淨解析及安裝專案，仍選 `exchange-calendars==4.5.6`；修正前完整測試為 368 passed／1 failed，失敗即原 2025-01-09 案例。[維護者的 4.5.8 發布 metadata](https://pypi.org/project/exchange_calendars/4.5.8/) 已要求 Python `~=3.10`，不能將新版本直接安裝到 3.9 並宣稱相容。

採方案 B：`OfficialClosureCorrection` 先定義市場／calendar／生效日／公告日／URL／審核說明；共用日曆供應層只移除已證實且仍被套件列為開市的日期。修正加入 `official-closures-v1` 審核紀錄 digest；套件已正確排除該日則不增加 correction revision。保留 01-08 真正缺價及 01-09 異常 bar 的辨識，一般與 metadata 路徑共用。

來源為本文連結的 ICE／NYSE 公告，已透過 web 工具閱讀。直接下載原始 HTML 回傳 HTTP 403，故 `artifacts/acceptance/P0/nyse-evidence/review.json` 是明列取得限制的審核紀錄，不冒充原公告 bytes 或原文 hash。這個修正不回填歷史公告可得資訊，也不會重算覆寫既有帳本。
