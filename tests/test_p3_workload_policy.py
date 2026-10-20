"""Tests for HeatTrace P3-03 Workload Generation and P3-04 Interfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import pytest
import pandas as pd

from heattrace.workload import (
    WORKLOAD_JOB_COLUMNS,
    build_and_export_workloads,
    generate_deterministic_workload,
    validate_workload_dataframe,
)
from heattrace.policy import (
    FixtureEarliestDeadlineFirstPolicy,
    FixturePersistenceForecastProvider,
    ForecastPoint,
    ForecastProvider,
    ForecastResult,
    ScheduledJobAllocation,
    ScheduleResult,
    SchedulingConstraints,
    SchedulingPolicy,
)


def test_workload_generation_deterministic_with_same_seed():
    """Verify that same seed generates byte-identical workload traces."""
    df1 = generate_deterministic_workload(job_count=40, random_seed=20261016)
    df2 = generate_deterministic_workload(job_count=40, random_seed=20261016)
    pd.testing.assert_frame_equal(df1, df2)


def test_workload_generation_differs_with_different_seed():
    """Verify that different seed produces different job arrivals and energy."""
    df1 = generate_deterministic_workload(job_count=40, random_seed=20261016)
    df2 = generate_deterministic_workload(job_count=40, random_seed=99999999)
    assert not df1.equals(df2)


def test_workload_generation_validates_constraints():
    """Verify workload generator produces valid jobs satisfying all physical constraints."""
    df = generate_deterministic_workload(job_count=50, random_seed=20261016)
    assert len(df) == 50
    assert list(df.columns) == WORKLOAD_JOB_COLUMNS

    for _, row in df.iterrows():
        assert row["arrival_offset_hours"] >= 0
        assert row["deadline_offset_hours"] <= 120
        assert row["deadline_offset_hours"] > row["arrival_offset_hours"]
        assert row["processing_requirement"] > 0
        assert row["processing_requirement"] <= (row["deadline_offset_hours"] - row["arrival_offset_hours"])
        assert row["energy_kwh"] > 0.0
        assert row["maximum_parallelism"] in (1, 2, 4)
        assert 1 <= row["priority"] <= 5


def test_workload_validation_rejects_invalid_cases():
    """Verify validator catches duplicate jobs, deadline before arrival, or excessive processing."""
    df = generate_deterministic_workload(job_count=5, random_seed=20261016)

    # Duplicate job ID
    df_dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate job_id"):
        validate_workload_dataframe(df_dup)

    # Deadline <= arrival
    df_bad_dead = df.copy()
    df_bad_dead.loc[0, "deadline_offset_hours"] = df_bad_dead.loc[0, "arrival_offset_hours"]
    with pytest.raises(ValueError, match="deadline_offset_hours .* <= arrival"):
        validate_workload_dataframe(df_bad_dead)

    # Processing > slack
    df_bad_proc = df.copy()
    df_bad_proc.loc[0, "processing_requirement"] = 200
    with pytest.raises(ValueError, match="processing_requirement .* exceeds window"):
        validate_workload_dataframe(df_bad_proc)


def test_workload_export_and_manifest():
    """Verify build_and_export_workloads creates files and valid manifest."""
    res = build_and_export_workloads(job_count=30)
    assert res["parquet_path"].exists()
    assert res["csv_path"].exists()
    assert res["manifest_path"].exists()
    assert res["manifest"]["job_count"] == 30
    assert res["manifest"]["random_seed"] == 20261016


def test_p3_04_forecast_provider_protocol_and_fixture():
    """Verify FixturePersistenceForecastProvider conforms to ForecastProvider protocol."""
    provider = FixturePersistenceForecastProvider(default_price=55.0, default_carbon=250.0)
    assert isinstance(provider, ForecastProvider)

    origin = datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc)
    res = provider.forecast(origin, horizon_hours=24)

    assert isinstance(res, ForecastResult)
    assert res.origin_timestamp_utc == origin
    assert len(res.points) == 24
    assert res.points[0].predicted_price_usd_per_mwh == 55.0
    assert res.points[0].predicted_carbon_g_per_kwh == 250.0

    df_fc = res.to_dataframe()
    assert len(df_fc) == 24
    assert "predicted_price_usd_per_mwh" in df_fc.columns


def test_p3_04_scheduling_policy_protocol_and_fixture():
    """Verify FixtureEarliestDeadlineFirstPolicy conforms to SchedulingPolicy protocol."""
    policy = FixtureEarliestDeadlineFirstPolicy()
    assert isinstance(policy, SchedulingPolicy)

    df_workload = generate_deterministic_workload(job_count=10, random_seed=20261016)
    provider = FixturePersistenceForecastProvider()
    origin = datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc)
    fc = provider.forecast(origin, horizon_hours=120)
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0)

    sched_res = policy.schedule(df_workload, fc, constraints)
    assert isinstance(sched_res, ScheduleResult)
    assert sched_res.is_feasible is True
    assert len(sched_res.allocations) > 0

    df_alloc = sched_res.to_dataframe()
    assert "allocated_hour_offset" in df_alloc.columns
    assert "execution_power_kw" in df_alloc.columns
