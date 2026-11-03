# Frozen odd-lot protocols and experiments

`types.py` defines immutable contracts. Nested settings are canonical JSON strings rather than mutable dictionaries. `protocol_from_studies()` accepts a finite tuple of verified, current schema-3 studies. Candidates must share exact snapshot, source inventory/policy, readiness inputs, calendar, universe, periods and warmup. Each candidate binds its full research and backtest settings. Candidate and protocol IDs are deterministic; the protocol stores its exact candidate budget, selection/rejection rules, seed and analysis grid.

The original v1 analysis plan explicitly describes the existing batch engine: ensemble, momentum and equal-weight, its fixed validation sensitivity scenarios, and the no-cost total-return reference. The seed is identity-bearing; this engine currently makes no random draws. V1 retains its original declaration that the tradable benchmark is absent. V2 adds the explicitly declared ETF benchmark below; automatic candidate selection remains pending and is not implied by a successful engine run.

In this initial interface a candidate is one complete frozen batch configuration, not a single strategy row. The protocol explicitly lists all three strategies and every sensitivity scenario evaluated inside that batch. Subsequent selection/multiple-testing diagnostics must account for those strategy/scenario trials, rather than using the batch count as the number of statistical trials.

`ProtocolPeriod` records purpose and prior data access. Already-accessed or unknown post-2025 periods remain historical exploration; a backdated declaration cannot preregister already historical observations as unseen. Local declaration/recording timestamps and content hashes do not independently prove preregistration or historical publication availability.

## Public workflow

1. Freeze candidate studies with the existing source verification and readiness contracts, before looking at candidate performance.
2. Capture `ExecutionIdentity` from the actual source checkout. It binds Git revision, tracked code diff, untracked source/test bytes and runtime versions. Markdown progress records and output artifacts are excluded. The execution wrapper rejects a different source directory from the executing package.
3. Build a `StudyProtocol` using explicit periods, access notes and `SelectionRule`, then `freeze_protocol(protocol, protocols_root)`. Existing content is verified/reused, never overwritten. A child requires its parent protocol to exist.
4. Call `run_registered_study(protocol_path, candidate_id, studies_directory=..., registry_path=..., source_directory=...)`. The wrapper revalidates candidate settings and source identity, calls the existing guarded runner, exports the report and records the outcome.

`storage.py` publishes `protocol.json` atomically. Its actual recording time is separate from supplied declaration time. `registry.py` uses a dedicated SQLite schema, refusing unrelated paper/account databases. Protocol and experiment definitions are immutable. Each execution starts a new numbered attempt; completed attempts cannot be rewritten or deleted through the supported schema/API. Concurrent starts serialize and reject a second running attempt.

An interrupted running attempt requires an explicit `finish_attempt(..., status="failed", reason=...)` before retry. There is no automatic reset. Failed and blocked attempts remain visible through `experiments()` and `attempts()`. Repeated identical successful or blocked inputs must reproduce their result fingerprint; a mismatch is stored as a failed attempt with the observed fingerprint, retaining earlier results.

## Outputs and limits

`results.py` hashes business frames, configurations, metrics and unavailability reasons. Exact float representations and distinct missing kinds are preserved; report UUIDs, output paths and attempt timestamps are excluded. Missing outputs are not converted to valid zero-valued metrics.

Reports add `protocol.json`, `experiment.json` and a human-readable protocol/access section, all included in the existing report hash manifest. Outcome `succeeded` means the declared computation completed; it does not establish sufficient trades, strategy validity or milestone acceptance. Required unavailable periods produce `blocked` while preserving their report and full readiness details. The wrapper cannot turn an old holdout checkbox into unseen-sample evidence.

Report verification also validates protocol content identity, candidate settings, study/data binding and experiment identity. Rehashing an edited protocol sidecar does not make a mismatched experiment valid. The initial local report context without an explicit schema field remains readable as v1; new reports write that field explicitly.

The registry protects normal lifecycle operations and verifies stored content identities. It is not a signed external audit service; an administrator controlling the database and source files is outside that integrity guarantee. Separate output files and SQLite are not one transaction: a crash can leave a report without a terminal attempt, which requires explicit review/recovery. The wrapper never overwrites an earlier report or resets a failed experiment.

Tests use offline ready/blocked source bundles, deterministic repeated runs, injected failures, source mismatch, report tampering, concurrent starts and numerical mismatches. Real local data remains independently subject to event, coverage and period acceptance. UI protocol controls, automatic selection, risk diagnostics and M13 statistical/report acceptance are not complete.

## V2: tradable ETF benchmark

Pass `benchmark_spec=BenchmarkSpec(...)` to `protocol_from_studies()` to freeze `frozen_odd_lot_batch_v2`. The spec requires the study's separate benchmark symbol, matching initial cash, explicit ETF sell-tax and price-band assumptions, and a rule note. It fixes one initial close signal followed by one next-session order, daily expiry of any remainder, cash dividends without reinvestment and the same observed-session settlement proxy. Rules are declared model inputs, not a certification of historical legal or broker behavior.

`odd_lot_benchmarks.run_tradable_benchmark()` uses a single-ETF view and the shared odd-lot account loop. It keeps strategy matching/slippage/commission/participation/fill-fraction assumptions; only passive allocation and the explicit ETF instrument rule differ. The benchmark has no stop/risk sizing, so an unrelated strategy volatility window cannot suppress its initial order. The existing default multi-asset strategy path retains its behavior and the study still requires at least two trade assets plus a separate benchmark.

Entry requests at most 999 shares once. The shared fill engine can reduce that request for liquidity, partial-fill or cash constraints. It never creates a later top-up. Dividends, splits, fractional receivables and T+2 observed-session accounting use the same account operations; dividend payment remains the model's effective-ex-date assumption.

`benchmark.py` gates every period on the frozen readiness result, uses the same warmup/evaluation sessions as the strategy and attaches the benchmark's fills, orders, settlements, actions, episodes and equity curve to the standard report/archive. `benchmark_specs.json` is hashed and semantically compared with the protocol. The comparison table labels the no-cost reference and the cost-bearing strategy/benchmark rows separately and reports final invested/cash fractions. Benchmark entries are not automatically added to the existing strategy sensitivity grid; that extension belongs to R05.

V1 protocols and reports keep their old analysis identity and remain readable. Upgrading to v2 creates a child protocol and a new experiment. A blocked period also blocks its ETF benchmark; additional unavailable benchmark combinations do not imply additional missing dates or attempted performance searches.

## V3: risk diagnostics

Pass `risk_diagnostics=True` together with an explicit `benchmark_spec` to freeze `frozen_odd_lot_batch_v3`. `diagnostics.py` attaches read-only account diagnostics after benchmark execution and before numerical fingerprinting. V1/V2 continue to omit diagnostics; any execution code change requires a new protocol identity.

The [diagnostic module](../odd_lot_diagnostics/README.md) records capital/settlement ratios, emitted unfilled outcomes, entry-budget loss excess and first-stop-to-share-exit latency. Open positions and unsettled entitlements stay pending; passive benchmark budgets are not applicable. Missing evidence remains unavailable. Reports write JSON, per-account CSVs and HTML limitations. Verification reconstructs diagnostics from archived account sources and checks account inventory, JSON and CSV consistency, in addition to hashes and protocol binding.

The earlier paragraph describing risk diagnostics as pending records the pre-v3 scope. Core diagnostics and report integration now exist; benchmark sensitivity, automatic candidate decisions, UI controls and full M13 acceptance remain separate work.

## V4: matched sensitivity

Add `matched_sensitivity=True` alongside the benchmark and diagnostic declarations to freeze `frozen_odd_lot_batch_v4`. The existing finite scenario grid is evaluated for ensemble, momentum and the declared tradable ETF on identical validation sessions. V4 skips the old summary-only sensitivity branch and retains every outcome plus each successful scenario's settings/business frames. Older protocol versions retain their analysis declarations and reports.

The [sensitivity module](../odd_lot_sensitivity/README.md) records unavailable metrics, failed/blocked scenarios, costs and invested/cash fractions. Any failed required scenario makes the attempt failed after exporting all outcomes; a later successful retry preserves the earlier report. The verifier checks the full frozen grid, source-account summaries and settings. No automatic selection is performed from validation sensitivity. The earlier sensitivity-pending statements record pre-v4 scope; automatic decisions, UI, real-data acceptance and full M13 validation remain separate.

## V5: executable decision policy and registered sources

Provide an explicit `DecisionPolicy` through `decision_policy=...` along with benchmark, diagnostics and matched-sensitivity declarations. V5 requires ordered development-selection and validation-check periods; objective/sample counts must agree with SelectionRule. The structured policy governs decisions; legacy free-text notes do not override its gates. Old v1–v4 plans remain without executable selection.

`odd_lot_decisions.workflow` reads complete registry attempt prefixes and verified study/report sources, recomputes primary account metrics, checks locked account settings and rejects contradictory comparison values. Development ranking is not replaced after validation failure. Required matched-scenario counterpart failures remain unavailable even when one strategy row succeeded. Decision JSON/CSV/HTML and full source references publish atomically in a new capture directory; archived prefixes remain verifiable after later attempts. A new live export must match the protocol's execution identity and unchanged current sources.

These are local integrity guarantees, not signed source/time authenticity. The separate development-only selection artifact, strictly phased evidence collection and UI are still outstanding under M13_DECISION_UI; current whole-evidence decision identity must not be presented as a development-only fingerprint. Real-data acceptance and full R07/M13 gates remain independent.

Development analysis now has a separate collector and immutable selection capture in [odd_lot_decisions](../odd_lot_decisions/README.md). It authenticates complete byte inventories while parsing only development account business evidence; it does not reinterpret the existing v5 batch execution as staged. `registry_read.ReadOnlyExperimentRegistry` reuses registry read validation through SQLite `mode=ro` and `query_only`, rejecting missing/empty/foreign/unsupported databases without initialization. Existing writable registration behavior is unchanged. The phased final-decision protocol/workflow and UI remain separate deliverables.

## V6: saved development selection before validation analysis

Pass `phased_decisions=True` with the explicit decision policy, benchmark, diagnostics and matched-sensitivity settings to freeze a new v6 child protocol. The analysis plan declares `saved_development_selection_then_validation_v1`, `persist_before_validation_v1` and `development_selection_v1`. Unsupported/missing declarations are rejected; v5 cannot inject the new capture/selection fields. Defaults keep the original v1–v5 plans/identities unchanged.

V6 candidate research still produces the complete frozen batch report. The analysis workflow first exports a development-only capture, then accepts its saved path for validation. This is a staged analysis of existing results, not a claim that validation history was previously unseen or that batch generation was split. Legacy `build_registered_decision()` rejects v6 so callers cannot bypass persistence through the old all-evidence path.

See `odd_lot_decisions.phased_evaluation.evaluate_saved_selection()` and `phased_reporting.export_phased_decision()` / `verify_phased_decision_report()`. They authenticate the saved prefix before validation and preserve the selected candidate on rejection/unavailability. The new schema-2 decision package embeds the source selection capture and publishes immutable `<protocol>/<decision>/<capture>` outputs. Archived packages replay their original prefix; live publication requires unchanged current sources and execution identity. UI/full acceptance and real-data gates remain separate.


## Explicit research scope changes

Changing the traded universe or evaluation dates creates a new frozen study and a new protocol; preserve the original blocked study, reports and protocol. Prepare the desired scope from the original evidence and pass it to `freeze_odd_lot_study`, then bind that study through `protocol_from_studies` with `parent_protocol_id` set to the original protocol. Keep the parent frozen under the same protocol root before publishing its child. The child candidate must reference the new study ID; do not edit the original JSON or remove findings from its report.

Record the concrete scope-change reason, parent study reference and already accessed data in the child's immutable `ProtocolPeriod.access_note`, retaining the appropriate `data_access` and retrospective purpose. A shorter period or removed asset may become ready for that new scope while the original remains blocked. This does not establish an unseen sample or justify selecting a better-looking outcome. Register both protocol versions and inspect the old report again before research execution. These are existing interfaces and a documented explicit workflow, not an automatic semantic check of the human's reason text.

`tests/test_scope_change_lineage.py` executes both source-backed cases: excluding a missing final benchmark day and removing a third trade asset with an unresolved missing quote. It verifies new study/candidate/protocol IDs, parent lineage, reason/access notes, unchanged original bytes, retained blocked status, and false historical holdout flags. Scoped execution evidence is under `artifacts/acceptance/M12-5/scope-change-lineage/`; actual production scope and data gates remain unchanged.
