# HeatTrace Track B2 — Phase 3 Completion Record
**Phase**: Phase 3 — Weather-Only Station Event and Regional-Episode Catalogue  
**Status**: COMPLETE (Frozen Before Downstream Experiments)  
**Date**: 2026-10-31  
**Scope**: 5 Primary Stations, 2022–2026 Warm Seasons (June 1 – September 30)  
**Authoritative Manifest**: [`data/v2/manifests/p12_b2_event_freeze.json`](../data/v2/manifests/p12_b2_event_freeze.json)

---

## 1. Executive Summary

Track B2 Phase 3 has been completed strictly using weather-only observations from NOAA GHCNh and the frozen Track B2 protocol (`configs/p12_b2_protocol.yaml`):
1. **Station-Specific Empirical P90 Thresholds**: Computed from pooled valid daily maxima across the fixed 2022–2025 baseline years (linear percentile interpolation).
2. **Station Event Detection**: Strict multi-day heatwave detection ($T_{\max} > P_{90}$ for $\ge 3$ consecutive local days) in `America/Los_Angeles`. Missing days break runs; zero imputation was applied.
3. **Multi-Station Identity**: Unique deterministic identities assigned (`B2_HW_<STATION_CODE>_<YYYYMMDD>`), eliminating v1 cross-station collisions.
4. **Phase Labeling**: Canonical hourly labels (`onset`, `sustained`, `peak`, `recovery`) across complete preserved events, written to Parquet.
5. **Regional Episode Clustering**: 24-hour UTC expanded buffer connected-component clustering yielded 15 independent regional episodes, established as the primary independent statistical unit.
6. **Eligibility Governance**:
   - Primary Stations: Exactly 5 (`SFO`, `SAC`, `FAT`, `RDD`, `LAX`).
   - Contingency Fallback: `SAC_FALLBACK` (`USW00093225`) was not activated and produced 0 events.
   - SFO 2025: Excluded from event screening due to 97.54% daily-max coverage ($< 98.0\%$).
   - Year 2022: 9 events catalogued; all explicitly marked `EXCLUDED` from joint evaluation due to the EIA 2022 source gap.
   - Year 2026: 4 events catalogued; all labeled `PROVISIONAL`.
   - Years 2023–2025: 12 events marked `ELIGIBLE` for joint grid evaluation.
7. **Scientific Protection**: Phase 4 controls, workloads, forecasts, and scheduler experiments have not been started. Downstream price, carbon, and outcome data were never loaded or inspected.

---

## 2. Station-Specific P90 Baseline Thresholds

Baseline evaluated: June 1 through September 30 for years 2022, 2023, 2024, 2025 ($4 \times 122 = 488$ expected days).

| Station Code | NOAA GHCNh ID | Official Station Name | Climate Class | CAISO Hub | Expected Days | Valid Days | Missing Days | Missing Dates | Sample Size | P90 Threshold |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| **SFO** | `USW00023234` | SAN FRANCISCO INTL AP | Northern coastal | `TH_NP15_GEN-APND` | 488 | 485 | 3 | 2025-08-30; 2025-08-31; 2025-09-01 | 485 | **25.60°C** |
| **SAC** | `USW00023232` | SACRAMENTO AP ASOS | Northern inland | `TH_NP15_GEN-APND` | 488 | 488 | 0 | NONE | 488 | **38.30°C** |
| **FAT** | `USW00093193` | FRESNO YOSEMITE INTL | Central inland | `TH_ZP26_GEN-APND` | 488 | 488 | 0 | NONE | 488 | **40.60°C** |
| **RDD** | `USW00024257` | REDDING AP | Far-northern inland | `TH_NP15_GEN-APND` | 488 | 488 | 0 | NONE | 488 | **41.70°C** |
| **LAX** | `USW00023174` | LOS ANGELES INTL AP | Southern coastal | `TH_SP15_GEN-APND` | 488 | 488 | 0 | NONE | 488 | **26.70°C** |

*Note: SFO valid daily maxima from 2022–2025 contribute to the empirical baseline under the frozen protocol, but SFO 2025 is excluded from event screening.*

---

## 3. Station-Year Screening Matrix

Across 30 audited station-years (25 primary + 5 inactive fallback):
- **Screened**: 24 station-years across the 5 primary stations.
- **Not Screened / Excluded**: SFO 2025 (daily-max coverage 97.54% < 98.0%).
- **Not Screened / Inactive Fallback**: SAC_FALLBACK 2022–2026 (primary SAC passed Phase 2 gate).

---

## 4. Station Event Catalogue (25 Detected Events)

| Event ID | Station | Local Dates | Days | Peak Date | Peak Tmax | Full Window (UTC) | Regional Episode | Joint Eval Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- | :--- |
| `B2_HW_SFO_20220620` | SFO | 2022-06-20 to 2022-06-22 | 3 | 2022-06-21 | 36.7°C | 2022-06-19 07:00 to 06-24 07:00 | `B2_EP_20220620_01` | EXCLUDED |
| `B2_HW_FAT_20220625` | FAT | 2022-06-25 to 2022-06-27 | 3 | 2022-06-27 | 41.7°C | 2022-06-24 07:00 to 06-29 07:00 | `B2_EP_20220625_02` | EXCLUDED |
| `B2_HW_LAX_20220808` | LAX | 2022-08-08 to 2022-08-10 | 3 | 2022-08-09 | 28.9°C | 2022-08-07 07:00 to 08-12 07:00 | `B2_EP_20220808_03` | EXCLUDED |
| `B2_HW_LAX_20220831` | LAX | 2022-08-31 to 2022-09-12 | 13 | 2022-09-09 | 38.3°C | 2022-08-30 07:00 to 09-14 07:00 | `B2_EP_20220831_04` | EXCLUDED |
| `B2_HW_FAT_20220904` | FAT | 2022-09-04 to 2022-09-07 | 4 | 2022-09-06 | 45.6°C | 2022-09-03 07:00 to 09-09 07:00 | `B2_EP_20220831_04` | EXCLUDED |
| `B2_HW_RDD_20220904` | RDD | 2022-09-04 to 2022-09-06 | 3 | 2022-09-06 | 46.1°C | 2022-09-03 07:00 to 09-08 07:00 | `B2_EP_20220831_04` | EXCLUDED |
| `B2_HW_SAC_20220904` | SAC | 2022-09-04 to 2022-09-09 | 6 | 2022-09-05 | 45.6°C | 2022-09-03 07:00 to 09-11 07:00 | `B2_EP_20220831_04` | EXCLUDED |
| `B2_HW_SFO_20220904` | SFO | 2022-09-04 to 2022-09-08 | 5 | 2022-09-05 | 35.6°C | 2022-09-03 07:00 to 09-10 07:00 | `B2_EP_20220831_04` | EXCLUDED |
| `B2_HW_SFO_20220922` | SFO | 2022-09-22 to 2022-09-24 | 3 | 2022-09-24 | 28.3°C | 2022-09-21 07:00 to 09-26 07:00 | `B2_EP_20220922_05` | EXCLUDED |
| `B2_HW_RDD_20230714` | RDD | 2023-07-14 to 2023-07-17 | 4 | 2023-07-16 | 43.9°C | 2023-07-13 07:00 to 07-19 07:00 | `B2_EP_20230714_06` | ELIGIBLE |
| `B2_HW_LAX_20230908` | LAX | 2023-09-08 to 2023-09-11 | 4 | 2023-09-10 | 30.0°C | 2023-09-07 07:00 to 09-13 07:00 | `B2_EP_20230908_07` | ELIGIBLE |
| `B2_HW_SAC_20240701` | SAC | 2024-07-01 to 2024-07-06 | 6 | 2024-07-06 | 42.8°C | 2024-06-30 07:00 to 07-08 07:00 | `B2_EP_20240701_08` | ELIGIBLE |
| `B2_HW_RDD_20240702` | RDD | 2024-07-02 to 2024-07-12 | 11 | 2024-07-06 | 48.3°C | 2024-07-01 07:00 to 07-14 07:00 | `B2_EP_20240701_08` | ELIGIBLE |
| `B2_HW_SFO_20240702` | SFO | 2024-07-02 to 2024-07-04 | 3 | 2024-07-02 | 31.1°C | 2024-07-01 07:00 to 07-06 07:00 | `B2_EP_20240701_08` | ELIGIBLE |
| `B2_HW_FAT_20240703` | FAT | 2024-07-03 to 2024-07-13 | 11 | 2024-07-07 | 45.0°C | 2024-07-02 07:00 to 07-15 07:00 | `B2_EP_20240701_08` | ELIGIBLE |
| `B2_HW_SAC_20240710` | SAC | 2024-07-10 to 2024-07-12 | 3 | 2024-07-11 | 43.3°C | 2024-07-09 07:00 to 07-14 07:00 | `B2_EP_20240701_08` | ELIGIBLE |
| `B2_HW_RDD_20240719` | RDD | 2024-07-19 to 2024-07-24 | 6 | 2024-07-19 | 43.3°C | 2024-07-18 07:00 to 07-26 07:00 | `B2_EP_20240719_09` | ELIGIBLE |
| `B2_HW_FAT_20240722` | FAT | 2024-07-22 to 2024-07-26 | 5 | 2024-07-23 | 43.3°C | 2024-07-21 07:00 to 07-28 07:00 | `B2_EP_20240719_09` | ELIGIBLE |
| `B2_HW_LAX_20240905` | LAX | 2024-09-05 to 2024-09-09 | 5 | 2024-09-06 | 38.3°C | 2024-09-04 07:00 to 09-11 07:00 | `B2_EP_20240905_10` | ELIGIBLE |
| `B2_HW_LAX_20250821` | LAX | 2025-08-21 to 2025-08-23 | 3 | 2025-08-23 | 30.0°C | 2025-08-20 07:00 to 08-25 07:00 | `B2_EP_20250821_11` | ELIGIBLE |
| `B2_HW_LAX_20250828` | LAX | 2025-08-28 to 2025-08-30 | 3 | 2025-08-29 | 28.3°C | 2025-08-27 07:00 to 09-01 07:00 | `B2_EP_20250828_12` | ELIGIBLE |
| `B2_HW_FAT_20260802` | FAT | 2026-08-02 to 2026-08-04 | 3 | 2026-08-03 | 41.7°C | 2026-08-01 07:00 to 08-06 07:00 | `B2_EP_20260802_13` | PROVISIONAL |
| `B2_HW_LAX_20260821` | LAX | 2026-08-21 to 2026-08-30 | 10 | 2026-08-27 | 31.1°C | 2026-08-20 07:00 to 09-01 07:00 | `B2_EP_20260821_14` | PROVISIONAL |
| `B2_HW_LAX_20260907` | LAX | 2026-09-07 to 2026-09-12 | 6 | 2026-09-09 | 36.1°C | 2026-09-06 07:00 to 09-14 07:00 | `B2_EP_20260907_15` | PROVISIONAL |
| `B2_HW_SFO_20260907` | SFO | 2026-09-07 to 2026-09-10 | 4 | 2026-09-09 | 33.9°C | 2026-09-06 07:00 to 09-12 07:00 | `B2_EP_20260907_15` | PROVISIONAL |

---

## 5. Regional Episode Grouping (15 Independent Units)

Regional episodes represent connected components over $\pm 24\text{h}$ UTC expanded event windows. They constitute the primary independent statistical unit for Track B2.

| Episode ID | Member Events | Stations | Years | Earliest Start (UTC) | Latest End (UTC) | Member Event IDs | Eligibility Summary |
| :--- | :---: | :--- | :---: | :--- | :--- | :--- | :--- |
| `B2_EP_20220620_01` | 1 | SFO | 2022 | 2022-06-20 07:00 | 2022-06-23 07:00 | `B2_HW_SFO_20220620` | EXCLUDED_FROM_JOINT_EVALUATION |
| `B2_EP_20220625_02` | 1 | FAT | 2022 | 2022-06-25 07:00 | 2022-06-28 07:00 | `B2_HW_FAT_20220625` | EXCLUDED_FROM_JOINT_EVALUATION |
| `B2_EP_20220808_03` | 1 | LAX | 2022 | 2022-08-08 07:00 | 2022-08-11 07:00 | `B2_HW_LAX_20220808` | EXCLUDED_FROM_JOINT_EVALUATION |
| `B2_EP_20220831_04` | 5 | FAT, LAX, RDD, SAC, SFO | 2022 | 2022-08-31 07:00 | 2022-09-13 07:00 | `B2_HW_LAX_20220831`; `B2_HW_FAT_20220904`; `B2_HW_RDD_20220904`; `B2_HW_SAC_20220904`; `B2_HW_SFO_20220904` | EXCLUDED_FROM_JOINT_EVALUATION |
| `B2_EP_20220922_05` | 1 | SFO | 2022 | 2022-09-22 07:00 | 2022-09-25 07:00 | `B2_HW_SFO_20220922` | EXCLUDED_FROM_JOINT_EVALUATION |
| `B2_EP_20230714_06` | 1 | RDD | 2023 | 2023-07-14 07:00 | 2023-07-18 07:00 | `B2_HW_RDD_20230714` | ELIGIBLE |
| `B2_EP_20230908_07` | 1 | LAX | 2023 | 2023-09-08 07:00 | 2023-09-12 07:00 | `B2_HW_LAX_20230908` | ELIGIBLE |
| `B2_EP_20240701_08` | 5 | FAT, RDD, SAC, SFO | 2024 | 2024-07-01 07:00 | 2024-07-14 07:00 | `B2_HW_SAC_20240701`; `B2_HW_RDD_20240702`; `B2_HW_SFO_20240702`; `B2_HW_FAT_20240703`; `B2_HW_SAC_20240710` | ELIGIBLE |
| `B2_EP_20240719_09` | 2 | FAT, RDD | 2024 | 2024-07-19 07:00 | 2024-07-27 07:00 | `B2_HW_RDD_20240719`; `B2_HW_FAT_20240722` | ELIGIBLE |
| `B2_EP_20240905_10` | 1 | LAX | 2024 | 2024-09-05 07:00 | 2024-09-10 07:00 | `B2_HW_LAX_20240905` | ELIGIBLE |
| `B2_EP_20250821_11` | 1 | LAX | 2025 | 2025-08-21 07:00 | 2025-08-24 07:00 | `B2_HW_LAX_20250821` | ELIGIBLE |
| `B2_EP_20250828_12` | 1 | LAX | 2025 | 2025-08-28 07:00 | 2025-08-31 07:00 | `B2_HW_LAX_20250828` | ELIGIBLE |
| `B2_EP_20260802_13` | 1 | FAT | 2026 | 2026-08-02 07:00 | 2026-08-05 07:00 | `B2_HW_FAT_20260802` | PROVISIONAL |
| `B2_EP_20260821_14` | 1 | LAX | 2026 | 2026-08-21 07:00 | 2026-08-31 07:00 | `B2_HW_LAX_20260821` | PROVISIONAL |
| `B2_EP_20260907_15` | 2 | LAX, SFO | 2026 | 2026-09-07 07:00 | 2026-09-13 07:00 | `B2_HW_LAX_20260907`; `B2_HW_SFO_20260907` | PROVISIONAL |

---

## 6. Generated Scientific Artifacts & Hashes

| Artifact Path | Format | Rows | Bytes | SHA-256 Hash |
| :--- | :---: | :---: | :---: | :--- |
| [`data/v2/events/p12_b2_thresholds.csv`](../data/v2/events/p12_b2_thresholds.csv) | CSV | 5 | 1,098 | `14647f06ec16b45f9daa729cea22a66e12ebcc89c20e30985353d992e7392b9f` |
| [`data/v2/events/p12_b2_station_year_screening.csv`](../data/v2/events/p12_b2_station_year_screening.csv) | CSV | 30 | 3,549 | `6e5da5567bf48806e4c609f302d4162042f20217d10deebd80644e61e564ed96` |
| [`data/v2/events/p12_b2_station_events.csv`](../data/v2/events/p12_b2_station_events.csv) | CSV | 25 | 12,497 | `3a44a4b13d28b9f160133ecebf822d7798579c6c3983471ab243dea2e909f215` |
| [`data/v2/events/p12_b2_regional_episodes.csv`](../data/v2/events/p12_b2_regional_episodes.csv) | CSV | 15 | 3,165 | `af9a44e3d13036732d5daa6ef37f2d0037c35694611bbcb50b3c7660c55b680d` |
| [`data/v2/events/p12_b2_hourly_phase_labels.parquet`](../data/v2/events/p12_b2_hourly_phase_labels.parquet) | Parquet | 4,320 | 54,468 | `6b2c92a7d20ed8a9c553ac128e10e84e5d5393a7e01f4c78d019ba9378480275` |
| [`data/v2/events/p12_b2_hourly_phase_labels_preview.csv`](../data/v2/events/p12_b2_hourly_phase_labels_preview.csv) | CSV | 100 | 17,112 | `ae1242510faced474365079f7698fddf6c001bed4dc559208185d78f9dc9bf62` |
| [`data/v2/manifests/p12_b2_event_freeze.json`](../data/v2/manifests/p12_b2_event_freeze.json) | JSON | 846 lines | 26,939 | `972675ef164cd29628eebdc4e509dce352b62a70a2e7214c9e9083f8d33d91c5` |

---

## 7. Two-Pass Reproduction Verification

A complete two-pass generation was executed writing to an isolated temporary directory. All scientific artifacts matched bit-for-bit:
- `p12_b2_thresholds.csv`: BIT-IDENTICAL (`14647f06ec16b45f9daa729cea22a66e12ebcc89c20e30985353d992e7392b9f`)
- `p12_b2_station_year_screening.csv`: BIT-IDENTICAL (`6e5da5567bf48806e4c609f302d4162042f20217d10deebd80644e61e564ed96`)
- `p12_b2_station_events.csv`: BIT-IDENTICAL (`3a44a4b13d28b9f160133ecebf822d7798579c6c3983471ab243dea2e909f215`)
- `p12_b2_regional_episodes.csv`: BIT-IDENTICAL (`af9a44e3d13036732d5daa6ef37f2d0037c35694611bbcb50b3c7660c55b680d`)
- `p12_b2_hourly_phase_labels.parquet`: BIT-IDENTICAL (`6b2c92a7d20ed8a9c553ac128e10e84e5d5393a7e01f4c78d019ba9378480275`)
- `p12_b2_hourly_phase_labels_preview.csv`: BIT-IDENTICAL (`ae1242510faced474365079f7698fddf6c001bed4dc559208185d78f9dc9bf62`)
