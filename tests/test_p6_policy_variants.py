"""Focused tests for HeatTrace Phase 3: Workload scaling, policy variants, and boundaries."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd
import pytest

from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
)
from heattrace.thermal.facility import (
    FacilityConfig,
    FacilityModelKind,
    build_forecast_facility_state,
    build_realized_facility_state,
    get_preset_thermal_scenario,
)
from heattrace.thermal.policies import (
    CapacityAwarePolicy,
    FullThermalAwarePolicy,
    OracleFullThermalAwarePolicy,
    StaticUnawarePolicy,
    get_p6_policy,
)
from heattrace.workload.generator import generate_deterministic_workload
from heattrace.workload.scaling import (
    FROZEN_WORKLOAD_SEEDS,
    SUPPORTED_MULTIPLIERS,
    scale_workload,
)


@pytest.fixture
def canonical_workload_seed1() -> pd.DataFrame:
    return generate_deterministic_workload(
        workload_trace_id="trace_standard_120h_v0",
        window_duration_hours=120,
        job_count=50,
        random_seed=20261016,
    )


@pytest.fixture
def canonical_workload_seed2() -> pd.DataFrame:
    return generate_deterministic_workload(
        workload_trace_id="trace_standard_120h_v1",
        window_duration_hours=120,
        job_count=50,
        random_seed=20261017,
    )


@pytest.fixture
def forecast_120h() -> ForecastResult:
    start = datetime(2022, 6, 20, 0, 0, tzinfo=timezone.utc)
    points = []
    for h in range(120):
        ts = datetime.fromtimestamp(start.timestamp() + h * 3600, tz=timezone.utc)
        # Vary price and carbon so order differs
        price = 30.0 + 10.0 * np.sin(h / 6.0)
        carbon = 200.0 + 50.0 * np.cos(h / 8.0)
        points.append(
            ForecastPoint(
                timestamp_utc=ts,
                horizon_hours=h,
                predicted_price_usd_per_mwh=float(price),
                predicted_carbon_g_per_kwh=float(carbon),
            )
        )
    return ForecastResult(
        origin_timestamp_utc=start,
        points=points,
        model_name="test_forecast_provider",
        model_version="1.0",
    )


@pytest.fixture
def nominal_constraints() -> SchedulingConstraints:
    return SchedulingConstraints(
        max_cluster_power_kw=500.0,
        max_concurrent_jobs=16,
        allow_preemption=True,
    )


@pytest.fixture
def facility_states(forecast_120h: ForecastResult) -> tuple[pd.DataFrame, pd.DataFrame]:
    scenario = get_preset_thermal_scenario("medium")
    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=500.0,
        thermal_scenario=scenario,
    )
    # 120 hourly points
    timestamps = [p.timestamp_utc for p in forecast_120h.points]
    # Forecast temperatures: base 25C + diurnal sine wave
    f_temps = [25.0 + 8.0 * np.sin(h / 12.0) for h in range(120)]
    # Realized temperatures: hotter heatwave realized
    r_temps = [28.0 + 12.0 * np.sin(h / 12.0) for h in range(120)]

    forecast_in = pd.DataFrame({
        "timestamp_utc": timestamps,
        "forecast_temperature_c": f_temps,
    })
    realized_in = pd.DataFrame({
        "timestamp_utc": timestamps,
        "temperature_c": r_temps,
    })

    forecast_fac = build_forecast_facility_state(forecast_in, config)
    realized_fac = build_realized_facility_state(realized_in, config)
    return forecast_fac, realized_fac


@pytest.fixture
def realized_market_120h(forecast_120h: ForecastResult) -> pd.DataFrame:
    timestamps = [p.timestamp_utc for p in forecast_120h.points]
    # Realized prices and carbons differ from forecasts
    prices = [35.0 + 15.0 * np.cos(h / 7.0) for h in range(120)]
    carbons = [210.0 + 40.0 * np.sin(h / 9.0) for h in range(120)]
    return pd.DataFrame({
        "timestamp_utc": timestamps,
        "price_usd_per_mwh": prices,
        "carbon_g_per_kwh": carbons,
    })


# =========================================================================
# Workload Scaling Tests
# =========================================================================

def test_scale_workload_1x_frame_equivalent_and_non_mutating(canonical_workload_seed1: pd.DataFrame):
    """1x scaling returns frame-equivalent DataFrame without mutating original, preserving trace_id."""
    orig_copy = canonical_workload_seed1.copy(deep=True)
    scaled = scale_workload(canonical_workload_seed1, 1.0, seed=20261016)

    pd.testing.assert_frame_equal(scaled, orig_copy)
    assert scaled is not canonical_workload_seed1
    pd.testing.assert_frame_equal(canonical_workload_seed1, orig_copy)
    assert scaled["workload_trace_id"].iloc[0] == canonical_workload_seed1["workload_trace_id"].iloc[0]


def test_scale_workload_2x_and_3x_exact_totals(canonical_workload_seed1: pd.DataFrame):
    """2x and 3x scaling produce exact integer and energy multiples."""
    orig_proc = int(canonical_workload_seed1["processing_requirement"].sum())
    orig_energy = float(canonical_workload_seed1["energy_kwh"].sum())

    scaled_2x = scale_workload(canonical_workload_seed1, 2.0, seed=20261016)
    assert len(scaled_2x) == len(canonical_workload_seed1) * 2
    assert int(scaled_2x["processing_requirement"].sum()) == orig_proc * 2
    assert math.isclose(scaled_2x["energy_kwh"].sum(), orig_energy * 2, rel_tol=1e-6)

    scaled_3x = scale_workload(canonical_workload_seed1, 3.0, seed=20261016)
    assert len(scaled_3x) == len(canonical_workload_seed1) * 3
    assert int(scaled_3x["processing_requirement"].sum()) == orig_proc * 3
    assert math.isclose(scaled_3x["energy_kwh"].sum(), orig_energy * 3, rel_tol=1e-6)


def test_scale_workload_trace_id_format_and_distinctness(canonical_workload_seed1: pd.DataFrame):
    """2x and 3x receive deterministic multiplier-and-seed-specific trace IDs."""
    orig_trace = str(canonical_workload_seed1["workload_trace_id"].iloc[0])

    s1 = scale_workload(canonical_workload_seed1, 1.0, seed=20261016)
    s2 = scale_workload(canonical_workload_seed1, 2.0, seed=20261016)
    s3 = scale_workload(canonical_workload_seed1, 3.0, seed=20261016)

    assert s1["workload_trace_id"].iloc[0] == orig_trace
    expected_s2_trace = f"{orig_trace}__x2__seed20261016"
    expected_s3_trace = f"{orig_trace}__x3__seed20261016"

    assert (s2["workload_trace_id"] == expected_s2_trace).all()
    assert (s3["workload_trace_id"] == expected_s3_trace).all()

    # Distinct trace IDs
    trace_set = {s1["workload_trace_id"].iloc[0], s2["workload_trace_id"].iloc[0], s3["workload_trace_id"].iloc[0]}
    assert len(trace_set) == 3


def test_scale_workload_deterministic_replicas_and_no_collisions(canonical_workload_seed1: pd.DataFrame):
    """Repeated calls produce identical DataFrames with collision-free unique IDs."""
    call1 = scale_workload(canonical_workload_seed1, 2.0, seed=20261016)
    call2 = scale_workload(canonical_workload_seed1, 2.0, seed=20261016)

    pd.testing.assert_frame_equal(call1, call2)
    assert call1["job_id"].nunique() == len(call1)
    # Check replica suffix naming
    assert any("_rep1" in jid for jid in call1["job_id"])


def test_scale_workload_seed_binding_and_rejections(
    canonical_workload_seed1: pd.DataFrame,
    canonical_workload_seed2: pd.DataFrame,
):
    """Binds seed to workload; rejects seed mismatches, mixed seeds, null seeds, and non-ints."""
    # Matching seed accepted
    s1 = scale_workload(canonical_workload_seed1, 2.0, seed=20261016)
    assert len(s1) == 100
    s2 = scale_workload(canonical_workload_seed2, 2.0, seed=20261017)
    assert len(s2) == 100

    # Seed mismatch: seed-20261016 workload with seed=20261017 arg
    with pytest.raises(ValueError, match="does not match function seed argument"):
        scale_workload(canonical_workload_seed1, 2.0, seed=20261017)

    # Seed-20261017 workload with seed=20261016 arg
    with pytest.raises(ValueError, match="does not match function seed argument"):
        scale_workload(canonical_workload_seed2, 2.0, seed=20261016)

    # Mixed seeds in dataframe
    mixed_df = canonical_workload_seed1.copy(deep=True)
    mixed_df.loc[0, "seed"] = 20261017
    with pytest.raises(ValueError, match="contains mixed seeds"):
        scale_workload(mixed_df, 2.0, seed=20261016)

    # Missing / null seed
    null_df = canonical_workload_seed1.copy(deep=True)
    null_df.loc[0, "seed"] = None
    with pytest.raises(ValueError, match="contains null/missing seed values"):
        scale_workload(null_df, 2.0, seed=20261016)

    # Boolean seed in dataframe
    bool_df = canonical_workload_seed1.copy(deep=True)
    bool_df["seed"] = bool_df["seed"].astype(object)
    bool_df.loc[0, "seed"] = True
    with pytest.raises(TypeError, match="contains boolean value"):
        scale_workload(bool_df, 2.0, seed=20261016)


def test_scale_workload_rejection_of_unsupported_inputs(canonical_workload_seed1: pd.DataFrame):
    """Rejects booleans, NaN, Inf, unsupported multipliers, and unapproved seeds loudly."""
    # Boolean multiplier
    with pytest.raises(TypeError, match="multiplier cannot be a boolean"):
        scale_workload(canonical_workload_seed1, True, seed=20261016)

    # Boolean seed
    with pytest.raises(TypeError, match="seed cannot be a boolean"):
        scale_workload(canonical_workload_seed1, 1.0, seed=True)

    # Unsupported multipliers
    with pytest.raises(ValueError, match="Unsupported multiplier"):
        scale_workload(canonical_workload_seed1, 1.5, seed=20261016)
    with pytest.raises(ValueError, match="Unsupported multiplier"):
        scale_workload(canonical_workload_seed1, 4.0, seed=20261016)

    # Unsupported seed
    with pytest.raises(ValueError, match="Unsupported seed"):
        scale_workload(canonical_workload_seed1, 2.0, seed=99999999)

    # NaN / Inf multiplier
    with pytest.raises(ValueError, match="multiplier must be finite"):
        scale_workload(canonical_workload_seed1, float("nan"), seed=20261016)
    with pytest.raises(ValueError, match="multiplier must be finite"):
        scale_workload(canonical_workload_seed1, float("inf"), seed=20261016)


def test_scale_workload_rejects_duplicate_source_or_inconsistent_trace_ids(canonical_workload_seed1: pd.DataFrame):
    """Rejects workload with duplicate job IDs or mixed trace IDs."""
    dup_df = canonical_workload_seed1.copy(deep=True)
    dup_df.loc[1, "job_id"] = dup_df.loc[0, "job_id"]
    with pytest.raises(ValueError, match="Duplicate job_id found"):
        scale_workload(dup_df, 2.0, seed=20261016)

    mixed_trace_df = canonical_workload_seed1.copy(deep=True)
    mixed_trace_df.loc[1, "workload_trace_id"] = "other_trace"
    with pytest.raises(ValueError, match="inconsistent workload_trace_ids"):
        scale_workload(mixed_trace_df, 2.0, seed=20261016)


# =========================================================================
# Policy Variant & Information Leakage Tests
# =========================================================================

def test_policy_ids_and_deployability(
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
    realized_market_120h: pd.DataFrame,
):
    """All 4 policy IDs are stable; deployable flags strictly match requirements."""
    forecast_fac, realized_fac = facility_states

    static_p = get_p6_policy("static_unaware")
    assert static_p.policy_id == "static_unaware"
    assert static_p.deployable is True

    cap_p = get_p6_policy("capacity_aware", facility_state=forecast_fac)
    assert cap_p.policy_id == "capacity_aware"
    assert cap_p.deployable is True

    full_p = get_p6_policy("full_thermal_aware", facility_state=forecast_fac)
    assert full_p.policy_id == "full_thermal_aware"
    assert full_p.deployable is True

    oracle_p = get_p6_policy(
        "oracle_full_thermal_aware",
        facility_state=realized_fac,
        realized_market_state=realized_market_120h,
    )
    assert oracle_p.policy_id == "oracle_full_thermal_aware"
    assert oracle_p.deployable is False


def test_deployable_policies_reject_realized_inputs(
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
    realized_market_120h: pd.DataFrame,
):
    """Deployable policies reject source_context='realized' and realized_market_state."""
    forecast_fac, realized_fac = facility_states

    # static_unaware rejects facility state and realized market state
    with pytest.raises(ValueError, match="static_unaware rejects any supplied facility_state"):
        get_p6_policy("static_unaware", facility_state=forecast_fac)
    with pytest.raises(ValueError, match="static_unaware rejects any supplied realized_market_state"):
        get_p6_policy("static_unaware", realized_market_state=realized_market_120h)

    # capacity_aware rejects realized facility state and realized market state
    with pytest.raises(ValueError, match="Invalid facility state source_context 'realized'"):
        get_p6_policy("capacity_aware", facility_state=realized_fac)
    with pytest.raises(ValueError, match="capacity_aware deployable policy rejects realized_market_state"):
        get_p6_policy("capacity_aware", facility_state=forecast_fac, realized_market_state=realized_market_120h)

    # full_thermal_aware rejects realized facility state and realized market state
    with pytest.raises(ValueError, match="Invalid facility state source_context 'realized'"):
        get_p6_policy("full_thermal_aware", facility_state=realized_fac)
    with pytest.raises(ValueError, match="full_thermal_aware deployable policy rejects realized_market_state"):
        get_p6_policy("full_thermal_aware", facility_state=forecast_fac, realized_market_state=realized_market_120h)


def test_oracle_policy_requires_realized_state_and_market(
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
    realized_market_120h: pd.DataFrame,
):
    """Oracle requires both realized facility state and realized market state."""
    forecast_fac, realized_fac = facility_states

    # Missing realized market state
    with pytest.raises(ValueError, match="oracle_full_thermal_aware requires realized_market_state"):
        get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac)

    # Forecast facility state rejected
    with pytest.raises(ValueError, match="Invalid facility state source_context 'forecast'"):
        get_p6_policy(
            "oracle_full_thermal_aware",
            facility_state=forecast_fac,
            realized_market_state=realized_market_120h,
        )


def test_mutating_realized_values_cannot_change_deployable_schedules(
    canonical_workload_seed1: pd.DataFrame,
    forecast_120h: ForecastResult,
    nominal_constraints: SchedulingConstraints,
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
    realized_market_120h: pd.DataFrame,
):
    """Proves mutating future realized facility, price, or carbon values cannot change deployable schedules."""
    forecast_fac, realized_fac = facility_states

    p_static = get_p6_policy("static_unaware")
    res_static_1 = p_static.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)

    p_cap = get_p6_policy("capacity_aware", facility_state=forecast_fac)
    res_cap_1 = p_cap.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)

    p_full = get_p6_policy("full_thermal_aware", facility_state=forecast_fac)
    res_full_1 = p_full.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)

    # Mutate future realized facility state and market state drastically
    realized_fac_mutated = realized_fac.copy(deep=True)
    realized_fac_mutated["pue"] = realized_fac_mutated["pue"] * 3.0
    realized_fac_mutated["effective_compute_capacity_kw"] = 10.0

    realized_market_mutated = realized_market_120h.copy(deep=True)
    realized_market_mutated["price_usd_per_mwh"] = 9999.0
    realized_market_mutated["carbon_g_per_kwh"] = 9999.0

    # Re-schedule deployable policies (they only consume forecast inputs)
    res_static_2 = p_static.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)
    res_cap_2 = p_cap.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)
    res_full_2 = p_full.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)

    assert res_static_1.allocations == res_static_2.allocations
    assert res_cap_1.allocations == res_cap_2.allocations
    assert res_full_1.allocations == res_full_2.allocations


def test_oracle_responds_to_realized_market_and_ignores_causal_forecast():
    """Oracle uses realized price/carbon and ignores causal forecast points, shifting preferred hours."""
    # Single job that can run at hour 5 or hour 6
    workload = pd.DataFrame([{
        "workload_trace_id": "test_trace",
        "job_id": "job_0001",
        "arrival_offset_hours": 5,
        "deadline_offset_hours": 7,
        "processing_requirement": 1,
        "energy_kwh": 50.0,
        "maximum_parallelism": 1,
        "priority": 1,
        "preemptible": True,
        "seed": 20261016,
        "generator_version": "1.0",
    }])
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    # Forecast predicts hour 5 is cleanest (carbon=100) and hour 6 is dirty (carbon=500)
    start = datetime(2022, 6, 20, 0, 0, tzinfo=timezone.utc)
    f_points = []
    for h in range(120):
        ts = datetime.fromtimestamp(start.timestamp() + h * 3600, tz=timezone.utc)
        c = 100.0 if h == 5 else (500.0 if h == 6 else 300.0)
        f_points.append(ForecastPoint(ts, h, 50.0, c))
    forecast = ForecastResult(start, f_points, "test", "1.0")

    timestamps = [p.timestamp_utc for p in f_points]
    realized_fac = pd.DataFrame({
        "timestamp_utc": timestamps,
        "pue": [1.2] * 120,
        "effective_compute_capacity_kw": [500.0] * 120,
        "source_context": ["realized"] * 120,
    })

    # Case A: Realized carbon has hour 5 clean (100) and hour 6 dirty (500) -> Oracle picks hour 5
    market_a = pd.DataFrame({
        "timestamp_utc": timestamps,
        "price_usd_per_mwh": [50.0] * 120,
        "carbon_g_per_kwh": [100.0 if h == 5 else (500.0 if h == 6 else 300.0) for h in range(120)],
    })
    oracle_a = get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=market_a)
    sched_a = oracle_a.schedule(workload, forecast, constraints)
    assert sched_a.allocations[0].allocated_hour_offset == 5

    # Case B: In reality, a wind surge occurred at hour 6 (carbon=10) while hour 5 spiked (carbon=800)
    # The causal forecast still thought hour 5 was cleaner (100 vs 500)
    # The Oracle with perfect information MUST allocate to hour 6!
    market_b = pd.DataFrame({
        "timestamp_utc": timestamps,
        "price_usd_per_mwh": [50.0] * 120,
        "carbon_g_per_kwh": [800.0 if h == 5 else (10.0 if h == 6 else 300.0) for h in range(120)],
    })
    oracle_b = get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=market_b)
    sched_b = oracle_b.schedule(workload, forecast, constraints)
    assert sched_b.allocations[0].allocated_hour_offset == 6


def test_oracle_market_timestamp_alignment_and_non_finite_rejection(
    forecast_120h: ForecastResult,
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
    realized_market_120h: pd.DataFrame,
):
    """Oracle market timestamps must align; non-finite and negative carbon fail loudly."""
    _, realized_fac = facility_states

    # Timestamp mismatch between market state and facility state
    market_shifted = realized_market_120h.copy(deep=True)
    market_shifted["timestamp_utc"] = pd.date_range("2024-01-01", periods=120, freq="1h", tz="UTC")
    with pytest.raises(ValueError, match="does not match expected timestamp"):
        get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=market_shifted)

    # Non-finite price (Inf and NaN)
    market_inf_p = realized_market_120h.copy(deep=True)
    market_inf_p.loc[0, "price_usd_per_mwh"] = float("inf")
    with pytest.raises(ValueError, match="price_usd_per_mwh contains non-finite values"):
        get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=market_inf_p)

    market_nan_p = realized_market_120h.copy(deep=True)
    market_nan_p.loc[0, "price_usd_per_mwh"] = float("nan")
    with pytest.raises(ValueError, match="price_usd_per_mwh contains missing/NaN values"):
        get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=market_nan_p)

    # Negative carbon
    market_neg_c = realized_market_120h.copy(deep=True)
    market_neg_c.loc[0, "carbon_g_per_kwh"] = -10.0
    with pytest.raises(ValueError, match="carbon_g_per_kwh cannot contain negative values"):
        get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=market_neg_c)


def test_energy_only_capacity_remains_nominal(
    canonical_workload_seed1: pd.DataFrame,
    forecast_120h: ForecastResult,
    nominal_constraints: SchedulingConstraints,
):
    """Energy-only facility model effective capacity equals nominal compute capacity."""
    scenario = get_preset_thermal_scenario("medium")
    config = FacilityConfig(
        model_kind=FacilityModelKind.energy_only,
        nominal_compute_capacity_kw=500.0,
        thermal_scenario=scenario,
    )
    timestamps = [p.timestamp_utc for p in forecast_120h.points]
    forecast_in = pd.DataFrame({
        "timestamp_utc": timestamps,
        "forecast_temperature_c": [35.0] * 120,
    })
    fac_df = build_forecast_facility_state(forecast_in, config)

    assert (fac_df["effective_compute_capacity_kw"] == 500.0).all()

    policy = get_p6_policy("capacity_aware", facility_state=fac_df)
    res = policy.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)
    assert res.is_feasible is True


def test_no_job_silently_disappears_and_unmet_deadlines(
    canonical_workload_seed1: pd.DataFrame,
    forecast_120h: ForecastResult,
    nominal_constraints: SchedulingConstraints,
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
):
    """Under extreme capacity reduction, uncompleted work sets is_feasible=False and lists jobs."""
    forecast_fac, _ = facility_states

    # Severe power constraint (e.g. 5 kW max capacity)
    severely_capped = forecast_fac.copy(deep=True)
    severely_capped["effective_compute_capacity_kw"] = 5.0

    p = get_p6_policy("capacity_aware", facility_state=severely_capped)
    res = p.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)

    assert res.is_feasible is False
    assert len(res.unmet_deadlines) > 0
    # Every job is either fully allocated or in unmet_deadlines
    alloc_counts = {}
    for a in res.allocations:
        alloc_counts[a.job_id] = alloc_counts.get(a.job_id, 0) + 1

    for _, row in canonical_workload_seed1.iterrows():
        jid = str(row["job_id"])
        req = int(row["processing_requirement"])
        act = alloc_counts.get(jid, 0)
        if act < req:
            assert jid in res.unmet_deadlines


def test_no_duplicate_job_hour_allocations(
    canonical_workload_seed1: pd.DataFrame,
    forecast_120h: ForecastResult,
    nominal_constraints: SchedulingConstraints,
    facility_states: tuple[pd.DataFrame, pd.DataFrame],
    realized_market_120h: pd.DataFrame,
):
    """No schedule result contains duplicate (job_id, hour) allocations."""
    forecast_fac, realized_fac = facility_states

    policies = [
        get_p6_policy("static_unaware"),
        get_p6_policy("capacity_aware", facility_state=forecast_fac),
        get_p6_policy("full_thermal_aware", facility_state=forecast_fac),
        get_p6_policy("oracle_full_thermal_aware", facility_state=realized_fac, realized_market_state=realized_market_120h),
    ]

    for p in policies:
        res = p.schedule(canonical_workload_seed1, forecast_120h, nominal_constraints)
        pairs = [(a.job_id, a.allocated_hour_offset) for a in res.allocations]
        assert len(pairs) == len(set(pairs)), f"Duplicates in {p.policy_id}"
