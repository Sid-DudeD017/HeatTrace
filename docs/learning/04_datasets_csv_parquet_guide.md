# 4. Dataset, CSV, Parquet, JSON, and YAML guide

## 4.1 Raw observations versus model artifacts

Raw NOAA PSV and CAISO ZIP files, plus the EIA workbook/JSON, are historical sources. Processed Parquets are transformations. Event/control files are frozen benchmark definitions. Workload traces are synthetic. Matrix rows are planned configurations. Run rows are simulated outcomes. Analysis tables are derived evidence.

## 4.2 B2 source and processed data dictionary

| Path | Shape inspected | Meaning and units | Producer → consumer |
|---|---:|---|---|
| `data/v2/manifests/p12_b2_source_coverage.csv` | 30×26 | NOAA station/year coverage; °C metadata, hours/days, hashes, PASS/EXCLUDED/PROVISIONAL | acquisition → event gate |
| `data/v2/manifests/p12_b2_price_carbon_coverage.csv` | 20×19 | 15 CAISO hub-years and 5 EIA BA-years; USD/MWh, MW, gCO2/kWh | acquisition → joint eligibility |
| `data/v2/processed/p12_b2_hourly_<STATION>_<YEAR>.parquet` | normally 2,928×12 | UTC/local time, °C min/max/aggregate, observation count, missing/conflict flags | P2 → P3/P5 |
| `data/v2/processed/p12_b2_caiso_all_parsed.parquet` | 45,255×7 | node, DAM/LMP type, price USD/MWh, source ZIP | P2 → P5 |
| `data/v2/processed/p12_b2_eia_all_parsed.parquet` | 8,784×15 | CISO demand/net generation MWh, emissions tons, generated/consumed intensities | P2 → P5 |

Coverage columns are self-describing; the key distinction is `observed_hours` (raw observations can be subhourly) versus `valid_temperature_hours` (expected hourly bins). `eligibility_status` is a gate, and `rejection_reasons` explains failures. Example: SFO 2022 has 2,928 valid hourly temperatures, 122 valid daily maxima, zero gaps/conflicts, and PASS.

An hourly weather row such as SFO 2024-06-01 07:00 UTC records local midnight, 13.3°C, one observation, no conflict, and the raw-source SHA-256. A CAISO row records interval-start UTC and a hub LMP. An EIA row distinguishes generated and consumed intensity; B2 scoring uses `co2_intensity_consumed_g_per_kwh` as a statewide proxy.

## 4.3 Event catalogue

### `p12_b2_thresholds.csv` — 5×17

Columns: `station_code`, NOAA identity/name, `climate_class`, `caiso_proxy_hub`, timezone, percentile/method, baseline years, expected/valid/missing days and dates, sample size, `threshold_p90_c`, min/max daily maximum. Example SFO: 485/488 valid days, P90 25.6°C, three missing SFO 2025 dates.

### `p12_b2_station_events.csv` — 25×31

Identity/location columns are followed by threshold metadata; local start/end/peak; UTC event start/end; duration; peak/mean maximum; cumulative exceedance in °C-days; onset/recovery/full-window boundaries; episode ID; year; eligibility; provisional/exclusion reason; source files.

Representative row `B2_HW_SFO_20220620`: 20–22 June, three qualifying days, peak 36.7°C, 72 active hours, full 120-hour window from 19–24 June, episode 01, weather PASS but joint EXCLUDED because of the EIA 2022 annual gate.

### `p12_b2_regional_episodes.csv` — 15×13

Columns give episode ID, 24h buffer, component/event boundaries, member/station counts, delimited station and event IDs, years, independent-unit flag, and eligibility summary. Regional episodes—not cells, seeds, or stations—are the primary uncertainty unit.

### `p12_b2_hourly_phase_labels.parquet` — 4,320×17

Each event-hour row has UTC/local timestamps, phase and Boolean phase flags, active-heatwave flag, daily maximum, threshold, exceedance, and missingness. `peak` marks the peak local date; `sustained` marks other qualifying event days; onset/recovery are padding.

## 4.4 Controls, ordinary windows, and workloads

`p12_b2_controls.csv` is 12×24. It records the event/episode/station, source and selected year, local/UTC bounds, duration, same-year/fallback status, deterministic rank/score, coverage, embedded-event and protected-overlap checks, and hashes. Example: RDD 2023’s 144-hour event is matched to 7–13 July with weekday difference 0, calendar distance 5, weather distance 8.15.

`p12_b2_ordinary_windows.csv` is 240×24. It adds seasonal stratum, primary-selection flag, overlap component, `overlaps_another_selected_window`, and fallback/limitation labels. Exactly 146 selected rows overlap another selected window.

Workload files under `data/v2/workloads/` are CSV/Parquet pairs for five durations × two seeds × three multipliers = 30 traces. Columns are:

| Column | Meaning |
|---|---|
| `workload_trace_id`, `job_id` | deterministic trace/job identity |
| `arrival_offset_hours` | first hour job can run |
| `deadline_offset_hours` | exclusive deadline |
| `processing_requirement` | required one-hour allocation slots |
| `energy_kwh` | total job IT energy apportioned across slots |
| `maximum_parallelism` | simultaneous units allowed |
| `priority`, `preemptible` | job attributes |
| `seed`, `generator_version` | reproducibility metadata |

The first 120h, seed 20261016, 1× job arrives at hour 0, deadline 15, requires one slot, uses 71.93 kWh, and is preemptible. Multipliers scale demand. Workload hashes guarantee the same trace is reused across event/control/equal-duration ordinary windows.

## 4.5 Matrix and run results

`p12_b2_matrix_cells.csv` is 6,480×17. Its columns define run ID, track, event/episode/station, window type/ID/duration, facility, curve, policy, multiplier, seed/hash, objective, role, and deployability.

The total is:

\[
12[18(20+2)+144]=12(540)=6480.
\]

For every event, 18 primary cells (3 policies × 3 multipliers × 2 seeds) run on the event, its control, and 20 ordinary windows: 396. The event/control pair also gets 108 v1-grid extensions, 24 HeatGuard cells, and 12 oracle cells: 144. Matrix IDs existing only prove planned/terminal coverage; status determines success.

`p12_b2_runs.parquet` is 6,480×43. After identity/configuration fields it contains execution/failure status; scheduler/thermal feasibility; jobs and processing accounting; IT/cooling/facility energy; peak power, violation hours and maximum exceedance; cost/carbon; margin; forecast identity/cutoff; runtime/hash. Failed rows set unevaluated metrics null.

Example run `p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__static_unaware__m1__s20261016__carbon_first` decodes as B2, RDD event, heatwave window, capped/medium facility, static policy, 1× workload, seed 20261016, carbon objective. Its row is SUCCESS but scheduler- and thermally-infeasible: 127 demanded slots, 124 completed, three unfinished, five cap-violation hours, 35.9888 kW maximum exceedance, 8,493.3048 kWh facility energy, $550.5815, and 1,850.1808 kg proxy carbon. Stage 2 re-executed this cell and reported a bit-identical result.

## 4.6 Analysis artifacts

| Path | Shape | Interpretation |
|---|---:|---|
| `p12_b2_missingness_audit.csv` | 29×10 | successes/failures by scope; weather vs forecast missing |
| `p12_b2_equal_service_audit.csv` | 9×6 | pair-level service inclusion; separate trio audit is table 8 |
| `p12_b2_event_metrics.csv` | 48×22 | policy-level heatwave-minus-control event effects |
| `p12_b2_episode_metrics.csv` | 36×19 | event effects aggregated to episode |
| `p12_b2_ordinary_distributions.csv` | 25×15 | common support, K, P95, classification |
| `p12_b2_g1_g5_assessment.csv` | 5×8 | final P6 classifications and evidence summary |
| `tables/table8_equal_service_audit.csv` | cohort audit | 7/66 heatwave, 19/48 control, 430/1,230 ordinary core trios pass |
| `tables/table9_g4_continuity_gate.csv` | one row | failed causal ablation gate |
| `tables/table10_g5_robustness_inventory.csv` | 10 rows | one executed, nine absent sensitivities |

## 4.7 v1 evidence artifacts

The canonical v1 run table is `data/archive/heattrace_v1_d5b3c86/canonical_p8/p6_validity_runs.parquet` (756×46). Important fields mirror B2 but use `triplet_id`, `context`, cohort, policy/margin, demanded/completed energy/slots, facility excess, cost/carbon, feasibility, and frozen hashes. `canonical_analysis/p6_h1_h5_assessment.csv` is 5×9; event, pairwise, cohort, feasibility, equal-service, and forecast-evidence CSVs sit beside it. `frozen_benchmarks/p6_event_control_index.csv` contains the three confirmation plus one development triplet.

## 4.8 Trace one heatwave end to end

For `B2_HW_SFO_20240702`: raw `GHCNh_USW00023234_2024.psv` → hourly SFO 2024 Parquet → local daily maxima compared with 25.6°C → event row and hourly phases → regional episode 08 → selected control and 20 ordinary windows → duration-specific workload hashes → matrix IDs → run rows → event/episode metrics → G1/G3 tables and figures. Price rows come from NP15 CAISO archives; carbon rows come from the shared CISO EIA table. The forecast-aware row then incorrectly uses the v1 SFO artifact—which is valid only for SFO, not evidence for transfer to other stations.

## 4.9 JSON/YAML manifests

Protocol/event/window/execution manifests record hashes, counts, provenance, and freeze identities. JSONL files are append-style source or execution ledgers. Checkpoint JSON files record completed IDs/batches. They are reproducibility metadata, not independent scientific observations. The P11 archive manifest plus `verify_archive.py` provides a 54-file hash inventory.

