# P6 Frozen Benchmark-Validity Evaluation Protocol
**Status:** DRAFT (Phase 0 Freeze)  
**Study Label:** Bounded CAISO Complete-Heatwave Benchmark Validity Evaluation  
**Date:** October 2026  

---

## 1. Study Scope and Research Objective

This study is a bounded CAISO case-series evaluation designed to test whether complete-heatwave benchmarking changes simulated thermal-feasibility or deployable-policy-ranking conclusions relative to matched controls and event-blind windows.

The central inquiry investigates whether evaluating data center workload schedulers under whole-heatwave episodes reveals constraints and trade-offs that are obscured when using ordinary matched controls or arbitrary event-blind windows of equal duration.

---

## 2. Preregistered Hypotheses

The following three scientific hypotheses are frozen exactly as specified:

### Primary Confirmatory Hypothesis:
**H1 — Static feasibility:**
Under the power-capped model, the static scheduler has lower tested maximum feasible workload in complete heatwaves than matched controls.

### Secondary Confirmatory Hypotheses:
**H2 — Capacity-awareness recovery:**
During heatwaves, capacity-aware scheduling has a higher tested feasible workload or fewer violations than static scheduling.

**H3 — Event-blind understatement:**
Event-blind equal-duration windows understate feasibility failures or policy-ranking changes exposed by complete heatwave windows.

---

## 3. Primary Contrast and Evaluation Specification

The evaluation preregisters the primary contrast framework for hypothesis H1 while explicitly recording three unresolved primary-analysis decisions:

1. **Primary Hypothesis:**
   - **H1 (Static feasibility)**. H2 and H3 are explicitly designated as secondary confirmatory hypotheses.

2. **Primary Population / Unit of Analysis:**
   - Confirmatory `pair_id` event triplets only ($N = 3$ confirmatory pairs under the approved fallback design, or $N = 4$ in primary mode), strictly excluding the single exploratory development triplet.

3. **Primary Simulated Facility Model:**
   - The **power-capped model**, where total facility power is constrained to $P_{\text{cap}} = \text{nominal\_capacity} \times \text{base\_pue}$ and compute capacity is thermally derated via $C_{\text{eff}}[t] = \min(\text{nominal\_capacity}, P_{\text{cap}} / \text{PUE}[t])$. (The energy-only model serves as a secondary model context).

4. **Primary Scheduler Policy:**
   - The **static deployable scheduler** (`static_unaware`), which plans under nominal ratings without temperature awareness.

5. **Primary Outcome Measure:**
   - Tested maximum feasible workload multiplier, denoted $\lambda^*$, evaluated on the frozen discrete grid $\{1.0\times, 2.0\times, 3.0\times\}$.

6. **Primary Paired Comparison:**
   - The paired difference within each confirmatory event pair:
     $$\Delta \lambda^*_i = \lambda^*_{\text{heatwave}, i} - \lambda^*_{\text{matched\_control}, i}$$
     for each confirmatory triplet $i \in \{1, 2, 3\}$ in fallback mode (or $\{1, 2, 3, 4\}$ in primary mode).

7. **Directional Support Criterion:**
   - $\Delta \lambda^*_i < 0$ (lower tested feasible workload during the complete heatwave relative to its matched control) indicates a reduction in tested feasible workload.

8. **Seed Handling:**
   - The two explicit seeds within each pair/context/configuration cell are aggregated prior to event-level contrasts and bootstrap resampling (`primary_analysis.seed_aggregation_rule: aggregate_within_pair_context_configuration_before_contrast`). Seeds are not treated as independent observations.

9. **Event Handling & Statistical Aggregation:**
   - Report pair-level effects $\Delta \lambda^*_i$ directly alongside their across-event descriptive summary. Do not pool configuration cells or seeds as independent sample units.

10. **Grid Qualification:**
    - $\lambda^*$ is strictly grid-bounded by the preregistered discrete workload levels ($1.0\times, 2.0\times, 3.0\times$) and must be interpreted as a tested boundary rather than an exact continuous capacity threshold.

11. **Approved Primary-Analysis Decisions (Phase 3 Freeze):**
    The primary contrast dimensions are approved and frozen:
    - **Thermal-Curve Rule (`primary_analysis.thermal_curve_rule`):** `medium_primary_low_sensitivity` (medium curve is evaluated as primary; low curve serves as sensitivity check).
    - **Objective Rule (`primary_analysis.objective_rule`):** `carbon_first_primary_confirmatory_cost_first_optional_secondary` (`carbon_first` is the primary confirmatory objective; `cost_first` is supported optional secondary objective and cut first if runtime reduction is needed).
    - **Across-Pair Support Rule (`primary_analysis.across_pair_support_rule`):** `three_pair_bounded_case_series_at_least_two_negative_contrasts_and_negative_median`. Aggregate seeds within each pair/context/configuration before contrasts. Contrast is heatwave minus matched control ($\Delta \lambda^*_i = \lambda^*_{\text{heatwave}, i} - \lambda^*_{\text{matched\_control}, i}$). H1 directional support requires at least two of the three confirmatory pairs to have a negative contrast ($\Delta \lambda^*_i < 0$) and the across-pair median contrast to be negative. All three pair effects must still be reported. This is bounded case-series evidence, not population inference.

12. **Secondary Analyses:**
    - H2 (capacity-awareness recovery) and H3 (event-blind understatement), event-blind window contrasts, deployable policy ranking changes, and energy-only facility evaluations are explicitly secondary confirmatory investigations.

13. **Null-Result Path and Interpretation:**
    - If confirmatory data do not satisfy the frozen `primary_analysis.across_pair_support_rule`, H1 is not supported:
      *"The tested static scheduler did not show a consistent heatwave-specific reduction in its feasibility envelope under the simulated facility model."*
    - A null result must be retained and reported honestly; it must never trigger post-hoc tuning or modification of PUE slopes, facility caps, workload levels, or event selection.

14. **Equal-Service Requirement for Economic and Carbon Comparisons:**
    - Raw cost and grid carbon metrics may only be compared directly between schedules that complete identical amounts of required workload service (equal completed work). Comparisons between schedules with unequal completion or infeasible states are invalid.

15. **Oracle Reference Marked Non-Deployable:**
    - The oracle reference policy (`oracle_full_thermal_aware`) has access to realized thermal and price/carbon sequences in hindsight. It is strictly marked `deployable: false` and is excluded from deployable policy rankings.

16. **Planned Development vs. Confirmation Separation (Fallback Design Approved):**
    - The repository's frozen heatwave catalogue (`data/events/heatwave_events_v0.parquet`) contains exactly four authentic detected heatwave events across 2022–2025. Per human approval, the study operates under the approved **Fallback Design (Small Bounded Case Series)**:
      - Exactly **one development triplet** (`TRIPLET_DEV_ae821c`, heatwave `HW_20240702`) using the 2024 event `HW_20240702` is used for runtime verification, adapter debugging, and pilot mechanism tests.
      - Exactly **three confirmatory triplets** (`TRIPLET_CONF_1_f5c700`, `TRIPLET_CONF_2_2a6e22`, `TRIPLET_CONF_3_628624`) using authentic 2022 events (`HW_20220620`, `HW_20220904`, `HW_20220922`) are held untouched and uninspected until the final confirmatory grid execution ($N = 3$ confirmatory pairs).
      - The development triplet is programmatically excluded from confirmatory analysis tables and figures.
      - The study is formally described and qualified as a small bounded case series rather than a broad statistical sample.

---

## 4. Frozen Permitted-Claim Boundaries

All reporting, manuscripts, and discussions must strictly adhere to the following permitted and prohibited claim boundaries:

### Permitted Claims:
- Facility responses and capacity deratings are simulated based on piecewise-linear cooling models, not observed physical data center failures.
- Conclusions are strictly conditional on the selected CAISO events, simulated facility models, synthetic workloads, and configuration parameters.
- Findings assess benchmark validity and scheduler sensitivity within the declared experimental framework.
- Describe the study as a small bounded case series ($N=3$ confirmatory triplets, $N=1$ development triplet).

### Prohibited Claims:
- **Do not** claim that five triplets exist when only four authentic heatwaves exist.
- **Do not** generalize findings beyond the small bounded case series to population-wide or causal claims across all heatwaves or facilities.
- **Do not** claim that historical heatwaves caused observed physical data-center capacity failures or blackouts.
- **Do not** claim that the simulated facility model represents universal data-center thermodynamics or cooling physics across all facilities.
- **Do not** claim that thermal-aware scheduling itself is novel.
- **Do not** claim causal or population-wide heatwave effects across all data centers or power grids.
- **Do not** describe random workload seeds or experimental grid cells as independent heatwave observations ($N$ equals the number of independent event triplets, not the number of grid runs).
- **Do not** claim a faithful reproduction of Ruparel et al.'s adaptive distributionally robust optimization (DRO) method (the capacity adapter is a deterministic heuristic repair mechanism).

---

## 5. Unresolved Fields and Deferred Human-Approval Items

The following items record the current status of protocol fields following Gate 1:

| Category | Field / Detail | Current Status | Resolution Milestone |
| :--- | :--- | :---: | :--- |
| **Development Triplet** | `pair_id`: `TRIPLET_DEV_ae821c`, HW: `HW_20240702`, CTRL: `CTRL_20240605`, BLIND: `BLIND_ef75b17921d7` | **FROZEN (Gate 1)** | Phase 1 (Gate 1 Passed) |
| **Confirmatory Triplets** | 3 confirmatory triplets: `TRIPLET_CONF_1_f5c700` (`HW_20220620`), `TRIPLET_CONF_2_2a6e22` (`HW_20220904`), `TRIPLET_CONF_3_628624` (`HW_20220922`) | **FROZEN (Gate 1 Fallback)** | Phase 1 (Gate 1 Passed) |
| **Random Seeds** | 2 explicit workload generation seeds: `20261016`, `20261017` | **FROZEN (P3)** | Phase 3 Freeze |
| **Deadline Regime** | `processing_requirement_unit`: `hourly_discrete_slot`, `arrival_semantics`: `window_relative_hour_inclusive`, `deadline_semantics`: `window_relative_hour_exclusive`, `slack_distribution`: `canonical_deterministic_generator_seed_drawn`, `slack_bounds_hours`: `effective_range_0_to_24_hours` | **FROZEN (P3)** | Phase 3 Freeze |
| **Parameter Sources** | `low_curve_source`, `medium_curve_source`, `base_pue_source`, `facility_cap_interpretation_source` | **FROZEN (P2)** | Phase 2 Facility Model review |
| **Primary Analysis (Thermal Curve)** | `primary_analysis.thermal_curve_rule`: `medium_primary_low_sensitivity` | **FROZEN (P2)** | Phase 2 Freeze |
| **Primary Analysis (Objective)** | `primary_analysis.objective_rule`: `carbon_first_primary_confirmatory_cost_first_optional_secondary` | **FROZEN (P3)** | Phase 3 Freeze |
| **Primary Analysis (H1 Support)** | `primary_analysis.across_pair_support_rule`: `three_pair_bounded_case_series_at_least_two_negative_contrasts_and_negative_median` | **FROZEN (P3)** | Phase 3 Freeze |
| **Deployable Policies** | `static_unaware`, `capacity_aware`, `full_thermal_aware` | Frozen | Phase 0 Freeze |
| **Temperature Forecast Contract** | `TinyTemperatureLSTM` (72x5 -> 24), train-only scaler, half-open splits (`end_exclusive_utc`), 3 causal baselines, sealed confirmatory outcomes (`confirmatory_status: sealed_not_materialized`), development origins from window start (97 per context), validation-only Forecast Gate | **FROZEN (Phase 4 Corrected)** | Phase 4 Bounded Pass |
| **HeatGuard Calibration & Rolling** | Past-only quantile $q=0.90$ with `method="higher"`, medium curve, fixed comparator $0.10$, 24h horizon, 1h commit, beyond-horizon reservation | **FROZEN (Phase 5)** | Phase 5 Calibration & Rolling |

---

## 6. Phase 5 HeatGuard Calibration & Rolling Scheduling Protocol

### 6.1 Calibration Equations and Residual Definition
Calibration residuals are computed strictly over the frozen calibration interval $[2022\text{-}06\text{-}01\text{T}00:00:00\text{Z}, 2022\text{-}06\text{-}16\text{T}00:00:00\text{Z})$.
A calibration origin $t_{\text{orig}}$ is valid if and only if its complete 24-hour target lies strictly within the reservation:
$$\text{calibration\_start} \le t_{\text{orig}} \quad \text{and} \quad t_{\text{orig}} + 24\text{ hours} \le \text{calibration\_end\_exclusive}$$
Any origin whose target crosses the reservation boundary is strictly rejected.

Residuals:
$$\text{residual}[i, h] = \text{realized\_PUE}[i, h] - \text{forecast\_PUE}[i, h]$$
where:
$$\text{forecast\_PUE} = f(\text{forecast\_temperature})$$
$$\text{realized\_PUE} = f(\text{realized\_temperature})$$
and $f(\cdot)$ is the frozen medium facility thermal curve ($\text{base\_PUE}=1.20$, $\text{threshold}=22.0^\circ\text{C}$, $\text{slope}=0.020/^\circ\text{C}$, $\text{max\_PUE}=1.70$).

The calibrated safety margin $m_{\text{cal}}$ is:
$$m_{\text{cal}} = \max\left(0, \text{quantile}(\text{residuals}, q = 0.90, \text{method} = \text{"higher"})\right)$$
where $\text{method} = \text{"higher"}$ selects the conservative observed order statistic rather than linear interpolation.

The safe PUE upper bound is capped at $\text{max\_PUE}$:
$$\text{PUE}_{\text{safe}}[t] = \min(\text{max\_pue}, \text{forecast\_PUE}[t] + m_{\text{cal}})$$

> [!IMPORTANT]
> **Heuristic Buffer Disclaimer:**
> Calibration provides a heuristic upper-PUE buffer against forecast underprediction; it is **not** a formal theoretical coverage guarantee.

### 6.2 Safe Capacity Derivation
Safe compute capacity is calculated according to the facility model:
- **Energy-only:**
  $$\text{safe\_capacity}[t] = \text{nominal\_capacity}[t]$$
- **Power-capped:**
  $$\text{safe\_capacity}[t] = \min\left(\text{nominal\_capacity}[t], \frac{\text{facility\_cap\_kw}}{\text{PUE}_{\text{safe}}[t]}\right)$$

### 6.3 Rolling Replan and Commitment Semantics
1. **Horizon and Commitment:**
   - $\text{forecast\_horizon\_hours} = 24$
   - $\text{commit\_hours} = 1$
   - Replan frequency is once per committed hour ($1\text{ hour}$).
2. **Causal Information Barrier & Released-Job Information Set:**
   - At origin $t$, only historical and causal forecast information available at or before $t$ is accessed.
   - The deployable scheduler may optimize only jobs satisfying:
     $$\text{arrival\_offset\_hours} \le t, \quad \text{remaining\_requirement} > 0, \quad \text{deadline\_offset\_hours} > t$$
   - Not-yet-released jobs ($\text{arrival} > t$) must not enter optimization merely because they arrive within 24 hours. Future arrivals enter planning only after their release hour.
   - Future realized temperatures, future realized PUE, and future market outcomes must never influence present decisions.
   - Confirmatory intervals remain completely uninspected during calibration and development.
3. **State Preservation:**
   - Replan only unfinished, released, eligible work.
   - Commit only the first hour ($t$) of the 24-hour plan.
   - Completed work is preserved and never reappears or reallocates.
   - Unfinished work carries forward into subsequent replans. No silent job dropping.

### 6.4 Beyond-Horizon Deadline Rule and Allocation Enforcement
For a job whose deadline $D$ exceeds the current 24-hour horizon ($D > t + 24$):
- Calculate minimum in-window required processing:
  $$\text{future\_slots\_after\_horizon} = \max(0, D - (t + 24))$$
  $$\text{req\_in\_window} = \max(0, \text{remaining\_req} - \text{future\_slots\_after\_horizon})$$
- Mandatory requirement semantics:
  - If $D \le t + 24$: $\text{window\_effective\_req} = \text{remaining\_req}$, $\text{temporary\_deadline} = D - t$.
  - If $D > t + 24$: $\text{window\_effective\_req} = \text{req\_in\_window}$, $\text{temporary\_deadline} = 24$.
  - If $\text{req\_in\_window} = 0$, the job has no mandatory current-window allocation and is carried forward without entering the current window optimization.
- The 24-hour replan must actually allocate at least $\text{req\_in\_window}$ units to that job before the horizon ends.
- The scheduler verifies that actual planned allocations in the 24-hour window meet each $\text{req\_in\_window}$ requirement.
- When sufficient capacity does not exist to satisfy in-window required work, report projected infeasibility explicitly. Never silently pretend the job is feasible or drop the requirement.

### 6.5 Minimum Calibration Support, Provenance, and Self-Verifiable Artifact
- Calibration requires at least $100$ distinct valid calibration origins, each with complete finite 24-hour targets.
- If distinct origins $< 100$, fail loudly or switch to the explicitly labeled fixed-margin fallback ($m_{\text{fixed}} = 0.10$).
- Confirmation data is never inspected to fill missing calibration support.
- Calibration contract strictly enforces verified 64-character hexadecimal SHA-256 hashes for:
  - Phase 4 artifact manifest (`ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79`)
  - Model checkpoint (`69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed`)
  - Forecast configuration (`bda89d3baf3f9c1cade93aca5d43f8c5bb64de4fc07b548e0e8cf2349578d1d7`)
  - Split contract (`59fdcf783d2b2d825e44d5a9eaf29a87fa96f262b921e4b6394c2f96c6a4284c`)
- Self-verifiable production artifact `data/models/p6_heatguard_calibration_v3/`:
  - Contains `manifest.json`, `calibration.json`, `origins.json`, `forecast_temperatures.npy`, `realized_temperatures.npy`, `residuals.npy`.
  - Manifest SHA-256 hash: `bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c`.
  - Margin recomputed and verified independently: $m_{\text{cal}} \approx 0.016000$ (exactly $0.015999984741210893$).
  - Full self-verification validates file SHA-256 hashes, array shapes, origins, PUE residuals re-derived through medium curve, and $q=0.90$ higher order statistic.
- Deployable Calibrated Production Construction Path:
  - `HeatGuardScheduler(..., margin_mode="calibrated", calibration_artifact_dir=..., expected_manifest_sha256=..., repository_root=...)`
  - While the generic artifact loader (`load_calibration_artifact`) can validate a caller-selected manifest for offline audit/testing, deployable calibrated HeatGuard accepts only the frozen V3 manifest hash recorded in `p6_validity.yaml` (`FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256 = "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c"`).
  - Re-signing or substituting another internally consistent V3 artifact is strictly rejected for the frozen analysis.
  - Calibrated mode cannot accept raw numeric margins or standalone/manually constructed `CalibrationResult` objects.
  - Must load V3 artifact strictly from disk, verifying the external manifest hash, all internal artifact files, array metadata, NOAA source datasets, and required Phase 4 model files (`artifact_manifest.json`, `tiny_lstm_checkpoint.pt`).
  - Fails closed immediately if any required input, file, hash, or provenance element is missing or mismatched.
  - Fixed comparator (`margin_mode="fixed"`) is strictly frozen at $0.10$ and rejects any non-numeric value, boolean, NaN, inf, or value $\ne 0.10$. No-margin mode (`margin_mode="none"`) always applies exactly $0.0$.

### 6.6 Policy Comparators and Objectives
Comparators are evaluated under identical causal inputs:
1. Calibrated HeatGuard ($m_{\text{cal}}$)
2. Fixed-margin comparator ($m_{\text{fixed}} = 0.10$)
3. No-margin comparator ($m = 0.0$)
Primary deployable evaluation remains `carbon_first`; `cost_first` is a secondary comparator. Raw USD and $\text{kgCO}_2$ are never added directly, and no composite policy is introduced in Phase 5.

*Note: No scientific parameters, seed values, or event selections were invented. All 4 heatwaves are authentic detected events from the frozen catalogue.*
