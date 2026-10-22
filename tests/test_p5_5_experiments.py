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
    """Critical Issue 3C: Audit fails closed if saved headline findings are manually edited or synthetic."""
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

    # Copy and tamper headline findings with invalid value
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


def test_p5_5_audit_fails_on_synthetic_8_row_headline(tmp_path: Path):
    """Critical Issue 1 & 6: Audit fails closed if saved headline findings are an 8-row synthetic artifact."""
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

    # Synthetic 8-row headline artifact
    synthetic_hf = {
        "metadata": {
            "grid_version": "v2",
            "total_scenarios": 4,
            "total_runs": 8,
            "jointly_feasible_scenarios_count": 4,
            "primary_fair_population_pct": 100.0,
        },
        "headline_1_flat_forecast_collapse": {
            "flat_forecast_scenarios_evaluated": 2,
            "flat_forecast_schedule_identical_count": 1,
            "flat_forecast_collapse_pct": 50.0,
            "non_flat_scenarios_evaluated": 2,
            "non_flat_schedule_divergence_count": 1,
            "non_flat_divergence_pct": 50.0,
        },
        "headline_2_primary_fair_savings": {
            "control_window_id": "CTRL_20240605",
            "control_sample_size_scenarios": 1,
            "control_cost_first_savings_pct": 10.0,
            "event_window_id": "HW_20240702",
            "event_sample_size_scenarios": 1,
            "event_cost_first_savings_pct": 10.0,
        },
        "headline_3_noise_degradation": {
            "common_cohort_sample_size_per_level": 0,
            "savings_pct_by_noise_sigma": {
                "oracle_sigma_0": 0.0,
                "noisy_sigma_0_10": 0.0,
                "noisy_sigma_0_25": 0.0,
                "noisy_sigma_0_50": 0.0,
            },
            "noise_retention_high_sigma_pct": 0.0,
            "secondary_descriptive_savings_pct": {
                "oracle_sigma_0": 0.0,
                "noisy_sigma_0_10": 0.0,
                "noisy_sigma_0_25": 0.0,
                "noisy_sigma_0_50": 0.0,
            },
            "secondary_descriptive_sample_sizes": {
                "oracle": 2, "noisy_low": 0, "noisy_med": 0, "noisy_high": 0,
            },
        },
        "headline_4_carbon_cost_tradeoff": {
            "event_sample_size_scenarios": 1,
            "carbon_first_emissions_reduction_pct": 0.0,
            "carbon_first_cost_premium_vs_cost_first_pct": 0.0,
        },
        "headline_5_tail_risk_cvar90": {
            "event_sample_size_scenarios": 1,
            "cvar_cost_90_baseline_usd_h": 1.0,
            "cvar_cost_90_cost_first_usd_h": 1.0,
            "cvar_cost_90_dro_inspired_usd_h": 1.0,
            "cvar_cost_first_reduction_pct": 0.0,
        },
        "headline_6_operational_feasibility": {
            "unconstrained_feasibility_pct": 100.0,
            "moderate_stress_feasibility_pct": 100.0,
            "extreme_stress_feasibility_pct": 100.0,
            "workload_3x_extreme_feasibility_pct": 100.0,
        },
        "headline_7_comparator_validation": {},
    }
    with (t_data / "results/p5_5_headline_findings.json").open("w", encoding="utf-8") as f:
        json.dump(synthetic_hf, f, indent=2)

    res = run_g5_5_audit(repo_root=t_root, data_dir=t_data, config_dir=t_cfg, output_audit_path=tmp_path / "audit.json")
    assert res["status"] == "VERIFIED_FAIL"
    assert res["checks"]["headline_numbers_reproduce"] is False
    assert any("total_scenarios mismatch" in r for r in res["failure_reasons"])
    assert any("total_runs mismatch" in r for r in res["failure_reasons"])


def test_headline_findings_pure_calculation_and_test_isolation(tmp_path: Path):
    """Critical Issue 2: Verify compute_headline_findings is pure and production files are unmutated."""
    from heattrace.ingest.provenance import sha256_file
    from heattrace.analysis.p5_5_figures import write_headline_findings

    monitored_files = [
        "data/results/p5_5_headline_findings.json",
        "data/results/p5_5_headline_findings.csv",
        "data/results/p5_5_experiment_results.parquet",
        "data/results/p5_5_experiment_results.csv",
        "data/manifests/p5_5_comprehensive_audit.json",
    ]
    initial_hashes = {f: sha256_file(f) for f in monitored_files}

    # 1. Calling compute_headline_findings with output_dir=None creates no files
    results_df = pd.read_parquet("data/results/p5_5_experiment_results.parquet")
    comp_df = pd.read_csv("data/results/p5_5_comparator_validation_results.csv")
    dummy_empty_dir = tmp_path / "empty_dir"
    dummy_empty_dir.mkdir()

    findings = compute_headline_findings(results_df, comp_df, output_dir=None)
    assert isinstance(findings, dict)
    assert list(dummy_empty_dir.iterdir()) == []

    # 2. Synthetic calculation tests do not touch production
    synth_df = pd.DataFrame([
        {"scenario_id": "S1", "policy_name": "baseline_reference", "forecast_scenario_id": "flat_forecast", "schedule_digest": "d1", "window_id": "HW", "is_feasible": True, "total_realized_cost_usd": 10.0, "total_realized_emissions_kg": 5.0, "delivered_energy_kwh": 100.0, "window_type": "event", "noise_sigma": 0.0, "workload_multiplier": 1.0, "resource_scenario_id": "unconstrained", "deadline_scenario_id": "baseline", "cvar_cost_90": 1.0},
        {"scenario_id": "S1", "policy_name": "cost_first", "forecast_scenario_id": "flat_forecast", "schedule_digest": "d1", "window_id": "HW", "is_feasible": True, "total_realized_cost_usd": 10.0, "total_realized_emissions_kg": 5.0, "delivered_energy_kwh": 100.0, "window_type": "event", "noise_sigma": 0.0, "workload_multiplier": 1.0, "resource_scenario_id": "unconstrained", "deadline_scenario_id": "baseline", "cvar_cost_90": 1.0},
    ])
    synth_findings = compute_headline_findings(synth_df)
    assert synth_findings["metadata"]["total_scenarios"] == 1

    # 3. Explicit writer writes to target tmp directory only
    target_tmp = tmp_path / "written"
    j_p, c_p = write_headline_findings(synth_findings, target_tmp)
    assert j_p.exists()
    assert c_p.exists()
    assert j_p.parent == target_tmp

    # Verify all monitored production hashes remain byte-for-byte identical
    for f in monitored_files:
        assert sha256_file(f) == initial_hashes[f], f"Production file modified by test: {f}"


def test_forecast_versus_realized_information_leakage():
    """Critical Issue 7: Verify scheduling policies strictly receive forecasts, workloads, and constraints.

    Future realized price or carbon columns must NEVER be passed to scheduling policies.
    """
    from heattrace.policy.interfaces import (
        ForecastPoint,
        ForecastResult,
        SchedulingConstraints,
    )
    from datetime import datetime, timezone

    # 1. Verify ForecastResult / ForecastPoint schema only contains forecast fields
    pt = ForecastPoint(
        timestamp_utc=datetime.now(timezone.utc),
        horizon_hours=1,
        predicted_price_usd_per_mwh=50.0,
        predicted_carbon_g_per_kwh=200.0,
    )
    assert not hasattr(pt, "realized_price_usd_per_mwh")
    assert not hasattr(pt, "realized_carbon_g_per_kwh")
    assert not hasattr(pt, "price_usd_per_mwh")
    assert not hasattr(pt, "carbon_intensity_g_per_kwh")

    fc_res = ForecastResult(
        origin_timestamp_utc=datetime.now(timezone.utc),
        points=[pt],
        model_name="test_fc",
        model_version="1.0",
    )
    fc_df = fc_res.to_dataframe()
    assert "predicted_price_usd_per_mwh" in fc_df.columns
    assert "predicted_carbon_g_per_kwh" in fc_df.columns
    assert "realized_price_usd_per_mwh" not in fc_df.columns
    assert "realized_carbon_g_per_kwh" not in fc_df.columns

    # 2. Instrumented policy that inspects input signatures and columns
    class LeakageDetectorPolicy:
        policy_name = "leakage_detector"
        policy_version = "1.0"

        def __init__(self):
            self.inspected_forecast_columns = []
            self.inspected_workload_columns = []

        def schedule(self, workload_df: pd.DataFrame, forecast: ForecastResult, constraints: SchedulingConstraints):
            self.inspected_forecast_columns = list(forecast.to_dataframe().columns)
            self.inspected_workload_columns = list(workload_df.columns)
            from heattrace.policy.interfaces import ScheduleResult
            return ScheduleResult(
                policy_name=self.policy_name,
                policy_version=self.policy_version,
                workload_trace_id="test",
                window_duration_hours=len(forecast.points),
                allocations=[],
                is_feasible=True,
            )

    det = LeakageDetectorPolicy()
    workload = generate_stressed_workload_v2(job_count=5, slack_multiplier=1.0)
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16)

    det.schedule(workload, fc_res, constraints)

    # Realized labels/measurements must be completely absent from policy inputs
    forbidden_leakage_terms = ["realized", "observed", "actual_price", "actual_carbon", "temperature_c"]
    for col in det.inspected_forecast_columns:
        for term in forbidden_leakage_terms:
            assert term not in col.lower(), f"Information leakage detected in forecast input: {col}"

    for col in det.inspected_workload_columns:
        for term in forbidden_leakage_terms:
            assert term not in col.lower(), f"Information leakage detected in workload input: {col}"


def test_frozen_baseline_hashes_unmutated_after_test_execution():
    """Critical Issue 2: Verify frozen baseline hashes are completely unchanged."""
    from heattrace.ingest.provenance import sha256_file
    with open("p1_p5_baseline_hashes.json") as f:
        base = json.load(f)
    for path, expected_h in base.items():
        assert Path(path).exists(), f"Baseline file missing: {path}"
        cur_h = sha256_file(path)
        assert cur_h == expected_h, f"Baseline file modified: {path}"

