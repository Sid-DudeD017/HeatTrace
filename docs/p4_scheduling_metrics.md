# HeatTrace P4 Scheduling & Metrics Methodology

## 1. Scheduling Model V0

All P4 policies and comparators evaluate over a common discrete horizon under identical physical conditions:

- **Window Offsets:** Integer hours $h \in \{0, \dots, 119\}$ (120 hours total per window).
- **Interval Semantics:** Job arrival offset $a_j$ is inclusive ($h \ge a_j$), deadline offset $d_j$ is exclusive ($h < d_j$).
- **Processing Requirements:** $p_j$ integer unit-hours of compute work.
- **Power & Energy Consumption:** Each unit-hour consumes power $P_j = E_j / p_j$ kW and energy $u_j = E_j / p_j$ kWh.
- **Job Parallelism:** A job may allocate at most $m_j \in \{1, 2, 4\}$ execution units concurrently in one hour.
- **Physical Cluster Limits:**
  - Hourly total cluster power: $\sum_{j} P_{j, h} \le 500.0$ kW.
  - Hourly distinct concurrent jobs: $|\{j : P_{j, h} > 0\}| \le 16$.
- **Preemption Rules:**
  - Preemptible jobs ($preemptible = True$): May execute in non-contiguous hourly slots.
  - Non-preemptible jobs ($preemptible = False$): Must execute in a strictly contiguous block of $p_j$ active hours.
- **Conservation Laws:** Total allocated energy $\sum_h E_{j, h} = E_j$ within numerical tolerance ($10^{-3}$ kWh). No policy may synthesize or drop energy.

## 2. Forecast Causality and No-Leakage Contract

- **Strict Causality:** At forecast origin $T$, any historical time series used for persistence or aggregation is filtered to $t < T$.
- **No Future Realized Values:** Target-period actual prices and carbon intensities are strictly forbidden in scheduling policies.
- **Fallback Policy:** If pre-origin history is missing or unverified, frozen defaults are used:
  - Electricity price: $45.0$ USD/MWh
  - Carbon intensity: $220.0$ g/kWh
- **Forecast/Actual Separation:** Policies receive only `ForecastResult` structures. Realized prices/carbon are joined strictly post-scheduling during scoring.

## 3. Policy Objectives & Heuristic Robustness

- **Cost-First Greedy (`cost_first`):** Prioritizes hours with lower forecast electricity price. Preserves and exploits negative LMP prices.
- **Carbon-First Greedy (`carbon_first`):** Prioritizes hours with lower forecast carbon intensity.
- **Balanced Greedy (`balanced`):** Min-max normalizes forecast price and carbon across the 120h horizon, minimizing $0.5 \times \hat{p}_{\text{norm}} + 0.5 \times \hat{c}_{\text{norm}}$.
- **Risk-Penalized DRO-Inspired Heuristic (`dro_inspired`):**
  - Score: $S_h = S_{\text{balanced}, h} + \lambda \times \Delta_h$.
  - Penalty derived from causal pre-origin historical residual quantile ($\alpha = 0.90, \lambda = 0.25$).
  - **Limitation Disclosure:** This is a transparent heuristic penalty, NOT a formal mathematical DRO optimizer with dual conic solvers. It provides no supremum ambiguity-set certificate.

## 4. Exact Small-Instance Hindsight Comparator

- **Scope:** Exact branch-and-bound optimization using realized actuals (explicit hindsight comparator).
- **Instance Limit:** Strictly bounded to small instances ($\le 6$ jobs, $\le 24$ hours).
- **Benchmark Handling:** For the full 30-job / 120-hour benchmark, the comparator returns status `unsupported`. It is never labeled zero-gap or optimal.

## 5. Metric Formulas

- **Realized Cost:** $\text{Cost (USD)} = \sum_h \frac{E_h \times \text{LMP}_h}{1000}$.
- **Realized Emissions:** $\text{Emissions (kg)} = \sum_h \frac{E_h \times \text{Carbon}_h}{1000}$.
- **CVaR₀.₉:** Expected shortfall of the top 10% worst hourly losses.
- **Comparator Gap:** $\frac{\text{Obj}_{\text{policy}} - \text{Obj}_{\text{exact}}}{\max(|\text{Obj}_{\text{exact}}|, \epsilon)}$.

## 6. Carbon Data-Quality Limitation

Across the 2024 CAISO benchmark, 240/240 hours retain EIA Known Data Issue flags ($0/240$ primary-eligible). All carbon emissions results carry the explicit label `quality_limited_sensitivity_only` and must not be cited as clean primary causal evidence.
