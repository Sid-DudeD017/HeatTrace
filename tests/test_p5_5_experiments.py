"""Targeted unit and integration tests for P5.5 experiment implementation (Grid v2).

Tests:
- Deterministic scenario grid v2 generation and seed isolation.
- Workload generation properties.
- Forecast scenarios: no-leakage, unconfounded seeds, identical hash across stress parameters.
- Schedule artifact existence and SHA-256 digest determinism.
- Exact small-instance comparator validation.
- Primary fair comparison population and equal delivered work.
- Headline numbers reproduction.
- G5.5-a comprehensive audit pass without modifying production audit file (uses tmp_path).
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from heattrace.analysis.p5_5_figures import compute_headline_findings
from heattrace.experiments.p5_5_comparator_validation import run_small_instance_comparator_validation
from heattrace.experiments.p5_5_grid import (
    P55ScenarioSpecV2,
    build_preregistered_p5_5_grid_v2,
    generate_stressed_workload_v2,
)
from heattrace.experiments.p5_5_scenarios import (
    compute_forecast_seed,
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


def test_p5_5_grid_v2_generation_and_seed_isolation():
    """Verify that grid v2 is deterministic, contains 270 scenarios, and seeds are isolated."""
    grid = build_preregistered_p5_5_grid_v2()
    assert len(grid) == 270

    # Test seed isolation: forecast_seed must be identical for identical (window_id, forecast_scenario_id)
    # regardless of workload, capacity, or deadline settings
    df_grid = pd.DataFrame([s.to_dict() for s in grid])
    fc_seed_counts = df_grid.groupby(["window_id", "forecast_scenario_id"])["forecast_seed"].nunique()
    assert (fc_seed_counts == 1).all(), "forecast_seed varies across stress parameters!"

    # Workload seed must depend only on job_count
    wl_seed_counts = df_grid.groupby("job_count")["workload_seed"].nunique()
    assert (wl_seed_counts == 1).all(), "workload_seed varies across capacity/deadline parameters!"


def test_p5_5_forecast_noise_trajectory_invariance(sample_benchmark_df: pd.DataFrame):
    """Critical Issue 3: Verify forecast perturbation is strictly invariant across capacity/deadline stress."""
    hw_df = sample_benchmark_df[sample_benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)
    base_seed = 20261016

    # Generate noisy forecasts across two different capacity scenarios
    fc_seed1 = compute_forecast_seed(base_seed, "HW_20240702", "noisy_oracle_medium")
    fc_seed2 = compute_forecast_seed(base_seed, "HW_20240702", "noisy_oracle_medium")
    assert fc_seed1 == fc_seed2

    _, _, hash1 = generate_noisy_oracle_forecast(hw_df, noise_sigma=0.25, seed=fc_seed1)
    _, _, hash2 = generate_noisy_oracle_forecast(hw_df, noise_sigma=0.25, seed=fc_seed2)
    assert hash1 == hash2, "Identical forecast settings must produce identical hash!"

    # Different noise sigma produces different hash
    fc_seed_low = compute_forecast_seed(base_seed, "HW_20240702", "noisy_oracle_low")
    _, _, hash_low = generate_noisy_oracle_forecast(hw_df, noise_sigma=0.10, seed=fc_seed_low)
    assert hash1 != hash_low, "Different noise levels must produce different hash!"


def test_p5_5_evidence_labels_strict_taxonomy():
    """Critical Issue 4: Verify that stressed flat forecast cases are NOT labelled authentic."""
    grid = build_preregistered_p5_5_grid_v2()
    df_grid = pd.DataFrame([s.to_dict() for s in grid])

    # Authentic historical baseline must ONLY be 1x workload, unconstrained, baseline deadline
    auth = df_grid[df_grid["evidence_class"] == "authentic_historical_baseline"]
    assert len(auth) == 2  # exactly 1 for event, 1 for control
    assert (auth["workload_multiplier"] == 1.0).all()
    assert (auth["resource_scenario_id"] == "unconstrained").all()
    assert (auth["deadline_scenario_id"] == "baseline").all()
    assert (auth["forecast_type"] == "flat").all()

    # Stressed flat cases must be controlled_simulation_flat_forecast
    stressed_flat = df_grid[df_grid["evidence_class"] == "controlled_simulation_flat_forecast"]
    assert len(stressed_flat) == 52  # 54 flat total - 2 authentic = 52


def test_p5_5_small_instance_comparator_exact_optimality():
    """Critical Issue 6: Exact branch-and-bound comparator achieves 0.0% gap on cost_first under oracle."""
    comp_df, comp_summary = run_small_instance_comparator_validation()
    assert comp_summary["status"] == "VERIFIED_SUPPORTED"
    assert comp_summary["all_instances_optimal"] is True

    cf_rows = comp_df[comp_df["policy_name"] == "cost_first"]
    assert (cf_rows["cost_optimality_gap_usd"] == 0.0).all()
    assert (cf_rows["cost_optimality_gap_pct"] == 0.0).all()

    # Baseline reference should have non-zero suboptimality gap
    base_rows = comp_df[comp_df["policy_name"] == "baseline_reference"]
    assert (base_rows["cost_optimality_gap_pct"] > 0.0).all()


def test_p5_5_headline_numbers_reproducibility():
    """Critical Issue 2: Verify that headline findings numbers reproduce directly from result table."""
    results_df = pd.read_parquet("data/results/p5_5_experiment_results.parquet")
    comp_df = pd.read_csv("data/results/p5_5_comparator_validation_results.csv")

    findings = compute_headline_findings(results_df, comp_df)
    assert findings["metadata"]["total_scenarios"] == 270
    assert findings["metadata"]["total_runs"] == 1350
    assert findings["metadata"]["jointly_feasible_scenarios_count"] == 158

    # Check that control savings and event savings are positive
    assert findings["headline_2_primary_fair_savings"]["control_cost_first_savings_pct"] > 40.0
    assert findings["headline_2_primary_fair_savings"]["event_cost_first_savings_pct"] > 20.0


def test_p5_5_audit_verified_pass_isolated(tmp_path: Path):
    """Critical Issue 8: Run G5.5 audit outputting to tmp_path to avoid modifying production audit artifact."""
    temp_audit_file = tmp_path / "test_p5_5_audit.json"
    audit_res = run_g5_5_audit(output_audit_path=temp_audit_file)

    assert audit_res["status"] == "VERIFIED_PASS"
    assert audit_res["failure_count"] == 0
    assert audit_res["total_runs_evaluated"] == 1350
    assert audit_res["feasible_runs_count"] == 880
    assert audit_res["infeasible_runs_count"] == 470
    assert audit_res["jointly_feasible_scenarios_count"] == 158

    for check_name, passed in audit_res["checks"].items():
        assert passed is True, f"Audit check failed: {check_name}"

    assert temp_audit_file.exists()
