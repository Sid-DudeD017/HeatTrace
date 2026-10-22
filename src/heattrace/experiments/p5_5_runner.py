"""Experiment runner and execution engine for P5.5.

Runs all 5 policies (baseline_reference, cost_first, carbon_first, balanced, dro_inspired)
across all 270 preregistered scenarios.
Records long-form results table and provenance manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any
import pandas as pd

from heattrace.evaluation.metrics import compute_schedule_metrics
from heattrace.experiments.p5_5_grid import (
    P55ScenarioSpec,
    build_preregistered_p5_5_grid,
    generate_stressed_workload,
)
from heattrace.experiments.p5_5_scenarios import (
    generate_flat_forecast,
    generate_noisy_oracle_forecast,
    generate_oracle_forecast,
)
from heattrace.ingest.provenance import sha256_file
from heattrace.policy.baseline import BaselineReferencePolicy
from heattrace.policy.comparator import ExactSmallInstanceHindsightComparator
from heattrace.policy.greedy import (
    BalancedGreedyPolicy,
    CarbonFirstGreedyPolicy,
    CostFirstGreedyPolicy,
)
from heattrace.policy.interfaces import (
    ForecastResult,
    SchedulingConstraints,
    SchedulingPolicy,
)
from heattrace.policy.robust import RiskPenalizedDROInspiredPolicy


def get_policy_instance_p5_5(name: str) -> SchedulingPolicy:
    if name == "baseline_reference":
        return BaselineReferencePolicy()
    elif name == "cost_first":
        return CostFirstGreedyPolicy()
    elif name == "carbon_first":
        return CarbonFirstGreedyPolicy()
    elif name == "balanced":
        return BalancedGreedyPolicy()
    elif name == "dro_inspired":
        return RiskPenalizedDROInspiredPolicy()
    else:
        raise ValueError(f"Unknown policy: {name}")


def execute_single_scenario_p5_5(
    spec: P55ScenarioSpec,
    realized_window_df: pd.DataFrame,
    workload_cache: dict[tuple[int, float], pd.DataFrame],
    policies: list[str],
    comparator: ExactSmallInstanceHindsightComparator,
) -> list[dict[str, Any]]:
    """Execute all policies on a single preregistered scenario."""
    # 1. Retrieve or generate deterministic workload
    cache_key = (spec.job_count, spec.slack_multiplier)
    if cache_key in workload_cache:
        workload_df = workload_cache[cache_key]
    else:
        workload_df = generate_stressed_workload(
            job_count=spec.job_count,
            slack_multiplier=spec.slack_multiplier,
            random_seed=20261016,  # common workload seed across windows
        )
        workload_cache[cache_key] = workload_df

    # 2. Build forecast according to spec
    noise_meta: dict[str, float] = {}
    if spec.forecast_type == "flat":
        forecast = generate_flat_forecast(realized_window_df)
    elif spec.forecast_type == "oracle":
        forecast = generate_oracle_forecast(realized_window_df)
    elif spec.forecast_type == "noisy_oracle":
        forecast, noise_meta = generate_noisy_oracle_forecast(
            realized_window_df,
            noise_sigma=spec.noise_sigma,
            seed=spec.random_seed,
            noise_scenario_id=spec.forecast_scenario_id,
        )
    else:
        raise ValueError(f"Unknown forecast_type: {spec.forecast_type}")

    # Build forecast dataframe for evaluation
    fc_df = pd.DataFrame([
        {
            "window_id": spec.window_id,
            "horizon_hour": p.horizon_hours,
            "predicted_price_usd_per_mwh": p.predicted_price_usd_per_mwh,
            "predicted_carbon_g_per_kwh": p.predicted_carbon_g_per_kwh,
        }
        for p in forecast.points
    ])

    constraints = SchedulingConstraints(
        max_cluster_power_kw=spec.max_cluster_power_kw,
        max_concurrent_jobs=spec.max_concurrent_jobs,
    )

    # Check comparator support for small instances
    comp_res = comparator.solve(workload_df, realized_window_df, constraints)

    rows: list[dict[str, Any]] = []

    for pol_name in policies:
        t0 = time.time()
        policy = get_policy_instance_p5_5(pol_name)
        sched = policy.schedule(workload_df, forecast, constraints)
        runtime_ms = round((time.time() - t0) * 1000.0, 2)

        # Realized scoring
        m = compute_schedule_metrics(
            sched,
            workload_df,
            realized_window_df,
            fc_df,
            window_id=spec.window_id,
            window_type=spec.window_type,
            comparator_objective=comp_res.optimal_cost_usd if comp_res.is_supported else None,
            comparator_gap=(
                round(m_cost - comp_res.optimal_cost_usd, 4)
                if (comp_res.is_supported and comp_res.optimal_cost_usd is not None and (m_cost := sched.total_cost_usd) is not None)
                else None
            ),
            comparator_status=comp_res.status,
            comparator_reason=comp_res.reason,
            carbon_interpretation_label="quality_limited_sensitivity_only",
        )

        row = {
            "scenario_id": spec.scenario_id,
            "window_id": spec.window_id,
            "window_type": spec.window_type,
            "evidence_class": spec.evidence_class,
            "forecast_scenario_id": spec.forecast_scenario_id,
            "forecast_type": spec.forecast_type,
            "noise_sigma": spec.noise_sigma,
            "workload_multiplier": spec.workload_multiplier,
            "job_count": spec.job_count,
            "resource_scenario_id": spec.resource_scenario_id,
            "max_cluster_power_kw": spec.max_cluster_power_kw,
            "max_concurrent_jobs": spec.max_concurrent_jobs,
            "deadline_scenario_id": spec.deadline_scenario_id,
            "slack_multiplier": spec.slack_multiplier,
            "random_seed": spec.random_seed,
            "policy_name": pol_name,
            "policy_version": policy.policy_version,
            "is_feasible": m["is_feasible"],
            "sla_completion_rate": m["sla_completion_rate"],
            "deadline_misses": m["deadline_misses"],
            "unmet_processing_unit_hours": m["unmet_processing_unit_hours"],
            "unmet_energy_kwh": m["unmet_energy_kwh"],
            "total_realized_cost_usd": m["total_realized_cost_usd"],
            "total_realized_emissions_kg": m["total_realized_emissions_kg"],
            "total_allocated_energy_kwh": m["total_allocated_energy_kwh"],
            "max_cluster_power_kw_observed": m["max_cluster_power_kw"],
            "max_concurrent_jobs_observed": m["max_concurrent_jobs"],
            "forecast_price_mae": m["forecast_price_mae"],
            "forecast_carbon_mae": m["forecast_carbon_mae"],
            "forecast_price_bias": m["forecast_price_bias"],
            "forecast_carbon_bias": m["forecast_carbon_bias"],
            "cvar_cost_90": m["cvar_cost_90"],
            "cvar_emissions_90": m["cvar_emissions_90"],
            "cvar_composite_loss_90": m["cvar_composite_loss_90"],
            "comparator_status": m["comparator_status"],
            "comparator_reason": m["comparator_reason"],
            "carbon_interpretation_label": m["carbon_interpretation_label"],
            "runtime_ms": runtime_ms,
        }
        rows.append(row)

    return rows


def run_full_p5_5_experiment(
    benchmark_parquet_path: Path | str = "data/benchmarks/benchmark_2024_event_control_v0.parquet",
    config_path: Path | str = "configs/p5_5.yaml",
    output_dir: Path | str = "data/results",
    manifest_dir: Path | str = "data/manifests",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute complete preregistered P5.5 experiment grid across all policies."""
    out_dir = Path(output_dir)
    m_dir = Path(manifest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m_dir.mkdir(parents=True, exist_ok=True)

    bench_df = pd.read_parquet(benchmark_parquet_path)
    grid = build_preregistered_p5_5_grid(config_path)

    # Separate windows
    realized_by_win = {
        wid: bench_df[bench_df["window_id"] == wid].sort_values("timestamp_utc").reset_index(drop=True)
        for wid in bench_df["window_id"].unique()
    }

    policies = [
        "baseline_reference",
        "cost_first",
        "carbon_first",
        "balanced",
        "dro_inspired",
    ]

    comparator = ExactSmallInstanceHindsightComparator(max_jobs=6, max_horizon_hours=24)
    workload_cache: dict[tuple[int, float], pd.DataFrame] = {}

    all_rows: list[dict[str, Any]] = []
    t_start = time.time()

    for idx, spec in enumerate(grid):
        win_df = realized_by_win[spec.window_id]
        scen_rows = execute_single_scenario_p5_5(
            spec,
            win_df,
            workload_cache,
            policies,
            comparator,
        )
        all_rows.extend(scen_rows)

    total_time = time.time() - t_start
    results_df = pd.DataFrame(all_rows)

    csv_path = out_dir / "p5_5_experiment_results.csv"
    parquet_path = out_dir / "p5_5_experiment_results.parquet"
    results_df.to_csv(csv_path, index=False)
    results_df.to_parquet(parquet_path, index=False)

    # Generate execution manifest
    manifest_path = m_dir / "p5_5_experiment_manifest.json"
    manifest = {
        "manifest_version": "1.0",
        "phase": "P5.5",
        "execution_timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_scenarios": len(grid),
        "total_runs": len(results_df),
        "total_runtime_seconds": round(total_time, 2),
        "policies": policies,
        "results_files": {
            "csv": {
                "path": str(csv_path),
                "sha256": sha256_file(csv_path),
                "size_bytes": csv_path.stat().st_size,
            },
            "parquet": {
                "path": str(parquet_path),
                "sha256": sha256_file(parquet_path),
                "size_bytes": parquet_path.stat().st_size,
            },
        },
        "summary": {
            "feasible_runs": int(results_df["is_feasible"].sum()),
            "infeasible_runs": int((~results_df["is_feasible"]).sum()),
            "unique_scenarios": int(results_df["scenario_id"].nunique()),
        },
    }

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return results_df, manifest
