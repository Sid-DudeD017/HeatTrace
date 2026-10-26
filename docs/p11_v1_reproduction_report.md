# HeatTrace Phase 11 — v1 Reproduction and Archive Report

**Date:** 2026-10-25
**Study Phase:** Phase 11 (Days 13–14: Reproduce and Archive v1)
**Status:** COMPLETE WITH LIMITATIONS
**Overall Decision:** LIMITED RESULT

---

## 1. Implementation Checkpoints & Environment

- **Runner Execution Commit:** `d5b3c86ac9076b118644e32dd2c8b6ab6f7cab2d`
- **Analysis Implementation Commit:** `995a5b76a5cc1233213c52cdf5b8443d849e23f3`
- **Git Tree Status:** Clean tracked tree verified.
- **Python Runtime:** Python 3.13.3 (macOS darwin arm64).

---

## 2. Paths & Artifact Provenance

### Paths
- **Canonical P8 Results Directory:** `data/results/`
- **Clean Reproduction Directory:** `data/reproductions/heattrace_v1_d5b3c86/`
- **Clean Reproduction Analysis Directory:** `data/reproductions/analysis/`
- **Immutable v1 Archive Directory:** `data/archive/heattrace_v1_d5b3c86/`
- **Archive Manifest:** `data/archive/heattrace_v1_d5b3c86/archive_manifest.json`

### Canonical P8 Artifact SHA-256 Hashes
- **p6_validity_runs.parquet:** `c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f` (Verified unchanged)
- **p6_validity_checkpoint.parquet:** `c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f` (Verified unchanged)
- **p6_validity_manifest.json:** `d0dd9f870ec2a431cc16177c5f1b7a5e6b47a7dc888b0acb491a819656006082` (Verified unchanged)
- **p6_validity_execution.jsonl:** `de430ceea4559de2f4e67f5b122223b3496dfe854e1f5efa874909363bff0e80` (Verified unchanged)

### Frozen Input & Calibration Hashes
- **HeatGuard Calibration Manifest:** `bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c`
- **P4 Temperature Artifact Manifest:** `ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79`
- **P4 Temperature Checkpoint:** `69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed`
- **p6_validity.yaml:** `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1`
- **p6_thermal.yaml:** `250f1b07daa6a19bcc9fe7415c7034b5ade240d69095cf3b539b7ee6ba001551`
- **p6_frozen_protocol.md:** `78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede`
- **p6_event_control_pairs.parquet:** `60cea3627d9f81d3b2020e17930a6418b6aa0bfe3b292256e3949f76947dd109`
- **p6_event_control_index.csv:** `a57a777325c21cdbd343f8ec718734ad45d6cfbcfa293a80b29b324249a14b72`
- **p7_phase_label_overlay.parquet:** `7157a2e64efafa148aa276efc20c12893ad1e938ecf767c76a5ccd5e7c49da23`

---

## 3. Reproduction Execution Metrics & Recomputed Hashes

The Phase 11 reproduction execution was performed via `execute_frozen_confirmation` rerun from zero checkpoint state in a fresh session:
- **Total Executed Cells:** 756
- **Unique Run IDs:** 756
- **Run-ID Digest:** `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1` (Exact match)
- **Cohort Counts:**
  - `core_benchmark`: 432
  - `event_blind_benchmark`: 216
  - `algorithm_comparators`: 72
  - `oracle_reference`: 36
- **Oracle Deployable Invariant:** All 36 oracle rows have `deployable == False`.
- **Zero Development Leakage:** 0 rows matching `DEV` triplet or windows.
- **Failures Retained:** Explicitly audited; zero unhandled errors.

### Accurate Observed Reproduction Artifact Hashes
- **reproduction runs.parquet:** `2a41634a318193f8fcde624bd0dd0e023a9da19d1e4fd682cb32895fba9033fa`
- **reproduction checkpoint.parquet:** `2a41634a318193f8fcde624bd0dd0e023a9da19d1e4fd682cb32895fba9033fa`
- **reproduction manifest.json:** `29e60aee534bb3f91ab9aecf4704bea85a2d80ba5043996c8fc94579effc8b32`
- **reproduction execution.jsonl:** `d1df535a3ee1a0be2404afd03dfb35803af06528b239225d4f6932ca204e7935`

---

## 4. Scientific vs Operational Differences

After run-ID alignment across all 756 rows, exact parquet column comparisons show:
- **Real Non-Operational Columns (44 columns):** All 44 actual non-operational columns matched exactly (zero scientific discrepancies):
  1. `run_id` (exact match)
  2. `triplet_id` (exact match)
  3. `context` (exact match)
  4. `window_id` (exact match)
  5. `cohort` (exact match)
  6. `facility_model` (exact match)
  7. `thermal_curve` (exact match)
  8. `workload_multiplier` (exact match)
  9. `seed` (exact match)
  10. `workload_trace_id` (exact match)
  11. `objective` (exact match)
  12. `policy_id` (exact match)
  13. `policy_version` (exact match)
  14. `deployable` (exact match)
  15. `margin_mode` (exact match)
  16. `applied_margin` (exact match)
  17. `status` (exact match)
  18. `error_class` (exact match)
  19. `error_message` (exact match)
  20. `demanded_processing_slots` (exact match)
  21. `demanded_energy_kwh` (exact match)
  22. `completed_processing_slots` (exact match)
  23. `completed_energy_kwh` (exact match)
  24. `unfinished_processing_slots` (exact match)
  25. `unmet_deadlines_count` (exact match)
  26. `allocation_count` (exact match)
  27. `facility_power_violation_hours` (exact match)
  28. `total_facility_power_excess_kwh` (exact match)
  29. `maximum_facility_power_excess_kw` (exact match)
  30. `realized_facility_energy_kwh` (exact match)
  31. `cooling_adjusted_cost_usd` (exact match)
  32. `cooling_adjusted_carbon_kg` (exact match)
  33. `scheduler_feasible` (exact match)
  34. `thermally_feasible` (exact match)
  35. `p6_config_sha256` (exact match)
  36. `p6_thermal_config_sha256` (exact match)
  37. `p6_protocol_sha256` (exact match)
  38. `benchmark_parquet_sha256` (exact match)
  39. `benchmark_index_sha256` (exact match)
  40. `phase_overlay_sha256` (exact match)
  41. `p4_manifest_sha256` (exact match)
  42. `p4_checkpoint_sha256` (exact match)
  43. `calibration_manifest_sha256` (exact match)
  44. `workload_sha256` (exact match)
- **Operational-Only Differences:**
  - `execution_commit`: Canonical P8 recorded commit vs Stage 1 commit `d5b3c86ac9076b118644e32dd2c8b6ab6f7cab2d` (differed in 756 rows).
  - `runtime_seconds`: Execution clock variations, $\le 0.20\text{ s}$ difference (differed in 751 rows; 5 rows had identical rounded execution times).
  - No scientific outcome difference was found.

---

## 5. Hypothesis Evidence Regeneration (H1–H5)

Phase 9 analysis rerun on reproduction outputs from committed analysis source (`995a5b7`) regenerated all hypothesis conclusions and derived tables:

| Hypothesis | Status | Verdict | Event Effects / Discrimination | Conclusion Match |
|---|---|---|---|---|
| **H1** | Frozen Primary | SUPPORTED | CONF_1: -0.5x, CONF_2: -0.5x, CONF_3: 0.0x | EXACT MATCH |
| **H2** | Frozen Secondary | PARTIALLY_SUPPORTED | 0/2 boundary recovery; 2/2 full-thermal violation reduction | EXACT MATCH |
| **H3** | Frozen Secondary | PARTIALLY_SUPPORTED | CONF_1: 24/36, CONF_2: 23/36, CONF_3: 0/36; 0 reversals | EXACT MATCH |
| **H4** | Exploratory (Post-Day 8) | NOT_ESTIMABLE | Missing controlled forecast intervention traces | EXACT MATCH |
| **H5** | Frozen Secondary | NOT_SUPPORTED | Dynamic margin does not beat fixed 0.10 margin | EXACT MATCH |

P11 strengthened research reproducibility and artifact quality, but did not generate new scientific evidence. No HeatGuard advantage was established, forecast-caused regret was not identified, the third event remained null, and zero strict ranking reversals were observed.

### Table and Figure Cryptographic Hashes
All reproduced tables and deterministic figures match canonical outputs byte-for-byte:
- `p6_event_level_metrics.csv`: `05bbe336f61ff08e0f5654e3cf0f5f35a20464de3eca81ca87800e587c361e6b` (Match)
- `p6_policy_pairwise_metrics.csv`: `261dadaf4a8c6939448927d66cd91a68b6a4eca89811eb547386995f59774e73` (Match)
- `p6_t1_cohort_provenance.csv`: `86ccf8243a67b1cf3c904efc026dd084376ef97fd90cd1c2292608b2e66164a0` (Match)
- `p6_t2_event_feasibility.csv`: `40dda3001aacd21aaa0aa3babbee734b7e9b5292742be5abd9c78e0347a800cd` (Match)
- `p6_t3_equal_service_gaps.csv`: `13e8efcae8c2c78affc6e78158c7528c00e3c90f2d57579c3504818a8346764f` (Match)
- `p6_t4_forecast_evidence.csv`: `6c479ce5f12d916bdbe2074e965ce815ae5788c8533fc89a62f15aeca16fe676` (Match)
- `p6_h1_h5_assessment.csv`: `48ac19530bc60db2a6945d7231f9ab518059441e1336544fea65a462a864f4ba` (Match)
- `p6_f1_event_policy_contrasts.png`: `d58be76f27605d47307b753fc0baa120f45ab4e92fed838a9a4d169996826114` (Match)
- `p6_f2_allocation_distance_status.md`: `a68d94a9e4dbc29600e0c4a0f7027c21d65cc9e5973f1c59df3e90aa8d110951` (Match)
- `p6_f3_forecast_regret_status.md`: `b95aac50a8c15dca814cb6ce97c426fb3f915a250e3e7203ef95cec0cf69c231` (Match)
- `p6_f4_h1_sensitivity.png`: `247a97f2ba3c6b050bf69454d3b5da73811538d20efb74f60f81a377a064af4d` (Match)

---

## 6. Adversarial Probes

Direct adversarial probes executed against the verification pipeline:
1. **Missing Run ID:** Failed closed (`Expected 756 rows, found 755`).
2. **Duplicate Run ID:** Failed closed (`Expected 756 unique run_ids, found 755`).
3. **Development Leakage:** Verified 0 dev triplets in confirmatory outputs.
4. **Oracle Marked Deployable:** Failed closed (`Oracle reference contains rows marked deployable=True`).
5. **Dropped Work Credit to H2:** Failed closed (H2 reverted to `NOT_SUPPORTED`).
6. **Incomplete Demanded Service Credit to H2:** Failed closed (H2 reverted to `NOT_SUPPORTED`).
7. **Altered Frozen Input Hash:** Failed closed (`P4 manifest hash mismatch`).
8. **Omitted / Unexpected Failure Row:** Failed closed (`Not all rows have status SUCCESS`).

---

## 7. Focused Test Suite

- `pytest tests/test_p6_validity_runner.py -k "enumeration or contamination or digest or frozen"`: **5 passed**, 72 deselected in 1.36s.
- `pytest tests/test_p6_validity_analysis.py`: **24 passed** in 33.86s.
- `git diff --check`: Clean (zero trailing whitespace or conflict markers).

---

## 8. Immutable v1 Archive

- **Archive Location:** `data/archive/heattrace_v1_d5b3c86/`
- **Total Archived Artifacts:** 54 files (content-addressed, no symlinks, relative portable paths).
- **Complete Model Dependencies Included:**
  - HeatGuard v3: calibration.json, forecast_temperatures.npy, origins.json, realized_temperatures.npy, residuals.npy, manifest.json.
  - Temperature model v2: artifact_manifest.json, tiny_lstm_checkpoint.pt, scaler.json, split_manifest.json, training_history.json, evaluation_metrics.csv.
  - External raw NOAA sources explicitly categorized under `external_source_inputs`.
- **Archive Manifest:** `data/archive/heattrace_v1_d5b3c86/archive_manifest.json`
- **Archive Manifest SHA-256:** `2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4`
- **Self-Verification Command:** `python3 data/archive/heattrace_v1_d5b3c86/verify_archive.py` (Result: PASS, 54/54 verified).

---

## 9. Explicit Reproduction Limitations

The Phase 11 reproduction establishes same-environment experimental equivalence, but operates under material limitations:
1. **Same-Environment Rerun:** The rerun occurred on the same host machine and repository lineage as prior development.
2. **Missing Shell Command Transcript:** The exact Python/shell invocation command launching the simulation was not retained in an external transcript.
3. **No Raw Test/Execution Logs:** No raw pytest/JUnit XML logs or external scheduler logs were archived.
4. **No Dependency Lock:** No `uv.lock`, `poetry.lock`, or pinned requirements snapshot was archived; third-party package environments are not frozen.
5. **No Raw Dataset Reconstruction:** NOAA, CAISO, and EIA raw datasets were not rebuilt from original primary web APIs.
6. **No Clean-Checkout Simulation:** While `git archive` portability establishes that the archive verifies independently in a clean extraction, full simulation rerun was not performed from a clean checkout.
7. **Same-Environment vs Independent:** This is a same-environment experimental reproduction, not a third-party independent reproduction.

---

## 10. Phase 11 Guardrail Verifications

- Canonical P8/P9/P10 artifact bytes remained completely unchanged: **CONFIRMED**.
- Zero v2 or Phase 12 work performed: **CONFIRMED**.
- Limited Result verdict preserved without upgrade: **CONFIRMED**.
- Equal-service and independence rules strictly preserved: **CONFIRMED**.
- All 756 cells were rerun from zero checkpoint state in a fresh session during Phase 11: **CONFIRMED**.

**Phase 11 Verdict:** **COMPLETE WITH LIMITATIONS**
