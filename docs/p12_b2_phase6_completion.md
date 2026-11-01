# Phase 6 Completion Report — Track B2 (G1–G5 Corrected Retrospective Analysis)

**State:** CORRECTED AND COMPLETE — READY FOR REVIEW  
**Timestamp UTC:** 2026-11-01T00:15:00Z  
**Analysis Type:** Retrospective Operational Analysis (Exploratory / Retrospective)  
**Analysis Unit:** `regional_episode_id` (nested station events within regional episodes and years)  
**Verdict:** `PHASE 6 CORRECTED — READY FOR REVIEW`

---

## 1. Methodological Boundary and Provenance Notice

> [!IMPORTANT]
> **Provenance and Confirmatory Status Notice:**
> The high-level G1–G5 hypotheses and general decision criteria were preregistered and frozen in Phase 1 (`configs/p12_b2_protocol.yaml`, `docs/p12_b2_frozen_protocol_draft.md`). However, the exact operational estimands, deterministic tested feasibility boundaries, common-support equal-service trio criteria, and implementation code were finalized **after** Phase 5 scheduler execution outcomes were already inspected.
> 
> Therefore, all exact Phase 6 calculations are **retrospective/exploratory** and must **not** be designated as preregistered confirmatory analyses. This limitation cannot be repaired retroactively using the same data. Confirmatory validation of these findings requires untouched future events, a held-out dataset, or a separately frozen replication study.

---

## 2. Corrected Executive Summary & Preregistered Decisions

| Hypothesis | Frozen Label | Frozen Preregistered Claim | Corrected Classification | Operational Evidence Basis |
|---|---|---|---|---|
| **G1** | Temporal Replication | Feasibility boundaries and policy-performance separations recur across multiple independent warm-season years. | **LIMITED** *(Full Claim)*<br>**SUPPORTED** *(Narrow Claim)* | Narrow claim (*static power-cap vulnerability*) is replicated in 3 of 3 years (2023, 2024, 2025) across 6 of 6 paired episodes (median diff = +8.08h). However, full G1 claim is **LIMITED**: calculated tested feasibility boundary difference has mean = -0.08x (5 episodes delta = 0.0x, 1 episode delta = -0.5x due to strict cap enforcement in control; scheduler feasibility diff = 0), and equal-service policy gaps are heavily constrained by high-load throttling. |
| **G2** | Geographic Heterogeneity | Thermal feasibility and policy separation magnitudes systematically vary across California climate regions. | **DESCRIPTIVE_ONLY** | Coastal ($N=4$ episodes) vs Inland ($N=3$ episodes) across $R=6$ total unique episodes (Episode 08 spans SFO and FAT). Point contrast Inland - Coastal = +9.10h; 95% regional-episode cluster-bootstrap CI is **[-3.06h, +25.25h]** (spans zero). EIA CISO carbon proxy is shared statewide and cannot identify geographic carbon heterogeneity. |
| **G3** | Benchmark Discriminability | Complete heatwave windows are more discriminating among policies than ordinary warm-season windows. | **WITHIN_ORDINARY_DISTRIBUTION** *(Limited)* | Evaluated using common workload support and strict equal-service trios. Exactly 4 matrix events possess valid common support: 1 exceeds P95 (`LAX_20240905`), 3 remain within ordinary distributions (`LAX_20230908`, `LAX_20250821`, `SFO_20240702`). 8 matrix events are non-estimable (1 failed execution, 7 no valid heatwave equal service); 13 catalogue events absent from matrix. Reconciled identity: $25 = 4 + 8 + 13$. At episode level: 1 exceeds P95, 3 within ordinary, 11 non-estimable. |
| **G4** | Full-Event Continuity | Multi-day full-event evaluation captures compounding thermal and backlog dynamics missed by isolated peak-day windows. | **NON_ESTIMABLE** | Causal continuity gate failed closed: Phase 5 realization tables record aggregate realization metrics but lack internal allocation traces and cross-boundary backlog states; post-hoc peak slicing truncates arrivals and corrupts causal deadlines; no separately frozen ablation manifest exists. |
| **G5** | Bounded Robustness | Primary findings are stable across variations in event definition threshold, duration, thermal parameters, capacity limits, and episode grouping. | **PARTIALLY_ROBUST — LOW THERMAL CURVE ONLY** | Exactly 1 preregistered variant is executed in Phase 5 (`low_thermal_curve`): all 6 paired episodes show positive static vulnerability increase (median = +5.33h vs +8.08h on medium curve). Energy-only facility model is a baseline comparator (0 violation hours by construction), not a G5 sensitivity. The 9 unexecuted predeclared variants are classified **NON_ESTIMABLE** and do not count toward robustness. |

---

## 3. G1 Feasibility Boundary Calculation

The tested feasibility boundary is calculated deterministically across tested multipliers ($1.0\times, 2.0\times, 3.0\times$) for `static_unaware` under `power_capped` / `medium` curve. A row is strictly feasible only if:
- `execution_status == "SUCCESS"`
- `scheduler_feasible == True`
- `thermally_feasible == True`
- `unfinished_processing_slots == 0`
- `jobs_missed == 0`
- `power_cap_violation_hours == 0`
- `maximum_power_cap_exceedance_kw == 0`

If a successful seed has no strictly feasible multiplier, its boundary is $0.0\times$. Failed or missing rows remain `NON_ESTIMABLE` (never converted to zero).

### Event and Episode Boundary Results

| Regional Episode ID | Year | Station Events | Mean Heatwave Boundary | Mean Control Boundary | Delta Boundary (HW - Ctrl) | Status |
|---|---|---|---|---|---|---|
| `B2_EP_20230714_06` | 2023 | RDD | 0.00x | 0.00x | 0.00x | ESTIMABLE |
| `B2_EP_20230908_07` | 2023 | LAX | 0.00x | 0.00x | 0.00x | ESTIMABLE |
| `B2_EP_20240701_08` | 2024 | SFO, FAT | 0.25x | 0.25x | 0.00x | ESTIMABLE |
| `B2_EP_20240719_09` | 2024 | RDD, FAT | 0.00x | 0.00x | 0.00x | ESTIMABLE |
| `B2_EP_20240905_10` | 2024 | LAX | 0.00x | 0.00x | 0.00x | ESTIMABLE |
| `B2_EP_20250821_11` | 2025 | LAX | 0.00x | 0.50x | -0.50x | ESTIMABLE |

Across the 6 estimable episodes, the mean boundary contrast is **-0.08x** (median = 0.00x). In 5 episodes, static policies exceed the power cap even at $1.0\times$ load during both heatwaves and matched controls due to baseline ambient summer heat in California, making the tested boundary $0.0\times$ in both contexts. In episode 11 (`LAX_20250821`), control seed 20261016 achieves strict feasibility at $1.0\times$ while the heatwave exceeds cap limits, yielding a delta of $-0.50\times$. Full G1 feasibility boundary replication is therefore classified **`LIMITED`**.

---

## 4. G3 Common Workload Support Recalculation

Policy separation is evaluated strictly over common workload support:
1. Define the heatwave common-support set as the valid equal-service trios $(workload\_seed, workload\_multiplier)$ in that heatwave window.
2. An ordinary window is valid if and only if it contains valid equal-service trios for every condition in the heatwave common-support set.
3. Additional ordinary window conditions outside the heatwave common-support set are excluded to preserve identical condition weighting.
4. $K$ counts distinct ordinary windows with complete common support ($K \ge 10$).
5. Strict inequality is enforced: $heatwave\_separation > ordinary\_p95$.

### Event-Level Common-Support Results

| Station Event ID | Heatwave Conditions | Total Frozen OW | Excluded OW | Valid Common-Support K | Heatwave Separation | Ordinary P95 | Exceeds P95? | Classification |
|---|---|---|---|---|---|---|---|---|
| `B2_HW_LAX_20230908` | (20261017, 1.0x), (20261017, 2.0x) | 20 | 5 | 15 | 0.00h | 0.45h | False | `WITHIN_ORDINARY_DISTRIBUTION` |
| `B2_HW_LAX_20240905` | (20261017, 1.0x) | 20 | 0 | 20 | 2.00h | 0.00h | True | `HEATWAVE_EXCEEDS_P95` |
| `B2_HW_LAX_20250821` | (20261016, 1.0x), (20261017, 1.0x) | 20 | 4 | 16 | 0.00h | 0.00h | False | `WITHIN_ORDINARY_DISTRIBUTION` |
| `B2_HW_SFO_20240702` | (20261016, 1.0x), (20261017, 1.0x) | 20 | 2 | 18 | 0.00h | 0.07h | False | `WITHIN_ORDINARY_DISTRIBUTION` |
| *8 Matrix Events* | Empty HW support / failed | 20 each | 20 each | 0 | NaN | NaN | False | `NON_ESTIMABLE` |
| *13 Catalog Events* | Absent from matrix | 0 | 0 | 0 | NaN | NaN | False | `NON_ESTIMABLE` |

---

## 5. Reconciled Event Denominators

Programmatic accounting across the entire evaluation catalogue:

$$\text{Total Catalogue Events } (25) = \text{Estimable Matrix Events } (4) + \text{Non-Estimable Matrix Events } (8) + \text{Absent from Matrix } (13)$$

### Detailed Breakdown:
- **Total Catalogue Events:** 25
- **Represented in Phase 5 Execution Matrix:** 12
  - **Estimable Events (Common Support K >= 10):** 4 (`LAX_20230908`, `LAX_20240905`, `LAX_20250821`, `SFO_20240702`)
  - **Non-Estimable Matrix Events:** 8
    - *Execution Failed in Matrix:* 1 (`LAX_20250828`, weather data incomplete)
    - *No Valid Equal-Service Heatwave Support:* 7 (`FAT_20240703`, `FAT_20240722`, `RDD_20230714`, `RDD_20240702`, `RDD_20240719`, `SAC_20240701`, `SAC_20240710` due to thermal throttling)
    - *Common Support K < 10:* 0
- **Absent from Phase 5 Execution Matrix:** 13 (`FAT_20220625`, `FAT_20220904`, `FAT_20260802`, `LAX_20220808`, `LAX_20220831`, `LAX_20260821`, `LAX_20260907`, `RDD_20220904`, `SAC_20220904`, `SFO_20220620`, `SFO_20220904`, `SFO_20220922`, `SFO_20260907`)

---

## 6. Artifact Inventory and Table Accounting

Exactly seven table files are generated and maintained for Phase 6 under `data/v2/tables/`:
- `data/v2/tables/table1_missingness_flow.csv`
- `data/v2/tables/table2_nested_events_episodes.csv`
- `data/v2/tables/table3_episode_level_effects.csv`
- `data/v2/tables/table8_equal_service_audit.csv`
- `data/v2/tables/table9_g4_continuity_gate.csv`
- `data/v2/tables/table10_g5_robustness_inventory.csv`
- `data/v2/tables/table11_final_g1_g5_decision.csv`

No intermediate tables 4–7 were created or required.

## 7. Verification and Acceptance Checks

- Complete test suite passed: `12 passed in tests/test_p12_b2_phase6_analysis.py`; full suite `111 passed in 39.99s`.
- `git diff --check` confirmed clean formatting with zero whitespace errors.
- Protected Phase 5 baseline hashes verified identical before and after all changes.

---

## 8. Final Verdict

**`PHASE 6 PROVENANCE FINALIZED — READY FOR PHASE 7`**

*(Phase 7 has not been started.)*
