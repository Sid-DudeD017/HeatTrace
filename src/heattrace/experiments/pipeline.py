"""Master workflow pipeline for HeatTrace Phase P5."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.analysis.bootstrap import (
    compute_hourly_paired_signal_differences,
    compute_paired_metrics_differences,
)
from heattrace.analysis.characterization import run_event_characterization_pipeline
from heattrace.analysis.figures import generate_p5_figures_and_tables
from heattrace.analysis.sampling import generate_sampling_manifests, validate_sampling_manifests
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

    history_path = data_dir / "processed/hourly_caiso_v0.parquet"
    history_df = pd.read_parquet(history_path)

    workload_path = data_dir / "workloads/workload_trace_v0.parquet"
    workload_df = pd.read_parquet(workload_path)

    forecast_path = data_dir / "forecasts/p4_historical_forecasts_v0.parquet"
    forecast_df = pd.read_parquet(forecast_path)

    constraints = SchedulingConstraints(
        max_cluster_power_kw=cfg["constraints"]["max_cluster_power_kw"],
        max_concurrent_jobs=cfg["constraints"]["max_concurrent_jobs"],
    )

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
    )
    df_treatment_metrics = treatment_out["metrics_df"]
    df_treatment_metrics.to_csv(results_dir / "p5_e3_treatment_metrics.csv", index=False)
    with (results_dir / "p5_treatment_variants_meta.json").open("w", encoding="utf-8") as f:
        json.dump(treatment_out["variants_metadata"], f, indent=2)

    # 4. P5-03 & P5-06 / E4: Equal-Budget Sampling & Experiments
    sampling_out = run_p5_sampling_experiments(
        benchmark_df=benchmark_df,
        forecast_df=forecast_df,
        workload_df=workload_df,
        constraints=constraints,
        budget_hours=cfg["evaluation_budget_hours"],
        seed=cfg["random_seed"],
    )
    df_sampling_metrics = sampling_out["metrics_df"]
    df_sampling_metrics.to_csv(results_dir / "p5_e4_sampling_metrics.csv", index=False)

    for s_name, s_df in sampling_out["manifests"].items():
        s_df.to_csv(manifests_dir / f"p5_sampling_{s_name}.csv", index=False)

    # 5. P5-05 / E2: Event-Control Policy Experiment Table
    # Filter raw variant from treatment metrics (which corresponds to raw event-control run)
    df_e2_metrics = df_treatment_metrics[df_treatment_metrics["variant"] == "raw"].reset_index(drop=True)
    df_e2_metrics.to_csv(results_dir / "p5_e2_policy_comparison_metrics.csv", index=False)

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

    # 8. P5-10: Paired Differences and Bootstrap Analysis
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

    # 10. P5-04 & P5-12: Atomically Publish Manifest & Frozen Package
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

    p5_dataset_manifest = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": cfg["random_seed"],
        "event_window_id": cfg["benchmark"]["event_window_id"],
        "control_window_id": cfg["benchmark"]["control_window_id"],
        "horizon_hours": cfg["benchmark"]["horizon_hours"],
        "evaluation_budget_hours": cfg["evaluation_budget_hours"],
        "policies": cfg["policies"],
        "treatment_variants": cfg["treatment_variants"],
        "sampling_strategies": cfg["sampling_strategies"],
        "treatment_rules": {
            "clipping": "1st and 99th percentiles fitted strictly from pre-origin/historical data.",
            "missing_imputation": "Causal forward fill only; fallback to pre-origin historical median. No backward fill.",
        },
        "sampling_rules": {
            "budget": "Equal 120-hour budget across ordinary, stratified, and phase-aware strategies.",
            "determinism": f"Deterministic selection with seed {cfg['random_seed']}.",
        },
        "carbon_data_quality": {
            "interpretation_label": "quality_limited_sensitivity_only",
            "known_data_issue_rows": 240,
            "primary_analysis_eligible_rows": 0,
            "caveat": "All carbon emissions findings are descriptive/sensitivity-only and not primary causal evidence.",
        },
        "known_limitations": [
            "Carbon intensity data contains known EIA data issue flags across all 240 benchmark hours.",
            "Full 120h/30-job benchmark exceeds small-instance exact comparator limits (status: unsupported).",
            "Single 120h benchmark window pair limits inferential generalization across heatwaves.",
            "Flat historical persistence forecasts cause identical policy dispatch under earliest-hour tie breaking.",
        ],
        "output_files": output_files_meta,
    }

    manifest_path = manifests_dir / "p5_dataset_manifest.json"
    write_atomic_json(manifest_path, p5_dataset_manifest)

    return {
        "status": "success",
        "manifest_path": manifest_path,
        "results_generated": len(output_files_meta),
    }
