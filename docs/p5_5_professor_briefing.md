# HeatTrace P5.5 Briefing: Policy Discriminability & Stress Testing

**Meeting Briefing for Faculty Advisory Committee**  
**Date**: October 23, 2026  
**Evidence Classification**: Preliminary Controlled Simulation & Hindsight Upper Bounds  
**Audit Gate**: Gate G5.5-a Sign-Off (`VERIFIED_PASS`)  

---

## 1. Project Context & Objectives
HeatTrace investigates how extreme weather regimes impact electricity prices, carbon intensity, and workload scheduling in computational data centers.

### What P0–P5 Established
- **P0–P3**: Validated ingest of NOAA weather, CAISO prices, and EIA-930 grid data; formal heatwave detection (90th-percentile thresholds) and control matching.
- **P4**: Formal workload contract and scheduling policies (`cost_first`, `carbon_first`, `balanced`, `dro_inspired`).
- **P5 Authentic Baseline**: Empirical heatwave conditions elevated temperatures (+8.78°C), demand (+18.4%), and electricity prices (+107.8%). However, all scheduling policies produced identical schedules because forecasts were static persistence projections ($45/MWh, 220 g/kWh) and cluster capacity was unconstrained.

### Why P5.5 Was Added
P5.5 systematically maps the exact operational and informational conditions under which policies become distinguishable, determining the sensitivity of policy performance to forecast noise, workload pressure, capacity limits, and deadline flexibility.

---

## 2. Strongest Numerical Findings (Primary Fair Comparison Population)

All primary policy comparisons are conducted strictly on **jointly feasible scenarios with equal delivered energy** (N=158 scenarios):

1. **Information Gradients are the Primary Discriminability Prerequisite**:
   - Under flat forecasts, **100% of scenarios (54 of 54)** collapsed into identical schedules.
   - Non-flat forecasts produced **100% schedule differentiation (216 of 216)**, confirmed by canonical schedule digests.
2. **Cost-First Captures Sizable Reductions Under Foresight**:
   - In the matched control regime (`CTRL_20240605`, N=13), `cost_first` reduced electricity costs by **45.81%** vs. baseline ASAP execution.
   - In the heatwave event regime (`HW_20240702`, N=16), `cost_first` reduced electricity costs by **24.59%** vs. baseline.
3. **Monotonic Value Decay with Forecast Noise (Unconfounded Seeds)**:
   - For `cost_first`, relative savings vs. baseline degraded predictably as forecast error increased:
     * Oracle ($\sigma=0$): **34.10%** savings (N=29)
     * Low Noise ($\sigma=0.10$): **33.18%** savings (N=28)
     * Medium Noise ($\sigma=0.25$): **31.88%** savings (N=28)
     * High Noise ($\sigma=0.50$): **24.02%** savings (N=33)
   - High noise retained **70.44%** of the oracle advantage.
4. **Carbon vs. Cost Pareto Trade-Off**:
   - In the heatwave event (N=16), `carbon_first` reduced the emissions proxy by **14.93%**, but incurred a **23.53%** cost premium over `cost_first`.
5. **Operational Feasibility Limits**:
   - Feasibility was **99.1%** unconstrained, **73.8%** under moderate stress (250 kW / 8 jobs), and collapsed to **22.7%** under extreme stress (120 kW / 3 jobs). At $3	imes$ workload under extreme stress, feasibility was **0.0%**.
6. **Small-Instance Exact Comparator Validation**:
   - On 24-hour slices, `cost_first` achieved an exact **0.00%** optimality gap (global optimum), while baseline ASAP incurred a **21.19%** gap.

---

## 3. Central Figures for Meeting Discussion

1. **Cost–Carbon Pareto Frontier**: `data/figures/p5_5_fig1_cost_carbon_pareto.png`
2. **Forecast Error Sensitivity**: `data/figures/p5_5_fig2_forecast_error_sensitivity.png`
3. **Exact Small-Instance Comparator Gaps**: `data/figures/p5_5_fig6_comparator_optimality_gaps.png`

---

## 4. Key Limitations
- **Single Event/Control Pair**: Evaluated across 270 controlled combinations of one 120-hour heatwave event and one control window.
- **Carbon Disclaimer**: All carbon intensity observations carry EIA Known Data Issue flags; findings are quality-limited sensitivity evidence only.
- **No Causal / Production Claims**: Oracle and noisy-oracle runs are controlled simulations.
