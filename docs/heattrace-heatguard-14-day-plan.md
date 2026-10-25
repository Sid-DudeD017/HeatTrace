# HeatTrace + HeatGuard: revised 14-day implementation plan

Status: planning only. This document does not authorize confirmatory execution or post-outcome tuning.

## Recommended change summary

1. Keep historical-event benchmark validity as the primary contribution.
2. Treat HeatGuard as a bounded secondary algorithm experiment, not as presumed novelty.
3. Reuse the existing causal forecast, policy, thermal, validation, and provenance interfaces.
4. Add one CPU-sized temperature forecaster: a 72-hour, five-feature input mapped directly to 24 hourly temperatures by a one-layer, 32-hidden-unit LSTM.
5. Compare the LSTM with persistence, same-hour-previous-day, and the existing historical forecast before allowing it into HeatGuard.
6. Calibrate one past-only global upper PUE-residual margin and compare it with no margin and a separately frozen fixed margin.
7. Preserve the approved fallback design: one development triplet and three confirmatory triplets. The confirmatory pair is the statistical unit.
8. Reduce the essential unique scheduler grid to 756 runs. Preserve all three confirmatory pairs; cut the secondary objective and optional ablations before cutting events.
9. Add explicit GO/PIVOT/STOP gates for forecast value, scheduler value, runtime, leakage, and confirmatory readiness.
10. If the LSTM does not beat simple forecasts, pivot HeatGuard to the best simple causal forecast. If calibrated risk does not beat fixed margin, retain the result as a negative comparison.

## A. Repository audit

### Complete and reusable

- Historical ingestion and alignment exist for NOAA, CAISO, and EIA data under `src/heattrace/ingest/` and `src/heattrace/process/`.
- Weather-only event detection, event/control construction, fallback Gate 1 materialization, blind-window auditing, and provenance artifacts exist.
- Gate 1 currently freezes one development plus three confirmatory event/control/blind triplets. Plans that assume four confirmatory pairs are stale.
- `src/heattrace/forecast/historical.py` provides a causal historical-persistence provider with fallback behavior and future-actual leakage tests.
- `src/heattrace/forecast/schema.py` defines the current forecast-table contract.
- `src/heattrace/policy/` contains typed scheduling interfaces, greedy policies, feasibility comparison, and a DRO-inspired heuristic explicitly documented as not being a formal Ruparel reproduction.
- `src/heattrace/thermal/model.py`, `facility.py`, `metrics.py`, `scheduler.py`, and `validation.py` provide the approved energy-only and fixed-power-capped facility models, forecast/realized separation, scoring, and adversarial validation.
- P5.5 already contains forecast-sensitivity and policy-distinguishability machinery that can inform, but not replace, the new causal forecast evaluation.
- P0-P2 correctness, triplet, facility, and validity suites are present and passing in the current working tree.

### Partial

- Existing forecasts cover price/carbon persistence and controlled forecast scenarios, but there is no learned temperature forecast provider.
- Existing thermal-aware adapters can consume forecast capacity but do not implement the HeatGuard calibration and rolling-decision contract.
- Existing experiment runners and provenance patterns can be reused, but the revised 756-run matrix and forecast-training manifests are not implemented.
- Existing workload semantics must be frozen in Phase 3 before the rolling scheduler can be judged for deadline completion.

### Missing

- No PyTorch dependency is declared in `pyproject.toml`.
- No TinyLSTM dataset, model, training, checkpoint, evaluation, or calibration module exists locally.
- No compatible pretrained checkpoint has been verified.
- No HeatGuard policy, fixed-margin comparator, rolling replanner, or HeatGuard-specific result schema exists.
- No chronological split manifest currently separates training, calibration, development, and confirmatory forecast origins.

### Architectural blockers to resolve before ML work

- Freeze processing units, arrival/deadline semantics, slack distribution, slack bounds, and two workload seeds.
- Keep forecast values and realized values in separate types/tables through scheduling and scoring.
- Ensure a rolling decision never reads weather later than its forecast origin.
- Ensure unfinished jobs, violations, and failed cells remain explicit in results.
- Preserve P4/P5 behavior and the existing policy interface; use adapters rather than a rewrite.

### Ruparel-reference finding

The cited paper describes a single-layer, 32-hidden-unit TinyLSTM trained per region and per price/carbon/renewable series, using a short univariate sequence, one-step output, MSE, and autoregressive multi-step rollout. The proposed HeatTrace model is materially different: temperature only, 72 x 5 inputs, dropout, SmoothL1, and a direct 24-output head. Therefore:

- call it a lightweight TinyLSTM-inspired backbone;
- do not claim architectural equivalence or faithful reproduction;
- inspect and record the exact upstream commit and license before reusing code;
- do not claim a pretrained checkpoint unless weights, feature schema, scaler, and output horizon are verified.

Primary references:

- Paper: https://doi.org/10.1186/s13677-026-00904-7
- Repository: https://github.com/Hardik27/Carbon-Aware-Scheduler

## B. Revised scientific scope

### Primary contribution: benchmark validity

Question: do independently selected, complete historical heatwaves reveal simulated feasibility-envelope changes or scheduler-ranking changes that matched ordinary and event-blind evaluations miss?

- H1: under the power-capped model, the static scheduler has a lower grid-bounded feasible workload in heatwaves than in matched controls.
- H2: forecast-capacity-aware scheduling recovers part of that tested feasibility loss.
- H3: complete-event evaluation produces materially different feasibility or ranking conclusions from event-blind equal-duration windows.

Support requires paired event-level evidence across the three confirmatory pairs. Grid cells and workload seeds are not independent observations. Failure to meet the frozen support rule is a reportable null.

### Secondary contribution: HeatGuard

- H4: using the same causal temperature forecast, a globally calibrated upper PUE-residual margin reduces realized facility violations and deadline failures relative to deterministic thermal awareness and a frozen fixed margin, without an unacceptable service-normalized cost/carbon penalty.

Evidence supporting H4:

- fewer realized violation hours and/or deadline failures at equal demanded/completed work;
- non-inferior or transparently traded-off cost and production-based carbon proxy;
- improvement visible by event, not only after pooling run cells;
- no confirmatory-data tuning.

Evidence refuting H4:

- fixed margin performs as well or better;
- HeatGuard only reduces violations by dropping or deferring required service;
- the forecast adds no value over persistence;
- improvements disappear in leave-one-event-out or are driven by one event.

### Novelty boundary

Forecasting, LSTMs, thermal-aware scheduling, robust optimization, and forecast-error margins are established prior work. Potential novelty is limited to the combination of a leakage-controlled historical-heatwave benchmark, the specific conservative-capacity formulation, and reproducible event-level findings. Adding an LSTM alone is not a novelty claim.

## C. Updated architecture

```text
NOAA observations ──> chronological split manifest ──> 72x5 windows
                                                   ├─> persistence/day-lag/EWMA
                                                   └─> TinyLSTM 72→24
                                                               │
calibration observations <── forecast errors <── predicted T ──┤
                                                               v
                                              predicted PUE + frozen margin
                                                               │
price/carbon causal forecasts ──────────────────────────────────┤
                                                               v
jobs + deadlines ──> static / deterministic / fixed / HeatGuard / oracle
                                                               │
realized weather, price, carbon ──> realized facility scoring ──┤
                                                               v
                                     immutable run table + manifest
                                                               │
                                   paired event-level analysis and figures
```

Information boundaries:

- Training fits model weights and scalers using training observations only.
- Validation may select epoch and starting hyperparameters.
- Calibration estimates the PUE-residual quantile and fixed comparator margin.
- The development triplet may debug integration and runtime but cannot alter confirmatory event identities.
- Confirmatory weather outcomes cannot change features, scalers, hyperparameters, margins, objectives, or workload levels.
- Deployable schedulers receive only causal forecasts and state available at the decision origin.
- The oracle alone receives realized future sequences and is always `deployable=false`.

## D. Mathematical and operational specification

### Forecast

For each origin `t`, construct `X_t` with shape `[72,5]`:

1. standardized observed temperature;
2. hour-of-day sine;
3. hour-of-day cosine;
4. day-of-year sine;
5. day-of-year cosine.

The 72 rows end at `t-1`; no value at or after `t` is an input. Train-only mean and scale standardize temperature. Calendar features are deterministic and need no fitting.

```text
h_t, c_t = LSTM(X_t), hidden_size=32, layers=1
z_t = Dropout(final_hidden, p=0.1)
T_hat[t:t+24] = Linear(32,24)(z_t)
```

Use AdamW (`lr=0.001`), SmoothL1, batch size 64, at most 50 epochs, fixed seed, and early stopping on chronological validation loss. These are frozen starting settings, not optimized claims.

Forecast metrics: MAE, RMSE, horizon-specific absolute error at 1/6/12/24 hours, heatwave/control error, and extreme-temperature underprediction. Compare with last observation, same hour previous day, and existing persistence/EWMA behavior.

### PUE and residual calibration

Use the already frozen facility curve:

`PUE_hat[t] = f(T_hat[t])`.

On calibration origins only:

`e = PUE(realized_temperature) - PUE_hat`.

Freeze:

`m_cal = max(0, empirical_quantile(e, 0.90, documented method))`.

Then:

`PUE_safe[t] = min(max_pue, PUE_hat[t] + m_cal)`.

This is a heuristic upper residual buffer, not a distribution-free coverage guarantee. Missing or non-finite calibration data fail loudly. If the calibration sample is too small, pivot to the frozen fixed-margin baseline; never estimate from confirmatory outcomes.

### Conservative capacity

Power-capped model:

`C_safe[t] = min(C_nominal, facility_cap_kw / PUE_safe[t])`.

Energy-only model:

`C_safe[t] = C_nominal`; PUE affects facility energy/objective accounting but never compute capacity.

All quantities use kW for power and kWh for one-hour energy slots.

### Objective and units

For scheduled compute energy `E[j,t]` in kWh:

- predicted facility energy = `E[j,t] * PUE_hat[t]` kWh;
- predicted cost = facility energy times `price_hat[t] / 1000` when price is USD/MWh;
- predicted carbon proxy = facility energy times `carbon_hat[t] / 1000` when intensity is g/kWh, yielding kg.

Do not directly add USD and kg. Freeze train/calibration-derived positive reference scales `s_cost` and `s_carbon`, then minimize:

`alpha * predicted_cost/s_cost + beta * predicted_carbon_kg/s_carbon`.

The primary objective and weights must be frozen before confirmation. Raw and normalized components must both be logged.

### Scheduling constraints

- release time and exclusive deadline;
- exact processing/service requirement;
- hourly conservative capacity;
- concurrency and maximum parallelism;
- no duplicate `(job_id,hour)` allocations;
- no silent dropping; unfinished work is explicit infeasibility;
- deterministic tie-breaking and stable IDs.

### Rolling operation

- Issue a 24-hour temperature forecast at each decision origin.
- Replan unfinished eligible work, preserve completed work, and commit only the next execution interval.
- Use only observations available through the origin.
- For a deadline beyond 24 hours, enforce the minimum in-window work needed to keep later completion possible; carry the rest forward. If remaining capacity cannot preserve feasibility, report projected infeasibility rather than dropping work.
- Multi-day events use newly available observations at each roll; future realized conditions are never substituted.

### Failure behavior

- Missing checkpoint, scaler, calibration artifact, or causal history: fail the learned-policy run explicitly or use a separately configured and logged simple-forecast pivot; never silently use realized future data.
- Non-finite forecast/PUE/capacity: fail the cell.
- Deadline or facility violation: retain the schedule and violation metrics.
- Training non-convergence: preserve logs and pivot to the best simple baseline.

## E. File-by-file implementation plan

| File | Action and interface | Reuse/dependencies | Tests |
|---|---|---|---|
| `pyproject.toml` | Add a CPU ML optional extra; pin the tested PyTorch range in the frozen environment record. | Keep core installation lightweight. | Import-without-ML and import-with-ML smoke tests. |
| `configs/p6_validity.yaml` | Add split boundaries, model hyperparameters, calibration quantile/method, fixed margin, rolling rule, forecast gate, matrix dimensions, and seeds. | Preserve approved P0-P2 values. | Reject placeholders at freeze, unknown keys, leakage-producing boundaries, invalid margins. |
| `src/heattrace/forecast/dataset.py` | `build_temperature_windows`, chronological split validation, train-only scaler fit/transform. | NOAA/aligned tables and existing forecast schema. | Exact shapes, causal lookback, split disjointness, scaler leakage mutation tests. |
| `src/heattrace/forecast/tiny_lstm.py` | `TinyTemperatureLSTM(input_size=5,hidden_size=32,horizon=24,dropout=0.1)` and checkpoint metadata validation. | Optional PyTorch only. | Shape, determinism in eval mode, CPU save/load, incompatible checkpoint rejection. |
| `src/heattrace/forecast/train_temperature.py` | Seeded CPU trainer with AdamW, SmoothL1, early stopping, atomic checkpoint and JSON history. | Dataset module and provenance hashing. | Tiny synthetic overfit, deterministic seed, train-only fit, interrupted-write safety. |
| `src/heattrace/forecast/evaluate_temperature.py` | LSTM plus persistence/day-lag/EWMA metrics by horizon/context/extreme. | Existing historical provider where compatible. | Metric fixtures, no future actuals, missing-origin handling. |
| `src/heattrace/forecast/calibration.py` | `fit_upper_pue_margin(errors,q=0.90)` and immutable artifact schema. | Frozen facility function. | Quantile method, nonnegative clamp, train/calibration separation, non-finite rejection. |
| `src/heattrace/thermal/heatguard.py` | HeatGuard, deterministic no-margin, fixed-margin adapters; rolling state and conservative-capacity vector. | `FacilityConfig`, forecast builders, policy interfaces, scheduler adapter. | Information-set mutation, capacity formula, completed-work preservation, no silent dropping. |
| `src/heattrace/workload/scaling.py` | Deterministic 1x/2x/3x scaling and stable IDs if not already implemented. | Existing workload schema. | Conservation, stable IDs, unchanged 1x. |
| `src/heattrace/experiments/p6_validity_runner.py` | Enumerate core/blind/algorithm cohorts, resume, explicit failure rows, artifact hashes. | Existing experiment/provenance patterns. | Exact 756 unique essential run IDs, development exclusion, resume and schema tests. |
| `src/heattrace/evaluation/p6_validity.py` | Forecast, benchmark, HeatGuard, paired event, service-normalized, tail-risk, and runtime summaries. | Existing evaluation metrics and bootstrap patterns. | Pair-level aggregation, equal-service filtering, leave-one-event-out. |
| `src/heattrace/cli.py` | Narrow commands for dataset build, train, forecast evaluation, calibration, dry-run, pilot, and frozen execution. | Existing CLI conventions. | Dry-run only; no confirmatory side effects. |
| `tests/test_p6_lstm.py` | Dataset/model/trainer/evaluator tests. | Synthetic data only for unit tests. | Fast CPU suite. |
| `tests/test_p6_heatguard.py` | Risk margin, rolling scheduling, leakage, and workload accounting tests. | Synthetic forecast/job fixtures. | Adversarial bounds and information-set tests. |
| `docs/p6_frozen_protocol.md` | Add split, forecast gate, margin, objective normalization, rolling rule, matrix, and null paths. | Preserve Gate 1/2 decisions. | Placeholder and claim audit before freeze. |

Do not overwrite existing result artifacts. New artifacts use versioned paths for model checkpoints, forecast metrics, calibration, pilot, and confirmation.

## F. Revised 14-day schedule

| Day | Work and required input | Deliverable and exact validation | Effort / fallback |
|---|---|---|---|
| 1 | Preserve completed correctness scope; audit current tree and reference implementation. | Audit section, passing P0 targeted tests, no code copied from upstream. | 0.5-1 day; treat upstream only as prior art if reuse is unclear. |
| 2 | Preserve completed Gate 1 fallback bundle and provenance. | One development + three confirmation triplets; leakage/overlap tests. | Complete; never seek stronger events. |
| 3 | Preserve completed P2 facility abstraction and sources. | Facility/config suites pass; medium primary and low sensitivity frozen. | Complete; no curve retuning. |
| 4 | Freeze workload/deadline units, seeds, scaling, and three core policy information sets. | `test_p6_policy_variants.py`; workload conservation and no-leakage tests. | 1 day; wrap existing policies rather than rewrite. |
| 5 | Build chronological temperature dataset/split manifest and simple baselines. | Dataset hash; causal-window and split-disjointness tests; baseline metric table. | 1 day; STOP ML if training history is insufficient. |
| 6 | Implement/train TinyLSTM on CPU and compare forecasts. | Checkpoint + scaler + history + metrics; LSTM/baseline tests. Forecast Gate GO/PIVOT/STOP. | 1 day; pivot to best simple forecast if no meaningful advantage. |
| 7 | Calibrate PUE margin and implement HeatGuard/fixed/no-margin rolling adapters. | Calibration JSON; `test_p6_heatguard.py`; information-mutation tests. | 1 day; omit rolling ablation before weakening safety tests. |
| 8 | Run development-only pilot across core and algorithm comparators. | Pilot table, trace audit, runtime projection, mechanism review. | 1 day; keep nulls, fix only defects, do not tune on confirmation. |
| 9 | Freeze protocol, split, checkpoint hash, margins, objective, workload rules, and exact matrix. | Config/protocol/checkpoint hashes, Git commit, 756-cell dry-run. | 0.5-1 day; remove optional objective/ablation if runtime is excessive. |
| 10 | Execute frozen essential confirmation once with resume/provenance. | Immutable result + manifest; exactly 756 unique run IDs or explicit failed rows. | 1 day; never exclude based on outcomes. |
| 11 | Produce forecast, benchmark, HeatGuard, event-blind, and event-level analyses. | Mandatory tables/figures, leave-one-event-out, service-normalized comparisons. | 1 day; omit optional plots before mandatory evidence. |
| 12 | Complete methods/results/discussion, including negative paths. | Claim-to-table traceability audit and draft. | 1 day; no new features. |
| 13 | Reproduce from a clean output directory and audit hashes/claims. | Reproduction report; targeted suites; artifact equality. | 1 day; correctness fixes only. |
| 14 | Final evidence triage and package. | Final report, manifest, figures, limitations, submission archive. | 1 day; drop algorithmic claim if unsupported, retain benchmark paper. |

## G. Revised experiment matrix

The approved fallback provides three confirmatory pairs, not four.

### Essential unique runs

1. Core heatwave/control benchmark:
   `3 pairs x 2 contexts x 2 facility models x 2 curves x 3 workload levels x 2 seeds x 1 primary objective x 3 core policies = 432`.
2. Mandatory event-blind benchmark:
   `3 blinds x 2 facility models x 2 curves x 3 workload levels x 2 seeds x 1 primary objective x 3 core policies = 216`.
3. Algorithmic additions on power-capped/medium/primary-objective cells:
   - fixed-margin + HeatGuard: `3 pairs x 2 contexts x 3 workloads x 2 seeds x 2 new policies = 72`;
   - non-deployable oracle: `3 x 2 x 3 x 2 = 36`;
   - static and deterministic thermal-aware cells are reused from the core grid.

Essential unique total: `432 + 216 + 72 + 36 = 756`.

Development pilots and forecast-origin evaluation rows are tracked separately and are not confirmatory scheduler runs.

### Optional, in cut order

1. Second objective across all cohorts: up to 756 additional unique runs.
2. No-rolling HeatGuard ablation: 36 runs.
3. Additional margin-quantile sensitivity: development/calibration only unless separately frozen.
4. Small exact/MILP comparator: development instances only.

Never cut a confirmatory pair before optional objectives, ablations, or repeated configurations.

### Resource estimate

- TinyLSTM has roughly six thousand trainable parameters; CPU training should fit comfortably within ordinary workstation memory. Measure actual wall time and peak RSS in the development run rather than promising a duration.
- Forecast tensors are small; PyTorch runtime overhead, not model size, dominates memory.
- The 756 scheduler cells should be checkpointed by pair/cohort. Gate 3 requires a measured pilot projection before confirmation.

### Statistical unit

Aggregate seeds/configurations within each pair and prespecified cell before paired contrasts. Report all three pair effects, sign consistency, descriptive intervals, and leave-one-pair-out results. Do not present run count as sample size.

## H. Publication-critical evidence

Mandatory:

1. Table: event/control/blind identities, weather, price, demand, and data completeness.
2. Figure: temperature to PUE and effective-capacity relationship for low/medium curves.
3. Figure: grid-bounded feasibility envelope by context and policy.
4. Figure/table: policy ranking by paired event/control and event/blind contrasts.
5. Figure: complete-event versus event-blind conclusion comparison.
6. Table/figure: forecast MAE/RMSE and 1/6/12/24-hour error, including extreme underprediction.
7. Figure/table: HeatGuard versus deterministic and fixed-margin comparators for violations, deadlines, completed work, service-normalized cost/carbon, and runtime.

Optional:

- calibration coverage by horizon;
- no-rolling ablation;
- cost-carbon frontier;
- small exact-comparator optimality gap;
- extra qualitative traces beyond one representative development and one confirmatory event.

## I. Risk register

| Risk | Detection | Frozen fallback |
|---|---|---|
| Only three confirmatory pairs | Gate 1 catalogue count | Small bounded case series; report all pair effects; no population claim. |
| Weak thermal effect | Development feasibility envelope | Keep parameters frozen; emphasize energy/accounting findings or report null. |
| LSTM does not beat simple forecasts | Day 6 metric gate | Use best causal simple baseline in HeatGuard; report negative LSTM result. |
| Insufficient training data | Split/window count and seasonal coverage | STOP learned model; use persistence/day-lag/EWMA. |
| Forecast leakage | Future-actual mutation and split tests | Block freeze until fixed; no waiver. |
| HeatGuard only adds conservatism | Equal-service and fixed-margin comparison | Report as negative result; do not claim algorithmic improvement. |
| No ranking reversal | Paired confirmation | Report null; benchmark can still contribute data/protocol evidence. |
| Event-blind sampling finds same failures | H3 comparison | Reject H3 and narrow benchmark claim. |
| Runtime/implementation overload | Day 8 measured projection | Drop second objective, no-rolling ablation, and MILP in that order. |
| Inappropriate physical claims | Claim audit | Use “simulated power-capped facility model”; never claim observed outage/capacity loss. |
| Too few independent events | Event-level uncertainty | Descriptive pair effects and leave-one-out; no asymptotic population inference. |
| Incompatible upstream code/checkpoint | Commit/schema/license audit | Reimplement the small architecture locally; label it inspired, newly trained. |
| Deadline beyond 24-hour horizon | Rolling adversarial tests | Preserve feasibility reserve and explicit projected infeasibility. |

## J. Sequential single-agent execution prompts

### Prompt 1 — workload and policy contract

Own only workload scaling, P6 policy wrappers, their tests, and the necessary validity-config fields. Freeze units, deadlines, slack, and two seeds with human-approved values. Implement deterministic 1x/2x/3x scaling and static/capacity/full-aware/oracle wrappers over existing interfaces. Oracle is always non-deployable. Add workload-conservation, stable-ID, information-mutation, deadline, capacity, and no-silent-dropping tests. Do not edit events, facility equations, forecasting, runner, or results. Run only targeted policy/workload/P4 compatibility suites and `git diff --check`.

### Prompt 2 — causal dataset and simple forecast baselines

Own only `src/heattrace/forecast/dataset.py`, the narrow additions to existing forecast modules, config split fields, and forecast tests. Build 72x5 temperature windows with the last input at origin-1, chronological train/validation/calibration/development/confirmation boundaries, and a train-only scaler. Implement last-observation, same-hour-previous-day, and compatible persistence/EWMA baselines. Produce metric fixtures without reading confirmatory outcomes for tuning. Do not add PyTorch or HeatGuard yet. Tests must mutate future actuals and confirmation data and prove training artifacts unchanged.

### Prompt 3 — TinyLSTM training and evaluation

Own only `tiny_lstm.py`, `train_temperature.py`, `evaluate_temperature.py`, `tests/test_p6_lstm.py`, the optional ML dependency, and versioned model artifacts. Implement the exact 72x5 -> LSTM(32, one layer) -> dropout(0.1) -> linear(24) model with AdamW, SmoothL1, fixed seed, max 50 epochs, and early stopping. CPU only. Save scaler, checkpoint metadata, split hash, config hash, seed, history, and metrics atomically. Compare against all simple baselines. Do not claim equivalence to Ruparel: record that the cited model is one-step autoregressive and the HeatTrace model is direct multi-horizon. If the forecast gate fails, stop and recommend the best simple baseline.

### Prompt 4 — calibration and HeatGuard

Own only calibration, `thermal/heatguard.py`, their tests, and narrow exports. Fit the frozen empirical 0.90 upper residual quantile on calibration data only. Implement deterministic no-margin, frozen fixed-margin, HeatGuard calibrated-margin, and oracle reference using the same forecast where applicable. Use the approved energy-only/power-capped facility API. Implement rolling 24-hour replanning that commits one interval, preserves completed work, carries unfinished work, handles beyond-horizon deadlines, and never reads future realized data. Log raw objective units, normalized components, violations, deadlines, completed work, and runtime. Do not edit event selection, facility parameters, model training, or results.

### Prompt 5 — pilot, runner, and freeze candidate

Own only the revised P6 runner, CLI hooks, provenance schema, and runner tests. Enumerate the exact cohorts and prove 756 unique essential run IDs, three confirmatory pairs, development exclusion, reused core cells, stable IDs, explicit failure rows, atomic checkpoint/resume, and complete hashes. Run development data only. Produce a runtime projection and GO/PIVOT/STOP report. Do not execute confirmation or tune parameters.

### Prompt 6 — frozen execution and analysis

After human approval and saved hashes, execute the frozen 756-cell matrix once. Own only versioned output, manifest, evaluation, and figure paths. Do not edit scientific configuration, model, margins, events, facility, policies, or workloads. Aggregate seeds before pair contrasts; use pair as the independent unit; retain failures; separate unequal-service cost/carbon comparisons; mark oracle non-deployable; produce mandatory evidence and null-result wording.

### Prompt 7 — reproduction and claims audit

Using a clean output directory, reproduce forecast metrics, calibration artifact, 756 run IDs, manifest hashes, mandatory tables, and figures. Fix only mechanical reproducibility or evidence-traceability defects. Verify every numerical claim against source tables, every use of “LSTM-assisted” against the forecast gate result, and every HeatGuard improvement against deterministic and fixed-margin comparators. If unsupported, remove the improvement claim but preserve the negative result.

