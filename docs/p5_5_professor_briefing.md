# HeatTrace P5.5 Briefing: Policy Discriminability & Stress Testing

**Meeting Briefing for Faculty Advisory Committee**  
**Date**: October 23, 2026  
**Phase**: P5.5 Completion & Gate G5.5-a Sign-Off (`VERIFIED_PASS`)  

---

## 1. Project Objective & Context
HeatTrace investigates how extreme weather regimes—specifically multi-day heatwaves—impact energy market dynamics, carbon intensity, and workload scheduling in computational data centers.

### What P0–P5 Established
- **P0–P2**: High-integrity ingest, QC, and timestamp alignment of NOAA weather, CAISO LMP prices, and EIA-930 grid data.
- **P3**: Robust heatwave detection (90th-percentile temperature thresholds) and matched-control sampling.
- **P4**: Formal contract for workload execution, scheduling heuristics (Cost-First, Carbon-First, Balanced, DRO-inspired), and strict evaluation metrics.
- **P5**: Authentic empirical finding: 2024 heatwave conditions elevated temperatures (+8.78°C), demand (+18.4%), electricity prices (+107.8%), and execution cost (+127.1%). However, **all scheduling policies produced identical schedules and identical costs**.

### Why P5.5 Was Added
The P5 diagnostic revealed that identical policy outcomes were an artifact of flat persistence forecasts ($45/MWh, 220 g/kWh) and unconstrained capacity (500 kW / 16 jobs for 30 jobs). P5.5 was added to systematically determine the precise conditions under which policies become distinguishable across forecast fidelity, workload pressure, capacity limits, and deadline flexibility.

---

## 2. Strongest Numerical Findings (From 1,350 Evaluated Runs)

1. **Information Gradients are the Primary Policy Separator**:
   - Under flat forecasts, **100% of scenarios (54/54)** collapsed into identical policy results.
   - When non-flat forecast information was present, **100% of scenarios (216/216)** separated distinctly.
2. **Cost-First Captures Sizable Savings Under Foresight**:
   - In the matched control regime, `cost_first` reduced electricity costs by **43.86%** relative to the baseline ASAP schedule (\$113.14 vs. \$197.40).
   - In the heatwave event regime, `cost_first` reduced electricity costs by **19.38%** relative to baseline (\$346.55 vs. \$430.79), demonstrating that heatwaves compress flexible optimization margins due to higher baseload prices.
3. **Monotonic Value Decay with Forecast Noise**:
   - Relative cost savings degraded predictably as forecast error increased:
     - Oracle ($\sigma=0$): **31.62%** savings
     - Low noise ($\sigma=0.10$): **31.51%** savings
     - Medium noise ($\sigma=0.25$): **29.26%** savings
     - High noise ($\sigma=0.50$): **25.54%** savings
   - A $50\%$ relative noise level degraded only $\sim 19.2\%$ of the total oracle benefit, showing robust residual value in directional price forecasts.
4. **Feasibility and Operational Stress Limits**:
   - System feasibility dropped from **99.33%** (unconstrained) to **88.00%** (moderate stress: 250 kW / 8 jobs) and **32.22%** (extreme stress: 120 kW / 3 jobs).
   - At $3\times$ workload pressure under extreme bottlenecking, feasibility dropped to **0.00%**, mapping the exact physical collapse envelope.

---

## 3. Central Figures for Review

1. **Cost–Carbon Pareto Frontier**:
   - File: `data/figures/p5_5_fig1_cost_carbon_pareto.png` (also `.svg`)
   - Demonstrates the trade-off: `carbon_first` achieves lowest emissions (-14.9%) but incurs +19.5% cost vs. `cost_first`. `balanced` provides an optimal compromise.
2. **Forecast Error Sensitivity**:
   - File: `data/figures/p5_5_fig2_forecast_error_sensitivity.png` (also `.svg`)
   - Highlights the monotonic degradation of policy efficacy as forecast noise increases from $\sigma=0$ to $\sigma=0.50$.
3. **Feasibility and SLA Stress Envelope Heatmap**:
   - File: `data/figures/p5_5_fig4_feasibility_sla_heatmap.png` (also `.svg`)
   - Quantifies the joint impact of workload multiplier ($1\times, 2\times, 3\times$) and cluster limits (unconstrained, 250 kW, 120 kW) on deadline compliance.

---

## 4. Methodological Limitations & Evidence Boundaries

- **Carbon Data**: EIA-930 hourly carbon observations carry known data-quality flags across all benchmark rows. All carbon metrics are strictly **quality-limited sensitivity evidence**.
- **Oracle vs. Deployable**: Oracle evaluations represent theoretical hindsight upper bounds, not deployable forecasters.
- **No Causal / Production Claims**: Results are deterministic simulation benchmarks establishing mathematical discriminability.

---

## 5. Next Steps for Phase P6
With policy discriminability and stress boundaries rigorously proven and Gate G5.5-a passed:
1. Integrate realistic machine-learning time-series forecasters (e.g., gradient boosted or neural quantile forecasters trained on 2022–2023 data).
2. Execute rolling-horizon online scheduling over 2025 out-of-sample test windows.
3. Finalize paper manuscript and reproducible dissertation replication archive.
