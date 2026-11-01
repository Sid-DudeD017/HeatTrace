# P12 Track B2 experiment matrix

**Status:** parametric planning estimate; final count depends on the frozen station-event catalogue.  
**No B2 cells have been enumerated or executed.**

## 1. Analysis units

- `E`: number of eligible station-level heatwave events.
- `R`: number of independent regional episodes after overlap grouping; scientific independence is based on `R`, not `E`.
- `K`: representative ordinary windows per station event; primary target `K=20`, extended target `K=30`, minimum `K=10`.
- Each event has one complete heatwave window and one matched ordinary control.

## 2. Primary matrix

The broad ordinary-window distribution uses the primary v1 condition only:

| Dimension | Levels |
|---|---|
| Context/window | 1 heatwave + 1 matched control + `K` ordinary windows |
| Facility | power-capped |
| Thermal curve | medium |
| Workload | 1x, 2x, 3x |
| Seeds | 20261016, 20261017 |
| Objective | carbon-first primary; cost co-reported |
| Policies | static unaware, capacity-aware, full thermal-aware |

This is `3 policies × 3 loads × 2 seeds = 18` cells per window, or:

```text
primary cells per station event = 18 × (K + 2)
```

## 3. Event/control sensitivity and comparator matrix

Run these only on the heatwave and matched-control windows, not automatically on all 20-30 ordinary windows:

1. Add energy-only and low-curve combinations to reproduce the v1 core grid: 108 cells beyond the primary event/control subset.
2. HeatGuard fixed and calibrated, power-capped medium: 24 cells per event/control pair.
3. Hindsight oracle, power-capped medium: 12 cells per event/control pair.

Therefore:

```text
base total per station event = 18 × (K + 2) + 144
                             = 18K + 180
```

| Ordinary windows K | Cells per station event |
|---:|---:|
| 10 minimum | 360 |
| 20 primary target | 540 |
| 30 extended target | 720 |

G4 adds 18 cells per valid station-event ablation. Each additional G5 power-cap/thermal scenario on heatwave+control adds 36 cells. These additions must be enumerated separately in the final dry-run manifest.

## 4. Scenario counts

The catalogue is unknown, so an exact total would be fabricated. Planning ranges are:

| Eligible station events E | K=20 base | K=30 base | With G4 + three G5 scenarios per event |
|---:|---:|---:|---:|
| 5 | 2,700 | 3,600 | 3,330 / 4,230 |
| 10 | 5,400 | 7,200 | 6,660 / 8,460 |
| 15 | 8,100 | 10,800 | 9,990 / 12,690 |

These are execution cells, not independent samples. The paper must report both `E` station events and `R` regional episodes.

## 5. Full-grid alternative

Running the complete v1 core grid on every ordinary window would cost:

```text
full-grid cells per station event = 72K + 180
K=20: 1,620
K=30: 2,340
```

This is optional second-week work. It adds limited scientific value relative to the primary power-capped/medium ordinary distribution and should not displace coverage, episode grouping or reproduction.

## 6. Runtime and storage estimate

The v1 manifest records 268.32 seconds for 756 120-hour cells on the original environment, approximately 0.355 seconds/cell. Use only as a planning baseline:

```text
estimated seconds ≈ cells × 0.355 × (mean window hours / 120)
```

Budget 3x this estimate for variable-duration windows, model loading, checkpointing, validation and contention. For 10 station events at K=20, the 5,400-cell base is about 32 minutes at the v1 rate and roughly 1.5-2 hours with the planning safety factor, before acquisition/model preparation and reproduction. A zero-checkpoint reproduction approximately doubles execution time.

Storage planning:

- Existing SFO GHCNh files are roughly 10-12 MB per station-year; five stations × five evaluation years is approximately 250-350 MB before pre-2022 training data.
- Station forecast-training files may add another 200-300 MB.
- EIA workbook is about 98 MB locally.
- CAISO archives, processed parquets, logs, models and duplicate reproduction artifacts justify a 1.5 GB working budget and a smaller content-addressed release bundle.

All estimates must be replaced with observed sizes/runtime in the Day-2 and Day-5 manifests.

## 7. Required dry-run checks before execution

1. Exact matrix count matches the formula and frozen catalogue.
2. Every canonical key and run ID is unique.
3. No v1 result path is a B2 output target.
4. Every station event maps to one regional episode.
5. Every event/control/ordinary group shares duration and workload hash.
6. Forecast history ends at `t-1`; no future weather or outcomes enter deployable policies.
7. Oracle rows are non-deployable.
8. Ordinary/control selection files contain no scheduler metrics.
9. All expected source, model, config and protocol hashes are present.
10. Failed cells remain in the execution log and analysis denominator where preregistered.

## 8. Planned outputs

```text
data/v2/manifests/p12_b2_matrix_dry_run.json
data/v2/results/p12_b2_runs.parquet
data/v2/results/p12_b2_execution.jsonl
data/v2/results/p12_b2_event_metrics.csv
data/v2/results/p12_b2_episode_metrics.csv
data/v2/results/p12_b2_ordinary_distributions.csv
data/v2/results/p12_b2_g1_g5_assessment.csv
```

**Track B2 implementation plan prepared. No new scientific experiments have been executed.**
