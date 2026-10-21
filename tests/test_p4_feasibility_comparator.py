"""Tests for feasibility validator and exact small-instance hindsight comparator."""

from __future__ import annotations

import datetime
from pathlib import Path
import pytest
import pandas as pd

from heattrace.policy.comparator import ExactSmallInstanceHindsightComparator
from heattrace.policy.feasibility import validate_schedule_feasibility
from heattrace.policy.greedy import CostFirstGreedyPolicy
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
)


def test_feasibility_catches_power_and_concurrency_violations():
    workload = pd.DataFrame([
        {
            "job_id": f"job_{i}",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 10,
            "processing_requirement": 1,
            "energy_kwh": 100.0,
            "maximum_parallelism": 1,
            "preemptible": True,
        }
        for i in range(20)
    ])

    # Allocate all 20 jobs to hour 0:
    # Total power = 20 * 100 = 2000 kW > 500 kW
    # Total concurrency = 20 > 16
    allocs = [
        ScheduledJobAllocation(
            job_id=f"job_{i}",
            allocated_hour_offset=0,
            execution_power_kw=100.0,
            allocated_energy_kwh=100.0,
        )
        for i in range(20)
    ]
    sched = ScheduleResult(
        policy_name="bad_alloc",
        policy_version="1.0",
        workload_trace_id="test",
        window_duration_hours=24,
        allocations=allocs,
        is_feasible=True,
    )

    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)
    rep = validate_schedule_feasibility(sched, workload, constraints)
    assert rep.is_feasible is False
    assert any("exceeds limit 500.0 kW" in v for v in rep.violations)
    assert any("exceeds limit 16" in v for v in rep.violations)


def test_feasibility_catches_non_preemptible_gap():
    workload = pd.DataFrame([{
        "job_id": "job_np",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 10,
        "processing_requirement": 2,
        "energy_kwh": 50.0,
        "maximum_parallelism": 1,
        "preemptible": False,
    }])
    # Allocate at hour 1 and hour 3 (gap at hour 2)
    allocs = [
        ScheduledJobAllocation("job_np", 1, 25.0, 25.0),
        ScheduledJobAllocation("job_np", 3, 25.0, 25.0),
    ]
    sched = ScheduleResult("np_test", "1.0", "test", 24, allocs)
    rep = validate_schedule_feasibility(sched, workload, SchedulingConstraints(500.0, 16))
    assert rep.is_feasible is False
    assert any("allocated non-contiguously" in v for v in rep.violations)


def test_exact_comparator_finds_optimum_on_tiny_instance():
    workload = pd.DataFrame([
        {
            "workload_trace_id": "tiny_trace",
            "job_id": "j1",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 4,
            "processing_requirement": 2,
            "energy_kwh": 100.0,
            "maximum_parallelism": 1,
            "preemptible": False,
        },
        {
            "workload_trace_id": "tiny_trace",
            "job_id": "j2",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 4,
            "processing_requirement": 1,
            "energy_kwh": 50.0,
            "maximum_parallelism": 1,
            "preemptible": True,
        },
    ])

    # Prices: h0=100, h1=10, h2=20, h3=90
    realized_df = pd.DataFrame({
        "price_usd_per_mwh": [100.0, 10.0, 20.0, 90.0],
        "carbon_g_per_kwh": [100.0, 100.0, 100.0, 100.0],
    })

    comp = ExactSmallInstanceHindsightComparator(max_jobs=6, max_horizon_hours=24)
    res = comp.solve(workload, realized_df, SchedulingConstraints(500.0, 16), objective_mode="cost")

    assert res.is_supported is True
    assert res.status == "optimal"

    # For j1 (contiguous 2 hours): [1, 2] has sum of prices 30.0 -> cost = (50*10 + 50*20)/1000 = 1.5 USD
    # For j2 (1 hour): h1 (price 10) -> cost = (50*10)/1000 = 0.5 USD
    # Total optimal cost = 2.0 USD
    assert res.optimal_cost_usd == pytest.approx(2.0, abs=1e-3)


def test_exact_comparator_refuses_large_instances():
    comp = ExactSmallInstanceHindsightComparator(max_jobs=6, max_horizon_hours=24)
    big_workload = pd.DataFrame([{"job_id": f"j{i}"} for i in range(10)])
    realized_df = pd.DataFrame({"price_usd_per_mwh": [50.0] * 120, "carbon_g_per_kwh": [200.0] * 120})

    res = comp.solve(big_workload, realized_df, SchedulingConstraints(500.0, 16))
    assert res.is_supported is False
    assert res.status == "unsupported"
    assert "exceeds exact comparator limit" in res.reason
