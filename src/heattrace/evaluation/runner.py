"""Common benchmark runner executing all policies under identical conditions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.evaluation.artifacts import (
    build_p4_run_manifest,
    publish_p4_run_artifacts_atomically,
)
from heattrace.evaluation.metrics import compute_schedule_metrics
from heattrace.forecast.historical import build_historical_forecast_dataset
from heattrace.manifests import (
    build_p4_experiment_manifest,
    build_p4_forecast_manifest,
    validate_p4_experiment_manifest,
    write_atomic_json,
)
from heattrace.policy.feasibility import validate_schedule_feasibility
from heattrace.policy.greedy import (
    BalancedGreedyPolicy,
    CarbonFirstGreedyPolicy,
    CostFirstGreedyPolicy,
)
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    SchedulingConstraints,
    SchedulingPolicy,
)
from heattrace.policy.robust import RiskPenalizedDROInspiredPolicy


def run_p4_benchmark(
    *,
    repo_root: Path,
    output_run_dir: Path | None = None,
    p4_config_path: Path | None = None,
) -> dict[str, Any]:
    """Execute the authentic P4 benchmark across event and control windows."""
    repo_root = repo_root.resolve()
    if p4_config_path is None:
        p4_config_path = repo_root / "configs/p4.yaml"
    else:
        p4_config_path = p4_config_path.resolve()

    if output_run_dir is None:
        output_run_dir = repo_root / "runs/p4_v0"
    else:
        output_run_dir = output_run_dir.resolve()

    cfg = load_yaml(p4_config_path)

    # 1. Load experiment manifest and inputs
    benchmark_df = pd.read_parquet(repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet")
    workload_df = pd.read_parquet(repo_root / "data/workloads/workload_trace_v0.parquet")

    event_id = cfg["benchmark"]["event_window_id"]
    control_id = cfg["benchmark"]["control_window_id"]
    horizon = int(cfg["benchmark"]["horizon_hours"])

    # 2. Build or load historical forecasts
    forecast_df = build_historical_forecast_dataset(
        benchmark_df,
        event_window_id=event_id,
        control_window_id=control_id,
        horizon_hours=horizon,
        fallback_price_usd_per_mwh=float(cfg["forecast"]["fallback_price_usd_per_mwh"]),
        fallback_carbon_g_per_kwh=float(cfg["forecast"]["fallback_carbon_g_per_kwh"]),
    )

    # Staging directory for atomic publication
    stage_dir = repo_root / f"runs/staging_p4_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # Prepare policies
    policies: list[SchedulingPolicy] = [
        CostFirstGreedyPolicy(),
        CarbonFirstGreedyPolicy(),
        BalancedGreedyPolicy(
            cost_weight=float(cfg["objectives"]["balanced_cost_weight"]),
            carbon_weight=float(cfg["objectives"]["balanced_carbon_weight"]),
        ),
        RiskPenalizedDROInspiredPolicy(
            cost_weight=float(cfg["objectives"]["balanced_cost_weight"]),
            carbon_weight=float(cfg["objectives"]["balanced_carbon_weight"]),
            cvar_alpha=float(cfg["risk"]["cvar_alpha"]),
            uncertainty_quantile=float(cfg["risk"]["uncertainty_quantile"]),
            dro_risk_penalty_lambda=float(cfg["risk"]["dro_risk_penalty_lambda"]),
        ),
    ]

    constraints = SchedulingConstraints(
        max_cluster_power_kw=float(cfg["constraints"]["max_cluster_power_kw"]),
        max_concurrent_jobs=int(cfg["constraints"]["max_concurrent_jobs"]),
    )

    all_metrics: list[dict[str, Any]] = []

    # Write forecasts to stage
    stage_fc_dir = stage_dir / "forecasts"
    stage_fc_dir.mkdir(parents=True, exist_ok=True)
    stage_fc_parquet = stage_fc_dir / "p4_historical_forecasts_v0.parquet"
    forecast_df.to_parquet(stage_fc_parquet, index=False)

    windows = [(control_id, "control"), (event_id, "event")]

    for wid, wtype in windows:
        w_realized = benchmark_df[benchmark_df["window_id"] == wid].sort_values("timestamp_utc").reset_index(drop=True)
        w_fc = forecast_df[forecast_df["window_id"] == wid].sort_values("horizon_hour").reset_index(drop=True)

        # Convert forecast rows to ForecastResult for policy input
        origin_ts = pd.to_datetime(w_fc["origin_timestamp_utc"].iloc[0], utc=True).to_pydatetime()
        fc_points = [
            ForecastPoint(
                timestamp_utc=pd.to_datetime(r["target_timestamp_utc"], utc=True).to_pydatetime(),
                horizon_hours=int(r["horizon_hour"]),
                predicted_price_usd_per_mwh=float(r["predicted_price_usd_per_mwh"]),
                predicted_carbon_g_per_kwh=float(r["predicted_carbon_g_per_kwh"]),
            )
            for _, r in w_fc.iterrows()
        ]
        fc_result = ForecastResult(
            origin_timestamp_utc=origin_ts,
            points=fc_points,
            model_name="historical_persistence_v0",
            model_version="1.0",
        )

        for pol in policies:
            pol_dir = stage_dir / wid / pol.policy_name
            pol_dir.mkdir(parents=True, exist_ok=True)

            # Schedule using forecast ONLY
            sched = pol.schedule(workload_df, fc_result, constraints)

            # Re-validate feasibility strictly
            feas_rep = validate_schedule_feasibility(sched, workload_df, constraints, window_duration_hours=horizon)
            with (pol_dir / "feasibility.json").open("w", encoding="utf-8") as f:
                json.dump(feas_rep.to_dict(), f, indent=2)

            # Export schedule
            sched_df = sched.to_dataframe()
            sched_df.to_parquet(pol_dir / "schedule.parquet", index=False)
            sched_df.head(10).to_csv(pol_dir / "schedule_sample.csv", index=False)

            # Realized scoring joined post-scheduling
            m = compute_schedule_metrics(
                sched,
                workload_df,
                w_realized,
                forecast_df,
                window_id=wid,
                window_type=wtype,
                cvar_alpha=float(cfg["risk"]["cvar_alpha"]),
            )
            with (pol_dir / "metrics.json").open("w", encoding="utf-8") as f:
                json.dump(m, f, indent=2)

            all_metrics.append(m)

    # Export comparison metrics
    comp_df = pd.DataFrame(all_metrics)
    comp_df.to_csv(stage_dir / "comparison_metrics.csv", index=False)
    with (stage_dir / "comparison_metrics.json").open("w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2)

    # Build stage run manifest
    rm = build_p4_run_manifest(stage_dir)
    with (stage_dir / "run_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(rm, f, indent=2)

    # Publish atomically
    publish_p4_run_artifacts_atomically(output_run_dir, stage_dir)

    # Also build and write forecast manifest and parquet to data/forecasts/
    data_fc_dir = repo_root / "data/forecasts"
    data_fc_dir.mkdir(parents=True, exist_ok=True)
    fc_p_path = data_fc_dir / "p4_historical_forecasts_v0.parquet"
    fc_s_path = data_fc_dir / "p4_historical_forecasts_v0_sample.csv"
    forecast_df.to_parquet(fc_p_path, index=False)
    forecast_df.head(20).to_csv(fc_s_path, index=False)

    fc_manifest = build_p4_forecast_manifest(
        fc_p_path,
        fc_s_path,
        p4_config_path=p4_config_path,
        repo_root=repo_root,
    )
    write_atomic_json(repo_root / "data/manifests/p4_forecast_manifest.json", fc_manifest)

    # Write experiment manifest to data/manifests/
    exp_manifest = build_p4_experiment_manifest(repo_root=repo_root, p4_config_path=p4_config_path)
    write_atomic_json(repo_root / "data/manifests/p4_experiment_manifest.json", exp_manifest)

    return {
        "status": "success",
        "output_run_dir": output_run_dir.as_posix(),
        "metrics_count": len(all_metrics),
        "comparison_metrics": all_metrics,
    }
