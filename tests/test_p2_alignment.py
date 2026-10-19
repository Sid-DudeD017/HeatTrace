"""Comprehensive unit tests for HeatTrace Phase P2: Alignment, QC, Provenance, and Onboarding."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from heattrace.ingest.noaa import (
    check_noaa_temperature_quality,
    get_local_day_utc_bounds,
)
from heattrace.process.alignment import (
    aggregate_noaa_hourly_temperature,
    build_aligned_dataset,
    build_canonical_hourly_intervals,
    load_caiso_dam_lmp_by_interval,
    load_eia_api_data_by_interval,
    load_eia_workbook_by_interval,
    write_aligned_coverage_csv,
    write_aligned_manifest_json,
    write_aligned_outputs,
)
from heattrace.process.loader import inspect_aligned_dataset, load_aligned_dataset
from heattrace.process.quality import (
    CANONICAL_COLUMNS,
    DEFAULT_RECONCILIATION_TOLERANCE_LB_PER_KWH,
    validate_aligned_dataframe,
)


def _create_mock_noaa_psv(file_path: Path, station_id: str = "USW00023234") -> None:
    """Create a minimal valid synthetic NOAA GHCNh PSV file."""
    header = "STATION|Station_name|DATE|Year|Month|Day|Hour|Minute|LATITUDE|LONGITUDE|ELEVATION|temperature|temperature_Quality_Code|temperature_Measurement_Code|temperature_Report_Type|temperature_Source_Code\n"
    lines = [header]

    # Two test days: 2024-06-07 and 2024-07-02
    for d_str in ("2024-06-07", "2024-07-02"):
        s_utc, e_utc, _ = get_local_day_utc_bounds(d_str, "America/Los_Angeles")
        curr = s_utc
        while curr < e_utc:
            # Observation at top of hour
            lines.append(
                f"{station_id}|SFO|{curr.strftime('%Y-%m-%dT%H:%M:%S')}|{curr.year}|{curr.month}|{curr.day}|{curr.hour}|{curr.minute}|37.6|-122.4|3.0|20.0|||FM15|313\n"
            )
            # Second observation at half-past hour to test within-hour aggregation
            mid = curr + timedelta(minutes=30)
            lines.append(
                f"{station_id}|SFO|{mid.strftime('%Y-%m-%dT%H:%M:%S')}|{mid.year}|{mid.month}|{mid.day}|{mid.hour}|{mid.minute}|37.6|-122.4|3.0|22.0|1||FM15|313\n"
            )
            curr += timedelta(hours=1)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("".join(lines), encoding="utf-8")


def _create_mock_caiso_zip(
    zip_path: Path,
    start_utc: datetime,
    end_utc: datetime,
    node: str = "TH_NP15_GEN-APND",
    price_base: float = 30.0,
) -> None:
    """Create a minimal valid synthetic CAISO OASIS zip with total LMP records."""
    import io
    import zipfile

    out_csv = io.StringIO()
    writer = csv.writer(out_csv)
    writer.writerow([
        "INTERVALSTARTTIME_GMT",
        "INTERVALENDTIME_GMT",
        "NODE",
        "MARKET_RUN_ID",
        "LMP_TYPE",
        "XML_DATA_ITEM",
        "MW",
        "GROUP",
    ])

    curr = start_utc
    hour_idx = 0
    while curr < end_utc:
        h_end = curr + timedelta(hours=1)
        # Include some negative price to verify acceptance
        price = price_base if hour_idx % 5 != 0 else -15.5
        writer.writerow([
            curr.strftime("%Y-%m-%dT%H:%M:00-00:00"),
            h_end.strftime("%Y-%m-%dT%H:%M:00-00:00"),
            node,
            "DAM",
            "LMP",
            "LMP_PRC",
            str(price),
            "1",
        ])
        curr = h_end
        hour_idx += 1

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("test_caiso.csv", out_csv.getvalue())


def _create_mock_eia_json(
    json_path: Path,
    start_utc: datetime,
    end_utc: datetime,
    ba: str = "CISO",
) -> None:
    """Create a minimal valid synthetic EIA API region-data JSON file."""
    records = []
    curr = start_utc
    while curr < end_utc:
        p_str = curr.strftime("%Y-%m-%dT%H")
        records.append({
            "period": p_str,
            "respondent": ba,
            "type": "D",
            "value": "25000",
            "value-units": "megawatthours",
        })
        records.append({
            "period": p_str,
            "respondent": ba,
            "type": "NG",
            "value": "20000",
            "value-units": "megawatthours",
        })
        curr += timedelta(hours=1)

    payload = {"response": {"data": records}}
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload), encoding="utf-8")


from tests.test_p1_ingest import _create_mock_ciso_xlsx



# =========================================================================
# Test Suite
# =========================================================================


def test_build_canonical_hourly_intervals():
    """Verify UTC hourly interval construction, boundaries, and 24 hours per day."""
    days_cfg = {
        "ordinary": {"date": "2024-06-07"},
        "heatwave": {"date": "2024-07-02"},
    }
    intervals = build_canonical_hourly_intervals(days_cfg, target_timezone="America/Los_Angeles")
    assert len(intervals) == 48

    # Check order is ascending
    ts_list = [inv["timestamp_utc"] for inv in intervals]
    assert ts_list == sorted(ts_list)
    assert len(set(ts_list)) == 48

    # Check boundaries
    assert ts_list[0] == datetime(2024, 6, 7, 7, 0, tzinfo=timezone.utc)
    assert intervals[23]["timestamp_utc"] == datetime(2024, 6, 8, 6, 0, tzinfo=timezone.utc)
    assert intervals[24]["timestamp_utc"] == datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc)
    assert intervals[47]["timestamp_utc"] == datetime(2024, 7, 3, 6, 0, tzinfo=timezone.utc)


def test_dst_spring_forward_and_fall_back_boundaries():
    """Verify that DST spring-forward produces 23 hours and fall-back produces 25 hours."""
    # In America/Los_Angeles:
    # 2024-03-10: Spring-forward (23 hours)
    # 2024-11-03: Fall-back (25 hours)
    s_sp, e_sp, hrs_sp = get_local_day_utc_bounds("2024-03-10", "America/Los_Angeles")
    assert hrs_sp == 23.0
    assert (e_sp - s_sp).total_seconds() == 23 * 3600

    s_fb, e_fb, hrs_fb = get_local_day_utc_bounds("2024-11-03", "America/Los_Angeles")
    assert hrs_fb == 25.0
    assert (e_fb - s_fb).total_seconds() == 25 * 3600

    # Ensure canonical builder accurately reflects 23 and 25 hours
    intervals_dst = build_canonical_hourly_intervals(
        {"spring": {"date": "2024-03-10"}, "fall": {"date": "2024-11-03"}},
        target_timezone="America/Los_Angeles",
    )
    assert len(intervals_dst) == 48
    spring_invs = [x for x in intervals_dst if x["local_date"] == "2024-03-10"]
    fall_invs = [x for x in intervals_dst if x["local_date"] == "2024-11-03"]
    assert len(spring_invs) == 23
    assert len(fall_invs) == 25


def test_noaa_within_hour_aggregation(tmp_path: Path):
    """Test NOAA arithmetic mean, min, max, count, and quality filtering."""
    psv_file = tmp_path / "GHCNh_USW00023234_2024.psv"
    _create_mock_noaa_psv(psv_file)

    intervals = [
        {
            "timestamp_utc": datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc),
            "interval_end_utc": datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc),
            "local_date": "2024-07-02",
            "qc_day_type": "heatwave",
        },
        {
            "timestamp_utc": datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc),
            "interval_end_utc": datetime(2024, 7, 2, 9, 0, tzinfo=timezone.utc),
            "local_date": "2024-07-02",
            "qc_day_type": "heatwave",
        },
    ]

    res = aggregate_noaa_hourly_temperature(psv_file, intervals, expected_station="USW00023234")
    # In mock, hour 7:00 has two obs: 20.0 and 22.0 -> mean = 21.0
    h7 = res[datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc)]
    assert h7["temperature_c"] == 21.0
    assert h7["temperature_obs_count"] == 2
    assert h7["temperature_min_c"] == 20.0
    assert h7["temperature_max_c"] == 22.0
    assert h7["temperature_missing"] is False


def test_noaa_missing_hour_no_interpolation(tmp_path: Path):
    """Verify that an hour with no accepted observations has temperature_missing=True and None values."""
    psv_file = tmp_path / "GHCNh_USW00023234_2024.psv"
    # Write only 1 observation at 07:00
    psv_file.write_text(
        "STATION|Station_name|DATE|Year|Month|Day|Hour|Minute|LATITUDE|LONGITUDE|ELEVATION|temperature|temperature_Quality_Code|temperature_Measurement_Code|temperature_Report_Type|temperature_Source_Code\n"
        "USW00023234|SFO|2024-07-02T07:00:00|2024|7|2|7|0|37.6|-122.4|3.0|25.0|||FM15|313\n"
    )

    intervals = [
        {
            "timestamp_utc": datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc),
            "interval_end_utc": datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc),
            "local_date": "2024-07-02",
            "qc_day_type": "heatwave",
        },
        {
            "timestamp_utc": datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc),
            "interval_end_utc": datetime(2024, 7, 2, 9, 0, tzinfo=timezone.utc),
            "local_date": "2024-07-02",
            "qc_day_type": "heatwave",
        },
    ]

    res = aggregate_noaa_hourly_temperature(psv_file, intervals, expected_station="USW00023234")
    h8 = res[datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc)]
    assert h8["temperature_c"] is None
    assert h8["temperature_obs_count"] == 0
    assert h8["temperature_min_c"] is None
    assert h8["temperature_max_c"] is None
    assert h8["temperature_missing"] is True


def test_eia_hour_ending_to_interval_start_mapping(tmp_path: Path):
    """Verify that EIA workbook hour-ending timestamp maps accurately to canonical interval start."""
    wb_path = tmp_path / "CISO.xlsx"
    start_utc = datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_path, hours=1, start_date_utc=start_utc)

    intervals = [{
        "timestamp_utc": start_utc,
        "interval_end_utc": end_utc,
        "local_date": "2024-07-02",
        "qc_day_type": "heatwave",
    }]

    wb_data = load_eia_workbook_by_interval(wb_path, intervals, expected_ba="CISO")
    assert start_utc in wb_data
    assert wb_data[start_utc]["hour_ending_utc"] == end_utc


def test_carbon_intensity_conversion_and_reconciliation(tmp_path: Path):
    """Verify conversion of lb/kWh to g/kWh (using 453.59237) and reconciliation against recalculated value."""
    wb_path = tmp_path / "CISO.xlsx"
    start_utc = datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2024, 7, 2, 8, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_path, hours=1, start_date_utc=start_utc)

    intervals = [{
        "timestamp_utc": start_utc,
        "interval_end_utc": end_utc,
        "local_date": "2024-07-02",
        "qc_day_type": "heatwave",
    }]
    wb_data = load_eia_workbook_by_interval(wb_path, intervals)
    row = wb_data[start_utc]

    gen_lb = row["co2_intensity_generated_lb_per_kwh"]
    gen_g = gen_lb * 453.59237
    assert abs(row["co2_intensity_generated_g_per_kwh"] - gen_g) < 1e-6

    # Recalculation
    co2_mt = row["co2_emissions_generated_metric_tons"]
    pos_gen = row["positive_generation_mwh"]
    recalc_lb = (co2_mt * 2204.62262185) / (pos_gen * 1000.0)
    assert abs(recalc_lb - gen_lb) < 1e-6


def test_eia_data_issue_propagation_and_eligibility(tmp_path: Path):
    """Verify that EIA rows with data_issue=1 retain flags and set primary_analysis_eligible=False."""
    # Synthetic complete pipeline setup
    d_dir = tmp_path / "data"
    cfg_dir = tmp_path / "configs"
    d_dir.mkdir(parents=True)
    cfg_dir.mkdir(parents=True)

    sources_cfg = {
        "study": {"timezone": "UTC"},
        "weather": {"stations": [{"id": "USW00023234"}]},
        "price": {"node": "TH_NP15_GEN-APND", "product": "day_ahead_hourly_lmp"},
        "carbon": {"balancing_authority": "CISO"},
        "qc": {
            "primary_station_id": "USW00023234",
            "target_timezone": "America/Los_Angeles",
            "days": {
                "heatwave": {"date": "2024-07-02"},
                "ordinary": {"date": "2024-06-07"},
            },
        },
    }

    (cfg_dir / "sources.yaml").write_text(
        "price:\n  node: TH_NP15_GEN-APND\n  product: day_ahead_hourly_lmp\n"
        "carbon:\n  balancing_authority: CISO\n"
        "weather:\n  stations:\n    - id: USW00023234\n"
        "qc:\n  primary_station_id: USW00023234\n  target_timezone: America/Los_Angeles\n"
        "  days:\n    heatwave:\n      date: '2024-07-02'\n    ordinary:\n      date: '2024-06-07'\n",
        encoding="utf-8",
    )

    # Generate mock sources
    _create_mock_noaa_psv(d_dir / "raw/noaa/GHCNh_USW00023234_2024.psv")

    s1, e1, _ = get_local_day_utc_bounds("2024-07-02", "America/Los_Angeles")
    s2, e2, _ = get_local_day_utc_bounds("2024-06-07", "America/Los_Angeles")

    _create_mock_caiso_zip(
        d_dir / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240702_20240703.zip",
        s1,
        e1,
    )
    _create_mock_caiso_zip(
        d_dir / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240607_20240608.zip",
        s2,
        e2,
    )

    _create_mock_eia_json(d_dir / "raw/eia/eia930_region_CISO_20240702.json", s1, e1)
    _create_mock_eia_json(d_dir / "raw/eia/eia930_region_CISO_20240607.json", s2, e2)

    # Spans both dates (from s2 to e1 is 26 days = 624 hours)
    total_hours = int((e1 - s2).total_seconds() / 3600)
    _create_mock_ciso_xlsx(d_dir / "raw/eia/CISO.xlsx", hours=total_hours, start_date_utc=s2, issue_flag_mode="all")

    df = build_aligned_dataset(sources_cfg=sources_cfg, data_dir=d_dir)
    assert len(df) == 48
    assert df["carbon_data_issue"].all()
    assert not df["carbon_primary_analysis_eligible"].any()
    assert (df["source_quality"] == "success_with_data_issues").all()

    # Negative prices must be accepted and preserved
    assert (df["price_usd_per_mwh"] < 0).any()

    # Parquet and CSV output writing
    outputs = write_aligned_outputs(df, data_dir=d_dir, config_dir=cfg_dir)
    parquet_p = Path(outputs["parquet_path"])
    sample_csv_p = Path(outputs["sample_csv_path"])
    cov_p = Path(outputs["coverage_path"])
    man_p = Path(outputs["manifest_path"])

    assert parquet_p.exists()
    assert sample_csv_p.exists()
    assert cov_p.exists()
    assert man_p.exists()

    # Loader verification
    loaded_df = load_aligned_dataset(parquet_p, validate=True)
    assert len(loaded_df) == 48
    summary = inspect_aligned_dataset(parquet_p)
    assert summary["row_count"] == 48
    assert summary["duplicate_timestamps"] == 0


def test_schema_validation_failures(tmp_path: Path):
    """Test deterministic validation failures on shifted timestamps, duplicates, missing columns, or bad counts."""
    # Start with valid dummy DataFrame
    ts = pd.date_range("2024-07-02 07:00", periods=48, freq="h", tz="UTC")
    data = {c: [None] * 48 for c in CANONICAL_COLUMNS}
    data["timestamp_utc"] = ts
    data["local_date"] = ["2024-07-02"] * 24 + ["2024-06-07"] * 24
    data["qc_day_type"] = ["heatwave"] * 24 + ["ordinary"] * 24
    data["temperature_missing"] = [False] * 48
    data["temperature_c"] = [20.0] * 48
    data["temperature_obs_count"] = [1] * 48
    data["temperature_min_c"] = [20.0] * 48
    data["temperature_max_c"] = [20.0] * 48
    data["price_missing"] = [False] * 48
    data["price_usd_per_mwh"] = [35.0] * 48
    data["demand_missing"] = [False] * 48
    data["demand_mw"] = [25000.0] * 48
    data["net_generation_missing"] = [False] * 48
    data["net_generation_mw"] = [20000.0] * 48
    data["carbon_missing"] = [False] * 48
    data["carbon_g_per_kwh"] = [200.0] * 48
    data["carbon_data_issue"] = [False] * 48
    data["carbon_primary_analysis_eligible"] = [True] * 48
    data["source_quality"] = ["success"] * 48
    data["generated_intensity_reconciliation_difference"] = [0.0] * 48

    df_valid = pd.DataFrame(data)[CANONICAL_COLUMNS]
    # Passes validation
    validate_aligned_dataframe(
        df_valid, expected_rows=48, expected_dates=["2024-07-02", "2024-06-07"]
    )

    # 1. Failure on wrong row count
    with pytest.raises(ValueError, match="Expected exactly 48 rows"):
        validate_aligned_dataframe(df_valid.iloc[:40])

    # 2. Failure on duplicate timestamps
    df_dup = df_valid.copy()
    df_dup.loc[1, "timestamp_utc"] = df_dup.loc[0, "timestamp_utc"]
    with pytest.raises(ValueError, match="duplicate timestamp_utc"):
        validate_aligned_dataframe(df_dup)

    # Failure on non-monotonic timestamps (swap adjacent rows without duplicating)
    df_non_mono = df_valid.copy()
    df_non_mono.loc[0, "timestamp_utc"], df_non_mono.loc[1, "timestamp_utc"] = (
        df_valid.loc[1, "timestamp_utc"],
        df_valid.loc[0, "timestamp_utc"],
    )
    with pytest.raises(ValueError, match="timestamp_utc is not monotonically increasing"):
        validate_aligned_dataframe(df_non_mono)

    # 3. Failure on naive timestamp
    df_naive = df_valid.copy()
    df_naive["timestamp_utc"] = [t.replace(tzinfo=None) for t in df_valid["timestamp_utc"]]
    with pytest.raises(ValueError, match="timestamp_utc must be timezone-aware UTC"):
        validate_aligned_dataframe(df_naive)

    # 4. Failure on unaligned timestamp (not on the hour)
    df_unaligned = df_valid.copy()
    df_unaligned.loc[0, "timestamp_utc"] = df_unaligned.loc[0, "timestamp_utc"] + timedelta(
        minutes=15
    )
    with pytest.raises(ValueError, match="not aligned to the top of the hour"):
        validate_aligned_dataframe(df_unaligned)

    # 5. Failure on negative carbon
    df_neg_carbon = df_valid.copy()
    df_neg_carbon.loc[0, "carbon_g_per_kwh"] = -10.0
    with pytest.raises(ValueError, match="carbon intensity .* is negative"):
        validate_aligned_dataframe(df_neg_carbon)

    # 6. Failure on excessive reconciliation diff
    df_bad_reconcil = df_valid.copy()
    df_bad_reconcil.loc[0, "generated_intensity_reconciliation_difference"] = 0.05
    with pytest.raises(ValueError, match="carbon reconciliation diff .* exceeds tolerance"):
        validate_aligned_dataframe(df_bad_reconcil)

    # 7. Missing required column
    df_missing_col = df_valid.drop(columns=["price_usd_per_mwh"])
    with pytest.raises(ValueError, match="schema mismatch"):
        validate_aligned_dataframe(df_missing_col)


def test_test_isolation_guarantee():
    """Verify that no test writes to production data directories."""
    # Confirm production raw CISO.xlsx hash remains intact
    ciso_wb = Path("data/raw/eia/CISO.xlsx")
    assert ciso_wb.exists()
    from heattrace.ingest.provenance import sha256_file

    expected_sha = "b418ea77f536048e11fe0c5786de7544dfa7c774a90083e7f2c0d9facc74ce50"
    assert sha256_file(ciso_wb) == expected_sha
