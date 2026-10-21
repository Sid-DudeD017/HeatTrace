"""Feasibility validation for workload schedules and cluster physical limits."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any
import pandas as pd

from heattrace.policy.interfaces import ScheduleResult, SchedulingConstraints


@dataclass
class FeasibilityReport:
    """Detailed structured feasibility report."""
    is_feasible: bool
    violations: list[str] = field(default_factory=list)
    completed_jobs: list[str] = field(default_factory=list)
    incomplete_jobs: list[str] = field(default_factory=list)
    deadline_misses: list[str] = field(default_factory=list)
    unmet_processing_unit_hours: float = 0.0
    unmet_energy_kwh: float = 0.0
    max_hourly_power_kw: float = 0.0
    max_hourly_concurrent_jobs: int = 0
    total_allocated_energy_kwh: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_feasible": self.is_feasible,
            "violation_count": len(self.violations),
            "violations": self.violations,
            "completed_jobs_count": len(self.completed_jobs),
            "incomplete_jobs_count": len(self.incomplete_jobs),
            "deadline_misses_count": len(self.deadline_misses),
            "completed_jobs": self.completed_jobs,
            "incomplete_jobs": self.incomplete_jobs,
            "deadline_misses": self.deadline_misses,
            "unmet_processing_unit_hours": round(self.unmet_processing_unit_hours, 4),
            "unmet_energy_kwh": round(self.unmet_energy_kwh, 4),
            "max_hourly_power_kw": round(self.max_hourly_power_kw, 4),
            "max_hourly_concurrent_jobs": self.max_hourly_concurrent_jobs,
            "total_allocated_energy_kwh": round(self.total_allocated_energy_kwh, 4),
        }


def validate_schedule_feasibility(
    schedule: ScheduleResult,
    workload_df: pd.DataFrame,
    constraints: SchedulingConstraints,
    *,
    energy_tolerance_kwh: float = 1e-3,
    max_cluster_power_kw: float = 500.0,
    max_concurrent_jobs: int = 16,
    window_duration_hours: int = 120,
) -> FeasibilityReport:
    """Strictly and independently recompute feasibility from allocations.

    Checks:
    - Unknown jobs
    - Duplicate allocations (job_id, hour)
    - Out-of-window offsets ([0, window_duration_hours))
    - Non-finite or negative values
    - Arrival (inclusive) and deadline (exclusive) compliance
    - Preemptible vs non-preemptible contiguity
    - Parallelism per hour <= maximum_parallelism
    - Total unit-hours == processing_requirement
    - Total allocated energy == energy_kwh (within tolerance)
    - Hourly cluster power <= max_cluster_power_kw
    - Hourly concurrent distinct jobs <= max_concurrent_jobs
    """
    violations: list[str] = []
    workload_jobs = {row["job_id"]: row for _, row in workload_df.iterrows()}

    allocs = schedule.allocations
    allocated_jobs: set[str] = set()

    # Track hourly usage
    hourly_power: dict[int, float] = {h: 0.0 for h in range(window_duration_hours)}
    hourly_jobs: dict[int, set[str]] = {h: set() for h in range(window_duration_hours)}

    # Track per-job allocations
    job_alloc_hours: dict[str, list[int]] = {jid: [] for jid in workload_jobs}
    job_alloc_units: dict[str, float] = {jid: 0.0 for jid in workload_jobs}
    job_alloc_energy: dict[str, float] = {jid: 0.0 for jid in workload_jobs}

    seen_pairs: set[tuple[str, int]] = set()

    for idx, a in enumerate(allocs):
        jid = a.job_id
        if jid not in workload_jobs:
            violations.append(f"Allocation {idx}: unknown job_id '{jid}'")
            continue

        allocated_jobs.add(jid)
        h = a.allocated_hour_offset
        pwr = a.execution_power_kw
        en = a.allocated_energy_kwh

        # Check out of window
        if h < 0 or h >= window_duration_hours:
            violations.append(f"Job {jid}: allocated hour {h} out of window [0, {window_duration_hours})")
            continue

        # Check finite and positive
        if not math.isfinite(pwr) or pwr <= 0:
            violations.append(f"Job {jid} hour {h}: invalid execution_power_kw {pwr}")
        if not math.isfinite(en) or en <= 0:
            violations.append(f"Job {jid} hour {h}: invalid allocated_energy_kwh {en}")

        # Check duplicate
        pair = (jid, h)
        if pair in seen_pairs:
            violations.append(f"Job {jid} has duplicate allocation in hour {h}")
        seen_pairs.add(pair)

        # Update hourly stats
        hourly_power[h] = hourly_power.get(h, 0.0) + pwr
        hourly_jobs[h].add(jid)

        job_info = workload_jobs[jid]
        unit_energy = float(job_info["energy_kwh"]) / float(job_info["processing_requirement"])
        units_allocated = en / unit_energy if unit_energy > 0 else 1.0

        # Max parallelism check
        max_par = float(job_info.get("maximum_parallelism", 1))
        if units_allocated > max_par + 1e-4:
            violations.append(f"Job {jid} hour {h}: units {units_allocated:.2f} exceeds max_parallelism {max_par}")

        # Arrival and deadline check (arrival inclusive, deadline exclusive)
        arr = int(job_info["arrival_offset_hours"])
        dead = int(job_info["deadline_offset_hours"])
        if h < arr:
            violations.append(f"Job {jid} allocated at {h} before arrival {arr}")
        if h >= dead:
            violations.append(f"Job {jid} allocated at {h} at/after deadline {dead}")

        job_alloc_hours[jid].append(h)
        job_alloc_units[jid] += units_allocated
        job_alloc_energy[jid] += en

    # Global cluster constraints
    max_observed_pwr = 0.0
    max_observed_concurrent = 0
    for h in range(window_duration_hours):
        hp = hourly_power[h]
        if hp > max_observed_pwr:
            max_observed_pwr = hp
        if hp > max_cluster_power_kw + 1e-4:
            violations.append(f"Hour {h}: cluster power {hp:.2f} kW exceeds limit {max_cluster_power_kw} kW")

        cj = len(hourly_jobs[h])
        if cj > max_observed_concurrent:
            max_observed_concurrent = cj
        if cj > max_concurrent_jobs:
            violations.append(f"Hour {h}: concurrent jobs {cj} exceeds limit {max_concurrent_jobs}")

    # Job-level completion and contiguity checks
    completed_jobs: list[str] = []
    incomplete_jobs: list[str] = []
    deadline_misses: list[str] = []
    unmet_units: float = 0.0
    unmet_energy: float = 0.0
    total_allocated_en = sum(job_alloc_energy.values())

    for jid, job_info in workload_jobs.items():
        req_proc = float(job_info["processing_requirement"])
        req_energy = float(job_info["energy_kwh"])
        act_units = job_alloc_units[jid]
        act_energy = job_alloc_energy[jid]

        # Check completion
        units_complete = abs(act_units - req_proc) <= 1e-3
        energy_complete = abs(act_energy - req_energy) <= energy_tolerance_kwh

        if units_complete and energy_complete:
            completed_jobs.append(jid)
        else:
            incomplete_jobs.append(jid)
            diff_units = max(0.0, req_proc - act_units)
            diff_energy = max(0.0, req_energy - act_energy)
            unmet_units += diff_units
            unmet_energy += diff_energy
            violations.append(
                f"Job {jid} incomplete: units {act_units:.2f}/{req_proc:.2f}, energy {act_energy:.2f}/{req_energy:.2f}"
            )

        # Check contiguity for non-preemptible jobs
        is_preemptible = bool(job_info.get("preemptible", True))
        hours = sorted(job_alloc_hours[jid])
        if not is_preemptible and len(hours) > 1:
            # Must be strictly contiguous
            for i in range(1, len(hours)):
                if hours[i] != hours[i - 1] + 1:
                    violations.append(f"Non-preemptible job {jid} allocated non-contiguously: {hours}")
                    break

        # Check deadline miss if any allocated hour >= deadline
        dead = int(job_info["deadline_offset_hours"])
        if any(h >= dead for h in hours) or (not units_complete):
            if not units_complete:
                deadline_misses.append(jid)

    is_feasible = len(violations) == 0

    return FeasibilityReport(
        is_feasible=is_feasible,
        violations=violations,
        completed_jobs=completed_jobs,
        incomplete_jobs=incomplete_jobs,
        deadline_misses=deadline_misses,
        unmet_processing_unit_hours=unmet_units,
        unmet_energy_kwh=unmet_energy,
        max_hourly_power_kw=max_observed_pwr,
        max_hourly_concurrent_jobs=max_observed_concurrent,
        total_allocated_energy_kwh=total_allocated_en,
    )
