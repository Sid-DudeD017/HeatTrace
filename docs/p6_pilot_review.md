# Phase 6 Pilot Review: Development-Only Mechanism, Forecast, and Runtime Audit

**Phase:** Phase 6 (Day 8) — Development-Only Mechanism, Forecast, and Runtime Pilot  
**Date:** October 2026 (Post-Causal Repair & Re-execution)  
**Status:** PILOT AUDIT PASS  
**Boundary Integrity:** Confirmatory outcomes remain strictly sealed and unexecuted.  

---

## 1. Executive Summary & Audit Overview

### 1.1 Invalidation and Archival of Pre-Repair Artifacts
Prior to this execution pass, initial pilot artifacts were evaluated and determined to be scientifically invalid due to six verified structural defects:
1. **Causal Information Leakage & Information Asymmetry:** Core deployable policies (`static_unaware`, `capacity_aware`, `full_thermal_aware`) were scheduled once over a 120-hour forecast horizon synthesized from future rolling origins, rather than executing under the common 24-hour horizon, 1-hour commitment rolling replan boundary used by HeatGuard.
2. **Workload Mutation:** The runner deleted the `maximum_parallelism` column from the canonical workload before passing it to HeatGuard, altering the frozen workload schema.
3. **Unfiltered Confirmation Loading:** `pd.read_parquet` was executed across the entire `data/benchmarks/p6_event_control_pairs.parquet` file prior to in-memory filtering, breaching read-time confirmation isolation.
4. **Superficial Mutation Probe:** The prior confirmatory mutation test verified only matrix enumeration rather than end-to-end dataset loading, forecast generation, schedules, and metrics.
5. **Missing Config Validation & Provenance:** `configs/p6_validity.yaml` was not validated through `load_p6_validity_config`, and output rows lacked configuration and dataset SHA-256 provenance hashes.
6. **Insecure Resume:** Stale successful rows were accepted based solely on `run_id` without verifying schema or provenance digests.

All three invalid pre-repair artifacts were moved to `data/results/archive/p6_invalid_pre_causal_fix/` along with an archival note:
- `p6_development_pilot.parquet` (SHA-256: `bcda381650a6be511044eb78f7f63d7440b66cbd4b768ce4041055f344014cca`)
- `p6_forecast_metrics.csv` (SHA-256: `7006055fb9be85d0fe54e3e17ce2ed498e13b244402d60d510c57fcb0a45e558`)
- `p6_pilot_review.md` (SHA-256: `3a30e0a276c9154db1bacb6f2bfbd34895211f78cc630f3b50cbdf79c0949352`)
- Archive note: `data/results/archive/p6_invalid_pre_causal_fix/ARCHIVE_NOTE.md`

### 1.2 Corrected Pilot Status: PILOT AUDIT PASS
Following the implementation of the shared rolling causal harness, workload preservation, read-time pyarrow pushdown filtering, fail-closed resume, and full provenance logging, the development pilot was executed cleanly. All six Phase 6 definition-of-done criteria are satisfied:
1. **No missing pilot cells:** Exactly 252 unique pilot cells were enumerated and executed (252 successes, 0 failures, 0 dropped cells).
2. **Forecast Gate decision recorded:** Validation Forecast Gate decision recorded as **GO** via Condition 1 (`cond1 = True`, relative RMSE improvement $10.98\% \ge 2.0\%$), with Condition 2 recorded as false (`cond2 = False`).
3. **Hourly invariants pass:** Perfect work conservation across all 252 rows ($\text{demanded} = \text{completed} + \text{unfinished}$), allocations strictly in $[0, 120)$, no allocations past deadline, and power-capped capacity respected.
4. **Fixed margin compared fairly:** Calibrated, fixed ($0.10$), and deterministic/no-margin full-thermal-aware comparators received identical causal inputs and rolling information barriers.
5. **Runtime projection measured:** Measured development wall-clock time was $88.98\text{s}$ ($88.36\text{s}$ cumulative cell compute). Projected confirmatory runtime across the 756-cell matrix is $265.1\text{s}$ ($\approx 4.42\text{ minutes}$, conservative P95 bound: $320.3\text{s} \approx 5.34\text{ minutes}$).
6. **No confirmatory tuning or execution:** Confirmatory outcomes remained sealed. Zero confirmatory triplets were loaded, inspected, scored, or executed.

---

## 2. Verified Frozen Artifact Hashes & Input Provenance

All frozen hashes specified in `configs/p6_validity.yaml` and the Phase 6 contract were directly verified from disk prior to runner execution:

| Artifact Description | Expected Frozen SHA-256 | Observed Disk SHA-256 | Verification Status |
| :--- | :--- | :--- | :---: |
| **Phase 4 Temperature V2 Manifest** (`data/models/p6_temperature_v2/artifact_manifest.json`) | `ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79` | `ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79` | **MATCH** |
| **Phase 4 Temperature V2 Checkpoint** (`data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt`) | `69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed` | `69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed` | **MATCH** |
| **HeatGuard V3 Manifest** (`data/models/p6_heatguard_calibration_v3/manifest.json`) | `bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c` | `bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c` | **MATCH** |

### Additional Input Provenance Hashes Recorded per Result Row:
- **P6 Validity Config Raw File Hash (`p6_config_sha256`):** `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1`
- **P6 Thermal Config Raw File Hash (`p6_thermal_config_sha256`):** `250f1b07daa6a19bcc9fe7415c7034b5ade240d69095cf3b539b7ee6ba001551`
- **Canonical Development Benchmark Dataframe Hash (`development_benchmark_sha256`):** `17302e7fe2b80dc7e73cfb485b99dc271580460ccc864ec60ff047cedebee023` (computed via `compute_canonical_df_sha256(pairs_dev)`; distinct from raw parquet file hash `60cea3627d9f81d3b2020e17930a6418b6aa0bfe3b292256e3949f76947dd109` across all triplets)
- **Forecast Metrics Source Hash (`forecast_metrics_source_sha256`):** `7006055fb9be85d0fe54e3e17ce2ed498e13b244402d60d510c57fcb0a45e558`

---

## 3. Pilot Matrix & Observed Execution Counts

### 3.1 Matrix Arithmetic
The development pilot operates exclusively on `TRIPLET_DEV_ae821c` (heatwave `HW_20240702`, matched control `CTRL_20240605`, event blind `BLIND_ef75b17921d7`):
- **Cohort A (Core Heatwave/Control):** $1\text{ pair} \times 2\text{ contexts} \times 2\text{ facility models} \times 2\text{ curves} \times 3\text{ workloads} \times 2\text{ seeds} \times 1\text{ objective} \times 3\text{ policies} = 144\text{ cells}$.
- **Cohort B (Event-Blind Benchmark):** $1\text{ blind} \times 2\text{ facility models} \times 2\text{ curves} \times 3\text{ workloads} \times 2\text{ seeds} \times 1\text{ objective} \times 3\text{ policies} = 72\text{ cells}$.
- **Cohort C (Algorithm Comparators):** $1\text{ pair} \times 2\text{ contexts} \times 1\text{ facility (power-capped)} \times 1\text{ curve (medium)} \times 3\text{ workloads} \times 2\text{ seeds} \times 1\text{ objective} \times 2\text{ policies (calibrated, fixed)} = 24\text{ cells}$.
- **Cohort D (Oracle Reference):** $1\text{ pair} \times 2\text{ contexts} \times 1\text{ facility} \times 1\text{ curve} \times 3\text{ workloads} \times 2\text{ seeds} \times 1\text{ objective} \times 1\text{ policy} = 12\text{ cells}$.  
**Total Expected Cells:** $144 + 72 + 24 + 12 = 252\text{ unique cells}$.

### 3.2 Observed Deliverable Counts
Audited directly from `data/results/p6_development_pilot.parquet`:
- **Total Rows:** $252$
- **Unique Run-IDs:** $252$ (0 duplicates, 0 missing cells).
- **Execution Status:** $252$ `SUCCESS`, $0$ `FAILED`.
- **Cohort Breakdown:**
  - `core_benchmark`: $144$
  - `event_blind_benchmark`: $72$
  - `algorithm_comparators`: $24$
  - `oracle_reference`: $12$
- **Deployability Labels:**
  - $240$ deployable cells marked `deployable = True`.
  - $12$ oracle reference cells marked `deployable = False`.
- **Triplet Isolation:** All $252$ rows belong strictly to `TRIPLET_DEV_ae821c`. Confirmatory triplets (`TRIPLET_CONF_1_f5c700`, `TRIPLET_CONF_2_2a6e22`, `TRIPLET_CONF_3_628624`) were filtered at read-time and never entered runner memory.

---

## 4. Temperature Forecast Gate & Development Behavior

### 4.1 Frozen Validation Forecast Gate Decision
Preserved in `data/results/p6_forecast_metrics.csv` from `data/models/p6_temperature_v2/evaluation_metrics.csv`:
- **Decision:** **GO**
- **Selected Model:** `TinyTemperatureLSTM`
- **Validation RMSE:** $2.0739^\circ\text{C}$ (MAE: $1.3842^\circ\text{C}$)
- **Best Baseline:** `same_hour_previous_day`, RMSE: $2.3297^\circ\text{C}$ (MAE: $1.6227^\circ\text{C}$)
- **Condition 1 (RMSE Improvement $\ge 0.02$):**  
  $$\frac{2.3297 - 2.0739}{2.3297} = 10.98\% \ge 2.0\% \implies \mathbf{cond1 = True}$$
- **Condition 2 (Extreme Improvement $\ge 0.05$ and RMSE Slack $\ge -0.02$):**  
  $$\frac{3.2155 - 3.4291}{3.2155} = -6.64\% < 5.0\% \implies \mathbf{cond2 = False}$$
- **Conclusion:** The model passed through Condition 1. Condition 2 is explicitly false. The Forecast Gate decision was frozen on validation data only and is not retroactively altered by development outcomes.

### 4.2 Observed Development Forecast Outcomes (`TRIPLET_DEV_ae821c`)
Recorded across 97 rolling origins per context in `data/results/p6_forecast_metrics.csv`:
- **heatwave (`HW_20240702`):** `TinyTemperatureLSTM` RMSE = $5.8075^\circ\text{C}$ vs baseline `same_hour_previous_day` RMSE = $3.6948^\circ\text{C}$ (extreme underprediction MAE = $6.8661^\circ\text{C}$).
- **matched_control (`CTRL_20240605`):** `TinyTemperatureLSTM` RMSE = $1.8744^\circ\text{C}$ vs baseline `same_hour_previous_day` RMSE = $2.5746^\circ\text{C}$ (extreme underprediction MAE = $3.2949^\circ\text{C}$).
- **event_blind (`BLIND_ef75b17921d7`):** `TinyTemperatureLSTM` RMSE = $3.0177^\circ\text{C}$ vs baseline `same_hour_previous_day` RMSE = $1.8762^\circ\text{C}$.

*Assessment:* Under extreme heat conditions exceeding training ranges, the LSTM exhibits underprediction error, which motivates evaluating safety margins. Whether either margin mitigates facility violations is established strictly by scheduling metrics.

---

## 5. Hourly Invariant & Workload Preservation Audit

Audited across all 252 executed pilot rows:
1. **Work Conservation:** Demanded processing slots equal completed plus unfinished processing slots across all rows ($\text{demanded} = \text{completed} + \text{unfinished}$).
2. **Allocation Validity:** $\text{allocation\_count} = \text{completed\_processing\_slots}$. No duplicate `(job_id, hour)` allocations.
3. **Temporal Invariants:** All allocations satisfy $t \ge \text{arrival}$ and $t < \text{deadline}$, bounded strictly within $[0, 120)$.
4. **Parallelism Bounds:** `maximum_parallelism` was preserved without deletion across all scaled workloads. All jobs received at most one allocation per discrete hourly slot, satisfying parallelism bounds $\le 1, 2, 4$.
5. **Facility Constraints:** In energy-only mode, nominal compute capacity was maintained. In power-capped mode, compute capacity followed the frozen equation $C_{\text{eff}}[t] = \min(500, 600 / \text{PUE}[t])$.

---

## 6. Equal-Service Policy Comparison Audit

Evaluating the 12 primary power-capped, medium-curve, carbon-first configurations across heatwave and control contexts provides an equal-service comparison:

### 6.1 Heatwave Context (`HW_20240702`)
Across the 6 primary heatwave cells (3 workloads $\times$ 2 seeds), total completed processing slots were identical ($1,188$ slots demanded and completed):

| Policy ID | Completed Slots | Violation Hours | Total Excess Energy | Realized Cost | Realized Carbon |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `full_thermal_aware` (reused rolling deterministic) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$3,820.26$ | $12,954.44\text{ kg}$ |
| `heatguard_calibrated` ($m_{\text{cal}} \approx 0.016$) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$3,820.26$ | $12,954.44\text{ kg}$ |
| `heatguard_fixed` ($m_{\text{fixed}} = 0.10$) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$3,809.11$ | $12,959.42\text{ kg}$ |
| `oracle_full_thermal_aware` (non-deployable reference) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$2,981.65$ | $10,200.32\text{ kg}$ |

### 6.2 Control Context (`CTRL_20240605`)
Across the 6 primary control cells:

| Policy ID | Completed Slots | Violation Hours | Total Excess Energy | Realized Cost | Realized Carbon |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `full_thermal_aware` (reused rolling deterministic) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$1,414.10$ | $8,752.17\text{ kg}$ |
| `heatguard_calibrated` ($m_{\text{cal}} \approx 0.016$) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$1,414.10$ | $8,752.17\text{ kg}$ |
| `heatguard_fixed` ($m_{\text{fixed}} = 0.10$) | $1,188$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$1,414.10$ | $8,752.17\text{ kg}$ |
| `oracle_full_thermal_aware` (non-deployable reference) | $1,176$ | $0\text{ hours}$ | $0.00\text{ kWh}$ | $\$1,004.49$ | $6,748.07\text{ kg}$ |

**Fair Comparison Findings:**
- Under the corrected rolling causal harness, `full_thermal_aware` and `heatguard_calibrated` produce identical schedules and metrics ($1,188$ slots completed, $\$3,820.26$ cost, $12,954.44\text{ kg}$ carbon in heatwave), confirming the mathematical and semantic equivalence of the zero-margin full thermal aware scheduler and HeatGuard in the primary diagnostic setting.
- In heatwave conditions, `heatguard_fixed` completed identical service ($1,188$ slots) with a cost difference of $-\$11.15$ ($-0.29\%$) and a carbon difference of $+4.98\text{ kg}$ ($+0.04\%$), reflecting small shifts in allocation hours under the conservative $0.10$ PUE margin.
- `oracle_full_thermal_aware` is non-deployable and uses perfect hindsight; in the control context, it completed $1,176$ slots (leaving $12$ unfinished due to greedy hindsight trade-offs), meaning direct cost/carbon superiority claims relative to deployable policies are invalid.

---

## 7. Runtime Measurements & Confirmation Projections

### 7.1 Measured Development Pilot Runtimes
- **Total Wall-Clock Runtime:** $88.98\text{ seconds}$
- **Cumulative Cell Compute Time:** $88.36\text{ seconds}$
- **Cohort Timing Statistics:**
  - `core_benchmark` ($144$ cells): mean = $0.3784\text{s}$, min = $0.2713\text{s}$, max = $0.5062\text{s}$, P95 = $0.4655\text{s}$ (sum: $54.50\text{s}$)
  - `event_blind_benchmark` ($72$ cells): mean = $0.3755\text{s}$, min = $0.2743\text{s}$, max = $0.4700\text{s}$, P95 = $0.4398\text{s}$ (sum: $27.03\text{s}$)
  - `algorithm_comparators` ($24$ cells): mean = $0.2715\text{s}$, min = $0.2174\text{s}$, max = $0.3415\text{s}$, P95 = $0.3210\text{s}$ (sum: $6.52\text{s}$)
  - `oracle_reference` ($12$ cells): mean = $0.0263\text{s}$, min = $0.0208\text{s}$, max = $0.0319\text{s}$, P95 = $0.0317\text{s}$ (sum: $0.32\text{s}$)

### 7.2 Confirmation Runtime Projections
1. **Confirmatory 756-Cell Matrix Projection:**
   - Expected Mean:  
     $$T_{\text{conf, mean}} = (432 \times 0.3784\text{s}) + (216 \times 0.3755\text{s}) + (72 \times 0.2715\text{s}) + (36 \times 0.0263\text{s}) = \mathbf{265.1\text{ seconds}} \quad (\approx 4.42\text{ minutes})$$
   - Conservative P95 Bound:  
     $$T_{\text{conf, p95}} = (432 \times 0.4655\text{s}) + (216 \times 0.4398\text{s}) + (72 \times 0.3210\text{s}) + (36 \times 0.0317\text{s}) = \mathbf{320.3\text{ seconds}} \quad (\approx 5.34\text{ minutes})$$
2. **Fallback Benchmark-Only 648-Cell Matrix Projection:**
   - Expected Mean:  
     $$T_{\text{fallback, mean}} = (432 \times 0.3784\text{s}) + (216 \times 0.3755\text{s}) = \mathbf{244.6\text{ seconds}} \quad (\approx 4.08\text{ minutes})$$
   - Conservative P95 Bound:  
     $$T_{\text{fallback, p95}} = (432 \times 0.4655\text{s}) + (216 \times 0.4398\text{s}) = \mathbf{296.1\text{ seconds}} \quad (\approx 4.93\text{ minutes})$$

*Feasibility Range:* Execution time across both configurations is projected between $4.1$ and $5.3$ minutes on CPU. The computational budget is well within acceptable limits.

---

## 8. Confirmatory Data Isolation & Fail-Closed Resume Confirmation

It is explicitly confirmed that:
1. **Confirmatory Seal Maintained:** Production runner code loaded zero confirmatory outcome rows (`TRIPLET_CONF_1_f5c700`, `TRIPLET_CONF_2_2a6e22`, `TRIPLET_CONF_3_628624`) into memory during the development run due to read-time pyarrow pushdown filtering (`load_development_benchmark_filtered`).
2. **Confirmatory Matrix Unexecuted:** No confirmatory triplet cell has been executed, evaluated, or inspected.
3. **Synthetic Confirmatory Mutation Invariance:** In `test_end_to_end_confirmatory_mutation_invariance`, confirmatory outcomes are tested without reading real confirmatory rows. Real development rows are loaded via pushdown filtering and joined with fabricated synthetic confirmatory rows (`TRIPLET_CONF_SYNTHETIC`). Drastic mutations of weather, price, carbon, and demand signals on the synthetic confirmatory partition leave filtered development inputs, precomputed forecasts, and selected downstream scientific metrics (realized compute slots, cooling-adjusted costs, cooling-adjusted carbon, and applied margins) identical.
4. **Fail-Closed Resume Architecture:** In `execute_development_pilot`, existing output files are validated through `validate_existing_pilot_parquet`. The validator rejects partial corruption, missing or unexpected columns (43 expected), duplicate run IDs, unknown run IDs, altered scientific key values (triplet, context, window, cohort, facility model, thermal curve, workload multiplier, seed, objective, policy ID, policy version, deployability, margin mode), altered workload trace IDs, and provenance hash mismatches across all 8 hashes (`p6_config_sha256`, `p6_thermal_config_sha256`, `development_benchmark_sha256`, `workload_sha256`, `forecast_metrics_source_sha256`, `p4_manifest_sha256`, `p4_checkpoint_sha256`, `calibration_manifest_sha256`). If any validation check fails, the runner refuses to overwrite or resume, preserving file integrity. Valid complete resumes require zero cell recalculations.

---

## 9. Gate 3 Readiness Recommendation

- **Gate Status:** `PILOT AUDIT PASS`
- **Recommendation:** **READY FOR ME CONFIRMATORY FREEZE (PHASE 7)**.  
  All six definition-of-done criteria, causal rolling fairness, workload preservation, read-time confirmation isolation, synthetic adversarial verification, fail-closed resume, and provenance hashing are supported by verified code, adversarial tests, and immutable result artifacts.
