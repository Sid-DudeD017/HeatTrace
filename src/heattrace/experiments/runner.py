"""Experiment runner for P5 treatment variants, sampling strategies, and comparator checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from heattrace.analysis.sampling import generate_sampling_manifests
from heattrace.analysis.treatments import build_treatment_variants
from heattrace.evaluation.metrics import compute_schedule_metrics
from heattrace.ingest.provenance import sha256_file
from heattrace.policy.comparator import ExactSmallInstanceHindsightComparator
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
)
from heattrace.policy.robust import RiskPenalizedDROInspiredPolicy


def get_policy_instance(name: str):
    if name == "cost_first":
        return CostFirstGreedyPolicy()
    elif name == "carbon_first":
        return CarbonFirstGreedyPolicy()
    elif name == "balanced":
        return BalancedGreedyPolicy()
    elif name == "dro_inspired":
        return RiskPenalizedDROInspiredPolicy()
    else:
        raise ValueError(f"Unknown policy: {name}")


def run_single_experiment_instance(
    policy_name: str,
    workload_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    realized_df: pd.DataFrame,
    constraints: SchedulingConstraints,
    *,
    window_id: str,
    window_type: str,
    experiment_id: str,
    variant_name: str = "raw",
    sampling_strategy: str = "ordinary_window",
) -> dict[str, Any]:
    """Execute a single policy run on a specific window, variant, and sampling condition."""
    policy = get_policy_instance(policy_name)

    # Convert forecast dataframe to ForecastResult
    pts = [
        ForecastPoint(
            timestamp_utc=row["target_timestamp_utc"],
            horizon_hours=int(row["horizon_hour"]),
            predicted_price_usd_per_mwh=float(row["predicted_price_usd_per_mwh"]),
            predicted_carbon_g_per_kwh=float(row["predicted_carbon_g_per_kwh"]),
        )
        for _, row in forecast_df.sort_values("horizon_hour").iterrows()
    ]
    fc_res = ForecastResult(
        origin_timestamp_utc=forecast_df["origin_timestamp_utc"].iloc[0],
        points=pts,
        model_name=str(forecast_df["model_name"].iloc[0]),
        model_version=str(forecast_df["model_version"].iloc[0]),
    )

    # Execute policy schedule (forecast only!)
    schedule_res = policy.schedule(workload_df, fc_res, constraints)

    # Compute metrics strictly using realized dataframe post-schedule
    metrics = compute_schedule_metrics(
        schedule_res,
        workload_df,
        realized_df,
        forecast_df,
        window_id=window_id,
        window_type=window_type,
    )

    metrics["experiment_id"] = experiment_id
    metrics["variant"] = variant_name
    metrics["sampling_strategy"] = sampling_strategy
    metrics["status"] = "success" if schedule_res.is_feasible else "infeasible"

    return {
        "schedule": schedule_res,
        "metrics": metrics,
    }


def run_p5_treatment_experiments(
    benchmark_df: pd.DataFrame,
    history_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    workload_df: pd.DataFrame,
    constraints: SchedulingConstraints,
) -> dict[str, Any]:
    """Run E3 treatment variants (raw, clipped, causal_imputed) across all 4 policies and 2 windows."""
    variants_res = build_treatment_variants(benchmark_df, history_df)
    variants = variants_res["variants"]

    policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]
    windows = ["CTRL_20240605", "HW_20240702"]

    results: list[dict[str, Any]] = []

    for v_name, v_df in variants.items():
        for wid in windows:
            wtype = "event" if wid.startswith("HW") else "control"
            fc_sub = forecast_df[forecast_df["window_id"] == wid]
            real_sub = v_df[v_df["window_id"] == wid].sort_values("timestamp_utc").reset_index(drop=True)

            for pol in policies:
                exp_id = f"exp_treatment_{v_name}_{wid}_{pol}"
                run_out = run_single_experiment_instance(
                    policy_name=pol,
                    workload_df=workload_df,
                    forecast_df=fc_sub,
                    realized_df=real_sub,
                    constraints=constraints,
                    window_id=wid,
                    window_type=wtype,
                    experiment_id=exp_id,
                    variant_name=v_name,
                    sampling_strategy="ordinary_window",
                )
                results.append(run_out["metrics"])

    return {
        "metrics_df": pd.DataFrame(results),
        "variants_metadata": variants_res["metadata"],
    }


def run_p5_sampling_experiments(
    benchmark_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    workload_df: pd.DataFrame,
    constraints: SchedulingConstraints,
    budget_hours: int = 120,
    seed: int = 20261016,
) -> dict[str, Any]:
    """Run E4 equal-budget sampling experiments across policies."""
    manifests = generate_sampling_manifests(benchmark_df, budget_hours=budget_hours, seed=seed)
    policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]

    results: list[dict[str, Any]] = []

    for strat_name, manifest in manifests.items():
        # Evaluation uses the subset of timestamps specified by manifest
        # Extract corresponding realized rows
        sampled_realized = pd.merge(
            manifest[["timestamp_utc", "sample_index", "window_id", "phase_label"]],
            benchmark_df,
            on=["timestamp_utc", "window_id", "phase_label"],
            how="inner",
        ).sort_values("sample_index").reset_index(drop=True)

        # Match forecast rows for these timestamps
        sampled_forecast = pd.merge(
            manifest[["timestamp_utc", "sample_index", "window_id"]],
            forecast_df,
            left_on=["timestamp_utc", "window_id"],
            right_on=["target_timestamp_utc", "window_id"],
            how="inner",
        ).sort_values("sample_index").reset_index(drop=True)

        # Assign horizon hour 0..119 for the sampled window
        sampled_forecast["horizon_hour"] = np.arange(len(sampled_forecast))

        for pol in policies:
            exp_id = f"exp_sampling_{strat_name}_{pol}"
            # Workload is identical 120h workload
            run_out = run_single_experiment_instance(
                policy_name=pol,
                workload_df=workload_df,
                forecast_df=sampled_forecast,
                realized_df=sampled_realized,
                constraints=constraints,
                window_id="sampled_budget_120h",
                window_type=strat_name,
                experiment_id=exp_id,
                variant_name="raw",
                sampling_strategy=strat_name,
            )
            res_meta = run_out["metrics"]
            res_meta["sampling_strategy"] = strat_name
            res_meta["budget_hours"] = len(manifest)
            results.append(res_meta)

    return {
        "metrics_df": pd.DataFrame(results),
        "manifests": manifests,
    }


def run_p5_comparator_instances(
    benchmark_df: pd.DataFrame,
    workload_df: pd.DataFrame,
    constraints: SchedulingConstraints,
) -> dict[str, Any]:
    """Execute comparator on supported small instance and evaluate status on full benchmark."""
    comp = ExactSmallInstanceHindsightComparator(max_jobs=6, max_horizon_hours=24)

    # 1. Full benchmark test (must report 'unsupported' honestly)
    full_hw = benchmark_df[benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)
    full_res = comp.solve(workload_df, full_hw, constraints)

    # 2. Supported small instance fixture: 4 jobs, 24 hours
    small_wl = workload_df.head(4).copy()
    small_wl["arrival_offset_hours"] = [0, 2, 4, 6]
    small_wl["deadline_offset_hours"] = [10, 12, 14, 16]
    small_wl["processing_requirement"] = [2, 2, 2, 2]
    small_hw = full_hw.head(24).copy()

    supported_res = comp.solve(small_wl, small_hw, constraints, objective_mode="cost")

    return {
        "full_benchmark": {
            "is_supported": full_res.is_supported,
            "status": full_res.status,
            "reason": full_res.reason,
            "optimal_objective": full_res.optimal_objective,
        },
        "supported_small_fixture": {
            "is_supported": supported_res.is_supported,
            "status": supported_res.status,
            "reason": supported_res.reason,
            "optimal_cost_usd": supported_res.optimal_cost_usd,
            "optimal_emissions_kg": supported_res.optimal_emissions_kg,
            "optimal_objective": supported_res.optimal_objective,
        },
    }
