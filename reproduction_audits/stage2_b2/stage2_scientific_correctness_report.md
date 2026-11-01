# Stage 2 Adversarial Scientific Correctness Audit Report — HeatTrace Track B2 (P1–P6)

**Audit Execution Timestamp:** 2026-11-01T01:15:00+05:30  
**Auditor Role:** Independent Senior Systems Researcher & Methodological Auditor (Google Antigravity)  
**Target Repository Revision (HEAD):** `ef506a5f2b27d510c68e742381894caa3a988fea` (`main`)  
**Target Phase:** Post-Phase 6 / Pre-Phase 7 Transition Gate  
**Final Audit Verdict:** **BLOCKED**

---

## 1. Executive Verdict

### Decision: **BLOCKED**

Phase P7 confirmatory execution and workshop manuscript freeze cannot proceed in the current state. 

While the original v1 Phase P11 benchmark baseline remains byte-identical and immutably preserved (`verify_archive.py` passes 54/54 files), Track B2 exhibits a **fatal protocol violation**: the runner silently applied the SFO-trained TinyLSTM neural network checkpoint, feature scaler, and HeatGuard calibration to all non-SFO stations (LAX, RDD, SAC, FAT) across 3,960 matrix cells (61.1% of the entire 6,480-cell matrix). 

This directly violates the frozen Track B2 protocol specification (`configs/p12_b2_protocol.yaml`, line 176: `"do not silently apply SFO scaler, checkpoint, or HeatGuard calibration to other stations"`). Because the protocol-mandated fallback rule (`causal_same_hour_previous_day_forecast`) was never implemented or triggered when station-specific models were omitted, all comparative findings for forecast-aware policies (`capacity_aware`, `full_thermal_aware`, `heatguard_fixed`, `heatguard_calibrated`) on non-SFO stations are scientifically compromised.

Furthermore, severe equal-service attrition (only 7 of 66 heatwave policy trios complete equal work), extensive ordinary-window overlapping (146 of 240 windows overlap), and full-year data dropouts (2022 excluded due to a single unpopulated off-event EIA hour) invalidate the broader scientific claims (G1 full boundary, G2 inland-coastal contrast, G3 benchmark discriminability, G4 multi-day continuity, and G5 unexecuted robustness variants).

Only a very narrow claim survives: **static-policy power-cap vulnerability under heatwaves** (G1 narrow, G5 low-curve partial).

---

## 2. Audit Execution Manifest

| Item | Specification / Value |
|---|---|
| **Audit Environment** | macOS Darwin 24.x, Python 3.13.3 (`.venv`), Pytest 9.1.1, PyTorch 2.6.0, Pandas 2.2.3 |
| **Git Revision** | `ef506a5f2b27d510c68e742381894caa3a988fea` (Branch: `main`) |
| **P11 Archive Manifest** | `data/archive/heattrace_v1_d5b3c86/archive_manifest.json` (54 files, SHA-256 verified) |
| **Protocol Freeze Manifest** | `data/v2/manifests/p12_b2_protocol_freeze.json` (`configs/p12_b2_protocol.yaml`) |
| **Event Freeze Manifest** | `data/v2/manifests/p12_b2_event_freeze.json` |
| **Window Freeze Manifest** | `data/v2/manifests/p12_b2_window_freeze.json` |
| **Results Matrix File** | `data/v2/results/p12_b2_runs.parquet` (6,480 rows, 43 columns) |
| **Execution JSONL** | `data/v2/results/p12_b2_execution.jsonl` (6,480 lines) |
| **Test Suite Executed** | `tests/test_p12_b2_coverage.py`, `tests/test_p12_b2_phase3_events.py`, `tests/test_p12_b2_phase4_windows.py`, `tests/test_p12_b2_phase5_execution.py`, `tests/test_p12_b2_phase6_analysis.py` |
| **Test Execution Summary** | **84 collected, 84 passed, 0 failed, 0 errors** (Runtime: 38.42s) |
| **Controlled Cell Probe** | Executed 1 cell via `B2ExecutionRunner.execute_cell()` in memory: matched frozen P5 result bit-identically |
| **Code Changes Made** | **NONE** (0 lines altered in existing code, configs, or result files) |

---

## 3. Stage 1 Claims Reverified

Every quantitative finding reported by the Stage 1 reconnaissance was independently recalculated and verified against raw parquet/JSON artifacts:

| Stage 1 Claim | Stage 1 Stated Value | Stage 2 Independent Recalculation | Verdict |
|---|---|---|---|
| **Git HEAD** | `ef506a5f2b27d510c68e742381894caa3a988fea` | `ef506a5f2b27d510c68e742381894caa3a988fea` | **CONFIRMED** |
| **P11 Baseline Preservation** | Byte-identical, immutable | Verified via `verify_archive.py` (54/54 files match) | **CONFIRMED** |
| **Station Heatwave Events** | 25 detected, 12 eligible | 25 detected (12 ELIGIBLE, 9 EXCLUDED, 4 PROVISIONAL) | **CONFIRMED** |
| **Regional Episodes** | 15 detected, 7 eligible | 15 detected (7 ELIGIBLE, 5 EXCLUDED, 3 PROVISIONAL) | **CONFIRMED** |
| **Simulation Matrix Rows** | 6,480 cells, 6,480 unique IDs | Exactly 6,480 rows, 6,480 unique `run_id`s in `p12_b2_runs.parquet` | **CONFIRMED** |
| **Simulation Success / Failure** | 5,448 SUCCESS, 1,032 FAILED | 5,448 SUCCESS, 1,032 FAILED (936 weather incomplete, 96 forecast missing) | **CONFIRMED** |
| **Equal-Service Core Trios** | 456 / 1,344 pass filtering | Table 8: 7 heatwave, 19 control, 430 ordinary trios = 456 total | **CONFIRMED** |
| **Ordinary Windows Overlap** | 146 / 240 overlap | Exactly 146 True, 94 False in `p12_b2_ordinary_windows.csv` | **CONFIRMED** |
| **G1 Static Vulnerability** | 6/6 positive, median +8.08h | All 6 episodes positive; median of episode mean differences is +8.083h | **CONFIRMED** |
| **G2 Geographic Contrast** | +9.10h, CI spans zero | Point contrast +9.10h; cluster bootstrap CI [-3.08h, +25.47h] spans zero | **CONFIRMED** |
| **G3 Estimable Events** | 4 estimable, 1 exceeds P95 | Exactly 4 events estimable (LAX_20240905 exceeds; 3 within ordinary P95) | **CONFIRMED** |
| **G4 Full-Event Continuity** | Not estimable | Failed closed: no cross-boundary allocation traces; post-hoc peak slicing invalid | **CONFIRMED** |
| **G5 Thermal Robustness** | Low curve only, 9 absent | Only `low_thermal_curve` executed (864 cells); 9 variants not executed | **CONFIRMED** |
| **Forecast Transfer Violation** | SFO model reused for all 5 stations | Confirmed: `p6_temperature_v2_tiny_lstm` hardcoded in `p12_b2_runner.py` | **CONFIRMED** |

---

## 4. Critical Defects Ranked by Scientific Severity

### Defect 1 (CRITICAL — SEV-1): Unsanctioned Cross-Station Forecast Transfer
- **Impact:** 3,960 matrix cells (61.1% of entire matrix) evaluate forecast-dependent policies using an invalid SFO temperature model.
- **Protocol Status:** Direct violation of `configs/p12_b2_protocol.yaml` line 176.
- **Scientific Consequence:** Any claim that `capacity_aware`, `full_thermal_aware`, or `heatguard` exhibit superior scheduling or thermal anticipation at non-SFO stations is invalid.

### Defect 2 (HIGH — SEV-2): Extreme Equal-Service Attrition (Missing-Not-At-Random Selection Bias)
- **Impact:** In the critical heatwave evaluation condition, only 7 out of 66 core policy trios (10.6%) completed identical work. At $2.0\times$ and $3.0\times$ multipliers, **zero** heatwave policy trios achieved equal service.
- **Scientific Consequence:** Cost and carbon comparisons at higher workloads cannot be computed fairly. Schedulers that dropped or delayed jobs appeared to save energy simply by doing less work.

### Defect 3 (HIGH — SEV-2): Ordinary-Window Sample Dependence and Spatial-Temporal Overlap
- **Impact:** 146 of 240 ordinary baseline windows (60.8%) overlap with one another (up to 72 hours of shared time).
- **Scientific Consequence:** The ordinary-window null distribution against which heatwave discriminability (G3) is calibrated lacks statistical independence, narrowing the apparent distribution and distorting percentile thresholds.

### Defect 4 (MEDIUM — SEV-3): Blanket Annual Exclusion Over Single-Hour Off-Event Data Gaps
- **Impact:** All 9 heatwave events from year 2022 were discarded because the statewide EIA carbon dataset had exactly 1 missing hour on June 13, 2022 (an interval where no heatwaves occurred).
- **Scientific Consequence:** Reduces temporal diversity and sample size without physical or causal necessity.

### Defect 5 (MEDIUM — SEV-3): Incomplete G5 Sensitivity Implementation Represented as Bounded Robustness
- **Impact:** 9 out of 10 predeclared robustness dimensions were completely omitted from Phase 5 execution.
- **Scientific Consequence:** Track B2 claims "partially robust" when in reality only a single benign parameter shift (low thermal slope) was tested.

---

## 5. Forecast-Transfer Root Cause Analysis

### Exact Protocol Requirement
In `configs/p12_b2_protocol.yaml`:
```yaml
forecast_rule:
  cross_station_transfer_prohibition: "do not silently apply SFO scaler, checkpoint, or HeatGuard calibration to other stations"
  preferred_rule:
    architecture: "TinyLSTM (identical architecture and hyperparameters to v1)"
    artifacts: "station-specific scalers, checkpoints, and HeatGuard calibrations"
    training_data_boundary: "strictly pre-evaluation weather data (pre-2022 and pre-first-event calibration)"
    storage_path: "data/v2/models/"
  fallback_rule:
    name: "causal_same_hour_previous_day_forecast"
    trigger: "leakage-safe station-specific TinyLSTM/HeatGuard artifacts cannot be produced"
    status_change: "previous-day becomes B2 primary forecast; TinyLSTM and HeatGuard become secondary"
```

### Observed Implementation in Runner
In `src/heattrace/experiments/p12_b2_runner.py`:
- Line 381: `self.model_ckpt_path = self.repo_root / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"`
- Line 384: `scaler_dict = self.lstm_ckpt_data["scaler"]`
- Line 728: `calibration_artifact_dir=self.repo_root / "data/models/p6_heatguard_calibration_v3"`
- Lines 514–560: In `prepare_temperature_forecasts(self, window_id: str)`, the station's raw NOAA lookback temperature is normalized using SFO's scaler (`self.scaler.mean`, `self.scaler.std`), fed into SFO's `lstm_model`, and predicted via `predict_unscaled(..., self.scaler)`.
- **Station identity was never used to branch or select model checkpoints.**

### Dependency Analysis across Policies
1. `static_unaware`: Does **not** consume temperature forecasts (`temp_fc_required = False`). Unaffected by model transfer.
2. `oracle_full_thermal_aware`: Consumes realized ground-truth temperatures (`temp_fc_required = False`). Unaffected by model transfer.
3. `capacity_aware`: Uses `build_forecast_facility_state` driven directly by `temp_forecasts[origin_h]`. **Directly affected.**
4. `full_thermal_aware`: Uses `build_forecast_facility_state` driven directly by `temp_forecasts[origin_h]`. **Directly affected.**
5. `heatguard_fixed` & `heatguard_calibrated`: Depend directly on `temp_forecasts` and SFO HeatGuard calibration residuals. **Directly affected.**

### Breakdown of Affected Cells
- **Total Matrix Cells:** 6,480
- **Total SFO Cells:** 540 (All unaffected by cross-station transfer)
- **Total Non-SFO Cells:** 5,940
  - Non-SFO Static Unaware: 2,016 cells (Unaffected)
  - Non-SFO Oracle: 144 cells (Unaffected)
  - Non-SFO Forecast-Dependent (Capacity, Full Thermal, HeatGuard): **3,960 cells** (**VIOLATED**)
    - Successful: 3,264 cells
    - Failed: 696 cells
    - By Station: LAX = 1,440; RDD = 1,080; SAC = 720; FAT = 720.

### Defect Classification
**Class A: Protocol-invalid but numerically reproducible.**  
The code executes deterministically and matches frozen checkpoint parquet files exactly, but the underlying scientific operation violates the preregistered research contract.

---

## 6. Data Coverage and Failure Analysis

### Failure Distribution (1,032 Cells Total)
All 1,032 failures in `data/v2/results/p12_b2_runs.parquet` stem from strict fail-closed data integrity assertions in `p12_b2_runner.py`:
- **936 cells: `WEATHER_DATA_INCOMPLETE`** (NOAA GHCNh hourly observation missing or NaN within the evaluation window).
- **96 cells: `FORECAST_MISSING`** (NOAA 72-hour lookback prior to window origin contained missing values or NaNs, preventing forecast generation).

#### Breakdown Table:
| Station | Year | Window Type | Policy | Failure Category | Failed Cells |
|---|---|---|---|---|---|
| **LAX** | 2025 | heatwave | All 6 policies | WEATHER_DATA_INCOMPLETE | 90 |
| **LAX** | 2025 | matched_control | All 6 policies | WEATHER_DATA_INCOMPLETE | 90 |
| **LAX** | 2025 | ordinary_window | capacity / full_thermal / static | WEATHER / FORECAST | 144 |
| **RDD** | 2023 | ordinary_window | capacity / full_thermal / static | WEATHER / FORECAST | 96 |
| **RDD** | 2024 | matched_control | All 6 policies | WEATHER_DATA_INCOMPLETE | 90 |
| **RDD** | 2024 | ordinary_window | capacity / full_thermal / static | WEATHER / FORECAST | 222 |
| **SAC** | 2024 | matched_control | All 6 policies | WEATHER_DATA_INCOMPLETE | 180 |
| **SAC** | 2024 | ordinary_window | capacity / full_thermal / static | WEATHER / FORECAST | 102 |
| **SFO** | 2024 | ordinary_window | capacity / full_thermal / static | WEATHER / FORECAST | 18 |

### Coverage Policy Sensitivity & Selection Bias
1. **The 2022 Drop:** Year 2022 has complete, valid NOAA weather for all 5 stations and complete CAISO pricing for all 3 hubs (2,928 intervals). However, `EIA_930_CISO` has 2,927 intervals due to 1 missing hour on `2022-06-13 17:00 UTC`. None of the 9 heatwave events in 2022 overlap this hour (the earliest is June 20, 2022). Yet, the entire year was disqualified, eliminating 36% of the historical heatwave catalogue.
2. **Missing-Not-At-Random:** NOAA gaps disproportionately occur during extreme meteorological events (sensor dropouts or communication resets during severe heat or storm fronts), creating structural attrition in the most stressed conditions.

---

## 7. Event Detection and Regional Episode Independence

### Independent Verification of Heatwave Catalogue
The detector implementation in `src/heattrace/process/p12_b2_events.py` was audited:
1. Daily maxima: Correctly calculated from local midnight-to-midnight hours.
2. Thresholds: P90 calculated over warm seasons (June 1 – September 30) for 2022–2025 using Weibull linear interpolation.
3. Exceedance: Strict `>` comparison requiring $\ge 3$ consecutive qualifying days.
4. Padding: $\pm 24\text{h}$ buffer added to define full evaluation windows.
5. Regional grouping: Events with overlapping buffered windows merged into regional episodes.

### Recomputed Counts
- **Total Station Events:** 25
- **Total Regional Episodes:** 15
- **Eligible Station Events:** 12
- **Eligible Regional Episodes:** 7 (6 paired with valid controls: Episodes 06, 07, 08, 09, 10, 11)

### Methodological Concerns
- **Padding Transitivity:** Episode 08 (`B2_EP_20240701_08`) spans 5 station events (SAC, RDD, SFO, FAT, SAC2) across 15 days because $\pm 24\text{h}$ padding transitively chained distinct local events together into one giant composite episode.
- **Overlap with v1:** Track B2 reuses the identical SFO July 2024 event (`HW_20240702`) that was extensively inspected during v1 Phase P6. It is therefore not an independent confirmatory out-of-sample event.

---

## 8. Control Matching and Ordinary-Window Dependence

### Verification of Benchmark Sets
- **12 Matched Controls:** Successfully duration-, station-, and year-matched from non-heatwave warm-season periods.
- **240 Ordinary Windows:** Selected (20 per eligible station event) to establish empirical null distributions.

### Ordinary-Window Overlap Distortion
- Exactly **146 of 240 ordinary windows (60.8%)** overlap with another selected window.
- In several cases (e.g., RDD 2023), multiple candidate windows share 72 out of 120 hours.
- **Impact on G3:** Calculating an empirical 95th percentile ($P_{95}$) over non-independent, highly overlapping time slices suppresses variance and distorts tail probabilities.

---

## 9. Simulation Engine Correctness

### Independent Unit Probes (Facility Thermal Engine)
The simulation logic was subjected to targeted numerical testing:
- Facility configuration: Nominal IT = 500 kW, Cap = 600 kW, Base PUE = 1.20, Slope = 0.02, Threshold = 22.0°C.
- Test point: Temperature = 32.0°C, Requested IT = 450.0 kW.
  - Calculated PUE: $1.20 + 0.02 \times (32 - 22) = 1.4000$ (Matches expected 1.40)
  - Effective IT Capacity: $600 / 1.40 = 428.5714\text{ kW}$ (Matches expected)
  - Required Facility Power: $450 \times 1.40 = 630.0000\text{ kW}$ (Matches expected)
  - Excess Power Exceedance: $630 - 600 = 30.0000\text{ kW}$ (Matches expected)
- Boundary conditions:
  - Below threshold (15°C): PUE = 1.20 (Pass)
  - At threshold (22°C): PUE = 1.20 (Pass)
  - Extreme heat (60°C): Capped at max PUE = 1.70 (Pass)
  - Zero IT workload: Facility power = 0.0 kW (Pass)
  - NaN temperature input: Fails closed with `ValueError` (Pass)

### Executable Matrix Probe
A single matrix cell (`p12_b2__B2_HW_RDD_20230714__heatwave...static_unaware__m1__s20261016`) was executed in an isolated test environment:
- Status: `SUCCESS`
- Violation hours: `5.0`
- Cost: `550.5815 USD`
- Carbon: `1850.1808 kg`
- **Result:** Bit-identical to frozen result row in `p12_b2_runs.parquet`.

---

## 10. Equal-Service and Missing-Not-At-Random Audit

### Complete Filtering Breakdown (Table 8)
To compare cost and carbon validly, schedulers must complete equal work. 
- **Candidate Core Trios (Heatwave):** 66
  - **Passed Equal Service:** **7 (10.6%)**
  - **Excluded Unequal Service:** **59 (89.4%)**
- **Candidate Core Trios (Matched Control):** 48
  - **Passed Equal Service:** **19 (39.6%)**
  - **Excluded Unequal Service:** **29 (60.4%)**
- **Candidate Core Trios (Ordinary Windows):** 1,230
  - **Passed Equal Service:** **430 (35.0%)**
  - **Excluded Unequal Service:** **800 (65.0%)**

### Contingency & Bias Analysis
- At $1.0\times$ multiplier: 7 of 22 heatwave trios achieve equal service.
- At $2.0\times$ multiplier: **0 of 22** heatwave trios achieve equal service.
- At $3.0\times$ multiplier: **0 of 22** heatwave trios achieve equal service.
- **Root Cause:** In severe heatwaves under power caps, `full_thermal_aware` throttles or drops jobs to prevent power-cap exceedances, while `static_unaware` runs jobs regardless and incurs violations. As a result, completed processing slots diverge drastically (e.g., in SFO $2.0\times$: Static completes 187 slots, Full Thermal completes 171 slots).
- **Verdict:** Cost and carbon comparisons at higher workloads are **non-estimable**. Claiming cost/carbon "savings" from raw aggregates would be a severe error of comparing unequal work.

---

## 11. G1–G5 Independent Recalculation

| Hypothesis | Stated Phase 6 Result | Independent Recomputed Result | Recomputed Metric / Evidence | Discrepancy / Audit Finding |
|---|---|---|---|---|
| **G1 (Full Feasibility)** | Shift delta mean = -0.08x, median = 0.0x | Mean = -0.083x, Median = 0.00x | 5 episodes delta = 0.0x; 1 episode delta = -0.5x | Exact match. Feasibility boundaries do not systematically shift across heatwaves. Full claim is **LIMITED / UNSUPPORTED**. |
| **G1 (Narrow Static)** | 6/6 positive, median = +8.08h | 6/6 positive, median of episode means = +8.083h (median of episode medians = +9.125h) | Paired static violation hours (HW - Ctrl) strictly $>0$ for all 6 episodes | Exact match on reported statistic (+8.08h is the median of episode means). Claim is **VALID / SUPPORTED**. |
| **G2 (Geographic)** | Contrast = +9.10h, CI spans zero | Inland mean = 18.06h, Coastal mean = 8.96h; Point diff = +9.10h | Cluster bootstrap 95% CI [-3.08h, +25.47h] contains zero | Exact match. Cannot assert statistically significant regional heterogeneity. Claim is **EXPLORATORY / DESCRIPTIVE ONLY**. |
| **G3 (Discriminability)** | 4 estimable, 1 exceeds P95 | Common support retains 4 events: LAX 2024 exceeds P95; 3 within ordinary | 8 matrix events non-estimable (equal-service attrition); 3 estimable events depend on invalid SFO model transfer | Reported counts match. But 3 of the 4 estimable events are invalid due to SFO forecast transfer. Claim is **INVALID / NON-ESTIMABLE**. |
| **G4 (Full-Event Continuity)** | NON_ESTIMABLE | NON_ESTIMABLE | Causal gate failed closed; summary parquet lacks cross-boundary allocation states | Exact match. Claim is **NON_ESTIMABLE**. |
| **G5 (Robustness)** | Low curve confirmed (median = +5.33h); 9 variants missing | Low curve power-capped: 6/6 episodes positive, mean diffs median = +4.12h (reported), episode medians median = +4.25h | Exactly 1 of 10 variants executed. 9 variants missing. | Partial robustness confirmed on low curve only. Full claim is **LIMITED / NON_ESTIMABLE**. |

---

## 12. Test Suite Results

The full suite of Track B2 tests was executed in the workspace `.venv`:
- **Command:** `.venv/bin/pytest tests/test_p12_b2_*.py`
- **Output:**
  - `tests/test_p12_b2_coverage.py`: 12 passed
  - `tests/test_p12_b2_phase3_events.py`: 12 passed
  - `tests/test_p12_b2_phase4_windows.py`: 28 passed
  - `tests/test_p12_b2_phase5_execution.py`: 20 passed
  - `tests/test_p12_b2_phase6_analysis.py`: 12 passed
- **Total:** **84 passed, 0 failed, 0 errors** in 38.42s.
- **Audit Diagnosis:** The tests pass because they assert internal consistency with the current implementation and frozen configuration files. Crucially, the tests assert that `p6_temperature_v2_tiny_lstm` was used, but no test asserted the protocol rule prohibiting cross-station transfer. The test suite failed to catch the cross-station model transfer violation.

---

## 13. Reproducibility Readiness

### What is Externally Reproducible Today
- Byte-for-byte re-execution of the 6,480-cell matrix using the existing runner code.
- Event and episode detection algorithms from raw NOAA weather.
- Static-policy thermal violation numbers and G1 narrow vulnerability.

### What is NOT Externally Reproducible
- Leakage-safe, station-specific TinyLSTM model training (training code/data for non-SFO stations was never created).
- Station-specific HeatGuard calibration.
- Full-event continuity dynamics (G4) due to omission of internal state logging.
- G5 multidimensional robustness (the 9 variants were never generated).

---

## 14. Scientific Claim Triage

| # | Scientific Claim | Classification | Evidence-Based Justification |
|---|---|---|---|
| 1 | **P11 Baseline Preservation** | **VALID** | Byte-identical to original archive; verified via `verify_archive.py` (54/54 files match). |
| 2 | **Multi-Station Heatwave Catalogue** | **VALID** | 25 events correctly detected across 5 stations using strict P90 definition. |
| 3 | **Multi-Year Event Replication** | **VALID** | Events successfully span 2023, 2024, and 2025 across multiple independent climate zones. |
| 4 | **G1 Full Feasibility-Boundary Replication** | **INVALID** | Feasibility boundary delta is near-zero (mean -0.08x); no systematic boundary shift detected. |
| 5 | **G1 Narrow Static Vulnerability** | **VALID** | Replicated across 6/6 paired episodes (median +8.08h violation hours). |
| 6 | **G2 Geographic Heterogeneity** | **EXPLORATORY** | Cluster bootstrap confidence interval [-3.08h, +25.47h] crosses zero; statewide carbon is unidentifiable. |
| 7 | **G3 Benchmark Discriminability** | **INVALID** | 3 of 4 estimable events rely on invalid SFO model transfer; 89.4% heatwave equal-service exclusion. |
| 8 | **G4 Full-Event Continuity** | **NOT ESTIMABLE** | Internal hourly allocation traces and backlog states were not logged; causal continuity gate failed closed. |
| 9 | **G5 Bounded Robustness** | **LIMITED** | Only 1 variant (low thermal curve) was executed; 9 predeclared variants are completely absent. |
| 10 | **Forecast-Aware Scheduling Comparisons** | **INVALID** | Directly contaminated by SFO model transfer to non-SFO stations across 3,960 cells. |
| 11 | **HeatGuard Comparisons** | **INVALID** | SFO calibration residuals and thresholds applied to non-SFO climates without station recalibration. |
| 12 | **Cost / Carbon Comparisons** | **NOT ESTIMABLE** | Severe equal-service attrition (0% valid trios at 2x and 3x multipliers); comparisons confound work and cost. |
| 13 | **Independent External Reproducibility** | **LIMITED** | Executable only within current repo; lacks station training pipelines and artifact recipes. |
| 14 | **Material Strengthening of Workshop Novelty** | **LIMITED** | Replicating static power-cap vulnerability across 3 years strengthens empirical foundation, but scheduling superiority claims collapse. |

---

## 15. Required Repairs Before Phase P7

1. **Implement Fallback Forecast Rule (MANDATORY / BLOCKING):**
   - In accordance with `configs/p12_b2_protocol.yaml` lines 182–186, implement `causal_same_hour_previous_day_forecast` as the primary forecast for all non-SFO stations, or train genuine station-specific TinyLSTM models using strictly pre-2022 weather.
2. **Re-execute Non-SFO Forecast-Dependent Cells (MANDATORY / BLOCKING):**
   - Re-run the 3,960 compromised cells using the protocol-compliant forecast provider.
3. **Harmonize 2022 Coverage Policy (RECOMMENDED):**
   - Modify the window-level coverage assertion so that years are not excluded globally due to off-event missing data, recovering 9 heatwave events.
4. **Fix Ordinary-Window Sampling Overlap (RECOMMENDED):**
   - Enforce non-overlapping constraints during candidate sampling to ensure true statistical independence in the empirical null distribution.
5. **Log Hourly Allocation Traces for G4 (RECOMMENDED):**
   - Persist internal scheduler allocations to allow prospective evaluation of multi-day compounding dynamics.

---

## 16. Publication-Readiness Assessment

### Strongest Defensible HeatTrace B2 Claim Today:
> *"Across 6 independent regional heatwave episodes spanning 3 warm seasons (2023–2025) and 4 California climate regions, static temperature-unaware schedulers operating under facility power caps incur a median of +8.08 additional hours of power-cap exceedances compared to matched non-heatwave periods. However, evaluating forecast-guided mitigation across diverse climates requires strict station-specific calibration and equal completed service accounting, without which apparent cost and carbon benefits are obscured by thermal throttling and model transfer artifacts."*

Any claim asserting that HeatGuard or TinyLSTM-guided policies beat static policies in cost or carbon across California stations is currently **unsupported and unpublishable**.

---

## 17. Independent Reviewer Questions

1. Why was the protocol-mandated fallback forecasting rule (`causal_same_hour_previous_day_forecast`) bypassed in favor of hardcoding the SFO TinyLSTM checkpoint in `p12_b2_runner.py`?
2. How does the paper plan to present cost and carbon metrics when 89.4% of heatwave policy trios failed equal-service validation?
3. What is the justification for claiming "robustness" (G5) when 9 of the 10 predeclared sensitivity configurations were never run?

---

## 18. Final Decision

# **BLOCKED**

Phase P7 cannot begin until the forecast-transfer violation is corrected, the fallback or station-specific forecasting pipeline is executed, and equal-service comparisons are restricted to verifiable common support.
