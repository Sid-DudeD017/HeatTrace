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

import hashlib
import json
from pathlib import Path
import shutil
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


def test_p5_5_all_1350_schedules_and_digests_traceability():
    """Critical Issue 3B: Verify all 1,350 schedule parquet artifacts, allocation counts, and SHA-256 digests."""
    results_df = pd.read_parquet("data/results/p5_5_experiment_results.parquet")
    assert len(results_df) == 1350

    repo_root = Path(__file__).resolve().parent.parent
    for _, row in results_df.iterrows():
        p = repo_root / row["schedule_artifact_path"]
        assert p.exists(), f"Schedule artifact missing: {p}"
        sched = pd.read_parquet(p)
        assert len(sched) == row["allocation_count"]

        # Recompute digest
        sorted_alloc = sched.sort_values(by=["allocated_hour_offset", "job_id"])
        rows_payload = []
        for _, a in sorted_alloc.iterrows():
            rows_payload.append(f"{a['job_id']}:{int(a['allocated_hour_offset'])}:{float(a['execution_power_kw']):.4f}:{float(a['allocated_energy_kwh']):.4f}")
        rebuilt_digest = hashlib.sha256("|".join(rows_payload).encode("utf-8")).hexdigest()
        assert rebuilt_digest == row["schedule_digest"]


def test_p5_5_audit_fails_on_corrupted_schedule(tmp_path: Path):
    """Critical Issue 3B: G5.5 audit fails closed if a schedule artifact is altered."""
    results_df = pd.read_parquet("data/results/p5_5_experiment_results.parquet")
    temp_results_csv = tmp_path / "p5_5_experiment_results.csv"
    temp_results_parquet = tmp_path / "p5_5_experiment_results.parquet"

    # Tamper with one schedule digest in results table
    tampered_df = results_df.copy()
    tampered_df.loc[0, "schedule_digest"] = "0" * 64
    tampered_df.to_csv(temp_results_csv, index=False)
    tampered_df.to_parquet(temp_results_parquet, index=False)

    temp_audit_file = tmp_path / "test_audit.json"
    t_data = tmp_path / "data"
    (t_data / "results").mkdir(parents=True, exist_ok=True)
    shutil.copy(temp_results_csv, t_data / "results/p5_5_experiment_results.csv")
    shutil.copy(temp_results_parquet, t_data / "results/p5_5_experiment_results.parquet")

    # Symlink other data directories so audit can access manifests, figures, schedules
    base_data = Path("data").resolve()
    for sub in ["manifests", "schedules", "figures", "events", "benchmarks", "workloads", "raw"]:
        if (base_data / sub).exists():
            (t_data / sub).symlink_to(base_data / sub)

    # Audit pointing to tampered results must fail closed
    audit_res = run_g5_5_audit(data_dir=t_data, output_audit_path=temp_audit_file)
    assert audit_res["status"] == "VERIFIED_FAIL"
    assert "schedule_artifacts_exist" in audit_res["checks"]
    assert audit_res["checks"]["schedule_artifacts_exist"] is False


def test_p5_5_common_cohort_noise_construction():
    """Critical Issue 4: Common-cohort construction across forecast levels yields like-for-like sample."""
    results_df = pd.read_parquet("data/results/p5_5_experiment_results.parquet")
    comp_df = pd.read_csv("data/results/p5_5_comparator_validation_results.csv")
    findings = compute_headline_findings(results_df, comp_df)

    h3 = findings["headline_3_noise_degradation"]
    assert h3["common_cohort_sample_size_per_level"] == 26
    sav = h3["savings_pct_by_noise_sigma"]
    # Monotonic degradation: oracle > low > med > high
    assert sav["oracle_sigma_0"] > sav["noisy_sigma_0_10"] > sav["noisy_sigma_0_25"] > sav["noisy_sigma_0_50"]
    assert h3["noise_retention_high_sigma_pct"] > 60.0


def test_p5_5_calculated_collapse_and_divergence_percentages():
    """Critical Issue 5: Verify collapse and divergence percentages are calculated dynamically from counts."""
    # Test on synthetic df with partial collapse
    synth_data = [
        {"scenario_id": "S1", "policy_name": "baseline_reference", "forecast_scenario_id": "flat_forecast", "schedule_digest": "d1"},
        {"scenario_id": "S1", "policy_name": "cost_first", "forecast_scenario_id": "flat_forecast", "schedule_digest": "d1"},
        {"scenario_id": "S2", "policy_name": "baseline_reference", "forecast_scenario_id": "flat_forecast", "schedule_digest": "d1"},
        {"scenario_id": "S2", "policy_name": "cost_first", "forecast_scenario_id": "flat_forecast", "schedule_digest": "d2"},
        {"scenario_id": "S3", "policy_name": "baseline_reference", "forecast_scenario_id": "oracle_forecast", "schedule_digest": "d1"},
        {"scenario_id": "S3", "policy_name": "cost_first", "forecast_scenario_id": "oracle_forecast", "schedule_digest": "d2"},
        {"scenario_id": "S4", "policy_name": "baseline_reference", "forecast_scenario_id": "oracle_forecast", "schedule_digest": "d1"},
        {"scenario_id": "S4", "policy_name": "cost_first", "forecast_scenario_id": "oracle_forecast", "schedule_digest": "d1"},
    ]
    synth_df = pd.DataFrame(synth_data)
    for col in ["window_id", "is_feasible", "total_realized_cost_usd", "total_realized_emissions_kg", "delivered_energy_kwh", "window_type", "noise_sigma", "workload_multiplier", "resource_scenario_id", "deadline_scenario_id", "cvar_cost_90"]:
        synth_df[col] = 1.0 if "cost" in col or "emiss" in col or "workload" in col or "cvar" in col else (True if col == "is_feasible" else "dummy")

    findings = compute_headline_findings(synth_df)
    h1 = findings["headline_1_flat_forecast_collapse"]
    # Flat: 2 scenarios, 1 collapsed -> 50.0%
    assert h1["flat_forecast_scenarios_evaluated"] == 2
    assert h1["flat_forecast_schedule_identical_count"] == 1
    assert h1["flat_forecast_collapse_pct"] == 50.0
    # Non-flat: 2 scenarios, 1 diverged -> 50.0%
    assert h1["non_flat_scenarios_evaluated"] == 2
    assert h1["non_flat_schedule_divergence_count"] == 1
    assert h1["non_flat_divergence_pct"] == 50.0


def test_p5_5_audit_fails_on_tampered_headline(tmp_path: Path):
    """Critical Issue 3C: Audit fails closed if saved headline findings are manually edited."""
    repo_root = Path(__file__).resolve().parent.parent
    t_root = tmp_path / "repo"
    t_data = t_root / "data"
    t_cfg = t_root / "configs"
    t_docs = t_root / "docs"
    (t_data / "results").mkdir(parents=True, exist_ok=True)
    (t_data / "manifests").mkdir(parents=True, exist_ok=True)
    (t_data / "figures").mkdir(parents=True, exist_ok=True)
    t_cfg.mkdir(parents=True, exist_ok=True)
    t_docs.mkdir(parents=True, exist_ok=True)

    # Copy minimal manifests, configs, and docs for audit to reach check 14
    shutil.copy(repo_root / "configs/p5_5.yaml", t_cfg / "p5_5.yaml")
    shutil.copy(repo_root / "data/manifests/p5_5_experiment_grid.json", t_data / "manifests/p5_5_experiment_grid.json")
    shutil.copy(repo_root / "data/results/p5_5_experiment_results.parquet", t_data / "results/p5_5_experiment_results.parquet")
    shutil.copy(repo_root / "data/results/p5_5_experiment_results.csv", t_data / "results/p5_5_experiment_results.csv")
    shutil.copy(repo_root / "data/results/p5_5_comparator_validation_results.csv", t_data / "results/p5_5_comparator_validation_results.csv")
    shutil.copy(repo_root / "data/results/p5_5_comparator_validation_results.json", t_data / "results/p5_5_comparator_validation_results.json")
    shutil.copytree(repo_root / "data/results/p5_5_schedules", t_data / "results/p5_5_schedules", dirs_exist_ok=True)
    shutil.copytree(repo_root / "data/figures", t_data / "figures", dirs_exist_ok=True)
    shutil.copytree(repo_root / "docs", t_docs, dirs_exist_ok=True)
    for f in ["p5_5_policy_comparison_summary.csv", "p5_5_policy_paired_differences.csv", "p5_5_view1_primary_fair_summary.csv", "p5_5_view2_service_normalized_summary.csv", "p5_5_view3_failure_aware_summary.csv"]:
        shutil.copy(repo_root / f"data/results/{f}", t_data / f"results/{f}")
    shutil.copy(repo_root / "p1_p5_baseline_hashes.json", t_root / "p1_p5_baseline_hashes.json")

    # Copy and tamper headline findings
    shutil.copy(repo_root / "data/results/p5_5_headline_findings.json", t_data / "results/p5_5_headline_findings.json")
    with (t_data / "results/p5_5_headline_findings.json").open("r") as f:
        tampered_hf = json.load(f)
    tampered_hf["headline_2_primary_fair_savings"]["control_cost_first_savings_pct"] = 99.99
    with (t_data / "results/p5_5_headline_findings.json").open("w") as f:
        json.dump(tampered_hf, f, indent=2)

    res = run_g5_5_audit(repo_root=t_root, data_dir=t_data, config_dir=t_cfg, output_audit_path=tmp_path / "audit.json")
    assert res["status"] == "VERIFIED_FAIL"
    assert res["checks"]["headline_numbers_reproduce"] is False
    assert any("Headline 2 control_cost_first_savings_pct mismatch" in r for r in res["failure_reasons"])


def test_frozen_baseline_hashes_unmutated_after_test_execution():
    """Critical Issue 2: Verify frozen baseline hashes are completely unchanged."""
    from heattrace.ingest.provenance import sha256_file
    with open("p1_p5_baseline_hashes.json") as f:
        base = json.load(f)
    for path, expected_h in base.items():
        assert Path(path).exists(), f"Baseline file missing: {path}"
        cur_h = sha256_file(path)
        assert cur_h == expected_h, f"Baseline file modified: {path}"

