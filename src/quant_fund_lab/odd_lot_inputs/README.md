# Provider-preserving odd-lot price inputs

`types.py` defines raw price sources, observations, a frozen source policy and selection outcomes. Source identity includes provider/dataset, original URL, retrieval time, raw path/hash, units, conversion revision and declared usage references. Prices are unadjusted and volume uses shares. A no-quote observation has absent prices, retaining its original row locator; it is not a suspension attestation or an executable zero price.

`load_finmind_price_bundle(directory)` in `finmind.py` reads a DATA-01 acquisition bundle offline. It validates manifest identity, request URLs/ranges, source bytes, dates, stock IDs, finite OHLC, integer volume/counts and duplicate keys. The existing normalized CSV must pass both its SHA-256 and a field-by-field comparison with reconstructed raw rows and month claims. Neither a successful HTTP status nor an updated CSV hash proves data equivalence. The acquisition scripts remain separate artifacts and are not imported at runtime.

`load_twse_price_observations(inputs)` in `twse.py` reads original rows from an already prepared official bundle. TWSE and FinMind retain distinct providers, datasets and source IDs. The reader does not insert FinMind records into the official manifest.

`select_prices(observations, policy)` in `selection.py` compares overlapping raw quotes/volume and applies the frozen provider priority only where the sources agree. Quote-status disagreement is a conflict. Conflicting keys have no selected quote; callers must retain and block on those conflicts. Duplicate rows from the same source are rejected. No values are averaged, forward-filled or silently replaced. `price_selection_records()` exports selected/conflicting keys with raw row lineage for CSV handoff.

The `reviewed_provider_v1` policy uses absolute price tolerance 1e-8, exact share counts, explicit start/end/cutoff and a unique provider priority. Policy and selection fingerprints bind both lineage and selected numeric values; changing an in-memory quote cannot retain its previous identity.

`reviewed_provider_v2` (schema 2) is an explicit opt-in for independently evidenced individual halts. A selected no-quote row with zero volume and no reported turnover or trade count can use the shared normalizer's official suspension evidence. Executable opens stay absent, volume stays zero, and a prior close is required for the valuation mark. No evidence, a different symbol/date, positive trade activity or an actual quoted halt remains blocked. Source rows and lineage are preserved. This rule does not remove market sessions or relax event/coverage/warmup checks.

V1 remains the default and keeps its serialized fields, policy fingerprint and original strict no-quote findings. Version/schema mismatches are rejected. UI exposes the opt-in as「依官方個股停牌證據核對無報價」; selection is frozen in policy/provenance and changing it creates a new study. Old v1 studies are reconstructed with v1 behavior, not silently promoted. Forward plans must keep their frozen source policy; v2 evidence cannot be substituted into a v1 plan.

Current scope is raw acquisition reading and selection. Event/calendar-aware `PreparedOddLotInput`, provider-mode freeze/load/run/report/UI and full research acceptance remain pending. Existing official studies keep their source policy. A selected FinMind month is not counted as an official TWSE import, and a no-conflict selection does not prove corporate-action coverage, historical availability or research readiness.

The paragraph above records the initial raw-reader delivery. `prepare.py` now defines `PreparedOddLotInput` and `prepare_reviewed_odd_lot_input()`. The reviewed selection replaces only the quote input of the shared normalizer through `overlay.py`; official events, suspensions, review coverage, return reconstruction and conflict checks remain shared. All original official findings are retained as explicit policy context, while recomputed findings govern the reviewed policy. Nonblocking context cannot replace active findings.

Native `provider_reviewed` studies now freeze/reconstruct both source namespaces and the source policy, validate normalized data against raw originals, use shared readiness before performance, and export a hashed `price_selection.csv`. The Streamlit source option is explicit; its default end comes from the provider manifest. Ready and blocked studies have been run through both backend and full UI fixtures. Existing official studies keep their original identity and reviewed input cannot be frozen as official.

Readiness rules are now `readiness-v2` to identify the policy-applicability semantics. Archived v1 decisions remain readable with integrity verification, but execution requires a new freeze under current rules. Real-data event/calendar review and the remaining acceptance matrix are still required; engineering integration is not research acceptance.

The local integration handoff is `artifacts/acceptance/DATA-02/raw-selection/`, containing `price_selection.csv` and `summary.json`. Unit tests use self-built minimal data; provider raw files remain outside version control.


## Invalid-input diagnostics

`errors.py` defines `PriceSourceError(ValueError)`, retaining compatibility with callers that catch `ValueError`. It carries `source_path`, optional `row_locator` and the original validation detail. Manifest entry failures identify `provider_manifest.json` and `sources[index]`; raw observation failures identify the original raw path and `data[index]`; normalized observation failures identify the CSV path and physical `line[number]` including the header. File integrity, response shape and missing-record errors have no fabricated row. Wrapped parser/validation exceptions retain their original cause. No diagnostic adds source fields to serialized policy or observation identity, changes accepted input values, repairs invalid input or writes the source bundle.

Scoped regression evidence is under `artifacts/acceptance/DATA-02/source-error-context/`. This change follows the 306-file integrated snapshot; that snapshot's full-suite result does not cover it. Final release still requires a matching final source inventory and complete regression.


## Selection report contract

`reporting.py` provides `price_selection_csv(selection: PriceSelection) -> bytes` and `verify_price_selection_report(directory: Path, selection: PriceSelection, manifest: dict) -> bool`. Export and verification share the exact UTF-8 CSV encoder. Provider reports require `price_selection.csv` in the hash manifest and must match the selection reconstructed from the frozen original source bytes and policy. Rehashing an edited provider, source ID or row locator cannot authenticate a different selection. Verification is read-only and does not run strategy performance. Existing original report bytes and frozen policy identities are preserved.


Official observation readers also raise `PriceSourceError`: malformed source rows identify the raw file and parsed `data[index]` offset, while manifest/schema/parser/hash failures carry file-level context. CSV footers retain the original skip behavior; parsed table offsets are not physical CSV line numbers. Diagnostics do not change serialized observations or policy identity. Direct official cases and both-profile regressions are recorded in `artifacts/acceptance/DATA-02/official-error-context/`.
