# 2. From HeatTrace v1 to Track B2

## 2.1 Chronology

The Git history shows v1 progressing through ingestion/alignment, events, scheduling, forecasting/thermal modeling, a frozen P6 protocol, P7 dry-run freeze, P8 756-cell execution, P9 analysis, P10 validity freeze, and P11 reproduction/archive. P11 commits `995a5b7` through `1114e5b` created and corrected the portable archive and reports. B2 files exist in the working tree but are not in Git at current `HEAD ef506a5`; that fact is central to reproducibility.

### v1, P1–P11

- Geographic scope: SFO (`USW00023234`) paired with CAISO NP15 and EIA CISO.
- Historical catalogue: four authentic detected SFO heatwaves over 2022–2025. The July 2024 event was development; three 2022 events became frozen confirmation triplets.
- Controls: same-duration matched non-event windows. Event-blind windows were selected without heatwave labels/outcomes to represent conventional historical evaluation.
- Policies: static, capacity-aware, full thermal-aware, calibrated/fixed HeatGuard, and non-deployable oracle.
- Forecasting: 72-hour, five-feature TinyLSTM to 24-hour temperature; historical persistence market forecast.
- Matrix: 756 rows = 432 core event/control + 216 event-blind + 72 HeatGuard + 36 oracle. Equivalently, 3 triplets × 252 cells. These are configuration/seed repetitions nested in only three historical events.
- P11: a second zero-resume execution produced 756/756 successes and matched all 44 real non-operational columns after run-ID alignment. It did not reacquire raw data, lock dependencies, or run in a clean independent environment.

### Track B2, P1–P6

Professor feedback motivated broader temporal and geographic evidence: five stations—SFO, SAC, FAT, RDD, LAX—over 2022–2026, with regional episodes as the independent unit.

#### P1 — protocol and preservation

Objective: freeze the B2 research contract without pooling it with v1 and protect P11 hashes. Inputs are `configs/p12_b2_protocol.yaml`, `docs/p12_b2_frozen_protocol_draft.md`, and the v1 archive. Output is `data/v2/manifests/p12_b2_protocol_freeze.json`. The protocol freezes stations, warm season, P90 event rule, episode grouping, controls, K=20 ordinary windows, workloads, policies, forecast rules, G1–G5, and decision gates. Important limitation: the YAML still labels itself `1.0-draft` / pending authorization even though later documents treat it as frozen.

#### P2 — data acquisition and validation

Code: `scripts/p12_b2_acquire_sources.py` and `src/heattrace/process/p12_b2_coverage.py`. It parses NOAA GHCNh, CAISO DAM LMP, and EIA-930/CISO workbook data; writes 30 NOAA station-year coverage rows, 20 market/carbon coverage rows, processed Parquets, source hashes, and gap inventories. Reported test command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_p12_b2_coverage.py tests/test_p1_ingest.py -q
```

Actual status: 23 NOAA PASS, six 2026 PROVISIONAL, SFO 2025 EXCLUDED; CAISO has complete 15 hub-years; EIA has 2023–2025 PASS, 2026 PROVISIONAL, and 2022 EXCLUDED for one missing off-event hour. Stage 2 criticizes dropping all 2022 joint events for that one hour.

#### P3 — events and regional episodes

Code: `scripts/p12_b2_detect_events.py` and `src/heattrace/process/p12_b2_events.py`. Command:

```bash
.venv/bin/python scripts/p12_b2_detect_events.py
```

Inputs are processed hourly station files and coverage manifests. Outputs are thresholds, screening, 25 station events, 4,320 hourly phase labels, 15 regional episodes, and an event-freeze manifest. Counts: 12 eligible events, nine 2022 excluded, four 2026 provisional; seven eligible episodes. Thresholds are SFO 25.6°C, SAC 38.3°C, FAT 40.6°C, RDD 41.7°C, LAX 26.7°C. Stage 2 verified the algorithm, while noting transitive chaining in episode 08.

#### P4 — controls, ordinary windows, workloads, matrix freeze

Code: `src/heattrace/process/p12_b2_windows.py`, especially `B2Phase4Pipeline.select_matched_control_for_event`, `select_ordinary_windows_from_candidates`, `generate_and_freeze_workloads`, and `build_matrix_dry_run`. Inputs: eligible events, thresholds, weather, protocol, hashes. Outputs: 12 controls, 240 ordinary windows, overlap graph, 30 duration/seed/multiplier workload pairs, 6,480-cell dry-run matrix, and window freeze. Selection is outcome-blind. Tests: 28 Phase 4 and 21 Phase 3 tests were reported passing. Limitation: 146/240 selected ordinary windows overlap another selected window.

#### P5 — scheduling execution

Code: `src/heattrace/experiments/p12_b2_runner.py`. Safe inspection commands include:

```bash
.venv/bin/python -m heattrace.experiments.p12_b2_runner --preflight-only
.venv/bin/python -m pytest tests/test_p12_b2_phase5_execution.py -q
```

The full runner command is intentionally not repeated as a recommendation because it writes canonical results. It executed all 6,480 IDs, yielding 5,448 successes and 1,032 structured failures: 936 weather-incomplete and 96 forecast-missing. It records checkpoints, JSONL, Parquet, and a manifest. Critical defect: one SFO checkpoint/scaler and SFO HeatGuard calibration were applied to every station instead of invoking the declared previous-day fallback.

#### P6 — retrospective analysis

Code: `src/heattrace/evaluation/p12_b2_validity.py` and `p12_b2_reporting.py`. Inputs are Phase 5 runs, events, controls, and ordinary windows. Outputs include event/episode metrics, missingness, equal-service audits, ordinary distributions, G1–G5 assessment, seven tables, and four figures. The exact operational estimands were finalized after outcomes were inspected, so P6 calls itself retrospective/exploratory. Reported tests: 12 Phase 6 tests; Stage 2 later ran all 84 B2 tests.

## 2.2 Before versus after

| Dimension | v1 frozen confirmation | B2 executed matrix |
|---|---:|---:|
| Stations | 1: SFO | 5: SFO, SAC, FAT, RDD, LAX |
| Historical years | 2022 confirmation; 2024 development; catalogue 2022–2025 | 2022–2026 catalogue; joint matrix 2023–2025 |
| Station events | 3 confirmatory (+1 development) | 25 catalogue; 12 eligible/matrix |
| Independent grouping | 3 event triplets | 15 episodes; 7 eligible; 6 valid paired episodes for G1 |
| Controls | 1 per triplet | 12 matched controls |
| Ordinary/event-blind | 1 blind per triplet | 20 ordinary windows per eligible event = 240 |
| Matrix rows | 756 | 6,480 |
| Successful rows | 756 | 5,448 |
| Policies | 3 core + 2 HeatGuard + oracle | Same six |
| Multipliers/seeds | 1×,2×,3×; 2 seeds | Same |
| Facility/curves | energy-only/power-capped; low/medium | primary power-capped medium; pair extensions plus low curve/energy-only |
| Hypotheses | H1–H3 frozen; H4 exploratory; H5 comparator | G1–G5; exact P6 estimands retrospective |
| Strongest result | two of three events show −0.5× coarse static boundary effect | 6/6 paired episodes show positive static cap-violation difference, median +8.08h |
| Principal validity issue | small case series | cross-station forecast transfer, equal-service attrition, overlap, incomplete sensitivities |

## 2.3 Dependency chain

Weather/market/grid acquisition → station coverage → daily maxima/P90 → station events → buffered regional episodes → matched controls/ordinary windows → deterministic workloads/matrix → rolling forecasts and schedulers → realized thermal scoring → equal-service and episode aggregation → G1–G5 tables/figures.

