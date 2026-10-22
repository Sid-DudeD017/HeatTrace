"""Targeted unit and integration tests for P5.5 experiment implementation."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from heattrace.analysis.p5_5_figures import generate_p5_5_figures, generate_p5_5_summary_tables
from heattrace.experiments.p5_5_grid import (
    P55ScenarioSpec,
    build_preregistered_p5_5_grid,
    freeze_experiment_grid,
    generate_stressed_workload,
)
from heattrace.experiments.p5_5_runner import (
    execute_single_scenario_p5_5,
    get_policy_instance_p5_5,
    run_full_p5_5_experiment,
)
from heattrace.experiments.p5_5_scenarios import (
    generate_flat_forecast,
    generate_noisy_oracle_forecast,
    generate_oracle_forecast,
)
from heattrace.policy.baseline import BaselineReferencePolicy
from heattrace.policy.comparator import ExactSmallInstanceHindsightComparator
from heattrace.policy.interfaces import SchedulingConstraints
from heattrace.process.p5_5_audit import run_g5_5_audit


@pytest.fixture
def sample_benchmark_df() -> pd.DataFrame:
    """Load authentic benchmark dataframe."""
    return pd.read_parquet("data/benchmarks/benchmark_2024_event_control_v0.parquet")


def test_p5_5_deterministic_scenario_grid_generation():
    """Verify that preregistered grid generation is deterministic, complete, and contains 270 scenarios."""
    grid1 = build_preregistered_p5_5_grid()
    grid2 = build_preregistered_p5_5_grid()

    assert len(grid1) == 270
    assert len(grid1) == len(grid2)

    for s1, s2 in zip(grid1, grid2):
        assert s1.scenario_id == s2.scenario_id
        assert s1.random_seed == s2.random_seed
        assert s1.workload_multiplier == s2.workload_multiplier
        assert s1.job_count == s2.job_count
        assert s1.max_cluster_power_kw == s2.max_cluster_power_kw
        assert s1.max_concurrent_jobs == s2.max_concurrent_jobs
        assert s1.slack_multiplier == s2.slack_multiplier


def test_p5_5_stressed_workload_generation_properties():
    """Validate workload scaling, job identity stability, and deadline constraint enforcement."""
    for jc in [30, 60, 90]:
        for slack in [0.5, 1.0, 1.5]:
            wl = generate_stressed_workload(job_count=jc, slack_multiplier=slack, random_seed=20261016)
            assert len(wl) == jc
            assert wl["job_id"].iloc[0] == "job_0001" or "job_0001" in wl["job_id"].values
            # All deadlines > arrival + processing_requirement
            assert (wl["deadline_offset_hours"] >= wl["arrival_offset_hours"] + wl["processing_requirement"]).all()
            assert (wl["deadline_offset_hours"] <= 120).all()
            assert (wl["arrival_offset_hours"] >= 0).all()


def test_p5_5_forecast_scenarios_and_no_leakage(sample_benchmark_df: pd.DataFrame):
    """Test flat, oracle, and seeded noisy oracle forecasts; ensure structural separation."""
    hw_df = sample_benchmark_df[sample_benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)

    # 1. Flat forecast has constant values
    flat_fc = generate_flat_forecast(hw_df)
    assert len(flat_fc.points) == 120
    prices = [p.predicted_price_usd_per_mwh for p in flat_fc.points]
    assert len(set(prices)) == 1

    # 2. Oracle forecast exactly matches realized values
    oracle_fc = generate_oracle_forecast(hw_df)
    assert len(oracle_fc.points) == 120
    for p, actual_price in zip(oracle_fc.points, hw_df["price_usd_per_mwh"]):
        assert np.isclose(p.predicted_price_usd_per_mwh, actual_price)

    # 3. Seeded noisy oracle is reproducible and exhibits expected MAE degradation
    noisy_fc1, m1 = generate_noisy_oracle_forecast(hw_df, noise_sigma=0.25, seed=42)
    noisy_fc2, m2 = generate_noisy_oracle_forecast(hw_df, noise_sigma=0.25, seed=42)
    assert m1["forecast_price_mae"] == m2["forecast_price_mae"]
    assert np.isclose(noisy_fc1.points[0].predicted_price_usd_per_mwh, noisy_fc2.points[0].predicted_price_usd_per_mwh)
    assert m1["forecast_price_mae"] > 0.0

    # Higher noise sigma produces higher MAE
    noisy_fc_high, m_high = generate_noisy_oracle_forecast(hw_df, noise_sigma=0.50, seed=42)
    assert m_high["forecast_price_mae"] > m1["forecast_price_mae"]


def test_p5_5_baseline_reference_policy_execution(sample_benchmark_df: pd.DataFrame):
    """Test that baseline_reference schedules greedily earliest arrival."""
    hw_df = sample_benchmark_df[sample_benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)
    fc = generate_oracle_forecast(hw_df)
    wl = generate_stressed_workload(job_count=30, slack_multiplier=1.0)
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    pol = BaselineReferencePolicy()
    sched = pol.schedule(wl, fc, constraints)
    assert sched.is_feasible is True
    assert len(sched.allocations) > 0


def test_p5_5_infeasible_scenario_traceable_recording(sample_benchmark_df: pd.DataFrame):
    """Ensure that under extreme capacity constraint, infeasible schedules are recorded rather than dropped."""
    hw_df = sample_benchmark_df[sample_benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)
    fc = generate_oracle_forecast(hw_df)
    # Stressed workload with 90 jobs and tight deadlines
    wl = generate_stressed_workload(job_count=90, slack_multiplier=0.5)
    # Extreme bottleneck: 120 kW and 3 jobs
    extreme_constraints = SchedulingConstraints(max_cluster_power_kw=120.0, max_concurrent_jobs=3)

    pol = BaselineReferencePolicy()
    sched = pol.schedule(wl, fc, extreme_constraints)
    assert sched.is_feasible is False
    assert len(sched.unmet_deadlines) > 0


def test_p5_5_audit_verified_pass():
    """Verify that the G5.5-a comprehensive audit passes with 100% compliance."""
    audit_res = run_g5_5_audit()
    assert audit_res["status"] == "VERIFIED_PASS"
    assert audit_res["failure_count"] == 0
    assert audit_res["total_runs_evaluated"] == 1350
    assert audit_res["feasible_runs_count"] > 0
    assert audit_res["infeasible_runs_count"] > 0
    for check_name, passed in audit_res["checks"].items():
        assert passed is True, f"Audit check failed: {check_name}"
