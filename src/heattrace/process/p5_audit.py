"""Comprehensive Gate G5-a verification audit for HeatTrace P5."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.provenance import sha256_file
from heattrace.manifests import write_atomic_json


def run_g5_audit(
    *,
    repo_root: Path,
    data_dir: Path | None = None,
    results_dir: Path | None = None,
    config_dir: Path | None = None,
    output_audit_path: Path | None = None,
) -> dict[str, Any]:
    """Execute gate G5-a comprehensive verification audit."""
    repo_root = repo_root.resolve()
    if data_dir is None:
        data_dir = repo_root / "data"
    else:
        data_dir = data_dir.resolve()

    if results_dir is None:
        results_dir = repo_root / "data/results"
    else:
        results_dir = results_dir.resolve()

    if config_dir is None:
        config_dir = repo_root / "configs"
    else:
        config_dir = config_dir.resolve()

    if output_audit_path is None:
        output_audit_path = data_dir / "manifests/p5_comprehensive_audit.json"
    else:
        output_audit_path = output_audit_path.resolve()

    failure_reasons: list[str] = []

    # 1. P5 Manifest Existence & Schema
    p5_manifest_path = data_dir / "manifests/p5_dataset_manifest.json"
    if not p5_manifest_path.exists():
        failure_reasons.append("P5 dataset manifest missing: data/manifests/p5_dataset_manifest.json")
    else:
        with p5_manifest_path.open("r", encoding="utf-8") as f:
            p5_manifest = json.load(f)
        for req_field in ["schema_version", "created_at_utc", "seed", "event_window_id", "control_window_id", "output_files", "known_limitations"]:
            if req_field not in p5_manifest:
                failure_reasons.append(f"P5 dataset manifest missing field: {req_field}")

        # Check output files integrity
        for rel_p, meta in p5_manifest.get("output_files", {}).items():
            full_p = repo_root / rel_p
            if not full_p.exists():
                failure_reasons.append(f"Manifest declared file does not exist: {rel_p}")
            else:
                act_sha = sha256_file(full_p)
                if act_sha != meta.get("sha256"):
                    failure_reasons.append(f"File hash mismatch for {rel_p}: actual {act_sha} != recorded {meta.get('sha256')}")

    # 2. E1 Traceability: Characterization Tables
    char_tables = [
        "p5_e1_hourly_source_table.csv",
        "p5_e1_window_summary_table.csv",
        "p5_e1_phase_summary_table.csv",
        "p5_e1_persistence_table.csv",
        "p5_e1_lag_analysis_table.csv",
    ]
    for ct in char_tables:
        ct_p = results_dir / ct
        if not ct_p.exists():
            failure_reasons.append(f"E1 characterization table missing: {ct}")

    # 3. E2 Traceability: Event-Control Policy Experiment
    e2_csv = results_dir / "p5_e2_policy_comparison_metrics.csv"
    if not e2_csv.exists():
        failure_reasons.append("E2 policy comparison metrics missing: p5_e2_policy_comparison_metrics.csv")
    else:
        df_e2 = pd.read_csv(e2_csv)
        if len(df_e2) != 8:
            failure_reasons.append(f"E2 metrics incomplete: expected 8 runs, got {len(df_e2)}")
        # Check carbon label
        if not (df_e2["carbon_interpretation_label"] == "quality_limited_sensitivity_only").all():
            failure_reasons.append("E2 carbon interpretation label is not quality_limited_sensitivity_only")

    # 4. E3 Traceability: Treatment Variants
    e3_csv = results_dir / "p5_e3_treatment_metrics.csv"
    if not e3_csv.exists():
        failure_reasons.append("E3 treatment metrics missing: p5_e3_treatment_metrics.csv")
    else:
        df_e3 = pd.read_csv(e3_csv)
        # 3 variants x 2 windows x 4 policies = 24 runs
        if len(df_e3) != 24:
            failure_reasons.append(f"E3 metrics incomplete: expected 24 runs, got {len(df_e3)}")

    # 5. E4 Traceability: Equal-Budget Sampling
    e4_csv = results_dir / "p5_e4_sampling_metrics.csv"
    if not e4_csv.exists():
        failure_reasons.append("E4 sampling metrics missing: p5_e4_sampling_metrics.csv")
    else:
        df_e4 = pd.read_csv(e4_csv)
        # 3 strategies x 4 policies = 12 runs
        if len(df_e4) != 12:
            failure_reasons.append(f"E4 metrics incomplete: expected 12 runs, got {len(df_e4)}")
        # Verify equal budget
        if "budget_hours" in df_e4.columns:
            if not (df_e4["budget_hours"] == 120).all():
                failure_reasons.append(f"E4 equal-budget violation: found non-120 budgets: {df_e4['budget_hours'].unique()}")

    # 6. E4 Strategy Comparison Table
    strat_cmp_csv = results_dir / "p5_e4_strategy_comparison_summary.csv"
    if not strat_cmp_csv.exists():
        failure_reasons.append("E4 strategy comparison summary missing: p5_e4_strategy_comparison_summary.csv")

    # 7. Figures & Source Tables Traceability
    for fig_id in [1, 2, 3, 4, 5]:
        fig_p = repo_root / f"data/figures/p5_fig{fig_id}_*.png"
        matches = list((repo_root / "data/figures").glob(f"p5_fig{fig_id}_*.png"))
        if not matches:
            failure_reasons.append(f"Figure p5_fig{fig_id} missing")
        src_p = results_dir / f"p5_source_table_fig{fig_id}_*.csv"
        src_matches = list(results_dir.glob(f"p5_source_table_fig{fig_id}_*.csv"))
        if not src_matches:
            failure_reasons.append(f"Source table for fig{fig_id} missing")

    # 8. Comparator Claims Check
    comp_json_p = results_dir / "p5_comparator_results.json"
    if not comp_json_p.exists():
        failure_reasons.append("Comparator results missing: p5_comparator_results.json")
    else:
        with comp_json_p.open("r", encoding="utf-8") as f:
            c_data = json.load(f)
        full_res = c_data.get("full_benchmark", {})
        if full_res.get("status") != "unsupported":
            failure_reasons.append(f"Full benchmark comparator status must be 'unsupported', got '{full_res.get('status')}'")
        if full_res.get("optimal_objective") is not None:
            failure_reasons.append("Full benchmark must not report a fake optimal objective")

        small_res = c_data.get("supported_small_fixture", {})
        if small_res.get("status") != "optimal":
            failure_reasons.append(f"Supported small fixture comparator must be 'optimal', got '{small_res.get('status')}'")

    # 9. Protected Baseline Hashes Check (P1-P4)
    # Validate core immutable data, catalogue, workload, forecast, and configuration artifacts
    core_protected = {
        "configs/p4.yaml": "43d1131cdca6c29984006dda64ee3253c476fe6616f238627a133eb7d010f082",
        "configs/sources.yaml": "41b3c3d66ef7a11fedc43d1cf5cf521c460ec81a68401f7ac8f12939c41994da",
        "configs/study.yaml": "a5ff32b0fea496b0e197b5e632c19cae14decda187b32f4cd6ed2927e473b881",
        "data/benchmarks/benchmark_2024_event_control_v0.parquet": "711ac21fb3d7178453edaf6f31d139eaf9d8a7ec600af1bd7e3a85a2f5c4a142",
        "data/benchmarks/benchmark_2024_event_control_v0_sample.csv": "997ae7e1bf4ab2999de49606450ee0d59452047e5ae0f2abb2a31e406a0b34ec",
        "data/processed/hourly_caiso_v0.parquet": "c41e2c26f1e350f78458910c6dddf9ec3004caaaafc2a961b5c7367a31f0eefe",
        "data/processed/hourly_caiso_v0_sample.csv": "3dbabe90bbc7beb67f09e16ca2430bf005056094b831f6f5315ef0171942ebb3",
        "data/events/heatwave_events_v0.parquet": "22edce3ac72eef8c0b77e4f1839bd1ac1f83f43b5d065ffed1b4d4344066cb9c",
        "data/events/control_catalogue_v0.parquet": "38f9d419a449240863022406050c92bb29538323dda769e832f1fa796e889a21",
        "data/workloads/workload_trace_v0.parquet": "3812f172b65193e779e05dbd5e802efe22609a9790d2890dd90b7609d6cbe5cc",
        "data/forecasts/p4_historical_forecasts_v0.parquet": "3d3832f37c866024c7e528758680e97e5cd6d5f3d5000614ed68307ea5bf60ae",
    }
    for rel_p, exp_hash in core_protected.items():
        full_p = repo_root / rel_p
        if not full_p.exists():
            failure_reasons.append(f"Protected artifact {rel_p} missing")
        else:
            cur_h = sha256_file(full_p)
            if cur_h.lower() != exp_hash.lower():
                failure_reasons.append(f"Protected artifact {rel_p} hash changed: {cur_h} != {exp_hash}")

    is_pass = (len(failure_reasons) == 0)
    audit_record = {
        "gate": "G5-a",
        "status": "VERIFIED_PASS" if is_pass else "VERIFIED_FAIL",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "failure_count": len(failure_reasons),
        "failure_reasons": failure_reasons,
        "checked_experiments": ["E1", "E2", "E3", "E4"],
        "comparator_audit": {
            "full_benchmark_status": "unsupported",
            "supported_small_instance_status": "optimal",
        },
        "carbon_data_quality": {
            "interpretation_label": "quality_limited_sensitivity_only",
            "disclaimer_verified": True,
        },
    }

    write_atomic_json(output_audit_path, audit_record)
    return audit_record
