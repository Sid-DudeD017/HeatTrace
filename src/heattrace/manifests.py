"""P4 experiment and forecast manifest builder and strict validator."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.provenance import sha256_file
from heattrace.process.audit import validate_file_entry_schema


P4_EXPERIMENT_MANIFEST_VERSION = "1.0"
P4_FORECAST_MANIFEST_VERSION = "1.0"


def build_p4_forecast_manifest(
    forecast_parquet_path: Path,
    forecast_sample_csv_path: Path,
    *,
    p4_config_path: Path,
    repo_root: Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build forecast manifest with strict hashes and file sizes."""
    if generated_at_utc is None:
        generated_at_utc = datetime.now(timezone.utc).isoformat()

    cfg = load_yaml(p4_config_path)

    f_p_rel = forecast_parquet_path.relative_to(repo_root).as_posix()
    f_s_rel = forecast_sample_csv_path.relative_to(repo_root).as_posix()
    cfg_rel = p4_config_path.relative_to(repo_root).as_posix()

    return {
        "manifest_version": P4_FORECAST_MANIFEST_VERSION,
        "generated_at_utc": generated_at_utc,
        "configuration_path": cfg_rel,
        "provider": cfg.get("forecast", {}).get("provider", "historical_persistence_v0"),
        "fallback_price_usd_per_mwh": cfg.get("forecast", {}).get("fallback_price_usd_per_mwh", 45.0),
        "fallback_carbon_g_per_kwh": cfg.get("forecast", {}).get("fallback_carbon_g_per_kwh", 220.0),
        "forbid_future_actuals": cfg.get("forecast", {}).get("forbid_future_actuals", True),
        "windows": [
            cfg.get("benchmark", {}).get("control_window_id", "CTRL_20240605"),
            cfg.get("benchmark", {}).get("event_window_id", "HW_20240702"),
        ],
        "horizon_hours": cfg.get("benchmark", {}).get("horizon_hours", 120),
        "output_files": {
            "forecast_parquet": {
                "path": f_p_rel,
                "sha256": sha256_file(forecast_parquet_path),
                "size_bytes": forecast_parquet_path.stat().st_size,
            },
            "forecast_sample_csv": {
                "path": f_s_rel,
                "sha256": sha256_file(forecast_sample_csv_path),
                "size_bytes": forecast_sample_csv_path.stat().st_size,
            },
        },
    }


def build_p4_experiment_manifest(
    *,
    repo_root: Path,
    p4_config_path: Path | None = None,
    generated_at_utc: str | None = None,
    git_commit: str | None = None,
) -> dict[str, Any]:
    """Build the official P4-01 experiment manifest."""
    repo_root = repo_root.resolve()
    if p4_config_path is None:
        p4_config_path = repo_root / "configs/p4.yaml"
    else:
        p4_config_path = p4_config_path.resolve()

    if generated_at_utc is None:
        generated_at_utc = datetime.now(timezone.utc).isoformat()

    study_cfg_path = repo_root / "configs/study.yaml"
    study_cfg = load_yaml(study_cfg_path)
    p4_cfg = load_yaml(p4_config_path)

    # Check git commit if not provided
    if git_commit is None:
        try:
            import subprocess
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
            git_commit = proc.stdout.strip()
        except Exception:
            git_commit = "unknown"

    # Define required input files
    required_inputs = {
        "benchmark_parquet": repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet",
        "heatwave_events_parquet": repo_root / "data/events/heatwave_events_v0.parquet",
        "control_catalogue_parquet": repo_root / "data/events/control_catalogue_v0.parquet",
        "workload_trace_parquet": repo_root / "data/workloads/workload_trace_v0.parquet",
        "p3_benchmark_manifest": repo_root / "data/manifests/benchmark_manifest.json",
        "p3_comprehensive_audit": repo_root / "data/manifests/p3_comprehensive_audit.json",
        "p4_config": p4_config_path,
    }

    input_files_meta: dict[str, Any] = {}
    for key, fpath in required_inputs.items():
        if not fpath.exists():
            raise FileNotFoundError(f"Required input artifact missing: {fpath}")
        rel_p = fpath.relative_to(repo_root).as_posix()
        input_files_meta[key] = {
            "path": rel_p,
            "sha256": sha256_file(fpath),
            "size_bytes": fpath.stat().st_size,
        }

    # Chronological splits from study.yaml
    chron_splits = study_cfg.get("chronological_splits", {
        "training_years": [2022, 2023],
        "validation_years": [2024],
        "test_years": [2025],
    })

    # Expected P4 output paths
    expected_outputs = {
        "experiment_manifest": "data/manifests/p4_experiment_manifest.json",
        "forecast_manifest": "data/manifests/p4_forecast_manifest.json",
        "forecast_parquet": "data/forecasts/p4_historical_forecasts_v0.parquet",
        "forecast_sample_csv": "data/forecasts/p4_historical_forecasts_v0_sample.csv",
        "run_manifest": "runs/p4_v0/run_manifest.json",
        "comparison_metrics_csv": "runs/p4_v0/comparison_metrics.csv",
        "comparison_metrics_json": "runs/p4_v0/comparison_metrics.json",
        "g4_audit_json": "data/manifests/p4_comprehensive_audit.json",
    }

    manifest = {
        "manifest_version": P4_EXPERIMENT_MANIFEST_VERSION,
        "schema_version": "1.0",
        "generated_at_utc": generated_at_utc,
        "git_commit": git_commit,
        "random_seed": p4_cfg.get("random_seed", 20261016),
        "chronological_splits": {
            "training": "2022-2023",
            "validation": "2024",
            "test": "2025",
            "details": chron_splits,
        },
        "windows": {
            "event_window_id": p4_cfg.get("benchmark", {}).get("event_window_id", "HW_20240702"),
            "control_window_id": p4_cfg.get("benchmark", {}).get("control_window_id", "CTRL_20240605"),
            "horizon_hours": p4_cfg.get("benchmark", {}).get("horizon_hours", 120),
        },
        "workload": {
            "trace_id": "trace_standard_120h_v0",
            "seed": p4_cfg.get("random_seed", 20261016),
        },
        "scheduling_constraints": p4_cfg.get("constraints", {
            "max_cluster_power_kw": 500.0,
            "max_concurrent_jobs": 16,
            "arrival_inclusive": True,
            "deadline_exclusive": True,
        }),
        "forecast_specification": {
            "methodology": "causal_historical_persistence",
            "provider": p4_cfg.get("forecast", {}).get("provider", "historical_persistence_v0"),
            "version": "1.0",
            "fallback_price_usd_per_mwh": p4_cfg.get("forecast", {}).get("fallback_price_usd_per_mwh", 45.0),
            "fallback_carbon_g_per_kwh": p4_cfg.get("forecast", {}).get("fallback_carbon_g_per_kwh", 220.0),
            "forbid_future_actuals": True,
        },
        "policies": [
            {"name": "cost_first", "version": "1.0", "type": "greedy"},
            {"name": "carbon_first", "version": "1.0", "type": "greedy"},
            {"name": "balanced", "version": "1.0", "type": "greedy"},
            {"name": "dro_inspired", "version": "1.0", "type": "risk_penalized_heuristic"},
        ],
        "metric_definitions": {
            "cvar_alpha": p4_cfg.get("risk", {}).get("cvar_alpha", 0.90),
            "uncertainty_quantile": p4_cfg.get("risk", {}).get("uncertainty_quantile", 0.90),
            "dro_risk_penalty_lambda": p4_cfg.get("risk", {}).get("dro_risk_penalty_lambda", 0.25),
        },
        "carbon_data_quality_declaration": {
            "known_data_issue_rows": 240,
            "primary_analysis_eligible_rows": 0,
            "interpretation_label": "quality_limited_sensitivity_only",
            "disclosure": (
                "All 240 benchmark rows carry EIA known-data-issue flags. Carbon intensity metrics "
                "are technically evaluated for algorithmic sensitivity and stress testing only, and must not "
                "be interpreted as clean primary causal evidence."
            ),
        },
        "forecast_actual_separation_declaration": {
            "is_separate": True,
            "statement": (
                "Forecast inputs and realized scoring inputs are strictly isolated. Policies receive only "
                "ForecastResult structures containing historical predictions; realized actual prices and "
                "carbon intensities are joined strictly post-scheduling for evaluation."
            ),
        },
        "input_files": input_files_meta,
        "expected_output_paths": expected_outputs,
    }

    return manifest


def validate_p4_experiment_manifest(manifest_data: dict[str, Any], repo_root: Path) -> list[str]:
    """Strictly validate P4 experiment manifest against schema and filesystem state."""
    errors: list[str] = []
    repo_root = repo_root.resolve()

    if not isinstance(manifest_data, dict):
        return ["Experiment manifest must be a JSON object"]

    # Required top-level fields
    req_fields = [
        "manifest_version",
        "schema_version",
        "generated_at_utc",
        "git_commit",
        "random_seed",
        "chronological_splits",
        "windows",
        "workload",
        "scheduling_constraints",
        "forecast_specification",
        "policies",
        "metric_definitions",
        "carbon_data_quality_declaration",
        "forecast_actual_separation_declaration",
        "input_files",
        "expected_output_paths",
    ]
    for rf in req_fields:
        if rf not in manifest_data:
            errors.append(f"Missing required field '{rf}'")

    if errors:
        return errors

    # Check manifest version
    if manifest_data["manifest_version"] != P4_EXPERIMENT_MANIFEST_VERSION:
        errors.append(f"Invalid manifest_version '{manifest_data['manifest_version']}'")

    # Validate input files schema and digests
    input_files = manifest_data.get("input_files", {})
    if not isinstance(input_files, dict):
        errors.append("input_files must be a dict")
    else:
        for k, entry in input_files.items():
            errs = validate_file_entry_schema(
                entry,
                manifest_name="p4_experiment_manifest.json",
                context=f"input_files.{k}",
                repo_root=repo_root,
            )
            errors.extend(errs)

    # Validate path escapes in expected_output_paths
    exp_outs = manifest_data.get("expected_output_paths", {})
    if not isinstance(exp_outs, dict):
        errors.append("expected_output_paths must be a dict")
    else:
        for k, p_str in exp_outs.items():
            p_obj = Path(p_str)
            if p_obj.is_absolute():
                errors.append(f"expected_output_paths.{k} must not be absolute: '{p_str}'")
            if ".." in p_obj.parts:
                errors.append(f"expected_output_paths.{k} path escape '../' not permitted: '{p_str}'")

    # Separation declaration
    sep = manifest_data.get("forecast_actual_separation_declaration", {})
    if not sep.get("is_separate"):
        errors.append("forecast_actual_separation_declaration.is_separate must be True")

    # Carbon declaration
    carb = manifest_data.get("carbon_data_quality_declaration", {})
    if carb.get("interpretation_label") != "quality_limited_sensitivity_only":
        errors.append(f"carbon_data_quality_declaration.interpretation_label must be 'quality_limited_sensitivity_only', got '{carb.get('interpretation_label')}'")

    return errors


def write_atomic_json(filepath: Path, data: dict[str, Any]) -> None:
    """Write JSON data atomically using a staging file and atomic rename."""
    filepath = filepath.resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    stage_path = filepath.with_name(f"{filepath.name}.tmp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")

    try:
        with stage_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
        stage_path.replace(filepath)
    except Exception:
        if stage_path.exists():
            stage_path.unlink()
        raise


def write_atomic_csv(filepath: Path, df: pd.DataFrame, **to_csv_kwargs: Any) -> None:
    """Write DataFrame to CSV atomically using a sibling staging file and atomic rename."""
    filepath = filepath.resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    stage_path = filepath.with_name(f"{filepath.name}.tmp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")

    try:
        df.to_csv(stage_path, **to_csv_kwargs)
        stage_path.replace(filepath)
    except Exception:
        if stage_path.exists():
            stage_path.unlink()
        raise


def write_atomic_figure(filepath: Path, fig: Any, **savefig_kwargs: Any) -> None:
    """Save matplotlib figure atomically using a sibling staging file and atomic rename."""
    filepath = filepath.resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    suffix = filepath.suffix
    stage_path = filepath.with_name(f"{filepath.stem}_tmp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{suffix}")

    try:
        fig.savefig(stage_path, **savefig_kwargs)
        stage_path.replace(filepath)
    except Exception:
        if stage_path.exists():
            stage_path.unlink()
        raise
