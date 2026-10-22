"""Small-instance exact hindsight comparator validation suite for P5.5 (Critical Issue 6).

Evaluates exact branch-and-bound comparator on 24-hour / 4-job slices of the
authentic benchmark event and control signals. Evaluates all policies and computes
exact optimality gaps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.evaluation.metrics import compute_schedule_metrics
from heattrace.experiments.p5_5_scenarios import generate_oracle_forecast
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
from heattrace.workload.generator import generate_deterministic_workload


def run_small_instance_comparator_validation(
    benchmark_parquet_path: Path | str = "data/benchmarks/benchmark_2024_event_control_v0.parquet",
    config_path: Path | str = "configs/p5_5.yaml",
    output_dir: Path | str = "data/results",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute exact branch-and-bound validation across all policies on supported small instances."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_yaml(config_path)

    bench_df = pd.read_parquet(benchmark_parquet_path)
    val_specs = cfg.get("comparator_validation", {}).get("scenarios", [])
    max_jobs = cfg.get("comparator_validation", {}).get("exact_max_jobs", 6)
    max_horizon = cfg.get("comparator_validation", {}).get("exact_max_horizon_hours", 24)

    comparator = ExactSmallInstanceHindsightComparator(
        max_jobs=max_jobs,
        max_horizon_hours=max_horizon,
    )

    policies: dict[str, SchedulingPolicy] = {
        "baseline_reference": BaselineReferencePolicy(),
        "cost_first": CostFirstGreedyPolicy(),
        "carbon_first": CarbonFirstGreedyPolicy(),
        "balanced": BalancedGreedyPolicy(),
        "dro_inspired": RiskPenalizedDROInspiredPolicy(),
    }

    results: list[dict[str, Any]] = []

    for spec in val_specs:
        wid = spec["window_id"]
        wtype = spec["window_type"]
        horizon = spec["horizon_hours"]
        jcount = spec["job_count"]
        seed = spec["random_seed"]

        win_slice = (
            bench_df[bench_df["window_id"] == wid]
            .sort_values("timestamp_utc")
            .iloc[:horizon]
            .reset_index(drop=True)
        )
        workload = generate_deterministic_workload(
            workload_trace_id=f"wl_comp_val_{wid}_{horizon}h_{jcount}j",
            window_duration_hours=horizon,
            job_count=jcount,
            random_seed=seed,
        )
        constraints = SchedulingConstraints(
            max_cluster_power_kw=spec["max_cluster_power_kw"],
            max_concurrent_jobs=spec["max_concurrent_jobs"],
        )

        # 1. Exact Branch-and-Bound optimal solve
        comp_res = comparator.solve(workload, win_slice, constraints, objective_mode="cost")
        if not comp_res.is_supported or comp_res.optimal_cost_usd is None:
            raise RuntimeError(f"Comparator solve failed unexpectedly for small instance {spec['id']}: {comp_res.reason}")

        optimal_cost = comp_res.optimal_cost_usd
        optimal_emiss = comp_res.optimal_emissions_kg

        # 2. Evaluate each policy under perfect-information oracle
        oracle_fc = generate_oracle_forecast(win_slice)
        fc_df = pd.DataFrame([
            {
                "window_id": wid,
                "horizon_hour": p.horizon_hours,
                "predicted_price_usd_per_mwh": p.predicted_price_usd_per_mwh,
                "predicted_carbon_g_per_kwh": p.predicted_carbon_g_per_kwh,
            }
            for p in oracle_fc.points
        ])

        for pol_name, pol_inst in policies.items():
            sched = pol_inst.schedule(workload, oracle_fc, constraints)
            m = compute_schedule_metrics(
                sched,
                workload,
                win_slice,
                fc_df,
                window_id=wid,
                window_type=wtype,
                comparator_objective=optimal_cost,
                comparator_gap=round(sched.total_cost_usd - optimal_cost, 4) if sched.total_cost_usd is not None else None,
                comparator_status="optimal",
                comparator_reason=comp_res.reason,
            )

            cost_gap = round(m["total_realized_cost_usd"] - optimal_cost, 4)
            pct_gap = round((cost_gap / optimal_cost) * 100.0, 2) if optimal_cost > 0 else 0.0

            results.append({
                "validation_id": spec["id"],
                "window_id": wid,
                "window_type": wtype,
                "horizon_hours": horizon,
                "job_count": jcount,
                "policy_name": pol_name,
                "policy_version": pol_inst.policy_version,
                "is_feasible": m["is_feasible"],
                "realized_cost_usd": m["total_realized_cost_usd"],
                "optimal_cost_usd": optimal_cost,
                "cost_optimality_gap_usd": cost_gap,
                "cost_optimality_gap_pct": pct_gap,
                "realized_emissions_kg": m["total_realized_emissions_kg"],
                "optimal_emissions_kg": optimal_emiss,
                "comparator_status": "optimal",
                "comparator_reason": comp_res.reason,
            })

    val_df = pd.DataFrame(results)
    csv_path = out_dir / "p5_5_comparator_validation_results.csv"
    json_path = out_dir / "p5_5_comparator_validation_results.json"
    val_df.to_csv(csv_path, index=False)

    summary = {
        "status": "VERIFIED_SUPPORTED",
        "total_instances_evaluated": len(val_specs),
        "total_policy_evaluations": len(val_df),
        "all_instances_optimal": bool((val_df["comparator_status"] == "optimal").all()),
        "mean_gap_usd_by_policy": {k: float(v) for k, v in val_df.groupby("policy_name")["cost_optimality_gap_usd"].mean().items()},
        "csv_path": str(csv_path),
        "csv_sha256": sha256_file(csv_path),
    }

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    return val_df, summary
