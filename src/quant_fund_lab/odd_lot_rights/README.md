# Corporate-rights accounting core

## Registered source-backed historical admission (2026-10-30)

`registered_source.authenticate_registered_catalog` reads the original frozen
StudyProtocol, enforced-readonly ExperimentRegistry and verified raw-backed
candidate study. It checks the executing package/source identity, catalog
protocol/execution/calendar pins, ready historical period, exact candidate
research/engine settings, clean initial cash account, full market frames,
prior liquidity, signal origin and request session bounds. Sources, registry,
protocol and execution identity are checked again before returning. Missing
registries are rejected without initialization. Historical/exploratory labels
remain those declared in the original protocol.

`registered_catalog_workflow.commit_registered_catalog_day` calls those actual
source gates before catalog admission and at SQL fault boundaries, so a raw
source change before commit rolls back the complete account day. The matching
readonly verifier combines source authentication with catalog/history replay.

Existing StudyProtocol plans do not declare the new rights policy/mark adapters.
This first historical entry therefore admits no selected rights elections,
after-close rights commands, new-identity stops, conversion risk mappings or
rights marks. Valid checksums and a ready price study cannot authorize those
unknowns. An authenticated rights supplement/issuer adapter remains required
for their eventual admission. This guard is not a substitute for completing
that integration. Future/unseen periods are refused here and must use the
separate forward-observation decision/registration/acquisition workflow.

The tests use an actual native ready-study/protocol/registry fixture and direct
SQL admission, plus source/registry/settings/calendar/command/forward refusals.
They establish local source binding, not that any real event is research-ready,
that the fixture is an unseen sample, or that the latest code passes all release
and native-compatibility gates.

## Ledger-bound request catalog revisions (2026-10-30)

`request_catalog.RightsRequestCatalog` fixes the complete ledger configuration
and initial combined checkpoint. Each ordered RequestCatalogEntry identifies
its session, original archive checksum, day-input fingerprint and predecessor
checkpoint checksum. `append_request_catalog` fully prepares the supplied day
against its predecessor before creating a one-entry revision. The revision
retains every previous entry and points to its parent's content identity;
`verify_catalog_extension` rejects root/configuration/prefix rewrites.

`request_catalog_files.freeze_request_catalog` exclusively publishes a root or
verified single-entry extension, preserving previous bytes. Loading requires
the externally retained catalog checksum. The checksum binds all six ledger
identities and full initial state; it does not prove reviewer approval, official
source truth, actual prior publication or a registered study protocol. The
ledger's protocol/execution/calendar digests remain externally supplied anchors.

`catalog_workflow.verify_catalog_ledger` compares the catalog with the actual
ledger root and every completed source/predecessor, then replays that entire
completed prefix from pinned archives. `commit_catalog_day` permits exactly one
pending next entry and rechecks all catalog archive bytes at SQL fault boundaries.
When every listed session is complete, another invocation performs full checking
and returns None without adding a day. A stale catalog cannot omit committed
history. Tests freeze/reopen seven catalog revisions through the receipt
lifecycle and reject changed configuration, historical inputs, predecessor,
archive bytes, invalid parent publication and midcommit prior-archive mutation.

This local catalog is the handoff boundary for a later authenticated protocol/
review registry and UI. Its complete source frames retain the earlier explicit
frame-extension limit; incremental future-observation admission is not implied.

## Portable original daily requests (2026-10-30)

`day_request_codec.py` archives the complete predecessor engine state, full
authorized account, supplied market frames and liquidity, engine/research
settings, commands, clocks, corporate events, conversion risk mappings and marks.
Its closed typed-value registry in `request_values_codec.py` never imports types
named by an input document. Decimal strings, float scalar kinds, missing values,
datetime-index metadata and supported frame dtypes survive canonical round trips.
Unknown fields/types/versions, duplicate JSON keys and unsupported dtypes fail.
This first portable schema deliberately limits frame dtypes to explicit supported
numeric, bool, object and naive datetime64 values; it does not silently cast an
unsupported source format. Loading does not authorize a command's execution.

`day_request_archive.archive_day_request` validates reconstruction, flushes a
temporary sibling and exclusively publishes a checksum-named file. Existing
bytes are verified and preserved; partial temporary writes never become the
final archive. Symlink paths are refused. `load_day_archive` requires an
externally retained expected checksum, checks bytes before/after decoding, and
returns fresh objects. The archive cannot authenticate its own provenance.

`commit_archived_day` consumes that loaded request through the public atomic
workflow and rechecks original archive bytes at every SQL fault boundary.
`verify_archived_days` loads a complete externally pinned catalog and performs
read-only historical replay, then rechecks the files. Tests discard original
day objects, reload seven daily requests, restart the SQL account each day and
verify the complete receipt lifecycle. Changed but valid payloads still fail
the original checksum; midcommit archive replacement rolls back the whole day.

Reviewed catalog registration/identity, official source and historical
availability authentication, archive retention/sharing UI, incremental frame
extension semantics and final-source release gates remain required. JSON
canonicality and checksums do not prove an issuer event or unobserved holdout.

## Durable day execution and external-input replay (2026-10-30)

`durable_day_workflow.commit_rights_day` connects the common day workflow and
explicit joined NAV to RightsEngineLedger. It requires the entire prior engine
checkpoint (including stops, exits, obligations and fractional receivables) and
AuthorizedRightsAccount to match the verified SQL predecessor. Locked settings
bind engine/research assumptions and lot rounding policy. Each commit fingerprints
all supplied market frames, prior liquidity, commands, processing clocks, mappings
and marks, and stores real business events, NAV and workflow details with the
combined checkpoint/completion in the existing atomic transaction. Inputs are
checked again after execution and at each write fault boundary before commit.

This first contract binds the complete supplied market frame, including supplied
future rows. Extending that frame is not silently permitted as equivalent old
input; incremental prefix semantics require a separate reviewed contract.
Source hashes do not authenticate issuer facts, historical availability or the
external execution/calendar/protocol identities pinned by ledger configuration.

`durable_day_audit.verify_durable_days` reads every completed SQL session and
re-executes the supplied original external request catalog, comparing full
checkpoint, input identity, event/NAV payload and digest. A rehashed altered NAV
can pass storage integrity but fails this check. This is behavior replay using
the common engine, with independent financial/lot equations underneath; it is
not an independently implemented execution engine or source authentication.
The caller must preserve and authenticate the original request/source catalog.
Historical replay is read-only; the commit entry advances the latest state.

Tests run actual parent/receipt/final trading through seven SQL days, restarting
from the stored checkpoint each day, and verify no early T+2 spending or lost
conversion exit. Payment/delivery failures at four SQL phases roll back on both
RuntimeError and KeyboardInterrupt. Changed settings, prior stop, source volume,
marks, missing history and precommit source mutation are rejected. Automatic
input archive loading, independent durable risk/NAV auditing, UI/registration,
pre-opening rights phases and real-event admission remain separate gates.

## Ordered day entry and receipt risk transfer (2026-10-30)

`day_workflow.advance_rights_day` composes actual lot-aware engine execution,
joined inventory posting, typed `RightsCloseCommand` operations and the next
immutable engine projection. It carries AuthorizedRightsAccount, including the
full frozen instruction catalog and archived original authorizations. A command
batch must be uniquely identified, ordered and on the same date after the latest
recorded engine close. Grant, revision, payment, delivery, conversion, evidenced
fraction payout and unpaid expiry reuse their existing transitions/audits.
No partial batch or day value is returned on failure. This is a pure after-close
phase: it cannot model an earlier bank deadline or replace required pre-opening
ownership qualification. Durable source binding and SQL atomicity remain gates.

`conversion_risk.ReceiptRiskTransfer` explicitly maps a recorded conversion
after the current engine anchor to final-security risk and pending exit state.
New identity prices/stops are supplied explicitly, never copied from the receipt.
Under the declared carry_receipt_exit priority, an outstanding receipt SELL keeps
its reason and covers actual final holdings; it replaces a competing final BUY.
A partial conversion retains a resized receipt exit and its receipt stop for
remaining receipt units. Removing a receipt BUY needs explicit cancellation.
Missing/mismatched mappings, stale conversion anchors and chained mappings in
one projection are rejected. The outer frozen policy must authorize this mapping.

Hypothetical distinct parent/receipt/final fixtures pay50 for five claims,
deliver two free and three locked receipts, actually sell only two receipts,
convert only the remaining three and keep the final exit pending until release.
The final three shares actually sell later; separate T+2 receipts produce cash
50/250/250/550 and explicit NAV1050 throughout. Daily restart and uninterrupted
paths agree. The common day entry matches the independently staged operations,
and same-day replay preserves the original authorization archive and inventory.

## Joined corporate-lot session posting (2026-10-30)

`lot_flow.run_and_post_lot_session` now executes the real projected opening,
then returns the resulting engine session and a single posted RightsInventory.
The new portfolio_lot_session command records original lots, explicit corporate
events and rounding policy, actual fill price/gross/fees, and final lots. Whole
lot replacement postings preserve each remaining right key and release date;
corporate transformations may remove locked ownership, while fills consume only
currently released lots. Cash is the reconciled engine close, never a second
accumulator. Failed execution/reconstruction does not mutate the caller.

`lot_flow_audit.py` reconstructs event and fill quantities without calling the
posting or lot-transition functions, checks fill gross/cash equations, and uses
the established independent session cash-component audit. Inventory replay also
compares every journal's initial lots with its reconstructed account prefix.
Both legacy portfolio_session and new portfolio_lot_session are recognized by
following-session projection and joined NAV. The legacy posting API is retained.

Replaying a completed lot session requires its original recorded account prefix;
that prefix must match completed receipts, initial anchors and posting history.
The original engine inputs are re-executed, changed output/payload is refused,
and a valid replay preserves the latest account bytes even after later sessions.
The outer workflow must authenticate the archived prefix and underlying inputs.

Direct fixtures cover split/reverse-split locked exits, terminal removal,
T+2 cash, canonical policy payment, next-session cash projection, actual buying
and explicit joined NAV, with restart and rehashed journal counterexamples.
These are local pure APIs. Automatic command-phase orchestration, the complete
delivery/conversion lifecycle, independent durable checkpoint reconstruction,
versioned SQL/UI integration and real issuer source admission remain gates.

## Canonical authorization application (2026-10-30)

`apply_authorized_subscription` now routes new authorized payments through the
shared `elect_subscription` operation. The single resulting policy_election
receipt stores the canonical participation semantics, actual elected requests
and daily cutoffs; its policy name binds the SHA of the entire frozen
RightsSessionPolicy, including later predeclared actions. Changing an unexecuted
instruction after the first payment therefore changes the account policy and
is rejected. Both authorization and direct participation APIs share that same
receipt, cash and independent audit path. They do not authorize two payments.

Replay retains the original-authorization requirement and the canonical command
payload guard. Earlier bare subscribe receipts remain byte-preserving no-ops
when the caller supplies their authenticated unchanged original authorization;
they are never rewritten or upgraded silently. A payable interval must have
positive duration, aligning both authorization and canonical cutoff contracts.

The older paragraphs below describe the original separate authorization
boundary. New canonical receipts now provide local policy binding, while
authentication of source facts, historical policy freeze and the original
authorization, plus atomic workflow/SQL integration, remain required.

## Corporate lots before opening execution (2026-10-30)

`lot_events.py` declares typed split/terminal events and an explicit
`LotRoundingPolicy`. `opening_lots.project_opening_lots` audits the prior account,
checks the declared event clock, and preserves each original lot's release date
on its whole transformed units. Under the supported conservative policy,
residual whole units pooled across fractional contributors receive the latest
contributor's release date. Per-lot fractions and aggregate unconverted
fractions remain exact disclosures; this projection never invents cash proceeds.
This policy is an engineering choice requiring explicit research agreement,
not evidence of issuer pooling rules. Receipt conversion retains its separate
verified ownership contract.

`lot_session.run_lot_projected_session` checks the real engine cash/holdings
anchor, event symbols, split ratios, terminal presence and supplied limits,
then calls the shared session with transformed sale caps. Zero and one in the
market split series mean no split. Exact Decimal whole counts must agree with
the engine's floating-point boundary; ambiguous rounding is rejected before
execution. The actual corporate-action result is checked against projected
post-event ownership. Unlocked transformed units can sell while locked units
retain ownership, stop state and exit retry. Terminal events consume locked
ownership as corporate actions rather than executable sales.

The account, engine input and original lots are unchanged. The returned
`ProjectedLotSession` is a plan/result pair; it is not a posted inventory or a
durable checkpoint. The old `post_engine_session` cannot record all these
corporate lot transformations. The outer workflow still must authenticate
sources and the supplied opening clock and atomically record events, fills,
cash, lots and rights in a versioned format. No real issuer event is enabled.

## Explicit payment policy and cutoff boundary (2026-10-30)

`session_policy.py` defines immutable `SubscriptionElection`,
`RightsSessionPolicy` and `PaymentInterval` contracts. A version-one policy
contains explicitly selected, canonically ordered atomic batches, exact terms,
quantities and fees, a Taipei clock and its freeze time. Unlisted actions are
declined regardless of available cash. Terms unavailable at policy freeze are
rejected. Each leg needs an evidenced same-day payment interval; date-only
payment terms cannot establish a bank cutoff. Interval endpoints are inclusive.

`payment_authorization.authorize_subscription` validates the complete election,
policy availability, interval availability and intraday clock before returning a
typed authorization. `apply_authorized_subscription` invokes the existing
atomic cash transition. A completed later book clock cannot be backdated into an
earlier payment interval, and insufficient usable cash rejects the whole batch.
Retry requires the original unchanged authorization in addition to the core
receipt; policy and interval changes alter the authorization identity.

This API is an explicit boundary, not automatic durable workflow activation.
The outer workflow must authenticate the recorded original authorization and
source evidence, then atomically persist the authorization with the resulting
book and inventory. The existing book codec alone cannot prove policy binding.
Trade-versus-payment scheduling, source-backed bank availability, continuous
session orchestration and versioned SQL remain later integration requirements.
The tests use hypothetical terms; real 2881/2882 admission is unchanged.

## Latest session-flow and projection boundary (2026-10-30)

Registered-protocol admission follow-up: `protocol_admission` checks the actual
frozen StudyProtocol against an existing read-only ExperimentRegistry, the
catalog protocol ID, current executing checkout/runtime identity, declared
calendar-revision digest, selected candidate and historical period. Each
archived request must match its listed input/settings/session, the frozen
research and derived engine configuration, declared universe and period.
`commit_protocol_catalog_day` invokes that check before the common catalog
workflow and again at SQL boundaries; changed protocol envelope bytes or
registered/code bindings roll back the day. All-complete catalogs remain no-op.
This explicit historical entry refuses forward_observation periods. It does
not establish issuer/source truth, preregistration timing, readiness, a valid
continue decision or authority for real forward activity. Calendar identity is
the local SHA of canonical revision-list content, not a second exchange-source
certification. Existing low-level storage/catalog APIs retain their documented
scope; automatic UI admission still needs this explicit binding and source gates.

Inspection follow-up: the common `verify_archived_days` entry now always runs
independent persisted NAV and risk equations before production history replay.
Catalog prefix verification inherits those gates. `inspect_rights_catalog`
loads an externally checksum-pinned catalog, opens an existing regular account
read-only and returns completed/pending counts, cash, NAV and holdings only
after all checks. It never initializes a missing account or migrates a format.
The main Streamlit app exposes an opt-in “權利事件帳戶唯讀核驗” form that calls
this backend only on explicit submission; rerender performs no read/replay or
write action. Local archive integrity remains distinct from historical source,
protocol registration and actual forward admission. No creation or commit action
is exposed by this inspection form.

Independent risk follow-up: `day_risk_audit` reuses the independent engine
stop/pending equations, then separately reconstructs declared post-close receipt
conversion risk and new-held stop assignments. It never calls production signal
planning or conversion-risk transfer. The durable preparation gate rejects a
lost/changed exit, stop drift or changed retained obligations before SQL writes.
New records retain the pre-rights engine-close checkpoint in `risk_audit` events.
`persisted_risk_audit` uses that state, stored business signals/fills/actions and
external original observations/mappings to independently check each completed
day without production workflow replay. Rehashed final stop drift still fails
even when financial quantities and the storage chain remain valid. Old records
without the required risk evidence fail this audit as insufficient; no repair
or migration is implied. Alpha targets and new-instrument risk levels remain
declared inputs requiring policy/source authentication, not independently
estimated strategy quality.

Independent NAV follow-up: `checkpoint_nav_audit.audit_checkpoint_nav` rebuilds
each cash, held-security, unpaid/pending-right, sale/fractional receivable and
reserved-payable disclosure from the combined checkpoint, original session link
and external marks. It does not call production engine or valuation functions.
`prepare_durable_day` invokes it before a commit can be prepared, so coordinated
errors in the production NAV and a component are rejected before SQL mutation.
`persisted_nav_audit.verify_persisted_nav` applies the equations to recorded SQL
NAV against external original day marks without production workflow replay.
Rehashing an incorrect NAV preserves storage integrity but still fails this
read-only business audit. Market/source authenticity, policy registration and
full risk/execution replay remain distinct gates; these equations cannot prove
that a coherent substituted external price catalog is historically true.

Combined engine SQL follow-up: `RightsEngineCheckpoint` binds the complete
authorized account to the engine's current cash, owned shares and completed
session, preserving settlement/receivable and stop/pending state. Its separate
canonical codec keeps both existing component encodings intact. New
`RightsEngineLedger` uses `rights_engine_checkpoint_v1`, distinct tables and
explicit externally supplied `RightsLedgerConfig`. That config pins the exact
initial checkpoint, full policy, execution, calendar, settings and protocol.
Existing files of another format are refused without migration or rewriting.

Each commit places state, grouped events (including supplied engine/rights NAV
records) and the completed-session digest in one SQLite transaction. History
prefixes and origin/offset must remain intact. Identical replay is a verified
no-op; changed completion data or stale parents fail. BaseException at state,
event, completion and precommit boundaries rolls back the whole day. A source/
business validator can reject before commit; final verification also prevents
that callback from silently replacing and rehashing the submitted record.
Read-only loading performs no account initialization or writes.

This is a storage API, exercised using actual copied engine/T+2/election states,
not a source-authenticated automatic workflow or UI. The stored event hash and
checkpoint equality do not independently prove every NAV mark, risk transition,
source prefix or historical registration. Those audits must be connected to
the precommit gate before real activation; initial/config identities must come
from trusted external records. The old odd_lot_checkpoint_v1 store is unchanged.

Full authorization archive follow-up: `authorization_archive.py` joins the
audited `RightsInventory`, complete frozen `RightsSessionPolicy` and every
original `PaymentAuthorization` in one immutable `AuthorizedRightsAccount`.
`apply_account_authorization` returns inventory and archive together, or neither;
replays read the stored original authorization. `record_account_decline` can
record an unlisted nonparticipation choice without consuming claims, but cannot
override a frozen selected payment or assert an irreversible legal waiver.

`authorization_archive_codec.py` round-trips the complete catalog, including
unexecuted choices, exact terms/fees and daily intervals, alongside the original
inventory encoding. The independent archive verifier checks every catalog term
at policy freezing, every executed batch/window against its original receipt,
and exact authorization/payment coverage without production constructors or
payment functions. Coherent replacement of an unused instruction still fails
the recorded policy SHA binding. Legacy bare receipts can be archived without
rewriting their original inventory bytes when their complete original
authorization is explicitly supplied. Supplied history is not authenticated by
this operation. SQL transaction integration, registered-policy/source anchors,
continuous workflow, UI and actual issuer/forward acceptance remain pending.

Participation follow-up: `RightsParticipationPolicy` binds explicit election or
decline-only mode, full-batch cash failure, evidenced fractional handling,
explicit current marks, already-usable cash and an inclusive/exclusive cutoff.
`PaymentCutoff` records a disclosed daily payable interval for each elected leg.
`elect_subscription` requires an explicit pay/decline decision and records the
whole policy, policy ID, requests and windows in one original `policy_election`
receipt. Late processing and backdating fail. Declining does not expire unpaid
rights or consume already paid claims. The first policy ID binds later elections
in that account; independently audited posting rejects a changed policy or a
later bare legacy payment that bypasses it. Legacy histories before activation
keep their existing command representation.

`payment_policy_audit.py` reconstructs policy authorization independently of
production constructors/election/payment functions, before the existing cash
equations run. Rehashed unsupported rules, changed later policy IDs or invalid
cutoffs still fail. Exact local Decimal arithmetic survives low caller precision.
Policy `frozen_at` and cutoff evidence are supplied knowledge assertions, not
proof of historical registration or official bank/issuer publication. Prior
registered-protocol binding and authenticated daily payment windows remain
required before a real workflow may use these commands. No automatic election,
prorating, funding from future receipts or actual issuer activation is implied.

The adjacent `RightsSessionPolicy`/`PaymentAuthorization` API separately freezes
the actual action IDs and complete elected batches before authorization. The
new receipt API binds participation semantics and records the exact batch at
execution; it does not replace that earlier frozen-choice contract. A combined
workflow must bind the original authorization to the persisted policy receipt
and independently reconstruct it. Until that bridge is implemented, these APIs
remain explicitly scoped building blocks, not interchangeable guarantees.

NAV follow-up: `session_nav.value_session_nav` joins a recorded actual engine
close with the current same-day rights inventory and explicit security/claim
marks. Its typed `RightsSessionNAV` counts cash, held assets, unpaid rights,
pending claims, unsettled positive sales and fractional receivables once each.
Buy reservations and fee-shortfall payables are disclosures, not second NAV
deductions. Later rights payments/deliveries may change cash/holdings; the
pre-command engine equity remains a separately reconstructed baseline.
The API checks the latest session anchor, baseline equity, fractional marks,
current market-security quotes and TWD currency. New receipt/final identities
need their own explicit marks, including when held units are not yet tradable.
It refuses missing/future/stale marks and never rewrites the old engine result.
This is a pure joined-NAV API, not automatic durable/UI integration or a proof
of the economic truth of external marks. Frozen valuation policy, source
authentication and independent persisted NAV reconstruction remain required.

Opening-capacity follow-up: `execution_capacity.opening_sale_limits` evaluates
audited post-event lots at the actual opening date. The optional typed
`OpeningSaleLimits` now reaches the real shared session/opening executor, keeping
owned shares in NAV while limiting SELL fills. Locked exit quantities expire
for the day, with the stop/pending exit retained for retry. A later release is
re-evaluated at that later opening. The independent session link also rejects
fills above declared limits, and inventory reconstruction rejects archived
debits before the original lot's release. The default None preserves legacy
outputs. These hooks are not yet automatically orchestrated by the durable
workflow; pre-opening corporate-action lot transformation remains required.
The following paragraphs retain the earlier projection delivery boundaries.

The historical descriptions below retain the original delivery scope. The newer
`post_engine_session` now posts reconciled real engine closes into the joined
inventory, with original commands, exact usable cash, inventory movements and
independent reconstruction. Duplicate session identities and changed replay
payloads fail. T+2 receipts become spendable only at the actual credited close.
The existing durable workflow does not automatically invoke this adapter yet.

`session_projection.py` adds the reverse boundary: `project_rights_session`
checks the last recorded engine close against supplied runtime cash/holdings,
then builds an immutable session checkpoint with current rights cash and owned
shares. Existing settlement/receivable, pending-order and risk history is
retained. Newly held security identities require explicit typed stop states;
parent stops are never silently copied to another instrument. Projection refuses
future rights knowledge, stale anchors, terminated identities and lossy
Decimal-to-float cash conversion. It neither authenticates supplied source terms
nor independently proves runtime risk/settlement history.

The projection separately reports current tradable units while keeping every
owned share in the checkpoint for valuation. Restoring the checkpoint alone
does not enforce those sale limits: the next execution adapter must consume
them before admitting locked lots to a running workflow. Real following-session
tests currently cover payment and already-tradable delivery, not partial sales
from mixed locked/unlocked lots, rights-aware NAV or versioned SQL atomicity.
The signal-session projection uses only that completed day's known state;
future release dates must be evaluated afresh by the next opening adapter.

Participation, same-day payment cutoffs, new-instrument prices, risk policy,
source authentication, continuous orchestration and durable versioning remain
explicit integration gates. Real 2881/2882 events remain unsupported.

This package is the first E05 accounting delivery. Its rights transitions are not yet called by the
historical runner, readiness normalizer, or durable account workflow. Real issuer
events remain unsupported until their facts, adapters and integration pass their
own gates. No brokerage interfaces or real orders are involved.

The existing shared historical/durable session now invokes only the independent
`session_link.py` cash/holdings boundary verification before returning its result.
That verification does not activate rights transitions or change result schemas.

## Information and ownership contracts

- `EntitlementEvent` contains only the parent security, ex-session, disclosed
  entitlement ratios, instrument-class keys and evidence/availability references.
  All legs use the same explicitly supplied pre-event eligible parent units.
- `PaymentTerms` is supplied when its price/window is known. `PaymentRequest`
  explicitly declares whole units and fees. No hidden participation, prorating,
  pooling, fee or preferred-leg priority is inferred.
- `DeliveryTerms` is supplied later, when delivery, stable security identity and
  the newly delivered units' tradability and explicit fee are known. The book emits a typed
  `SecurityCredit`; the outer account must atomically apply it with the new book
  and enforce `tradable_session` in execution.
- `FractionalCashTerms` supplies an evidenced net cash amount for an exact bonus
  fraction. The engine does not infer proceeds from the underlying quote.
- `ReceiptConversionTerms` describes a one-for-one receipt-to-final-security
  exchange and its explicit fee. The outer account supplies verified current receipt holdings. A
  matching debit and credit are emitted together; historical delivery totals
  bound conversion, but cannot prove current holdings on their own.

Each term group has its own timezone-aware `available_at` and immutable evidence
SHA references. Execution rejects future knowledge. Granting rights does not
require loading future payment or delivery announcements. The source adapter
must authenticate the references and what they establish; a valid SHA string is
not proof the supplied fact is true or was historically published at that time.

## State and operations

`RightsBook` holds already usable cash, exact unpaid rights, paid/bonus pending
delivery units, lifetime delivered/expired/fractionally settled quantities and
canonical original command receipts. Entitlements conserve the declared
pre-event ownership basis. Bonus whole units are pending claims, never instant
tradable shares. Fractions remain explicit until documented disposal or expiry.

`grant_entitlements`, `subscribe_batch`, `deliver_claim`, `expire_unpaid`,
`settle_fraction`, `convert_receipt` and `revise_entitlements` are pure immutable operations. A failed
command changes no caller state. Reusing an action ID with identical payload is
a verified no-op; changing its payload fails. A new action cannot backdate the
completed processing clock. The outer ledger must persist the resulting book,
cash and inventory changes in one transaction.

A newly disclosed ratio can revise the same original ownership basis before
any payment, delivery, expiry or fractional settlement consumes the event. New
evidence and a later knowledge time are required; prior command receipts remain.
Consumed entitlements require an explicit correction/refund flow that this first
delivery does not yet implement. It never rewrites an earlier checkpoint.

Payment checks the full explicit batch before changing cash or quantities. The
caller must exclude reserved cash and unsettled sale receivables from the book's
cash input. Multiple explicit payments can consume remaining whole entitlements;
unpaid expiry leaves paid delivery claims intact. Payment windows currently use
declared dates; source-specific payment cutoffs, bank availability and election
rules must be validated by the adapter/policy before a command is issued.

This sub-book does not own a second cash balance alongside the portfolio. At
integration, the outer account must supply its current verified usable cash for
each transition/valuation and post the returned delta once. Trading settlements
remain the outer account's responsibility; a stale cached sub-book cash value
must never fund an election or be added to portfolio cash a second time.

`value_book` requires separate current-session marks for every positive unpaid
right and pending claim. Missing, future, stale, duplicate or unrelated marks
fail. Explicitly documented zero is permitted. Delivered inventory is excluded
from this sub-book's value, preventing duplicate valuation after delivery.
Valuation formulas and asset prices are external, frozen research inputs.

All monetary/ratio inputs use finite `Decimal`, with bounded input precision and
80-digit local arithmetic. Float/boolean quantities and monetary values are
rejected. `encode_book`/`decode_book` preserve exact canonical strings, command
payloads and typed quantities; duplicate JSON keys or unexpected schema/fields
fail. This codec is structural verification, not an independent financial audit
or external source authentication.

`audit_rights(book, initial_cash=..., recorded_movements=...)` now independently
reconstructs cash, fees and every per-leg balance from original commands, without
calling production transitions. The initial usable cash is an external anchor,
not reverse-inferred from the final checkpoint. Optional typed inventory posting
logs must exactly match every expected debit/credit, including quantity, security
and tradability. Missing, duplicated or substituted postings fail. The result
returns the expected movements even when final checkpoint balances disagree.

This audit currently covers an isolated rights book with no unrecorded outer
cash flows. When integrating portfolio trading/settlements, those external flows
need authenticated linkage and independent reconciliation. A coherent replacement
of both commands and source terms requires source validation; the financial audit
alone cannot establish historical truth or current receipt ownership. It does
not yet reconstruct market marks or portfolio NAV.

`book_validation.py` also binds every event's complete leg set and common eligible
ownership to its original grant, the current declaration to its latest recorded
terms, and each command's knowledge time to its processing clock. Recomputing a
command hash does not make future information available in the past.

## Hypothetical acceptance example

For 100 parent units and 100 usable cash, grant 10 bonus units, 5 ordinary
subscription rights and 2 preferred rights. Explicitly pay 5×10 + 2×20 = 90,
leaving 10 cash. At illustrative marks 20 for bonus/ordinary assets and 25 for
preferred, the original 360 sub-book value is conserved across payment and
delivery: 100 + 200 + 50 + 10 = 10 + 200 + 100 + 50. Explicit total fees of 0.25
reduce that value to 359.75. An 89-cash full election fails as one unit; a smaller
election must be explicitly chosen.

Tests also cover exact fractional entitlement, paid claims surviving expiry,
known net fractional payout, sold receipts not being included in the supplied
conversion quantity, delayed tradability, missing valuation evidence, low caller
Decimal precision, checkpoint round trips, and rejected/repeated commands.
These are hypothetical fixtures, not accepted 2881/2882 event terms.

## Remaining integration

### Joined security inventory boundary

`inventory.py` now defines `RightsInventory` and typed `SecurityLot` records.
The only current cash balance is `book.cash`; the explicit initial cash anchor
exists solely for independent reconciliation. Opening lots are separately
anchored. `post_rights_transition` accepts one command extending the exact
account prefix, independently audits its financial result and output movements,
and returns cash/rights/lots/postings as a single immutable value. A failure
publishes none of them. Replayed no-ops cannot contain a cash delta or credit.

Every grant is checked against actual pre-event owned parent units. This check
is repeated during checkpoint construction/decoding against the command-time
inventory, including earlier deliveries. It cannot be bypassed by directly
constructing a structurally valid book. Credits retain per-lot tradability dates;
debits consume only the same right's same security. `tradable_units` never
releases units early or answers past-session questions from a future checkpoint.

`inventory_valuation.py` requires separate current known marks for held securities
and remaining rights/claims. Nontradable delivered units remain assets but move
to security valuation, leaving pending claims; one cash balance is counted once.
`inventory_codec.py` provides a separate exact canonical checkpoint with financial,
posting, ownership and lot reconstruction on load. It does not change the old
SQLite checkpoint-v1 or claim durable transaction support.

This boundary has not yet admitted ordinary trading sales, portfolio cash flows,
settlement receivables, stop handling or independent source-backed opening lots.
The existing historical runner still does not call it. Those integrations must
use the same authoritative cash/inventory instead of creating a parallel account.

### Existing session cash/holding link

`reconcile_session_portfolio(inputs, result)` directly checks real shared-session
outputs using business events and the supplied prior runtime. It reconstructs
ACT/365 interest on prior spendable cash, dividend/split/CIL and terminal cash,
BUY reservations, negative-fee SELL shortfalls, and positive SELL credits at
T+2 close. Prior obligations must retain their identities; new obligations match
actual fills and may not settle early. Reserved buy cash and shortfall payables
are not deducted a second time. NAV cash/settled-cash disclosures, outstanding
sale receivables and resulting integer holdings must reconcile.

The verifier returns a `SessionPortfolioLink` describing the close boundary with
usable cash separate from unsettled sales. `run_odd_lot_session` checks this link
before returning the existing result; it adds no fields and changes no valid
business-event output. Tests inject simultaneous runtime/NAV cash drift inside
the actual close function and confirm rejection without changing input state.
This is a prerequisite for rights synchronization, not the synchronization itself.
It does not certify economic prices or source authenticity, and does not yet
post session cash flows into `RightsInventory` or migrate its lots/stops.

1. Authenticate each actual issuer leg, eligibility, final ratio, payment choice,
   receipt identity, exchange mechanism, fees and information timeline.
2. Define frozen participation/fractional/valuation policy and post-consumption corrections;
   unknown inputs must keep readiness blocked.
3. Connect the joined inventory boundary to the existing session core so trading,
   settlement cash, rights movements, stops, NAV and terminal events share one
   authoritative event lifecycle.
4. Add a separately versioned durable state/codec, atomic SQL records and source
   snapshots. Preserve existing checkpoint-v1 bytes and historical behavior.
5. Extend the independent rights cash/quantity audit to authenticated outer cash
   flows, actual inventory/current receipt ownership and source-linked NAV marks;
   canonical encoding and isolated book reconstruction alone are insufficient.
6. Complete historical-versus-incremental, fault/retry, source-tampering, new-data,
   UI and final full-profile acceptance before admitting real events.
