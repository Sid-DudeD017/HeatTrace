"""Day 1 Smoke Run and P6 Thermal Experiment Grid entry point.

Runs thermal sensitivity evaluation for:
- 1 event / control pair (HW_20240702, CTRL_20240605)
- 1 existing policy (CostFirstGreedyPolicy)
- 1 identical workload (trace_standard_120h_v0)
- 2 policy classes (temperature_unaware, heat_aware)
- 3 thermal sensitivity levels (low, medium, high)
- Total runs = 2 windows * 1 policy * 2 policy classes * 3 sensitivity levels = 12 runs
- Writes Day 1 smoke results and manifest without touching P5/P5.5 artifacts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any
import pandas as pd
import yaml

from heattrace.ingest.provenance import sha256_file
from heattrace.policy.greedy import CostFirstGreedyPolicy
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    SchedulingConstraints,
)
from heattrace.thermal.model import (
    ThermalScenario,
    build_hourly_thermal_state,
)
from heattrace.thermal.metrics import score_thermal_schedule
from heattrace.thermal.scheduler import (
    HeatAwareCapacityAdapter,
    create_temperature_unaware_schedule,
)
from heattrace.thermal.validation import (
    compute_configuration_digest,
    compute_workload_digest,
    validate_matched_inputs,
    validate_schedule_bounds,
)


def load_p6_thermal_config(config_path: Path) -> dict[str, Any]:
    """Load and parse p6_thermal.yaml."""
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_p6_thermal_smoke(
    benchmark_parquet_path: Path,
    workload_parquet_path: Path,
    forecast_parquet_path: Path,
    config_path: Path,
    output_dir: Path,
    manifest_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute Day 1 deterministic thermal smoke run."""
    config = load_p6_thermal_config(config_path)
    config_digest = compute_configuration_digest(config)

    # 1. Load benchmark and workload datasets
    bench_df = pd.read_parquet(benchmark_parquet_path)
    workload_df = pd.read_parquet(workload_parquet_path)
    forecast_all_df = pd.read_parquet(forecast_parquet_path)

    event_id = str(config["windows"]["event"])
    ctrl_id = str(config["windows"]["control"])
    expected_horizon = int(config["windows"]["expected_horizon_hours"])

    # Load and strictly validate facility parameters from YAML
    facility_cfg = config.get("facility", {})
    nominal_compute_cap_kw = float(facility_cfg.get("nominal_compute_capacity_kw", 500.0))
    if nominal_compute_cap_kw <= 0.0 or not math.isfinite(nominal_compute_cap_kw):
        raise ValueError(f"nominal_compute_capacity_kw must be positive and finite, got {nominal_compute_cap_kw}")

    max_concurrent_jobs = int(facility_cfg.get("max_concurrent_jobs", 16))
    if max_concurrent_jobs <= 0:
        raise ValueError(f"max_concurrent_jobs must be a positive integer, got {max_concurrent_jobs}")

    facility_base_pue = float(facility_cfg.get("base_pue", 1.20))
    model_base_pue = float(config["thermal_model"]["base_pue"])
    if not math.isclose(facility_base_pue, model_base_pue, rel_tol=1e-6):
        raise ValueError(f"facility base_pue ({facility_base_pue}) must match thermal_model base_pue ({model_base_pue})")

    tol_kw = float(facility_cfg.get("violation_tolerance_kw", 1e-6))
    if tol_kw < 0.0 or not math.isfinite(tol_kw):
        raise ValueError(f"violation_tolerance_kw must be finite and non-negative, got {tol_kw}")

    threshold_temp = float(config["thermal_model"]["threshold_temperature_c"])
    derived_facility_cap_kw = float(nominal_compute_cap_kw * facility_base_pue)

    # Split windows
    event_df = (
        bench_df[bench_df["window_id"] == event_id]
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )
    ctrl_df = (
        bench_df[bench_df["window_id"] == ctrl_id]
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )

    # Build thermal scenarios
    scenarios: dict[str, ThermalScenario] = {}
    for sc_id, sc_cfg in config["thermal_model"]["scenarios"].items():
        scenarios[sc_id] = ThermalScenario(
            scenario_id=sc_id,
            base_pue=model_base_pue,
            threshold_temperature_c=threshold_temp,
            slope_per_c=float(sc_cfg["slope_per_c"]),
            max_pue=float(sc_cfg["max_pue"]),
        )

    # Validate matched inputs with complete metadata enforcement
    val_meta = validate_matched_inputs(
        event_df=event_df,
        control_df=ctrl_df,
        event_workload=workload_df,
        control_workload=workload_df,
        expected_horizon_hours=expected_horizon,
        config=config,
        nominal_compute_cap_kw_event=nominal_compute_cap_kw,
        nominal_compute_cap_kw_control=nominal_compute_cap_kw,
        scenarios_event=scenarios,
        scenarios_control=scenarios,
    )
    workload_digest = val_meta["event_workload_digest"]

    base_policy = CostFirstGreedyPolicy()
    nominal_constraints = SchedulingConstraints(
        max_cluster_power_kw=nominal_compute_cap_kw,
        max_concurrent_jobs=max_concurrent_jobs,
    )

    smoke_rows: list[dict[str, Any]] = []

    windows = [
        ("event", event_id, event_df),
        ("control", ctrl_id, ctrl_df),
    ]

    for win_type, win_id, win_realized in windows:
        # Build ForecastResult for window
        win_fc_rows = (
            forecast_all_df[forecast_all_df["window_id"] == win_id]
            .sort_values("horizon_hour")
            .reset_index(drop=True)
        )
        pts = [
            ForecastPoint(
                timestamp_utc=row["target_timestamp_utc"],
                horizon_hours=int(row["horizon_hour"]),
                predicted_price_usd_per_mwh=float(row["predicted_price_usd_per_mwh"]),
                predicted_carbon_g_per_kwh=float(row["predicted_carbon_g_per_kwh"]),
            )
            for _, row in win_fc_rows.iterrows()
        ]
        fc_res = ForecastResult(
            origin_timestamp_utc=win_fc_rows["origin_timestamp_utc"].iloc[0],
            points=pts,
            model_name=str(win_fc_rows["model_name"].iloc[0]),
            model_version=str(win_fc_rows["model_version"].iloc[0]),
        )

        for sc_id, scenario in scenarios.items():
            thermal_state = build_hourly_thermal_state(
                win_realized, scenario, nominal_compute_cap_kw=nominal_compute_cap_kw
            )
            eff_cap_kw = thermal_state["effective_compute_capacity_kw"].to_numpy()

            # Class 1: temperature_unaware
            unaware_sched = create_temperature_unaware_schedule(
                base_policy, workload_df, fc_res, nominal_constraints
            )
            validate_schedule_bounds(unaware_sched, workload_df, expected_horizon)
            _, unaw_metrics = score_thermal_schedule(
                unaware_sched,
                workload_df,
                win_realized,
                thermal_state,
                violation_tolerance_kw=tol_kw,
            )

            smoke_rows.append({
                "window_type": win_type,
                "window_id": win_id,
                "policy_class": "temperature_unaware",
                "policy_name": unaware_sched.policy_name,
                "policy_version": unaware_sched.policy_version,
                "thermal_scenario_id": sc_id,
                "nominal_compute_capacity_kw": nominal_compute_cap_kw,
                "facility_power_cap_kw": derived_facility_cap_kw,
                **unaw_metrics,
            })

            # Class 2: heat_aware
            adapter = HeatAwareCapacityAdapter(
                base_policy,
                eff_cap_kw,
                tolerance_kw=tol_kw,
            )
            aware_sched = adapter.schedule(workload_df, fc_res, nominal_constraints)
            validate_schedule_bounds(aware_sched, workload_df, expected_horizon)
            _, awar_metrics = score_thermal_schedule(
                aware_sched,
                workload_df,
                win_realized,
                thermal_state,
                violation_tolerance_kw=tol_kw,
            )

            smoke_rows.append({
                "window_type": win_type,
                "window_id": win_id,
                "policy_class": "heat_aware",
                "policy_name": aware_sched.policy_name,
                "policy_version": aware_sched.policy_version,
                "thermal_scenario_id": sc_id,
                "nominal_compute_capacity_kw": nominal_compute_cap_kw,
                "facility_power_cap_kw": derived_facility_cap_kw,
                **awar_metrics,
            })

    results_df = pd.DataFrame(smoke_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    results_csv_path = output_dir / "p6_day1_smoke_results.csv"
    results_df.to_csv(results_csv_path, index=False)

    manifest_path = manifest_dir / "p6_day1_smoke_manifest.json"

    # Compute repository-relative paths where possible
    try:
        repo_root = Path(".").resolve()
        rel_csv_path = str(results_csv_path.resolve().relative_to(repo_root))
        rel_config_path = str(config_path.resolve().relative_to(repo_root))
        rel_benchmark_path = str(benchmark_parquet_path.resolve().relative_to(repo_root))
        rel_workload_path = str(workload_parquet_path.resolve().relative_to(repo_root))
        rel_forecast_path = str(forecast_parquet_path.resolve().relative_to(repo_root))
    except Exception:
        rel_csv_path = str(results_csv_path)
        rel_config_path = str(config_path)
        rel_benchmark_path = str(benchmark_parquet_path)
        rel_workload_path = str(workload_parquet_path)
        rel_forecast_path = str(forecast_parquet_path)

    manifest_content = {
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "P6_Day1_Smoke",
        "experiment_label": config.get("experiment_label", "controlled_thermal_stress"),
        "version": config.get("version", "1.0"),
        "provenance_hashes": {
            "configuration_file_sha256": sha256_file(config_path),
            "canonical_configuration_digest": config_digest,
            "benchmark_parquet_sha256": sha256_file(benchmark_parquet_path),
            "workload_parquet_sha256": sha256_file(workload_parquet_path),
            "canonical_workload_digest": workload_digest,
            "forecast_parquet_sha256": sha256_file(forecast_parquet_path),
            "results_csv_sha256": sha256_file(results_csv_path),
        },
        "experiment_parameters": {
            "nominal_compute_capacity_kw": nominal_compute_cap_kw,
            "derived_facility_cap_kw": derived_facility_cap_kw,
            "max_concurrent_jobs": max_concurrent_jobs,
            "violation_tolerance_kw": tol_kw,
            "policy_name": base_policy.policy_name,
            "policy_version": base_policy.policy_version,
            "event_window_id": event_id,
            "control_window_id": ctrl_id,
            "expected_horizon_hours": expected_horizon,
            "thermal_scenario_ids": list(scenarios.keys()),
        },
        "source_paths": {
            "config_path": rel_config_path,
            "benchmark_parquet_path": rel_benchmark_path,
            "workload_parquet_path": rel_workload_path,
            "forecast_parquet_path": rel_forecast_path,
            "results_csv_path": rel_csv_path,
        },
        "total_runs": len(results_df),
        "results_files": {
            "csv": {
                "path": rel_csv_path,
                "sha256": sha256_file(results_csv_path),
                "row_count": len(results_df),
            }
        },
        "summary": {
            "runs_evaluated": len(results_df),
            "windows": [ctrl_id, event_id],
            "scenarios": list(scenarios.keys()),
            "policy_classes": ["temperature_unaware", "heat_aware"],
            "feasible_runs": int(results_df["thermally_feasible"].sum()),
            "infeasible_runs": int((~results_df["thermally_feasible"]).sum()),
        },
        "disclaimer": "Day 1 smoke test run only; implementation verification check, not scientific finding.",
    }

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_content, f, indent=2)

    return results_df, manifest_content


def main() -> int:
    parser = argparse.ArgumentParser(description="HeatTrace P6 Day 1 Thermal Stress Smoke Runner")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/p6_thermal.yaml"),
        help="Path to p6_thermal.yaml configuration",
    )
    args = parser.parse_args()

    repo_root = Path(".").resolve()
    print("\n================== HeatTrace P6 Day 1 Thermal Stress Smoke ==================")
    try:
        results_df, manifest = run_p6_thermal_smoke(
            benchmark_parquet_path=repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet",
            workload_parquet_path=repo_root / "data/workloads/workload_trace_v0.parquet",
            forecast_parquet_path=repo_root / "data/forecasts/p4_historical_forecasts_v0.parquet",
            config_path=repo_root / args.config,
            output_dir=repo_root / "data/results",
            manifest_dir=repo_root / "data/manifests",
        )
        print(f"Success! Executed {len(results_df)} runs.")
        print(f"Results written to: {manifest['results_files']['csv']['path']}")
        print(f"Manifest written to: {repo_root / 'data/manifests/p6_day1_smoke_manifest.json'}")
        print(f"Feasible runs: {manifest['summary']['feasible_runs']}/{len(results_df)}")
        print("============================================================================\n")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n[P6 THERMAL SMOKE ERROR] Failed: {e}\n")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
