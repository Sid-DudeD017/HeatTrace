# HeatTrace research claims and evidence

Authoritative evidence order: frozen protocol -> archived P8 cell table -> corrected P9/P10 generated tables -> P11 scientific-equivalence comparison. Planning text is not outcome evidence.

## H1–H5 adjudication

| Hypothesis | Frozen claim and test | Observed result | Verdict | Evidence and qualification |
|---|---|---|---|---|
| H1 | Static scheduler has lower tested maximum feasible workload in heatwave than matched control; medium curve, power-capped, carbon-first, event-level `lambda_hw-lambda_control`; support requires >=2/3 negative and negative median. | CONF1 -0.5x, CONF2 -0.5x, CONF3 0.0x; median -0.5x. Low-curve sensitivity only 1/3 negative. | **SUPPORTED** | `docs/p6_frozen_protocol.md:19-87`; `data/results/p6_h1_h5_assessment.csv`; `docs/p6_validity_report.md:98-113`. Coarse tested grid only, not a continuous threshold. |
| H2 | During heatwaves, capacity-aware scheduling has higher tested workload **or** fewer violations than static. | Exact `capacity_aware`: 0.0x recovery, 0.0h reduction. `full_thermal_aware`: no recovery; reductions 1.0h and 0.5h in applicable events, but CONF1 boundary worsened -0.5x. CONF3 N/A. | **PARTIALLY SUPPORTED** | `docs/p6_frozen_protocol.md:21-29`; `data/results/p6_t2_event_feasibility.csv`; `docs/p6_validity_report.md:115-128`. Supported only by the frozen OR rule's violation branch. |
| H3 | Complete-event evaluation produces materially different feasibility or ranking conclusions from event-blind equal-duration windows. Elevated prospectively after Day 8. | Heatwave vs blind non-zero gaps: 24/36 vs 0/36 in CONF1 and CONF2; 0/36 vs 0/36 in CONF3. 48 tie-to-non-tie transitions; 0 strict reversals/108. CONF1 control also 24/36. | **PARTIALLY SUPPORTED** | `docs/p6_validity_report.md:130-145`; `data/results/p6_t3_equal_service_gaps.csv`. This is policy separation, not strict reversal or consistent heatwave-specific superiority. |
| H4 | Controlled same-scheduler forecast substitution isolates forecast-caused regret. Formulated after Day 8. | No forecast arm, no hourly allocation vectors, scalar allocation count only. | **NOT ESTIMABLE** | `docs/p6_validity_report.md:147-154`; `data/results/p6_t4_forecast_evidence.csv`; `src/heattrace/experiments/p6_validity_runner.py:2205-2251`. Exploratory, not frozen confirmation. |
| H5 | Calibrated PUE-residual HeatGuard beats deterministic/no-margin and fixed 0.10 margin. | Calibrated vs fixed violation hours: CONF1 1.0 vs 0.0; CONF2 0.5 vs 0.5; CONF3 0 vs 0. Improved over both in 0/3 events. | **NOT SUPPORTED** | `docs/p6_validity_report.md:156-166`; `data/results/p6_t2_event_feasibility.csv`. No superiority/safety claim. |

## Finding-to-artifact map

| Finding | Numerical evidence | Evidence class | Source | Interpretation | Limitation |
|---|---|---|---|---|---|
| Development historical contrast | 2024 heatwave-control mean temperature +4.05°C; LMP +$26.71/MWh; demand +5,968 MW. | Development P5 | `docs/p5_experiments.md:14-30`; `data/results/p5_e1_window_summary_table.csv` | Historical conditions differ strongly in this pair. | One pair; paired hours are not independent events. |
| P5 policy collapse | All four policies: control $103.9966/569.8798 kg, heatwave $236.2015/831.2562 kg; identical allocations. | Development P5 | `docs/p5_policy_diagnostic.md:1-35` | Flat causal forecasts plus earliest tie-break erase policy distinctions. | Not evidence that the policies are universally equivalent. |
| P5.5 information-gradient result | 54/54 flat scenarios identical; 216/216 non-flat scenarios distinct. | Controlled development | `docs/p5_5_findings_report.md:23-30` | Time-varying information is necessary here for discriminability. | Oracle/noisy-oracle forecasts and one event/control pair. |
| P5.5 foresight performance | Equal-work oracle cost-first gaps: 45.81% control and 24.59% heatwave; noisy common cohort falls 35.00% to 23.58%. | Controlled hindsight | `docs/p5_5_findings_report.md:31-47` | Demonstrates value of information in synthetic controls. | Not deployable HeatTrace savings or causal LSTM evidence. |
| H1 feasibility | -0.5x, -0.5x, 0.0x. | Frozen confirmation | `data/results/p6_h1_h5_assessment.csv` | Bounded support for static feasibility degradation. | N=3; medium curve; synthetic facility/workload; discrete grid. |
| H2 violation tradeoff | Full thermal 1.0h and 0.5h reductions; exact capacity-aware 0h; no boundary recovery. | Frozen confirmation | `data/results/p6_t2_event_feasibility.csv`; `docs/p6_validity_report.md:115-128` | Thermal objective can change violations without improving the tested boundary. | Mixed outcome; CONF3 N/A. |
| H3 benchmark discriminability | `[+24,+24,0]` non-zero comparisons versus blind; 0 strict reversals. | Frozen confirmation | `data/results/p6_h1_h5_assessment.csv`; `docs/p6_validity_report.md:130-145` | Chosen blind windows missed gaps in two events. | CONF1 control discriminated equally; third event null. |
| Equal service | 530/540 pairwise comparisons eligible; 10 rejected, all involving incomplete non-deployable oracle; deployable rows complete required work. | Confirmation quality | `docs/p6_validity_report.md:187-205`; `data/results/p6_analysis_manifest.json` | Deployable cost/carbon comparisons are not driven by job dropping. | Oracle comparisons with unequal work are unusable. |
| Forecast gate | Validation LSTM RMSE 2.0739°C vs day-lag 2.3297°C; development heatwave 5.8075 vs 3.6948. | Validation + development | `data/results/p6_forecast_metrics.csv`; `docs/p6_pilot_review.md:83-103` | Validation gate passed, but heatwave generalization was poor. | No confirmatory forecast metric or causal scheduling intervention. |
| HeatGuard result | 0/3 event advantage over both comparators. | Frozen confirmation | `docs/p6_validity_report.md:156-166` | Negative algorithm result. | Conditional on frozen margin/model and three cases. |
| Reproduction | 756/756 rows, zero scientific differences, regenerated tables/figures match. | P11 reproduction | `data/results/p11_reproduction_comparison.json`; `docs/p11_v1_reproduction_report.md:47-116` | Strong deterministic reproducibility on the recorded machine/environment. | Exact dependencies not locked; raw external inputs not archived. |

## Corrections and discrepancies

1. `docs/p11_v1_reproduction_report.md:100` and `data/results/p11_reproduction_comparison.json` say CONF2 H3 is **23/36**. The corrected authoritative P10 report and current generated H3 table say **24/36** (`docs/p6_validity_report.md:134-140`; `data/results/p6_h1_h5_assessment.csv`). Use 24/36.
2. P11 says both "clean execution ... 756" (`docs/p11_v1_reproduction_report.md:47-66`) and "756 cells were not rerun" (`:161`). The two distinct output hashes and scientific comparison demonstrate a rerun; the last sentence is stale/incorrect.
3. The original 14-day plan labels HeatGuard as H4 (`docs/heattrace-heatguard-14-day-plan.md:81-97`). After Day 8, final P10 numbering makes forecast attribution exploratory H4 and HeatGuard comparator H5 (`docs/p6_validity_report.md:78-90,147-166`).
4. P6's benchmark table collapsed phase labels to `heatwave`; P7 repaired storage via an overlay but no phase-level result schema was added (`docs/p7_freeze_readiness.md:61-98`; `src/heattrace/experiments/p6_validity_runner.py:2205-2251`).
5. P5 described its event outcome sample as "phase-aware," but because policies were identical and later P8 did not retain phase metrics, this does not establish phase-dependent scheduler behavior (`docs/p5_experiments.md:52-58`).

## Permitted and prohibited claims

Permitted:

- "In two of three modeled CAISO cases, static scheduling had a 0.5x lower grid-bounded feasibility envelope in heatwave than control."
- "Complete heatwave windows exposed equal-service policy separations missed by the selected blind windows in two cases; the third case was null."
- "Calibrated HeatGuard did not outperform the fixed-margin comparator."

Prohibited:

- HeatGuard is superior, formally robust, or a Ruparel reproduction.
- Heatwaves generally cause real data-center failures.
- Capacity/thermal awareness restored feasibility.
- Event-blind testing selected the wrong scheduler (0 strict reversals).
- LSTM errors caused scheduler regret.
- Carbon gaps are avoided or marginal emissions.

These boundaries match `docs/p6_validity_report.md:240-262`.
