"""Thermal scoring and metrics computation under realized thermal state.

Evaluates ScheduleResult against thermal conditions without silently altering allocations.
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.interfaces import ScheduleResult
from heattrace.thermal.model import ThermalScenario
from heattrace.thermal.validation import validate_timestamps_aligned


def score_thermal_schedule(
    schedule: ScheduleResult,
    workload_df: pd.DataFrame,
    realized_df: pd.DataFrame,
    thermal_state_df: pd.DataFrame,
    *,
    violation_tolerance_kw: float = 1e-6,
    carbon_interpretation_label: str = "quality_limited_sensitivity_only",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score a ScheduleResult against realized thermal state.

    Calculates:
        hourly_compute_power_kw
        hourly_compute_energy_kwh
        hourly_pue
        hourly_facility_power_kw
        hourly_facility_energy_kwh
        hourly_cooling_energy_kwh
        hourly_effective_compute_capacity_kw
        hourly_facility_power_excess_kw

    Summary metrics:
        facility_power_violation_hours
        total_facility_power_excess_kwh
        maximum_facility_power_excess_kw
        total_compute_energy_kwh
        total_cooling_energy_kwh
        total_facility_energy_kwh
        cooling_adjusted_cost_usd
        cooling_adjusted_carbon_kg
        thermally_feasible

    Failure rule:
        thermally_feasible is false when:
        - any hourly facility-power excess exceeds the frozen tolerance, or
        - the schedule leaves required workload unfinished by its deadline (or is_feasible is false).

    Returns:
        (hourly_score_df, summary_metrics_dict)
    """
    if isinstance(violation_tolerance_kw, bool) or not isinstance(violation_tolerance_kw, (int, float)):
        raise TypeError(f"violation_tolerance_kw must be a non-boolean numeric float, got {type(violation_tolerance_kw).__name__}")
    if not math.isfinite(violation_tolerance_kw) or violation_tolerance_kw < 0.0:
        raise ValueError(f"violation_tolerance_kw must be finite and non-negative, got {violation_tolerance_kw}")

    # Validate required columns exist in input DataFrames
    req_realized = {"timestamp_utc", "price_usd_per_mwh", "carbon_g_per_kwh"}
    missing_realized = req_realized - set(realized_df.columns)
    if missing_realized:
        raise ValueError(f"realized_df missing required columns: {sorted(missing_realized)}")

    req_thermal = {"timestamp_utc", "pue", "effective_compute_capacity_kw", "facility_power_cap_kw", "thermal_scenario_id"}
    missing_thermal = req_thermal - set(thermal_state_df.columns)
    if missing_thermal:
        raise ValueError(f"thermal_state_df missing required columns: {sorted(missing_thermal)}")

    validate_timestamps_aligned(realized_df, thermal_state_df)
    horizon = len(realized_df)

    pue_arr = thermal_state_df["pue"].to_numpy(dtype=float)
    if not np.all(np.isfinite(pue_arr)):
        raise ValueError("thermal_state_df['pue'] contains non-finite values (NaN or Inf)")
    if np.any(pue_arr < 1.0):
        raise ValueError(f"thermal_state_df['pue'] contains invalid values (< 1.0): min={np.min(pue_arr)}")

    eff_cap_arr = thermal_state_df["effective_compute_capacity_kw"].to_numpy(dtype=float)
    if not np.all(np.isfinite(eff_cap_arr)):
        raise ValueError("thermal_state_df['effective_compute_capacity_kw'] contains non-finite values (NaN or Inf)")
    if np.any(eff_cap_arr <= 0.0):
        raise ValueError("thermal_state_df['effective_compute_capacity_kw'] must be strictly positive")

    fac_cap_arr = thermal_state_df["facility_power_cap_kw"].to_numpy(dtype=float)
    if not np.all(np.isfinite(fac_cap_arr)):
        raise ValueError("thermal_state_df['facility_power_cap_kw'] contains non-finite values (NaN or Inf)")
    if np.any(fac_cap_arr <= 0.0):
        raise ValueError("thermal_state_df['facility_power_cap_kw'] must be strictly positive")

    realized_prices = realized_df["price_usd_per_mwh"].to_numpy(dtype=float)
    if not np.all(np.isfinite(realized_prices)):
        raise ValueError("realized_df['price_usd_per_mwh'] contains non-finite values (NaN or Inf)")

    realized_carbons = realized_df["carbon_g_per_kwh"].to_numpy(dtype=float)
    if not np.all(np.isfinite(realized_carbons)):
        raise ValueError("realized_df['carbon_g_per_kwh'] contains non-finite values (NaN or Inf)")

    # Validate schedule allocations
    for i, a in enumerate(schedule.allocations):
        h = a.allocated_hour_offset
        if isinstance(h, bool) or not isinstance(h, (int, np.integer)):
            raise TypeError(f"Allocation {i} allocated_hour_offset must be an integer, got {type(h).__name__}")
        p = a.execution_power_kw
        if isinstance(p, bool) or not isinstance(p, (int, float, np.floating)):
            raise TypeError(f"Allocation {i} execution_power_kw must be numeric, got {type(p).__name__}")
        if not math.isfinite(float(p)) or float(p) < 0.0:
            raise ValueError(f"Allocation {i} execution_power_kw must be finite and non-negative, got {p}")
        e = a.allocated_energy_kwh
        if isinstance(e, bool) or not isinstance(e, (int, float, np.floating)):
            raise TypeError(f"Allocation {i} allocated_energy_kwh must be numeric, got {type(e).__name__}")
        if not math.isfinite(float(e)) or float(e) < 0.0:
            raise ValueError(f"Allocation {i} allocated_energy_kwh must be finite and non-negative, got {e}")

    hourly_compute_power = np.zeros(horizon, dtype=float)
    hourly_compute_energy = np.zeros(horizon, dtype=float)

    # Aggregate hourly compute power and energy from allocations without curtailment
    for a in schedule.allocations:
        h = int(a.allocated_hour_offset)
        if 0 <= h < horizon:
            hourly_compute_power[h] += float(a.execution_power_kw)
            hourly_compute_energy[h] += float(a.allocated_energy_kwh)

    hourly_facility_power = hourly_compute_power * pue_arr
    hourly_facility_energy = hourly_compute_energy * pue_arr
    hourly_cooling_energy = hourly_facility_energy - hourly_compute_energy

    # Hourly facility power excess above facility_power_cap_kw
    # Note: excess_power_kw = max(facility_power_kw - facility_power_cap_kw, 0.0)
    raw_fac_excess = hourly_facility_power - fac_cap_arr
    hourly_fac_excess = np.maximum(raw_fac_excess, 0.0)

    # Hourly compute capacity excess is mathematically identical:
    # hourly_compute_power - effective_compute_capacity_kw = (hourly_facility_power - facility_cap) / pue

    # Violation condition strictly respects frozen tolerance
    hourly_violation_mask = raw_fac_excess > violation_tolerance_kw
    facility_power_violation_hours = int(np.sum(hourly_violation_mask))
    maximum_facility_power_excess_kw = float(np.max(hourly_fac_excess)) if horizon > 0 else 0.0
    total_facility_power_excess_kwh = float(np.sum(hourly_fac_excess))  # 1 hour per step

    # Costs and Carbon using realized hourly prices and carbon intensity
    # cost_usd = facility_energy_kwh * price_usd_per_mwh / 1000
    hourly_cost_usd = (hourly_facility_energy * realized_prices) / 1000.0
    cooling_adjusted_cost_usd = float(np.sum(hourly_cost_usd))

    # carbon_kg = facility_energy_kwh * carbon_g_per_kwh / 1000
    hourly_carbon_kg = (hourly_facility_energy * realized_carbons) / 1000.0
    cooling_adjusted_carbon_kg = float(np.sum(hourly_carbon_kg))

    total_compute_energy_kwh = float(np.sum(hourly_compute_energy))
    total_cooling_energy_kwh = float(np.sum(hourly_cooling_energy))
    total_facility_energy_kwh = float(np.sum(hourly_facility_energy))

    # Allocation validity and SLA checks on workload completion
    workload_jobs = {str(row["job_id"]): row for _, row in workload_df.iterrows()}
    job_alloc_energy: dict[str, float] = {jid: 0.0 for jid in workload_jobs}
    job_alloc_units: dict[str, int] = {jid: 0 for jid in workload_jobs}

    seen_alloc_pairs: set[tuple[str, int]] = set()
    invalid_allocation_jobs: set[str] = set()
    invalid_allocation_count: int = 0
    actual_deadline_miss_jobs: set[str] = set(schedule.unmet_deadlines)

    for a in schedule.allocations:
        jid = str(a.job_id)
        h = int(a.allocated_hour_offset)

        # 1. Unknown job ID check
        if jid not in workload_jobs:
            invalid_allocation_count += 1
            invalid_allocation_jobs.add(jid)
            continue

        job_info = workload_jobs[jid]
        arr = int(job_info["arrival_offset_hours"])
        dead = int(job_info["deadline_offset_hours"])

        # 2. Duplicate allocation check
        pair = (jid, h)
        if pair in seen_alloc_pairs:
            invalid_allocation_count += 1
            invalid_allocation_jobs.add(jid)
        seen_alloc_pairs.add(pair)

        # 3. Horizon bounds check
        if h < 0 or h >= horizon:
            invalid_allocation_count += 1
            invalid_allocation_jobs.add(jid)

        # 4. Arrival check
        if h < arr:
            invalid_allocation_count += 1
            invalid_allocation_jobs.add(jid)

        # 5. Deadline check (deadline exclusive)
        if h >= dead:
            invalid_allocation_count += 1
            invalid_allocation_jobs.add(jid)
            actual_deadline_miss_jobs.add(jid)

        # Valid in-bounds allocation contributes to completion
        if 0 <= h < horizon and arr <= h < dead:
            job_alloc_energy[jid] += float(a.allocated_energy_kwh)
            job_alloc_units[jid] += 1

    unfinished_jobs: list[str] = []
    for jid, job in workload_jobs.items():
        req_energy = float(job["energy_kwh"])
        req_proc = int(job["processing_requirement"])
        act_energy = job_alloc_energy[jid]
        act_units = job_alloc_units[jid]

        energy_done = abs(act_energy - req_energy) <= 1e-3
        units_done = (act_units == req_proc)

        # A job is complete only if energy, units, and all allocations were in-bounds
        if not (energy_done and units_done) or (jid in invalid_allocation_jobs):
            unfinished_jobs.append(jid)
            if not (energy_done and units_done):
                actual_deadline_miss_jobs.add(jid)

    leaves_work_unfinished = (len(unfinished_jobs) > 0) or (len(actual_deadline_miss_jobs) > 0)
    has_invalid_allocations = (invalid_allocation_count > 0)

    thermally_feasible = bool(
        (facility_power_violation_hours == 0)
        and (not leaves_work_unfinished)
        and (not has_invalid_allocations)
        and schedule.is_feasible
    )

    hourly_df = pd.DataFrame(
        {
            "timestamp_utc": realized_df["timestamp_utc"].copy(),
            "hourly_compute_power_kw": hourly_compute_power,
            "hourly_compute_energy_kwh": hourly_compute_energy,
            "hourly_pue": pue_arr,
            "hourly_facility_power_kw": hourly_facility_power,
            "hourly_facility_energy_kwh": hourly_facility_energy,
            "hourly_cooling_energy_kwh": hourly_cooling_energy,
            "hourly_effective_compute_capacity_kw": eff_cap_arr,
            "hourly_facility_power_excess_kw": hourly_fac_excess,
            "facility_power_violation": hourly_violation_mask,
            "hourly_cost_usd": hourly_cost_usd,
            "hourly_carbon_kg": hourly_carbon_kg,
        },
        index=realized_df.index,
    )

    summary = {
        "policy_name": schedule.policy_name,
        "policy_version": schedule.policy_version,
        "thermal_scenario_id": str(thermal_state_df["thermal_scenario_id"].iloc[0]),
        "total_compute_energy_kwh": round(total_compute_energy_kwh, 4),
        "total_cooling_energy_kwh": round(total_cooling_energy_kwh, 4),
        "total_facility_energy_kwh": round(total_facility_energy_kwh, 4),
        "cooling_adjusted_cost_usd": round(cooling_adjusted_cost_usd, 4),
        "cooling_adjusted_carbon_kg": round(cooling_adjusted_carbon_kg, 4),
        "facility_power_violation_hours": facility_power_violation_hours,
        "total_facility_power_excess_kwh": round(total_facility_power_excess_kwh, 4),
        "maximum_facility_power_excess_kw": round(maximum_facility_power_excess_kw, 4),
        "thermally_feasible": thermally_feasible,
        "unfinished_jobs_count": len(unfinished_jobs),
        "deadline_misses_count": len(actual_deadline_miss_jobs),
        "invalid_allocation_count": invalid_allocation_count,
        "invalid_allocation_jobs": sorted(list(invalid_allocation_jobs)),
        "carbon_interpretation_label": carbon_interpretation_label,
        "carbon_disclaimer": "EIA carbon observations contain known data-quality flags across all benchmark rows. Findings are descriptive/sensitivity-only and not primary causal evidence.",
    }

    return hourly_df, summary
