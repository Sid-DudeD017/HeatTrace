# HeatTrace Phase 9 Confirmatory Analysis Report

**Phase:** Phase 9 / Day 11 (Corrected Event-Level Analysis)
**Protocol Reference:** `docs/p6_frozen_protocol.md`
**Configuration Reference:** `configs/p6_validity.yaml`
- **Repository Base Commit:** `37bdffbf27666c40a24fb0591d2e2d7436508adf`
- **Implementation Git Commit:** none; the current repair is uncommitted (`uncommitted_source_changes`)
- **Authoritative Implementation Identity:** recorded analysis-source (`bea868ca4a76fa8a4a762e39591c6ad03a210f9c9f93edcffa94109bc19f4291`) and focused-test (`0ac246de29ac593f4ef0bc2f70706ca33b5041a5abdae39f76f69cc0cc0c8ed7`) SHA-256 hashes
**Status:** COMPLETE (PASS_WITH_BOUNDED_LIMITATIONS)

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

## 2. Hypothesis Evaluation Summary (Dynamically Rendered)

### H1 — Static Feasibility: **SUPPORTED**
- **Frozen Scope:** Power-capped model, static_unaware policy, carbon_first objective, medium thermal curve as primary.
- **Event-Level Pair Effects (HW - CTRL):** TRIPLET_CONF_1_f5c700: -0.5x, TRIPLET_CONF_2_2a6e22: -0.5x, TRIPLET_CONF_3_628624: 0.0x
- **Median Effect:** -0.5x
- **Support Criterion:** Requires $\ge 2$ of 3 negative effects and negative median. Result: 2/3 negative, median is negative.
- **Sensitivity (Low Curve):** 1/3 negative, median=0.0x.

### H2 — Capacity-Awareness Recovery: **PARTIALLY_SUPPORTED**
- **Frozen Scope:** Power-capped model, heatwave context, carbon_first objective, medium curve.
- **Evaluator Results:**
#### Policy: `capacity_aware`
- **f5c700:** applicable=True (static loss=-0.5x); policy HW boundary=2.5x vs static HW boundary=2.5x -> boundary change=0.0x (recovery=False); violation hours at 3x: static=1.5h, policy=1.5h -> reduction=0.0h (service change=0.0 slots)
- **2a6e22:** applicable=True (static loss=-0.5x); policy HW boundary=2.5x vs static HW boundary=2.5x -> boundary change=0.0x (recovery=False); violation hours at 3x: static=1.0h, policy=1.0h -> reduction=0.0h (service change=0.0 slots)
- **628624:** NOT_APPLICABLE_NO_PREREQUISITE_LOSS (static HW=3.0x, static CTRL=3.0x)

#### Policy: `full_thermal_aware`
- **f5c700:** applicable=True (static loss=-0.5x); policy HW boundary=2.0x vs static HW boundary=2.5x -> boundary change=-0.5x (recovery=False); violation hours at 3x: static=1.5h, policy=0.5h -> reduction=1.0h (service change=0.0 slots)
- **2a6e22:** applicable=True (static loss=-0.5x); policy HW boundary=2.5x vs static HW boundary=2.5x -> boundary change=0.0x (recovery=False); violation hours at 3x: static=1.0h, policy=0.5h -> reduction=0.5h (service change=0.0 slots)
- **628624:** NOT_APPLICABLE_NO_PREREQUISITE_LOSS (static HW=3.0x, static CTRL=3.0x)
- **Classification:** **PARTIALLY_SUPPORTED** under frozen disjunction (boundary recovery OR fewer violations): no tested boundary recovery; exact `capacity_aware` policy provides no improvement; `full_thermal_aware` reduces violation hours in both applicable events (1.0h in CONF_1, 0.5h in CONF_2); evidence is mixed across policies and outcomes.

### H3 — Event-Blind Understatement: **PARTIALLY_SUPPORTED**
- **Evaluation Scope:** 36 seed-aggregated core-policy comparisons per triplet/context (3 policy pairs × 2 facility models × 2 curves × 3 workloads).
- **Event-Level Results (Independent Triplet Units):**
- **TRIPLET_CONF_1_f5c700:** heatwave nonzero cost=24/36, control nonzero=24/36, blind nonzero=0/36; event effect (HW - blind)=+24; transitions vs blind: tie->nontie=24, strict_reversals=0, unchanged=12 (discriminating=True)
- **TRIPLET_CONF_2_2a6e22:** heatwave nonzero cost=24/36, control nonzero=0/36, blind nonzero=0/36; event effect (HW - blind)=+24; transitions vs blind: tie->nontie=24, strict_reversals=0, unchanged=12 (discriminating=True)
- **TRIPLET_CONF_3_628624:** heatwave nonzero cost=0/36, control nonzero=0/36, blind nonzero=0/36; event effect (HW - blind)=+0; transitions vs blind: tie->nontie=0, strict_reversals=0, unchanged=36 (discriminating=False)
- **Descriptive Event Effects (HW - Blind Nonzero Count):** [24, 24, 0], median=+24.0, sign consistency=2/3 positive.
- **Leave-One-Out Sensitivity:** {'excl_f5c700': '1/2 discriminating', 'excl_2a6e22': '1/2 discriminating', 'excl_628624': '2/2 discriminating'}.
- **Classification:** **PARTIALLY_SUPPORTED**. CONF_1 and CONF_2 expose policy cost/carbon separations and baseline-tie to heatwave-non-tie transitions that event-blind windows completely obscure (0/36 nonzero gaps in blind); CONF_3 is a null event where both heatwave and blind show zero separation. Strict reversals (A-preferred to B-preferred) were zero.

### H4 — Forecast Mechanism Attribution: **NOT_ESTIMABLE**
- **Classification:** **NOT_ESTIMABLE**.
- **Reason:** The frozen confirmation matrix does not contain a controlled forecast-source intervention (varying forecast input while holding scheduler, facility model, workload, and objective identical). Substituting policy comparisons or hindsight oracle runs violates causal attribution.

### H5 — HeatGuard Comparator: **NOT_SUPPORTED**
- **Zero-Margin Equivalence:** full_thermal_aware verified equivalent to zero-margin HeatGuard: shares 24h rolling horizon, 1h commitment, PUE temperature scaling, and safety_margin=0.0.
- **Event-Level Comparator Results:**
- **TRIPLET_CONF_1_f5c700:** calibrated violations=1.0h, fixed violations=0.0h, full_thermal violations=1.0h (improved over fixed=False, improved over deterministic=False)
- **TRIPLET_CONF_2_2a6e22:** calibrated violations=0.5h, fixed violations=0.5h, full_thermal violations=0.5h (improved over fixed=False, improved over deterministic=False)
- **TRIPLET_CONF_3_628624:** calibrated violations=0.0h, fixed violations=0.0h, full_thermal violations=0.0h (improved over fixed=False, improved over deterministic=False)
- **Classification:** **NOT_SUPPORTED**. Calibrated HeatGuard failed to outperform fixed-margin HeatGuard (which had fewer or equal violations) or deterministic Full Thermal Aware across the series.

---

## 3. Equal-Service Accounting

- **Total seed-aggregated within-cell policy pairs:** 540
- **Eligible equal-service comparisons:** 530
- **Rejected unequal-service comparisons:** 10
- **Rejection breakdown:** All 10 rejections occurred in `control` context involving `oracle_full_thermal_aware` (where seed 20261016 experienced 12 unfinished processing slots). All deployable policy pairs had 100% equal completed service across all seeds.

---

## 4. Deliverables Produced

- `data/results/p6_event_level_metrics.csv` (378 rows)
- `data/results/p6_policy_pairwise_metrics.csv` (540 rows)
- `data/results/p6_analysis_manifest.json`
- `data/results/p6_t1_cohort_provenance.csv` (5 rows)
- `data/results/p6_t2_event_feasibility.csv` (72 rows)
- `data/results/p6_t3_equal_service_gaps.csv` (27 rows; primary condition 9 per triplet)
- `data/results/p6_t4_forecast_evidence.csv` (17 rows)
- `data/results/p6_h1_h5_assessment.csv` (5 rows)
- `data/figures/p6_f1_event_policy_contrasts.png` (displays CONF_1, CONF_2, and CONF_3 separately)
- `data/figures/p6_f4_h1_sensitivity.png` (displays event-level H1 effects and H3 discriminability with denominator 36)
- `data/figures/p6_f2_allocation_distance_status.md`
- `data/figures/p6_f3_forecast_regret_status.md`
