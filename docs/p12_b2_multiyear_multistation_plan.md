# P12 Track B2 multi-year, multi-station implementation plan

**Status:** planning only; no Track B2 experiment has been executed  
**Prepared:** 2026-10-29  
**Repository baseline:** `main` at `ef506a5f2b27d510c68e742381894caa3a988fea`  
**Historical boundary:** HeatTrace v1/P11 is immutable and remains a separate three-event study.

## 1. Decision and research question

Track B2 asks:

> Do complete historical heatwave events reveal cloud-scheduling feasibility and policy-performance differences consistently across multiple California climate regions and years, compared with matched ordinary conditions and representative event-blind evaluation windows?

This is a benchmark-validity and external-validity extension. It is not a new scheduling-algorithm project and must not change the P11 result, its 756-cell matrix, or H1-H5 classifications.

The candidate evaluation scope is June-September 2022-2026 at five fixed NOAA GHCNh stations:

| Priority | Climate role | Station | NOAA GHCNh ID | Candidate CAISO hub |
|---:|---|---|---|---|
| 1 | Northern coastal | San Francisco International | `USW00023234` | `TH_NP15_GEN-APND` |
| 2 | Northern inland | Sacramento Airport/Executive | `USW00023232` | `TH_NP15_GEN-APND` |
| 3 | Central inland | Fresno Yosemite International | `USW00093193` | `TH_ZP26_GEN-APND` |
| 4 | Far-northern inland | Redding Airport | `USW00024257` | `TH_NP15_GEN-APND` |
| 5 | Southern coastal | Los Angeles International | `USW00023174` | `TH_SP15_GEN-APND` |

These are frozen *candidate identities*, not an assertion that coverage is already adequate. Day 2 must apply the eligibility gate in `docs/p12_b2_data_source_matrix.md`. Sacramento Metropolitan (`USW00093225`) is the predeclared replacement only if `USW00023232` fails coverage or metadata checks; any replacement requires a dated rationale before event detection.

## 2. Repository findings

### Present and reusable

- P6-P11 source is present and tracked, including `src/heattrace/experiments/p6_validity_runner.py`, `src/heattrace/evaluation/p6_validity.py`, the thermal/forecast modules, P6/P7 configs, benchmark inputs, tests, and the P11 archive.
- `data/results/p11_reproduction_comparison.json` records 756/756 successful cells and zero scientific-field differences.
- `data/archive/heattrace_v1_d5b3c86/archive_manifest.json` inventories 54 verified P11 artifacts.
- Reusable components include NOAA/CAISO/EIA parsers, local-day/DST handling, weather-only event detection, phase labeling, deterministic workload generation, rolling policies, equal-service checks, result validation, artifact hashing, and event-level analysis.
- `origin/main` and local `main` both resolve locally to `ef506a5`; the older statement that the remote ends at P5.5 is no longer current.

### Missing or unsuitable for B2 without new v2 work

- No multi-station event catalogue, regional-episode grouping, station-year coverage matrix, variable-duration workload generator, or B2 runner exists.
- Only SFO NOAA files for 2022-2025 are local. No local 2026 SFO file and no local Sacramento, Fresno, Redding, or LAX hourly files are present.
- The current raw CAISO cache is NP15/2024-oriented. SP15/ZP26 and general 2022-2026 coverage are not locally demonstrated.
- Existing event and runner code contains SFO/NP15 and 120-hour assumptions that must be parameterized in a separate v2 namespace rather than edited in place.
- The v1 TinyLSTM and HeatGuard calibration are SFO-specific. B2 may reuse the architecture and algorithms, but not silently apply the SFO scaler/calibration to other stations.
- Exact dependencies remain lower bounds in `pyproject.toml`. A fresh checkout still needs a lock file, verified raw-input retrieval, and archive-to-runtime restoration tooling.
- The older team checklist at `heattrace-team-checklist.snugmouse256.chatgpt.site` stops at a historical P0-P6/P5.5 state and is not the current source of truth.

## 3. Preservation and namespace rules

1. Do not edit `configs/p6_validity.yaml`, `configs/p6_thermal.yaml`, `docs/p6_frozen_protocol.md`, the P6-P11 results, or the P11 archive.
2. Create v2 artifacts under names containing `p12_b2` or `v2`, for example:
   - `configs/p12_b2_protocol.yaml`
   - `data/v2/manifests/`
   - `data/v2/events/`
   - `data/v2/benchmarks/`
   - `data/v2/results/`
   - `data/v2/models/`
3. All v2 manifests must include the P11 archive ID and hash as a historical dependency, never as a mutable input.
4. V1 results may be quoted for motivation but are not pooled into B2 hypothesis tests.
5. Development, protocol-pilot, and confirmatory B2 events must be explicitly labeled and kept separate.

## 4. Proposed implementation structure

| Responsibility | Existing code to reuse | Proposed v2 code/artifact |
|---|---|---|
| Station-aware NOAA coverage | `ingest/noaa.py`, `process/coverage.py` | `process/p12_b2_coverage.py` |
| Station-specific event detection | `process/events.py` | `process/p12_b2_events.py` |
| Regional episode grouping | none | `process/p12_b2_episodes.py` |
| Controls and ordinary samples | `process/controls.py`, `process/p6_event_bundle.py` | `process/p12_b2_controls.py` |
| Variable-duration workloads | `workload/generator.py`, `workload/scaling.py` | `workload/p12_b2_generator.py` |
| Station forecast/calibration artifacts | `forecast/*`, `thermal/heatguard.py` | `experiments/p12_b2_forecasts.py`, `data/v2/models/` |
| B2 experiment enumeration/execution | `experiments/p6_validity_runner.py` | `experiments/p12_b2_runner.py` |
| G1-G5 analysis | `evaluation/p6_validity.py` | `evaluation/p12_b2_validity.py` |
| Frozen protocol/config | P6/P7 contracts as patterns | `configs/p12_b2_protocol.yaml`, signed manifest |

New modules must call reusable pure functions where possible; frozen v1 functions may be wrapped, not behaviorally changed.

## 5. Seven-day critical path

| Day | Task | Existing files reused | New files/artifacts | Acceptance criteria | Main risk |
|---:|---|---|---|---|---|
| 1 | Audit repository; freeze B2 scope, hypotheses, station candidates, episode rule, event duration, controls, and analysis units | P6/P7 configs, P11 reports/archive, `events.py`, `p6_validity.py` | six planning docs; draft `configs/p12_b2_protocol.yaml` design | P11 hashes unchanged; candidate stations and all preregistration decisions recorded; no results read to select B2 events | hidden v1 assumptions or an unresolved forecast protocol |
| 2 | Audit NOAA 2022-2026 hourly completeness; validate NP15/ZP26/SP15 DAM coverage and EIA CISO fields; create provenance/coverage matrix | ingestion modules and coverage contracts | `p12_b2_source_coverage.csv/json`, raw-source manifests | every station-year/hub-year has row counts, missingness, duplicate/DST checks, quality flags, retrieval hash and eligibility; 2026 marked provisional where appropriate | historical OASIS access or station gaps |
| 3 | Detect station-level events with station-specific thresholds; create phase labels; group correlated station events into regional episodes; freeze identities | `events.py`, validation schemas | station event catalogue, hourly labels, episode graph/table, freeze manifest | weather-only selection; no scheduler/price/carbon outcomes read; independent sample count is episode count; v1 events labeled but not merged | too few independent episodes or episode-rule sensitivity |
| 4 | Construct same-station, preferably same-year matched controls and 20 ordinary/event-blind windows per event (30 where available); freeze benchmark matrix | `controls.py`, `p6_event_bundle.py` | control catalogue, candidate audit, ordinary-window sample, combined benchmark and matrix manifest | equal duration and coverage; no heatwave/buffer overlap; outcome-blind deterministic selection; minimum 10 ordinary windows or LIMITED | insufficient valid same-year controls, especially for long events |
| 5 | Run existing policies in B2 namespace using the frozen matrix; validate equal service and causal rolling inputs | thermal/policy/forecast modules; workload generator; P6 runner contracts | B2 checkpoints, execution log, run parquet, manifest | every enumerated cell succeeds or has an explicit failure; no v1 output touched; exact run-ID uniqueness and workload hashes | variable-duration bugs or forecast artifacts not ready |
| 6 | Analyze G1-G3; run bounded G5 sensitivities; pilot G4 only if continuity gate passes; report positive, null and negative events | P6 analysis patterns | event/episode tables, ordinary-window distributions, station/year figures, G1-G5 assessment | station observations nested under regional episodes; equal-service filters enforced; no pseudo-replication; all non-estimable hypotheses marked | sample too small for confirmatory population claims |
| 7 | Reproduce B2 outputs from zero checkpoint in a pinned environment; audit leakage/provenance; prepare paper tables and professor brief | P11 verifier/report patterns | reproduction comparison, artifact archive, paper figures, decision record | zero scientific differences; source and result hashes pass; GO/LIMITED/NEGATIVE/INVALID decision issued | packaging/reproduction consumes final-day margin |

## 6. Forecast and HeatGuard rule requiring Day-1 freeze

The SFO v1 model cannot be applied unchanged to inland and southern stations. The recommended B2 protocol is:

- retain the exact TinyLSTM architecture and training hyperparameters;
- create station-specific v2 scalers, checkpoints, and HeatGuard residual calibrations in `data/v2/models/`;
- use only pre-evaluation information, preferably pre-2022 hourly weather for model training plus a pre-first-event validation/calibration interval;
- keep the same model artifact fixed for all 2022-2026 events at that station;
- compare model accuracy by station and year, but do not create a new forecast-causality claim;
- if pre-2022 coverage or a leakage-safe calibration is unavailable, use a preregistered causal previous-day forecast as the B2 primary arm and classify TinyLSTM/HeatGuard results as secondary rather than applying an invalid cross-station model.

This decision must be frozen before events are run through schedulers.

## 7. Seven-day hypothesis scope

| Hypothesis | Seven-day status | Minimum defensible evidence |
|---|---|---|
| G1 temporal replication | Primary, feasible | event/episode effects in at least two eligible years; episode-level reporting |
| G2 geographic heterogeneity | Primary descriptive; confirmatory only with adequate episodes | at least two independent regional episodes contributing to each compared climate class; otherwise descriptive only |
| G3 benchmark discriminability | Primary, feasible | event effects compared with the distribution of at least 10, target 20-30, outcome-blind ordinary windows per event |
| G4 full-event continuity | Conditional pilot | only if full-history, deadline, arrival and workload-exposure equivalence is validated; otherwise defer |
| G5 robustness | Bounded sensitivity, feasible | predeclared threshold, thermal-curve, cap, and control-sampling variants; no exhaustive tuning |

## 8. Fallback order

The scientific priority is coverage and climate contrast, not simply the original list order:

1. SFO + Sacramento establishes coastal/inland NP15 replication with the least price-pipeline change.
2. Add Fresno to introduce ZP26 and central-inland contrast.
3. Add Redding if its event catalogue adds independent northern episodes rather than duplicates Sacramento/Fresno episodes.
4. Add LAX after SP15 data and coastal representativeness pass.

If five stations are not feasible, a defensible minimum is SFO, Sacramento and Fresno with at least two independent years and explicit episode clustering. Two stations can support a registered report or limited case series, but not a strong multi-region empirical paper.

## 9. Decision conditions

- **GO:** at least three eligible stations spanning coastal/inland and at least two CAISO hubs, multiple independent regional episodes in at least two years, complete primary matrices, successful reproduction, and interpretable G1-G3 evidence (including nulls).
- **LIMITED:** two or three stations or few episodes, incomplete 2026/hub coverage, or only descriptive G2/G4; submit as a bounded case series or registered report.
- **NEGATIVE:** the protocol and data are valid but heatwaves do not discriminate policies more than ordinary windows or effects do not replicate. This is publishable if power and coverage are adequate.
- **INVALID:** outcome leakage, missing/incorrect mappings, pseudo-replication, unequal service, unrecoverable source gaps, failed artifact hashes, or non-reproducible outputs. Do not make scientific claims.

## 10. Optional second week

1. Increase ordinary-window samples from 20 to 30 per event.
2. Complete deferred stations and repeat coverage/freeze gates.
3. Run G4 continuity ablations with retained allocation traces.
4. Add hierarchical/cluster bootstrap uncertainty at the regional-episode level.
5. Containerize the clean-checkout workflow and commission an external reproduction.
6. Finish related work, venue formatting, artifact documentation, and reviewer-facing threat analysis.

**Track B2 implementation plan prepared. No new scientific experiments have been executed.**
