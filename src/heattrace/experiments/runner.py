"""Experiment runner for P5 treatment variants, sampling strategies, and comparator checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from heattrace.analysis.sampling import generate_outcome_sampling_manifests
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


def run_single_schedule_run(
    policy_name: str,
    workload_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    realized_df: pd.DataFrame,
    constraints: SchedulingConstraints,
    *,
    window_id: str,
    window_type: str,
    variant_name: str = "raw",
    forecast_digest: str = "",
    realized_digest: str = "",
    workload_digest: str = "",
    constraint_digest: str = "",
    schedule_digest: str = "",
) -> dict[str, Any]:
    """Execute policy schedule on original contiguous timeline and compute metrics & hourly outcomes."""
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

    # Compute aggregate metrics post-schedule
    metrics = compute_schedule_metrics(
        schedule_res,
        workload_df,
        realized_df,
        forecast_df,
        window_id=window_id,
        window_type=window_type,
    )
    metrics["variant"] = variant_name
    metrics["status"] = "success" if schedule_res.is_feasible else "infeasible"

    # Compute hourly outcome profile (for sampling evaluation and hourly pairing)
    horizon = len(realized_df)
    hourly_pwr = np.zeros(horizon, dtype=float)
    hourly_cost = np.zeros(horizon, dtype=float)
    hourly_emiss = np.zeros(horizon, dtype=float)
    hourly_jobs: list[set[str]] = [set() for _ in range(horizon)]

    prices = realized_df["price_usd_per_mwh"].to_numpy()
    carbons = realized_df["carbon_g_per_kwh"].to_numpy()

    for a in schedule_res.allocations:
        h = a.allocated_hour_offset
        if 0 <= h < horizon:
            hourly_pwr[h] += a.execution_power_kw
            hourly_cost[h] += (a.allocated_energy_kwh * prices[h]) / 1000.0
            hourly_emiss[h] += (a.allocated_energy_kwh * carbons[h]) / 1000.0
            hourly_jobs[h].add(a.job_id)

    outcome_rows = []
    for h in range(horizon):
        outcome_rows.append({
            "window_id": window_id,
            "window_type": window_type,
            "policy_name": policy_name,
            "policy_version": "1.0",
            "hour_offset": h,
            "timestamp_utc": realized_df["timestamp_utc"].iloc[h],
            "phase_label": realized_df.get("phase_label", pd.Series(["control"]*horizon)).iloc[h],
            "execution_power_kw": round(float(hourly_pwr[h]), 4),
            "concurrent_jobs_count": len(hourly_jobs[h]),
            "hourly_cost_usd": round(float(hourly_cost[h]), 4),
            "hourly_emissions_kg": round(float(hourly_emiss[h]), 4),
            "workload_trace_id": str(workload_df["workload_trace_id"].iloc[0]),
            "workload_digest": workload_digest,
            "constraint_digest": constraint_digest,
            "schedule_digest": schedule_digest,
            "forecast_digest": forecast_digest,
            "realized_scoring_digest": realized_digest,
            "carbon_quality_label": "quality_limited_sensitivity_only",
        })

    return {
        "schedule": schedule_res,
        "metrics": metrics,
        "hourly_outcomes": pd.DataFrame(outcome_rows),
    }


def run_p5_treatment_experiments(
    benchmark_df: pd.DataFrame,
    history_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    workload_df: pd.DataFrame,
    constraints: SchedulingConstraints,
    fit_cutoff_utc: str = "2024-06-05T07:00:00+00:00",
    source_file_hash: str = "",
    forecast_digest: str = "",
    realized_digest: str = "",
    workload_digest: str = "",
    constraint_digest: str = "",
    schedule_digests: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    """Run E3 treatment variants across all 4 policies and 2 windows with strict cutoff enforcement."""
    variants_res = build_treatment_variants(
        benchmark_df=benchmark_df,
        history_df=history_df,
        fit_cutoff_utc=fit_cutoff_utc,
        source_file_hash=source_file_hash,
    )
    variants = variants_res["variants"]
    variants_meta = variants_res["metadata"]

    policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]
    windows = ["CTRL_20240605", "HW_20240702"]

    results: list[dict[str, Any]] = []
    hourly_outcomes_dict: dict[tuple[str, str], pd.DataFrame] = {}

    for v_name, v_df in variants.items():
        v_status = variants_meta[v_name].get("status", "supported")

        for wid in windows:
            wtype = "event" if wid.startswith("HW") else "control"
            fc_sub = forecast_df[forecast_df["window_id"] == wid]
            real_sub = v_df[v_df["window_id"] == wid].sort_values("timestamp_utc").reset_index(drop=True)

            for pol in policies:
                exp_id = f"exp_treatment_{v_name}_{wid}_{pol}"

                if v_status != "supported":
                    unsupported_meta = {
                        "experiment_id": exp_id,
                        "variant": v_name,
                        "window_id": wid,
                        "window_type": wtype,
                        "policy_name": pol,
                        "policy_version": "1.0",
                        "status": "unsupported_insufficient_pre_target_history",
                        "reason": variants_meta[v_name].get("limitation", "Insufficient pre-target history"),
                        "total_realized_cost_usd": None,
                        "total_realized_emissions_kg": None,
                        "sla_completion_rate": None,
                        "carbon_interpretation_label": "quality_limited_sensitivity_only",
                    }
                    results.append(unsupported_meta)
                    continue

                sched_sha = schedule_digests.get((wid, pol), "") if schedule_digests else ""

                run_out = run_single_schedule_run(
                    policy_name=pol,
                    workload_df=workload_df,
                    forecast_df=fc_sub,
                    realized_df=real_sub,
                    constraints=constraints,
                    window_id=wid,
                    window_type=wtype,
                    variant_name=v_name,
                    forecast_digest=forecast_digest,
                    realized_digest=realized_digest,
                    workload_digest=workload_digest,
                    constraint_digest=constraint_digest,
                    schedule_digest=sched_sha,
                )
                m = run_out["metrics"]
                m["experiment_id"] = exp_id
                results.append(m)

                # Store raw hourly outcomes for downstream sampling & bootstrap
                if v_name == "raw":
                    hourly_outcomes_dict[(wid, pol)] = run_out["hourly_outcomes"]

    return {
        "metrics_df": pd.DataFrame(results),
        "variants_metadata": variants_meta,
        "treatment_fit_info": variants_res["treatment_fit_info"],
        "hourly_outcomes": hourly_outcomes_dict,
    }


def run_p5_sampling_experiments(
    hourly_outcomes: dict[tuple[str, str], pd.DataFrame],
    workload_digest: str = "",
    constraint_digest: str = "",
    budget_hours: int = 120,
    seed: int = 20261016,
    source_outcome_paths: dict[str, str] | None = None,
    source_outcome_digests: dict[str, str] | None = None,
    schedule_paths: dict[str, str] | None = None,
    schedule_digests: dict[str, str] | None = None,
    forecast_digest: str = "",
    realized_scoring_digest: str = "",
) -> dict[str, Any]:
    """Execute E4 equal-budget sampling over already-generated hourly policy outcomes.

    Never reassigns pseudo-horizons or reschedules discontinuous slices.
    Evaluates equal 120-hour sample budgets for each policy across:
    1. ordinary_window: 120 hours from CTRL_20240605 outcomes.
    2. event_stratified: 60 hours CTRL + 60 hours HW outcomes.
    3. phase_aware: 120 hours from HW_20240702 outcomes.
    """
    policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]

    # Manifests are generated from the representative hourly outcome structure
    sample_ctrl = hourly_outcomes[("CTRL_20240605", "cost_first")]
    sample_hw = hourly_outcomes[("HW_20240702", "cost_first")]

    manifests = generate_outcome_sampling_manifests(
        control_outcomes_df=sample_ctrl,
        event_outcomes_df=sample_hw,
        budget_hours=budget_hours,
        seed=seed,
        workload_id="trace_standard_120h_v0",
        workload_digest=workload_digest,
        constraint_digest=constraint_digest,
        source_outcome_paths=source_outcome_paths,
        source_outcome_digests=source_outcome_digests,
        schedule_paths=schedule_paths,
        schedule_digests=schedule_digests,
        forecast_digest=forecast_digest,
        realized_scoring_digest=realized_scoring_digest,
    )

    results: list[dict[str, Any]] = []

    for strat_name, manifest in manifests.items():
        for pol in policies:
            exp_id = f"exp_sampling_{strat_name}_{pol}"

            # Filter outcomes for pol using manifest indices
            selected_rows = []
            for _, m_row in manifest.iterrows():
                target_wid = m_row["window_id"]
                target_h = int(m_row["original_hour_offset"])
                pol_outcomes = hourly_outcomes[(target_wid, pol)]
                matching_h = pol_outcomes[pol_outcomes["hour_offset"] == target_h].iloc[0]
                selected_rows.append(matching_h)

            df_sampled_outcomes = pd.DataFrame(selected_rows)

            tot_cost = float(df_sampled_outcomes["hourly_cost_usd"].sum())
            tot_emiss = float(df_sampled_outcomes["hourly_emissions_kg"].sum())
            mean_pwr = float(df_sampled_outcomes["execution_power_kw"].mean())
            max_pwr = float(df_sampled_outcomes["execution_power_kw"].max())
            max_concur = int(df_sampled_outcomes["concurrent_jobs_count"].max())

            # Sampled CVaR 0.90
            q_cost = float(np.quantile(df_sampled_outcomes["hourly_cost_usd"], 0.90))
            tail_cost = df_sampled_outcomes[df_sampled_outcomes["hourly_cost_usd"] >= q_cost]["hourly_cost_usd"]
            cvar_cost = float(tail_cost.mean()) if len(tail_cost) > 0 else q_cost

            results.append({
                "experiment_id": exp_id,
                "sampling_strategy": strat_name,
                "policy_name": pol,
                "policy_version": "1.0",
                "budget_hours": len(manifest),
                "evaluation_mode": "sampled_hourly_outcomes",
                "total_sampled_cost_usd": round(tot_cost, 4),
                "total_sampled_emissions_kg": round(tot_emiss, 4),
                "mean_sampled_power_kw": round(mean_pwr, 4),
                "max_sampled_power_kw": round(max_pwr, 4),
                "max_sampled_concurrency": max_concur,
                "cvar_cost_90": round(cvar_cost, 4),
                "status": "success",
                "carbon_interpretation_label": "quality_limited_sensitivity_only",
                "note": "Evaluated over authentic schedule outcomes; no discontinuous pseudo-horizon scheduling.",
            })

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
