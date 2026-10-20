"""Tests for HeatTrace P3-05 Control Matching, P3-06 Audit, and G3-a Benchmark."""

from __future__ import annotations

from datetime import datetime, timezone
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
    assert "validation_year_2024" in splits
    assert "test_year_2025" in splits

    assert splits["validation_year_2024"]["status"] == "complete_auditable_benchmark_v0"
    assert splits["test_year_2025"]["events_detected"] == []


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
        validate_benchmark_dataframe(df_bad)


def test_audit_failure_on_missing_or_corrupt_data(tmp_path):
    """Verify run_p3_audit reports failure when required files are missing."""
    empty_data_dir = tmp_path / "data"
    empty_data_dir.mkdir()
    res = run_p3_audit(data_dir=empty_data_dir)
    assert res["status"] == "failed"
    assert len(res["failure_reasons"]) > 0
