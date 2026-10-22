# HeatTrace P5.5 Findings Report: Policy Discriminability & Stress Testing

**Phase**: P5.5 — Policy Discriminability & Stress Testing (Grid Version v2)  
**Audit Gate**: Gate G5.5-a (`VERIFIED_PASS`)  
**Evidence Taxonomy**:
- `authentic_historical_baseline`: Original P5 1× workload, unconstrained capacity, baseline deadline under authentic CAISO/NOAA/EIA 120-hour windows.
- `controlled_simulation_flat_forecast`: Flat forecast combined with modified workload, capacity, or deadline conditions.
- `controlled_hindsight_upper_bound`: Perfect-information oracle evaluations.
- `controlled_simulation_noisy_oracle`: Seeded perturbations of realized signals with unconfounded noise trajectories.
- Carbon Interpretation: `quality_limited_sensitivity_only` across all rows. No causal, certified emissions, or production-readiness claims are made.

---

## 1. Experimental Methodology & Separation of Analysis Populations

### Primary Fair Comparison Population
To eliminate the artifact where infeasible policies appear artificially inexpensive by dropping unserved work, all primary policy comparisons are conducted strictly on the **Primary Fair Comparison population**:
- **Total Preregistered Scenarios**: 270
- **Jointly Feasible Scenarios**: 158 (58.52% of total)
- **Delivered Work Equality**: Exactly identical delivered energy (max difference 0.0 kWh) across all policies within each analyzed scenario.

In addition to the primary fair view, the complete repository outputs include:
1. `data/results/p5_5_view1_primary_fair_summary.csv`: Jointly feasible scenarios only.
2. `data/results/p5_5_view2_service_normalized_summary.csv`: Cost per delivered kWh and carbon per delivered kWh with explicit SLA metrics.
3. `data/results/p5_5_view3_failure_aware_summary.csv`: Penalized costs ($1.00/unmet kWh + $50/unmet job).
4. `data/results/p5_5_policy_paired_differences.csv`: Paired differences with explicit feasibility, delivered energy, and validity flags.

---

## 2. Headline Numerical Findings

1. **Information Gradients are the Primary Discriminability Prerequisite**:
   - Under `flat_forecast` (zero forecast gradient), **100.0% of scenarios (54 of 54)** produced 100% identical schedule allocations and identical costs across all 5 policies, exactly reproducing the authentic P5 baseline collapse.
   - Across non-flat forecast scenarios (oracle and noisy oracle), **100.0% of scenarios (216 of 216)** produced distinct schedule allocations verified by unique schedule SHA-256 digests.

2. **Primary Fair Cost Savings (Equal Delivered Work)**:
   - In the matched control regime (`CTRL_20240605`) under oracle foresight (N=13 jointly feasible scenarios), `cost_first` reduced electricity costs by **45.81%** relative to `baseline_reference`.
   - In the heatwave event regime (`HW_20240702`) under oracle foresight (N=16 jointly feasible scenarios), `cost_first` reduced electricity costs by **24.59%** relative to baseline. The smaller percentage reduction during heatwaves reflects the elevated baseload cost floor ($26.42/MWh minimum during heatwave vs. -$10.51/MWh solar curtailment trough during control).

3. **Forecast Noise Sensitivity (Common Cohort, N=26 Per Level)**:
   - Evaluated strictly across the common like-for-like cohort of stress cells (identical window, workload, capacity, and deadline settings that are jointly feasible with equal work at every forecast level), relative cost savings for `cost_first` degraded monotonically:
     * Oracle ($\sigma=0.00$, N=26): **35.00%** savings
     * Low Noise ($\sigma=0.10$, N=26): **33.91%** savings
     * Medium Noise ($\sigma=0.25$, N=26): **31.96%** savings
     * High Noise ($\sigma=0.50$, N=26): **23.58%** savings
   - At high noise ($\sigma=0.50$), `cost_first` retained **67.37%** of the oracle foresight advantage.
   - *(Secondary descriptive unconstrained set: Oracle 34.10%, Low 33.18%, Med 31.88%, High 24.02%)*

4. **Cost vs. Quality-Limited Carbon Pareto Trade-Off**:
   - In the heatwave event under oracle foresight (N=16), `carbon_first` achieved a **14.93%** reduction in the quality-limited emissions proxy relative to baseline, but incurred a **23.53%** cost premium over `cost_first`.

5. **Tail-Risk Mitigation (CVaR₀.₉₀)**:
   - In the heatwave event under oracle foresight (N=16), `cost_first` reduced 90th-percentile hourly tail loss from **$12.94/h** (baseline) to **$9.68/h** (a **25.19%** reduction).
   - `dro_inspired` achieved **$10.82/h**, bounding worst-case tail spikes.

6. **Operational Feasibility Stress Boundary**:
   - Schedule feasibility was **99.11%** under unconstrained cluster limits, **73.78%** under moderate stress (250 kW / 8 jobs), and collapsed to **22.67%** under extreme stress (120 kW / 3 jobs).
   - At 3× workload pressure under extreme resource stress, feasibility dropped to **0.00%**, mapping the physical saturation boundary.

7. **Exact Small-Instance Comparator Validation**:
   - On 24-hour / 4-job slices of the authentic signals, exact branch-and-bound verified that `cost_first` achieved an exact **0.00%** optimality gap (finding the global optimum), whereas `baseline_reference` incurred a **21.19%** suboptimality gap.

---

## 3. Artifact Index

1. **Results Tables**:
   - Long-form table: `data/results/p5_5_experiment_results.csv` and `.parquet`
   - Primary Fair View: `data/results/p5_5_view1_primary_fair_summary.csv`
   - Service-Normalized View: `data/results/p5_5_view2_service_normalized_summary.csv`
   - Failure-Aware View: `data/results/p5_5_view3_failure_aware_summary.csv`
   - Paired Differences: `data/results/p5_5_policy_paired_differences.csv`
   - Comparator Validation: `data/results/p5_5_comparator_validation_results.csv`
   - Machine-Readable Headline Findings: `data/results/p5_5_headline_findings.json` and `.csv`
2. **Figures (PNG + SVG)**:
   - Fig 1 (Cost-Carbon Pareto): `data/figures/p5_5_fig1_cost_carbon_pareto.png`
   - Fig 2 (Forecast Sensitivity): `data/figures/p5_5_fig2_forecast_error_sensitivity.png`
   - Fig 3 (Workload/Capacity Stress): `data/figures/p5_5_fig3_workload_capacity_pressure.png`
   - Fig 4 (Feasibility Heatmap): `data/figures/p5_5_fig4_feasibility_sla_heatmap.png`
   - Fig 5 (Event vs Control): `data/figures/p5_5_fig5_event_vs_control.png`
   - Fig 6 (Comparator Optimality Gaps): `data/figures/p5_5_fig6_comparator_optimality_gaps.png`
3. **Manifests**:
   - Experiment Grid Manifest: `data/manifests/p5_5_experiment_grid.json`
   - Experiment Run Manifest: `data/manifests/p5_5_experiment_manifest.json`
   - Gate G5.5-a Audit Manifest: `data/manifests/p5_5_comprehensive_audit.json`

---

## 4. Methodological Limitations
1. **Sample Scope**: Findings are derived from one 120-hour heatwave event (`HW_20240702`) and one matched control window (`CTRL_20240605`).
2. **Carbon Observations**: EIA carbon data carry official Known Data Issue flags across all rows; results are descriptive sensitivity metrics only.
3. **Hindsight Bounds**: Oracle evaluations are theoretical hindsight upper bounds, not deployable forecasts.
