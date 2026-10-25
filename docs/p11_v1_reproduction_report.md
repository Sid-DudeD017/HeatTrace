# HeatTrace Phase 11 — v1 Reproduction and Archive Report

**Date:** 2026-10-25
**Study Phase:** Phase 11 (Days 13–14: Reproduce and Archive v1)
**Status:** PASS
**Overall Decision:** LIMITED RESULT

---

## 1. Implementation Checkpoint & Environment

- **Stage 1 Implementation Commit:** `d5b3c86ac9076b118644e32dd2c8b6ab6f7cab2d`
- **Git Tree Status:** Clean tracked tree verified before reproduction.
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

## 3. Reproduction Execution Metrics

The clean execution was performed via `execute_frozen_confirmation` with zero checkpoint resumption:
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

### Reproduction Artifact Hashes
- **reproduction runs.parquet:** `2a41634a318193f8fcde624bd0dd0e023a9da19d1e4fd682cb32895fba9033fa`
- **reproduction checkpoint.parquet:** `2a41634a318193f8fcde624bd0dd0e023a9da19d1e4fd682cb32895fba9033fa`
- **reproduction manifest.json:** `7f34384a3237ebc5d64ff19eb0b0aa447dca08d6677f2d5a3eb7fa475727038e`
- **reproduction execution.jsonl:** `9bfeaa1cbbbc68114f86d63c45759efc78c89dc3ea7ec99f7d2f95fc72702a46`

---

## 4. Scientific vs Operational Differences

- **Scientific Fields:** Evaluated across all 756 cells and all metric dimensions:
  - `completed_processing_slots`: Exact match (0 diff)
  - `unfinished_processing_slots`: Exact match (0 diff)
  - `unmet_deadlines_count`: Exact match (0 diff)
  - `facility_power_violation_hours`: Exact match (0 diff)
  - `total_facility_power_excess_kwh`: Exact match (0 diff)
  - `cooling_adjusted_cost_usd`: Exact match (0 diff)
  - `cooling_adjusted_carbon_kg`: Exact match (0 diff)
  - `mean_pue`: Exact match (0 diff)
  - `max_pue`: Exact match (0 diff)
  - `peak_facility_power_kw`: Exact match (0 diff)
  - Feasibility flags (`scheduler_feasible`, `thermally_feasible`): Exact match (0 diff)
  - **Scientific Result:** 100% IDENTICAL (zero scientific discrepancies).
- **Operational-Only Differences:**
  - `execution_commit`: Canonical P8 recorded commit vs Stage 1 commit `d5b3c86ac9076b118644e32dd2c8b6ab6f7cab2d`.
  - `timestamp_utc`: Execution session timestamps.
  - `runtime_seconds`: Minor clock jitter ($\le 0.20\text{ s}$).

---

## 5. Hypothesis Evidence Regeneration (H1–H5)

Phase 9 analysis executed on reproduction outputs reproduced all hypothesis conclusions and derived tables:

| Hypothesis | Canonical Status | Reproduced Status | Event Effects / Discrimination | Conclusion Match |
|---|---|---|---|---|
| **H1** | SUPPORTED | SUPPORTED | CONF_1: -0.5x, CONF_2: -0.5x, CONF_3: 0.0x | EXACT MATCH |
| **H2** | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | 0/2 boundary recovery; 2/2 full-thermal violation reduction | EXACT MATCH |
| **H3** | PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | CONF_1: 24/36, CONF_2: 23/36, CONF_3: 0/36; 0 reversals | EXACT MATCH |
| **H4** | NOT_ESTIMABLE | NOT_ESTIMABLE | Missing controlled forecast intervention traces | EXACT MATCH |
| **H5** | NOT_SUPPORTED | NOT_SUPPORTED | Dynamic margin does not beat fixed 0.10 margin | EXACT MATCH |

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
- **Total Archived Artifacts:** 46 files (content-addressed, no symlinks, relative portable paths).
- **Archive Manifest:** `data/archive/heattrace_v1_d5b3c86/archive_manifest.json`
- **Archive Manifest SHA-256:** `950d56120c39a8f71b4a6e4bb55d804c27fcec0c7da5d5c3f8be7be9f8d93ab4`
- **Self-Verification Command:** `python3 data/archive/heattrace_v1_d5b3c86/verify_archive.py` (Result: PASS, 46/46 verified).

---

## 9. Phase 11 Guardrail Verifications

- Canonical P8/P9/P10 artifact bytes remained completely unchanged: **CONFIRMED**.
- Zero v2 or Phase 12 work performed: **CONFIRMED**.
- Limited Result verdict preserved without upgrade: **CONFIRMED**.
- Equal-service and independence rules strictly preserved: **CONFIRMED**.

**Phase 11 Verdict:** **PASS**
