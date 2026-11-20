# 3. Repository and code walkthrough

## 3.1 Scientific tree

```text
configs/                         frozen and development YAML contracts
scripts/                         B2 acquisition and event entry points
src/heattrace/
  ingest/                        NOAA, CAISO, EIA parsing/provenance
  process/                       alignment, events, controls, B2 coverage/events/windows
  workload/                      deterministic synthetic jobs and scaling
  forecast/                      datasets, baselines, TinyLSTM, calibration
  policy/                        generic greedy policies and feasibility adapters
  thermal/                       PUE/facility model, B2 policies, HeatGuard, scoring
  experiments/                   grids and v1/B2 runners
  evaluation/                    run metrics and H1–H5/G1–G5 analysis
  analysis/                      earlier P5/P5.5 characterization and figures
data/
  raw/, processed/               v1 historical inputs
  events/, benchmarks/           v1 events and frozen triplets
  models/, forecasts/            v1 learned/forecast artifacts
  results/, figures/             v1 execution and analysis outputs
  archive/                       immutable P11 bundle and verifier
  reproductions/                 P11 rerun outputs
  v2/raw/, processed/            B2 inputs
  v2/events/, benchmarks/        B2 event/window/matrix freezes
  v2/workloads/, checkpoints/    deterministic jobs and execution state
  v2/results/, tables/, figures/ B2 P5/P6 evidence
docs/                            protocols, reports, handoffs
tests/                           unit, integration, and scientific-contract tests
reproduction_audits/             Stage 2 B2 audit
```

There is no important `src/heattrace/process/experiments` folder; experiments are a sibling package. `data/v2/models/` is absent, which is part of the forecast-protocol failure.

## 3.2 Important Python files

| File | Purpose and important symbols | Inputs → outputs | Phase |
|---|---|---|---|
| `ingest/noaa.py` | NOAA PSV parsing/quality | GHCNh → observations | v1/B2 P2 |
| `ingest/caiso.py` | OASIS archives/LMP filtering | ZIP/XML/CSV → hourly LMP | v1/B2 P2 |
| `ingest/eia.py` | EIA/CISO workbook and intensity fields | XLSX/JSON → grid/carbon rows | v1/B2 P2 |
| `process/alignment.py` | hourly aggregation and UTC alignment | raw domains → aligned hours | v1 P2; reused B2 |
| `process/events.py` | original SFO event detector | aligned weather → v1 catalogue | v1 P3 |
| `process/controls.py` | original control matching | events/weather → controls | v1 P3 |
| `process/p12_b2_coverage.py` | B2 coverage records/gates | station/source stats → manifests | B2 P2 |
| `process/p12_b2_events.py` | `compute_station_p90_threshold`, `detect_b2_station_events`, `cluster_regional_episodes`, `build_b2_hourly_phase_labels` | hourly stations → events/episodes | B2 P3 |
| `process/p12_b2_windows.py` | `B2Phase4Pipeline`, control/ordinary selection, workloads, matrix | frozen events → 6,480 cells | B2 P4 |
| `workload/generator.py` | deterministic job generation/validation | duration, seed → job trace | v1/B2 |
| `workload/scaling.py` | multiplier/seed trace derivation | base trace → scaled workload | v1/B2 |
| `forecast/dataset.py` | causal 72×5 windows and training-only scaler | SFO history → tensors | v1 P4/P6 |
| `forecast/tiny_lstm.py` | baselines and `TinyTemperatureLSTM` | 72×5 → 24 temperatures | v1/B2 reused |
| `forecast/calibration.py` | past-only residual calibration | forecast/realized pairs → margin | v1 P6 |
| `thermal/model.py` | `ThermalScenario`, PUE/power/capacity equations | temperature → thermal state | v1/B2 |
| `thermal/facility.py` | energy-only/power-capped state builders | forecast/realized temperature → facility table | v1/B2 |
| `thermal/scheduler.py` | `HeatAwareCapacityAdapter` | greedy allocation → capacity-respecting repair | v1/B2 |
| `thermal/policies.py` | six policy classes | workloads/forecasts/states → schedule | v1/B2 |
| `thermal/heatguard.py` | fixed/calibrated rolling safety margin | forecasts/calibration → guarded capacity | v1/B2 |
| `thermal/metrics.py` | realized energy, violations, cost, carbon | allocation + realized state → metrics | v1/B2 |
| `experiments/p6_validity_runner.py` | frozen v1 matrix and 24h/1h rolling execution | P6 freezes → 756 rows | v1 P8/P11 |
| `evaluation/p6_validity.py` | H1–H5 tables/figures | 756 rows → evidence | v1 P9/P10 |
| `experiments/p12_b2_runner.py` | `B2ExecutionRunner`, window preparation, execution/checkpoints | B2 matrix → 6,480 terminal rows | B2 P5 |
| `evaluation/p12_b2_validity.py` | missingness, equal service, G1–G5 | B2 runs → analysis CSVs | B2 P6 |
| `evaluation/p12_b2_reporting.py` | four B2 plots and seven tables | P6 DataFrames → figures/tables | B2 P6 |

Original v1 files are the modules without `p12_b2` plus P6 validity code. B2 added the `p12_b2_*` modules, scripts, tests, protocol, and `data/v2`. Historically, `workload/scaling.py` was modified during development phase transitions; in the current repository tree it is tracked and unchanged, and this guide describes its role without altering it.

## 3.3 How to read a scheduler call

`B2ExecutionRunner.execute_cell` decodes one matrix row, loads the frozen workload, prepares realized weather/price/carbon, prepares market forecasts, optionally prepares temperature forecasts, constructs a 100 kW nominal facility, runs the selected rolling policy, then scores committed allocations against realized PUE and market/grid values. Failure rows retain known identity/workload fields but set unevaluated metrics to null.

The deployable loop replans over 24 hours and commits one hour. Generic policies are greedy, then `HeatAwareCapacityAdapter` repairs allocations to fit forecast capacity. This is not a mixed-integer optimizer and not formal distributionally robust optimization.

## 3.4 One source excerpt, explained

From `thermal/model.py`:

```python
excess = np.maximum(arr - scenario.threshold_temperature_c, 0.0)
pue_arr = np.minimum(
    scenario.base_pue + scenario.slope_per_c * excess,
    scenario.max_pue,
)
```

Line 1 clips cool-hour excess to zero. Lines 2–4 add a linear heat penalty and cap PUE. `facility.py` then computes `min(nominal_cap, facility_cap / pue)`. These are controlled sensitivity assumptions, not fitted data-center telemetry.

## 3.5 Tests and what they establish

Tests cover parsers, alignment, event rules, matching, workload/policy accounting, thermal equations, causal forecast boundaries, runner identities, failure schemas, and analysis denominators. Stage 2 ran 84 B2 tests successfully. They establish implementation consistency with assertions—not scientific validity. No test compared the runner’s hard-coded SFO artifact to the protocol’s cross-station prohibition, so all tests passed despite the central defect.

