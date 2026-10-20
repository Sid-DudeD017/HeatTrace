"""Tests for HeatTrace P3-05 Control Matching, P3-06 Audit, and G3-a Benchmark."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
import pandas as pd

from heattrace.process.benchmark import (
    BENCHMARK_COLUMNS,
    build_and_export_p3_benchmark,
    validate_benchmark_dataframe,
)
from heattrace.process.controls import (
    CONTROL_CATALOGUE_COLUMNS,
    build_and_export_controls,
    match_deterministic_control,
    validate_control_dataframe,
)
from heattrace.process.events import compute_heatwave_percentile_threshold, detect_heatwave_events, load_heatwave_config
from heattrace.process.audit import run_p3_audit


def test_p3_05_deterministic_control_matching():
    """Verify control matching generates exactly 120h non-heatwave window around 2024-06-07."""
    base_dir = Path(__file__).resolve().parents[1]
    hw_cfg = load_heatwave_config(config_dir=base_dir / "configs")
    years = hw_cfg["years"]
    station_id = hw_cfg["station_id"]
    files = [base_dir / f"data/raw/noaa/GHCNh_{station_id}_{y}.psv" for y in years]

    thresh_info = compute_heatwave_percentile_threshold(
        files,
        station_id=station_id,
        years=years,
        months=hw_cfg["months"],
        target_timezone=hw_cfg["target_timezone"],
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
    )

    df_events, _ = detect_heatwave_events(
        thresh_info["daily_maxima"],
        thresh_info["threshold_p90_c"],
        station_id=station_id,
        target_timezone=hw_cfg["target_timezone"],
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
        min_consecutive_days=hw_cfg["min_consecutive_days"],
    )

    df_ctrl, candidates = match_deterministic_control(
        event_id="HW_20240702",
        df_events=df_events,
        daily_records=thresh_info["daily_maxima"],
        threshold_p90_c=thresh_info["threshold_p90_c"],
        target_year=2024,
        anchor_date="2024-06-07",
    )

    assert len(df_ctrl) == 1
    row = df_ctrl.iloc[0]
    assert row["control_id"] == "CTRL_20240605"
    assert row["matched_event_id"] == "HW_20240702"
    assert row["local_start_date"] == "2024-06-05"
    assert row["local_end_exclusive"] == "2024-06-10"
    assert int(row["duration_days"]) == 5
    assert int(row["duration_hours"]) == 120
    assert bool(row["is_eligible"]) is True
    assert row["anchor_date"] == "2024-06-07"


def test_g3_a_benchmark_alignment_and_dimensions():
    """Verify G3-a benchmark table has 240 rows, 120 event and 120 control, with zero missing values."""
    base_dir = Path(__file__).resolve().parents[1]
    res = build_and_export_p3_benchmark(data_dir=base_dir / "data", config_dir=base_dir / "configs")
    df = res["df_benchmark"]

    assert len(df) == 240
    assert list(df.columns) == BENCHMARK_COLUMNS

    ev_df = df[df["window_type"] == "event"]
    ctrl_df = df[df["window_type"] == "control"]

    assert len(ev_df) == 120
    assert len(ctrl_df) == 120
    assert ev_df["window_id"].unique().tolist() == ["HW_20240702"]
    assert ctrl_df["window_id"].unique().tolist() == ["CTRL_20240605"]

    # Check zero missingness across all required series
    assert (df["temperature_missing"] == False).all()
    assert (df["price_missing"] == False).all()
    assert (df["demand_missing"] == False).all()
    assert (df["net_generation_missing"] == False).all()
    assert (df["carbon_missing"] == False).all()

    # Carbon data issues are truthfully retained
    assert (df["carbon_data_issue"] == True).all()
    assert (df["carbon_primary_analysis_eligible"] == False).all()


def test_p3_06_audit_completeness():
    """Verify P3-06 audit reports all required fields, chronological splits, and unmatched reasons."""
    base_dir = Path(__file__).resolve().parents[1]
    audit_res = run_p3_audit(data_dir=base_dir / "data", config_dir=base_dir / "configs")

    assert audit_res["gate"] == "G3-a"
    assert audit_res["status"] == "verified_pass"
    assert audit_res["all_detected_events"] == ["HW_20220620", "HW_20220904", "HW_20220922", "HW_20240702"]
    assert audit_res["benchmark_eligible_events"] == ["HW_20240702"]
    assert audit_res["matched_events"] == ["HW_20240702"]
    assert len(audit_res["unmatched_events"]) == 3

    splits = audit_res["chronological_splits"]
    assert "training_years_2022_2023" in splits
    assert "validation_years_2024" in splits
    assert "test_years_2025" in splits

    assert splits["validation_years_2024"]["status"] == "complete_auditable_benchmark_v0"
    assert splits["test_years_2025"]["events_detected"] == []


def test_validate_benchmark_dataframe_negative_mutations():
    """Verify validate_benchmark_dataframe catches corrupted timestamps, NaNs, duplicates, and contradictions."""
    base_dir = Path(__file__).resolve().parents[1]
    res = build_and_export_p3_benchmark(data_dir=base_dir / "data", config_dir=base_dir / "configs")
    df_valid = res["df_benchmark"]

    # 1. NaN in temperature
    df_bad = df_valid.copy()
    df_bad.loc[0, "temperature_c"] = float("nan")
    with pytest.raises(ValueError, match="missing temperature observation"):
        validate_benchmark_dataframe(df_bad)

    # 2. NaN in price
    df_bad = df_valid.copy()
    df_bad.loc[5, "price_usd_per_mwh"] = float("nan")
    with pytest.raises(ValueError, match="missing price observation"):
        validate_benchmark_dataframe(df_bad)

    # 3. NaN in carbon intensity
    df_bad = df_valid.copy()
    df_bad.loc[10, "carbon_g_per_kwh"] = float("nan")
    with pytest.raises(ValueError, match="missing carbon_intensity observation"):
        validate_benchmark_dataframe(df_bad)

    # 4. Duplicate timestamp
    df_bad = df_valid.copy()
    df_bad.loc[1, "timestamp_utc"] = df_bad.loc[0, "timestamp_utc"]
    with pytest.raises(ValueError, match="duplicate timestamps"):
        validate_benchmark_dataframe(df_bad)

    # 5. Non-UTC timezone (e.g. America/New_York)
    df_bad = df_valid.copy()
    ts_list = df_bad["timestamp_utc"].tolist()
    from zoneinfo import ZoneInfo
    ts_list[0] = ts_list[0].astimezone(ZoneInfo("America/New_York"))
    df_bad["timestamp_utc"] = ts_list
    with pytest.raises(ValueError, match="UTC offset"):
        validate_benchmark_dataframe(df_bad)

    # 6. Logical contradiction: carbon_data_issue=True but carbon_primary_analysis_eligible=True
    df_bad = df_valid.copy()
    df_bad.loc[0, "carbon_data_issue"] = True
    df_bad.loc[0, "carbon_primary_analysis_eligible"] = True
    with pytest.raises(ValueError, match="logical contradiction"):
        validate_benchmark_dataframe(df_bad)

    # 7. Inconsistent local date / timestamp
    df_bad = df_valid.copy()
    df_bad.loc[0, "local_date"] = "1999-01-01"
    with pytest.raises(ValueError, match="local_date"):
        validate_benchmark_dataframe(df_bad)

    # 8. Wrong source node
    df_bad = df_valid.copy()
    df_bad.loc[0, "source_caiso_node"] = "WRONG_NODE"
    with pytest.raises(ValueError, match="unexpected source_caiso_node"):
        validate_benchmark_dataframe(df_bad, expected_caiso_node="TH_NP15_GEN-APND")

    # 9. Invalid event phase
    df_bad = df_valid.copy()
    df_bad.loc[df_bad["window_type"] == "event", "phase_label"] = "nonsense"
    with pytest.raises(ValueError, match="invalid phase_label"):
        validate_benchmark_dataframe(df_bad)

    # 10. Control row using event phase
    df_bad = df_valid.copy()
    df_bad.loc[df_bad["window_type"] == "control", "phase_label"] = "onset"
    with pytest.raises(ValueError, match="invalid phase_label"):
        validate_benchmark_dataframe(df_bad)

    # 11. Wrong event ID
    df_bad = df_valid.copy()
    df_bad.loc[df_bad["window_type"] == "event", "window_id"] = "HW_99999999"
    with pytest.raises(ValueError, match="window_id"):
        validate_benchmark_dataframe(df_bad, expected_event_id="HW_20240702")

    # 12. Wrong control ID
    df_bad = df_valid.copy()
    df_bad.loc[df_bad["window_type"] == "control", "window_id"] = "CTRL_99999999"
    with pytest.raises(ValueError, match="window_id"):
        validate_benchmark_dataframe(df_bad, expected_control_id="CTRL_20240605")

    # 13. Zero temperature observation count
    df_bad = df_valid.copy()
    df_bad.loc[0, "temperature_obs_count"] = 0
    with pytest.raises(ValueError, match="temperature_obs_count must be a positive integer"):
        validate_benchmark_dataframe(df_bad)

    # 14. Negative observation count
    df_bad = df_valid.copy()
    df_bad.loc[0, "temperature_obs_count"] = -1
    with pytest.raises(ValueError, match="temperature_obs_count must be a positive integer"):
        validate_benchmark_dataframe(df_bad)

    # 15. Inconsistent source quality
    df_bad = df_valid.copy()
    df_bad.loc[0, "source_quality"] = "missing"
    with pytest.raises(ValueError, match="invalid source_quality"):
        validate_benchmark_dataframe(df_bad)

    # 16. Missingness flag contradiction (missing=True on covered benchmark row)
    df_bad = df_valid.copy()
    df_bad.loc[0, "temperature_missing"] = True
    with pytest.raises(ValueError, match="temperature_missing must be False"):
        validate_benchmark_dataframe(df_bad)

    # 17. NaN demand
    df_bad = df_valid.copy()
    df_bad.loc[0, "demand_mw"] = float("nan")
    with pytest.raises(ValueError, match="missing demand observation"):
        validate_benchmark_dataframe(df_bad)

    # 18. NaN net generation
    df_bad = df_valid.copy()
    df_bad.loc[0, "net_generation_mw"] = float("nan")
    with pytest.raises(ValueError, match="missing net_generation observation"):
        validate_benchmark_dataframe(df_bad)

    # 19. Invalid station
    df_bad = df_valid.copy()
    df_bad.loc[0, "source_station_id"] = "WRONG_STATION"
    with pytest.raises(ValueError, match="unexpected source_station_id"):
        validate_benchmark_dataframe(df_bad, expected_station_id="USW00023234")

    # 20. Invalid balancing authority
    df_bad = df_valid.copy()
    df_bad.loc[0, "source_balancing_authority"] = "WRONG_BA"
    with pytest.raises(ValueError, match="unexpected source_balancing_authority"):
        validate_benchmark_dataframe(df_bad, expected_balancing_authority="CISO")

    # 21. Missing hour in sequence
    df_bad = df_valid.drop(index=10).reset_index(drop=True)
    with pytest.raises(ValueError, match="(Benchmark row count|non-continuous step)"):
        validate_benchmark_dataframe(df_bad)


def test_audit_workload_canonical_validation_negative_cases(tmp_path):
    """Verify run_p3_audit rejects workloads with negative energy, duplicate IDs, invalid dead, seed, or missing cols."""
    base_dir = Path(__file__).resolve().parents[1]
    import shutil

    # Prepare complete temporary environment with real data
    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)

    wl_path = t_data / "workloads/workload_trace_v0.parquet"
    df_wl_valid = pd.read_parquet(wl_path)

    # Case 1: negative energy_kwh
    df_wl_bad = df_wl_valid.copy()
    df_wl_bad.loc[0, "energy_kwh"] = -999.0
    df_wl_bad.to_parquet(wl_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("energy_kwh" in r for r in res["failure_reasons"])

    # Case 2: duplicate job_id
    df_wl_bad = df_wl_valid.copy()
    df_wl_bad.loc[1, "job_id"] = df_wl_bad.loc[0, "job_id"]
    df_wl_bad.to_parquet(wl_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("Duplicate job_id" in r for r in res["failure_reasons"])

    # Case 3: deadline before arrival
    df_wl_bad = df_wl_valid.copy()
    df_wl_bad.loc[0, "deadline_offset_hours"] = df_wl_bad.loc[0, "arrival_offset_hours"] - 1
    df_wl_bad.to_parquet(wl_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("deadline_offset_hours" in r for r in res["failure_reasons"])

    # Case 4: invalid seed
    df_wl_bad = df_wl_valid.copy()
    df_wl_bad.loc[0, "seed"] = 12345678
    df_wl_bad.to_parquet(wl_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("seed" in r for r in res["failure_reasons"])

    # Case 5: missing required column
    df_wl_bad = df_wl_valid.drop(columns=["priority"])
    df_wl_bad.to_parquet(wl_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("Workload columns mismatch" in r for r in res["failure_reasons"])


def test_clean_carbon_data_passes_audit_gate(tmp_path):
    """Verify that a clean synthetic benchmark with carbon_data_issue=0 and primary_eligible=240 passes the audit."""
    base_dir = Path(__file__).resolve().parents[1]
    import shutil

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    from heattrace.ingest.provenance import sha256_file
    import json

    b_path = t_data / "benchmarks/benchmark_2024_event_control_v0.parquet"
    df_clean = pd.read_parquet(b_path)
    df_clean["carbon_data_issue"] = False
    df_clean["carbon_primary_analysis_eligible"] = True
    df_clean["source_quality"] = "success"
    df_clean.to_parquet(b_path, index=False)

    # Update benchmark manifest hash and size to match clean mutation
    bm_path = t_data / "manifests/benchmark_manifest.json"
    bm_data = json.loads(bm_path.read_text(encoding="utf-8"))
    bm_data["output_files"]["benchmark_parquet"]["sha256"] = sha256_file(b_path)
    bm_data["output_files"]["benchmark_parquet"]["size_bytes"] = b_path.stat().st_size
    bm_path.write_text(json.dumps(bm_data, indent=2), encoding="utf-8")

    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "verified_pass"
    assert res["carbon_data_issue_audit"]["data_issue_flag_count"] == "0/240"
    assert res["carbon_data_issue_audit"]["primary_analysis_eligible_count"] == "240/240"


def test_audit_failure_on_missing_or_corrupt_data(tmp_path):
    """Verify run_p3_audit reports failure when required files are missing."""
    empty_data_dir = tmp_path / "data"
    empty_data_dir.mkdir()
    res = run_p3_audit(data_dir=empty_data_dir)
    assert res["status"] == "failed"
    assert len(res["failure_reasons"]) > 0


def test_audit_fails_on_provenance_manifest_mismatch(tmp_path):
    """Verify run_p3_audit fails when benchmark data is mutated without manifest update."""
    base_dir = Path(__file__).resolve().parents[1]
    import shutil

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    b_path = t_data / "benchmarks/benchmark_2024_event_control_v0.parquet"
    df_tampered = pd.read_parquet(b_path)
    # Alter one finite price value without updating benchmark_manifest.json
    df_tampered.loc[0, "price_usd_per_mwh"] = 999.99
    df_tampered.to_parquet(b_path, index=False)

    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("hash mismatch" in r and "benchmark_2024_event_control_v0.parquet" in r for r in res["failure_reasons"])


def test_audit_provenance_manifest_verification_edge_cases(tmp_path):
    """Verify manifest verification catches missing, malformed, incorrect size, absolute, and escaping paths."""
    from heattrace.process.audit import verify_provenance_manifest_entries

    from heattrace.ingest.provenance import sha256_file
    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("hello world\n", encoding="utf-8")
    real_sha = sha256_file(dummy_file)

    # Valid manifest
    manifest_valid = {
        "output_files": {
            "dummy": {
                "path": "dummy.txt",
                "sha256": real_sha,
                "size_bytes": dummy_file.stat().st_size,
            }
        }
    }
    assert verify_provenance_manifest_entries(manifest_valid, manifest_name="test", repo_root=tmp_path) == []

    # 1. Missing referenced file
    m_bad = {"f": {"path": "nonexistent.txt", "sha256": real_sha}}
    errs = verify_provenance_manifest_entries(m_bad, manifest_name="test", repo_root=tmp_path)
    assert any("does not exist" in e for e in errs)

    # 2. Incorrect recorded hash
    m_bad = {"f": {"path": "dummy.txt", "sha256": "0" * 64}}
    errs = verify_provenance_manifest_entries(m_bad, manifest_name="test", repo_root=tmp_path)
    assert any("hash mismatch" in e for e in errs)

    # 3. Incorrect size
    m_bad = {"f": {"path": "dummy.txt", "sha256": real_sha, "size_bytes": 999999}}
    errs = verify_provenance_manifest_entries(m_bad, manifest_name="test", repo_root=tmp_path)
    assert any("size mismatch" in e for e in errs)

    # 4. Absolute path
    m_bad = {"f": {"path": str(dummy_file.resolve()), "sha256": real_sha}}
    errs = verify_provenance_manifest_entries(m_bad, manifest_name="test", repo_root=tmp_path)
    assert any("absolute path not permitted" in e for e in errs)

    # 5. Escaping path ../
    m_bad = {"f": {"path": "../other.txt", "sha256": real_sha}}
    errs = verify_provenance_manifest_entries(m_bad, manifest_name="test", repo_root=tmp_path)
    assert any("path escape '../' not permitted" in e for e in errs)


def test_audit_fails_on_pending_or_duplicated_control(tmp_path):
    """Verify run_p3_audit fails on weather_eligible_pending status, duplicate controls, or missing required config."""
    base_dir = Path(__file__).resolve().parents[1]
    import shutil

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    c_path = t_data / "events/control_catalogue_v0.parquet"
    df_ctrl_valid = pd.read_parquet(c_path)

    # 1. Pending status: weather_eligible_pending_cross_source_validation
    df_pending = df_ctrl_valid.copy()
    df_pending["source_coverage_status"] = "weather_eligible_pending_cross_source_validation"
    df_pending.to_parquet(c_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("verified_complete" in r for r in res["failure_reasons"])

    # 2. Duplicated control record
    df_dup = pd.concat([df_ctrl_valid, df_ctrl_valid], ignore_index=True)
    df_dup.to_parquet(c_path, index=False)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("Duplicate" in r or "exactly 1 approved record" in r for r in res["failure_reasons"])

    # 3. Missing required price.node configuration
    df_ctrl_valid.to_parquet(c_path, index=False)
    # Remove price.node from configs/sources.yaml
    src_yaml = (t_cfg / "sources.yaml").read_text(encoding="utf-8")
    import re
    src_yaml_no_node = re.sub(r"node:\s*TH_NP15_GEN-APND", "", src_yaml)
    (t_cfg / "sources.yaml").write_text(src_yaml_no_node, encoding="utf-8")
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("price.node" in r for r in res["failure_reasons"])


def test_audit_fails_on_manifest_deletion_and_schema_tampering(tmp_path):
    """Verify that removing required entries from manifests or tampering with schemas fails audit."""
    import shutil
    base_dir = Path(__file__).resolve().parents[1]

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    bm_path = t_data / "manifests/benchmark_manifest.json"
    ctrl_m_path = t_data / "manifests/control_matching_audit.json"
    ev_m_path = t_data / "manifests/event_catalogue_manifest.json"
    wl_m_path = t_data / "workloads/workload_manifest.json"

    # 1. Exact bypass test: tamper benchmark price, delete output_files.benchmark_parquet entry, audit must fail
    b_parquet = t_data / "benchmarks/benchmark_2024_event_control_v0.parquet"
    df_tampered = pd.read_parquet(b_parquet)
    df_tampered.loc[0, "price_usd_per_mwh"] = 999.99
    df_tampered.to_parquet(b_parquet, index=False)

    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["output_files"]["benchmark_parquet"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)

    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("benchmark_manifest.json missing required entry output_files.benchmark_parquet" in r for r in res["failure_reasons"])

    # Restore price and manifest
    df_orig = pd.read_parquet(base_dir / "data/benchmarks/benchmark_2024_event_control_v0.parquet")
    df_orig.to_parquet(b_parquet, index=False)
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 2. benchmark_sample_csv removed
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["output_files"]["benchmark_sample_csv"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("benchmark_manifest.json missing required entry output_files.benchmark_sample_csv" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 3. Control catalogue entry removed from benchmark inputs
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["input_files"]["catalogues_and_workloads"]["control_catalogue_v0.parquet"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("input_files.catalogues_and_workloads.control_catalogue_v0.parquet" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 4. Workload trace entry removed from benchmark inputs
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["input_files"]["catalogues_and_workloads"]["workload_trace_v0.parquet"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("input_files.catalogues_and_workloads.workload_trace_v0.parquet" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 5. sources.yaml entry removed from benchmark inputs
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["input_files"]["configuration"]["sources.yaml"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("input_files.configuration.sources.yaml" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 6. Raw source entry removed from benchmark inputs
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["input_files"]["raw_sources"]["GHCNh_USW00023234_2024.psv"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("input_files.raw_sources.GHCNh_USW00023234_2024.psv" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 7. Control output Parquet entry removed from control_matching_audit.json
    with ctrl_m_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    del cm_data["output_files"]["control_catalogue_parquet"]
    with ctrl_m_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("output_files.control_catalogue_parquet" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_m_path)

    # 8. Workload manifest output entry removed
    with wl_m_path.open("r", encoding="utf-8") as f:
        wm_data = json.load(f)
    del wm_data["output_files"]["workload_trace_parquet"]
    with wl_m_path.open("w", encoding="utf-8") as f:
        json.dump(wm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("output_files.workload_trace_parquet" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/workloads/workload_manifest.json", wl_m_path)

    # 9. Event manifest output entry removed
    with ev_m_path.open("r", encoding="utf-8") as f:
        em_data = json.load(f)
    del em_data["output_files"]["heatwave_events_parquet"]
    with ev_m_path.open("w", encoding="utf-8") as f:
        json.dump(em_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("output_files.heatwave_events_parquet" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/event_catalogue_manifest.json", ev_m_path)

    # 10. Entire required manifest replaced with {}
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump({}, f)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("manifest must be a non-empty JSON object" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 11. Required hash field removed
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["output_files"]["benchmark_parquet"]["sha256"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("missing required field 'sha256'" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 12. Required size_bytes removed
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    del bm_data["output_files"]["benchmark_parquet"]["size_bytes"]
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("missing required field 'size_bytes'" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)

    # 13. SHA contains non-hex characters
    with bm_path.open("r", encoding="utf-8") as f:
        bm_data = json.load(f)
    bm_data["output_files"]["benchmark_parquet"]["sha256"] = "z" * 64
    with bm_path.open("w", encoding="utf-8") as f:
        json.dump(bm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("malformed SHA-256 hash" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/benchmark_manifest.json", bm_path)


def test_benchmark_construction_fails_on_corrupt_or_missing_control_audit(tmp_path):
    """Verify build_and_export_p3_benchmark fails strictly on control_matching_audit errors."""
    import shutil
    base_dir = Path(__file__).resolve().parents[1]

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    ctrl_audit_path = t_data / "manifests/control_matching_audit.json"

    # 1. Missing control_matching_audit.json
    ctrl_audit_path.unlink()
    with pytest.raises(FileNotFoundError, match="Required provenance manifest .* not found"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)

    # 2. Malformed JSON
    ctrl_audit_path.write_text("{this is not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed JSON"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)

    # 3. Non-object JSON
    ctrl_audit_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(TypeError, match="must parse as a JSON object"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)

    # 4. Missing output_files
    with ctrl_audit_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    del cm_data["output_files"]
    with ctrl_audit_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    with pytest.raises(ValueError, match="missing required 'output_files'"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)

    # 5. Missing expected Parquet entry
    with ctrl_audit_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    del cm_data["output_files"]["control_catalogue_parquet"]
    with ctrl_audit_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    with pytest.raises(ValueError, match="missing required output entry 'control_catalogue_parquet'"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)

    # 6. Wrong selected control ID
    with ctrl_audit_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    cm_data["selected_control_id"] = "CTRL_WRONG"
    with ctrl_audit_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    with pytest.raises(ValueError, match="selected_control_id .* does not match"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)

    # 7. Wrong matched event ID
    with ctrl_audit_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    cm_data["matched_event_id"] = "HW_WRONG"
    with ctrl_audit_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    with pytest.raises(ValueError, match="matched_event_id .* does not match"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_audit_path)


def test_unmatched_event_reasons_are_evidence_derived(tmp_path):
    """Verify unmatched event reasons derive from actual file / manifest evidence without false-pass patterns."""
    import shutil
    from heattrace.process.audit import verify_caiso_interval_source_evidence
    from heattrace.ingest.provenance import sha256_file
    base_dir = Path(__file__).resolve().parents[1]

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    ev_start_utc = pd.to_datetime("2022-06-19 07:00:00+00:00")
    ev_end_utc = pd.to_datetime("2022-06-24 07:00:00+00:00")
    caiso_node = "TH_NP15_GEN-APND"

    # A. Direct tests on verify_caiso_interval_source_evidence:
    # 1. Incomplete CAISO manifest record remains not_verified or missing
    dummy_rec_incomplete = {
        "provider": "CAISO",
        "request": {
            "node": caiso_node,
            "startdatetime": "2022-06-19T07:00:00+00:00",
            # missing enddatetime
        }
    }
    res_inc = verify_caiso_interval_source_evidence(
        data_dir=t_data,
        caiso_node=caiso_node,
        ev_start_utc=ev_start_utc,
        ev_end_utc=ev_end_utc,
        manifest_records=[dummy_rec_incomplete],
    )
    assert res_inc["status"] == "missing"
    assert res_inc["manifest_record_found"] is False
    assert res_inc["file_verified"] is False
    assert res_inc["parsed_interval_coverage_verified"] is False

    # 2. Valid record without a file fails verification
    dummy_rec_nofile = {
        "provider": "CAISO",
        "path": "data/raw/caiso/nonexistent_2022.zip",
        "sha256": "0" * 64,
        "size_bytes": 1000,
        "request": {
            "node": caiso_node,
            "startdatetime": "2022-06-19T07:00:00+00:00",
            "enddatetime": "2022-06-24T07:00:00+00:00",
        }
    }
    res_nofile = verify_caiso_interval_source_evidence(
        data_dir=t_data,
        caiso_node=caiso_node,
        ev_start_utc=ev_start_utc,
        ev_end_utc=ev_end_utc,
        manifest_records=[dummy_rec_nofile],
    )
    assert res_nofile["status"] == "missing"
    assert res_nofile["manifest_record_found"] is True
    assert res_nofile["file_verified"] is False

    # 3. File with bad hash fails verification
    real_zip = t_data / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240701_20240706.zip"
    dummy_rec_badhash = {
        "provider": "CAISO",
        "path": "data/raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240701_20240706.zip",
        "sha256": "f" * 64,
        "size_bytes": real_zip.stat().st_size,
        "request": {
            "node": caiso_node,
            "startdatetime": "2022-06-19T07:00:00+00:00",
            "enddatetime": "2022-06-24T07:00:00+00:00",
        }
    }
    res_badhash = verify_caiso_interval_source_evidence(
        data_dir=t_data,
        caiso_node=caiso_node,
        ev_start_utc=ev_start_utc,
        ev_end_utc=ev_end_utc,
        manifest_records=[dummy_rec_badhash],
    )
    assert res_badhash["status"] == "missing"
    assert res_badhash["manifest_record_found"] is True
    assert res_badhash["file_verified"] is False

    # 4. Partial interval coverage fails verification (e.g. 24h zip claiming 120h window)
    partial_zip = t_data / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240702_20240703.zip"
    dummy_rec_partial = {
        "provider": "CAISO",
        "path": "data/raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240702_20240703.zip",
        "sha256": sha256_file(partial_zip),
        "size_bytes": partial_zip.stat().st_size,
        "request": {
            "node": caiso_node,
            "startdatetime": "2024-07-01T07:00:00+00:00",
            "enddatetime": "2024-07-06T07:00:00+00:00",
        }
    }
    res_partial = verify_caiso_interval_source_evidence(
        data_dir=t_data,
        caiso_node=caiso_node,
        ev_start_utc=pd.to_datetime("2024-07-01 07:00:00+00:00"),
        ev_end_utc=pd.to_datetime("2024-07-06 07:00:00+00:00"),
        manifest_records=[dummy_rec_partial],
    )
    assert res_partial["status"] == "missing"
    assert res_partial["manifest_record_found"] is True
    assert res_partial["file_verified"] is True
    assert res_partial["parsed_interval_coverage_verified"] is False
    assert any("Missing" in d for d in res_partial["details"])

    # 5. Complete, verified, parsed interval coverage becomes available
    full_zip = t_data / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240701_20240706.zip"
    dummy_rec_full = {
        "provider": "CAISO",
        "path": "data/raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240701_20240706.zip",
        "sha256": sha256_file(full_zip),
        "size_bytes": full_zip.stat().st_size,
        "request": {
            "node": caiso_node,
            "startdatetime": "2024-07-01T07:00:00+00:00",
            "enddatetime": "2024-07-06T07:00:00+00:00",
        }
    }
    res_full = verify_caiso_interval_source_evidence(
        data_dir=t_data,
        caiso_node=caiso_node,
        ev_start_utc=pd.to_datetime("2024-07-01 07:00:00+00:00"),
        ev_end_utc=pd.to_datetime("2024-07-06 07:00:00+00:00"),
        manifest_records=[dummy_rec_full],
    )
    assert res_full["status"] == "available"
    assert res_full["manifest_record_found"] is True
    assert res_full["file_verified"] is True
    assert res_full["parsed_interval_coverage_verified"] is True

    # B. Integrated audit test:
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "verified_pass"
    unmatched_cases = {c["event_id"]: c for c in res["unmatched_cases_evidence"]}
    assert "HW_20220620" in unmatched_cases
    hw_2022 = unmatched_cases["HW_20220620"]
    assert hw_2022["source_evidence"]["weather"]["status"] == "available"
    assert hw_2022["source_evidence"]["caiso_price"]["status"] == "missing"
    assert hw_2022["source_evidence"]["caiso_price"]["parsed_interval_coverage_verified"] is False
    assert "caiso_price" in hw_2022["missing_or_incomplete_sources"]


def test_audit_fails_on_semantic_manifest_schema_violations(tmp_path):
    """Verify audit fails on semantic metadata and input omissions across all manifests."""
    import shutil
    base_dir = Path(__file__).resolve().parents[1]

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    ev_m_path = t_data / "manifests/event_catalogue_manifest.json"
    ctrl_m_path = t_data / "manifests/control_matching_audit.json"
    wl_m_path = t_data / "workloads/workload_manifest.json"

    # 1. NOAA input entry deleted from event manifest
    with ev_m_path.open("r", encoding="utf-8") as f:
        em_data = json.load(f)
    del em_data["input_files"]["GHCNh_USW00023234_2022.psv"]
    with ev_m_path.open("w", encoding="utf-8") as f:
        json.dump(em_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("event_catalogue_manifest.json missing required input file input_files.GHCNh_USW00023234_2022.psv" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/event_catalogue_manifest.json", ev_m_path)

    # 2. NOAA input entry deleted from control manifest
    with ctrl_m_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    del cm_data["input_files"]["GHCNh_USW00023234_2023.psv"]
    with ctrl_m_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("control_matching_audit.json missing required input file input_files.GHCNh_USW00023234_2023.psv" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_m_path)

    # 3. Control/event IDs replaced with fake values in control manifest
    with ctrl_m_path.open("r", encoding="utf-8") as f:
        cm_data = json.load(f)
    cm_data["selected_control_id"] = "CTRL_FAKE"
    with ctrl_m_path.open("w", encoding="utf-8") as f:
        json.dump(cm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("selected_control_id must be 'CTRL_20240605'" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/control_matching_audit.json", ctrl_m_path)

    # 4. Event IDs disagree with event catalogue in event manifest
    with ev_m_path.open("r", encoding="utf-8") as f:
        em_data = json.load(f)
    em_data["event_ids"] = ["HW_FAKE"]
    with ev_m_path.open("w", encoding="utf-8") as f:
        json.dump(em_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("event_ids" in r and "HW_FAKE" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/manifests/event_catalogue_manifest.json", ev_m_path)

    # 5. Workload seed disagrees with configuration
    with wl_m_path.open("r", encoding="utf-8") as f:
        wm_data = json.load(f)
    wm_data["random_seed"] = 99999999
    with wl_m_path.open("w", encoding="utf-8") as f:
        json.dump(wm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("random_seed" in r and "99999999" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/workloads/workload_manifest.json", wl_m_path)

    # 6. Workload duration disagrees with workload trace
    with wl_m_path.open("r", encoding="utf-8") as f:
        wm_data = json.load(f)
    wm_data["window_duration_hours"] = 72
    with wl_m_path.open("w", encoding="utf-8") as f:
        json.dump(wm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("window_duration_hours" in r and "72" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/workloads/workload_manifest.json", wl_m_path)

    # 7. Workload job count disagrees with workload trace
    with wl_m_path.open("r", encoding="utf-8") as f:
        wm_data = json.load(f)
    wm_data["job_count"] = 999
    with wl_m_path.open("w", encoding="utf-8") as f:
        json.dump(wm_data, f, indent=2)
    res = run_p3_audit(data_dir=t_data, config_dir=t_cfg)
    assert res["status"] == "failed"
    assert any("job_count" in r and "999" in r for r in res["failure_reasons"])
    shutil.copyfile(base_dir / "data/workloads/workload_manifest.json", wl_m_path)


def test_benchmark_publication_atomic_rollback_on_failure(tmp_path, monkeypatch):
    """Verify that simulated failure during publication triggers clean rollback with original files intact."""
    import shutil
    from heattrace.ingest.provenance import sha256_file
    base_dir = Path(__file__).resolve().parents[1]

    t_data = tmp_path / "data"
    t_cfg = tmp_path / "configs"
    t_data.mkdir()
    t_cfg.mkdir()

    shutil.copytree(base_dir / "configs", t_cfg, dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/events", t_data / "events", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/benchmarks", t_data / "benchmarks", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/workloads", t_data / "workloads", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/manifests", t_data / "manifests", dirs_exist_ok=True)
    shutil.copytree(base_dir / "data/raw", t_data / "raw", dirs_exist_ok=True)

    b_parquet = t_data / "benchmarks/benchmark_2024_event_control_v0.parquet"
    c_audit = t_data / "manifests/control_matching_audit.json"
    orig_b_sha = sha256_file(b_parquet)
    orig_c_sha = sha256_file(c_audit)

    # Mock Path.replace so that it fails midway on benchmark_manifest.json
    orig_replace = Path.replace
    def failing_replace(self, target):
        if "benchmark_manifest.json" in str(target):
            raise IOError("Simulated disk error during benchmark_manifest.json publication")
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(IOError, match="Simulated disk error"):
        build_and_export_p3_benchmark(data_dir=t_data, config_dir=t_cfg)

    # Verify rollback: destination files exist and hashes are completely preserved
    assert sha256_file(b_parquet) == orig_b_sha
    assert sha256_file(c_audit) == orig_c_sha
    # Verify no temporary directories left behind
    assert not list(t_data.glob("p3_pub_stage_*"))
    assert not list(t_data.glob("p3_pub_bak_*"))
