# HeatTrace Phase 7 Review: Day 9 Provenance Repair and Confirmatory Freeze

**Milestone:** Phase 7 (Day 9 Provenance Repair & Confirmatory Freeze)  
**Date:** October 2026  
**Gate 4 Recommendation:** **PASS**  
**Confirmation Sealing Status:** **SEALED — NOT EXECUTED** (Zero confirmatory outcome rows loaded or executed)  
**Implementation Commit:** `92f4b5739acf96ad837e54b9631f6ac974a1c7e6`

---

## 1. Executive Summary & Gate 4 Recommendation

In accordance with Phase 7 requirements of the HeatTrace 14-day plan, this review confirms:
1. **Provenance & Documentation Repairs:** Stale documentation identities and hashes in `docs/p6_gate1_review.md` and `docs/p6_pilot_review.md` were corrected against authoritative on-disk artifacts and validated execution contracts.
2. **Phase-Label Propagation Repair & Authoritative Loader:** The P6 phase-label builder defect (which collapsed all heatwave hours to `heatwave`) has been repaired via a versioned, deterministic phase-label sidecar overlay (`data/benchmarks/p7_phase_label_overlay.parquet`). The frozen benchmark parquet (`data/benchmarks/p6_event_control_pairs.parquet`) remains untouched and byte-identical. Canonical phases are supplied through the versioned sidecar and the authoritative fail-closed loading interface `load_p7_triplet_benchmark_with_overlay`. Phase-aware claims remain prohibited unless downstream execution/evaluation uses this loader successfully.
3. **Sealed 756-ID Confirmatory Dry Run:** A dedicated confirmatory dry-run matrix enumerator (`enumerate_p7_confirmatory_matrix` and `run_p7_confirmatory_dry_run`) was implemented in `src/heattrace/experiments/p6_validity_runner.py`. It derives exclusively from validated frozen configuration, enforcing exact approved confirmatory triplet and window identities (failing closed on fake IDs), producing exactly 756 unique, stable cell IDs across the preregistered cohorts with zero development contamination and zero confirmatory outcome data loaded.
4. **Adversarial Sealing & Integrity Probes:** Direct monkeypatch probes confirmed that parquet reading and scheduler execution are strictly absent from the dry run. Direct relational regression tests verified that window_type tampering, schema alterations, or hash mismatches fail closed immediately.
5. **Two-Commit Provenance Pattern:** The confirmatory dry-run manifest `data/manifests/p7_confirmatory_dry_run_manifest.json` is explicitly bound to the implementation commit `92f4b5739acf96ad837e54b9631f6ac974a1c7e6`. The follow-up provenance-repair commit captures this binding without self-referential git hash mutation.

Because all Phase 7 definition-of-done criteria are conclusively met with direct evidence, the **Gate 4 recommendation is PASS**.

---

## 2. Files Changed and Purpose

| File Path | Status | Purpose |
| :--- | :--- | :--- |
| `docs/p6_gate1_review.md` | Modified | Corrected development blind row from synthetic candidate `BLIND_3d808572606e` to authoritative selected candidate `BLIND_ef75b17921d7` with exact 120h timestamps and buffer hours. Preserved `BLIND_3d808572606e` in synthetic test contexts. |
| `docs/p6_pilot_review.md` | Modified | Updated recorded provenance hashes to reflect disk values: `p6_config_sha256` (`46f13248...`), `p6_thermal_config_sha256` (`250f1b07...`), canonical dataframe hash `development_benchmark_sha256` (`17302e7f...`), clearly distinguishing canonical dataframe hashes from raw parquet file hashes. Preserved historical Day 8 outcomes. |
| `src/heattrace/process/p6_event_bundle.py` | Modified | Implemented `build_p6_phase_label_overlay`, `save_p6_phase_label_overlay`, `load_p6_phase_label_overlay`, and `apply_p6_phase_label_overlay`. Preserves frozen parquet file while restoring canonical event phases (`onset`, `peak`, `sustained`, `recovery`). Relational join binds `window_type` and enforces strict semantic validity. |
| `src/heattrace/experiments/p6_validity_runner.py` | Modified | Implemented `ConfirmatoryCellSpec`, `enumerate_p7_confirmatory_matrix`, `run_p7_confirmatory_dry_run`, and `load_p7_triplet_benchmark_with_overlay`. Enforces exact frozen triplet and window identities, disk hashes, and commit binding. |
| `data/benchmarks/p7_phase_label_overlay.parquet` | Created | Deterministic phase-label sidecar overlay covering all 1,440 benchmark rows keyed by `(triplet_id, window_type, window_id, timestamp_utc)`. |
| `data/manifests/p7_confirmatory_dry_run_manifest.json` | Created | Confirmatory dry-run provenance manifest containing design metadata, cohort counts, run-ID digest, frozen hashes, and sealing status. Explicitly bound to implementation commit `92f4b573...`. |
| `tests/test_p6_event_bundle.py` | Modified | Added 8 adversarial test probes for phase-label overlay coverage, ordering invariance, fail-closed missing/duplicate detection, non-event protection, price/carbon independence, window-type tampering regression, and schema exactness. |
| `tests/test_p6_validity_runner.py` | Modified | Added 7 adversarial test probes verifying 756 exact counts, cohort subtotals, deterministic order invariance, parquet-reader sealing monkeypatches, fail-closed count tampering, fake pair/window identity rejection, authoritative loader pushdown isolation, and commit validation. |
| `docs/p7_freeze_readiness.md` | Created / Updated | This freeze-readiness report and Gate 4 review document. |

---

## 3. Stale References Repaired

### 3.1 `docs/p6_gate1_review.md`
- **Issue:** Section 4 table listed `BLIND_3d808572606e` (`2024-09-15 07:00` to `2024-09-20 07:00`) for `TRIPLET_DEV_ae821c`.
- **Authoritative Source:** `data/benchmarks/p6_event_control_index.csv` and `configs/p6_validity.yaml` both record `BLIND_ef75b17921d7` (`2024-09-19 07:00` to `2024-09-24 07:00`, 1,800 buffer hours after `HW_20240702`).
- **Correction Applied:** Row updated to `BLIND_ef75b17921d7` with authentic bounds. `BLIND_3d808572606e` was retained untouched in `tests/test_p6_event_bundle.py` where it serves as the synthetic missing-coverage replacement candidate.

### 3.2 `docs/p6_pilot_review.md`
- **Issue:** Provenance hashes in Section 2 were recorded with stale/intermediate pre-repair values (`p6_config_sha256: 7e2b7a96...`, `p6_thermal_config_sha256: 6451e06f...`, `development_benchmark_sha256: ca0ae560...`).
- **Correction Applied:** Replaced with actual values matching `data/results/p6_development_pilot.parquet` and verified raw disk files:
  - `p6_config_sha256`: `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1` (raw file hash)
  - `p6_thermal_config_sha256`: `250f1b07daa6a19bcc9fe7415c7034b5ade240d69095cf3b539b7ee6ba001551` (raw file hash)
  - `development_benchmark_sha256`: `17302e7fe2b80dc7e73cfb485b99dc271580460ccc864ec60ff047cedebee023` (canonical dataframe hash via `compute_canonical_df_sha256(pairs_dev)`)
  - Explicit note distinguishing raw parquet file hash (`60cea3627d9f...` for 1,440 rows across 4 triplets) from canonical development dataframe hash (`17302e7f...` for 360 development rows).

---

## 4. Phase-Label Propagation Repair & Authoritative Loader

### 4.1 Defect Analysis
In P6, `build_p6_benchmark_triplets` assigned `phase_label = ctx_label`, collapsing all 480 heatwave hours to `"heatwave"` and discarding canonical phase semantics (`onset`, `peak`, `sustained`, `recovery`). Overwriting the frozen parquet `data/benchmarks/p6_event_control_pairs.parquet` was strictly prohibited. Furthermore, the overlay join previously lacked `window_type` binding, allowing a relabeled row to evade validation.

### 4.2 Sidecar Overlay & Relational Binding Design
To maintain complete cryptographic continuity of frozen benchmark files, a deterministic sidecar overlay architecture was implemented:
- **Function:** `build_p6_phase_label_overlay(pairs_df, event_catalogue_df)` generates an overlay keyed strictly by `(triplet_id, window_type, window_id, timestamp_utc)`.
- **Phase Mapping:**
  - Heatwave rows map to canonical phases generated by `build_hourly_phase_labels(event_catalogue_df)` from `src/heattrace/process/events.py`.
  - Matched control rows map to `"control"`.
  - Event-blind rows map to `"event_blind"`.
- **Relational Joining:** `apply_p6_phase_label_overlay(pairs_df, overlay_df)` joins phase labels onto pairs by full composite identity keys `(triplet_id, window_type, window_id, timestamp_utc)`.
  - Input and overlay window types must agree exactly.
  - Heatwave rows accept only `onset`, `peak`, `sustained`, `recovery`.
  - Control rows accept only `control`.
  - Event-blind rows accept only `event_blind`.
  - Missing, extra, conflicting, or non-matching rows fail loudly.
- **Sidecar Artifact:** Materialized to `data/benchmarks/p7_phase_label_overlay.parquet` (1,440 rows, SHA-256: `7157a2e64efafa148aa276efc20c12893ad1e938ecf767c76a5ccd5e7c49da23`).
- **Phase Breakdown:**
  - `control`: 480 rows
  - `event_blind`: 480 rows
  - `sustained`: 240 rows
  - `peak`: 96 rows
  - `onset`: 72 rows
  - `recovery`: 72 rows
  - Total: 1,440 rows (100% complete coverage)

### 4.3 Authoritative Production Loader
The function `load_p7_triplet_benchmark_with_overlay` in `src/heattrace/experiments/p6_validity_runner.py` establishes the mandatory benchmark-loading interface:
- Uses pyarrow read-time pushdown filtering (`filters=[("triplet_id", "=", target_triplet_id)]`) on both the benchmark pairs parquet and the overlay parquet.
- Verifies overlay on-disk SHA-256 hash against `FROZEN_PHASE_OVERLAY_HASH`.
- Ensures zero rows from non-target triplets enter pandas memory.
- Applies the fail-closed `apply_p6_phase_label_overlay` join.
- Delivers complete rows with canonical phase labels.

---

## 5. Verified Frozen Values and Hash Table

All authoritative input hashes were verified directly from disk:

| Artifact / Configuration | Type | SHA-256 Hash | Verification Status |
| :--- | :--- | :--- | :---: |
| `configs/p6_validity.yaml` | Raw file | `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1` | **MATCH** |
| `configs/p6_thermal.yaml` | Raw file | `250f1b07daa6a19bcc9fe7415c7034b5ade240d69095cf3b539b7ee6ba001551` | **MATCH** |
| `docs/p6_frozen_protocol.md` | Raw file | `78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede` | **MATCH** |
| `data/models/p6_temperature_v2/artifact_manifest.json` | Raw file | `ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79` | **MATCH** |
| `data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt` | Raw file | `69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed` | **MATCH** |
| `data/models/p6_heatguard_calibration_v3/manifest.json` | Raw file | `bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c` | **MATCH** |
| `data/results/p6_forecast_metrics.csv` | Raw file | `7006055fb9be85d0fe54e3e17ce2ed498e13b244402d60d510c57fcb0a45e558` | **MATCH** |
| `data/benchmarks/p6_event_control_pairs.parquet` | Raw file | `60cea3627d9f81d3b2020e17930a6418b6aa0bfe3b292256e3949f76947dd109` | **MATCH (UNTOUCHED)** |
| `data/benchmarks/p6_event_control_index.csv` | Raw file | `a57a777325c21cdbd343f8ec718734ad45d6cfbcfa293a80b29b324249a14b72` | **MATCH (UNTOUCHED)** |
| Development Canonical Dataframe (`TRIPLET_DEV_ae821c`) | Canonical DF | `17302e7fe2b80dc7e73cfb485b99dc271580460ccc864ec60ff047cedebee023` | **MATCH** |
| `data/benchmarks/p7_phase_label_overlay.parquet` | Raw file | `7157a2e64efafa148aa276efc20c12893ad1e938ecf767c76a5ccd5e7c49da23` | **CREATED** |
| `data/manifests/p7_confirmatory_dry_run_manifest.json` | Raw file | Verified with 9 hashes | **CREATED & BOUND** |

---

## 6. Confirmatory Dry-Run Counts and Uniqueness Audit

Enumerated via `enumerate_p7_confirmatory_matrix(REPO_ROOT / "configs/p6_validity.yaml")`:
- **Cohort A (Core Benchmark):** 432 cells
  - 3 confirmatory pairs × 2 contexts (heatwave, control) × 2 facility models × 2 thermal curves × 3 workload multipliers × 2 seeds × 1 objective (`carbon_first`) × 3 policies (`static_unaware`, `capacity_aware`, `full_thermal_aware`) = 432
- **Cohort B (Event-Blind Benchmark):** 216 cells
  - 3 event-blind windows × 2 facility models × 2 thermal curves × 3 workload multipliers × 2 seeds × 1 objective (`carbon_first`) × 3 policies = 216
- **Cohort C (Algorithm Comparators):** 72 cells
  - 3 confirmatory pairs × 2 contexts × 1 facility model (`power_capped`) × 1 thermal curve (`medium`) × 3 workload multipliers × 2 seeds × 1 objective (`carbon_first`) × 2 policies (`heatguard_calibrated`, `heatguard_fixed`) = 72
- **Cohort D (Oracle Reference):** 36 cells
  - 3 confirmatory pairs × 2 contexts × 1 facility model (`power_capped`) × 1 thermal curve (`medium`) × 3 workload multipliers × 2 seeds × 1 objective (`carbon_first`) × 1 oracle policy (`oracle_full_thermal_aware`) = 36
  - All 36 cells verified with `deployable = False`.
- **Total Cells:** Exactly 756 cells.
- **Unique Run-IDs:** 756 (0 duplicates).
- **Unique Canonical Keys:** 756 (0 duplicates).
- **Run-ID Digest:** `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1`.
- **Zero Development Contamination:** 0 cells reference `TRIPLET_DEV_ae821c`, `HW_20240702`, `CTRL_20240605`, or `BLIND_ef75b17921d7`.

---

## 7. Adversarial Verification and Sealing Probes

Fifteen dedicated test probes were executed and verified:

1. `test_p7_phase_label_overlay_genuine_phases_survive`: Proves that all four heatwave phases (`onset`, `peak`, `sustained`, `recovery`) survive propagation into the benchmark data structure.
2. `test_p7_phase_label_overlay_shuffled_order_invariance`: Proves that random perturbation of row order in either source pairs or events produces identical overlay output and identity-keyed joining.
3. `test_p7_phase_label_overlay_missing_row_fails_loudly`: Proves that incomplete phase coverage fails closed immediately.
4. `test_p7_phase_label_overlay_duplicate_conflicting_fails_loudly`: Proves that duplicate or conflicting keys raise loud exceptions.
5. `test_p7_phase_label_control_blind_cannot_be_heatwave_phases`: Proves that control and blind rows cannot be assigned heatwave phase labels.
6. `test_p7_phase_label_independent_of_price_carbon_outcomes`: Proves that severe mutations to price, carbon, or demand columns have zero effect on phase labels.
7. `test_p7_phase_overlay_join_rejects_window_type_tampering`: Proves that changing a heatwave row to control or vice versa fails closed immediately during overlay application.
8. `test_p7_phase_label_overlay_schema_exactness`: Proves that the overlay loader rejects extra or missing columns.
9. `test_p7_confirmatory_matrix_exact_counts_and_subtotals`: Verifies 756 count, cohort subtotals (432, 216, 72, 36), key uniqueness, zero dev triplet leak, and non-deployable oracle marking.
10. `test_p7_confirmatory_matrix_deterministic_and_order_invariant`: Verifies exact identical run ID ordering under repeated calls and reverse-ordered configuration definitions.
11. `test_p7_confirmatory_dry_run_sealing_probe`: Monkeypatches both `pandas.read_parquet` and `pyarrow.parquet.read_table` to raise `AssertionError` if invoked during dry-run enumeration. Proves confirmatory datasets are strictly sealed.
12. `test_p7_confirmatory_dry_run_fails_closed_on_tampering`: Verifies that tampering with confirmatory triplet counts in configuration fails closed immediately.
13. `test_p7_confirmatory_matrix_rejects_fake_identities`: Proves that injecting a fake pair, heatwave, control, or blind ID fails closed even if cardinality remains 3.
14. `test_p7_authoritative_loader_triplet_isolation_and_provenance`: Proves that the authoritative loader reads only the requested triplet into memory and verifies overlay hash integrity.
15. `test_p7_confirmatory_dry_run_rejects_pending_or_invalid_commit`: Proves that dry-run rejects `PENDING_COMMIT` or malformed commit hashes.

---

## 8. Two-Commit Provenance Architecture

To resolve the self-referential git commit hash problem cleanly:
1. **Implementation Commit (`92f4b5739acf96ad837e54b9631f6ac974a1c7e6`):** Froze the initial P7 implementation code, configs, test suites, and preliminary manifest.
2. **Follow-up Binding Commit:** Points `data/manifests/p7_confirmatory_dry_run_manifest.json` explicitly to implementation commit `92f4b5739acf96ad837e54b9631f6ac974a1c7e6`, adds all 9 frozen disk hashes (including parquet, index, and overlay), and records this architecture in documentation. The manifest intentionally references the immutable implementation commit that generated the dry run, avoiding a circular dirty worktree loop.

---

## 9. Gate 4 Verdict

**GATE 4 RECOMMENDATION: PASS**  
All required provenance repairs, deterministic phase-label overlay mechanics, authoritative loader interfaces, exact frozen identity bindings, 756-cell dry-run enumeration, and adversarial sealing proofs are complete, tested, and verified against disk.
