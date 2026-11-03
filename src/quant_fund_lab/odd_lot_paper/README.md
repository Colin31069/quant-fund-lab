# Odd-lot session state

`types.py` defines immutable boundary state after completed NAV and before the
next close signal. It preserves the original rebalance origin and offset,
passive first-entry flag, stops, pending orders, fractional receivables and trade
settlements. Unknown future trade settlement dates remain session counts.
Negative sell settlements represent fee shortfalls; buy obligations stay positive.
Cash has already reserved buy payments and must not be reduced again in NAV.

`serialization.py` round-trips finite values with canonical JSON and rejects
duplicate object keys. Positions do not claim a cost basis: the current historical
portfolio state has none, and episode accounting uses cumulative business events.

This is L01a work only. No SQLite account, safe resume or single-day execution API
is available yet. Research archives and general PaperLedger must not be passed
off as durable odd-lot accounts. Next: historical-state adapters, input/result
contracts, hand-calculated baselines and extraction of the daily transition.

`bridge.py` now supplies the historical-state adapters. `capture_session_state`
requires the actual completed global index, converts outstanding obligations to
session counts, and preserves settled history. `restore_session_state` creates
fresh mutable historical objects and rebases future obligation indexes to the
new window. A stale unsettled obligation due at/before the checkpoint is rejected.
The loop is not yet wired to these adapters; unit round-trips do not prove daily
execution or persistent resume equivalence.

`closing.py` contains the first extracted execution step: post-open trade
settlement and close valuation. `AccountCloseInput`/`AccountCloseResult` define
its boundary. It copies portfolio and settlement records before processing,
credits positive sale proceeds once, marks fractional receivables, and computes
the unchanged NAV/payable fields. The historical loop now calls this step;
signal generation, corporate actions and order execution still need extraction.
Three fixed-seed strategy outputs were compared field-for-field with a saved
pre-extraction baseline; cash timing and fee shortfalls also have independent
hand-calculated tests. This is not the full session core or durable runner.

`event_prices.py` defines the pure event price transformation contract and is
called by the historical loop for stops/high-close levels and matching reference
prices. Cash dividend subtraction precedes split division. Declared splits cancel
pending buys; unknown event values preserve an invalid matching reference. The
actual cash dividend/split/terminal accounting remains in the original loop and
still needs its own transition extraction and state-equivalence checks.

The subsequent `distributions.py` extraction now handles dividend/split portfolio
accounting through explicit typed inputs/results and is wired into the loop.
It copies state before applying events, preserves the pre-split dividend share
count, and returns event deltas and deferred fractional receivables. The paragraph
above records the earlier price-only boundary; terminal accounting and the full
session orchestration still require extraction. Existing event helpers retain
their original treatment of unknown ratios and source-validation assumptions.

`opening.py` now provides explicit `OpeningExecutionInput`/`Result` for the
opening matching phase, including fresh portfolio/stops/pending state and order,
fill and settlement deltas. It retains sell-before-buy ordering, one-day buy
expiry, 999-share limits, position limits and decision-time risk-budget evidence.
Positive sale proceeds are removed from spendable cash until their T+2 obligation
is settled. `engine_records.py` holds the original mutable stop/order records;
the historical private names remain aliases for compatibility. The historical
loop and checkpoint bridge use the same record definitions.

`signals.py` plans close-time signals from an explicit history ending on the
signal date, using the original rebalance offset rather than a new segment origin.
Stops run daily and take precedence over model exits and entries. Passive ETF
first-entry state persists across calls.

`session.py` now exposes `OddLotSessionInput`/`Result` and
`run_odd_lot_session()`. The historical loop calls it for every signal/next-session
pair. It copies runtime state, plans signals, accrues interest, handles receivable
settlements, distributions and terminal events, executes opening orders, then
settles trades and values NAV. Result events are deltas; runtime keeps the full
settlement history. Models receive only history through the signal date.

Daily serialized checkpoint round-trips have been compared with uninterrupted
execution on a fixed synthetic fixture, and all three historical strategy outputs
remain exactly equal to a saved baseline from before extraction. Broader corporate
action/fault/resume matrices and durable SQLite transactions remain pending. These
functions do not validate a live account's source/config prefix or authorize use
of blocked research inputs; the future durable preflight must enforce those gates.

`ledger.py` now supplies a dedicated `odd_lot_checkpoint_v1` SQLite store with
typed `SessionCommit`. Explicit creation refuses existing paths; opening refuses
missing accounts or changed locked configuration. Each transaction saves state,
grouped business events and a chained completion digest. Replaying identical
commits is a verified no-op, and failures after checkpoint/event insertion roll
back all rows. Structural/digest checks detect changed events and broken chains;
they are not independent accounting reconciliation or external authenticity.

The store is not yet a durable runner: callers must supply validated inputs and
finite canonical event JSON. Market-data/signal prefix validation, snapshot
linkage, an event encoder, full account replay, independent accounting audit and
UI remain pending. General ledgers and study archives remain incompatible.

`replay.py` now implements internal `_replay_account` mechanics over complete
historical input panels. A typed `ReplayIdentity` locks protocol, execution,
calendar and origin alongside all research/execution settings. A chained digest
includes every input bar from warmup through each completed session. Completed
history/config changes are rejected before adding days, including no-new-day calls.
The replay restores the latest checkpoint, runs the shared daily core, encodes
event deltas and commits atomically. Whole-run and segmented/reopened SQLite
tables are identical, and injected commit failures can be retried exactly.

`event_codec.py` encodes scalar kinds explicitly so NaN/NA/NaT markers are not
silently converted to zero, floats retain their exact bits, and timestamps retain
their values. These are business-record missing markers, not valid market prices.
`strategy.py` colocates the existing targets and sizing helpers; the historical
helper names remain lookup-compatible for existing callers and test injection.

The internal replay is not a public account activation path. Frozen-study
readiness authentication, actual execution identity checks, external snapshots,
independent accounting audit, concurrency/input-mutation preflight and UI still
require integration. The identity strings alone do not certify those conditions.

`audit.py` independently reconstructs cash, quantities, trade settlement history,
fractional rights and NAV from stored events and explicit valuation marks. It uses
no execution functions and opens external accounts read-only. The internal replay
checks existing history before writing and runs this audit inside each day's SQL
transaction before commit; failed reconstruction rolls the entire day back.
The transition revision is now `odd_lot_session_v2_marks`, so older accounts
without valuation evidence cannot silently resume under the new audit contract.

Audit scope remains financial: stop/pending policy reconstruction, independent
fee-rate recomputation, source authenticity and snapshot linkage are not yet
certified. It detects coordinated cash/NAV edits even after recomputing digests,
but does not claim protection against every coordinated source/event alteration.

`audit_fees.py` now independently recomputes commission minima, per-instrument
sale tax and component rounding from locked research assumptions, without calling
the execution/cost helpers. The financial audit also checks fill/order quantities,
opening references, local/base amounts and recorded slippage, and binds dividend
withholding to the locked account rate. Stop/pending reconstruction and full
execution-price feasibility remain separate unfinished audit scopes.

`snapshots.py` publishes content-addressed market snapshots in immutable directories.
Each linked manifest is hash-locked, payload filenames are constrained, symlinks
are refused, all parquet hashes and the decoded logical input identity are checked.
Internal replay can require a locked snapshot root, stores a link in each committed
session, and validates old snapshot prefixes against SQL input fingerprints before
new work, including no-new-day calls. Snapshot files sit outside the SQL transaction;
rollback may leave an unreferenced payload, which is not a completed account day.

The transaction validator rechecks current input-prefix values and the latest
snapshot before committing. This detects input mutation during event insertion.
Snapshot provenance links have their own verifier and are not decoded as financial
events. Delta-only reconstruction and public frozen-study activation still remain
pending; the optional snapshot argument currently belongs to the internal API.

`workflow.py` adds `replay_registered_account` for a declared historical candidate,
strategy and period. It authenticates the executing checkout/runtime identity,
protocol binding, source-backed frozen study and readiness before account writes,
requires snapshots, revalidates sources during SQL stages and rejects forward
observation use. It is historical virtual replay, not the still-pending dedicated
forward-activation workflow; changed source data requires a new declared identity.

`history.py` provides read-only `reconstruct_account_history` for delta input. It
loads the latest committed snapshot link from the locked snapshot root, retains
only bars through the last committed date, validates overlapping historical rows,
and appends incoming panels with matching market/schema identity. The replay
runner still verifies all completed prefixes before committing. Initial-only
accounts with no committed snapshot require complete history. Snapshot pandas
frequency hints are not business data; actual session timestamps/values remain
fully checked. Public registered historical replay still uses its frozen study,
so delta reconstruction currently serves the internal replay workflow.

`audit_risk.py` adds an independent recorded-risk lifecycle check: previous
checkpoint stops trail on observed closes, dividend/split price transformations
retain their ordering, stop triggers preserve SELL retries, terminal/full exits
remove state, and entry fills carry their decision-time stops/budget. Pending
orders, terminated symbols and first-entry flags must match the reconstructed
result. It calls no signal/matching/session functions; alpha target weights and
model scores remain supplied signal evidence rather than independently recalculated
models. Market authenticity remains the separate source/snapshot scope.

Replay now records `risk_inputs` and uses transition revision
`odd_lot_session_v3_risk`. Earlier internal accounts cannot silently adopt missing
risk evidence. Hash-coherent stop/pending/flag changes are rejected by reconstruction
before resume, including no-new-day calls. Broader event/entry/exit matrices and
forward-observation activation remain subject to their own acceptance gates.

`inspection.py` opens the dedicated ledger read-only, verifies the structural chain,
and returns the shared financial/risk audit, last checkpoint and event counts.
Its source status explicitly states that snapshot/raw-source authentication is
not part of read-only inspection; executing replay performs that preflight.

The main Streamlit sidebar now exposes `零股持久化歷史帳戶`, rendering `ui.py` in
this package. Inspection is an explicit submit action. Historical replay requires
protocol/candidate/period/strategy, account and snapshot paths, and optional cutoff.
Safe continuation is the default; creation is a separate explicit choice and the
backend rejects existing paths. Failed operations never switch to creation, and
rerendering does not resubmit them. No reset/delete or forward-activation action is
exposed. This historical UI does not complete the separate forward-observation gate.

`source_checks.py` binds stored risk-input and valuation events exactly to the
fingerprint-verified market panels before resume and before commit. Recorded signal
dates/prices must match their prior-close inputs; active entry stop levels are
independently recomputed from the frozen volatility window/multiplier/bounds.
This rejects internally coherent event edits that otherwise leave financial/risk
equations unchanged. It does not independently regenerate alpha scores or target
weights, nor supply missing external evidence for blocked real studies.

`observation.py` defines a separate immutable `ObservationPlan` for future intent.
Registration reconstructs a real v6 phased decision, requires a continuing fixed
choice, checks current experiment history and actual execution identity, and locks
the selected settings, decision manifest, actual registration time and a strictly
future Taipei date. Atomic publication rechecks those sources. The access note
preserves prior historical exposure; an old validation period is never relabeled
as unseen. The requested date is still subject to the future calendar/data gate.

Registration publishes `registered_pending_verified_session` only. It creates no
SQLite account and no performance series. Verified new-session readiness, external
data acquisition timestamps, first-session activation and the forward UI remain
separate implementation and acceptance work. Hash readback detects altered plan
content but is not a substitute for authenticating its decision when activating.

`observation_auth.py` reconstructs the referenced phased decision, checks its exact
manifest and current experiment prefix, and binds the registered candidate,
strategy, settings, selection and execution identity. It also checks chronology
against protocol declaration and decision publication. This is read-only; a
coherently rehashed plan edit must still match the original decision.

`observation_evidence.py` defines `SessionEvidence` and `ForwardSessionAssessment`.
`observation_gate.py` rebuilds official or explicitly selected provider inputs
from raw sources, evaluates the full planned prefix with the shared readiness
and effective-calendar code, and binds all source hashes. Every forward session
and symbol (including the benchmark) needs a source acquisition record after
registration and on/after the price date, with no future acquisition timestamp.
Missing sessions, warmup, coverage or boundary calendar evidence remain blocked.
Readiness authenticates official suspension valuation where a price row is absent.
Provider archives may include later rows, but returned execution panels are copied
and clipped to the requested cutoff before assessment. Acquisition evidence covers
only the planned prefix. Source hashes retain the complete original archive chain.

These are local manifest acquisition records, not independent trusted timestamps
or proof of historical publication/revision times. No filesystem mtime is used.
The gate does not authenticate a plan by itself, create a snapshot/account or
enable forward trading; activation must combine authentication with this gate and
transaction-time checks. The forward activation workflow and UI are still pending.

`source_archive.py` now preserves the complete original source inventory in
content-addressed directories. `SourceArchiveLink` binds the archive manifest;
readback rejects missing/extra paths, symlinks and changed bytes. New monthly
responses/reviews create a new archive, retaining previously referenced originals.
Publication rechecks copied inputs and never repairs a changed archive. SQL rollback
may leave an unreferenced archive, which does not count as a completed session.

`forward_binding.py` connects the immutable plan and source capture to replay.
The account configuration locks the plan ID, archive root, symbols and provider
selection rule; research/execution settings must match the registered candidate.
Every session records encoded observation evidence in the same transaction as
business events/checkpoint/completion. Before commit and resume, archived raw
inputs must reconstruct readiness/acquisitions and the committed input prefix.
The existing normalized snapshot and independent financial/risk audit also run.

`forward_workflow.py` adds `run_observation_account` with pending/blocked/active
results. It authenticates the original decision/code and candidate source mode,
assesses the requested new-data prefix, archives originals and calls the shared
replay core. A trailing gap may complete only an earlier wholly ready prefix;
missing middle sessions are never skipped. Before the planned date it creates no
account; it never converts a historical account or resets an existing path.
Plan/decision and current raw hashes are rechecked at transaction stages.

The public workflow is under dedicated integration acceptance; forward UI and the
full operational matrix remain pending. Positive tests explicitly simulate future
time/data using offline fixtures. No real future observation, strategy-validity
claim or broker operation follows from those tests. Calendar/rule/runtime changes
remain identity changes requiring explicit handling rather than silent migration.

`forward_ui.py` now exposes explicit registration, plan readback and virtual-account
activation/continuation through the main sidebar's `零股前向虛擬觀察` entry.
Continuation is the default; creating an account is an explicit separate choice.
The UI reports pending/blocked/active from the shared backend and last completed
session, including a partially completed ready prefix. Form rerenders do not
register plans or submit sessions. Readback checks the plan hash only and says so;
execution performs full decision/source/snapshot authentication. There is no
automatic reset or broker integration. The earlier UI-pending paragraphs preserve
their original implementation stage; final full-case acceptance remains separate.

Forward daily bars also require acquisition at/after the session close from the
frozen `exchange-calendars` XTAI profile. A same-date morning timestamp cannot
certify a completed daily bar. The evidence-reviewed session list remains the
calendar gate; the provider schedule supplies the close time for each accepted
session. Runtime/calendar changes retain their existing identity guards.

Durable acceptance now includes independent hand calculations across real SQL
restart boundaries: dividend before reverse split, deferred fractional cash,
post-open T+2 sale proceeds, negative sale settlements caused by minimum fees,
999-share partial-entry expiry without top-up, and stop SELL retry across an
unquoted opening. Event-day failure after event insertion rolls back the entire
day; explicit retry matches uninterrupted business state/events/input digests.
Source-backed provenance remains a separate acceptance scope from these offline
fixtures, and each snapshot link retains its actual full/prefix capture identity.

`rebuild.py` adds `rebuild_registered_account` for explicit historical rebuild
into a different, previously absent path. It preserves the parent, verifies its
structural/financial state and then authenticates its original source/snapshot
prefix through read-only replay. Candidate settings, frozen execution and period
origin must match. Missing/unknown/corrupt parents, missing snapshots and forward
observation accounts refuse conversion. A parent must have a completed session.
The parent file/WAL hashes are checked again at every new-day transaction stage;
an external parent change rolls back that day. Returned parent hash/digest/path
references are displayed, while the new account resumes independently from its
frozen sources. The product never undoes external changes or repairs the parent.

Historical UI offers `保留原帳戶並重建至新路徑` with a separate required target
field. Safe continuation remains the default ordinary operation. Rebuild failure
does not reset either path or retry as ordinary creation; rerender does not repeat
the action. Internal read-only replay opens SQLite mode=ro and refuses creation
or processing beyond the completed prefix, including when newer input is supplied.

Forward resume also compares every completed full-universe input prefix, including
the benchmark, against the incoming source capture. An archive remaining internally
valid does not allow incoming past benchmark prices or volume to change unnoticed.
The trading-only financial input digest keeps its existing meaning; the separate
full-universe comparison covers benchmark provenance and warmup. Changes strictly
after the last completed session may form new input evidence and continue normally.


Unsupported-account safety is verified with actual `PaperLedger` and research archive SQLite schemas, an explicitly unsupported checkpoint-kind fixture, and an empty SQLite file. Inspection, internal resume and historical rebuild all refuse these formats without migration, source-file changes or creation of a rebuild target. The real account UI keeps safe continuation as its default and displays read/rebuild errors; rerender does not repeat either action. Supported checkpoint accounts use their separate read-only inspection and authenticated source/snapshot continuation gates. These offline tests do not certify an automatic migration or actual forward observation. Execution records are in `artifacts/acceptance/M14/legacy-account-operations/`.
# Optional rights-aware opening capacity

`OddLotSessionInput.sale_limits` accepts explicit `OpeningSaleLimits` for the
actual opening session and every post-event owned identity. Quantities must be
canonical nonnegative integers no greater than actual holdings. The opening
phase limits SELL fills while retaining all owned shares for valuation and
preserving partial/blocked exit retries. Orders retain requested/filled/expired
quantities and disclose `not_tradable` or `tradability_limited` when applicable.
The independent session cash/holding verifier rechecks fill capacity. With None,
the legacy path is unchanged. The rights adapter must supply authenticated
post-corporate-action lot capacities; this does not activate a new SQL schema or
admit real unsupported issuer events. See the adjacent rights README for scope.

