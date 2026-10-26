# HeatTrace complete project handoff (P1–P11)

Audit date: 2026-10-26. Repository boundary: `main` at `287cc958aa1a5267ef00cd17014069e07fa09eb0`. This is a retrospective audit, not a new experiment.

## Executive verdict

HeatTrace v1 is implemented through P11 and has a defensible **LIMITED RESULT**. The frozen confirmatory study contains 756 successful cells and the P11 reproduction contains a second 756-cell execution whose scientific fields are identical to the canonical run. The content-addressed archive verifies 54/54 files. However, the current working tree is not clean; the repository has no release tag; dependencies use lower bounds rather than an exact lock; raw NOAA inputs and the working model paths are Git-ignored; and the P11 report contains a direct contradiction about whether the 756 cells were rerun. Therefore the archived v1 evidence is intact and locally reproducible on this machine, but a third party cannot execute the full simulation from a bare checkout using one documented command without restoring external inputs/model paths and recreating the environment. Evidence: `docs/p11_v1_reproduction_report.md:47-88,142-161`, `data/results/p11_reproduction_comparison.json`, `data/archive/heattrace_v1_d5b3c86/archive_manifest.json`, `pyproject.toml:1-24`, `.gitignore:7-31`, and `src/heattrace/experiments/p6_validity_runner.py:1931-1964`.

Current Git facts:

- Branch `main`, HEAD `287cc95`, 17 commits ahead of `origin/main`; no local tags. Git history places P10 at `d5b3c86`, initial P11 at `995a5b7`, and the latest P11 metadata fix at `287cc95`.
- The working tree has pre-existing untracked models, reproduction outputs, archived invalid pilot material, P8 operational logs, and `docs/p6_validity_report.md`. It is not clean. P11's statement "clean tracked tree verified" describes the reproduction checkpoint, not the present workspace (`docs/p11_v1_reproduction_report.md:10-15`).
- Canonical P8 hashes on disk still match the P11 record: runs/checkpoint `c45391e6…`, manifest `d0dd9f87…`, execution log `de430cee…` (`docs/p11_v1_reproduction_report.md:28-43`).
- The archive verifier was rerun read-only during this audit and reported `SUCCESS: All 54 inventory files verified byte-identical`; its implementation and inventory are `data/archive/heattrace_v1_d5b3c86/verify_archive.py` and `archive_manifest.json`.

## Architecture in one view

```text
NOAA GHCNh hourly temperature (SFO USW00023234)
          |                                  CAISO OASIS DAM LMP (NP15)
          |                                  EIA-930 demand/generation/carbon proxy
          +------------ UTC alignment and QC ---------------+
                                                               |
     pooled summer daily maxima -> weather-only P90 events     |
          |                     -> onset/peak/sustained/recovery|
          +-> matched controls + event-blind windows ----------+
                                                               |
NOAA history -> 72x5 causal features -> TinyLSTM -> 24h T -----+
                                                -> PUE forecast |
synthetic jobs -> 1x/2x/3x deterministic workloads             |
                                                               v
         static / capacity-aware / full-thermal / HeatGuard / oracle
                               |
                     rolling 24h plan, commit 1h
                               |
                 realized thermal and market scoring
                               |
            frozen 756-cell table -> P9/P10 event-level analysis
```

The actual implementation follows this flow: ingestion (`src/heattrace/ingest/noaa.py:21-435`, `caiso.py:24-433`, `eia.py:54-1151`), UTC alignment (`src/heattrace/process/alignment.py:52-704`), weather-only events (`events.py:111-365`), controls and triplets (`controls.py:40-180`, `p6_event_bundle.py:88-161,617-719`), forecasting (`forecast/dataset.py:92-159,239-279`; `tiny_lstm.py:115-165`), facility physics (`thermal/model.py:60-251`; `facility.py:268-370`), workloads (`workload/generator.py:33-111`; `scaling.py:12-170`), policies (`thermal/policies.py:245-672`; `heatguard.py:337-620`), runner (`experiments/p6_validity_runner.py:589-803,1931-2252`), and analysis (`evaluation/p6_validity.py:78-1102,1379-1690`).

## Chronological phase reconstruction

The P1–P5 labels are the original project phases. P6–P11 map to Days 8–14 of the later 14-day HeatGuard plan (`docs/heattrace-heatguard-14-day-plan.md:252-269`).

| Phase | Original objective | Implemented and validation | Principal artifacts | Status |
|---|---|---|---|---|
| P1 | Prove authentic NOAA/CAISO/EIA acquisition before bulk work. | Download/cache/parsers, retry and provenance, 2-day QC; NOAA `31.1°C` hot day and `21.7°C` ordinary day; 24/24 hourly coverage, while EIA issue flags are retained. | `README.md:16-108`, `src/heattrace/ingest/`, `tests/test_p1_ingest.py` | Implemented and historically verified. Raw sources are intentionally untracked. |
| P2 | Build a canonical aligned hourly table. | UTC interval-start contract; EIA hour-ending minus one hour; production-average carbon conversion; 48-row P1 table and manifests. | `README.md:112-145`, `docs/p2_alignment.md:15-34`, `src/heattrace/process/alignment.py` | Implemented and verified for the P1 windows. |
| P3 | Detect heatwaves, label phases, generate workloads, match a control. | Pooled 2022–2025 Jun–Sep P90 (`25.6°C`), strict exceedance, >=3 consecutive days; 4 events; synthetic relative-offset jobs; 2024 benchmark. | `README.md:148-179`, `data/events/heatwave_events_v0.parquet`, `docs/p3_heatwaves.md` | Implemented and verified. |
| P4 | Implement causal forecasting interfaces, schedulers, scoring, feasibility, and a bounded exact comparator. | Four greedy policies plus baseline; strict forecast/actual split; exact comparator only for <=6 jobs and <=24h. | `docs/p4_scheduling_metrics.md`, `src/heattrace/policy/`, `src/heattrace/evaluation/` | Implemented. The `dro_inspired` policy is a heuristic, not formal DRO (`src/heattrace/policy/robust.py:1-8`). |
| P5 | Run the first historical event/control scheduling study. | One 120h 2024 event/control pair, 30 jobs, four policies. All schedules tied because causal forecasts were flat. | `docs/p5_experiments.md`, `docs/p5_policy_diagnostic.md`, `data/results/p5_*` | Implemented; valid development evidence, not later confirmation. |
| P5.5 | Diagnose policy collapse and stress discriminability. | 270 controlled scenarios; flat, oracle, noisy-oracle forecasts; capacity/deadline stress; fair/equal-work views. | `docs/p5_5_findings_report.md`, `data/results/p5_5_*` | Implemented development experiment. Hindsight/noisy-oracle results are not deployable claims. |
| P6 / Day 8 | Add thermal model, causal TinyLSTM, HeatGuard, and run development-only pilot. | Earlier pilot invalidated for six causal/provenance defects; corrected rolling pilot executed 252/252 cells. Forecast gate GO on validation, but LSTM lost to day-lag on development heatwave and blind windows. | `docs/p6_thermal_method.md`, `docs/p6_pilot_review.md:12-34,56-103`, model/calibration artifacts | Corrected pilot complete; original attempt unsuccessful and archived. |
| P7 / Day 9 | Freeze protocol and exact confirmatory matrix. | Repaired the P6 phase-label collapse with a sidecar overlay; froze hashes and 756 stable IDs; confirmatory dry run only. | `docs/p7_freeze_readiness.md:15-24,61-98,121-171`, `data/manifests/p7_confirmatory_dry_run_manifest.json` | Complete. |
| P8 / Day 10 | Execute confirmation once. | 756/756 successful rows, explicit failure schema, immutable log/checkpoint, no development rows, oracle non-deployable. | Root P8 outputs and archived copies under `data/archive/.../canonical_p8/`; runner at `p6_validity_runner.py:2255-2272` | Complete. |
| P9 / Day 11 | Analyze at event level. | Seed aggregation, equal-service filters, H1–H5 tables, figures, leave-one-event reasoning; several corrections followed initial analysis. | `docs/p6_phase9_analysis_report.md`, `data/results/p6_t1_*` through `p6_t4_*` | Complete after corrections through commit `37bdffb`. |
| P10 / Day 12 | Adversarial claim audit and manuscript interpretation. | Limited-result verdict, prohibited claims, event-level H1–H5 evidence and publication framing. | `docs/p6_validity_report.md`, `docs/heattrace-14-day-review.html`, commit `d5b3c86` | Complete, but root validity report is currently untracked; canonical copy is archived. |
| P11 / Days 13–14 | Reproduce, compare, archive, and draft manuscript. | A fresh output directory contains another 756-row execution; 0 scientific-field differences; regenerated tables/figures match; 54-file portable archive and preliminary manuscript. | `docs/p11_v1_reproduction_report.md`, `data/results/p11_reproduction_comparison.json`, `data/archive/heattrace_v1_d5b3c86/` | Substantively complete, with documentation/environment portability qualifications below. |

Git history also includes P0 source audit (`1b78b26`), which preceded requested P1.

## Historical data and event construction

### What is observed

- Weather: NOAA GHCNh station `USW00023234`, San Francisco International Airport, hourly observations. Although `configs/sources.yaml` lists Sacramento and LAX as candidate stations, the event catalogue and forecast model use SFO only (`configs/sources.yaml:15-27`; `configs/study.yaml:22-31`).
- Prices: CAISO OASIS day-ahead hourly total LMP, node `TH_NP15_GEN-APND`, USD/MWh (`configs/sources.yaml:7-12`; `docs/contracts.md:19-27`).
- Grid: EIA-930 CISO demand/net generation plus generated-electricity CO2 intensity from the official workbook. The proxy is production-average, not marginal or avoided emissions; workbook/API hours are hour-ending and shifted back one hour (`docs/p2_alignment.md:21-27`; `docs/contracts.md:66-73`).
- Study scope is Jun–Sep 2022–2025. All canonical timestamps are aware UTC interval starts; local-day weather boundaries use `America/Los_Angeles` (`configs/study.yaml:1-25`; `events.py:223-225`).

### Event rule and exact catalogue

The threshold is the linearly interpolated 90th percentile of pooled warm-season daily maxima. A day qualifies only when `Tmax > threshold`; an event requires at least three consecutive qualifying days (`events.py:111-165,168-211`). The four detected events in `data/events/heatwave_events_v0.parquet` (4 rows, SHA-256 `22edce3a…`) are:

| Event | Raw UTC interval | Days/hours | Peak |
|---|---|---:|---:|
| `HW_20220620` | 2022-06-20 07:00 to 2022-06-23 07:00 | 3 / 72 | 36.7°C |
| `HW_20220904` | 2022-09-04 07:00 to 2022-09-09 07:00 | 5 / 120 | 35.6°C |
| `HW_20220922` | 2022-09-22 07:00 to 2022-09-25 07:00 | 3 / 72 | 28.3°C |
| `HW_20240702` | 2024-07-02 07:00 to 2024-07-05 07:00 | 3 / 72 | 31.1°C |

The P6 study normalizes each evaluation to 120h: 72h events receive 24h before and 24h after; a 120h event receives no padding (`p6_event_bundle.py:88-161`). Exact development, confirmation, control, and blind intervals are in `data/benchmarks/p6_event_control_index.csv`. The 1,440-row triplet table equals 4 triplets x 3 contexts x 120 hours; SHA-256 `60cea362…`. The overlay also has 1,440 rows; SHA-256 `7157a2e6…`.

Control selection is weather/calendar based and explicitly excludes price, demand, generation, carbon, and scheduler outcomes (`controls.py:52-63`). Event-blind candidates exclude event/buffer overlaps and are fixed before scheduling (`p6_event_bundle.py:617-652`). This supports outcome-independent selection, though the matched controls all come from June 2024 rather than the same year as the 2022 events, and their matching scores include large calendar-distance penalties (`data/events/control_catalogue_v0.parquet`).

### Observed versus modeled

Observed: ambient temperature, DAM LMP, demand/net generation, and production-average carbon intensity. Modeled: PUE, cooling energy, effective IT capacity, jobs, deadlines, facility cap, scheduler actions, and any facility violations. No real data-center outage, PUE telemetry, battery, renewable dispatch, or marginal emissions data are present (`docs/p6_thermal_method.md:193-198`; `configs/p6_thermal.yaml:1-27`).

## Forecasting

TinyTemperatureLSTM maps `[batch,72,5]` to 24 direct hourly temperatures using one unidirectional LSTM layer (5 inputs, 32 hidden units), final hidden state, dropout 0.1, and a linear 32→24 head (`tiny_lstm.py:115-165`). Features are standardized temperature plus sine/cosine hour-of-day and day-of-year; the scaler is fit only on training observations (`forecast/dataset.py:118-159,239-266`). Frozen ranges are training 2022-01-01–2022-05-01, validation May 2022, calibration 2022-06-01–16 (`configs/p6_validity.yaml:94-121`). Training uses CPU AdamW, SmoothL1, seed 20261016, max 50 epochs and early stopping (`configs/p6_validity.yaml:122-144`).

Validation: LSTM RMSE 2.0739°C versus best baseline same-hour-previous-day 2.3297°C, a 10.98% improvement; the extreme-underprediction condition failed (3.4291 vs 3.2155°C), so the gate passed only Condition 1 (`docs/p6_pilot_review.md:83-95`; `data/results/p6_forecast_metrics.csv`). Development exposed poor transfer: heatwave RMSE 5.8075 versus 3.6948°C, control 1.8744 versus 2.5746°C, blind 3.0177 versus 1.8762°C (`docs/p6_pilot_review.md:97-103`). Confirmatory runs did not retain alternative forecast arms or allocation vectors: only scalar `allocation_count` exists. Forecast-caused regret is therefore unproven (`docs/p6_validity_report.md:147-154`; `data/results/p6_t4_forecast_evidence.csv`).

## Thermal facility and workload model

For ambient temperature `T`:

`PUE(T) = min(base_pue + slope * max(T - 22, 0), max_pue)`.

Facility power is `IT_power * PUE`. The nominal IT limit is 500 kW and fixed facility cap is `500 * 1.20 = 600 kW`. Energy-only capacity stays at 500 kW; power-capped effective IT capacity is `min(500, 600/PUE)` (`docs/p6_thermal_method.md:29-75`; `thermal/model.py:60-203`). Low/medium slopes are 0.010/0.020 per °C with max PUE 1.45/1.70; high exists for Day-1 sensitivity but was excluded from confirmation (`configs/p6_thermal.yaml:8-25`; `p6_validity.yaml:36-50`).

Worked example: at 32°C under the medium curve, PUE = `1.20 + .02*(32-22) = 1.40`; effective IT capacity is `600/1.40 = 428.57 kW`. A 450 kW IT schedule would draw `630 kW`, exceeding the facility cap by 30 kW for that hour. This is a model implication, not observed telemetry.

The generator creates relative arrivals, 1–6 processing slots, deadlines after processing plus 1–24h sampled slack (clipped at horizon), 15–75 kW per slot, priority 1–5 and preemption flag (`workload/generator.py:33-107`). Confirmation uses two frozen seeds and deterministic 1x/2x/3x replication without changing per-job attributes (`workload/scaling.py:12-38,114-170`). A completed slot is one required discrete processing allocation. Unfinished slots are demanded minus completed; deadline misses and invalid/out-of-window allocations make the schedule infeasible; realized facility power above the cap makes it thermally infeasible (`thermal/metrics.py:18-277`; `p6_validity_runner.py:2164-2240`). There is no intentional job dropping credit: equal-service analysis rejects incomplete/unequal work.

## Policies actually evaluated

| Policy | Rule and information | Rolling/deployable |
|---|---|---|
| `static_unaware` | Greedy carbon-first in confirmation using nominal capacity; no temperature/PUE/capacity input. | 24h/1h causal harness; deployable (`thermal/policies.py:245-302`). |
| `capacity_aware` | Same market objective, but repairs placements against forecast-derived effective capacity. | Rolling; deployable (`thermal/policies.py:305-386`). |
| `full_thermal_aware` | Multiplies forecast price/carbon by forecast PUE and enforces forecast capacity. | Rolling; deployable (`thermal/policies.py:389-496`). |
| `heatguard_calibrated` | Full thermal planning with safe PUE = forecast PUE + calibrated global margin 0.01599998, capped at max PUE. | Rolling; deployable (`heatguard.py:337-460,462-620`). |
| `heatguard_fixed` | Same mechanism with frozen PUE margin 0.10. | Rolling; deployable (`heatguard.py:434-445`). |
| `oracle_full_thermal_aware` | Uses realized PUE, capacity, prices and carbon in hindsight. | Non-deployable (`thermal/policies.py:499-620`). |

Earlier P4/P5 also evaluated `cost_first`, `carbon_first`, `balanced`, `dro_inspired`, and `baseline_reference`; P8 froze only carbon-first objective. Static and capacity-aware were frequently identical because the adapter had no need or ability to move allocations; full-thermal and calibrated HeatGuard were mathematically identical in the development primary setting, and in confirmation their reported metrics remain identical (`docs/p6_pilot_review.md:118-145`; `data/results/p6_t2_event_feasibility.csv`).

HeatGuard's margin is the 0.90 "higher" quantile of `(realized PUE - forecast PUE)` on a past-only calibration reservation, clipped below at zero. It is a heuristic buffer, not a coverage guarantee (`docs/p6_frozen_protocol.md:151-192`).

## Frozen experiment design

The matrix is enumerated from the validated config, rejects development identities, uses stable SHA-derived run IDs, and hard-requires carbon-first (`p6_validity_runner.py:589-655,780-803`). Arithmetic:

- Core heatwave/control: `3*2*2 facilities*2 curves*3 workloads*2 seeds*3 policies = 432`.
- Event blind: `3*2*2*3*2*3 = 216`.
- HeatGuard comparators: `3*2*3*2*2 = 72` (power-capped/medium only).
- Oracle: `3*2*3*2 = 36`.
- Total `432+216+72+36 = 756` (`p6_validity_runner.py:677-778`; `data/results/p6_t1_cohort_provenance.csv`).

All 756 succeeded. The independent unit is the historical triplet/event, N=3; seeds and grid cells are aggregated within event and are not independent (`docs/p6_frozen_protocol.md:33-87`; `docs/heattrace-heatguard-14-day-plan.md:305-307`). Deployable rolling forecasts use 72 hours ending at origin-1; only released jobs enter the planner; only the next hour is committed (`p6_validity_runner.py:1960-2003`; `heatguard.py:521-620`).

## Results and negative results

### Historical conditions

Across the medium-curve 120h confirmatory windows, heatwave means were warmer than controls in all three cases: 19.63 vs 15.37°C (CONF1), 23.38 vs 14.94°C (CONF2), and 18.52 vs 14.34°C (CONF3). Corresponding mean LMPs were 74.64 vs 24.56, 238.98 vs 16.81, and 72.57 vs 31.58 USD/MWh; mean production-carbon proxies were 188.50 vs 137.05, 275.84 vs 127.17, and 234.05 vs 177.07 g/kWh. Mean modeled PUE/capacity were 1.2266/490.22, 1.2549/479.83, 1.2084/496.72 for heatwaves versus 1.2027/498.95, 1.2004/499.84, 1.2000/499.99 for controls. These are direct group summaries of `data/benchmarks/p6_event_control_pairs.parquet` plus the frozen medium PUE equation; do not treat them as population estimates.

P5's development event showed +4.05°C hourly mean temperature and +$26.71/MWh price relative to its matched control; all policies nevertheless tied because forecasts were flat (`docs/p5_experiments.md:14-43`; `docs/p5_policy_diagnostic.md:1-35`). P5.5 showed that non-flat information creates differentiation, but oracle/noisy-oracle cost reductions are controlled hindsight results, not v1 HeatGuard benefits (`docs/p5_5_findings_report.md:23-58`).

### Confirmation

| Finding | Evidence | Interpretation and limit |
|---|---|---|
| Static tested feasibility fell 0.5x in CONF1 and CONF2; CONF3 was 0.0x. | `data/results/p6_h1_h5_assessment.csv`; `docs/p6_validity_report.md:98-113` | H1 supported under frozen rule; coarse grid and medium-curve case series only. Low-curve sensitivity was only 1/3 negative. |
| Exact capacity awareness recovered 0.0x and reduced violations by 0.0h. Full thermal awareness reduced mean violation hours at 3x by 1.0h (1.5→0.5) and 0.5h (1.0→0.5), but recovered no boundary and worsened CONF1 boundary by 0.5x. | `docs/p6_validity_report.md:115-128`; `data/results/p6_t2_event_feasibility.csv` | H2 only partially supported through the disjunctive violation branch. |
| Heatwave policy gaps were non-zero in 24/36 comparisons for CONF1 and CONF2, versus 0/36 blind; CONF3 0/36. Strict reversals: 0/108. CONF1 control also had 24/36. | `docs/p6_validity_report.md:130-145`; `data/results/p6_t3_equal_service_gaps.csv` | H3 partially supported as discriminability, not wrong-scheduler/ranking-reversal evidence and not uniquely heatwave-specific in CONF1. |
| At 3x, all deployable heatwave policies completed equal service with zero deadline misses; violations, not dropped work, separate feasibility. | Archived P8 table; `docs/p6_validity_report.md:187-205` | Cost/carbon gaps are valid only within equal-service comparisons. |
| Calibrated HeatGuard never beat both fixed and deterministic comparators: CONF1 violation hours 1.0 vs fixed 0.0; CONF2 0.5 vs 0.5; CONF3 0 vs 0. | `docs/p6_validity_report.md:156-166` | H5 not supported; no HeatGuard superiority. |
| Forecast-caused scheduling regret cannot be estimated. | `data/results/p6_t4_forecast_evidence.csv`; `docs/p6_validity_report.md:147-154` | H4 exploratory and not estimable: no controlled forecast substitution or allocation vectors. |

At 3x/medium/power-capped, seed-mean heatwave costs for static vs full-thermal were $1,295.13 vs $1,352.05 (CONF1), $4,193.29 vs $4,564.42 (CONF2), and identical $1,154.16 (CONF3); production-carbon proxies were 3,100.56 vs 3,337.35 kg, 4,551.84 vs 4,618.52 kg, and identical 3,680.92 kg. These are performance differences, not "savings delivered by HeatTrace," and the higher-cost/lower-violation tradeoff does not establish superiority (archived `canonical_p8/p6_validity_runs.parquet`).

## Phase-aware analysis status

P3 correctly generated onset, peak, sustained and recovery (`events.py:282-365`). P6 then collapsed every heatwave row to the generic `heatwave` label. P7 repaired storage by building the 1,440-row sidecar and authoritative relational join (`docs/p7_freeze_readiness.md:61-98`; `p6_event_bundle.py:1632-1729,1761-1815`). The runner loads that overlay (`p6_validity_runner.py:949-1027`), but P8 output records only triplet/context/window scalar outcomes, not phase-level allocations/backlogs/metrics (`p6_validity_runner.py:2205-2251`). Thus labels exist and reach the loaded benchmark, but phase-specific scheduling outcomes were not evaluated. Onset/peak/recovery scheduler claims are not defensible. A proper analysis must retain hourly committed allocations, forecast PUE/capacity, backlog and realized metrics keyed to phase, treat phases as repeated segments within events, and preserve cross-phase job state.

## Ruparel paper versus HeatTrace

The repository cites Hardik Ruparel, *Carbon-aware scheduling and distributionally robust optimization for cloud systems: forecasting, battery storage, and adaptive ambiguity refinement*, Journal of Cloud Computing 15, article 84 (2026), DOI `10.1186/s13677-026-00904-7`, and `Hardik27/Carbon-Aware-Scheduler` (`docs/heattrace-heatguard-14-day-plan.md:55-67`). The publisher confirms a geo-distributed multi-objective DRO over cost, carbon, latency and tail risk; region-specific forecasts for price/carbon/renewables; moment/Wasserstein ambiguity sets; Benders decomposition; adaptive radius refinement; battery constraints; and a six-policy synthetic benchmark. The local repository itself verifies only the TinyLSTM summary and non-reproduction boundary, so details beyond those are external reference context, not HeatTrace evidence.

| Aspect | Ruparel | HeatTrace | Relationship |
|---|---|---|---|
| Problem | Geo-distributed carbon/cost/latency scheduling under uncertain grid and renewable signals. | Single CAISO historical-event benchmark for deferred synthetic workloads under modeled thermal capacity. | Inspired problem area; different research question. |
| Forecast | Per-region one-step TinyLSTM for price/carbon/renewable, autoregressive rollout; EWMA fallback (as summarized locally). | Direct 72x5 temperature-only LSTM to 24 temperatures; market forecasts are causal persistence. | TinyLSTM-inspired only (`plan.md:55-62`; `tiny_lstm.py:115-165`). |
| Optimizer | Formal moment/Wasserstein DRO, DRCC/CVaR, two-stage Benders. | Greedy policies, deterministic capacity repair, and a transparent `dro_inspired` score penalty. | Not reproduced (`policy/robust.py:1-8`; `p6_thermal_method.md:193-198`). |
| Uncertainty | Distributional ambiguity and adaptive Wasserstein radius. | Past-only global 90th-percentile PUE residual margin; fixed 0.10 comparator. | Heuristic analogue, no formal guarantee (`p6_frozen_protocol.md:151-192`). |
| Energy system | Renewables and battery charge/discharge. | Neither battery nor renewable model. | Not implemented. |
| Geography | Multiple regions/data centers. | One CAISO region and one modeled facility. | Simplified/replaced. |
| Evidence | Synthetic OOD scenarios in the cited study. | Real historical grid/weather inputs plus synthetic facility/workload. | HeatTrace's main engineering/scientific distinction. |

HeatTrace does **not** implement the actual Wasserstein program, Benders decomposition, adaptive ambiguity refinement, battery dispatch, renewable-first policy, or geo-distributed placement.

## Novelty and publication readiness

Defensible novelty is the leakage-controlled, outcome-independent complete-heatwave benchmark with matched-control and event-blind contexts, provenance-locked event-level case evidence, and unusually candid null/negative results (`docs/heattrace-heatguard-14-day-plan.md:99-101`; `docs/p6_validity_report.md:315-327`). Thermal-aware scheduling, LSTMs, forecast margins and greedy carbon scheduling are prior-art components. The archive/provenance system is a strong engineering contribution, not itself a scientific discovery.

Strong claims: (1) modeled static feasibility was 0.5x lower in two of three medium-curve cases; (2) complete heatwave windows exposed equal-service gaps missed by the chosen blind windows in two cases; (3) fixed margins were at least as good as calibrated HeatGuard on violations. Reviewer rejection risks: N=3 dependent case series, one null event, 2024 controls for 2022 events, synthetic jobs/facility physics, weak thermal-curve sensitivity, production-average carbon proxy, no strict ranking reversals, no phase outcomes, no forecast intervention, and incomplete clean-checkout instructions (`docs/p6_validity_report.md:294-311`).

Suitable title/abstract framing: reproducible historical extreme-event benchmark and mixed case-series evidence. Prohibited framing: HeatGuard superiority, general heatwave causality, faithful Ruparel reproduction, forecast-sensitive regret, restored feasibility, avoided emissions, or production deployment.

## P11 reproducibility conclusion

P11 did more than metadata validation: the reproduction output contains 756 unique cells, a different parquet hash, and only operational differences from canonical results; regenerated scientific CSVs and deterministic figures match byte-for-byte (`docs/p11_v1_reproduction_report.md:47-116`; `data/results/p11_reproduction_comparison.json`). The line "756 cells were not rerun" at `docs/p11_v1_reproduction_report.md:161` contradicts lines 49-66 and the archived reproduction artifacts; the evidence supports that they **were rerun**. In contrast, `docs/p6_validity_report.md:329-334` had originally prescribed analysis-only reproduction without simulations. This likely explains the stale sentence.

P11 did not pin an exact environment, publish a tag/release, bundle raw NOAA files, or provide a start-to-finish clean-checkout command. `pyproject.toml` specifies ranges (`pandas>=2.0`, `pyarrow>=14.0`, `torch>=2.0`) and the runner hardcodes untracked `data/raw/noaa` and `data/models/...` paths (`p6_validity_runner.py:1936-1938`). The archive contains model copies and external NOAA hashes, but not raw NOAA bytes (`archive_manifest.json`, `external_source_inputs`). Archive verification and result inspection are clean-checkout capable; full simulation reproduction needs documented restoration/download steps.

## Bottom line for a professor

HeatTrace successfully built and reproduced a rigorous research prototype and historical-event benchmark. It found bounded evidence that the selected complete heatwaves can reveal modeled feasibility and policy-separation effects that chosen blind windows miss. It did **not** prove a better scheduler: HeatGuard was negative, capacity awareness did not restore the tested boundary, strict ranking reversals were absent, and forecast causality is untested. That honest boundary is the project's most important scientific property.
