"""Tests for P4 greedy policies, robust heuristic, and edge cases."""

from __future__ import annotations

import datetime
from pathlib import Path
import pytest
import pandas as pd

from heattrace.policy.greedy import (
    BalancedGreedyPolicy,
    CarbonFirstGreedyPolicy,
    CostFirstGreedyPolicy,
)
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    SchedulingConstraints,
)
from heattrace.policy.robust import RiskPenalizedDROInspiredPolicy
from heattrace.workload.generator import generate_deterministic_workload


@pytest.fixture
def test_forecast():
    points = []
    origin = datetime.datetime(2024, 7, 1, 7, 0, tzinfo=datetime.timezone.utc)
    for h in range(24):
        ts = origin + datetime.timedelta(hours=h)
        # Invert price and carbon to make policies clearly distinguishable:
        # early hours have low price, high carbon; late hours have high price, low carbon
        price = 10.0 + h * 5.0
        carbon = 300.0 - h * 10.0
        points.append(
            ForecastPoint(
                timestamp_utc=ts,
                horizon_hours=h,
                predicted_price_usd_per_mwh=price,
                predicted_carbon_g_per_kwh=carbon,
            )
        )
    return ForecastResult(
        origin_timestamp_utc=origin,
        points=points,
        model_name="test_model",
        model_version="1.0",
    )


@pytest.fixture
def small_workload():
    rows = [
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_01",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 24,
            "processing_requirement": 4,
            "energy_kwh": 200.0,
            "maximum_parallelism": 1,
            "priority": 3,
            "preemptible": False,
        },
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_02",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 24,
            "processing_requirement": 3,
            "energy_kwh": 150.0,
            "maximum_parallelism": 2,
            "priority": 1,
            "preemptible": True,
        },
    ]
    return pd.DataFrame(rows)


def test_greedy_policies_produce_distinguishable_schedules(small_workload, test_forecast):
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    cost_pol = CostFirstGreedyPolicy()
    carb_pol = CarbonFirstGreedyPolicy()

    s_cost = cost_pol.schedule(small_workload, test_forecast, constraints)
    s_carb = carb_pol.schedule(small_workload, test_forecast, constraints)

    assert s_cost.is_feasible is True
    assert s_carb.is_feasible is True

    # Cost-first should choose earlier hours (since prices are low early)
    cost_hours = [a.allocated_hour_offset for a in s_cost.allocations if a.job_id == "job_01"]
    # Carbon-first should choose later hours (since carbon is low late)
    carb_hours = [a.allocated_hour_offset for a in s_carb.allocations if a.job_id == "job_01"]

    assert cost_hours == [0, 1, 2, 3]
    assert carb_hours == [20, 21, 22, 23]


def test_balanced_policy_and_zero_range_normalization():
    # If price and carbon are constant (zero range), balanced policy should still produce valid feasible schedules
    origin = datetime.datetime(2024, 7, 1, 7, 0, tzinfo=datetime.timezone.utc)
    points = [
        ForecastPoint(
            timestamp_utc=origin + datetime.timedelta(hours=h),
            horizon_hours=h,
            predicted_price_usd_per_mwh=45.0,
            predicted_carbon_g_per_kwh=220.0,
        )
        for h in range(24)
    ]
    fc = ForecastResult(origin, points, "flat", "1.0")

    workload = pd.DataFrame([{
        "workload_trace_id": "test_flat",
        "job_id": "job_01",
        "arrival_offset_hours": 2,
        "deadline_offset_hours": 10,
        "processing_requirement": 3,
        "energy_kwh": 90.0,
        "maximum_parallelism": 1,
        "priority": 2,
        "preemptible": False,
    }])

    pol = BalancedGreedyPolicy()
    res = pol.schedule(workload, fc, SchedulingConstraints(500.0, 16))
    assert res.is_feasible is True
    assert len(res.allocations) == 3


def test_negative_prices_handled_correctly(small_workload):
    origin = datetime.datetime(2024, 7, 1, 7, 0, tzinfo=datetime.timezone.utc)
    # Give hour 5 a negative price (-20 USD/MWh)
    points = [
        ForecastPoint(
            timestamp_utc=origin + datetime.timedelta(hours=h),
            horizon_hours=h,
            predicted_price_usd_per_mwh=-20.0 if h == 5 else 50.0,
            predicted_carbon_g_per_kwh=200.0,
        )
        for h in range(24)
    ]
    fc = ForecastResult(origin, points, "neg_test", "1.0")

    cost_pol = CostFirstGreedyPolicy()
    res = cost_pol.schedule(small_workload, fc, SchedulingConstraints(500.0, 16))
    # Preemptible job_02 should pick hour 5
    j2_hours = [a.allocated_hour_offset for a in res.allocations if a.job_id == "job_02"]
    assert 5 in j2_hours


def test_dro_heuristic_monotonicity_and_lambda_zero(small_workload, test_forecast):
    constraints = SchedulingConstraints(500.0, 16)

    # When lambda == 0, DRO reduces to balanced
    dro_zero = RiskPenalizedDROInspiredPolicy(dro_risk_penalty_lambda=0.0)
    bal_pol = BalancedGreedyPolicy()

    s_dro_zero = dro_zero.schedule(small_workload, test_forecast, constraints)
    s_bal = bal_pol.schedule(small_workload, test_forecast, constraints)

    assert [a.allocated_hour_offset for a in s_dro_zero.allocations] == [a.allocated_hour_offset for a in s_bal.allocations]

    # Increasing uncertainty quantile increases penalty
    dro_lo = RiskPenalizedDROInspiredPolicy(uncertainty_quantile=0.5)
    dro_hi = RiskPenalizedDROInspiredPolicy(uncertainty_quantile=0.95)

    errs = [0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0]
    p_lo = dro_lo.compute_uncertainty_penalty(test_forecast, history_errors=errs)
    p_hi = dro_hi.compute_uncertainty_penalty(test_forecast, history_errors=errs)
    assert p_hi >= p_lo
