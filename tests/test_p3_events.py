"""Tests for HeatTrace Phase P3: Heatwave event detection, phase labeling, contracts, and validation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import re
import pytest
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.noaa import extract_daily_maxima, get_local_day_utc_bounds
from heattrace.process.events import (
    build_and_export_events,
    build_hourly_phase_labels,
    compute_heatwave_percentile_threshold,
    detect_heatwave_events,
    load_heatwave_config,
    write_event_coverage_csv,
    write_event_manifest_json,
)
from heattrace.process.event_validation import (
    EVENT_CATALOGUE_COLUMNS,
    HOURLY_EVENT_LABEL_COLUMNS,
    VALID_EVENT_PHASES,
    validate_heatwave_events,
    validate_hourly_event_labels,
)
from heattrace.process.quality import CANONICAL_COLUMNS


def _make_daily_record(
    local_date: str,
    temp_c: float | None,
    station_id: str = "USW00023234",
    tz: str = "America/Los_Angeles",
) -> dict[str, any]:
    """Helper to mock a daily maximum record."""
    return {
        "local_date": local_date,
        "daily_max_temperature_c": temp_c,
        "station_id": station_id,
        "timezone": tz,
        "quality_status": "valid" if temp_c is not None else "missing",
        "valid_observation_count": 24 if temp_c is not None else 0,
        "duplicate_observation_count": 0,
        "conflict_observation_count": 0,
        "timestamps_utc": [],
    }


def _make_mock_event(
    event_id: str = "HW_20240701",
    local_start_date: str = "2024-07-01",
    local_end_date: str = "2024-07-03",
    duration_days: int = 3,
    station_id: str = "USW00023234",
    tz_str: str = "America/Los_Angeles",
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    peak_date: str = "2024-07-02",
    peak_temp: float = 31.0,
    threshold_c: float = 25.6,
    percentile: float = 90.0,
    percentile_method: str = "linear_interpolation",
) -> dict[str, Any]:
    tz = ZoneInfo(tz_str)
    d_start = date.fromisoformat(local_start_date)
    d_end = date.fromisoformat(local_end_date)
    if start_utc is None:
        start_utc = datetime(d_start.year, d_start.month, d_start.day, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    if end_utc is None:
        next_d = d_end + timedelta(days=1)
        end_utc = datetime(next_d.year, next_d.month, next_d.day, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    dur_hours = int(round((end_utc - start_utc).total_seconds() / 3600.0))

    return {
        "event_id": event_id,
        "station_id": station_id,
        "timezone": tz_str,
        "threshold_percentile": percentile,
        "threshold_temperature_c": threshold_c,
        "percentile_method": percentile_method,
        "local_start_date": local_start_date,
        "local_end_date": local_end_date,
        "event_start_utc": start_utc,
        "event_end_utc": end_utc,
        "qualifying_day_count": duration_days,
        "duration_days": duration_days,
        "duration_hours": dur_hours,
        "peak_local_date": peak_date,
        "peak_temperature_c": peak_temp,
        "mean_max_temperature_c": 30.0,
        "cumulative_exceedance_c_days": 13.0,
        "missing_days_inside_event": 0,
        "valid_observation_count": 72,
        "duplicate_observation_count": 0,
        "conflict_observation_count": 0,
        "source_quality": "verified",
        "source_file_references": "NOAA GHCNh USW00023234",
    }


# =========================================================================
# Unit Tests for Heatwave Detection & Consecuteness Rules
# =========================================================================

def test_p3_detection_exactly_three_consecutive_days_creates_one_event():
    """Requirement: Exactly 3 consecutive qualifying days creates exactly 1 heatwave event."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2024-07-01", 24.0),
        _make_daily_record("2024-07-02", 26.0),
        _make_daily_record("2024-07-03", 27.0),
        _make_daily_record("2024-07-04", 28.0),
        _make_daily_record("2024-07-05", 24.5),
    ]
    df_events, runs = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 1
    assert len(runs) == 1
    row = df_events.iloc[0]
    assert row["event_id"] == "HW_20240702"
    assert row["local_start_date"] == "2024-07-02"
    assert row["local_end_date"] == "2024-07-04"
    assert row["duration_days"] == 3
    assert row["duration_hours"] == 72
    assert row["peak_local_date"] == "2024-07-04"
    assert row["peak_temperature_c"] == 28.0


def test_p3_detection_two_consecutive_days_fails_to_create_event():
    """Requirement: A 2-day exceedance does not qualify as an event."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2024-07-01", 26.0),
        _make_daily_record("2024-07-02", 27.0),
        _make_daily_record("2024-07-03", 24.0),
    ]
    df_events, runs = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 0
    assert len(runs) == 0


def test_p3_detection_missing_day_breaks_consecuteness():
    """Requirement: Missing day breaks consecuteness and cannot bridge events."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2024-07-01", 26.0),
        _make_daily_record("2024-07-02", 27.0),
        # 2024-07-03 missing from series
        _make_daily_record("2024-07-04", 28.0),
        _make_daily_record("2024-07-05", 29.0),
    ]
    df_events, runs = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 0
    assert len(runs) == 0


def test_p3_detection_non_qualifying_day_breaks_consecuteness():
    """Requirement: Non-qualifying day breaks consecuteness and creates separate events if runs >= 3."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2024-07-01", 26.0),
        _make_daily_record("2024-07-02", 27.0),
        _make_daily_record("2024-07-03", 28.0),
        _make_daily_record("2024-07-04", 24.0),  # Break
        _make_daily_record("2024-07-05", 26.5),
        _make_daily_record("2024-07-06", 27.5),
        _make_daily_record("2024-07-07", 28.5),
    ]
    df_events, runs = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 2
    assert df_events.iloc[0]["event_id"] == "HW_20240701"
    assert df_events.iloc[1]["event_id"] == "HW_20240705"


def test_p3_detection_longer_maximal_run_produces_single_event():
    """Requirement: Longer runs (e.g., 5 days) produce a single multi-day event with correct duration."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2022-09-04", 30.0),
        _make_daily_record("2022-09-05", 35.6),
        _make_daily_record("2022-09-06", 34.0),
        _make_daily_record("2022-09-07", 33.0),
        _make_daily_record("2022-09-08", 31.0),
    ]
    df_events, _ = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 1
    ev = df_events.iloc[0]
    assert ev["event_id"] == "HW_20220904"
    assert ev["duration_days"] == 5
    assert ev["duration_hours"] == 120
    assert ev["peak_local_date"] == "2022-09-05"
    assert ev["peak_temperature_c"] == 35.6


def test_p3_detection_strict_exceedance_boundary():
    """Requirement: Temperature exactly equal to P90 does NOT qualify (strictly greater than)."""
    threshold = 25.6
    daily_records = [
        _make_daily_record("2024-07-01", 25.6),
        _make_daily_record("2024-07-02", 25.60001),
        _make_daily_record("2024-07-03", 26.0),
        _make_daily_record("2024-07-04", 25.6),
    ]
    df_events, _ = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 0


def test_p3_detection_peak_tie_breaking():
    """Requirement: Tied daily maxima within an event resolve to the earliest date."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2024-07-01", 30.0),
        _make_daily_record("2024-07-02", 28.0),
        _make_daily_record("2024-07-03", 30.0),
        _make_daily_record("2024-07-04", 27.0),
    ]
    df_events, _ = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    assert len(df_events) == 1
    assert df_events.iloc[0]["peak_local_date"] == "2024-07-01"
    assert df_events.iloc[0]["peak_temperature_c"] == 30.0


# =========================================================================
# Phase Labeling & Interval Tests
# =========================================================================

def test_p3_phase_labeling_durations_and_coverage():
    """Requirement: For a 3-day event, onset=24h, peak=24h, sustained=48h, recovery=24h (total 120h)."""
    threshold = 25.0
    daily_records = [
        _make_daily_record("2024-07-01", 24.0),
        _make_daily_record("2024-07-02", 30.0),  # peak
        _make_daily_record("2024-07-03", 28.0),
        _make_daily_record("2024-07-04", 27.0),
        _make_daily_record("2024-07-05", 23.0),
    ]
    df_events, _ = detect_heatwave_events(daily_records, threshold_p90_c=threshold)
    daily_by_date = {d["local_date"]: d for d in daily_records}
    df_labels = build_hourly_phase_labels(df_events, daily_records_by_date=daily_by_date, threshold_p90_c=threshold)

    assert len(df_labels) == 120
    assert set(df_labels["event_phase"]) == {"onset", "peak", "sustained", "recovery"}

    counts = df_labels["event_phase"].value_counts().to_dict()
    assert counts["onset"] == 24
    assert counts["peak"] == 24
    assert counts["sustained"] == 48
    assert counts["recovery"] == 24

    onset_dates = df_labels[df_labels["event_phase"] == "onset"]["local_date"].unique()
    assert list(onset_dates) == ["2024-07-01"]

    recovery_dates = df_labels[df_labels["event_phase"] == "recovery"]["local_date"].unique()
    assert list(recovery_dates) == ["2024-07-05"]


def test_p3_dst_duration_conversion():
    """Requirement: Local day to UTC bounds handles 23-hour and 25-hour DST transitions accurately."""
    start_utc, end_utc, hours = get_local_day_utc_bounds("2024-03-10", "America/Los_Angeles")
    assert hours == 23.0
    assert (end_utc - start_utc).total_seconds() == 23 * 3600

    start_utc, end_utc, hours = get_local_day_utc_bounds("2024-11-03", "America/Los_Angeles")
    assert hours == 25.0
    assert (end_utc - start_utc).total_seconds() == 25 * 3600

    start_utc, end_utc, hours = get_local_day_utc_bounds("2024-07-02", "America/Los_Angeles")
    assert hours == 24.0
    assert (end_utc - start_utc).total_seconds() == 24 * 3600


def test_p3_phase_buffer_collision_detection():
    """Requirement: Fail explicitly if onset or recovery buffers collide between events."""
    ev1 = _make_mock_event("HW_20240701", "2024-07-01", "2024-07-03", duration_days=3)
    ev2 = _make_mock_event("HW_20240705", "2024-07-05", "2024-07-07", duration_days=3)
    df_colliding = pd.DataFrame([ev1, ev2], columns=EVENT_CATALOGUE_COLUMNS)
    with pytest.raises(ValueError, match="Phase buffer collision"):
        build_hourly_phase_labels(df_colliding)


# =========================================================================
# Validation Failure Paths
# =========================================================================

def test_p3_event_validation_detects_short_duration():
    """Event validator must reject events shorter than min_consecutive_days."""
    ev = _make_mock_event("HW_20240701", "2024-07-01", "2024-07-02", duration_days=2)
    df = pd.DataFrame([ev], columns=EVENT_CATALOGUE_COLUMNS)
    with pytest.raises(ValueError, match="duration_days 2 < min_consecutive_days"):
        validate_heatwave_events(df, min_consecutive_days=3)


def test_p3_event_validation_detects_duplicate_event_id():
    """Event validator must reject duplicate event_id."""
    ev = _make_mock_event("HW_20240701", "2024-07-01", "2024-07-03", duration_days=3)
    df = pd.DataFrame([ev, ev], columns=EVENT_CATALOGUE_COLUMNS)
    with pytest.raises(ValueError, match="Duplicate event_id values found"):
        validate_heatwave_events(df)


def test_p3_event_validation_detects_invalid_event_id_format():
    """Event validator must reject invalid event_id formats."""
    ev = _make_mock_event("HEATWAVE_1", "2024-07-01", "2024-07-03", duration_days=3)
    df = pd.DataFrame([ev], columns=EVENT_CATALOGUE_COLUMNS)
    with pytest.raises(ValueError, match="invalid event_id format"):
        validate_heatwave_events(df)


def test_p3_event_validation_detects_inconsistent_event_id_and_date():
    """Event validator must reject event_id date inconsistent with local_start_date."""
    ev = _make_mock_event("HW_20240705", "2024-07-01", "2024-07-03", duration_days=3)
    df = pd.DataFrame([ev], columns=EVENT_CATALOGUE_COLUMNS)
    with pytest.raises(ValueError, match="does not match local_start_date"):
        validate_heatwave_events(df)


def test_p3_event_validation_detects_non_utc_timezone():
    """Event validator must reject timezone-aware datetimes that are not UTC."""
    tz_la = ZoneInfo("America/Los_Angeles")
    start_la = datetime(2024, 7, 1, 0, 0, tzinfo=tz_la)
    end_la = datetime(2024, 7, 4, 0, 0, tzinfo=tz_la)
    ev = _make_mock_event("HW_20240701", "2024-07-01", "2024-07-03", duration_days=3, start_utc=start_la, end_utc=end_la)
    df = pd.DataFrame([ev], columns=EVENT_CATALOGUE_COLUMNS)
    with pytest.raises(ValueError, match="timezone must be UTC"):
        validate_heatwave_events(df)


def test_p3_hourly_validation_detects_duplicate_timestamp():
    """Hourly validator must reject duplicate timestamps."""
    row1 = {
        "timestamp_utc": datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc),
        "local_timestamp": "2024-07-01T00:00:00",
        "local_date": "2024-07-01",
        "hour_local": 0,
        "event_id": "HW_20240702",
        "event_phase": "onset",
        "station_id": "USW00023234",
        "daily_max_temperature_c": 24.0,
        "threshold_temperature_c": 25.6,
        "exceeds_threshold": False,
        "temperature_missing": False,
        "source_quality": "verified",
    }
    row2 = dict(row1)
    df = pd.DataFrame([row1, row2], columns=HOURLY_EVENT_LABEL_COLUMNS)
    with pytest.raises(ValueError, match="Duplicate timestamp_utc found"):
        validate_hourly_event_labels(df)


def test_p3_hourly_validation_detects_wrong_local_date():
    """Hourly validator must reject mismatch between timestamp_utc and local_date."""
    row = {
        "timestamp_utc": datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc),  # 2024-07-01 00:00:00 in LA
        "local_timestamp": "2024-07-01T00:00:00",
        "local_date": "2024-07-02",  # Mismatch!
        "hour_local": 0,
        "event_id": "HW_20240702",
        "event_phase": "onset",
        "station_id": "USW00023234",
        "daily_max_temperature_c": 24.0,
        "threshold_temperature_c": 25.6,
        "exceeds_threshold": False,
        "temperature_missing": False,
        "source_quality": "verified",
    }
    df = pd.DataFrame([row], columns=HOURLY_EVENT_LABEL_COLUMNS)
    with pytest.raises(ValueError, match="local_date '2024-07-02' != expected '2024-07-01'"):
        validate_hourly_event_labels(df)


# =========================================================================
# Contract Document Schema Tests
# =========================================================================

def test_p3_contract_table_schema_exact_match():
    """Verify docs/contracts.md documents exact column names and ordering for P3 tables."""
    from heattrace.workload import WORKLOAD_JOB_COLUMNS
    from heattrace.process.controls import CONTROL_CATALOGUE_COLUMNS
    from heattrace.process.benchmark import BENCHMARK_COLUMNS

    contracts_path = Path("docs/contracts.md")
    assert contracts_path.exists()
    content = contracts_path.read_text(encoding="utf-8")

    # 1. Event Catalogue Schema
    ev_match = re.search(r"### Event Catalogue Schema.*?(?=\n---|\Z)", content, re.DOTALL)
    assert ev_match is not None, "Event Catalogue Schema table not found"
    ev_cols = []
    for line in ev_match.group(0).splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_]+)`\s*\|", line.strip())
        if m:
            ev_cols.append(m.group(1))
    assert ev_cols == EVENT_CATALOGUE_COLUMNS

    # 2. Hourly Event Labels Schema
    lbl_match = re.search(r"### Hourly Event Labels Schema.*?(?=### Phase Assignment Rules|\Z)", content, re.DOTALL)
    assert lbl_match is not None, "Hourly Event Labels Schema table not found"
    lbl_cols = []
    for line in lbl_match.group(0).splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_]+)`\s*\|", line.strip())
        if m:
            lbl_cols.append(m.group(1))
    assert lbl_cols == HOURLY_EVENT_LABEL_COLUMNS

    # 3. Workload Job Schema
    wl_match = re.search(r"### Workload Job Schema.*?(?=\n---|\Z)", content, re.DOTALL)
    assert wl_match is not None, "Workload Job Schema table not found"
    wl_cols = []
    for line in wl_match.group(0).splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_]+)`\s*\|", line.strip())
        if m:
            wl_cols.append(m.group(1))
    assert wl_cols == WORKLOAD_JOB_COLUMNS

    # 4. Control Window Schema
    ctrl_match = re.search(r"### Control Window Schema.*?(?=\n---|\Z)", content, re.DOTALL)
    assert ctrl_match is not None, "Control Window Schema table not found"
    ctrl_cols = []
    for line in ctrl_match.group(0).splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_]+)`\s*\|", line.strip())
        if m:
            ctrl_cols.append(m.group(1))
    assert ctrl_cols == CONTROL_CATALOGUE_COLUMNS

    # 5. Benchmark Schema
    bench_match = re.search(r"### Benchmark Schema.*?(?=\n---|\Z)", content, re.DOTALL)
    assert bench_match is not None, "Benchmark Schema table not found"
    bench_cols = []
    for line in bench_match.group(0).splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_]+)`\s*\|", line.strip())
        if m:
            bench_cols.append(m.group(1))
    assert bench_cols == BENCHMARK_COLUMNS


# =========================================================================
# Authentic Data Integration Test (2022–2025)
# =========================================================================

def test_p3_authentic_dataset_event_detection_and_catalog():
    """Verify authentic 2022-2025 NOAA GHCNh files produce exact expected heatwaves."""
    base_dir = Path(__file__).resolve().parents[1]
    hw_cfg = load_heatwave_config(config_dir=base_dir / "configs")
    years = hw_cfg["years"]
    station_id = hw_cfg["station_id"]
    files = [base_dir / f"data/raw/noaa/GHCNh_{station_id}_{y}.psv" for y in years]

    for f in files:
        assert f.exists(), f"Authentic NOAA file missing: {f}"

    thresh_info = compute_heatwave_percentile_threshold(
        files,
        station_id=station_id,
        years=years,
        months=hw_cfg["months"],
        target_timezone=hw_cfg["target_timezone"],
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
    )

    assert thresh_info["sample_size"] == 485
    assert thresh_info["threshold_p90_display_c"] == 25.6
    assert abs(thresh_info["threshold_p90_c"] - 25.6) < 1e-5

    daily_by_date = {d["local_date"]: d for d in thresh_info["daily_maxima"]}

    df_events, runs = detect_heatwave_events(
        thresh_info["daily_maxima"],
        thresh_info["threshold_p90_c"],
        station_id=station_id,
        target_timezone=hw_cfg["target_timezone"],
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
        min_consecutive_days=hw_cfg["min_consecutive_days"],
    )

    assert len(df_events) == 4
    event_ids = df_events["event_id"].tolist()
    assert event_ids == ["HW_20220620", "HW_20220904", "HW_20220922", "HW_20240702"]

    sept2022 = df_events[df_events["event_id"] == "HW_20220904"].iloc[0]
    assert sept2022["local_start_date"] == "2022-09-04"
    assert sept2022["local_end_date"] == "2022-09-08"
    assert sept2022["duration_days"] == 5
    assert sept2022["duration_hours"] == 120
    assert sept2022["peak_local_date"] == "2022-09-05"
    assert sept2022["peak_temperature_c"] == 35.6

    df_labels = build_hourly_phase_labels(
        df_events,
        daily_records_by_date=daily_by_date,
        threshold_p90_c=thresh_info["threshold_p90_c"],
        target_timezone=hw_cfg["target_timezone"],
    )
    assert len(df_labels) == 528
    assert int(df_events["duration_hours"].sum()) == 336


def test_p3_manifest_and_sha256_integrity():
    """Verify generated manifest reflects authentic files and valid SHA-256 digests."""
    base_dir = Path(__file__).resolve().parents[1]
    manifest_path = base_dir / "data/manifests/event_catalogue_manifest.json"
    coverage_path = base_dir / "data/manifests/event_coverage.csv"
    events_parquet = base_dir / "data/events/heatwave_events_v0.parquet"
    labels_parquet = base_dir / "data/events/hourly_event_labels_v0.parquet"

    assert manifest_path.exists()
    assert coverage_path.exists()
    assert events_parquet.exists()
    assert labels_parquet.exists()

    with manifest_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    assert meta["phase"] == "P3"
    assert meta["pipeline_step"] == "P3-01/P3-02"
    assert meta["station_id"] == "USW00023234"
    assert meta["target_timezone"] == "America/Los_Angeles"
    assert meta["total_expected_days"] == 488
    assert meta["total_valid_days"] == 485
    assert meta["total_missing_days"] == 3
    assert meta["threshold_p90_display_c"] == 25.6
    assert meta["events_count"] == 4
    assert meta["total_event_hours"] == 336
    assert meta["total_phase_labeled_hours"] == 528

    for key, info in meta["output_files"].items():
        p = base_dir / info["path"]
        actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual_sha == info["sha256"], f"SHA256 mismatch for {key}: {actual_sha} != {info['sha256']}"


def test_p3_production_p1_p2_files_unmutated():
    """Verify test run does not modify frozen P1/P2 production files."""
    base_dir = Path(__file__).resolve().parents[1]
    expected_hashes = {
        "hourly_caiso_v0.parquet": (base_dir / "data/processed/hourly_caiso_v0.parquet", "c41e2c26f1e350f78458910c6dddf9ec3004caaaafc2a961b5c7367a31f0eefe"),
        "hourly_caiso_v0_sample.csv": (base_dir / "data/processed/hourly_caiso_v0_sample.csv", "3dbabe90bbc7beb67f09e16ca2430bf005056094b831f6f5315ef0171942ebb3"),
        "aligned_coverage.csv": (base_dir / "data/manifests/aligned_coverage.csv", "3d3ac3f85e5ee435f70dd2343b76912a7423f629f1312944b048a3a4017eb15d"),
        "aligned_dataset_manifest.json": (base_dir / "data/manifests/aligned_dataset_manifest.json", "6a51085632363c522b158f817faaab2593c09933fbb6fcf33e9829ce50379a32"),
        "CISO.xlsx": (base_dir / "data/raw/eia/CISO.xlsx", "b418ea77f536048e11fe0c5786de7544dfa7c774a90083e7f2c0d9facc74ce50"),
    }
    for name, (path, expected) in expected_hashes.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"{name} mutated! actual {actual} != expected {expected}"
