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
from heattrace.manifests import write_atomic_csv, write_atomic_json
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
# Positive Functionality Tests
# -------------------------------------------------------------

def test_treatment_fitting_strict_pre_cutoff_filtering(history_df):
    """Verify fitting rejects future/target observations and records strict accounting."""
    fit_info = fit_historical_treatment_parameters(
        history_df=history_df,
        fit_cutoff_utc="2024-06-05T07:00:00+00:00",
    )
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
    assert res["metadata"]["raw"]["status"] == "supported"
    assert res["metadata"]["causal_imputed"]["status"] == "supported"


def test_sampling_manifests_use_original_outcome_hours(repo_root):
    """Verify outcome sampling preserves original window, timestamp, and hour_offset without pseudo-horizons."""
    m_path = repo_root / "data/manifests/p5_sampling_event_stratified.csv"
    assert m_path.exists()
    df_m = pd.read_csv(m_path)

    assert len(df_m) == 120
    assert "original_hour_offset" in df_m.columns
    assert "window_id" in df_m.columns
    assert "source_outcome_path" in df_m.columns
    assert "source_outcome_sha256" in df_m.columns

    assert (df_m["window_id"] == "CTRL_20240605").sum() == 60
    assert (df_m["window_id"] == "HW_20240702").sum() == 60


def test_sampling_manifests_equal_budget_validation():
    """Verify all 3 manifests have exactly 120 selected outcome hours and no duplicates."""
    for s_name in ["ordinary_window", "event_stratified", "phase_aware"]:
        m = pd.read_csv(f"data/manifests/p5_sampling_{s_name}.csv")
        assert len(m) == 120
        assert not m["sample_index"].duplicated().any()


def test_policy_paired_differences_completeness(repo_root):
    """Verify policy paired differences contains all 4 policies and 10 required metrics."""
    df_pp = pd.read_csv(repo_root / "data/results/p5_policy_paired_differences.csv")
    assert len(df_pp) == 40

    policies = set(df_pp["policy_name"].unique())
    assert policies == {"cost_first", "carbon_first", "balanced", "dro_inspired"}

    req_metrics = {
        "cost_usd", "emissions_kg", "sla_completion", "cvar_cost_90", "cvar_emissions_90",
        "peak_power_kw", "peak_concurrency", "unmet_energy_kwh", "deadline_misses", "violation_count"
    }
    assert set(df_pp["metric"].unique()) == req_metrics
    assert (df_pp["inferential_status"] == "descriptive_single_window_pair").all()


def test_block_bootstrap_determinism():
    """Verify block-bootstrap with 24h blocks is strictly deterministic given the project seed."""
    hourly_diffs = np.sin(np.linspace(0, 10, 120)) * 10.0
    b1 = compute_block_bootstrap_ci(hourly_diffs, block_length_hours=24, seed=20261016, repetitions=500)
    b2 = compute_block_bootstrap_ci(hourly_diffs, block_length_hours=24, seed=20261016, repetitions=500)

    assert b1 == b2
    assert b1["block_length_hours"] == 24
    assert b1["ci_lower"] < b1["mean"] < b1["ci_upper"]


def test_atomic_write_interruption_preserves_previous_destination(tmp_path):
    """Verify atomic write failure leaves the destination file intact."""
    dest = tmp_path / "important.json"
    dest.write_text('{"safe": true}\n', encoding="utf-8")

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        write_atomic_json(dest, {"bad": Unserializable()})

    # File must still exist with original content
    assert dest.read_text(encoding="utf-8") == '{"safe": true}\n'


def test_g5_audit_passes_on_authentic_baseline(repo_root):
    """Verify G5-a passes cleanly on generated authentic repo state."""
    audit_res = run_g5_audit(repo_root=repo_root)
    assert audit_res["status"] == "VERIFIED_PASS"
    assert audit_res["failure_count"] == 0


# -------------------------------------------------------------
# Negative Mutation Tests (18 Fail-Closed Checks)
# -------------------------------------------------------------

def test_neg_01_missing_schedule_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    t_runs = tmp_path / "runs"
    shutil.copytree(repo_root / "runs", t_runs)
    (t_runs / "p4_v0/HW_20240702/cost_first/schedule.parquet").unlink()

    # Pass non-existent runs dir
    res = run_g5_audit(repo_root=tmp_path, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Required schedule artifact missing" in f for f in res["failure_reasons"])


def test_neg_02_missing_hourly_outcome_file_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    (t_data / "results/p5_hourly_outcomes/hourly_outcomes_CTRL_20240605_cost_first.csv").unlink()

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("hourly_outcomes_CTRL_20240605_cost_first.csv" in f for f in res["failure_reasons"])


def test_neg_03_nonexistent_code_revision_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_p = t_data / "manifests/p5_dataset_manifest.json"
    m_data = json.loads(m_p.read_text())
    m_data["source_code_commit"] = "0000000000000000000000000000000000000000"
    m_p.write_text(json.dumps(m_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("source_code_commit does not exist" in f for f in res["failure_reasons"])


def test_neg_04_source_hash_mismatch_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_p = t_data / "manifests/p5_dataset_manifest.json"
    m_data = json.loads(m_p.read_text())
    m_data["source_code_provenance"]["modules"]["src/heattrace/analysis/treatments.py"]["sha256"] = "f" * 64
    m_p.write_text(json.dumps(m_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("P5 source module hash mismatch" in f for f in res["failure_reasons"])


def test_neg_05_configuration_hash_mismatch_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_p = t_data / "manifests/p5_dataset_manifest.json"
    m_data = json.loads(m_p.read_text())
    m_data["input_files"]["configs/p5.yaml"]["sha256"] = "0" * 64
    m_p.write_text(json.dumps(m_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Input file hash mismatch for configs/p5.yaml" in f for f in res["failure_reasons"])


def test_neg_06_unequal_sampling_budget_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_path = t_data / "manifests/p5_sampling_ordinary_window.csv"
    df = pd.read_csv(m_path).head(100)  # cut to 100 rows
    df.to_csv(m_path, index=False)

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("budget != 120" in f for f in res["failure_reasons"])


def test_neg_07_workload_digest_mismatch_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_p = t_data / "manifests/p5_dataset_manifest.json"
    m_data = json.loads(m_p.read_text())
    m_data["input_files"]["data/workloads/workload_trace_v0.parquet"]["sha256"] = "1" * 64
    m_p.write_text(json.dumps(m_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Input file hash mismatch for data/workloads/workload_trace_v0.parquet" in f for f in res["failure_reasons"])


def test_neg_08_forecast_digest_mismatch_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_p = t_data / "manifests/p5_dataset_manifest.json"
    m_data = json.loads(m_p.read_text())
    m_data["input_files"]["data/forecasts/p4_historical_forecasts_v0.parquet"]["sha256"] = "2" * 64
    m_p.write_text(json.dumps(m_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Input file hash mismatch for data/forecasts/p4_historical_forecasts_v0.parquet" in f for f in res["failure_reasons"])


def test_neg_09_sampled_timestamp_mismatch_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_path = t_data / "manifests/p5_sampling_ordinary_window.csv"
    df = pd.read_csv(m_path)
    df.loc[0, "timestamp_utc"] = "2099-01-01T00:00:00+00:00"
    df.to_csv(m_path, index=False)

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Timestamp mismatch" in f for f in res["failure_reasons"])


def test_neg_10_duplicate_sample_identity_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    m_path = t_data / "manifests/p5_sampling_ordinary_window.csv"
    df = pd.read_csv(m_path)
    df.loc[1, "sample_index"] = df.loc[0, "sample_index"]
    df.to_csv(m_path, index=False)

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("duplicate sample indices" in f for f in res["failure_reasons"])


def test_neg_11_unsupported_clipping_presented_as_success_fails(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    meta_p = t_data / "results/p5_treatment_variants_meta.json"
    m_data = json.loads(meta_p.read_text())
    m_data["variants_metadata"]["clipped"]["status"] = "supported"
    meta_p.write_text(json.dumps(m_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Historical clipping variant must be marked 'unsupported_insufficient_pre_target_history'" in f for f in res["failure_reasons"])


def test_neg_12_removed_carbon_label_causes_failure(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    pp_p = t_data / "results/p5_policy_paired_differences.csv"
    df = pd.read_csv(pp_p)
    df["carbon_quality_label"] = "clean_primary_evidence"
    df.to_csv(pp_p, index=False)

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("quality_limited_sensitivity_only" in f for f in res["failure_reasons"])


def test_neg_13_unsupported_comparator_with_fake_objective_fails(repo_root, tmp_path):
    import shutil
    t_data = tmp_path / "data"
    shutil.copytree(repo_root / "data", t_data)
    comp_p = t_data / "results/p5_comparator_results.json"
    c_data = json.loads(comp_p.read_text())
    c_data["full_benchmark"]["optimal_objective"] = 123.45
    comp_p.write_text(json.dumps(c_data))

    res = run_g5_audit(repo_root=repo_root, data_dir=t_data)
    assert res["status"] == "VERIFIED_FAIL"
    assert any("Full benchmark comparator must report status 'unsupported' without objective" in f for f in res["failure_reasons"])
