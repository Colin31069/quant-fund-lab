# TWSE study readiness

`types.py` defines immutable findings, warmup evidence, period decisions and study results.
Finding IDs bind code, symbol, interval, discriminator and source policy; display text can change without changing semantic identity. The readiness fingerprint includes the full decision and evidence.

Warmup evidence must enumerate expected sessions independently of observed rows. Verified sessions must be a subset; only complete equality and the configured count permit a ready decision. Findings and dependencies remain traceable; periods cannot reference missing findings.

Assessment, legacy issue mapping, frozen-study integration and UI are still pending. These contracts alone do not certify any real dataset.

`readiness.py` now provides `assess_study_readiness(TWSEInput, periods, calendar=..., warmup=..., required_symbols=...)`. It verifies source bytes on every assessment, checks every expected session across stocks and benchmark, and requires at least max(120, configured warmup) complete prior sessions. Period ends are explicit. The caller supplies an evidence-reviewed TW calendar with coverage bounds; absent or insufficient calendar evidence yields unknown.

`legacy.py` maps known legacy findings conservatively and retains unknown messages as blockers. Identical legacy records retain an occurrence count; missing-day findings link to missing-month findings without dropping either. The assessment hashes the data, source inventory, issues, periods and calendar; it never writes files or computes performance.

Frozen-study/UI integration and the official effective-calendar adapter are still pending. Assessment fixtures prove the core contracts, not acceptance of the real local bundle. The earlier pending statement records the initial contract-only delivery.

## Frozen-study integration

New official freezes now use study schema 3. `frozen.py` re-prepares the archived raw bundle and compares normalized data, source inventory and quality findings before assessment; supplying source hashes cannot disguise unrelated prices or omitted issues. All period ends are explicit. `twse_calendar.py` supplies annual-calendar and sourced market-closure overlays; absent required annual coverage remains unknown.

The frozen metadata records the full decision and fingerprint. Load revalidates it, the runner blocks affected periods before performance, reports include `readiness.json` and `readiness_periods.csv` in the hash manifest, and the UI presents the same decision through `ui.py`. Source-specific legacy studies remain on schemas 1/2 without rewriting their files. Unknown future schemas are rejected.

The complete raw issue inventory remains available; display reasons show at most 20 details and link users to the full findings export. Raw quotes and invalid derived valuation/action state use separate codes so an unresolved event is not mislabeled as a missing price download. Individual findings reference the source manifest/manual records, while the full inventory is bound once in the input identity.

Ready and blocked end-to-end fixtures, normalized-data mismatch rejection, report tampering, UI presentation and the existing schema-2 local report have been checked. Full milestone acceptance still requires the remaining matrix, P0 compatibility, source handoff and period-specific data acceptance.

## Effective calendar contract

`market_calendar.CalendarClosures` is an immutable, market-scoped closure evidence snapshot with explicit coverage and a source revision. `twse_calendar.official_closure_evidence(source_files, source_hashes, start, end)` verifies the source bytes, annual coverage and global suspension evidence before constructing it; insufficient annual coverage returns `None`. Individual stock suspensions remain market sessions.

`expected_market_sessions(..., closures=...)`, general daily validation and point-in-time market validation accept this explicit snapshot. A market/coverage mismatch is rejected. With no snapshot the general API retains its package-calendar behavior; it cannot infer market closures from missing prices. Both official preparation and `official_calendar()` now use the same expected-session function and evidence adapter. Readiness consumes that same effective calendar. Missing annual sources still block preparation and leave readiness unknown.

The evidence revision and session values preserve the existing `twse-closures-v1` identity: this consolidates the calculation rather than retrospectively changing archived calendar policy. `tests/test_twse_calendar.py` checks annual and emergency closures, individual suspensions, genuine missing days, evidence tampering and the common session set across consumers. These contracts do not shift corporate-action dates or prove point-in-time publication availability.

Explicit cash-dividend date resolution is separate in `odd_lot_event_dates.py`. The optional `action_date_reviews.csv` binds the original event index, reviewed rule and scheduled/effective dates to source hashes. Only a verified market-wide closed day and its next effective session can resolve a pure cash dividend. Subscriptions, stock distributions and unsupported rights cannot use this rule. Without the registry existing archived decisions are unchanged. New reports include the hashed review CSV; cash payment timing remains the existing effective-ex-date simulation assumption.


## Readiness 驗收邊界補強

`tests/test_readiness_acceptance_edges.py` 補實際來源流程：重查前後完整檔案及既有
SQLite inventory 不變；顯示翻譯保留已評估問題 ID／blocking 狀態；只有基準 split
審核缺漏時，共用凍結 runner 仍拒絕產生帳戶績效；月檔匯出／匯入修復只移除
缺價，未建模事件的 blocking ID 與缺失 coverage 保留。
來源 fixture 的已知 issues 必須如實帶入 freeze，不能傳空集合繞過來源重建。
這些案例不代表真實 coverage 或權利事件已驗收。


## 分期缺月與暖機修復摘要

`repairs.py` 先定不可變 `PeriodRepairSummary`，再由
`period_repair_summaries(readiness)` 讀取已核驗的凍結判定。缺月以
`(symbol, month)` 去重，僅計入該期間 blocking IDs 引用的必要缺月；
非阻擋 context 不提升為修復需求。同一月可同時影響期內與暖機，兩欄不相加。
暖機未驗證數取預期 session 與已驗證集合之差；required shortfall 另列，
不將「未證明足夠」誤稱為等量已知缺價日。無法確認暖機窗口時缺月欄留空。

UI 與 `readiness_repairs.csv` 共用 `repair_summary_frame()`；HTML 也由相同
凍結資料產生。新增報告 manifest 明列 `repair_summary_rule=period_repairs_v1`，
讀回必須從原凍結 readiness 重建完全相同的 CSV，修改數字後重算 hash 仍拒絕；
未知規則拒絕。舊報告沒有此宣告及檔案時沿原格式驗證，不回寫舊資料。
這個摘要不改 readiness fingerprint、阻擋判定或績效規則。

`tests/test_readiness_repair_summary.py` 包含實際跨期缺月、原始來源→freeze→
runner→report→UI 的 ready／blocked 一致性、同月雙窗口去重、未知窗口、
新摘要與重算身分的新 readiness 篡改。主 AppTest 額外核對報告指紋、修復 ID
與實際 SQLite 帳戶數（受阻為零）。驗收範圍及分輪 logs 在
`artifacts/acceptance/B01/readiness-repair-summary-20261029/`；真實來源仍須另驗。
