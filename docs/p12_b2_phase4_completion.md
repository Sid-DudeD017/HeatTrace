# Track B2 Phase 4 Completion Report: Fair Matched Controls, Representative Ordinary Windows, and Execution Matrix Dry Run

**Execution Date:** 2026-10-31  
**Track:** B2 Multi-Year Multi-Station Benchmark  
**Phase:** Phase 4  
**Status:** COMPLETE (Formally Frozen, All Gates Verified, Zero Schedulers Executed, Phase 5 Unstarted)

---

## 1. Executive Summary and Scope

Phase 4 successfully implemented the outcome-blind selection of fair matched controls and representative ordinary warm-season windows, frozen duration-specific synthetic workloads, and completed the dry-run enumeration of the Track B2 Phase 5 execution matrix without running any schedulers or inspecting policy outcomes.

### Event Scope Inventory
- **Total Station Events in Phase 3 Catalogue:** 25 events (across 15 regional episodes).
- **Joint-Evaluation Eligible Events (Primary Scope):** 12 events (all from 2023–2025).
- **Excluded Events:** 9 events from 2022 (due to federal EIA-930 2022-06-13 interval omission).
- **Provisional Events:** 4 events from 2026 (pending full-calendar NOAA certification).
- **Audit Verification:** Excluded 2022 events, provisional 2026 events, SFO 2025 (coverage failure), and SAC_FALLBACK (untriggered) contributed **zero primary controls, zero ordinary windows, and zero execution matrix cells**.

---

## 2. Matched Control Selection

For every one of the 12 eligible station events, exactly one fair matched control was selected according to the frozen lexicographic calendar and weather ranking rule.

### Selected Controls Summary

| Matched Event ID | Station | Year | Event Start (Local) | Control Start (Local) | Control ID | Duration (Hours) | Matching Status | Limitation Label |
|---|---|---|---|---|---|---|---|---|
| `B2_HW_RDD_20230714` | RDD | 2023 | 2023-07-14 | 2023-07-07 | `B2_CTRL_RDD_20230714_20230707` | 144 | MATCHED (Same Year) | `NONE` |
| `B2_HW_LAX_20230908` | LAX | 2023 | 2023-09-08 | 2023-09-01 | `B2_CTRL_LAX_20230908_20230901` | 144 | MATCHED (Same Year) | `NONE` |
| `B2_HW_SAC_20240701` | SAC | 2024 | 2024-07-01 | 2024-06-17 | `B2_CTRL_SAC_20240701_20240617` | 192 | MATCHED (Same Year) | `NONE` |
| `B2_HW_RDD_20240702` | RDD | 2024 | 2024-07-02 | 2024-06-11 | `B2_CTRL_RDD_20240702_20240611` | 312 | MATCHED (Same Year) | `NONE` |
| `B2_HW_SFO_20240702` | SFO | 2024 | 2024-07-02 | 2024-06-25 | `B2_CTRL_SFO_20240702_20240625` | 120 | MATCHED (Same Year) | `NONE` |
| `B2_HW_FAT_20240703` | FAT | 2024 | 2024-07-03 | 2024-06-12 | `B2_CTRL_FAT_20240703_20240612` | 312 | MATCHED (Same Year) | `NONE` |
| `B2_HW_SAC_20240710` | SAC | 2024 | 2024-07-10 | 2024-06-19 | `B2_CTRL_SAC_20240710_20240619` | 120 | MATCHED (Same Year) | `NONE` |
| `B2_HW_RDD_20240719` | RDD | 2024 | 2024-07-19 | 2024-08-02 | `B2_CTRL_RDD_20240719_20240802` | 192 | MATCHED (Same Year) | `NONE` |
| `B2_HW_FAT_20240722` | FAT | 2024 | 2024-07-22 | 2024-07-29 | `B2_CTRL_FAT_20240722_20240729` | 168 | MATCHED (Same Year) | `NONE` |
| `B2_HW_LAX_20240905` | LAX | 2024 | 2024-09-05 | 2024-09-12 | `B2_CTRL_LAX_20240905_20240912` | 168 | MATCHED (Same Year) | `NONE` |
| `B2_HW_LAX_20250821` | LAX | 2025 | 2025-08-21 | 2025-08-14 | `B2_CTRL_LAX_20250821_20250814` | 120 | MATCHED (Same Year) | `NONE` |
| `B2_HW_LAX_20250828` | LAX | 2025 | 2025-08-28 | 2025-09-04 | `B2_CTRL_LAX_20250828_20250904` | 120 | MATCHED (Same Year) | `NONE` |

**Verification:**
- 100% (12/12) controls achieved `same_year == True`.
- No cross-year fallbacks were required; limitation labels are `NONE`.
- All controls matched the exact UTC duration of the full event evaluation window (onset day + complete heatwave + recovery day).

---

## 3. Representative Ordinary Windows and Overlap Graph

Every eligible event achieved the primary target of $K=20$ ordinary windows (total 240 ordinary windows across 12 events).

### Candidate Audit and Overlap Summary

| Event ID | Duration | Total Candidates Evaluated | Eligible Candidates | Selected $K$ | Effective Distinct Components | Overlapping Edges | Limitation Status |
|---|---|---|---|---|---|---|---|
| `B2_HW_RDD_20230714` | 144h (6d) | 117 | 95 | 20 | 16 | 4 | `NONE` |
| `B2_HW_LAX_20230908` | 144h (6d) | 117 | 95 | 20 | 16 | 4 | `NONE` |
| `B2_HW_SAC_20240701` | 192h (8d) | 115 | 66 | 20 | 3 | 21 | `NONE` |
| `B2_HW_RDD_20240702` | 312h (13d) | 110 | 51 | 20 | 3 | 51 | `NONE` |
| `B2_HW_SFO_20240702` | 120h (5d) | 118 | 75 | 20 | 14 | 6 | `NONE` |
| `B2_HW_FAT_20240703` | 312h (13d) | 110 | 51 | 20 | 3 | 51 | `NONE` |
| `B2_HW_SAC_20240710` | 120h (5d) | 118 | 75 | 20 | 14 | 6 | `NONE` |
| `B2_HW_RDD_20240719` | 192h (8d) | 115 | 66 | 20 | 3 | 21 | `NONE` |
| `B2_HW_FAT_20240722` | 168h (7d) | 116 | 69 | 20 | 4 | 16 | `NONE` |
| `B2_HW_LAX_20240905` | 168h (7d) | 116 | 69 | 20 | 4 | 16 | `NONE` |
| `B2_HW_LAX_20250821` | 120h (5d) | 118 | 102 | 20 | 20 | 0 | `NONE` |
| `B2_HW_LAX_20250828` | 120h (5d) | 118 | 102 | 20 | 20 | 0 | `NONE` |

**Candidate Audit Totals:**
- Total candidate windows audited: 1,388
- Control candidates audited: 1,388
- Ordinary window candidates audited: 1,388
- Retained in audit CSVs with explicit rejection reasons (`protected_heatwave_overlap`: 472 instances, `protected_regional_episode_overlap`: 472 instances, `embedded_three_day_p90_run`: 162 instances).

---

## 4. Workload Trace Generation and Hash Freeze

Workload generation satisfied variable-duration semantics with constant expected arrival intensity ($0.25\text{ jobs/hour}$):

| Duration (Hours) | 1x Job Count | 2x Job Count | 3x Job Count | Seeds | Parquet & CSV Traces |
|---|---|---|---|---|---|
| 120 | 30 | 60 | 90 | 20261016, 20261017 | Frozen in `data/v2/workloads/` |
| 144 | 36 | 72 | 108 | 20261016, 20261017 | Frozen in `data/v2/workloads/` |
| 168 | 42 | 84 | 126 | 20261016, 20261017 | Frozen in `data/v2/workloads/` |
| 192 | 48 | 96 | 144 | 20261016, 20261017 | Frozen in `data/v2/workloads/` |
| 312 | 78 | 156 | 234 | 20261016, 20261017 | Frozen in `data/v2/workloads/` |

**Verification:** All windows within the same event group, duration, seed, and multiplier reference the identical workload SHA256 hash.

---

## 5. Execution Matrix Dry Run

The complete matrix was enumerated according to the frozen protocol formula:
$$\text{Cells per eligible event} = 18 \times (K_e + 2) + 144 = 18 K_e + 180$$
Since all 12 events achieved $K_e = 20$:
$$\text{Cells per event} = 18(20) + 180 = 540$$
$$\text{Total matrix cells} = 12 \times 540 = 6,480$$

### Cell Breakdown:
- **Primary condition cells (power-capped, medium thermal, carbon-first, 3 core policies):**
  $18 \times 22\text{ windows} \times 12\text{ events} = 4,752\text{ cells}$
- **Event/Control Core-Grid Extension (108 per event):** $1,296\text{ cells}$
- **Event/Control HeatGuard Fixed and Calibrated (24 per event):** $288\text{ cells}$
- **Event/Control Hindsight Oracle Reference (12 per event):** $144\text{ cells}$
- **Total:** **6,480 cells**

### Deployability:
- **Deployable cells:** 6,336 cells ($97.78\%$)
- **Non-deployable cells (Hindsight Oracle):** 144 cells ($2.22\%$)
- **Unique Canonical Run IDs:** 6,480 unique IDs (zero collisions).

---

## 6. Authoritative Final Artifacts and SHA-256 Hashes

All SHA-256 hashes computed directly from finalized artifacts:

| Artifact Path | Description | Byte Size | Row Count | SHA-256 Digest |
|---|---|---|---|---|
| `data/v2/benchmarks/p12_b2_controls.csv` | 12 Selected Matched Controls | 4,476 | 12 | `d9859542adbdfd480e1b798a5e1d4db0a169e728c1f20f3f91c4cdeb06629682` |
| `data/v2/benchmarks/p12_b2_ordinary_windows.csv` | 240 Selected Ordinary Windows | 67,250 | 240 | `fa4c9af50b1b47ee6aa26f6a17e91d3ee3dc744d35b1e779235a28a368329102` |
| `data/v2/benchmarks/p12_b2_control_candidates.csv` | Control Candidate Pool Audit | 290,078 | 1,388 | `4c3c3acce3c0f4cc0d827e8782840c0e9834a733a4d8bc1febe204c0c2230fae` |
| `data/v2/benchmarks/p12_b2_ordinary_window_candidates.csv` | Ordinary Window Candidate Audit | 295,145 | 1,388 | `b923660a3805567708256699c5acef1a259e267355c8b76603aa658ca5b4967c` |
| `data/v2/benchmarks/p12_b2_window_overlap_graph.csv` | Ordinary Window Overlap Graph | 20,745 | 196 | `eef3488d3bdfc50a44ebdf9878d252eb366d8a71738d2f60c3530719c97cf890` |
| `data/v2/benchmarks/p12_b2_matrix_cells.csv` | 6,480 Planned Execution Cells | 2,470,674 | 6,480 | `d687b2b5eb791ecf0ec21b13c891da993d1cab86c1cbdbd23b7aca91d6c31487` |
| `data/v2/manifests/p12_b2_matrix_dry_run.json` | Matrix Dry Run Manifest | 24,682 | N/A | `8ecdc46c39d17480c6c646c4290a04ce3bf639aa998d46dd8a080f9385bdb5fe` |
| `data/v2/manifests/p12_b2_window_freeze.json` | Window Freeze Manifest | 6,724 | N/A | `9d00fbc24e451d08c02a0da5c0d32242798f4a81cfe3f28dc52c97a5f1279fa6` |

---

## 7. Protected P11 and Phase 3 Baseline Verification

| Protected Baseline Artifact | Expected SHA-256 | Actual Computed SHA-256 | Verification Status |
|---|---|---|---|
| `data/v2/manifests/p12_b2_event_freeze.json` (Phase 3 Freeze) | `972675ef164cd29628eebdc4e509dce352b62a70a2e7214c9e9083f8d33d91c5` | `972675ef164cd29628eebdc4e509dce352b62a70a2e7214c9e9083f8d33d91c5` | VERIFIED_MATCH |
| `data/archive/heattrace_v1_d5b3c86/archive_manifest.json` | `2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4` | `2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4` | VERIFIED_MATCH |
| `data/results/p11_reproduction_comparison.json` | `cf14e1bfc3f8031612229f989d6dcb784771f1f7112bda809871ac782bc9f49e` | `cf14e1bfc3f8031612229f989d6dcb784771f1f7112bda809871ac782bc9f49e` | VERIFIED_MATCH |
| `configs/p6_validity.yaml` | `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1` | `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1` | VERIFIED_MATCH |
| `docs/p6_frozen_protocol.md` | `78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede` | `78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede` | VERIFIED_MATCH |

---

## 8. Test Suite Execution and Acceptance Gates

Comprehensive automated test execution covering all criteria:
- `tests/test_p12_b2_phase4_windows.py`: 28 passed
- `tests/test_p12_b2_phase3_events.py`: 21 passed
- `tests/test_p12_b2_coverage.py`: 23 passed
- `tests/test_p3_events.py`: 1 passed
- `tests/test_p3_workload_policy.py`: 7 passed
- **Total:** **80 passed in 30.52s**

### Tested Properties
1. Only the 12 ELIGIBLE P3 events enter the primary Phase 4 matrix.
2. Excluded 2022 events produce zero primary cells.
3. Provisional 2026 events produce zero primary cells.
4. SFO 2025 and SAC_FALLBACK produce no selections.
5. Exactly one control per included event.
6. Selected controls are genuinely rank 1 under the lexicographic sort key (`final_rank == 1` and `candidate_rank == 1` across all 12 controls).
7. Same-station control enforcement.
8. Same-year preference.
9. Cross-year fallback explicitly tested end-to-end and labeled `LIMITED_CROSS_YEAR`.
10. Exact UTC duration equality.
11. DST-safe 23/25-hour duration handling.
12. No overlap with any protected event interval.
13. No embedded three-day strict-P90 run.
14. Missing weather explicitly rejects candidate (`missing_weather_day`).
15. Complete candidate pool materialized before selection.
16. Deterministic candidate ranking and tie-breaking.
17. Candidate ordering independence (shuffled input produces identical output).
18. $K=20$ selected when available.
19. $K=10$ and $K<10$ fallback behavior explicitly tested via helper on synthetic pools without fabricating data.
20. Ordinary-window overlap graph correctness and component IDs.
21. Global control/window IDs are unique.
22. Workload hashes reused across matched windows.
23. Different durations produce appropriate workload identities.
24. Matrix formula equals $18K_e + 180$.
25. Expected 6,480 total only when all 12 events have $K=20$.
26. Every canonical run ID is unique.
27. Oracle rows are non-deployable (`deployable == False`).
28. No v1 output path is targeted.
29. No scheduler execution occurs.
30. Guarded boundary: active monkeypatching verifies no price/carbon/policy outcome file is read.
31. Phase 3 and all P11 protected hashes remain unchanged.
32. Manifest file hashes match artifacts on disk.
33. Isolated two-run reproduction comparison matches byte-for-byte without mutating canonical repository outputs.

---

## 9. Remaining Limitations and Phase 5 Boundary
- No cross-year fallback limitations exist in the primary matrix (`limitation_label: NONE` for all 12 controls).
- No ordinary window sample limitations exist ($K=20$ for all 12 events).
- Due to window lengths and season bounds, ordinary windows within longer events (e.g. 13-day FAT and RDD events) have lower effective distinct components (3 components each); this pseudo-replication structure is formally captured in `p12_b2_window_overlap_graph.csv` for downstream clustering.
- **Phase 5 Status:** NOT STARTED. Zero schedulers were executed.
