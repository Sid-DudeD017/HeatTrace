"""Gate G4-a comprehensive audit for HeatTrace P4."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.forecast.schema import validate_forecast_dataframe
from heattrace.ingest.provenance import sha256_file
from heattrace.manifests import (
    validate_p4_experiment_manifest,
    write_atomic_json,
)
from heattrace.process.audit import validate_file_entry_schema
from heattrace.schemas import (
    validate_metrics_dictionary,
    validate_schedule_dataframe,
)


def run_g4_audit(
    *,
    repo_root: Path,
    data_dir: Path | None = None,
    runs_dir: Path | None = None,
    config_dir: Path | None = None,
    output_audit_path: Path | None = None,
) -> dict[str, Any]:
    """Execute gate G4-a comprehensive verification audit."""
    repo_root = repo_root.resolve()
    if data_dir is None:
        data_dir = repo_root / "data"
    else:
        data_dir = data_dir.resolve()

    if runs_dir is None:
        runs_dir = repo_root / "runs/p4_v0"
    else:
        runs_dir = runs_dir.resolve()

    if config_dir is None:
        config_dir = repo_root / "configs"
    else:
        config_dir = config_dir.resolve()

    if output_audit_path is None:
        output_audit_path = data_dir / "manifests/p4_comprehensive_audit.json"
    else:
        output_audit_path = output_audit_path.resolve()

    failure_reasons: list[str] = []

    # 1. P4 Experiment Manifest
    exp_m_path = data_dir / "manifests/p4_experiment_manifest.json"
    if not exp_m_path.exists():
        failure_reasons.append("data/manifests/p4_experiment_manifest.json missing")
        exp_m_data = {}
    else:
        with exp_m_path.open("r", encoding="utf-8") as f:
            exp_m_data = json.load(f)
        exp_errs = validate_p4_experiment_manifest(exp_m_data, repo_root=repo_root)
        failure_reasons.extend(exp_errs)

    # 2. Forecast Artifacts
    fc_m_path = data_dir / "manifests/p4_forecast_manifest.json"
    if not fc_m_path.exists():
        failure_reasons.append("data/manifests/p4_forecast_manifest.json missing")
    else:
        with fc_m_path.open("r", encoding="utf-8") as f:
            fc_m_data = json.load(f)
        for k, entry in fc_m_data.get("output_files", {}).items():
            errs = validate_file_entry_schema(entry, manifest_name="p4_forecast_manifest.json", context=k, repo_root=repo_root)
            failure_reasons.extend(errs)

    fc_parquet_path = data_dir / "forecasts/p4_historical_forecasts_v0.parquet"
    if not fc_parquet_path.exists():
        failure_reasons.append("data/forecasts/p4_historical_forecasts_v0.parquet missing")
    else:
        fc_df = pd.read_parquet(fc_parquet_path)
        fc_errs = validate_forecast_dataframe(fc_df, expected_rows=240)
        failure_reasons.extend(fc_errs)

    # 3. Run Manifest and artifacts
    run_m_path = runs_dir / "run_manifest.json"
    if not run_m_path.exists():
        failure_reasons.append("runs/p4_v0/run_manifest.json missing")
    else:
        with run_m_path.open("r", encoding="utf-8") as f:
            run_m_data = json.load(f)
        for rel_p, meta in run_m_data.get("output_files", {}).items():
            full_p = runs_dir / rel_p
            if not full_p.exists():
                failure_reasons.append(f"Run output file '{rel_p}' does not exist on disk")
            else:
                act_sha = sha256_file(full_p)
                if act_sha != meta.get("sha256"):
                    failure_reasons.append(f"Run output file '{rel_p}' hash mismatch")

    # 4. Workload validation
    wl_path = data_dir / "workloads/workload_trace_v0.parquet"
    if not wl_path.exists():
        failure_reasons.append("Workload parquet missing")
        workload_df = pd.DataFrame()
    else:
        workload_df = pd.read_parquet(wl_path)

    # 5. Production Policies and Windows Verification
    expected_policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]
    expected_windows = ["CTRL_20240605", "HW_20240702"]

    for wid in expected_windows:
        for pol in expected_policies:
            pol_dir = runs_dir / wid / pol
            if not pol_dir.exists():
                failure_reasons.append(f"Policy run directory missing: {wid}/{pol}")
                continue

            # Verify feasibility report
            feas_path = pol_dir / "feasibility.json"
            if not feas_path.exists():
                failure_reasons.append(f"Feasibility report missing: {wid}/{pol}")
            else:
                with feas_path.open("r", encoding="utf-8") as f:
                    feas_data = json.load(f)
                if not feas_data.get("is_feasible", False):
                    failure_reasons.append(f"Schedule for {wid}/{pol} is marked infeasible: {feas_data.get('violations')}")

            # Verify schedule dataframe
            sched_p = pol_dir / "schedule.parquet"
            if not sched_p.exists():
                failure_reasons.append(f"Schedule parquet missing: {wid}/{pol}")
            elif not workload_df.empty:
                s_df = pd.read_parquet(sched_p)
                s_errs = validate_schedule_dataframe(s_df, workload_df)
                failure_reasons.extend([f"{wid}/{pol}: {e}" for e in s_errs])

            # Verify metrics
            m_path = pol_dir / "metrics.json"
            if not m_path.exists():
                failure_reasons.append(f"Metrics JSON missing: {wid}/{pol}")
            else:
                with m_path.open("r", encoding="utf-8") as f:
                    m_data = json.load(f)
                m_errs = validate_metrics_dictionary(m_data)
                failure_reasons.extend([f"{wid}/{pol}: {e}" for e in m_errs])
                # Check carbon disclosure
                if m_data.get("carbon_interpretation_label") != "quality_limited_sensitivity_only":
                    failure_reasons.append(f"{wid}/{pol}: invalid carbon interpretation label")

    # 6. Protected Artifact Hashes Check
    protected_hashes = {
        "hourly_caiso_v0.parquet": (data_dir / "processed/hourly_caiso_v0.parquet", "c41e2c26f1e350f78458910c6dddf9ec3004caaaafc2a961b5c7367a31f0eefe"),
        "hourly_caiso_v0_sample.csv": (data_dir / "processed/hourly_caiso_v0_sample.csv", "3dbabe90bbc7beb67f09e16ca2430bf005056094b831f6f5315ef0171942ebb3"),
        "heatwave_events_v0.parquet": (data_dir / "events/heatwave_events_v0.parquet", "22edce3ac72eef8c0b77e4f1839bd1ac1f83f43b5d065ffed1b4d4344066cb9c"),
        "control_catalogue_v0.parquet": (data_dir / "events/control_catalogue_v0.parquet", "38f9d419a449240863022406050c92bb29538323dda769e832f1fa796e889a21"),
        "benchmark_2024_event_control_v0.parquet": (data_dir / "benchmarks/benchmark_2024_event_control_v0.parquet", "711ac21fb3d7178453edaf6f31d139eaf9d8a7ec600af1bd7e3a85a2f5c4a142"),
        "p3_comprehensive_audit.json": (data_dir / "manifests/p3_comprehensive_audit.json", "634726174294d5dacaaabf32e6288031be507c15229b684b010cbda2a83d1cf7"),
    }
    for name, (path_obj, exp_hash) in protected_hashes.items():
        if not path_obj.exists():
            failure_reasons.append(f"Protected artifact {name} missing")
        else:
            cur_h = sha256_file(path_obj)
            if cur_h.lower() != exp_hash.lower():
                failure_reasons.append(f"Protected artifact {name} hash modified: {cur_h} != {exp_hash}")

    is_pass = (len(failure_reasons) == 0)
    audit_record = {
        "gate": "G4-a",
        "status": "VERIFIED_PASS" if is_pass else "VERIFIED_FAIL",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "failure_count": len(failure_reasons),
        "failure_reasons": failure_reasons,
        "checked_policies": expected_policies,
        "checked_windows": expected_windows,
        "carbon_data_quality": {
            "known_data_issue_rows": 240,
            "primary_analysis_eligible_rows": 0,
            "interpretation_label": "quality_limited_sensitivity_only",
        },
    }

    write_atomic_json(output_audit_path, audit_record)
    return audit_record
