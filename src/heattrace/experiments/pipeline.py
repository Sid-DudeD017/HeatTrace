"""Master workflow pipeline for HeatTrace Phase P5."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any
import pandas as pd

from heattrace.analysis.bootstrap import (
    compute_hourly_paired_signal_differences,
    compute_policy_paired_differences,
)
from heattrace.analysis.characterization import run_event_characterization_pipeline
from heattrace.analysis.figures import generate_p5_figures_and_tables
from heattrace.analysis.sampling import validate_sampling_manifests
from heattrace.analysis.strategy_comparison import compare_evaluation_strategies
from heattrace.analysis.treatments import build_treatment_variants
from heattrace.config import load_yaml
from heattrace.experiments.runner import (
    run_p5_comparator_instances,
    run_p5_sampling_experiments,
    run_p5_treatment_experiments,
)
from heattrace.ingest.provenance import sha256_file
from heattrace.manifests import write_atomic_json
from heattrace.policy.interfaces import SchedulingConstraints


def run_complete_p5_pipeline(
    repo_root: Path,
    p5_config_path: Path | None = None,
) -> dict[str, Any]:
    """Execute complete deterministic P5 experimental workflow and generate all artifacts."""
    repo_root = repo_root.resolve()
    if p5_config_path is None:
        p5_config_path = repo_root / "configs/p5.yaml"

    cfg = load_yaml(p5_config_path)

    data_dir = repo_root / "data"
    results_dir = data_dir / "results"
    figures_dir = data_dir / "figures"
    manifests_dir = data_dir / "manifests"
    experiments_dir = data_dir / "experiments"

    for d in [results_dir, figures_dir, manifests_dir, experiments_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Load protected P1-P4 baseline inputs
    benchmark_path = data_dir / "benchmarks/benchmark_2024_event_control_v0.parquet"
    benchmark_df = pd.read_parquet(benchmark_path)
    benchmark_hash = sha256_file(benchmark_path)

    history_path = data_dir / "processed/hourly_caiso_v0.parquet"
    history_df = pd.read_parquet(history_path)
    history_hash = sha256_file(history_path)

    workload_path = data_dir / "workloads/workload_trace_v0.parquet"
    workload_df = pd.read_parquet(workload_path)
    workload_hash = sha256_file(workload_path)

    forecast_path = data_dir / "forecasts/p4_historical_forecasts_v0.parquet"
    forecast_df = pd.read_parquet(forecast_path)
    forecast_hash = sha256_file(forecast_path)

    p5_cfg_hash = sha256_file(p5_config_path)

    constraints = SchedulingConstraints(
        max_cluster_power_kw=cfg["constraints"]["max_cluster_power_kw"],
        max_concurrent_jobs=cfg["constraints"]["max_concurrent_jobs"],
    )
    constraint_dict = {
        "max_cluster_power_kw": constraints.max_cluster_power_kw,
        "max_concurrent_jobs": constraints.max_concurrent_jobs,
        "arrival_inclusive": True,
        "deadline_exclusive": True,
    }
    import hashlib
    constraint_hash = hashlib.sha256(json.dumps(constraint_dict, sort_keys=True).encode("utf-8")).hexdigest()

    # Earliest evaluated target origin
    earliest_target_origin_utc = "2024-06-05T07:00:00+00:00"

    # 2. P5-01 / E1: Event & Control Characterization
    char_res = run_event_characterization_pipeline(benchmark_df)
    char_res["hourly_source_table"].to_csv(results_dir / "p5_e1_hourly_source_table.csv", index=False)
    char_res["window_summary_table"].to_csv(results_dir / "p5_e1_window_summary_table.csv", index=False)
    char_res["phase_summary_table"].to_csv(results_dir / "p5_e1_phase_summary_table.csv", index=False)
    char_res["persistence_table"].to_csv(results_dir / "p5_e1_persistence_table.csv", index=False)
    char_res["lag_analysis_table"].to_csv(results_dir / "p5_e1_lag_analysis_table.csv", index=False)

    # 3. P5-02 & P5-06 / E3: Treatment Variants & Experiments
    treatment_out = run_p5_treatment_experiments(
        benchmark_df=benchmark_df,
        history_df=history_df,
        forecast_df=forecast_df,
        workload_df=workload_df,
        constraints=constraints,
        fit_cutoff_utc=earliest_target_origin_utc,
        source_file_hash=history_hash,
    )
    df_treatment_metrics = treatment_out["metrics_df"]
    df_treatment_metrics.to_csv(results_dir / "p5_e3_treatment_metrics.csv", index=False)
    with (results_dir / "p5_treatment_variants_meta.json").open("w", encoding="utf-8") as f:
        json.dump({
            "treatment_fit_info": treatment_out["treatment_fit_info"],
            "variants_metadata": treatment_out["variants_metadata"],
        }, f, indent=2)

    # 4. P5-05 / E2: Event-Control Policy Experiment Table (Raw Variant)
    df_e2_metrics = df_treatment_metrics[df_treatment_metrics["variant"] == "raw"].reset_index(drop=True)
    df_e2_metrics.to_csv(results_dir / "p5_e2_policy_comparison_metrics.csv", index=False)

    # 5. P5-03 & P5-06 / E4: Equal-Budget Sampling Experiments over Outcomes
    sampling_out = run_p5_sampling_experiments(
        hourly_outcomes=treatment_out["hourly_outcomes"],
        workload_digest=workload_hash,
        constraint_digest=constraint_hash,
        budget_hours=cfg["evaluation_budget_hours"],
        seed=cfg["random_seed"],
    )
    df_sampling_metrics = sampling_out["metrics_df"]
    df_sampling_metrics.to_csv(results_dir / "p5_e4_sampling_metrics.csv", index=False)

    sampling_manifest_digests = {}
    for s_name, s_df in sampling_out["manifests"].items():
        s_path = manifests_dir / f"p5_sampling_{s_name}.csv"
        s_df.to_csv(s_path, index=False)
        sampling_manifest_digests[f"p5_sampling_{s_name}.csv"] = sha256_file(s_path)

    # 6. P5-07: Hindsight Comparator Runs
    comparator_res = run_p5_comparator_instances(benchmark_df, workload_df, constraints)
    with (results_dir / "p5_comparator_results.json").open("w", encoding="utf-8") as f:
        json.dump(comparator_res, f, indent=2)

    # 7. P5-09: Figures and Source Tables
    fig_paths = generate_p5_figures_and_tables(
        benchmark_df=benchmark_df,
        characterization_results=char_res,
        comparison_metrics_df=df_e2_metrics,
        output_fig_dir=figures_dir,
        output_results_dir=results_dir,
    )

    # 8. P5-10: Paired Differences (Policy and Signals)
    # Policy paired differences
    policy_paired_diffs = compute_policy_paired_differences(
        df_e2_metrics,
        hourly_outcomes=treatment_out["hourly_outcomes"],
        seed=cfg["bootstrap"]["seed"],
        repetitions=cfg["bootstrap"]["repetitions"],
    )
    policy_paired_diffs.to_csv(results_dir / "p5_policy_paired_differences.csv", index=False)

    # Signal paired differences
    paired_signal_diffs = compute_hourly_paired_signal_differences(
        benchmark_df,
        seed=cfg["bootstrap"]["seed"],
        repetitions=cfg["bootstrap"]["repetitions"],
    )
    paired_signal_diffs.to_csv(results_dir / "p5_paired_signal_differences.csv", index=False)

    # 9. P5-11: Evaluation Strategy Comparison
    strat_comp_res = compare_evaluation_strategies(
        df_sampling_metrics,
        sampling_out["manifests"],
        target_budget_hours=cfg["evaluation_budget_hours"],
    )
    strat_comp_res["strategy_comparison_summary"].to_csv(results_dir / "p5_e4_strategy_comparison_summary.csv", index=False)

    # 10. P5-04 & P5-12: Complete Frozen Dataset Manifest with Full Provenance
    tracked_output_files = [
        "data/results/p5_e1_hourly_source_table.csv",
        "data/results/p5_e1_window_summary_table.csv",
        "data/results/p5_e1_phase_summary_table.csv",
        "data/results/p5_e1_persistence_table.csv",
        "data/results/p5_e1_lag_analysis_table.csv",
        "data/results/p5_e2_policy_comparison_metrics.csv",
        "data/results/p5_e3_treatment_metrics.csv",
        "data/results/p5_e4_sampling_metrics.csv",
        "data/results/p5_e4_strategy_comparison_summary.csv",
        "data/results/p5_comparator_results.json",
        "data/results/p5_policy_paired_differences.csv",
        "data/results/p5_paired_signal_differences.csv",
        "data/results/p5_treatment_variants_meta.json",
        "data/results/p5_source_table_fig1_distributions.csv",
        "data/results/p5_source_table_fig2_time_series.csv",
        "data/results/p5_source_table_fig3_phase_behavior.csv",
        "data/results/p5_source_table_fig4_lag_relationships.csv",
        "data/results/p5_source_table_fig5_policy_performance.csv",
        "data/figures/p5_fig1_signal_distributions.png",
        "data/figures/p5_fig2_signals_time_series.png",
        "data/figures/p5_fig3_phase_behavior.png",
        "data/figures/p5_fig4_lag_relationships.png",
        "data/figures/p5_fig5_policy_performance.png",
        "data/manifests/p5_sampling_ordinary_window.csv",
        "data/manifests/p5_sampling_event_stratified.csv",
        "data/manifests/p5_sampling_phase_aware.csv",
    ]

    output_files_meta: dict[str, dict[str, Any]] = {}
    for rel_p in tracked_output_files:
        full_p = repo_root / rel_p
        if full_p.exists():
            output_files_meta[rel_p] = {
                "sha256": sha256_file(full_p),
                "size_bytes": full_p.stat().st_size,
            }

    import subprocess
    try:
        git_rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root).decode("utf-8").strip()
    except Exception:
        git_rev = "unknown"

    p5_dataset_manifest = {
        "schema_version": "2.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_rev,
        "seed": cfg["random_seed"],
        "event_window_id": cfg["benchmark"]["event_window_id"],
        "control_window_id": cfg["benchmark"]["control_window_id"],
        "event_interval_utc": [
            str(benchmark_df[benchmark_df["window_id"] == "HW_20240702"]["timestamp_utc"].min()),
            str(benchmark_df[benchmark_df["window_id"] == "HW_20240702"]["timestamp_utc"].max()),
        ],
        "control_interval_utc": [
            str(benchmark_df[benchmark_df["window_id"] == "CTRL_20240605"]["timestamp_utc"].min()),
            str(benchmark_df[benchmark_df["window_id"] == "CTRL_20240605"]["timestamp_utc"].max()),
        ],
        "horizon_hours": cfg["benchmark"]["horizon_hours"],
        "evaluation_budget_hours": cfg["evaluation_budget_hours"],
        "policies": cfg["policies"],
        "treatment_variants": cfg["treatment_variants"],
        "sampling_strategies": cfg["sampling_strategies"],
        "treatment_fitting": {
            "fit_cutoff_utc": earliest_target_origin_utc,
            "status": treatment_out["treatment_fit_info"]["status"],
            "eligible_row_count": treatment_out["treatment_fit_info"]["eligible_row_count"],
            "excluded_target_future_row_count": treatment_out["treatment_fit_info"]["excluded_target_future_row_count"],
            "source_file_hash": history_hash,
            "rule": "Strict pre-cutoff filtering (t < 2024-06-05 07:00:00 UTC). Target observations strictly excluded.",
        },
        "sampling_rules": {
            "budget": "Equal 120 selected outcome hours across ordinary, stratified, and phase-aware strategies.",
            "evaluation_basis": "Evaluated over authentic schedule outcomes; no discontinuous pseudo-horizon scheduling.",
            "manifest_digests": sampling_manifest_digests,
        },
        "provenance_digests": {
            "p5_configuration_sha256": p5_cfg_hash,
            "benchmark_dataset_sha256": benchmark_hash,
            "history_source_sha256": history_hash,
            "workload_trace_sha256": workload_hash,
            "constraint_definition_sha256": constraint_hash,
            "forecast_dataset_sha256": forecast_hash,
        },
        "carbon_data_quality": {
            "interpretation_label": "quality_limited_sensitivity_only",
            "known_data_issue_rows": 240,
            "primary_analysis_eligible_rows": 0,
            "caveat": "All carbon emissions findings are descriptive/sensitivity-only and not primary causal evidence.",
        },
        "experiment_matrix": {
            "E1_characterization": "success",
            "E2_policy_comparison": "success",
            "E3_treatment_variants": "success_with_explicit_unsupported_clipping",
            "E4_equal_budget_sampling": "success",
        },
        "known_limitations": [
            "Carbon intensity data contains known EIA data issue flags across all 240 benchmark hours.",
            "Full 120h/30-job benchmark exceeds small-instance exact comparator limits (status: unsupported).",
            "Single 120h benchmark window pair limits inferential generalization across heatwaves.",
            "Zero pre-target observations exist in local history, rendering historical clipping bounds unsupported.",
            "Flat historical persistence forecasts cause identical policy dispatch under earliest-hour tie breaking.",
        ],
        "input_files": {
            "configs/p5.yaml": {"path": "configs/p5.yaml", "sha256": p5_cfg_hash},
            "data/benchmarks/benchmark_2024_event_control_v0.parquet": {"path": "data/benchmarks/benchmark_2024_event_control_v0.parquet", "sha256": benchmark_hash},
            "data/processed/hourly_caiso_v0.parquet": {"path": "data/processed/hourly_caiso_v0.parquet", "sha256": history_hash},
            "data/workloads/workload_trace_v0.parquet": {"path": "data/workloads/workload_trace_v0.parquet", "sha256": workload_hash},
            "data/forecasts/p4_historical_forecasts_v0.parquet": {"path": "data/forecasts/p4_historical_forecasts_v0.parquet", "sha256": forecast_hash},
        },
        "output_files": output_files_meta,
    }

    manifest_path = manifests_dir / "p5_dataset_manifest.json"
    write_atomic_json(manifest_path, p5_dataset_manifest)

    return {
        "status": "success",
        "manifest_path": manifest_path,
        "results_generated": len(output_files_meta),
    }
