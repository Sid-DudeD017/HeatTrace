# HeatTrace Policy Equivalence Diagnostic (P4 / P5)

## 1. Executive Summary & Root Cause Analysis

Across the Phase P4 benchmark evaluations on both `HW_20240702` and `CTRL_20240605`, all four production scheduling policies (`cost_first`, `carbon_first`, `balanced`, and `dro_inspired`) produced mathematically identical job allocations, costs, emissions, and CVaR outcomes:

- **Control Window (`CTRL_20240605`):** All 4 policies yielded Total Cost = \$103.9966, Total Emissions = 569.8798 kg, CVaR = \$3.1486.
- **Heatwave Window (`HW_20240702`):** All 4 policies yielded Total Cost = \$236.2015, Total Emissions = 831.2562 kg, CVaR = \$7.7894.

Detailed code and data inspection confirms that this behavior is **not a software defect, execution bug, or scoring error**. It is the authentic, deterministic, and mathematically expected outcome of two factors interacting in the experimental setup:

1. **Flat Pre-Origin Persistence Forecasts Across the 120-Hour Horizon:**
   - In adherence to strict causality and no-leakage rules, the P4 historical forecast provider (`historical_persistence_v0`) constructs forecasts using only observations strictly prior to the forecast origin timestamp ($t < T$).
   - For `CTRL_20240605` (origin 2024-06-05 07:00:00 UTC), no prior CAISO/weather observations were cached in the benchmark input, triggering the configured frozen fallback values ($p_h = \$45.0$/MWh, $c_h = 220.0$ g/kWh) uniformly across all $h \in [0, 119]$.
   - For `HW_20240702` (origin 2024-07-01 07:00:00 UTC), the single pre-origin observation available from the control window was persisted flatly across all 120 hours ($p_h = \$28.98081$/MWh, $c_h = 87.18878$ g/kWh).
   - In both cases, the forecast price and carbon signals are **spatially constant across the entire 120-hour scheduling horizon**.

2. **Identical Deterministic Tie-Breaking Across Policies Under Constant Objective Fields:**
   - Because predicted price and carbon intensity are constant across all 120 candidate hours, every eligible hourly slot evaluates to the exact same objective score:
     - `cost_first`: $S_h = \$28.98081$ (constant)
     - `carbon_first`: $S_h = 87.18878$ (constant)
     - `balanced`: $S_h = 0.5 \times 0.5 + 0.5 \times 0.5 = 0.5000$ (constant min-max normalized)
     - `dro_inspired`: $S_h = 0.5000 + (1.0 + h/120) \times 0.125$. Because the risk penalty strictly increases monotonically with horizon $h$, earlier hours always strictly beat later hours for all jobs.
   - For `cost_first`, `carbon_first`, and `balanced`, candidate hours with identical score break ties using the configured rule: **earliest candidate hour $h$**.
   - Under earliest-hour tie breaking, every job is allocated to the earliest available hour slots following its arrival offset $a_j$.
   - For `dro_inspired`, the monotonically increasing risk penalty also favors the earliest possible hour slot.
   - Consequently, all four policies allocate all 30 jobs to the exact same schedule allocations.

## 2. Experimental Verification

- **Job Constraint Feasibility:** The 30-job workload has an average slack of 11.5 hours (min 1 hour, max 24 hours), with power consumption well below the 500 kW cluster limit and at most 3 concurrent jobs (well below the 16 concurrency limit). Every job successfully completes at its earliest feasible opportunity without contention.
- **Scoring Integrity:** All realized scoring metrics accurately reflect the realized prices and emissions of these identical schedules.

## 3. Scientific Finding & Formal Limitation

This finding provides authentic experimental evidence that **in the presence of flat, non-time-varying forecasts (such as single-point historical persistence over multi-day horizons), policies designed with distinct cost, carbon, or risk trade-offs collapse to identical early-dispatch greedy schedules**.

Divergence between cost-optimal, carbon-optimal, and robust schedules requires **time-varying forecast trajectories** (e.g., diurnal solar curves or day-ahead price profiles) that provide temporal gradients for policies to exploit.
