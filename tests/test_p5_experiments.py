"""Tests for HeatTrace P5 experimental pipeline, E1-E4, comparator, and G5-a audit."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from heattrace.analysis.bootstrap import (
    compute_hourly_paired_signal_differences,
    compute_paired_bootstrap_ci,
)
from heattrace.analysis.characterization import (
    compute_distribution_summary,
    compute_lagged_associations,
    run_event_characterization_pipeline,
)
from heattrace.analysis.sampling import generate_sampling_manifests, validate_sampling_manifests
from heattrace.analysis.strategy_comparison import compare_evaluation_strategies
from heattrace.analysis.treatments import (
    build_treatment_variants,
    create_causal_imputed_variant,
    create_clipped_variant,
    fit_historical_clipping_bounds,
)
from heattrace.experiments.runner import run_p5_comparator_instances
from heattrace.policy.interfaces import SchedulingConstraints
from heattrace.process.p5_audit import run_g5_audit


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def benchmark_df(repo_root):
    return pd.read_parquet(repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet")


@pytest.fixture
def history_df(repo_root):
    return pd.read_parquet(repo_root / "data/processed/hourly_caiso_v0.parquet")


@pytest.fixture
def workload_df(repo_root):
    return pd.read_parquet(repo_root / "data/workloads/workload_trace_v0.parquet")


def test_characterization_distribution_summary(benchmark_df):
    """Verify E1 distribution summaries compute expected bounds and metrics."""
    summary_df = compute_distribution_summary(benchmark_df, group_cols=["window_id", "window_type"])
    assert len(summary_df) > 0
    assert "mean" in summary_df.columns
    assert "std" in summary_df.columns
    assert "q90" in summary_df.columns

    # Verify carbon quality flag counting
    carbon_row = summary_df[summary_df["signal"] == "carbon_g_per_kwh"].iloc[0]
    assert carbon_row["quality_limited_count"] == 120
    assert carbon_row["quality_eligible_count"] == 0


def test_lagged_associations_direction_and_bounds(benchmark_df):
    """Verify lag analysis calculates lags -24 to +24 and defines lag direction explicitly."""
    lag_df = compute_lagged_associations(
        benchmark_df,
        sig_x="temperature_c",
        sig_y="price_usd_per_mwh",
        max_lag=24,
    )
    assert len(lag_df) == (24 * 2 + 1) * 2  # 49 lags * 2 windows
    assert -24 in lag_df["lag_hours"].values
    assert 24 in lag_df["lag_hours"].values
    assert "lag_direction" in lag_df.columns
    assert "is_eligible" in lag_df.columns

    # Test lag > 0 direction definition
    lead_row = lag_df[lag_df["lag_hours"] == 5].iloc[0]
    assert "leads" in lead_row["lag_direction"]


def test_treatment_clipping_fitted_from_history_only(history_df, benchmark_df):
    """Verify clipping bounds are fit from pre-target history and preserve original values."""
    bounds = fit_historical_clipping_bounds(history_df, signals=["temperature_c", "price_usd_per_mwh"])
    assert "temperature_c" in bounds
    assert bounds["temperature_c"]["source_rows"] == len(history_df["temperature_c"].dropna())

    df_clipped, meta = create_clipped_variant(benchmark_df, bounds, signals=["temperature_c"])
    assert "temperature_c_orig" in df_clipped.columns
    assert "temperature_c_is_clipped" in df_clipped.columns
    # Original values remain untouched in _orig column
    pd.testing.assert_series_equal(df_clipped["temperature_c_orig"], benchmark_df["temperature_c"], check_names=False)


def test_causal_imputation_no_backward_fill(history_df):
    """Verify causal imputation uses forward fill and median fallback, never future values."""
    test_df = pd.DataFrame({
        "window_id": ["W1"] * 5,
        "timestamp_utc": pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC"),
        "temperature_c": [np.nan, 20.0, np.nan, 25.0, np.nan],
    })
    medians = {"temperature_c": 15.0}
    df_imp, meta = create_causal_imputed_variant(test_df, fallback_medians=medians, signals=["temperature_c"])

    vals = df_imp["temperature_c"].tolist()
    sources = df_imp["temperature_c_impute_source"].tolist()

    # Index 0 has no prior observation -> must use median fallback
    assert vals[0] == 15.0
    assert sources[0] == "historical_median_fallback"

    # Index 1 is original
    assert vals[1] == 20.0
    assert sources[1] == "original_observation"

    # Index 2 has prior 20.0 -> forward fill 20.0, not future 25.0
    assert vals[2] == 20.0
    assert sources[2] == "causal_forward_fill"

    # Index 3 is original
    assert vals[3] == 25.0

    # Index 4 forward fills 25.0
    assert vals[4] == 25.0
    assert sources[4] == "causal_forward_fill"


def test_sampling_manifests_equal_budget_and_no_duplicates(benchmark_df):
    """Verify deterministic equal budget (120h) and no duplicate timestamps within manifests."""
    manifests = generate_sampling_manifests(benchmark_df, budget_hours=120, seed=20261016)
    assert set(manifests.keys()) == {"ordinary_window", "event_stratified", "phase_aware"}

    for name, m in manifests.items():
        assert len(m) == 120
        assert not m["timestamp_utc"].duplicated().any()

    val_errs = validate_sampling_manifests(manifests, target_budget_hours=120)
    assert len(val_errs) == 0


def test_comparator_exactness_and_unsupported_status(benchmark_df, workload_df):
    """Verify exact small instance finds global optimum while full benchmark reports unsupported."""
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)
    res = run_p5_comparator_instances(benchmark_df, workload_df, constraints)

    full_res = res["full_benchmark"]
    assert full_res["status"] == "unsupported"
    assert full_res["optimal_objective"] is None

    small_res = res["supported_small_fixture"]
    assert small_res["status"] == "optimal"
    assert small_res["optimal_cost_usd"] is not None
    assert small_res["optimal_cost_usd"] > 0


def test_bootstrap_determinism_and_reproducibility():
    """Verify bootstrap 95% CI produces identical results with the same seed."""
    data = np.array([1.0, 2.0, 3.5, 4.0, 5.2, 6.1, 7.8, 8.4, 9.0, 10.5])
    ci1 = compute_paired_bootstrap_ci(data, seed=20261016, repetitions=500)
    ci2 = compute_paired_bootstrap_ci(data, seed=20261016, repetitions=500)
    assert ci1 == ci2
    assert ci1["ci_lower"] < ci1["mean"] < ci1["ci_upper"]


def test_gate_g5_audit_passes(repo_root):
    """Verify Gate G5-a comprehensive audit passes with 0 failures on generated artifacts."""
    audit_res = run_g5_audit(repo_root=repo_root)
    assert audit_res["status"] == "VERIFIED_PASS"
    assert audit_res["failure_count"] == 0
    assert len(audit_res["failure_reasons"]) == 0
