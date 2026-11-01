# HeatTrace Track B2 — Phase 2 Completion Record

**Document Identifier**: `docs/p12_b2_phase2_completion.md`  
**Phase Title**: Phase 2 — Acquire and Validate Multi-Station Historical Inputs  
**Completion Date**: 2026-10-31  
**Status**: COMPLETE (with declared exclusions)  
**Track B2 Stage**: Phase 1 Approved & Complete · Phase 2 Complete with Declared Exclusions · Phase 3 NOT STARTED  

---

## 1. Scope & Objective

Phase 2 established the multi-station, multi-year historical input foundation for HeatTrace Track B2 across three data domains:
1. **NOAA Weather**: GHCNh hourly surface observations and derived daily maxima across six California stations (30 station-years, 2022–2026).
2. **CAISO DAM LMP**: Day-Ahead Market wholesale hourly locational marginal prices for three major regional hubs (`TH_NP15_GEN-APND`, `TH_ZP26_GEN-APND`, `TH_SP15_GEN-APND`) across five warm seasons (15 hub-years, 2022–2026).
3. **EIA 930 CISO**: Hourly Balancing Authority demand, net generation, and consumed carbon intensity proxy for balancing authority `CISO` across five warm seasons (5 BA-years, 2022–2026).

Warm-season boundaries for all domains are defined strictly per the approved protocol:
- Local start: June 1 00:00:00 PDT (`America/Los_Angeles`).
- Local end: October 1 00:00:00 PDT.
- Expected duration: Exactly 2,928 hourly intervals per full season.

---

## 2. Generated Phase 2 Manifests

All Phase 2 outputs and validation records are published in the `data/v2/manifests/` namespace:

| Manifest File | Format | Description | Record Count |
| :--- | :--- | :--- | :---: |
| [`data/v2/manifests/p12_b2_source_coverage.csv`](file:///Users/siddharthbhakta/HeatTrace/data/v2/manifests/p12_b2_source_coverage.csv) | CSV | NOAA weather station-year coverage, quality codes, and eligibility classifications | 30 |
| [`data/v2/manifests/p12_b2_price_carbon_coverage.csv`](file:///Users/siddharthbhakta/HeatTrace/data/v2/manifests/p12_b2_price_carbon_coverage.csv) | CSV | CAISO hub-year and EIA BA-year interval coverage, hash provenance, and eligibility | 20 |
| [`data/v2/manifests/p12_b2_caiso_gap_inventory_after.csv`](file:///Users/siddharthbhakta/HeatTrace/data/v2/manifests/p12_b2_caiso_gap_inventory_after.csv) | CSV | CAISO post-recovery gap inventory showing remaining missing intervals | 15 |
| [`data/v2/manifests/p12_b2_caiso_acquisition_attempts.jsonl`](file:///Users/siddharthbhakta/HeatTrace/data/v2/manifests/p12_b2_caiso_acquisition_attempts.jsonl) | JSONL | CAISO bulk acquisition attempts, URL parameters, error codes, and disk paths | 4 |
| [`data/v2/manifests/p12_b2_raw_sources.jsonl`](file:///Users/siddharthbhakta/HeatTrace/data/v2/manifests/p12_b2_raw_sources.jsonl) | JSONL | Comprehensive raw source catalog with relative paths, SHA-256 hashes, and bytes | 281 |

---

## 3. Data Domain Status Summaries

### 3.1 NOAA Weather Domain (30 Station-Years)
Validated using established GHCNh PSV ingestion, temperature quality filters (`NOAA_ACCEPTED_QUALITY_CODES`), deterministic hourly bin aggregation, and calendar-day daily maximum extraction:
- **PASS**: **23 station-years** (100% hourly temperature coverage, >98% daily maxima, 0 conflicting duplicate observations).
- **PROVISIONAL**: **6 station-years** (all 6 stations for year 2026; 100% complete coverage, 0 conflicts; awaiting full calendar certification).
- **EXCLUDED**: **1 station-year**:
  - `USW00023234` (San Francisco International AP, SFO), Year 2025:
  - Daily-max coverage is 119/122 = 97.54%, falling below the frozen 98.0% daily-max coverage threshold.
- **Stations Evaluated (30 Station-Years: 5 Primary + 1 Inactive Fallback)**:
  1. `USW00023234` (San Francisco International AP, SFO)
  2. `USW00023232` (Sacramento Airport ASOS, SAC)
  3. `USW00093193` (Fresno Yosemite International, FAT)
  4. `USW00024257` (Redding Airport, RDD)
  5. `USW00023174` (Los Angeles International AP, LAX)
  - `USW00093225` (Sacramento Metro AP, `SAC_FALLBACK`) — predeclared northern inland fallback station. Validated for contingency purposes, but remains **inactive and audit-only** because primary Sacramento (`USW00023232`) passed all coverage and metadata gates. Phase 3 primary candidate event detection is strictly restricted to the 5 primary stations (`SFO`, `SAC`, `FAT`, `RDD`, `LAX`).

### 3.2 CAISO Wholesale Price Domain (15 Hub-Years)
Completed via Option B manual recovery of official daily CAISO archives:
- **147 Official Daily Archives** recovered under `data/v2/raw/caiso/bulk_historical/`:
  - 98 recovered dates for 2022; 49 recovered dates for 2023.
  - Header-driven DictReader parsing used exclusively; `MCE`, `MCC`, and `MCL` components ignored.
  - Exactly 3,528 hourly intervals recovered per hub (2,352 for 2022; 1,176 for 2023).
  - Exactly 24 records per downloaded day per hub; zero duplicate timestamps; zero conflicting price values.
- **Coverage Summary**:
  - `TH_NP15_GEN-APND`: 2022–2025 = 2,928/2,928 (**PASS**); 2026 = 2,928/2,928 (**PROVISIONAL**).
  - `TH_ZP26_GEN-APND`: 2022–2025 = 2,928/2,928 (**PASS**); 2026 = 2,928/2,928 (**PROVISIONAL**).
  - `TH_SP15_GEN-APND`: 2022–2025 = 2,928/2,928 (**PASS**); 2026 = 2,928/2,928 (**PROVISIONAL**).
  - **Remaining CAISO Gaps**: **0 missing intervals** across all 15 hub-years.

### 3.3 EIA 930 Grid & Carbon Domain (5 BA-Years)
Parsed and reconciled via authentic `CISO.xlsx` workbook:
- **PASS**: **3 BA-years** (2023, 2024, 2025: 2,928/2,928 valid intervals).
- **PROVISIONAL**: **1 BA-year** (2026: 2,928/2,928 valid intervals; provisional year).
- **EXCLUDED**: **1 BA-year**:
  - `CISO` Year 2022: 2,927/2,928 valid intervals (99.97%).
  - Missing interval: `2022-06-13 17:00:00 UTC` interval start (`2022-06-13T18` hour-ending).
  - **Authoritative Federal Source Gap**: Queried official EIA API v2 (`eia_api_v2_ciso_region_data_20220613T16_T20.json`); returned `null` for Demand (`D`), Net Generation (`NG`), and all fuel categories. The interval is unpopulated at the source and cannot be filled without synthetic fabrication. Under the zero-imputation protocol, 2022 is strictly `EXCLUDED`.

---

## 4. Manifest Programmatic Audit Counts

Reading directly from the generated manifest CSVs:

| Manifest | PASS | PROVISIONAL | EXCLUDED | Total Records |
| :--- | :---: | :---: | :---: | :---: |
| `p12_b2_source_coverage.csv` (NOAA) | 23 | 6 | 1 | 30 |
| `p12_b2_price_carbon_coverage.csv` (Price & Carbon) | 15 | 4 | 1 | 20 |
| `p12_b2_caiso_gap_inventory_after.csv` (CAISO Gaps) | 15 (0 gaps) | — | 0 | 15 |

---

## 5. Protected Baseline P11 Verification

The immutable 756-cell P11 reproduction artifacts and frozen configurations were verified byte-for-byte:

| Protected File Path | Baseline SHA-256 | Current Disk SHA-256 | Audit Status |
| :--- | :--- | :--- | :---: |
| `data/archive/heattrace_v1_d5b3c86/archive_manifest.json` | `2038706b9a...` | `2038706b9a...` | **MATCH** |
| `data/results/p11_reproduction_comparison.json` | `cf14e1bfc3...` | `cf14e1bfc3...` | **MATCH** |
| `configs/p6_validity.yaml` | `46f132487b...` | `46f132487b...` | **MATCH** |
| `docs/p6_frozen_protocol.md` | `78cf42a1d0...` | `78cf42a1d0...` | **MATCH** |

---

## 6. Regression & Acceptance Testing

The complete test suite was executed in the workspace virtual environment:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_p12_b2_coverage.py tests/test_p1_ingest.py -q
```
**Outcome**: `114 passed, 2 skipped in 75.75s` (0 failures).

Verified properties include:
- Nested archive discovery and total-LMP filtering.
- Rejection of error responses from market intervals.
- Automatic exclusion on conflicting prices.
- Deterministic deduplication of identical observations.
- Promotion of complete conflict-free CAISO hub-years to PASS.
- Preservation of EIA 2022 exclusion and 2026 provisional status.
- Immutability of baseline P11 hashes.

---

## 7. Formal Phase 2 Scientific Verdict

> **Verdict**: Track B2 Phase 2 acquisition and validation is complete with explicit eligibility classifications. CAISO Option B recovery is complete. The 2022 joint grid evaluation remains excluded because of one authoritative EIA source gap; SFO 2025 is excluded because its daily-max coverage is below the frozen 98% threshold; and 2026 remains provisional.

---

## 8. Phase 3 Handoff Boundaries & Protocol Restrictions

Phase 2 is formally closed. Phase 3 (Heatwave Detection & Regional Episode Catalogue) may proceed only under the following strict boundaries:
1. **Candidate Station Scope (5 Primary Stations)**:
   - Primary candidate stations for Phase 3 event detection are strictly: `SFO` (`USW00023234`), `SAC` (`USW00023232`), `FAT` (`USW00093193`), `RDD` (`USW00024257`), and `LAX` (`USW00023174`).
   - `SAC_FALLBACK` (`USW00093225`) is **inactive and audit-only** because primary Sacramento passed. It must not be processed as a sixth candidate station.
2. **Eligible Data Scope & 2022 Clarification**:
   - **Station-Specific P90 Baseline**: The empirical baseline uses valid daily maxima from the fixed 2022–2025 June–September period across the primary stations. Missing days are never imputed. SFO 2025 valid daily maxima contribute to the baseline calculation under the frozen pooled rule, but SFO 2025 fails the event-screening eligibility gate (97.54% < 98.0%) and is excluded from event detection. Weather data for 2022 remains in the baseline and weather-only event catalogue.
   - **Joint Weather-Price-Carbon Evaluation**: Authorized only for **years 2023, 2024, and 2025** across eligible station-hub pairs.
   - **Year 2022 Exclusion**: While 2022 heatwaves are identified in the meteorological catalogue, they are **excluded from joint weather-price-carbon scheduler evaluations** under the current protocol because EIA 2022 is excluded (missing 2022-06-13 17:00:00 UTC at the federal source).
   - **SFO 2025**: Excluded from heatwave analysis due to sub-threshold daily-max coverage (97.54% < 98.0%).
   - **Year 2026**: Restricted to provisional sensitivity analysis.
3. **Zero-Imputation Principle**: No missing observation may be forward-filled, interpolated, or synthetically created.
4. **No Phase 3 Work Executed**: Phase 3 event detection, control selection, forecasting, scheduler runs, and outcome inspection have **not** been started.
