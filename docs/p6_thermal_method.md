# Day 1 Thermal Stress Methodology: Controlled Simulation Mechanism

## 1. Motivation

In prior phases (P1–P5.5), HeatTrace utilized ambient temperature solely to detect, label, and classify heatwave events. Electricity price, grid carbon intensity, task deadlines, and fixed cluster power/concurrency constraints governed scheduling decisions. However, elevated ambient temperatures substantially impact data center cooling systems. In real facilities, chilling infrastructure must reject heat to hotter outside air, increasing the Power Usage Effectiveness (PUE) and scaling facility electricity consumption. When facility electrical interconnection caps or cooling limits are fixed, increased cooling demand compresses the power headroom available for IT compute servers, reducing effective compute capacity.

Day 1 introduces a controlled thermal-stress mechanism into HeatTrace to explore how temperature-driven cooling load and capacity derating interact with workload scheduling.

---

## 2. Causal Mechanism

The physical-causal progression implemented in this module is:

```
Ambient Temperature (temperature_c)
    │
    ▼ (piecewise-linear sensitivity above threshold)
Power Usage Effectiveness (PUE)
    │
    ├──▶ Cooling & Facility Energy Increase (facility_energy_kwh)
    │
    └──▶ Effective IT Compute Capacity Decreases (effective_compute_capacity_kw)
            │
            ▼
    Static Capacity Schedulers May Overcommit Facility Power
```

---

## 3. Core Equations and Units

All calculations operate on an hourly time step ($t$, duration 1.0 hour):

### 3.1 PUE from Temperature
$$
\text{excess\_temperature}[t] = \max(\text{temperature\_c}[t] - \text{threshold\_temperature\_c}, 0)
$$
$$
\text{PUE}[t] = \min(\text{base\_pue} + \text{slope\_per\_c} \times \text{excess\_temperature}[t],\, \text{max\_pue})
$$
*Constraint:* $\text{PUE}[t] \ge 1.0$ at all times. All numeric fields (`base_pue`, `threshold_temperature_c`, `slope_per_c`, `max_pue`) must be strictly finite, non-boolean floats.

### 3.2 Facility and Cooling Power & Energy
Given compute power $\text{compute\_power\_kw}[t]$ and compute energy $\text{compute\_energy\_kwh}[t]$:
$$
\text{facility\_power\_kw}[t] = \text{compute\_power\_kw}[t] \times \text{PUE}[t]
$$
$$
\text{facility\_energy\_kwh}[t] = \text{compute\_energy\_kwh}[t] \times \text{PUE}[t]
$$
$$
\text{cooling\_energy\_kwh}[t] = \text{facility\_energy\_kwh}[t] - \text{compute\_energy\_kwh}[t] = \text{compute\_energy\_kwh}[t] \times (\text{PUE}[t] - 1.0)
$$

### 3.3 Facility Power Cap and Effective Compute Capacity
Loaded directly from `configs/p6_thermal.yaml` (`nominal_compute_capacity_kw = 500.0`, `base_pue = 1.20`):
$$
\text{facility\_power\_cap\_kw} = \text{nominal\_compute\_capacity\_kw} \times \text{base\_pue} = 500.0 \times 1.20 = 600.0\text{ kW}
$$
$$
\text{effective\_compute\_capacity\_kw}[t] = \frac{\text{facility\_power\_cap\_kw}}{\text{PUE}[t]} = \text{nominal\_compute\_capacity\_kw} \times \frac{\text{base\_pue}}{\text{PUE}[t]}
$$
*Property:* At or below $\text{threshold\_temperature\_c}$, $\text{PUE}[t] = \text{base\_pue}$, preserving the nominal compute capacity exactly. As temperature rises, $\text{PUE}[t] > \text{base\_pue}$, compressing $\text{effective\_compute\_capacity\_kw}[t]$ below the nominal limit.

### 3.4 Cost and Carbon Conversions
$$
\text{cost\_usd}[t] = \frac{\text{facility\_energy\_kwh}[t] \times \text{price\_usd\_per\_mwh}[t]}{1000}
$$
$$
\text{carbon\_kg}[t] = \frac{\text{facility\_energy\_kwh}[t] \times \text{carbon\_g\_per\_kwh}[t]}{1000}
$$

---

## 4. Frozen Sensitivity and Facility Configuration

The sensitivity and facility limits are defined in `configs/p6_thermal.yaml` and frozen prior to experimental inspection:

| Parameter | Low Sensitivity | Medium Sensitivity | High Sensitivity |
| :--- | :---: | :---: | :---: |
| **Base PUE** (`base_pue`) | 1.20 | 1.20 | 1.20 |
| **Threshold Temperature** (`threshold_temperature_c`) | 22.0 °C | 22.0 °C | 22.0 °C |
| **Slope** (`slope_per_c`) | 0.010 / °C | 0.020 / °C | 0.035 / °C |
| **Max PUE** (`max_pue`) | 1.45 | 1.70 | 2.00 |

*Facility Cap & Operational Parameters (from YAML):*
- `nominal_compute_capacity_kw`: 500.0 kW
- `max_concurrent_jobs`: 16
- Nominal facility cap: $500.0 \times 1.20 = 600.0\text{ kW}$
- Numerical violation tolerance: $1.0 \times 10^{-6}\text{ kW}$

---

## 5. Policy Definitions

### 5.1 Temperature-Unaware Baseline
- Uses existing schedulers (`cost_first`, `carbon_first`, `balanced`, `dro_inspired`) without modification.
- Evaluates constraints against the original static nominal limit (`nominal_compute_capacity_kw = 500.0`).
- Does not observe temperature, PUE, facility cap, or dynamic effective compute capacity.
- Evaluated as-is under the realized thermal state so that physical capacity overcommitments remain fully observable.

### 5.2 Heat-Aware Capacity Adapter (Day 1 Controlled Feasibility MVP)
- Wraps any base scheduling policy (`<policy_name>_heat_aware_adapter`).
- Validates that the input effective capacity vector is non-empty, strictly positive, finite, and matches the horizon.
- Observes the dynamic vector $\text{effective\_compute\_capacity\_kw}[t]$.
- Receives the schedule from the base policy, retains allocations that fit within effective capacity and concurrency limits, and deterministically moves excess allocations to later feasible hours within $[ \text{arrival}, \text{deadline} )$.
- If no valid placement exists before deadline, records unmet deadlines and reports infeasibility.
- **Architectural Clarification:** This adapter is a controlled Day 1 feasibility repair adapter. It is explicitly NOT a native thermal optimizer and NOT a reproduction of Ruparel et al.'s adaptive DRO scheduler.

---

## 6. Feasibility, Scorer Deadline Semantics, and Timestamp Alignment

### 6.1 Timestamp Alignment Gate
Before scoring, `validate_timestamps_aligned` strictly enforces:
- `realized_df` and `thermal_state_df` both contain `timestamp_utc`.
- Both are timezone-aware UTC, strictly monotonic, contain no duplicates, and are aligned to the top of the hour.
- Both have identical lengths and match item-by-item in identical order.
- Any shift, reordering, duplicate, or naive timestamp fails loudly (never silently sorted).

### 6.2 Scorer Deadline & Bound Enforcement
`score_thermal_schedule` independently inspects every allocation:
- Allocations before arrival, at or after deadline, outside horizon $[0, \text{horizon})$, unknown job IDs, or duplicate (job, hour) pairs are flagged as invalid allocations.
- A job is complete only if:
  1. Required energy is delivered within numerical tolerance ($10^{-3}\text{ kWh}$).
  2. Required processing units are completely delivered.
  3. Every allocation for the job is within arrival and deadline bounds.
- Delivering energy after a deadline strictly fails feasibility.
- `thermally_feasible = True` if and only if:
  1. Hourly facility power excess $\le 10^{-6}\text{ kW}$.
  2. No unfinished jobs or deadline misses exist.
  3. No invalid allocations exist (`invalid_allocation_count == 0`).
  4. The underlying schedule result reported `is_feasible = True`.
- Summary metrics explicitly include:
  - `facility_power_violation_hours`
  - `maximum_facility_power_excess_kw`
  - `total_facility_power_excess_kwh`
  - `deadline_misses_count`
  - `unfinished_jobs_count`
  - `invalid_allocation_count`
  - `invalid_allocation_jobs`
  - `thermally_feasible`

---

## 7. Matched-Input and Workload Integrity

Integrity gates implemented in `src/heattrace/thermal/validation.py` require:
- **Canonical Workload Digest:** Deterministic SHA-256 digest computed across 9 canonical fields:
  `workload_trace_id`, `job_id`, `arrival_offset_hours`, `deadline_offset_hours`, `processing_requirement`, `energy_kwh`, `maximum_parallelism`, `priority`, `preemptible`.
  Any change to any of these fields (including priority or parallelism) changes the digest. The digest is row-order invariant and normalized using canonical sorted JSON.
- **Matched Inputs Enforcement:** `validate_matched_inputs` validates:
  - Event and control workload digests are identical.
  - Nominal compute capacities are identical.
  - Thermal scenario parameters are identical.
  - Horizon hours are identical (120 hours).
  - Window IDs differ between event and control, and appropriate window labels match.
  - Configuration digest is recorded.

---

## 8. Smoke Run and Positive-Control Implementation Check

### 8.1 Authentic Smoke Run
To execute the authentic Day 1 benchmark:
```bash
PYTHONPATH=src python3 -m heattrace.cli --run-p6-thermal-smoke
```
*(Or standalone module: `PYTHONPATH=src python3 -m heattrace.experiments.p6_thermal_grid`)*

- Evaluates 12 runs (2 windows $\times$ 1 policy $\times$ 2 policy classes $\times$ 3 thermal sensitivity levels).
- Under the standard unconstrained baseline workload ($30\text{ jobs}$, $500\text{ kW}$ nominal cap), the authentic smoke run shows 12/12 feasible runs because baseline cluster headroom exceeds thermal derating. This is an authentic outcome, not a flaw.

### 8.2 Positive-Control Synthetic Validation
To verify adapter mechanics when thermal stress does induce overcommitment, a dedicated synthetic positive-control test (`test_positive_control_unaware_failure_and_heat_aware_recovery`) is implemented in `tests/test_p6_thermal.py`:
- Concentrates high compute demand during hot hours ($35^\circ\text{C}$, $\text{PUE} = 1.46$, $\text{effective compute capacity} = 410.95\text{ kW}$).
- Proves that the temperature-unaware scheduler overcommits ($450\text{ kW} \times 1.46 = 657\text{ kW} > 600\text{ kW}$ cap, $\text{thermally\_feasible} = \text{False}$).
- Proves that `HeatAwareCapacityAdapter` detects the bottleneck, deterministically shifts workload into cooler subsequent hours with sufficient capacity, and achieves $\text{thermally\_feasible} = \text{True}$ on the identical workload.
- **Disclaimer:** The positive control is a synthetic implementation validation check, not an empirical finding.

---

## 9. Comprehensive Manifest Provenance

`data/manifests/p6_day1_smoke_manifest.json` records complete relative-path provenance:
- Hashes: `configuration_file_sha256`, `canonical_configuration_digest`, `benchmark_parquet_sha256`, `workload_parquet_sha256`, `canonical_workload_digest`, `forecast_parquet_sha256`, `results_csv_sha256`.
- Execution parameters: `nominal_compute_capacity_kw`, `derived_facility_cap_kw`, `max_concurrent_jobs`, `violation_tolerance_kw`, policy name/version, window IDs, horizon hours, scenario IDs.

---

## 10. Explicit Assumptions and Limitations

1. **Controlled Sensitivity, Not Calibrated Telemetry:** The piecewise-linear PUE curves represent preregistered sensitivity levels for controlled research evaluation, not calibrated empirical data center telemetry.
2. **Single CAISO Benchmark Pair:** Evaluation is conducted on `HW_20240702` and `CTRL_20240605`. Multi-event generalization is reserved for future research.
3. **No DRO Reproduction Claim:** `HeatAwareCapacityAdapter` is a deterministic Day 1 capacity-respecting repair adapter, not a reproduction of Ruparel et al.'s distributionally robust optimization (DRO) algorithm.
4. **Carbon Quality Disclaimer:** Carbon data contain known EIA quality flags across all benchmark rows. Findings are descriptive sensitivity metrics (`quality_limited_sensitivity_only`) and not avoided marginal emissions.
5. **No Universal Failure Claim:** Feasibility or infeasibility results in this controlled experiment demonstrate scheduler sensitivity to capacity derating under specified parameters; they do not prove that real-world data centers universally fail during heatwaves.

---

## 11. Day 2 Boundary and Requirements

Day 1 is strictly confined to interface design, scoring mechanics, thermal modeling, validation, unit tests, and smoke execution.

**Day 2 Requirements:**
Implement a native heat-aware policy that directly optimizes temperature-adjusted economic and carbon objectives:
- Cost-first score: $\text{predicted\_price}[t] \times \text{predicted\_PUE}[t]$
- Carbon-first score: $\text{predicted\_carbon}[t] \times \text{predicted\_PUE}[t]$
- Balanced score: linear combination of normalized temperature-adjusted scores,
while enforcing hourly effective compute capacity natively during candidate hour evaluation across the full experimental grid ($1.0\times, 2.0\times, 3.0\times$ workload multipliers, stress regimes, and bootstrap statistical distributions).
