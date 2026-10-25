# HeatTrace Phase 9 Confirmatory Analysis Report

**Phase:** Phase 9 / Day 11  
**Protocol Reference:** `docs/p6_frozen_protocol.md`  
**Configuration Reference:** `configs/p6_validity.yaml`  
**Status:** COMPLETE (Pass with bounded limitations)  

---

## 1. Provenance and Input Baseline Verification

All canonical P8 artifacts were verified byte-for-byte prior to analysis:
- `data/results/p6_validity_runs.parquet` (`c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f`)
- `data/results/p6_validity_checkpoint.parquet` (`c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f`)
- `data/results/p6_validity_manifest.json` (`d0dd9f870ec2a431cc16177c5f1b7a5e6b47a7dc888b0acb491a819656006082`)
- `data/results/p6_validity_execution.jsonl` (`de430ceea4559de2f4e67f5b122223b3496dfe854e1f5efa874909363bff0e80`)
- **Run-ID Digest:** `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1` (Exact match across 756 unique runs).

Zero failures, zero development row contamination, zero missing IDs, zero mutation.

---

## 2. Hypothesis Evaluation Summary

| Hypothesis | Frozen Scope | Estimability | Event-Level Effects | Median Effect | Classification | Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **H1 (Static Feasibility)** | Power-capped, static_unaware, carbon_first, medium primary | ESTIMABLE | CONF_1: -0.5x, CONF_2: -0.5x, CONF_3: 0.0x | -0.5x | **SUPPORTED** | Tested boundary on discrete grid; 2 of 3 pairs negative, median negative. |
| **H2 (Capacity Recovery)** | Power-capped, heatwave, carbon_first, medium curve | ESTIMABLE | Boundary recovery: 0.0x for all pairs. Violations: CONF_2 reduced from 2h to 1h, CONF_1 unchanged/mixed. | 0.0x | **NOT_SUPPORTED** | Tested boundary not recovered; capacity awareness cannot prevent derating under modeled caps. |
| **H3 (Event-Blind Understatement)** | Core benchmark across heatwave, control, blind contexts | ESTIMABLE | Heatwave: 48/72 nonzero cost gaps (mean $123.78). Blind: 0/72 nonzero cost gaps ($0.00). | N/A | **SUPPORTED** | Event-blind window completely understates policy differences exposed in complete heatwaves. |
| **H4 (Forecast Mechanism)** | Controlled forecast source mutation | NOT_ESTIMABLE | Controlled forecast-source intervention absent from P8 confirmation matrix. | N/A | **NOT_ESTIMABLE** | Causal forecast regret cannot be claimed without fixed-scheduler forecast mutation. |
| **H5 (HeatGuard Comparator)** | Medium curve, power-capped 120h | ESTIMABLE | Calibrated: 3.0h violations. Fixed: 1.0h violations. Deterministic FTA: 3.0h violations. | N/A | **NOT_SUPPORTED** | Calibrated margin failed to outperform fixed-margin heuristic or eliminate thermal violations. |

---

## 3. Equal-Service Accounting

- **Total within-cell policy pairs evaluated:** 1080
- **Eligible equal-service comparisons:** 1070
- **Rejected unequal-service comparisons:** 10
- **Rejection breakdown:** All 10 rejections occurred in `control` context involving `oracle_full_thermal_aware` (runs 721 and 731) which suffered 12 unfinished processing slots. All deployable-vs-deployable policy comparisons had 100% equal completed service.

---

## 4. Deliverables Produced

- `data/results/p6_event_level_metrics.csv` (378 rows)
- `data/results/p6_policy_pairwise_metrics.csv` (1080 rows)
- `data/results/p6_analysis_manifest.json`
- `data/results/p6_t1_cohort_provenance.csv`
- `data/results/p6_t2_event_feasibility.csv`
- `data/results/p6_t3_equal_service_gaps.csv`
- `data/results/p6_t4_forecast_evidence.csv`
- `data/results/p6_h1_h5_assessment.csv`
- `data/figures/p6_f1_event_policy_contrasts.png`
- `data/figures/p6_f4_h1_sensitivity.png`
- `data/figures/p6_f2_allocation_distance_status.md`
- `data/figures/p6_f3_forecast_regret_status.md`
