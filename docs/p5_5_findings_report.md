# HeatTrace P5.5 Findings Report: Policy Discriminability & Stress Testing

**Phase**: P5.5 — Policy Discriminability & Stress Testing  
**Audit Gate**: Gate G5.5-a (`VERIFIED_PASS`)  
**Evidence Standard**:
- Authentic historical baseline: P5 frozen CAISO/NOAA/EIA 120-hour windows.
- Controlled hindsight upper bound: Perfect-information oracle (`controlled_hindsight_upper_bound`).
- Controlled simulation: Deterministic seeded noisy oracles (`controlled_simulation`).
- Carbon interpretation: Quality-limited sensitivity only (`quality_limited_sensitivity_only`). No causal, production-readiness, or certified emissions claims are made.

---

## 1. Executive Summary & Research Question

### Research Question
Under what controlled conditions (forecast quality, workload pressure, capacity constraints, concurrency limits, and deadline flexibility) do workload scheduling policies become distinguishable, and where are the operational boundaries of feasibility and policy collapse?

### Background & Motivation
In Phase P5, evaluation on authentic CAISO 2024 heatwave (`HW_20240702`) and control (`CTRL_20240605`) windows revealed that while heatwave conditions dramatically elevated ambient temperatures (+8.78°C mean), system demand (+18.4%), LMP electricity prices (+107.8%), and overall execution costs (+127.1%), all scheduling policies produced identical schedules and identical costs ($103.9966 control, $236.2015 heatwave). 

Diagnostic analysis isolated the cause:
1. **Forecast Information Deficit**: Causal historical persistence forecasts emitted static horizontal projections ($45/MWh, 220 g/kWh), eliminating inter-hour cost gradients.
2. **Under-Constrained Cluster**: A 500 kW capacity and 16 concurrent job limit on a 30-job workload provided abundant slack, allowing greedy policies to default to identical arrival-ordered ties.

Phase P5.5 was designed to rigorously isolate policy separation thresholds by executing a full 270-scenario cartesian grid across 5 policies (1,350 total runs) spanning 5 forecast scenarios, 3 workload pressures ($1\times, 2\times, 3\times$), 3 cluster resource tiers, 3 deadline flexibility regimes, and 2 operational regimes (Heatwave Event vs. Matched Control).

---

## 2. Experimental Design & Preregistered Grid

The experiment was preregistered and frozen in machine-readable JSON at `data/manifests/p5_5_experiment_grid.json` prior to execution.

```
Total Scenarios: 270
Total Execution Runs: 1,350 (270 scenarios × 5 policies)
Evaluated Policies (5):
  1. baseline_reference (Earliest-Arrival / ASAP greedy benchmark)
  2. cost_first (Greedy electricity LMP price minimizer)
  3. carbon_first (Greedy carbon intensity proxy minimizer)
  4. balanced (Equal-weighted normalized price + carbon objective)
  5. dro_inspired (Distributionally robust risk-penalized heuristic)

Data Windows (2):
  - Heatwave Event: HW_20240702 (120 hours, July 1–6, 2024)
  - Matched Control: CTRL_20240605 (120 hours, June 5–10, 2024)

Forecast Regimes (5):
  - flat_forecast (Authentic baseline persistence: static projection)
  - oracle_forecast (Controlled hindsight upper bound: realized signals)
  - noisy_oracle_low (Controlled simulation: relative noise σ = 0.10, seed-derived)
  - noisy_oracle_medium (Controlled simulation: relative noise σ = 0.25, seed-derived)
  - noisy_oracle_high (Controlled simulation: relative noise σ = 0.50, seed-derived)

Workload Multipliers (3):
  - 1× (30 jobs, 101 processing-hours, 4,522.7 kWh)
  - 2× (60 jobs, 208 processing-hours, 9,287.5 kWh)
  - 3× (90 jobs, 307 processing-hours, 13,874.1 kWh)

Resource Pressures (3):
  - unconstrained: 500.0 kW max cluster power, 16 concurrent jobs
  - moderate_stress: 250.0 kW max cluster power, 8 concurrent jobs
  - extreme_stress: 120.0 kW max cluster power, 3 concurrent jobs

Deadline Flexibility (3):
  - baseline: 1.0× slack (mean slack: 11.5 hours)
  - tight: 0.5× slack (mean slack: 5.5 hours)
  - flexible: 1.5× slack (mean slack: 16.3 hours)
```

---

## 3. Headline Numerical Findings

1. **Information Gradients are the Primary Discriminability Prerequisite**:
   - Under `flat_forecast` (zero forecast gradient), **100% of scenarios (54 of 54)** produced identical costs across all 5 policies, exactly reproducing the authentic P5 baseline collapse.
   - As soon as non-flat forecast information was introduced (oracle or noisy oracle), **100% of scenarios (216 of 216)** produced distinct policy allocations and measurable cost/carbon divergence.

2. **Cost-First Achieves Sizable Reductions Under Forecast Availability**:
   - In the matched control regime under oracle foresight, `cost_first` reduced total realized electricity cost by **43.86%** relative to `baseline_reference` (mean cost: \$113.14 vs. \$197.40).
   - In the heatwave event regime under oracle foresight, `cost_first` reduced total realized cost by **19.38%** relative to `baseline_reference` (mean cost: \$346.55 vs. \$430.79). The smaller percentage reduction during heatwaves reflects the elevated baseload cost floor ($26.42/MWh minimum during heatwave vs. -$10.51/MWh solar curtailment trough during control).

3. **Forecast Noise Monotonically Degrades Policy Value**:
   - For `cost_first` across all windows, relative cost savings vs. baseline degraded monotonically from **31.62%** (oracle, $\sigma=0$) to **31.51%** ($\sigma=0.10$), **29.26%** ($\sigma=0.25$), and **25.54%** ($\sigma=0.50$).
   - Extreme noise ($\sigma=0.50$, price MAE \$22.8/MWh) eroded approximately **19.2% of the oracle foresight advantage**, yet `cost_first` remained distinctly superior to the non-shifting baseline.

4. **Carbon-First vs. Cost-First Pareto Trade-Off**:
   - Under oracle foresight in the heatwave regime, `carbon_first` achieved the lowest quality-limited emissions proxy (1,360.5 kg vs. 1,599.2 kg baseline, a **14.92% reduction**), but incurred **19.5% higher electricity cost** than `cost_first` (\$415.15 vs. \$346.55).
   - `balanced` achieved an effective compromised operating point, capturing **13.95% emissions reduction** while keeping cost within 5.8% of `cost_first` (\$366.78).

5. **Tail-Risk Mitigation (CVaR₀.₉₀)**:
   - In the heatwave event under oracle conditions, `cost_first` lowered 90th-percentile hourly tail loss ($\text{CVaR}_{0.90}$) from **\$11.59/h** (baseline) to **\$9.07/h** (-21.7%).
   - `dro_inspired` lowered tail risk to **\$9.94/h**, providing greater stability against horizon uncertainty than unpenalized balancing.

6. **Cluster Stress Envelope & Feasibility Collapse**:
   - Overall schedule feasibility was **73.19%** (988 of 1,350 runs feasible; 362 infeasible runs preserved and tracked with explicit deadline misses).
   - Feasibility drops sharply under concurrent load and bottlenecking:
     - Unconstrained: **99.33%** feasible.
     - Moderate stress (250 kW / 8 jobs): **88.00%** feasible.
     - Extreme stress (120 kW / 3 jobs): **32.22%** feasible.
   - At $3\times$ workload pressure under extreme resource stress, feasibility dropped to **0.00%**, establishing the exact operational capacity boundary for the 120-hour cluster.

---

## 4. Policy Performance Comparison Table

Table 1 summarizes mean performance across the 1,350 experimental runs grouped by policy and evidence class:

| Policy | Forecast Regime | Evidence Class | Mean Cost ($) | Mean Carbon (kg)* | Mean $\text{CVaR}_{0.90}$ | SLA Comp. Rate | Feasibility Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **baseline_reference** | flat_forecast | authentic_baseline | \$314.10 | 1,356.2 kg | \$8.28 | 98.9% | 85.2% |
| **cost_first** | flat_forecast | authentic_baseline | \$314.10 | 1,356.2 kg | \$8.28 | 98.9% | 85.2% |
| **carbon_first** | flat_forecast | authentic_baseline | \$314.10 | 1,356.2 kg | \$8.28 | 98.9% | 85.2% |
| **balanced** | flat_forecast | authentic_baseline | \$314.10 | 1,356.2 kg | \$8.28 | 98.9% | 85.2% |
| **dro_inspired** | flat_forecast | authentic_baseline | \$314.10 | 1,356.2 kg | \$8.28 | 98.9% | 85.2% |
| **baseline_reference** | oracle_forecast | controlled_hindsight | \$314.10 | 1,356.2 kg | \$8.28 | 98.9% | 85.2% |
| **cost_first** | oracle_forecast | controlled_hindsight | \$229.84 | 1,228.6 kg | \$6.35 | 97.4% | 72.2% |
| **carbon_first** | oracle_forecast | controlled_hindsight | \$287.35 | 1,146.5 kg | \$8.93 | 96.6% | 51.9% |
| **balanced** | oracle_forecast | controlled_hindsight | \$244.00 | 1,176.6 kg | \$6.87 | 97.2% | 74.1% |
| **dro_inspired** | oracle_forecast | controlled_hindsight | \$244.38 | 1,177.3 kg | \$6.88 | 97.3% | 74.1% |
| **cost_first** | noisy_oracle (low) | controlled_simulation | \$230.13 | 1,229.0 kg | \$6.37 | 97.2% | 72.2% |
| **cost_first** | noisy_oracle (med) | controlled_simulation | \$237.98 | 1,228.7 kg | \$6.62 | 97.3% | 74.1% |
| **cost_first** | noisy_oracle (high) | controlled_simulation | \$251.05 | 1,232.8 kg | \$7.01 | 97.0% | 68.5% |

*\*Carbon intensity contains known EIA data-quality flags across all benchmark rows; results are descriptive sensitivity metrics only.*

---

## 5. Artifact & Figure Index

All artifacts and publication-ready figures have been generated and verified:

1. **Cost–Carbon Pareto Frontier**:
   - PNG: `data/figures/p5_5_fig1_cost_carbon_pareto.png`
   - SVG: `data/figures/p5_5_fig1_cost_carbon_pareto.svg`
2. **Forecast-Error Sensitivity**:
   - PNG: `data/figures/p5_5_fig2_forecast_error_sensitivity.png`
   - SVG: `data/figures/p5_5_fig2_forecast_error_sensitivity.svg`
3. **Workload and Capacity Pressure**:
   - PNG: `data/figures/p5_5_fig3_workload_capacity_pressure.png`
   - SVG: `data/figures/p5_5_fig3_workload_capacity_pressure.svg`
4. **Feasibility and SLA Heatmap**:
   - PNG: `data/figures/p5_5_fig4_feasibility_sla_heatmap.png`
   - SVG: `data/figures/p5_5_fig4_feasibility_sla_heatmap.svg`
5. **Event vs. Control Paired Comparison**:
   - PNG: `data/figures/p5_5_fig5_event_vs_control.png`
   - SVG: `data/figures/p5_5_fig5_event_vs_control.svg`
6. **Data Tables & Manifests**:
   - Full Long-Form Experiment Results: `data/results/p5_5_experiment_results.csv` and `.parquet`
   - Policy Comparison Summary: `data/results/p5_5_policy_comparison_summary.csv`
   - Paired Differences: `data/results/p5_5_policy_paired_differences.csv`
   - Experiment Grid Manifest: `data/manifests/p5_5_experiment_grid.json`
   - Gate G5.5-a Audit Manifest: `data/manifests/p5_5_comprehensive_audit.json`

---

## 6. Methodological Limitations & Evidence Boundaries

1. **Carbon Interpretation**:
   EIA-930 hourly carbon observations for balancing authority CISO contain known official data-quality flags across all benchmark rows. Findings regarding carbon emissions are strictly **quality-limited sensitivity evidence** and must not be cited as certified carbon accounting or causal emissions reductions.
2. **Hindsight Oracle vs. Deployable Forecasting**:
   Oracle results represent a theoretical performance ceiling obtained by evaluating realized future values. They do not represent realizable performance of a causal production forecaster.
3. **Simulated Stress vs. Empirical Grid Dispatch**:
   Workload scaling ($1\times, 2\times, 3\times$) and capacity limits are controlled simulations on synthetic traces. They demonstrate policy sensitivity and operational failure boundaries, not empirical cluster telemetry.
4. **No Causal or Production-Readiness Claims**:
   The findings demonstrate mathematical policy discriminability under information and capacity gradients; they do not substantiate real-world deployment viability without online closed-loop testing (P6).
