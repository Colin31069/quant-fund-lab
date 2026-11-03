# DATA-01：取得缺少的台股歷史月價量

狀態：已另建執行聊天。Thread ID：`01a18086-65e3-7362-9b7d-ea546370d3e0`。
本檔定義計畫；實際取得數量以該工作的 `progress.json` 為準，不能將建立聊天當成資料已補齊。

## 續規劃進度快照（2026-10-28 11:32:23 +08:00）

本輪讀取 `artifacts/data_acquisition/2026-10-28/progress.json`：FinMind obtained／validated 均為 405，provider_remaining 為 0；official imported 為 0、remaining 為 405，research acceptance 仍 blocked。33 份 raw 價量及 normalized CSV 的 hash 已在本輪重核，與 provider manifest 相符。

原始目標 A／B／C 的 31／132／242 個 key 均已取得供應商資料，尚不符合下文官方匯入完成條件。原計畫與分母保留；新增 [DATA-02](DATA_SOURCE_INTEGRATION.md) 處理獨立來源接入，官方取得路徑繼續單獨核銷。

取得階段已輸出 8,128 筆目標日資料與 1,897 個官方數值抽查相符結果；日曆差集、企業行動與五類審核仍待完成。現行 inventory 採 obtained／validated 等布林欄，與下文原擬 status 欄不同，後續交接須明確映射且保留原始欄位。全部交付與研究驗收未通過前，DATA-01 不標 accepted。

## 目標、範圍與輸入

覆蓋缺少的 405 個 `(symbol, month)`，研究截止日固定 `2026-10-27`。11 個標的為 `2330.TW,2317.TW,2454.TW,2308.TW,2881.TW,2882.TW,2891.TW,1216.TW,1301.TW,2412.TW,0050.TW`，最後一個是基準。

起始清單為 `artifacts/odd_lot_studies/bfc2860d15435d56874eb036/reports/47e37b5b948044c6a1b485fec77004f0/missing_source_manifest.csv`。2026-10-28 已與現行 `artifacts/twse_odd_lot/manifest.json` 交叉核對，405 個均仍缺少。開始及每批完成時須重算，避免重複下載其他工作已補上的檔案。

| 批次 | 月份／缺口 | 階段驗收 |
| --- | --- | --- |
| A | 2023-10 至 2023-12，31 個 | 先交付開發期缺價修復，不宣稱事件審核已完成 |
| B | 2024-01 至 2024-12，132 個 | 驗證期月份覆蓋；暖機及事件另由 M12-5 判定 |
| C | 2025-01 至 2026-10，242 個 | 歷史評估月份覆蓋，資料僅使用至截止日 |

一份全市場逐日檔可能覆蓋多個需求；實體檔數與覆蓋月份分開計數。既有 499 筆來源登記與原始檔先保存雜湊基線；任何變更另建可追溯版本，不能改寫舊凍結研究。

## 已核對的取得路徑

以下來源於 2026-10-28 查核；「頁面存在」不等於已驗證能取得所需歷史資料。

| 優先 | 路徑與依據 | 已知能力 | 尚須驗證／採取動作 |
| --- | --- | --- | --- |
| 1 | 本機已取得但未登記的官方檔案 | 可沿用原始 bytes 做離線匯入 | 檢查來源身分、日期、代碼、雜湊與是否為孤兒檔；不能無證據補 provenance |
| 2 | [政府開放資料 11549](https://data.gov.tw/dataset/11549) | 列有 OHLC、成交股數；每日更新、免費開放授權 | 確認資源是否有歷史快照／歷史參數，及授權實際涵蓋端點；當日資料不能充作歷史回補 |
| 3 | [TWSE 歷史個股日成交查詢](https://www.twse.com.tw/zh/trading/historical/stock-day.html) | 有歷史查詢及 CSV 下載 | 查明可同意使用的批次取得方式；不能從公開查詢能力推論自動擷取已獲同意 |
| 4 | [TWSE 資料商店](https://www.twse.com.tw/zh/products/dataeshop.html) | 有盤後資料及歷史商品 | 先核對商品、樣本、月份與內部研究使用權；[FAQ](https://eshop.twse.com.tw/zh/page/faq.html) 提醒較早資料需另確認取得方式，價格與交付時間待查 |
| 5 | 其他有明確授權的供應商 | 需由供應商官方文件與樣本證明 | 若有完整 raw 價量，使用獨立 provider 身分與 schema；不得偽裝 TWSE 原始檔 |

[TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html) 對未經同意的自動下載設有限制；現有 `download_twse_bundle(authorized=False)` 守門維持。先建立可核對的來源／存取依據，不能僅因使用者要資料就替資料提供方聲明同意。這不妨礙本機盤點、公開文件調查與已授權資料匯入繼續進行。

本工作未獲代付款或代寄外部詢價訊息的授權。若需要付費／外部同意，先交可決策的商品、範圍、樣本、價格狀態及詢價草稿；沒有報價時明列未知，不能填估計值當報價。

## 執行工作包

| ID | 步驟 | 交付物／退出條件 |
| --- | --- | --- |
| D01 | 讀取 manifest、凍結缺檔清單，按批次及標的分組；保存既有來源 hash | `inventory.csv` 唯一鍵無重複；基線 31＋132＋242＝405 可重算 |
| D02 | 調查上述來源的歷史範圍、欄位、單位、raw／adjusted、ETF、存取同意與費用 | `source_matrix.csv` 每項含官方 URL、查核日期、已證實／未知、採用或拒絕理由 |
| D03 | 對候選途徑取得少量跨股票／ETF、跨批次的真實樣本 | 原始檔＋provenance 可解析；至少涵蓋股票／ETF與 A／B／C 的代表需求，尚缺樣本不能通過 |
| D04 | 用現有批次預覽檢查；若格式不同，先定義小型 adapter 契約與離線測試 | 不能把供應商資料改標為 TWSE；代碼／日期／單位與欄位正規化有可重現對照 |
| D05 | 依 A → B → C 取回、驗證並匯入；逐筆保存成功與失敗 | 可中斷重試，已存在相同來源不重寫，衝突隔離；限流／失敗依來源規範處理 |
| D06 | 比較原始需求與成功匯入集合，重新做逐日缺價檢查，交接 M12-5 | `progress.json`、剩餘清單、品質結果、重試方式與資料限制；不能以 HTTP 200 當成功 |

## 必要資料契約

`inventory.csv`：`symbol,month,batch,status,provider,source_url,raw_path,sha256,retrieved_at,error_code`。狀態區分 `missing/acquired/validated/imported/blocked`，每次狀態變更有歷程；`imported` 必須已有有效 manifest linkage。

Provenance 至少記錄真實來源、取得時間（含時區）、原始 bytes SHA-256、內容涵蓋日期、raw 價格與成交量單位、授權參照。若需正規化，另記 converter 版本、輸入與輸出 hash，保留原始檔，不將轉換檔說成官方原檔。

`progress.json` 分別計算 `target,acquired,validated,imported,remaining,blocked`；計數以目標 key 的集合運算取得。完整達標要求 `imported=405, remaining=0` 且逐日價格檢查通過；只關閉月份清單卻還有無法解釋的缺價，屬未通過驗證。

## 驗收矩陣

| 案例 ID | 情境 | 通過標準／證據 |
| --- | --- | --- |
| DATA-A01 | 重算缺口 | 去重後恰為原始目標集合；新增／已由他處補足的需求另列變更，不偷改分母 |
| DATA-A02 | 真實資料樣本 | 股票與 ETF、三批代表需求均能追溯原始檔並解析；空頁、登入頁、錯月或錯代碼一律失敗 |
| DATA-A03 | 數值與單位 | OHLC 為正且 finite、量非負且以股為單位；官方停牌／無成交例外有明確規則，不補假 open |
| DATA-A04 | 原始價格 | 核對樣本 raw 價格與來源；拆股前後不得拿已還原價再重複套拆股，未知基準不得匯入正式研究 |
| DATA-A05 | 重試與衝突 | 相同來源重試不增加重複 key；內容／來源衝突不覆寫；中斷後不丟已驗證資料 |
| DATA-A06 | 批次 A／B／C | 各批原始 key 全部已匯入，分別 31／132／242；每個 key 可反查來源與 hash |
| DATA-A07 | 舊來源保護 | 執行前後既有來源 bytes hash 一致；有正當新版本時保留前版與差異證據 |
| DATA-A08 | 最終覆蓋 | `remaining=0`；逐日缺價有行情或已核對停牌／休市解釋；企業行動缺口另列並交 M12-5 |

完整交付放 `artifacts/data_acquisition/2026-10-28/`，含 README、清單、來源比較、樣本、進度與核對結果。若外部條件阻擋，仍交上述可完成成果與精確剩餘 key；狀態為 `awaiting_external`，不得把調查完成報成資料完成。
