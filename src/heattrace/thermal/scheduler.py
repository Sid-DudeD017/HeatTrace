"""Thermal scheduling policies: Unaware baseline and Heat-Aware Capacity Adapter.

DISCLAIMER: The HeatAwareAdapter is a deterministic Day 1 capacity-respecting repair
adapter, NOT a faithful reproduction of Ruparel et al.'s adaptive DRO scheduler.
"""

from __future__ import annotations

import copy
import math
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.common import sort_workload_jobs_deterministically
from heattrace.policy.interfaces import (
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
    SchedulingPolicy,
)


def create_temperature_unaware_schedule(
    policy: SchedulingPolicy,
    workload_df: pd.DataFrame,
    forecast: ForecastResult,
    nominal_constraints: SchedulingConstraints,
) -> ScheduleResult:
    """Generate temperature-unaware schedule using existing policy and nominal constraints.

    Does not expose temperature, PUE, facility cap, or hourly effective capacity.
    """
    return policy.schedule(workload_df, forecast, nominal_constraints)


class HeatAwareCapacityAdapter:
    """Deterministic repair adapter ensuring allocations respect hourly effective capacity.

    Mechanics:
    1. Generate schedule using underlying policy.
    2. Respect arrival constraints, deadlines, processing requirements, energy,
       concurrency limits, and deterministic tie-breaking.
    3. Keep allocations that fit the hourly effective capacity vector.
    4. Deterministically move excess allocations to later feasible hours [arr, dead).
    5. Mark work as unmet if no valid placement exists.
    6. Report result under name '<original_policy_name>_heat_aware_adapter'.

    NOTE: This is NOT a published DRO reproduction. It is a Day 1 deterministic adapter.
    """

    def __init__(
        self,
        base_policy: SchedulingPolicy,
        hourly_effective_capacity_kw: np.ndarray | pd.Series | list[float],
        tolerance_kw: float = 1e-6,
    ) -> None:
        if isinstance(tolerance_kw, bool) or not isinstance(tolerance_kw, (int, float)):
            raise TypeError("tolerance_kw must be a numeric float")
        if not math.isfinite(tolerance_kw) or tolerance_kw < 0.0:
            raise ValueError(f"tolerance_kw must be finite and non-negative, got {tolerance_kw}")

        arr = np.asarray(hourly_effective_capacity_kw, dtype=float)
        if arr.size == 0:
            raise ValueError("hourly_effective_capacity_kw cannot be empty")
        if not np.all(np.isfinite(arr)):
            raise ValueError("hourly_effective_capacity_kw contains NaN or infinity")
        if np.any(arr <= 0.0):
            raise ValueError("hourly_effective_capacity_kw must contain strictly positive values")

        self.base_policy = base_policy
        self.effective_capacity = arr
        self.tolerance_kw = float(tolerance_kw)

    @property
    def policy_name(self) -> str:
        return f"{self.base_policy.policy_name}_heat_aware_adapter"

    @property
    def policy_version(self) -> str:
        return f"{self.base_policy.policy_version}-heat-aware-adapter"

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        if workload_df.empty:
            raise ValueError("workload_df cannot be empty")

        trace_id = str(workload_df["workload_trace_id"].iloc[0])
        horizon = len(forecast.points)

        if len(self.effective_capacity) != horizon:
            raise ValueError(
                f"Effective capacity length ({len(self.effective_capacity)}) != horizon ({horizon})"
            )

        # 1. Generate base schedule with nominal constraints
        base_result = self.base_policy.schedule(workload_df, forecast, constraints)

        # 2. Extract job metadata for bounds checking
        workload_jobs = {str(row["job_id"]): row for _, row in workload_df.iterrows()}

        # Group base allocations by job
        job_base_allocs: dict[str, list[ScheduledJobAllocation]] = {jid: [] for jid in workload_jobs}
        for a in base_result.allocations:
            if a.job_id in job_base_allocs:
                job_base_allocs[a.job_id].append(a)

        # Track hourly usage under effective capacity
        hourly_power = np.zeros(horizon, dtype=float)
        hourly_jobs: list[set[str]] = [set() for _ in range(horizon)]

        final_allocations: list[ScheduledJobAllocation] = []
        unmet_deadlines: list[str] = list(base_result.unmet_deadlines)

        # Process jobs in deterministic order matching common policy sorting
        sorted_jobs = sort_workload_jobs_deterministically(workload_df)

        for _, job in sorted_jobs.iterrows():
            jid = str(job["job_id"])
            arr = int(job["arrival_offset_hours"])
            dead = int(job["deadline_offset_hours"])
            proc_req = int(job["processing_requirement"])
            energy_kwh = float(job["energy_kwh"])
            max_parallelism = int(job.get("maximum_parallelism", 1))

            # Validate job bounds to prevent invalid bounds from causing indexing or arithmetic failures
            if arr < 0 or dead <= arr or proc_req <= 0 or not math.isfinite(energy_kwh) or energy_kwh < 0.0:
                if jid not in unmet_deadlines:
                    unmet_deadlines.append(jid)
                continue

            unit_power_kw = energy_kwh / proc_req
            unit_energy_kwh = energy_kwh / proc_req

            existing_allocs = sorted(job_base_allocs[jid], key=lambda a: a.allocated_hour_offset)
            allocated_for_this_job: list[ScheduledJobAllocation] = []

            # Track hours already assigned for this job to prevent duplicate (jid, hour)
            job_hours: set[int] = set()

            # Attempt to retain each existing allocation in place if it fits
            overflow_units = 0

            for a in existing_allocs:
                h = a.allocated_hour_offset
                # Strict bounds check: must be a valid non-negative integer strictly within [0, horizon)
                # and strictly within [arr, min(dead, horizon)) before ANY indexing!
                # Never index with negative h, and never index h >= horizon.
                if (
                    isinstance(h, (int, np.integer))
                    and not isinstance(h, bool)
                    and 0 <= h < horizon
                    and arr <= h < min(dead, horizon)
                ):
                    h_int = int(h)
                    cap_h = self.effective_capacity[h_int]
                    fits_cap = (hourly_power[h_int] + unit_power_kw <= cap_h + self.tolerance_kw)
                    fits_concurrent = (
                        jid in hourly_jobs[h_int]
                        or len(hourly_jobs[h_int]) < constraints.max_concurrent_jobs
                    )

                    if fits_cap and fits_concurrent and (h_int not in job_hours):
                        hourly_power[h_int] += unit_power_kw
                        hourly_jobs[h_int].add(jid)
                        job_hours.add(h_int)
                        allocated_for_this_job.append(
                            ScheduledJobAllocation(
                                job_id=jid,
                                allocated_hour_offset=h_int,
                                execution_power_kw=unit_power_kw,
                                allocated_energy_kwh=unit_energy_kwh,
                            )
                        )
                    else:
                        overflow_units += 1
                else:
                    # Out of bounds (e.g. h < 0, h >= horizon, h < arr, h >= dead, or non-int):
                    # Deterministically treat as overflow work to be repaired
                    overflow_units += 1

            # Deterministically place overflow units into feasible hours within [arr, min(dead, horizon))
            # Note: if arr >= min(dead, horizon), range is empty and overflow_units remain unplaced
            if overflow_units > 0:
                repair_start = max(arr, 0)
                repair_end = min(dead, horizon)
                if repair_start < repair_end:
                    for cand_h in range(repair_start, repair_end):
                        if overflow_units == 0:
                            break
                        if cand_h in job_hours:
                            continue
                        cap_h = self.effective_capacity[cand_h]
                        fits_cap = (hourly_power[cand_h] + unit_power_kw <= cap_h + self.tolerance_kw)
                        fits_concurrent = (
                            jid in hourly_jobs[cand_h]
                            or len(hourly_jobs[cand_h]) < constraints.max_concurrent_jobs
                        )

                        if fits_cap and fits_concurrent:
                            hourly_power[cand_h] += unit_power_kw
                            hourly_jobs[cand_h].add(jid)
                            job_hours.add(cand_h)
                            allocated_for_this_job.append(
                                ScheduledJobAllocation(
                                    job_id=jid,
                                    allocated_hour_offset=cand_h,
                                    execution_power_kw=unit_power_kw,
                                    allocated_energy_kwh=unit_energy_kwh,
                                )
                            )
                            overflow_units -= 1

            if len(allocated_for_this_job) < proc_req:
                if jid not in unmet_deadlines:
                    unmet_deadlines.append(jid)

            final_allocations.extend(allocated_for_this_job)

        # Sort allocations deterministically by hour offset, then job_id
        final_allocations.sort(key=lambda a: (a.allocated_hour_offset, a.job_id))

        is_feasible = (len(unmet_deadlines) == 0) and (
            len(final_allocations) == int(workload_df["processing_requirement"].sum())
        )

        return ScheduleResult(
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            workload_trace_id=trace_id,
            window_duration_hours=horizon,
            allocations=final_allocations,
            unmet_deadlines=sorted(list(set(unmet_deadlines))),
            is_feasible=is_feasible,
        )
