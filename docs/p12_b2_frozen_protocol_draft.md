# P12 Track B2 frozen protocol draft

**State:** DRAFT — must be signed and hashed before data-dependent event selection or scheduler execution.  
**Results status:** no Track B2 results exist.

## 1. Immutable historical boundary

- HeatTrace v1/P11 remains the study identified by archive `heattrace_v1_d5b3c86`.
- Its three confirmatory triplets, 756 cells, H1-H5 rules and results are not reclassified or pooled into B2.
- B2 uses a separate config, namespace, run-ID prefix, output directory and archive.
- Any shared implementation is referenced by commit and hash. B2 changes do not alter the v1 code path.

## 2. Evaluation population

### Station candidates

| Station key | NOAA GHCNh ID | Climate class | Price hub | Status before Day 2 |
|---|---|---|---|---|
| SFO | `USW00023234` | northern coastal | `TH_NP15_GEN-APND` | candidate; v1 weather source |
| SAC | `USW00023232` | northern inland | `TH_NP15_GEN-APND` | candidate |
| FAT | `USW00093193` | central inland | `TH_ZP26_GEN-APND` | candidate |
| RDD | `USW00024257` | far-northern inland | `TH_NP15_GEN-APND` | candidate |
| LAX | `USW00023174` | southern coastal | `TH_SP15_GEN-APND` | candidate |

Primary Sacramento replacement, only after a failed documented gate: `USW00093225` (Sacramento Metropolitan Airport). No other replacement is allowed after scheduler outcomes are visible.

### Time scope

- Evaluation seasons: local June 1 through September 30 in 2022, 2023, 2024, 2025 and 2026.
- Local timezone: `America/Los_Angeles`; all stored canonical keys are timezone-aware UTC interval starts.
- March 2026 is excluded from the primary protocol. An expanded-season sensitivity requires a separately frozen amendment.
- 2026 is labeled provisional until NOAA, CAISO and EIA inputs cover every selected window and the source manifests pass.
- Pre-2022 weather may be acquired only for leakage-safe forecast training/calibration; it is not part of the B2 event population.

## 3. Source eligibility gates

A station-year is event-screen eligible only when:

1. every local warm-season day can be constructed with valid, quality-filtered hourly observations or an explicit missing-day flag;
2. at least 95% of expected hourly temperature bins and 98% of local daily maxima are available;
3. no selected event/control window contains a missing daily maximum or unresolved timestamp conflict;
4. the mapped CAISO hub has complete DAM total-LMP bins for the full scheduler window;
5. EIA CISO demand/generation and production-average carbon proxy are complete for the window, with issue flags retained;
6. all input files have retrieval metadata, source URL/parameters, byte size and SHA-256.

The CAISO hub is a regional market signal, not a facility tariff. The single CISO carbon proxy is shared across all stations, so geographic carbon heterogeneity is not identifiable in B2.

## 4. Weather-only event definition

For each eligible station independently:

1. Compute local daily maximum temperature after existing NOAA quality filtering and duplicate resolution.
2. Compute a station-specific empirical P90 using June-September daily maxima from the fixed 2022-2025 baseline, linear interpolation.
3. A qualifying day has `Tmax > station P90` (strict inequality).
4. A station-level heatwave is at least three consecutive qualifying local days.
5. Missing days break a run; they are never imputed into an event.
6. Adjacent qualifying days form one event. No manual split/merge is allowed.
7. Record start/end, peak (earliest maximum on ties), duration, cumulative exceedance, missingness and source provenance.
8. Label onset as the preceding local day, recovery as the following local day, peak as the hottest event day, and remaining event days as sustained.

The threshold is local-relative; cross-station comparisons use standardized exceedance and event effects rather than interpreting equal absolute temperatures as equal severity. Sensitivities: P85 and P95, plus a minimum four-day event rule. These variants do not replace the primary catalogue.

## 5. Regional episode independence

- Each station event remains an observation with its own weather, price hub and scheduler results.
- Construct an overlap graph whose nodes are station events. Connect two nodes when their event intervals, each expanded by 24 hours on both sides, overlap in UTC.
- A connected component is one `regional_episode_id` and is the primary independent analysis unit.
- Events at different stations within one component are repeated measurements, not independent heatwaves.
- Workload seeds, policies and ordinary windows are repeated experimental cells, never independent historical samples.
- Primary uncertainty and sign counts use regional episodes. Station-event results are reported nested within episode and year.
- Sensitivity: recompute components using strict unbuffered overlap and a 48-hour buffer. If conclusions depend on the grouping rule, classify them as fragile.

## 6. Event windows and workloads

### Primary full-event window

- Start: local midnight one day before the first qualifying day.
- End: local midnight after the recovery day.
- Preserve the complete event; do not truncate long events.
- DST-derived 23/25-hour days retain their actual UTC duration.

### Variable-duration workload rule

- Preserve the v1 job schema and seed identities `20261016` and `20261017`.
- Generate jobs deterministically for the exact window duration using the frozen v1 arrival/energy/priority distributions and a constant expected arrival intensity per hour.
- Hash the duration-specific trace. Reuse that exact trace for the event, its matched control and all ordinary windows of equal duration.
- Compare cost/carbon only under equal demanded and completed service. Report service-normalized and per-hour values for differing durations.

### Fixed-duration secondary analysis

A 120-hour peak-centered window may be used as a secondary duration-standardized analysis. It must be labeled an ablation, may not replace the full-event primary window, and must retain causal 72-hour forecast history.

## 7. Controls and representative ordinary windows

For each station event:

1. Select one matched ordinary control at the same station and same year where possible.
2. Require equal UTC duration, identical source coverage, no overlap with any station heatwave/onset/recovery buffer, and no embedded three-day P90 exceedance run.
3. Match on season/calendar position, day-of-week composition and temperature characteristics only. Do not read price, carbon or scheduler outcomes during selection.
4. If no same-year control is valid, use the nearest eligible year and mark the comparison LIMITED; no silent cross-year fallback.
5. Deterministically sample 20 representative ordinary windows per event, stratified across the eligible warm season; increase to 30 only after the primary 20 are frozen.
6. Minimum valid ordinary sample: 10. Fewer than 10 makes G3 non-estimable for that event.
7. Exclude overlaps among sampled windows when possible; if availability requires overlap, record the overlap graph and do not treat windows as independent.

## 8. Forecast, policies and scoring

- Reuse the TinyLSTM architecture, rolling 24-hour forecast, one-hour commitment, scheduling policies, constraints and realized scoring semantics.
- Do not apply the SFO scaler/checkpoint/calibration to other stations.
- Preferred rule: station-specific v2 artifacts with identical architecture/hyperparameters trained/calibrated exclusively before the first B2 event.
- If leakage-safe station artifacts cannot be produced, freeze causal previous-day forecasting as B2 primary and keep TinyLSTM/HeatGuard secondary.
- Policies: `static_unaware`, `capacity_aware`, `full_thermal_aware`, `heatguard_fixed`, `heatguard_calibrated`, and non-deployable `oracle_full_thermal_aware`.
- Primary objective: `carbon_first`; cost is co-reported. Carbon is a production-average proxy, not avoided or marginal emissions.
- Facilities: power-capped/medium curve primary; energy-only and low curve as v1 comparators; high curve and cap variants are G5 sensitivities.
- Loads: `1.0x`, `2.0x`, `3.0x`; seeds: `20261016`, `20261017`.
- Metrics: demanded/completed/unfinished slots, deadlines, facility violation hours/excess, cooling-adjusted cost, production-carbon proxy, tested feasible boundary and equal-service policy gaps.

## 9. Hypotheses and predeclared criteria

### G1 — Temporal replication

For each regional episode/year, compute heatwave-minus-matched-control effects for static feasibility and equal-service policy gaps. Evidence of recurrence requires the preregistered direction in at least two independent years and a same-direction episode-level median. Otherwise classify as mixed/not replicated. This is bounded evidence, not a population guarantee.

### G2 — Geographic heterogeneity

Compare effect sizes by coastal/inland and north/central/south classes using station observations nested in episode. A confirmatory heterogeneity claim requires at least two independent regional episodes per compared class and an uncertainty interval excluding zero for the between-class contrast. Otherwise report descriptive heterogeneity only.

### G3 — Benchmark discriminability

For each station event, compare complete-event policy separation with its frozen ordinary-window distribution. The event is more discriminating only if its separation count or magnitude exceeds the 95th percentile of the ordinary distribution while equal service holds. Summarize at regional-episode level. No claim of a ranking reversal unless the preferred policy actually changes sign.

### G4 — Full-event continuity

Compare the full-event primary window with the preregistered isolated-peak-day/fixed-duration ablation using normalized outcomes and retained cross-boundary state. G4 is non-estimable if equivalent histories, arrivals, deadlines, service and allocation traces cannot be preserved. It is conditional within the seven-day schedule.

### G5 — Robustness

Repeat primary effect calculations under P85/P95 thresholds, four-day minimum duration, low/high thermal curves, at least one lower/higher facility cap, strict/48-hour episode grouping and alternative ordinary-window seeds. Do not tune variants after viewing scheduler outcomes. Classify conclusions as robust only if direction and substantive interpretation persist across all preregistered valid variants.

## 10. Validity gates and decisions

| Gate | Requirement |
|---|---|
| B2-G0 | Protocol/config signed and hashed before event catalogue or scheduler outcomes are inspected |
| B2-G1 | Station/year/hub/EIA coverage matrix passes; 2026 status explicit |
| B2-G2 | Station events and regional episodes validate; no phase collisions or missing selected-window weather |
| B2-G3 | Controls/ordinary windows are equal-duration, outcome-blind, coverage-complete and frozen |
| B2-G4 | Run matrix unique and complete; causal history and equal-service contracts pass |
| B2-G5 | G1-G5 tables preserve nesting, nulls/failures and sensitivity provenance |
| B2-G6 | Zero-checkpoint reproduction matches scientific fields and archive verification passes |

- **GO:** B2-G0 through G6 pass with at least three stations, two hubs, two climate classes and multiple regional episodes in multiple years.
- **LIMITED:** valid but smaller station/episode coverage or non-estimable G2/G4.
- **NEGATIVE:** valid design and adequate coverage, but no replication/discriminability advantage.
- **INVALID:** leakage, pseudo-replication, mapping error, unequal service, broken hashes or irreproducibility.

## 11. Protocol freeze record (to complete on Day 1)

Record commit, config hashes, station metadata snapshots, station eligibility policy, event/episode rules, control seed, ordinary-window count, forecast decision, matrix formula, analysis code hash and signed timestamp. Until completed, this document remains a draft and no result may be called confirmatory.

**Track B2 implementation plan prepared. No new scientific experiments have been executed.**
