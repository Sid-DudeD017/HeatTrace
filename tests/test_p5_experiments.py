"""Tests for HeatTrace P5 experimental pipeline, E1-E4, comparator, and G5-a audit."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from heattrace.analysis.bootstrap import (
    compute_block_bootstrap_ci,
    compute_hourly_paired_signal_differences,
    compute_paired_bootstrap_ci,
    compute_policy_paired_differences,
)
from heattrace.analysis.characterization import (
    compute_distribution_summary,
    compute_lagged_associations,
    run_event_characterization_pipeline,
)
from heattrace.analysis.sampling import generate_outcome_sampling_manifests, validate_sampling_manifests
from heattrace.analysis.strategy_comparison import compare_evaluation_strategies
from heattrace.analysis.treatments import (
    build_treatment_variants,
    create_causal_imputed_variant,
    create_clipped_variant,
    fit_historical_treatment_parameters,
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


# -------------------------------------------------------------
# Issue 1: Treatment Fitting & No-Leakage Tests
# -------------------------------------------------------------

def test_treatment_fitting_strict_pre_cutoff_filtering(history_df):
    """Verify fitting rejects future/target observations and records strict accounting."""
    fit_info = fit_historical_treatment_parameters(
        history_df=history_df,
        fit_cutoff_utc="2024-06-05T07:00:00+00:00",
    )
    # hourly_caiso_v0 has 0 rows before 2024-06-05 07:00:00 UTC
    assert fit_info["status"] == "unsupported_insufficient_pre_target_history"
    assert fit_info["eligible_row_count"] == 0
    assert fit_info["excluded_target_future_row_count"] == 48


def test_treatment_fitting_fails_closed_when_future_data_injected():
    """Verify that injecting extreme future data does not affect pre-cutoff parameters."""
    pre_cutoff_dates = pd.date_range("2024-05-01", periods=10, freq="D", tz="UTC")
    synthetic_history = pd.DataFrame({
        "timestamp_utc": pre_cutoff_dates,
        "temperature_c": [15.0, 16.0, 17.0, 15.5, 16.5, 17.5, 16.0, 15.0, 16.2, 16.8],
        "price_usd_per_mwh": [25.0] * 10,
        "carbon_g_per_kwh": [150.0] * 10,
        "demand_mw": [20000.0] * 10,
        "net_generation_mw": [18000.0] * 10,
    })

    cutoff = "2024-06-05T07:00:00+00:00"
    fit1 = fit_historical_treatment_parameters(synthetic_history, fit_cutoff_utc=cutoff)
    assert fit1["status"] == "supported"
    base_temp_upper = fit1["bounds"]["temperature_c"]["upper_bound"]

    # Inject extreme target-period observation (e.g. 2024-07-02 with temp=999.0)
    injected_history = pd.concat([
        synthetic_history,
        pd.DataFrame({
            "timestamp_utc": [pd.to_datetime("2024-07-02T12:00:00+00:00")],
            "temperature_c": [999.0],
            "price_usd_per_mwh": [9999.0],
            "carbon_g_per_kwh": [9999.0],
            "demand_mw": [99999.0],
            "net_generation_mw": [99999.0],
        })
    ], ignore_index=True)

    fit2 = fit_historical_treatment_parameters(injected_history, fit_cutoff_utc=cutoff)
    # The extreme value was after cutoff, so bounds must be exactly identical
    assert fit2["bounds"]["temperature_c"]["upper_bound"] == base_temp_upper
    assert fit2["excluded_target_future_row_count"] == 1


def test_treatment_variant_marked_unsupported_when_pre_cutoff_empty(benchmark_df, history_df):
    """Verify clipped variant is cleanly labeled unsupported when no pre-target history exists."""
    res = build_treatment_variants(
        benchmark_df=benchmark_df,
        history_df=history_df,
        fit_cutoff_utc="2024-06-05T07:00:00+00:00",
    )
    assert res["metadata"]["clipped"]["status"] == "unsupported_insufficient_pre_target_history"
    # Raw variant remains supported
    assert res["metadata"]["raw"]["status"] == "supported"
    # Causal imputed variant remains supported because benchmark has 0 missing cells
    assert res["metadata"]["causal_imputed"]["status"] == "supported"


# -------------------------------------------------------------
# Issue 2: Outcome Sampling Tests (No Pseudo-Horizons)
# -------------------------------------------------------------

def test_sampling_manifests_use_original_outcome_hours(repo_root):
    """Verify outcome sampling preserves original window, timestamp, and hour_offset without pseudo-horizons."""
    m_path = repo_root / "data/manifests/p5_sampling_event_stratified.csv"
    assert m_path.exists()
    df_m = pd.read_csv(m_path)

    assert len(df_m) == 120
    assert "original_hour_offset" in df_m.columns
    assert "window_id" in df_m.columns

    # 60 control rows, 60 event rows
    assert (df_m["window_id"] == "CTRL_20240605").sum() == 60
    assert (df_m["window_id"] == "HW_20240702").sum() == 60

    # Ensure original hour offsets are preserved (e.g. 0, 2, ..., 118)
    ctrl_offsets = df_m[df_m["window_id"] == "CTRL_20240605"]["original_hour_offset"].tolist()
    assert ctrl_offsets[0] == 0
    assert ctrl_offsets[1] == 2
    assert ctrl_offsets[-1] == 118


def test_sampling_manifests_equal_budget_validation():
    """Verify all 3 manifests have exactly 120 selected outcome hours and no duplicates."""
    for s_name in ["ordinary_window", "event_stratified", "phase_aware"]:
        m = pd.read_csv(f"data/manifests/p5_sampling_{s_name}.csv")
        assert len(m) == 120
        assert not m["sample_index"].duplicated().any()


# -------------------------------------------------------------
# Issue 3: Policy Paired Analysis & Block-Bootstrap Tests
# -------------------------------------------------------------

def test_policy_paired_differences_completeness(repo_root):
    """Verify policy paired differences contains all 4 policies and 10 required metrics."""
    df_pp = pd.read_csv(repo_root / "data/results/p5_policy_paired_differences.csv")
    assert len(df_pp) == 40  # 4 policies * 10 metrics

    policies = set(df_pp["policy_name"].unique())
    assert policies == {"cost_first", "carbon_first", "balanced", "dro_inspired"}

    req_metrics = {
        "cost_usd", "emissions_kg", "sla_completion", "cvar_cost_90", "cvar_emissions_90",
        "peak_power_kw", "peak_concurrency", "unmet_energy_kwh", "deadline_misses", "violation_count"
    }
    assert set(df_pp["metric"].unique()) == req_metrics

    # Verify inferential status is descriptive_single_window_pair
    assert (df_pp["inferential_status"] == "descriptive_single_window_pair").all()


def test_block_bootstrap_determinism():
    """Verify block-bootstrap with 24h blocks is strictly deterministic given the project seed."""
    hourly_diffs = np.sin(np.linspace(0, 10, 120)) * 10.0
    b1 = compute_block_bootstrap_ci(hourly_diffs, block_length_hours=24, seed=20261016, repetitions=500)
    b2 = compute_block_bootstrap_ci(hourly_diffs, block_length_hours=24, seed=20261016, repetitions=500)

    assert b1 == b2
    assert b1["block_length_hours"] == 24
    assert b1["ci_lower"] < b1["mean"] < b1["ci_upper"]


# -------------------------------------------------------------
# Issue 4: Audit Fail-Closed Tests (Negative Mutation Testing)
# -------------------------------------------------------------

def test_g5_audit_passes_on_authentic_baseline(repo_root):
    """Verify G5-a passes cleanly on generated authentic repo state."""
    audit_res = run_g5_audit(repo_root=repo_root)
    assert audit_res["status"] == "VERIFIED_PASS"
    assert audit_res["failure_count"] == 0


def test_g5_audit_fails_on_missing_file(repo_root, tmp_path):
    """Verify G5-a fails closed when a required result artifact is missing."""
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    # Remove policy paired analysis artifact
    (t_data / "results/p5_policy_paired_differences.csv").unlink()

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("p5_policy_paired_differences.csv" in f for f in res["failure_reasons"])


def test_g5_audit_fails_on_tampered_hash(repo_root, tmp_path):
    """Verify G5-a fails closed when a result file content is tampered with."""
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    # Tamper with E2 comparison metrics
    e2_path = t_data / "results/p5_e2_policy_comparison_metrics.csv"
    e2_path.write_text(e2_path.read_text() + "\ntampered_row,0,0,0\n")

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("hash mismatch" in f.lower() or "incomplete" in f.lower() for f in res["failure_reasons"])


def test_g5_audit_fails_if_target_leakage_in_treatment_metadata(repo_root, tmp_path):
    """Verify G5-a fails closed if treatment fit cutoff is set after target window start."""
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    meta_path = t_data / "results/p5_treatment_variants_meta.json"
    with meta_path.open() as f:
        meta = json.load(f)
    meta["treatment_fit_info"]["fit_cutoff_utc"] = "2024-07-15T00:00:00+00:00"
    with meta_path.open("w") as f:
        json.dump(meta, f)

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("violates no-leakage" in f or "Target leakage" in f or "hash mismatch" in f for f in res["failure_reasons"])


# -------------------------------------------------------------
# Comparator Exactness Tests
# -------------------------------------------------------------

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
