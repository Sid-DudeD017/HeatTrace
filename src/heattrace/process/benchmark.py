"""Stage 5 and 6: Aligned 2024 Event/Control Benchmark Construction, Verification, and Audit."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.caiso import parse_caiso_zip, validate_caiso_lmp_rows
from heattrace.ingest.coverage import compute_hourly_coverage
from heattrace.ingest.eia import (
    LB_TO_GRAMS,
    parse_and_validate_eia_ciso_workbook,
    parse_and_validate_eia_json,
)
from heattrace.ingest.noaa import (
    check_noaa_temperature_quality,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
)
from heattrace.ingest.provenance import sha256_file
from heattrace.process.controls import match_deterministic_control
from heattrace.process.events import compute_heatwave_percentile_threshold, detect_heatwave_events, load_heatwave_config


BENCHMARK_COLUMNS: list[str] = [
    "timestamp_utc",
    "local_timestamp",
    "local_date",
    "hour_local",
    "window_type",
    "window_id",
    "phase_label",
    "temperature_c",
    "temperature_obs_count",
    "temperature_missing",
    "price_usd_per_mwh",
    "price_missing",
    "demand_mw",
    "demand_missing",
    "net_generation_mw",
    "net_generation_missing",
    "carbon_g_per_kwh",
    "carbon_missing",
    "carbon_data_issue",
    "carbon_primary_analysis_eligible",
    "source_quality",
    "source_station_id",
    "source_caiso_node",
    "source_balancing_authority",
]


def build_benchmark_hourly_rows(
    *,
    window_type: str,  # "event" or "control"
    window_id: str,    # "HW_20240702" or "CTRL_20240605"
    start_date_str: str,
    end_date_inclusive_str: str,
    phase_mapping: dict[str, str],  # local_date -> phase_label
    data_dir: Path,
    target_timezone: str = "America/Los_Angeles",
) -> list[dict[str, Any]]:
    """Build aligned 120 hourly rows for one benchmark window from cached authentic sources."""
    tz = ZoneInfo(target_timezone)

    # Compute UTC bounds
    start_utc, _, _ = get_local_day_utc_bounds(start_date_str, target_timezone=target_timezone)
    _, end_utc, _ = get_local_day_utc_bounds(end_date_inclusive_str, target_timezone=target_timezone)

    expected_hours = int(round((end_utc - start_utc).total_seconds() / 3600.0))
    if expected_hours != 120:
        raise ValueError(f"Window {window_id} ({start_date_str} to {end_date_inclusive_str}) expected 120h, got {expected_hours}h")

    # 1. NOAA Observations
    noaa_file = data_dir / "raw/noaa/GHCNh_USW00023234_2024.psv"
    noaa_all = parse_ghcnh_psv(noaa_file, filter_date_start=start_utc, filter_date_end=end_utc)
    # Group by interval-start UTC
    noaa_by_hour: dict[datetime, list[float]] = {}
    for r in noaa_all:
        qc = check_noaa_temperature_quality(r.get("temperature_quality_code", ""))
        temp = r.get("temperature_c")
        if qc == "accepted" and temp is not None:
            ts = r["timestamp_utc"]
            bin_start = datetime(ts.year, ts.month, ts.day, ts.hour, 0, tzinfo=timezone.utc)
            noaa_by_hour.setdefault(bin_start, []).append(float(temp))

    # 2. CAISO OASIS LMP
    start_tag = start_date_str.replace("-", "")
    end_tag = (date.fromisoformat(end_date_inclusive_str) + timedelta(days=1)).strftime("%Y%m%d")
    caiso_file = data_dir / f"raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_{start_tag}_{end_tag}.zip"
    if not caiso_file.exists():
        raise FileNotFoundError(f"CAISO zip file not found: {caiso_file}")

    caiso_parsed, err = parse_caiso_zip(caiso_file, expected_node="TH_NP15_GEN-APND", expected_market="DAM")
    if err:
        raise ValueError(f"Error parsing CAISO zip {caiso_file}: {err}")
    lmp_rows = [r for r in caiso_parsed if r["lmp_type"] == "LMP"]
    validate_caiso_lmp_rows(
        lmp_rows,
        expected_node="TH_NP15_GEN-APND",
        expected_market="DAM",
        requested_start=start_utc,
        requested_end=end_utc,
    )
    caiso_by_hour = {r["timestamp_utc"]: float(r["price_usd_per_mwh"]) for r in lmp_rows}

    # 3. EIA API Demand and Net Gen
    eia_json_file = data_dir / f"raw/eia/eia930_region_CISO_{start_tag}.json"
    if not eia_json_file.exists():
        raise FileNotFoundError(f"EIA json file not found: {eia_json_file}")
    eia_api_data = parse_and_validate_eia_json(
        eia_json_file.read_text(encoding="utf-8"),
        expected_ba="CISO",
        requested_start=start_utc,
        requested_end=end_utc,
    )
    demand_by_hour = {r["timestamp_utc"]: float(r["value_mw"]) for r in eia_api_data["demand_rows"]}
    net_gen_by_hour = {r["timestamp_utc"]: float(r["value_mw"]) for r in eia_api_data["net_gen_rows"]}

    # 4. EIA Workbook Emissions and Intensity
    workbook_file = data_dir / "raw/eia/CISO.xlsx"
    eia_wb_data = parse_and_validate_eia_ciso_workbook(
        workbook_file,
        requested_start=start_utc,
        requested_end=end_utc,
        expected_ba="CISO",
    )
    wb_by_hour = {r["timestamp_utc"]: r for r in eia_wb_data["rows"]}

    rows: list[dict[str, Any]] = []
    curr = start_utc
    while curr < end_utc:
        loc_dt = curr.astimezone(tz)
        loc_ts_str = loc_dt.strftime("%Y-%m-%dT%H:%M:%S")
        loc_d_str = loc_dt.strftime("%Y-%m-%d")
        loc_hour = loc_dt.hour

        phase_val = phase_mapping.get(loc_d_str, "control")

        # Weather
        obs = noaa_by_hour.get(curr, [])
        if obs:
            temp_c = round(float(sum(obs) / len(obs)), 2)
            temp_obs_cnt = len(obs)
            temp_missing = False
        else:
            temp_c = None
            temp_obs_cnt = 0
            temp_missing = True

        # Price
        if curr in caiso_by_hour:
            price_val = caiso_by_hour[curr]
            price_missing = False
        else:
            price_val = None
            price_missing = True

        # Demand & Net Gen
        if curr in demand_by_hour:
            demand_val = demand_by_hour[curr]
            demand_missing = False
        else:
            demand_val = None
            demand_missing = True

        if curr in net_gen_by_hour:
            net_gen_val = net_gen_by_hour[curr]
            net_gen_missing = False
        else:
            net_gen_val = None
            net_gen_missing = True

        # Carbon
        if curr in wb_by_hour:
            wb_rec = wb_by_hour[curr]
            carbon_val = wb_rec["co2_intensity_generated_g_per_kwh"]
            carbon_missing = False
            has_issue = wb_rec["has_data_issue"]
            carbon_eligible = not has_issue
            source_q = "success_with_data_issues" if has_issue else "success"
        else:
            carbon_val = None
            carbon_missing = True
            has_issue = False
            carbon_eligible = False
            source_q = "missing"

        rows.append({
            "timestamp_utc": curr,
            "local_timestamp": loc_ts_str,
            "local_date": loc_d_str,
            "hour_local": loc_hour,
            "window_type": window_type,
            "window_id": window_id,
            "phase_label": phase_val,
            "temperature_c": temp_c,
            "temperature_obs_count": temp_obs_cnt,
            "temperature_missing": temp_missing,
            "price_usd_per_mwh": price_val,
            "price_missing": price_missing,
            "demand_mw": demand_val,
            "demand_missing": demand_missing,
            "net_generation_mw": net_gen_val,
            "net_generation_missing": net_gen_missing,
            "carbon_g_per_kwh": carbon_val,
            "carbon_missing": carbon_missing,
            "carbon_data_issue": has_issue,
            "carbon_primary_analysis_eligible": carbon_eligible,
            "source_quality": source_q,
            "source_station_id": "USW00023234",
            "source_caiso_node": "TH_NP15_GEN-APND",
            "source_balancing_authority": "CISO",
        })

        curr += timedelta(hours=1)

    return rows


def build_and_export_p3_benchmark(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
) -> dict[str, Any]:
    """Build, validate, and export the complete 240-row 2024 event/control benchmark."""
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    # Dynamically derive event, control, and phase mappings from catalogues
    events_parquet = data_dir / "events/heatwave_events_v0.parquet"
    control_parquet = data_dir / "events/control_catalogue_v0.parquet"
    labels_parquet = data_dir / "events/hourly_event_labels_v0.parquet"
    workload_parquet = data_dir / "workloads/workload_trace_v0.parquet"

    if not events_parquet.exists():
        raise FileNotFoundError(f"Event catalogue missing: {events_parquet}")
    if not control_parquet.exists():
        raise FileNotFoundError(f"Control catalogue missing: {control_parquet}")
    if not labels_parquet.exists():
        raise FileNotFoundError(f"Hourly labels missing: {labels_parquet}")

    df_events = pd.read_parquet(events_parquet)
    df_control = pd.read_parquet(control_parquet)
    df_labels = pd.read_parquet(labels_parquet)

    # Validate approved 2024 benchmark event
    hw_2024_rows = df_events[df_events["event_id"] == "HW_20240702"]
    if hw_2024_rows.empty:
        raise ValueError("Event HW_20240702 not found in heatwave event catalogue")
    ev_row = hw_2024_rows.iloc[0]

    # Validate approved 2024 benchmark control
    ctrl_rows = df_control[df_control["matched_event_id"] == "HW_20240702"]
    if ctrl_rows.empty:
        raise ValueError("Matched control for HW_20240702 not found in control catalogue")
    ctrl_row = ctrl_rows.iloc[0]
    if ctrl_row["control_id"] != "CTRL_20240605":
        raise ValueError(f"Expected control CTRL_20240605, got {ctrl_row['control_id']}")

    # Derive event window boundaries: onset (1 day pre) to recovery (1 day post)
    ev_start_d = date.fromisoformat(str(ev_row["local_start_date"])) - timedelta(days=1)
    ev_end_d = date.fromisoformat(str(ev_row["local_end_date"])) + timedelta(days=1)
    event_start_str = ev_start_d.isoformat()
    event_end_str = ev_end_d.isoformat()

    # Extract phase map dynamically from df_labels for HW_20240702
    hw_labels = df_labels[df_labels["event_id"] == "HW_20240702"]
    event_phase_map: dict[str, str] = {}
    for d_str, grp in hw_labels.groupby("local_date"):
        phases = grp["event_phase"].unique().tolist()
        event_phase_map[str(d_str)] = phases[0]

    # Derive control window boundaries and phase mapping
    ctrl_start_str = str(ctrl_row["local_start_date"])
    ctrl_end_exclusive = date.fromisoformat(str(ctrl_row["local_end_exclusive"]))
    ctrl_end_str = (ctrl_end_exclusive - timedelta(days=1)).isoformat()
    anchor_str = str(ctrl_row["anchor_date"])

    control_phase_map: dict[str, str] = {}
    cur_c_d = date.fromisoformat(ctrl_start_str)
    while cur_c_d < ctrl_end_exclusive:
        cur_iso = cur_c_d.isoformat()
        control_phase_map[cur_iso] = "control_anchor" if cur_iso == anchor_str else "control"
        cur_c_d += timedelta(days=1)

    event_rows = build_benchmark_hourly_rows(
        window_type="event",
        window_id="HW_20240702",
        start_date_str=event_start_str,
        end_date_inclusive_str=event_end_str,
        phase_mapping=event_phase_map,
        data_dir=data_dir,
    )

    control_rows = build_benchmark_hourly_rows(
        window_type="control",
        window_id=str(ctrl_row["control_id"]),
        start_date_str=ctrl_start_str,
        end_date_inclusive_str=ctrl_end_str,
        phase_mapping=control_phase_map,
        data_dir=data_dir,
    )

    all_rows = control_rows + event_rows  # 120 control + 120 event = 240 rows
    df_benchmark = pd.DataFrame(all_rows, columns=BENCHMARK_COLUMNS)

    validate_benchmark_dataframe(df_benchmark)

    benchmarks_dir = data_dir / "benchmarks"
    manifests_dir = data_dir / "manifests"
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = benchmarks_dir / "benchmark_2024_event_control_v0.parquet"
    csv_sample_path = benchmarks_dir / "benchmark_2024_event_control_v0_sample.csv"
    manifest_path = manifests_dir / "benchmark_manifest.json"

    df_benchmark.to_parquet(parquet_path, index=False)
    sample_df = pd.concat([df_benchmark.head(20), df_benchmark.tail(20)]).drop_duplicates().reset_index(drop=True)
    sample_df.to_csv(csv_sample_path, index=False)

    # Collect project-relative input files lineage
    repo_root = data_dir.parent
    def _rel(p: Path) -> str:
        return str(p.relative_to(repo_root)) if p.is_relative_to(repo_root) else str(p)

    raw_inputs: dict[str, dict[str, Any]] = {}
    candidate_raw = [
        data_dir / "raw/noaa/GHCNh_USW00023234_2024.psv",
        data_dir / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240605_20240610.zip",
        data_dir / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240701_20240706.zip",
        data_dir / "raw/eia/eia930_region_CISO_20240605.json",
        data_dir / "raw/eia/eia930_region_CISO_20240701.json",
        data_dir / "raw/eia/CISO.xlsx",
    ]
    for rf in candidate_raw:
        if rf.exists():
            raw_inputs[rf.name] = {
                "path": _rel(rf),
                "sha256": sha256_file(rf),
                "size_bytes": rf.stat().st_size,
            }

    catalogue_inputs: dict[str, dict[str, Any]] = {}
    for cf in [events_parquet, control_parquet, labels_parquet, workload_parquet]:
        if cf.exists():
            catalogue_inputs[cf.name] = {
                "path": _rel(cf),
                "sha256": sha256_file(cf),
                "size_bytes": cf.stat().st_size,
            }

    config_inputs: dict[str, dict[str, Any]] = {}
    for cname in ["sources.yaml", "study.yaml"]:
        cfg_p = config_dir / cname
        if cfg_p.exists():
            config_inputs[cname] = {
                "path": _rel(cfg_p),
                "sha256": sha256_file(cfg_p),
                "size_bytes": cfg_p.stat().st_size,
            }

    manifest = {
        "manifest_version": "1.0",
        "gate": "G3-a",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(df_benchmark),
        "event_rows": len(event_rows),
        "control_rows": len(control_rows),
        "event_window_id": str(ev_row["event_id"]),
        "control_window_id": str(ctrl_row["control_id"]),
        "event_interval_utc": [
            control_rows[0]["timestamp_utc"].isoformat() if False else event_rows[0]["timestamp_utc"].isoformat(),
            (event_rows[-1]["timestamp_utc"] + timedelta(hours=1)).isoformat(),
        ],
        "control_interval_utc": [
            control_rows[0]["timestamp_utc"].isoformat(),
            (control_rows[-1]["timestamp_utc"] + timedelta(hours=1)).isoformat(),
        ],
        "source_summary": {
            "noaa_station": "USW00023234",
            "caiso_node": "TH_NP15_GEN-APND",
            "eia_balancing_authority": "CISO",
            "timezone": "America/Los_Angeles",
            "canonical_timezone": "UTC",
        },
        "input_files": {
            "raw_sources": raw_inputs,
            "catalogues_and_workloads": catalogue_inputs,
            "configuration": config_inputs,
        },
        "output_files": {
            "benchmark_parquet": {
                "path": _rel(parquet_path),
                "sha256": sha256_file(parquet_path),
                "size_bytes": parquet_path.stat().st_size,
            },
            "benchmark_sample_csv": {
                "path": _rel(csv_sample_path),
                "sha256": sha256_file(csv_sample_path),
                "size_bytes": csv_sample_path.stat().st_size,
            },
        },
    }

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return {
        "df_benchmark": df_benchmark,
        "parquet_path": parquet_path,
        "csv_sample_path": csv_sample_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def validate_benchmark_dataframe(df: pd.DataFrame) -> None:
    """Validate the 240-row benchmark DataFrame according to G3-a specifications."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    actual_cols = list(df.columns)
    if actual_cols != BENCHMARK_COLUMNS:
        raise ValueError(
            f"Benchmark columns mismatch.\nExpected: {BENCHMARK_COLUMNS}\nActual:   {actual_cols}"
        )

    if len(df) != 240:
        raise ValueError(f"Benchmark row count {len(df)} != 240")

    ev_df = df[df["window_type"] == "event"]
    ctrl_df = df[df["window_type"] == "control"]

    if len(ev_df) != 120:
        raise ValueError(f"Event window rows {len(ev_df)} != 120")
    if len(ctrl_df) != 120:
        raise ValueError(f"Control window rows {len(ctrl_df)} != 120")

    # Check timestamps: monotonic within each window, top-of-hour, UTC-aware
    tz_la = ZoneInfo("America/Los_Angeles")

    for name, sub_df in [("event", ev_df), ("control", ctrl_df)]:
        ts_list = sub_df["timestamp_utc"].tolist()
        if ts_list != sorted(ts_list):
            raise ValueError(f"{name} window timestamps are not sorted monotonic ascending")
        if sub_df["timestamp_utc"].duplicated().any():
            raise ValueError(f"{name} window contains duplicate timestamps")

        # Verify continuous 120-hour hourly sequence
        for i in range(1, len(ts_list)):
            step_hours = (ts_list[i] - ts_list[i - 1]).total_seconds() / 3600.0
            if step_hours != 1.0:
                raise ValueError(
                    f"{name} window contains non-continuous step: {ts_list[i-1]} to {ts_list[i]} ({step_hours}h)"
                )

        for idx, row in sub_df.iterrows():
            ts = row["timestamp_utc"]
            if not isinstance(ts, (datetime, pd.Timestamp)) or ts.tzinfo is None:
                raise ValueError(f"Row {idx}: timestamp_utc must be timezone-aware UTC datetime")
            if ts.utcoffset() != timedelta(0):
                raise ValueError(f"Row {idx}: timestamp_utc must have UTC offset 0, got {ts.utcoffset()}")
            if ts.minute != 0 or ts.second != 0:
                raise ValueError(f"Row {idx}: timestamp_utc {ts} is not top-of-hour")

            # Validate local timestamps consistency with America/Los_Angeles
            expected_dt_la = ts.astimezone(tz_la)
            expected_local_ts = expected_dt_la.strftime("%Y-%m-%dT%H:%M:%S")
            expected_local_d = expected_dt_la.strftime("%Y-%m-%d")
            expected_local_h = expected_dt_la.hour

            if row["local_timestamp"] != expected_local_ts:
                raise ValueError(
                    f"Row {idx} ({name}): local_timestamp '{row['local_timestamp']}' != expected '{expected_local_ts}'"
                )
            if row["local_date"] != expected_local_d:
                raise ValueError(
                    f"Row {idx} ({name}): local_date '{row['local_date']}' != expected '{expected_local_d}'"
                )
            if int(row["hour_local"]) != expected_local_h:
                raise ValueError(
                    f"Row {idx} ({name}): hour_local {row['hour_local']} != expected {expected_local_h}"
                )

            # Metadata source checks
            if row["source_station_id"] != "USW00023234":
                raise ValueError(f"Row {idx}: unexpected source_station_id '{row['source_station_id']}'")
            if row["source_caiso_node"] != "TH_NP15_GEN-APND":
                raise ValueError(f"Row {idx}: unexpected source_caiso_node '{row['source_caiso_node']}'")
            if row["source_balancing_authority"] != "CISO":
                raise ValueError(f"Row {idx}: unexpected source_balancing_authority '{row['source_balancing_authority']}'")

            # Check required fields non-null and not NaN
            for col_val, col_missing, col_name in [
                (row["temperature_c"], row["temperature_missing"], "temperature"),
                (row["price_usd_per_mwh"], row["price_missing"], "price"),
                (row["demand_mw"], row["demand_missing"], "demand"),
                (row["net_generation_mw"], row["net_generation_missing"], "net_generation"),
                (row["carbon_g_per_kwh"], row["carbon_missing"], "carbon_intensity"),
            ]:
                if pd.isna(col_val) or col_missing is True:
                    raise ValueError(f"Row {idx} ({name}): missing {col_name} observation")
                if not math.isfinite(float(col_val)):
                    raise ValueError(f"Row {idx} ({name}): non-finite {col_name} observation ({col_val})")

            # Logical consistency check for carbon flags
            if bool(row["carbon_data_issue"]) is True and bool(row["carbon_primary_analysis_eligible"]) is True:
                raise ValueError(
                    f"Row {idx} ({name}): logical contradiction: carbon_data_issue is True but carbon_primary_analysis_eligible is True"
                )


def inspect_benchmark_dataset(parquet_path: Path | str) -> None:
    """Print human-readable summary of the 240-row benchmark table."""
    p = Path(parquet_path)
    if not p.is_file():
        raise FileNotFoundError(f"Benchmark file not found: {p}")

    df = pd.read_parquet(p)
    validate_benchmark_dataframe(df)

    print("\n=================== HeatTrace G3-a Aligned 2024 Benchmark ===================")
    print(f"File:                      {p}")
    print(f"Total Rows:                {len(df)} (120 event + 120 control)")
    print(f"Columns:                   {len(df.columns)}")
    print(f"Event Window:              HW_20240702 (2024-07-01 to 2024-07-05 local)")
    print(f"Control Window:            CTRL_20240605 (2024-06-05 to 2024-06-09 local)")
    print(f"Mean Event Temp:           {df[df['window_type'] == 'event']['temperature_c'].mean():.2f}°C")
    print(f"Mean Control Temp:         {df[df['window_type'] == 'control']['temperature_c'].mean():.2f}°C")
    print(f"Mean Event Price:          ${df[df['window_type'] == 'event']['price_usd_per_mwh'].mean():.2f}/MWh")
    print(f"Mean Control Price:        ${df[df['window_type'] == 'control']['price_usd_per_mwh'].mean():.2f}/MWh")
    print(f"Mean Event Carbon:         {df[df['window_type'] == 'event']['carbon_g_per_kwh'].mean():.2f} g/kWh")
    print(f"Mean Control Carbon:       {df[df['window_type'] == 'control']['carbon_g_per_kwh'].mean():.2f} g/kWh")
    print("-----------------------------------------------------------------------------")
    print("Validation Status:         PASSED (Clean loader verified, complete coverage)")
    print("=============================================================================\n")
