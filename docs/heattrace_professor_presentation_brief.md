# HeatTrace professor presentation brief

## Two-minute explanation

HeatTrace asks whether cloud schedulers look different when evaluated on complete historical heatwaves instead of ordinary or arbitrary short windows. It combines real NOAA temperature, CAISO day-ahead prices, and EIA-930 grid observations with a simulated data-center model and synthetic deferrable jobs. Temperature raises modeled PUE; under a fixed 600 kW facility cap, that reduces the IT capacity available from a nominal 500 kW cluster (`docs/p6_thermal_method.md:29-75`).

The project built weather-only heatwave detection, matched controls, event-blind windows, a direct 24-hour TinyLSTM temperature forecast, rolling greedy policies, and HeatGuard forecast margins. The final frozen study has three confirmatory heatwaves and 756 scheduler cells (`src/heattrace/experiments/p6_validity_runner.py:677-782`). Static scheduling had a 0.5x lower tested feasibility boundary in two events and no change in the third. Complete heatwave windows exposed policy cost/carbon-proxy separations that blind windows missed in two events, but there were no strict ranking reversals. Full thermal awareness reduced violation hours slightly but did not restore the tested boundary. HeatGuard did not beat a fixed margin, and forecast-caused regret cannot be tested because alternative forecast arms and hourly allocation vectors were not recorded (`docs/p6_validity_report.md:98-166`).

The contribution is therefore the reproducible historical-event benchmark and honest mixed evidence, not a superior scheduling algorithm. P11 reran all 756 cells with identical scientific values and archived the evidence, although clean-checkout packaging still needs dependency and input restoration documentation (`docs/p11_v1_reproduction_report.md:47-151`).

## Five-to-seven-minute walkthrough

1. **Question (30 seconds).** Explain that ordinary-window evaluation can miss extreme-event constraints; HeatTrace tests this in a bounded CAISO case series.
2. **Pipeline (60 seconds).** Show the diagram in `docs/heattrace_complete_project_handoff.md`: real historical signals -> weather-only event selection -> causal forecast -> simulated facility/workload -> rolling scheduler -> realized scoring.
3. **Physical mechanism (45 seconds).** Show `data/figures/p6_f4_h1_sensitivity.png` and explain `PUE(T)` and `Ceff=min(500,600/PUE)`. State explicitly that this is controlled sensitivity, not facility telemetry.
4. **Experimental design (60 seconds).** Show `data/benchmarks/p6_event_control_index.csv` and `data/results/p6_t1_cohort_provenance.csv`: N=3 independent event triplets, 756 cells, two seeds aggregated within event.
5. **Main results (90 seconds).** Use `data/figures/p6_f1_event_policy_contrasts.png` and `data/results/p6_t2_event_feasibility.csv`: H1 supported in two cases; H2 mixed; H3 two positive/one null; H5 negative.
6. **Forecast story (45 seconds).** Validation LSTM beat day-lag (2.0739 vs 2.3297°C RMSE), but lost badly on the development heatwave (5.8075 vs 3.6948). Do not imply causation (`data/results/p6_forecast_metrics.csv`).
7. **Reproducibility and close (45 seconds).** P11 produced an independent 756-row reproduction with zero scientific differences and a 54-file verified archive. Close with the limited claim and remaining v2 questions.

## Worked job example

Suppose a released job needs one 50 kW processing slot before its deadline.

1. At rolling origin `t`, the model consumes the previous 72 hours and predicts 24 temperatures. Only history through `t-1` is used (`src/heattrace/experiments/p6_validity_runner.py:1960-1987`).
2. If the predicted next-hour temperature is 32°C, medium-curve forecast PUE is 1.40. Power-capped safe IT capacity without margin is `600/1.40=428.57 kW`; calibrated HeatGuard adds about 0.016 PUE, giving `600/1.416=423.73 kW`; fixed margin gives `600/1.50=400 kW` (`docs/p6_frozen_protocol.md:151-192`).
3. The scheduler considers only jobs already arrived, chooses hours using carbon forecast multiplied by PUE for full thermal awareness, verifies capacity, and commits only hour `t` (`src/heattrace/thermal/policies.py:389-496`; `thermal/heatguard.py:521-620`).
4. After execution, realized temperature determines realized PUE and facility power. If total IT load was 450 kW at realized PUE 1.40, facility power is 630 kW, a 30 kW violation for one hour.
5. Metrics record completed slots, deadline misses, facility violation hours/excess, cooling-adjusted cost, and production-carbon proxy (`src/heattrace/experiments/p6_validity_runner.py:2164-2240`).

## Ten likely questions

1. **Is the heatwave selection biased by scheduler results?** No. Events use only NOAA daily maxima; controls/blinds are selected before outcomes and exclude price/carbon/scheduler information (`events.py:111-211`; `controls.py:52-63`).
2. **Why only three confirmatory events?** The authentic catalogue has four events; one 2024 event was reserved for development, leaving three sealed 2022 events (`docs/p6_frozen_protocol.md:88-103`).
3. **Why are controls in 2024?** Available aligned CAISO data and the fallback control catalogue led to June 2024 controls. This is a limitation because year/regime differences may confound event-control contrasts (`data/benchmarks/p6_event_control_index.csv`).
4. **Is PUE measured?** No. It is a frozen piecewise-linear controlled sensitivity model (`configs/p6_thermal.yaml:1-25`).
5. **What does 0.5x feasibility loss mean?** The tested boundary fell from 3.0x to 2.5x; it is grid-bounded, not a precise continuous capacity threshold (`docs/p6_validity_report.md:98-113`).
6. **Did thermal awareness solve the problem?** No. It reduced violation hours by 0.5–1.0h in two applicable cases but did not recover the tested boundary (`docs/p6_validity_report.md:115-128`).
7. **Did HeatGuard work?** Not better than fixed margin: 0/3 event advantage (`docs/p6_validity_report.md:156-166`).
8. **Did the LSTM cause scheduling regret?** Unknown. Confirmation has no same-scheduler forecast intervention or allocation vectors (`docs/p6_validity_report.md:147-154`).
9. **Is this Ruparel's DRO?** No. HeatTrace uses greedy/repair heuristics and a quantile PUE buffer; no Wasserstein optimization, Benders decomposition, battery, or renewable model (`src/heattrace/policy/robust.py:1-8`).
10. **Can I reproduce it?** The committed 54-file archive verifies and P11 reproduced scientific fields exactly. A bare checkout still lacks exact dependency pinning and runtime restoration of raw/model inputs (`docs/heattrace_p11_reproducibility_status.md`).

## Honest research status

- **Implemented and proven in-repository:** ingestion/alignment contracts, weather-only event construction, workload and thermal simulation, rolling policies, 756-cell confirmation, event-level analysis, P11 scientific reproduction.
- **Supported, bounded:** H1; H3 discriminability in two cases; full-thermal violation reductions under H2's OR rule.
- **Negative:** HeatGuard advantage; tested-boundary recovery; strict ranking reversals.
- **Untested/unestimable:** forecast-caused regret and phase-specific scheduler outcomes.
- **Planned only:** Days 15–21 ordinary-window robustness, controlled forecast arms, phase analysis, continuity ablation, and additional-event replication (`docs/heattrace-14-day-review.html:137-143`).

## What to say in one sentence

"HeatTrace is a reproducible historical-heatwave benchmark that found mixed, event-specific evidence of modeled thermal feasibility and policy separation, while its proposed HeatGuard margin was negative and forecast causality remains untested."
