# P12 Track B2 data-source matrix

**Status:** pre-acquisition audit; no Track B2 data has been downloaded.  
**Rule:** presence of a station or hub in an official catalogue does not prove complete 2022-2026 hourly coverage. Day 2 must measure coverage from acquired files.

## 1. Weather-station candidates

| Priority | Location | GHCNh ID | Approx. station setting | Proposed hub | Local repository state | Day-2 decision |
|---:|---|---|---|---|---|---|
| 1 | San Francisco International | `USW00023234` | coastal airport; marine influence; not representative of all Bay Area inland heat | `TH_NP15_GEN-APND` | 2022-2025 PSV files present; 2026 absent | retain if 2026 and selected-window coverage pass |
| 2 | Sacramento Airport/Executive | `USW00023232` | low-elevation inland urban-airport setting | `TH_NP15_GEN-APND` | configured, but no local raw files | compare with predeclared `USW00093225` only on coverage/metadata before freeze |
| 3 | Fresno Yosemite International | `USW00093193` | hot Central Valley inland airport | `TH_ZP26_GEN-APND` | not configured; no local raw files | retain if hourly coverage and ZP26 price coverage pass |
| 4 | Redding Airport | `USW00024257` | far-northern inland airport; very hot/dry regime | `TH_NP15_GEN-APND` | not configured; no local raw files | retain if it adds eligible independent episodes and coverage passes |
| 5 | Los Angeles International | `USW00023174` | southern coastal airport; marine influence; not inland LA | `TH_SP15_GEN-APND` | configured, but no local raw files | retain if hourly coverage and SP15 price coverage pass |

NOAA official metadata confirms the station identities. The GHCNh station list/documentation must be snapshotted into the B2 source manifest at freeze time. Candidate Sacramento replacement: `USW00093225`, Sacramento Metropolitan Airport. A replacement changes representativeness and must be documented; it is not a free sensitivity choice.

## 2. Market and carbon mappings

| Signal | Proposed source/identifier | Geographic interpretation | Current local evidence | Required validation |
|---|---|---|---|---|
| NP15 DAM LMP | CAISO OASIS `PRC_LMP`, `TH_NP15_GEN-APND` | northern trading-hub signal for SFO/Sacramento/Redding; not a retail tariff | parser and 2024 NP15 cache verified; some 2022 prices embodied in frozen v1 benchmark | 24/24 bins per day, total `LMP_PRC`, DAM, node identity, duplicate resolution for every selected window |
| ZP26 DAM LMP | `TH_ZP26_GEN-APND` | central trading-hub proxy for Fresno | official CAISO materials list the node; no local B2 cache | same validation plus historical access for 2022-2026 |
| SP15 DAM LMP | `TH_SP15_GEN-APND` | southern trading-hub proxy for LAX | official CAISO materials list the node; no local B2 cache | same validation plus historical access for 2022-2026 |
| Carbon proxy | EIA CISO production-based intensity | one balancing-authority-wide average shared by all stations | local CISO workbook exists; v1 retains issue flags | complete selected-window hours, unit reconciliation, issue flags and exact workbook/source hash |
| Demand/generation | EIA-930 CISO | system context, not station-local demand | ingestion/parser implemented | selected-window coverage and hour-ending to interval-start conversion |

CAISO OASIS exposes NP15, SP15 and ZP26 hub prices, and the standard recent-data path has a rolling historical-access limitation. The official historical downloader must be used for older windows when required. Hub mapping is a reproducible regional proxy, not proof that a hypothetical facility pays that price.

## 3. Coverage report schema

Create `data/v2/manifests/p12_b2_source_coverage.csv` with one row per station/year/source and at least:

```text
station_id, station_name, latitude, longitude, elevation_m,
year, season_start_local, season_end_local,
expected_hours, observed_hours, valid_temperature_hours,
missing_hours, duplicate_hours, conflict_hours,
expected_local_days, valid_daily_max_days,
source_url, retrieval_timestamp_utc, sha256, bytes,
provisional, eligibility_status, rejection_reasons
```

Create a companion price/carbon table by hub/year with expected/observed hourly bins, missing/duplicate counts, product/component identities, issue-flag counts and provenance.

## 4. Eligibility thresholds

- NOAA screen: at least 95% expected hourly temperature bins and 98% valid warm-season daily maxima; zero missing daily maxima inside any selected event/control/ordinary window.
- CAISO: exactly one validated DAM total-LMP value per UTC hour in every selected window after deterministic duplicate handling.
- EIA: exactly one demand/generation/carbon value per required interval; issue flags retained. Data issues may trigger sensitivity/exclusion but may not be silently called clean.
- 2026: provisional until the entire June-September screen and all selected windows pass every source gate. The current date being after September does not substitute for file-level completeness checks.

## 5. Forecast-training inputs

If station-specific TinyLSTM artifacts are used, acquire a separate pre-evaluation weather training range (recommended 2018-2021 plus a pre-first-event 2022 validation/calibration interval). Store it outside the 2022-2026 event-population manifest and record that it is model-training data, not an evaluated season.

## 6. Security and distribution

- `.env` is ignored and must remain outside archives/logs.
- Never store EIA, AWS or other credentials in configs, notebooks, provenance URLs or command transcripts.
- The current tracked tree contains a historical discussion of WattTime credential exposure in `docs/p11_external_reproduction_recovery_plan.md`; no credential value was printed during this planning audit.
- Before any public B2 package, run a current-tree and reachable-history secret scan, verify revocation/rotation separately, and distribute only sanitized source URLs/parameters.
- Large raw data should be distributed through documented official retrieval plus checksums or a licensed content-addressed data release, not committed ad hoc.

## 7. Expected artifacts

```text
data/v2/manifests/p12_b2_station_metadata.json
data/v2/manifests/p12_b2_source_coverage.csv
data/v2/manifests/p12_b2_price_carbon_coverage.csv
data/v2/manifests/p12_b2_raw_sources.jsonl
data/v2/processed/p12_b2_hourly_<station>_<year>.parquet
```

No file above exists yet. This document records the plan, not successful acquisition.

## 8. Verification sources

- NOAA GHCNh product description and access: <https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly>
- NOAA station metadata/search entry point: <https://www.ncei.noaa.gov/cdo-web/search>
- CAISO OASIS market-data portal: <https://oasis.caiso.com/mrioasis/logon.do>
- CAISO OASIS API specification: <https://www.caiso.com/documents/oasisapispecification.pdf>
- EIA hourly electric-grid monitor/API documentation: <https://www.eia.gov/electricity/gridmonitor/about>

These links verify source identity and access routes only. They do not replace the file-level 2022-2026 completeness audit required on Day 2.

**Track B2 implementation plan prepared. No new scientific experiments have been executed.**
