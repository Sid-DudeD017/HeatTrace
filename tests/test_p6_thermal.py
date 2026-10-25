"""Unit and regression tests for Day 1 thermal stress sprint."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd
import pytest

from heattrace.policy.greedy import CostFirstGreedyPolicy
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
    SchedulingPolicy,
)
from heattrace.thermal.model import (
    ThermalScenario,
    build_hourly_thermal_state,
    effective_compute_capacity_kw,
    facility_energy_kwh,
    facility_power_kw,
    pue_from_temperature,
)
from heattrace.thermal.metrics import score_thermal_schedule
from heattrace.thermal.scheduler import (
    HeatAwareCapacityAdapter,
    create_temperature_unaware_schedule,
)
from heattrace.thermal.validation import (
    CANONICAL_WORKLOAD_COLUMNS,
    compute_configuration_digest,
    compute_workload_digest,
    validate_matched_inputs,
    validate_schedule_bounds,
    validate_timestamps_aligned,
    validate_window_series,
)


@pytest.fixture
def low_scenario() -> ThermalScenario:
    return ThermalScenario(
        scenario_id="low",
        base_pue=1.20,
        threshold_temperature_c=22.0,
        slope_per_c=0.010,
        max_pue=1.45,
    )


@pytest.fixture
def medium_scenario() -> ThermalScenario:
    return ThermalScenario(
        scenario_id="medium",
        base_pue=1.20,
        threshold_temperature_c=22.0,
        slope_per_c=0.020,
        max_pue=1.70,
    )


@pytest.fixture
def high_scenario() -> ThermalScenario:
    return ThermalScenario(
        scenario_id="high",
        base_pue=1.20,
        threshold_temperature_c=22.0,
        slope_per_c=0.035,
        max_pue=2.00,
    )


# =========================================================================
# A. PUE Behavior Tests
# =========================================================================

def test_pue_at_and_below_threshold(medium_scenario: ThermalScenario):
    """PUE equals base PUE at and below threshold temperature."""
    assert pue_from_temperature(22.0, medium_scenario) == 1.20
    assert pue_from_temperature(15.0, medium_scenario) == 1.20
    assert pue_from_temperature(0.0, medium_scenario) == 1.20
    assert pue_from_temperature(-10.0, medium_scenario) == 1.20


def test_pue_increases_monotonically_above_threshold(medium_scenario: ThermalScenario):
    """PUE increases monotonically above threshold."""
    temps = np.array([22.0, 25.0, 30.0, 35.0, 40.0])
    pues = pue_from_temperature(temps, medium_scenario)
    assert np.all(np.diff(pues) > 0)


def test_pue_scenario_hierarchy(
    low_scenario: ThermalScenario,
    medium_scenario: ThermalScenario,
    high_scenario: ThermalScenario,
):
    """Low <= medium <= high at the same hot temperature."""
    hot_temp = 35.0
    pue_l = pue_from_temperature(hot_temp, low_scenario)
    pue_m = pue_from_temperature(hot_temp, medium_scenario)
    pue_h = pue_from_temperature(hot_temp, high_scenario)

    assert pue_l <= pue_m <= pue_h
    # 22 + (35 - 22)*0.01 = 1.20 + 0.13 = 1.33
    assert math.isclose(pue_l, 1.33, rel_tol=1e-6)
    # 1.20 + 13*0.02 = 1.46
    assert math.isclose(pue_m, 1.46, rel_tol=1e-6)
    # 1.20 + 13*0.035 = 1.20 + 0.455 = 1.655
    assert math.isclose(pue_h, 1.655, rel_tol=1e-6)


def test_pue_never_exceeds_max_pue(high_scenario: ThermalScenario):
    """PUE caps at max_pue even under extreme temperatures."""
    pue_extreme = pue_from_temperature(100.0, high_scenario)
    assert pue_extreme == high_scenario.max_pue


def test_pue_rejects_missing_and_non_finite_temperatures(medium_scenario: ThermalScenario):
    """Reject NaN, Inf, and non-finite temperature inputs."""
    with pytest.raises(ValueError, match="finite"):
        pue_from_temperature(float("nan"), medium_scenario)
    with pytest.raises(ValueError, match="finite"):
        pue_from_temperature(float("inf"), medium_scenario)

    arr = np.array([20.0, np.nan, 30.0])
    with pytest.raises(ValueError, match="missing or non-finite"):
        pue_from_temperature(arr, medium_scenario)


def test_scenario_dataclass_validation():
    """ThermalScenario raises errors on invalid parameters, non-finite values, and bad types."""
    with pytest.raises(ValueError, match="scenario_id"):
        ThermalScenario("", 1.2, 22.0, 0.02, 1.5)
    with pytest.raises(ValueError, match="scenario_id"):
        ThermalScenario("   ", 1.2, 22.0, 0.02, 1.5)
    with pytest.raises(ValueError, match="base_pue must be >= 1.0"):
        ThermalScenario("bad", 0.9, 22.0, 0.02, 1.5)
    with pytest.raises(ValueError, match="max_pue .* must be >= base_pue"):
        ThermalScenario("bad", 1.5, 22.0, 0.02, 1.2)
    with pytest.raises(ValueError, match="slope_per_c must be >= 0.0"):
        ThermalScenario("bad", 1.2, 22.0, -0.01, 1.5)

    # NaN and ±Inf rejection
    for val in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(ValueError, match="finite"):
            ThermalScenario("sc", val, 22.0, 0.02, 1.5)
        with pytest.raises(ValueError, match="finite"):
            ThermalScenario("sc", 1.2, val, 0.02, 1.5)
        with pytest.raises(ValueError, match="finite"):
            ThermalScenario("sc", 1.2, 22.0, val, 1.5)
        with pytest.raises(ValueError, match="finite"):
            ThermalScenario("sc", 1.2, 22.0, 0.02, val)

    # Boolean rejection
    with pytest.raises(TypeError, match="boolean"):
        ThermalScenario("sc", True, 22.0, 0.02, 1.5)
    with pytest.raises(TypeError, match="boolean"):
        ThermalScenario("sc", 1.2, 22.0, False, 1.5)


# =========================================================================
# B. Energy and Capacity Tests
# =========================================================================

def test_energy_increases_with_temperature(medium_scenario: ThermalScenario):
    """Identical compute energy consumes more facility energy at higher temperature."""
    compute_en = 100.0  # kWh
    pue_cool = pue_from_temperature(20.0, medium_scenario)  # 1.20
    pue_hot = pue_from_temperature(35.0, medium_scenario)   # 1.46

    fac_cool = facility_energy_kwh(compute_en, pue_cool)
    fac_hot = facility_energy_kwh(compute_en, pue_hot)

    assert fac_hot > fac_cool
    assert math.isclose(fac_cool, 120.0)
    assert math.isclose(fac_hot, 146.0)


def test_cooling_energy_equals_facility_minus_compute(medium_scenario: ThermalScenario):
    """Cooling energy equals facility energy minus compute energy."""
    c_en = 250.0
    pue = pue_from_temperature(30.0, medium_scenario)
    f_en = facility_energy_kwh(c_en, pue)
    cooling_en = f_en - c_en
    assert math.isclose(cooling_en, c_en * (pue - 1.0))


def test_effective_compute_capacity_decreases_as_pue_rises(medium_scenario: ThermalScenario):
    """Effective compute capacity decreases as PUE rises."""
    nominal_cap = 500.0
    fac_cap = nominal_cap * medium_scenario.base_pue  # 600 kW

    pue_base = 1.20
    pue_hot = 1.50

    eff_base = effective_compute_capacity_kw(fac_cap, pue_base)
    eff_hot = effective_compute_capacity_kw(fac_cap, pue_hot)

    # At base PUE, effective compute capacity equals nominal compute capacity
    assert math.isclose(eff_base, nominal_cap)
    assert eff_hot < eff_base
    assert math.isclose(eff_hot, 600.0 / 1.50)  # 400 kW


def test_power_and_capacity_validation():
    """Reject non-positive power limits and negative inputs."""
    with pytest.raises(ValueError, match="positive"):
        effective_compute_capacity_kw(0.0, 1.2)
    with pytest.raises(ValueError, match="positive"):
        effective_compute_capacity_kw(-100.0, 1.2)
    with pytest.raises(ValueError, match="pue must be >= 1.0"):
        effective_compute_capacity_kw(500.0, 0.8)
    with pytest.raises(ValueError, match="non-negative"):
        facility_power_kw(-10.0, 1.2)


def test_build_hourly_thermal_state_preserves_order_and_calculates(medium_scenario: ThermalScenario):
    """build_hourly_thermal_state generates expected DataFrame columns and values."""
    ts = pd.date_range("2024-07-02", periods=5, freq="h", tz="UTC")
    df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [20.0, 22.0, 25.0, 30.0, 35.0],
    })
    nominal_compute_cap_kw = 500.0

    state = build_hourly_thermal_state(df, medium_scenario, nominal_compute_cap_kw)
    assert len(state) == 5
    assert list(state.columns) == [
        "timestamp_utc",
        "temperature_c",
        "thermal_scenario_id",
        "pue",
        "nominal_compute_capacity_kw",
        "facility_power_cap_kw",
        "effective_compute_capacity_kw",
    ]
    # Check facility cap = nominal * base_pue = 600.0
    assert (state["facility_power_cap_kw"] == 600.0).all()
    # At hour 0 (20.0 C <= 22.0 C), pue = 1.20, eff_cap = 500.0
    assert state.loc[0, "pue"] == 1.20
    assert state.loc[0, "effective_compute_capacity_kw"] == 500.0
    # At hour 4 (35.0 C), pue = 1.46, eff_cap = 600 / 1.46
    assert math.isclose(state.loc[4, "pue"], 1.46)
    assert math.isclose(state.loc[4, "effective_compute_capacity_kw"], 600.0 / 1.46)


# =========================================================================
# C. Violation Scoring Tests
# =========================================================================

def test_thermal_scoring_zero_violations_when_under_capacity(medium_scenario: ThermalScenario):
    """A schedule below effective capacity has zero violations and is thermally feasible."""
    ts = pd.date_range("2024-07-02", periods=3, freq="h", tz="UTC")
    realized_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [30.0, 30.0, 30.0],
        "price_usd_per_mwh": [50.0, 50.0, 50.0],
        "carbon_g_per_kwh": [200.0, 200.0, 200.0],
    })
    thermal_state = build_hourly_thermal_state(realized_df, medium_scenario, nominal_compute_cap_kw=500.0)
    # Effective capacity is ~441.17 kW

    # Schedule allocating 300 kW per hour
    allocs = [
        ScheduledJobAllocation(job_id="j1", allocated_hour_offset=0, execution_power_kw=300.0, allocated_energy_kwh=300.0),
        ScheduledJobAllocation(job_id="j1", allocated_hour_offset=1, execution_power_kw=300.0, allocated_energy_kwh=300.0),
        ScheduledJobAllocation(job_id="j1", allocated_hour_offset=2, execution_power_kw=300.0, allocated_energy_kwh=300.0),
    ]
    from heattrace.policy.interfaces import ScheduleResult
    sched = ScheduleResult(
        policy_name="test_pol",
        policy_version="1.0",
        workload_trace_id="trace_test",
        window_duration_hours=3,
        allocations=allocs,
        is_feasible=True,
    )
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_test",
        "job_id": "j1",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 3,
        "processing_requirement": 3,
        "energy_kwh": 900.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    hourly_df, summary = score_thermal_schedule(sched, workload_df, realized_df, thermal_state)

    assert summary["facility_power_violation_hours"] == 0
    assert summary["total_facility_power_excess_kwh"] == 0.0
    assert summary["thermally_feasible"] is True


def test_thermal_scoring_reports_correct_violations_and_excess(medium_scenario: ThermalScenario):
    """A schedule above effective capacity reports violations and excess without mutating allocations."""
    ts = pd.date_range("2024-07-02", periods=2, freq="h", tz="UTC")
    realized_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [30.0, 20.0],  # hr 0: pue=1.36, eff_cap=600/1.36=441.176; hr 1: pue=1.20, eff_cap=500
        "price_usd_per_mwh": [100.0, 100.0],
        "carbon_g_per_kwh": [300.0, 300.0],
    })
    thermal_state = build_hourly_thermal_state(realized_df, medium_scenario, nominal_compute_cap_kw=500.0)

    # Allocate 500 kW in hour 0 (exceeds effective cap 441.176) and 400 kW in hour 1
    allocs = [
        ScheduledJobAllocation(job_id="j1", allocated_hour_offset=0, execution_power_kw=500.0, allocated_energy_kwh=500.0),
        ScheduledJobAllocation(job_id="j1", allocated_hour_offset=1, execution_power_kw=400.0, allocated_energy_kwh=400.0),
    ]
    from heattrace.policy.interfaces import ScheduleResult
    sched = ScheduleResult(
        policy_name="test_pol",
        policy_version="1.0",
        workload_trace_id="trace_test",
        window_duration_hours=2,
        allocations=allocs,
        is_feasible=True,
    )
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_test",
        "job_id": "j1",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 2,
        "processing_requirement": 2,
        "energy_kwh": 900.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    hourly_df, summary = score_thermal_schedule(sched, workload_df, realized_df, thermal_state)

    # In hour 0: compute_power = 500 kW, pue = 1.36 -> fac_power = 680 kW. Facility cap = 600 kW.
    # Excess facility power = 80 kW.
    assert summary["facility_power_violation_hours"] == 1
    assert math.isclose(summary["maximum_facility_power_excess_kw"], 80.0, rel_tol=1e-5)
    assert math.isclose(summary["total_facility_power_excess_kwh"], 80.0, rel_tol=1e-5)
    assert summary["thermally_feasible"] is False

    # Original allocations must remain unchanged (not curtailed)
    assert hourly_df.loc[0, "hourly_compute_power_kw"] == 500.0
    assert hourly_df.loc[1, "hourly_compute_power_kw"] == 400.0


def test_violation_tolerance_behavior(medium_scenario: ThermalScenario):
    """Values inside numerical tolerance do not trigger a violation."""
    ts = pd.date_range("2024-07-02", periods=1, freq="h", tz="UTC")
    realized_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [22.0],  # pue = 1.20, fac_cap = 600
        "price_usd_per_mwh": [50.0],
        "carbon_g_per_kwh": [200.0],
    })
    thermal_state = build_hourly_thermal_state(realized_df, medium_scenario, nominal_compute_cap_kw=500.0)

    # Compute power is nominal 500 + 1e-7 kW (facility power = 600.00000012, excess = 1.2e-7 <= 1e-6 tolerance)
    tiny_excess = 1e-7
    allocs = [
        ScheduledJobAllocation(job_id="j1", allocated_hour_offset=0, execution_power_kw=500.0 + tiny_excess, allocated_energy_kwh=500.0),
    ]
    sched = ScheduleResult(
        policy_name="test_pol",
        policy_version="1.0",
        workload_trace_id="trace_test",
        window_duration_hours=1,
        allocations=allocs,
        is_feasible=True,
    )
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_test",
        "job_id": "j1",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 1,
        "processing_requirement": 1,
        "energy_kwh": 500.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    _, summary = score_thermal_schedule(
        sched, workload_df, realized_df, thermal_state, violation_tolerance_kw=1e-6
    )
    assert summary["facility_power_violation_hours"] == 0
    assert summary["thermally_feasible"] is True


# =========================================================================
# D. Scheduler Behavior Tests
# =========================================================================

def test_unaware_policy_produces_identical_schedule():
    """Temperature-unaware scheduling produces identical schedule to base policy."""
    base_policy = CostFirstGreedyPolicy()
    workload = pd.DataFrame([
        {
            "job_id": "job_01",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 10,
            "processing_requirement": 3,
            "energy_kwh": 300.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
            "workload_trace_id": "trace_test",
        }
    ])
    ts = pd.date_range("2024-07-02", periods=10, freq="h", tz="UTC")
    pts = [
        ForecastPoint(
            timestamp_utc=ts[h],
            horizon_hours=h,
            predicted_price_usd_per_mwh=float(100 - h * 5),
            predicted_carbon_g_per_kwh=200.0,
        )
        for h in range(10)
    ]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    base_res = base_policy.schedule(workload, fc, constraints)
    unaware_res = create_temperature_unaware_schedule(base_policy, workload, fc, constraints)

    assert [a.allocated_hour_offset for a in base_res.allocations] == [
        a.allocated_hour_offset for a in unaware_res.allocations
    ]
    assert base_res.policy_name == unaware_res.policy_name


def test_heat_aware_adapter_respects_effective_capacity():
    """HeatAwareCapacityAdapter respects hourly effective capacity and moves work deterministically."""
    base_policy = CostFirstGreedyPolicy()
    workload = pd.DataFrame([
        {
            "job_id": "job_01",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 5,
            "processing_requirement": 3,
            "energy_kwh": 300.0,  # 100 kW per hour
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
            "workload_trace_id": "trace_test",
        }
    ])
    ts = pd.date_range("2024-07-02", periods=5, freq="h", tz="UTC")
    # Base policy will want hours 0, 1, 2 if prices are lowest there
    pts = [
        ForecastPoint(
            timestamp_utc=ts[h],
            horizon_hours=h,
            predicted_price_usd_per_mwh=float(10 * h),  # cheapest at 0, 1, 2
            predicted_carbon_g_per_kwh=200.0,
        )
        for h in range(5)
    ]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    # Restrict hour 0 effective capacity to 50 kW (cannot hold 100 kW job)
    eff_cap = np.array([50.0, 500.0, 500.0, 500.0, 500.0])

    adapter = HeatAwareCapacityAdapter(base_policy, eff_cap)
    res = adapter.schedule(workload, fc, constraints)

    # Job should not be placed in hour 0, but successfully placed in later hours
    assigned_hours = [a.allocated_hour_offset for a in res.allocations]
    assert 0 not in assigned_hours
    assert len(assigned_hours) == 3
    assert all(0 <= h < 5 for h in assigned_hours)
    assert res.is_feasible is True
    assert adapter.policy_name == "cost_first_heat_aware_adapter"


def test_heat_aware_adapter_reports_infeasible_when_unplaceable():
    """Adapter marks work as unmet if effective capacity cannot accommodate it before deadline."""
    base_policy = CostFirstGreedyPolicy()
    workload = pd.DataFrame([
        {
            "job_id": "job_01",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 3,
            "processing_requirement": 3,
            "energy_kwh": 300.0,  # 100 kW
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
            "workload_trace_id": "trace_test",
        }
    ])
    ts = pd.date_range("2024-07-02", periods=3, freq="h", tz="UTC")
    pts = [
        ForecastPoint(timestamp_utc=ts[h], horizon_hours=h, predicted_price_usd_per_mwh=10.0, predicted_carbon_g_per_kwh=200.0)
        for h in range(3)
    ]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    # Restrict all 3 hours to 50 kW (job requires 100 kW)
    eff_cap = np.array([50.0, 50.0, 50.0])

    adapter = HeatAwareCapacityAdapter(base_policy, eff_cap)
    res = adapter.schedule(workload, fc, constraints)

    assert res.is_feasible is False
    assert "job_01" in res.unmet_deadlines
    assert len(res.allocations) == 0


def test_heat_aware_adapter_concurrency_and_determinism():
    """Adapter respects concurrency limits and runs deterministically."""
    base_policy = CostFirstGreedyPolicy()
    # 3 jobs of 50 kW each
    workload = pd.DataFrame([
        {
            "job_id": f"job_{i}",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 4,
            "processing_requirement": 2,
            "energy_kwh": 100.0,  # 50 kW
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
            "workload_trace_id": "trace_test",
        }
        for i in range(3)
    ])
    ts = pd.date_range("2024-07-02", periods=4, freq="h", tz="UTC")
    pts = [
        ForecastPoint(timestamp_utc=ts[h], horizon_hours=h, predicted_price_usd_per_mwh=10.0, predicted_carbon_g_per_kwh=200.0)
        for h in range(4)
    ]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    # Concurrency limit = 2
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=2)
    eff_cap = np.array([500.0, 500.0, 500.0, 500.0])

    adapter = HeatAwareCapacityAdapter(base_policy, eff_cap)
    res1 = adapter.schedule(workload, fc, constraints)
    res2 = adapter.schedule(workload, fc, constraints)

    # Determinism
    assert [(a.job_id, a.allocated_hour_offset) for a in res1.allocations] == [
        (a.job_id, a.allocated_hour_offset) for a in res2.allocations
    ]

    # Verify no hour has > 2 concurrent jobs
    from collections import Counter
    hr_counts = Counter(a.allocated_hour_offset for a in res1.allocations)
    assert all(c <= 2 for c in hr_counts.values())


# =========================================================================
# E. Matched-Input and Boundary Validation Tests
# =========================================================================

def test_workload_digest_determinism_and_sensitivity():
    """Workload digest is deterministic, row-order invariant, and sensitive to every scheduling field."""
    base_job = {
        "workload_trace_id": "trace_std",
        "job_id": "job_01",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 24,
        "processing_requirement": 4,
        "energy_kwh": 200.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }
    second_job = {
        "workload_trace_id": "trace_std",
        "job_id": "job_02",
        "arrival_offset_hours": 5,
        "deadline_offset_hours": 30,
        "processing_requirement": 2,
        "energy_kwh": 100.0,
        "maximum_parallelism": 2,
        "priority": 2,
        "preemptible": False,
    }
    workload = pd.DataFrame([base_job, second_job])
    d1 = compute_workload_digest(workload)

    # 1. Row order invariance
    d2 = compute_workload_digest(workload.iloc[::-1])
    assert d1 == d2

    # 2. Sensitivity to every single field
    fields_to_mutate = [
        ("workload_trace_id", "trace_other"),
        ("job_id", "job_mutated"),
        ("arrival_offset_hours", 1),
        ("deadline_offset_hours", 25),
        ("processing_requirement", 5),
        ("energy_kwh", 200.5),
        ("maximum_parallelism", 4),
        ("priority", 3),
        ("preemptible", False),
    ]
    for field, new_val in fields_to_mutate:
        mut_df = workload.copy()
        mut_df.loc[0, field] = new_val
        d_mut = compute_workload_digest(mut_df)
        assert d_mut != d1, f"Mutation to {field} did not change workload digest"

    # 3. Missing required column raises ValueError
    for col in CANONICAL_WORKLOAD_COLUMNS:
        drop_df = workload.drop(columns=[col])
        with pytest.raises(ValueError, match="missing required canonical column"):
            compute_workload_digest(drop_df)


def test_window_series_validation_failures():
    """Window validation strictly fails on gaps, non-monotonicity, or missing temperature."""
    ts = pd.date_range("2024-07-02", periods=120, freq="h", tz="UTC")
    valid_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [25.0] * 120,
    })
    # Valid window passes
    validate_window_series(valid_df, expected_horizon_hours=120)

    # Wrong row count
    with pytest.raises(ValueError, match="Expected 120 rows"):
        validate_window_series(valid_df.iloc[:100], expected_horizon_hours=120)

    # Non-contiguous hour (shift row 10 and all subsequent rows by 2 hours)
    gap_df = valid_df.copy()
    gap_df.loc[10:, "timestamp_utc"] = gap_df.loc[10:, "timestamp_utc"] + pd.Timedelta(hours=2)
    with pytest.raises(ValueError, match="Non-contiguous hourly interval"):
        validate_window_series(gap_df, expected_horizon_hours=120)

    # Missing temperature
    nan_df = valid_df.copy()
    nan_df.loc[5, "temperature_c"] = np.nan
    with pytest.raises(ValueError, match="missing or non-finite"):
        validate_window_series(nan_df, expected_horizon_hours=120)


def test_schedule_bounds_validation():
    """validate_schedule_bounds detects out-of-horizon, early arrival, or late deadline."""
    workload = pd.DataFrame([{
        "job_id": "j1",
        "arrival_offset_hours": 2,
        "deadline_offset_hours": 6,
        "processing_requirement": 2,
        "energy_kwh": 100.0,
    }])
    from heattrace.policy.interfaces import ScheduleResult

    # Valid schedule
    valid_sched = ScheduleResult(
        "test", "1.0", "trace", 10,
        [
            ScheduledJobAllocation("j1", 2, 50.0, 50.0),
            ScheduledJobAllocation("j1", 3, 50.0, 50.0),
        ],
        is_feasible=True,
    )
    validate_schedule_bounds(valid_sched, workload, horizon_hours=10)

    # Early allocation before arrival
    bad_sched1 = ScheduleResult(
        "test", "1.0", "trace", 10,
        [ScheduledJobAllocation("j1", 1, 50.0, 50.0)],
        is_feasible=True,
    )
    with pytest.raises(ValueError, match="before arrival"):
        validate_schedule_bounds(bad_sched1, workload, horizon_hours=10)

    # Late allocation at/after deadline
    bad_sched2 = ScheduleResult(
        "test", "1.0", "trace", 10,
        [ScheduledJobAllocation("j1", 6, 50.0, 50.0)],
        is_feasible=True,
    )
    with pytest.raises(ValueError, match="at/after deadline"):
        validate_schedule_bounds(bad_sched2, workload, horizon_hours=10)


# =========================================================================
# F. Regression Control Tests
# =========================================================================

def test_effective_capacity_vector_validation(medium_scenario: ThermalScenario):
    """HeatAwareCapacityAdapter validates effective capacity vector and tolerance strictly."""
    base_policy = CostFirstGreedyPolicy()

    # Empty vector
    with pytest.raises(ValueError, match="empty"):
        HeatAwareCapacityAdapter(base_policy, np.array([]))

    # NaN / Inf in vector
    with pytest.raises(ValueError, match="NaN or infinity"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, np.nan, 400.0]))
    with pytest.raises(ValueError, match="NaN or infinity"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, np.inf, 400.0]))

    # Zero or negative capacity
    with pytest.raises(ValueError, match="strictly positive"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, 0.0, 400.0]))
    with pytest.raises(ValueError, match="strictly positive"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, -50.0, 400.0]))

    # Tolerance validation
    with pytest.raises(ValueError, match="finite and non-negative"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, 400.0]), tolerance_kw=-1e-5)
    with pytest.raises(ValueError, match="finite and non-negative"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, 400.0]), tolerance_kw=float("nan"))
    with pytest.raises(TypeError, match="numeric float"):
        HeatAwareCapacityAdapter(base_policy, np.array([500.0, 400.0]), tolerance_kw=True)


# =========================================================================
# G. Timestamp Alignment and Scorer Enforcement Tests
# =========================================================================

def test_timestamp_alignment_validation(medium_scenario: ThermalScenario):
    """Scorer fails loudly on timestamp mismatches: shift, reorder, duplicates, naive, length."""
    ts1 = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    df_real = pd.DataFrame({
        "timestamp_utc": ts1,
        "price_usd_per_mwh": [50.0] * 5,
        "carbon_g_per_kwh": [200.0] * 5,
    })
    df_state = pd.DataFrame({
        "timestamp_utc": ts1,
        "thermal_scenario_id": ["medium"] * 5,
        "pue": [1.2] * 5,
        "facility_power_cap_kw": [600.0] * 5,
        "effective_compute_capacity_kw": [500.0] * 5,
    })

    # Base valid passes
    validate_timestamps_aligned(df_real, df_state)

    # 1. Shifted timestamp
    df_shifted = df_state.copy()
    df_shifted["timestamp_utc"] = pd.date_range("2024-07-02 01:00", periods=5, freq="h", tz="UTC")
    with pytest.raises(ValueError, match="Timestamp mismatch"):
        validate_timestamps_aligned(df_real, df_shifted)

    # 2. Reordered timestamp
    df_reordered = df_state.iloc[[1, 0, 2, 3, 4]].copy()
    with pytest.raises(ValueError, match="strictly monotonically increasing"):
        validate_timestamps_aligned(df_real, df_reordered)

    # 3. Duplicate timestamp
    df_dup = df_state.copy()
    df_dup.loc[1, "timestamp_utc"] = df_dup.loc[0, "timestamp_utc"]
    with pytest.raises(ValueError, match="duplicate timestamps"):
        validate_timestamps_aligned(df_real, df_dup)

    # 4. Naive timestamp
    df_naive = df_state.copy()
    df_naive["timestamp_utc"] = df_naive["timestamp_utc"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="must be timezone-aware UTC"):
        validate_timestamps_aligned(df_real, df_naive)

    # 5. Unequal length
    with pytest.raises(ValueError, match="Row count mismatch"):
        validate_timestamps_aligned(df_real, df_state.iloc[:4])


def test_scorer_enforces_arrival_deadline_and_horizon():
    """score_thermal_schedule detects and rejects early, late, out-of-horizon, unknown, and duplicate allocations."""
    ts = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    realized_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [20.0] * 5,
        "price_usd_per_mwh": [50.0] * 5,
        "carbon_g_per_kwh": [200.0] * 5,
    })
    thermal_state = pd.DataFrame({
        "timestamp_utc": ts,
        "thermal_scenario_id": ["medium"] * 5,
        "pue": [1.2] * 5,
        "facility_power_cap_kw": [600.0] * 5,
        "effective_compute_capacity_kw": [500.0] * 5,
    })
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_test",
        "job_id": "j1",
        "arrival_offset_hours": 1,
        "deadline_offset_hours": 4,  # valid hours: 1, 2, 3
        "processing_requirement": 2,
        "energy_kwh": 200.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    # Valid on-time schedule
    valid_sched = ScheduleResult(
        "pol", "1.0", "trace", 5,
        [
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
            ScheduledJobAllocation("j1", 2, 100.0, 100.0),
        ],
        is_feasible=True,
    )
    _, sum_valid = score_thermal_schedule(valid_sched, workload_df, realized_df, thermal_state)
    assert sum_valid["thermally_feasible"] is True
    assert sum_valid["invalid_allocation_count"] == 0

    # 1. Allocation before arrival (hour 0 < arrival 1)
    sched_early = ScheduleResult(
        "pol", "1.0", "trace", 5,
        [
            ScheduledJobAllocation("j1", 0, 100.0, 100.0),
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
        ],
        is_feasible=True,
    )
    _, sum_early = score_thermal_schedule(sched_early, workload_df, realized_df, thermal_state)
    assert sum_early["thermally_feasible"] is False
    assert sum_early["invalid_allocation_count"] >= 1
    assert "j1" in sum_early["invalid_allocation_jobs"]

    # 2. Allocation after deadline (hour 4 >= deadline 4)
    # Even if total energy matches 200 kWh, delivering after deadline must NOT be feasible!
    sched_late = ScheduleResult(
        "pol", "1.0", "trace", 5,
        [
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
            ScheduledJobAllocation("j1", 4, 100.0, 100.0),
        ],
        is_feasible=True,
    )
    _, sum_late = score_thermal_schedule(sched_late, workload_df, realized_df, thermal_state)
    assert sum_late["thermally_feasible"] is False
    assert sum_late["deadline_misses_count"] >= 1
    assert sum_late["invalid_allocation_count"] >= 1

    # 3. Allocation outside horizon (hour 5 >= horizon 5)
    sched_outside = ScheduleResult(
        "pol", "1.0", "trace", 5,
        [
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
            ScheduledJobAllocation("j1", 5, 100.0, 100.0),
        ],
        is_feasible=True,
    )
    _, sum_out = score_thermal_schedule(sched_outside, workload_df, realized_df, thermal_state)
    assert sum_out["thermally_feasible"] is False
    assert sum_out["invalid_allocation_count"] >= 1

    # 4. Unknown job ID
    sched_unknown = ScheduleResult(
        "pol", "1.0", "trace", 5,
        [ScheduledJobAllocation("unknown_job", 1, 100.0, 100.0)],
        is_feasible=True,
    )
    _, sum_unk = score_thermal_schedule(sched_unknown, workload_df, realized_df, thermal_state)
    assert sum_unk["thermally_feasible"] is False
    assert sum_unk["invalid_allocation_count"] >= 1

    # 5. Duplicate job/hour allocation
    sched_dup = ScheduleResult(
        "pol", "1.0", "trace", 5,
        [
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
        ],
        is_feasible=True,
    )
    _, sum_dup = score_thermal_schedule(sched_dup, workload_df, realized_df, thermal_state)
    assert sum_dup["thermally_feasible"] is False
    assert sum_dup["invalid_allocation_count"] >= 1


# =========================================================================
# H. Positive-Control Implementation Validation Fixture
# =========================================================================

def test_positive_control_unaware_failure_and_heat_aware_recovery():
    """Positive Control Check: Under controlled thermal stress, unaware schedule violates

    facility cap, while heat_aware_capacity_adapter moves work into later available hours,
    satisfies all deadlines and capacity limits, and completes the workload.

    DISCLAIMER: This is a synthetic implementation validation check, not a scientific finding.
    """
    ts = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    # Hours 0, 1 are hot (35 C -> PUE = 1.46 under medium scenario)
    # Hours 2, 3, 4 are cool (20 C -> PUE = 1.20)
    realized_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [35.0, 35.0, 20.0, 20.0, 20.0],
        "price_usd_per_mwh": [10.0, 20.0, 80.0, 90.0, 100.0],  # cheapest at 0, 1
        "carbon_g_per_kwh": [200.0] * 5,
    })
    scenario = ThermalScenario("medium", 1.20, 22.0, 0.02, 1.70)
    nominal_cap_kw = 500.0
    fac_cap_kw = 600.0

    state = build_hourly_thermal_state(realized_df, scenario, nominal_compute_cap_kw=nominal_cap_kw)
    eff_cap = state["effective_compute_capacity_kw"].to_numpy()
    # At hr 0, 1: eff_cap = 600 / 1.46 = 410.95 kW
    # At hr 2, 3, 4: eff_cap = 600 / 1.20 = 500.0 kW

    # Workload requiring 450 kW in hour 0 (fits nominal 500 kW, but exceeds thermally-derated 410.95 kW)
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_pos_control",
        "job_id": "j_heavy",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 5,
        "processing_requirement": 1,
        "energy_kwh": 450.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    pts = [
        ForecastPoint(ts[h], h, float(realized_df["price_usd_per_mwh"].iloc[h]), 200.0)
        for h in range(5)
    ]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=nominal_cap_kw, max_concurrent_jobs=16)

    base_policy = CostFirstGreedyPolicy()

    # 1. Unaware schedule: schedules at hour 0 (cheapest price = $10/MWh)
    unaware_sched = create_temperature_unaware_schedule(base_policy, workload_df, fc, constraints)
    assert unaware_sched.allocations[0].allocated_hour_offset == 0

    # Score unaware schedule against thermal state
    _, unaw_summary = score_thermal_schedule(unaware_sched, workload_df, realized_df, state)
    # Facility power = 450 * 1.46 = 657 kW > 600 kW facility cap!
    assert unaw_summary["facility_power_violation_hours"] == 1
    assert unaw_summary["maximum_facility_power_excess_kw"] > 50.0
    assert unaw_summary["thermally_feasible"] is False

    # 2. Heat-aware capacity adapter: detects overflow at hour 0, deterministically moves job
    # to a later hour where capacity fits (hour 2, where eff_cap = 500 kW >= 450 kW)
    adapter = HeatAwareCapacityAdapter(base_policy, eff_cap)
    aware_sched = adapter.schedule(workload_df, fc, constraints)
    assert aware_sched.is_feasible is True
    assert aware_sched.allocations[0].allocated_hour_offset == 2  # moved to feasible hour

    # Score aware schedule against thermal state
    _, awar_summary = score_thermal_schedule(aware_sched, workload_df, realized_df, state)
    assert awar_summary["facility_power_violation_hours"] == 0
    assert awar_summary["total_facility_power_excess_kwh"] == 0.0
    assert awar_summary["thermally_feasible"] is True
    assert awar_summary["unfinished_jobs_count"] == 0
    assert awar_summary["deadline_misses_count"] == 0

    # Validate identical workload digests
    assert compute_workload_digest(workload_df) == compute_workload_digest(workload_df)


# =========================================================================
# I. Adversarial Correctness and Bounds Hardening Tests (Phase 0)
# =========================================================================

def _sample_fixtures():
    """Helper to generate baseline valid inputs for scoring and scheduler tests."""
    ts = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    realized_df = pd.DataFrame({
        "timestamp_utc": ts,
        "temperature_c": [25.0, 30.0, 20.0, 22.0, 21.0],
        "price_usd_per_mwh": [40.0, 50.0, 35.0, 45.0, 30.0],
        "carbon_g_per_kwh": [250.0, 280.0, 220.0, 240.0, 210.0],
    })
    scenario = ThermalScenario("medium", 1.20, 22.0, 0.02, 1.70)
    nominal_cap_kw = 500.0
    state = build_hourly_thermal_state(realized_df, scenario, nominal_compute_cap_kw=nominal_cap_kw)

    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_test",
        "job_id": "j1",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 5,
        "processing_requirement": 2,
        "energy_kwh": 200.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    valid_schedule = ScheduleResult(
        policy_name="test_pol",
        policy_version="1.0",
        workload_trace_id="trace_test",
        window_duration_hours=5,
        allocations=[
            ScheduledJobAllocation("j1", 0, 100.0, 100.0),
            ScheduledJobAllocation("j1", 1, 100.0, 100.0),
        ],
        unmet_deadlines=[],
        is_feasible=True,
    )
    return realized_df, state, workload_df, valid_schedule


def test_scorer_rejects_non_finite_and_invalid_pue():
    """Scorer rejects NaN, +/-Inf, and PUE < 1.0."""
    realized_df, state, workload_df, sched = _sample_fixtures()

    for bad_val in [float("nan"), float("inf"), float("-inf")]:
        bad_state = state.copy()
        bad_state.loc[0, "pue"] = bad_val
        with pytest.raises(ValueError, match="thermal_state_df\\['pue'\\] contains non-finite"):
            score_thermal_schedule(sched, workload_df, realized_df, bad_state)

    bad_state = state.copy()
    bad_state.loc[0, "pue"] = 0.95
    with pytest.raises(ValueError, match="thermal_state_df\\['pue'\\] contains invalid values"):
        score_thermal_schedule(sched, workload_df, realized_df, bad_state)


def test_scorer_rejects_non_finite_and_non_positive_effective_capacity():
    """Scorer rejects NaN, +/-Inf, zero, and negative effective compute capacity."""
    realized_df, state, workload_df, sched = _sample_fixtures()

    for bad_val in [float("nan"), float("inf"), float("-inf")]:
        bad_state = state.copy()
        bad_state.loc[1, "effective_compute_capacity_kw"] = bad_val
        with pytest.raises(ValueError, match="thermal_state_df\\['effective_compute_capacity_kw'\\] contains non-finite"):
            score_thermal_schedule(sched, workload_df, realized_df, bad_state)

    for bad_val in [0.0, -10.0]:
        bad_state = state.copy()
        bad_state.loc[1, "effective_compute_capacity_kw"] = bad_val
        with pytest.raises(ValueError, match="thermal_state_df\\['effective_compute_capacity_kw'\\] must be strictly positive"):
            score_thermal_schedule(sched, workload_df, realized_df, bad_state)


def test_scorer_rejects_non_finite_and_non_positive_facility_cap():
    """Scorer rejects NaN, +/-Inf, zero, and negative facility power cap."""
    realized_df, state, workload_df, sched = _sample_fixtures()

    for bad_val in [float("nan"), float("inf"), float("-inf")]:
        bad_state = state.copy()
        bad_state.loc[2, "facility_power_cap_kw"] = bad_val
        with pytest.raises(ValueError, match="thermal_state_df\\['facility_power_cap_kw'\\] contains non-finite"):
            score_thermal_schedule(sched, workload_df, realized_df, bad_state)

    for bad_val in [0.0, -500.0]:
        bad_state = state.copy()
        bad_state.loc[2, "facility_power_cap_kw"] = bad_val
        with pytest.raises(ValueError, match="thermal_state_df\\['facility_power_cap_kw'\\] must be strictly positive"):
            score_thermal_schedule(sched, workload_df, realized_df, bad_state)


def test_scorer_rejects_non_finite_price_and_carbon():
    """Scorer rejects NaN or +/-Inf in price or carbon intensity."""
    realized_df, state, workload_df, sched = _sample_fixtures()

    for bad_val in [float("nan"), float("inf"), float("-inf")]:
        bad_r = realized_df.copy()
        bad_r.loc[0, "price_usd_per_mwh"] = bad_val
        with pytest.raises(ValueError, match="realized_df\\['price_usd_per_mwh'\\] contains non-finite"):
            score_thermal_schedule(sched, workload_df, bad_r, state)

        bad_r = realized_df.copy()
        bad_r.loc[0, "carbon_g_per_kwh"] = bad_val
        with pytest.raises(ValueError, match="realized_df\\['carbon_g_per_kwh'\\] contains non-finite"):
            score_thermal_schedule(sched, workload_df, bad_r, state)


def test_scorer_rejects_invalid_violation_tolerance():
    """Scorer rejects boolean, non-numeric, negative, or non-finite violation_tolerance_kw."""
    realized_df, state, workload_df, sched = _sample_fixtures()

    with pytest.raises(TypeError, match="violation_tolerance_kw must be a non-boolean numeric float"):
        score_thermal_schedule(sched, workload_df, realized_df, state, violation_tolerance_kw=True)

    with pytest.raises(TypeError, match="violation_tolerance_kw must be a non-boolean numeric float"):
        score_thermal_schedule(sched, workload_df, realized_df, state, violation_tolerance_kw="invalid")

    with pytest.raises(ValueError, match="violation_tolerance_kw must be finite and non-negative"):
        score_thermal_schedule(sched, workload_df, realized_df, state, violation_tolerance_kw=-1e-5)

    with pytest.raises(ValueError, match="violation_tolerance_kw must be finite and non-negative"):
        score_thermal_schedule(sched, workload_df, realized_df, state, violation_tolerance_kw=float("nan"))


def test_scorer_rejects_invalid_allocation_power_energy_offset():
    """Scorer rejects boolean, non-integer offset, negative or non-finite power/energy."""
    realized_df, state, workload_df, _ = _sample_fixtures()

    # Boolean offset
    bad_sched = ScheduleResult("p", "1.0", "t", 5, [ScheduledJobAllocation("j1", True, 100.0, 100.0)], is_feasible=True)
    with pytest.raises(TypeError, match="allocated_hour_offset must be an integer"):
        score_thermal_schedule(bad_sched, workload_df, realized_df, state)

    # Float offset
    bad_sched = ScheduleResult("p", "1.0", "t", 5, [ScheduledJobAllocation("j1", 1.5, 100.0, 100.0)], is_feasible=True)
    with pytest.raises(TypeError, match="allocated_hour_offset must be an integer"):
        score_thermal_schedule(bad_sched, workload_df, realized_df, state)

    # Negative power
    bad_sched = ScheduleResult("p", "1.0", "t", 5, [ScheduledJobAllocation("j1", 0, -50.0, 100.0)], is_feasible=True)
    with pytest.raises(ValueError, match="execution_power_kw must be finite and non-negative"):
        score_thermal_schedule(bad_sched, workload_df, realized_df, state)

    # NaN energy
    bad_sched = ScheduleResult("p", "1.0", "t", 5, [ScheduledJobAllocation("j1", 0, 100.0, float("nan"))], is_feasible=True)
    with pytest.raises(ValueError, match="allocated_energy_kwh must be finite and non-negative"):
        score_thermal_schedule(bad_sched, workload_df, realized_df, state)


class DummyMockPolicy(SchedulingPolicy):
    """Custom mock policy providing configurable raw allocations for adapter testing."""
    def __init__(self, raw_allocs: list[ScheduledJobAllocation], name: str = "mock"):
        self.raw_allocs = raw_allocs
        self._name = name

    @property
    def policy_name(self) -> str:
        return self._name

    @property
    def policy_version(self) -> str:
        return "1.0"

    def schedule(self, workload_df, forecast, constraints):
        return ScheduleResult(
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            workload_trace_id=str(workload_df["workload_trace_id"].iloc[0]),
            window_duration_hours=len(forecast.points),
            allocations=self.raw_allocs,
            unmet_deadlines=[],
            is_feasible=True,
        )


def test_adapter_handles_out_of_range_offsets_without_index_error_or_negative_wrap():
    """Adapter deterministically handles -1, exactly horizon, and large offsets without crashing."""
    ts = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    pts = [ForecastPoint(ts[h], h, 10.0, 100.0) for h in range(5)]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_bounds",
        "job_id": "j_repaired",
        "arrival_offset_hours": 0,
        "deadline_offset_hours": 5,
        "processing_requirement": 3,
        "energy_kwh": 300.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    # Base allocations provide:
    # 1. offset -1 (negative index in Python would access last element if unchecked!)
    # 2. offset 5 (exactly horizon)
    # 3. offset 999 (far beyond horizon)
    base_allocs = [
        ScheduledJobAllocation("j_repaired", -1, 100.0, 100.0),
        ScheduledJobAllocation("j_repaired", 5, 100.0, 100.0),
        ScheduledJobAllocation("j_repaired", 999, 100.0, 100.0),
    ]

    mock_policy = DummyMockPolicy(base_allocs)
    eff_cap = np.array([500.0, 500.0, 500.0, 500.0, 500.0])
    adapter = HeatAwareCapacityAdapter(mock_policy, eff_cap)

    # Must NOT raise IndexError or wrap negatively; must repair all 3 into valid [0, 5) range: 0, 1, 2
    res = adapter.schedule(workload_df, fc, constraints)
    assert res.is_feasible is True
    assert len(res.allocations) == 3
    repaired_hours = [a.allocated_hour_offset for a in res.allocations]
    assert repaired_hours == [0, 1, 2]
    assert res.unmet_deadlines == []


def test_adapter_reports_unrecoverable_job_as_unmet_rather_than_crashing():
    """When an out-of-range base allocation cannot be repaired within [arr, min(dead, horizon)),
    the job is marked unmet and does not crash."""
    ts = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    pts = [ForecastPoint(ts[h], h, 10.0, 100.0) for h in range(5)]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    # Job arrives at 4 and has deadline 5 (only 1 hour window: hour 4), but requires 2 hours of processing!
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_tight",
        "job_id": "j_tight",
        "arrival_offset_hours": 4,
        "deadline_offset_hours": 5,
        "processing_requirement": 2,
        "energy_kwh": 200.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    # Base allocations give hour -1 and hour 10
    base_allocs = [
        ScheduledJobAllocation("j_tight", -1, 100.0, 100.0),
        ScheduledJobAllocation("j_tight", 10, 100.0, 100.0),
    ]

    mock_policy = DummyMockPolicy(base_allocs)
    eff_cap = np.array([500.0, 500.0, 500.0, 500.0, 500.0])
    adapter = HeatAwareCapacityAdapter(mock_policy, eff_cap)

    res = adapter.schedule(workload_df, fc, constraints)
    assert res.is_feasible is False
    assert "j_tight" in res.unmet_deadlines
    # Only 1 unit could fit in hour 4
    assert len(res.allocations) == 1
    assert res.allocations[0].allocated_hour_offset == 4


def test_adapter_validates_job_bounds_gracefully():
    """Jobs with inverted deadlines (deadline <= arrival) or negative arrivals do not crash."""
    ts = pd.date_range("2024-07-02 00:00", periods=5, freq="h", tz="UTC")
    pts = [ForecastPoint(ts[h], h, 10.0, 100.0) for h in range(5)]
    fc = ForecastResult(ts[0], pts, "test", "1.0")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    # Inverted deadline job (arrival 4, deadline 2)
    workload_df = pd.DataFrame([{
        "workload_trace_id": "trace_invalid_job",
        "job_id": "j_inverted",
        "arrival_offset_hours": 4,
        "deadline_offset_hours": 2,
        "processing_requirement": 1,
        "energy_kwh": 100.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
    }])

    mock_policy = DummyMockPolicy([])
    eff_cap = np.array([500.0, 500.0, 500.0, 500.0, 500.0])
    adapter = HeatAwareCapacityAdapter(mock_policy, eff_cap)

    res = adapter.schedule(workload_df, fc, constraints)
    assert res.is_feasible is False
    assert "j_inverted" in res.unmet_deadlines
    assert len(res.allocations) == 0


