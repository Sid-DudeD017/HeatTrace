"""Heatwave event detection, phase labeling, coverage tracking, and provenance."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.noaa import (
    extract_daily_maxima,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
)
from heattrace.ingest.provenance import sha256_file
from heattrace.process.event_validation import (
    EVENT_CATALOGUE_COLUMNS,
    HOURLY_EVENT_LABEL_COLUMNS,
    validate_heatwave_events,
    validate_hourly_event_labels,
)


def compute_heatwave_percentile_threshold(
    noaa_files: list[Path | str],
    *,
    station_id: str = "USW00023234",
    years: list[int] = [2022, 2023, 2024, 2025],
    months: list[int] = [6, 7, 8, 9],
    target_timezone: str = "America/Los_Angeles",
    percentile: float = 90.0,
) -> dict[str, Any]:
    """Compute empirical percentile threshold over pooled warm-season daily maxima.
    
    Uses linear interpolation method:
      k = (n - 1) * (percentile / 100.0)
      threshold = d[floor(k)] * (ceil(k) - k) + d[ceil(k)] * (k - floor(k))
    """
    tz = ZoneInfo(target_timezone)
    pooled_rows: list[dict[str, Any]] = []

    for f_path in noaa_files:
        path = Path(f_path)
        if not path.is_file():
            raise FileNotFoundError(f"NOAA raw data file not found: {path}")
        raw_rows = parse_ghcnh_psv(path)
        for r in raw_rows:
            ts_loc = r["timestamp_utc"].astimezone(tz)
            if ts_loc.year in years and ts_loc.month in months:
                pooled_rows.append(r)

    if not pooled_rows:
        raise ValueError(f"No weather observations found for years {years} and months {months}")

    daily_maxima = extract_daily_maxima(pooled_rows, target_timezone=target_timezone)
    sorted_max = sorted([d["daily_max_temperature_c"] for d in daily_maxima])
    n = len(sorted_max)
    if n == 0:
        raise ValueError("No valid daily maxima extracted from pooled observations")

    k = (n - 1) * (percentile / 100.0)
    f = int(k)
    c = f + 1
    if c >= n:
        threshold_val = float(sorted_max[-1])
    else:
        d0 = sorted_max[f] * (c - k)
        d1 = sorted_max[c] * (k - f)
        threshold_val = float(d0 + d1)

    return {
        "station_id": station_id,
        "target_timezone": target_timezone,
        "years": years,
        "months": months,
        "percentile": percentile,
        "percentile_method": "linear_interpolation",
        "sample_size": n,
        "threshold_p90_c": threshold_val,
        "threshold_p90_display_c": round(threshold_val, 2),
        "daily_maxima": daily_maxima,
    }


def detect_heatwave_events(
    daily_maxima: list[dict[str, Any]],
    threshold_p90_c: float,
    *,
    station_id: str = "USW00023234",
    target_timezone: str = "America/Los_Angeles",
    min_consecutive_days: int = 3,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Detect deterministic multi-day heatwave events and construct event catalogue.
    
    Event criteria:
      - Maximal consecutive sequence of >= min_consecutive_days where daily_max > threshold_p90_c.
      - A missing day or daily_max <= threshold_p90_c terminates the run.
      - Peak day: qualifying day with highest daily_max; earliest date breaks ties.
    """
    tz = ZoneInfo(target_timezone)

    # Sort daily maxima chronologically by local_date
    daily_by_date = {d["local_date"]: d for d in daily_maxima}
    all_dates = sorted(daily_by_date.keys())

    # Build date-indexed list to track consecutive calendar days
    # Note: to ensure strict calendar consecuteness, parse to date objects
    parsed_dates = [date.fromisoformat(d) for d in all_dates]

    runs: list[list[dict[str, Any]]] = []
    current_run: list[dict[str, Any]] = []

    for i, curr_d in enumerate(parsed_dates):
        d_str = curr_d.isoformat()
        day_rec = daily_by_date[d_str]
        t_max = day_rec["daily_max_temperature_c"]

        # Strict exceedance check
        is_qualifying = (t_max is not None and t_max > threshold_p90_c)

        if is_qualifying:
            if not current_run:
                current_run.append(day_rec)
            else:
                prev_date = date.fromisoformat(current_run[-1]["local_date"])
                if curr_d == prev_date + timedelta(days=1):
                    current_run.append(day_rec)
                else:
                    # Gap in dates: previous run ends
                    if len(current_run) >= min_consecutive_days:
                        runs.append(current_run)
                    current_run = [day_rec]
        else:
            if len(current_run) >= min_consecutive_days:
                runs.append(current_run)
            current_run = []

    if len(current_run) >= min_consecutive_days:
        runs.append(current_run)

    event_rows: list[dict[str, Any]] = []

    for run in runs:
        start_date_str = run[0]["local_date"]
        end_date_str = run[-1]["local_date"]
        dur_days = len(run)

        # ID: HW_YYYYMMDD
        eid_date = start_date_str.replace("-", "")
        event_id = f"HW_{eid_date}"

        # UTC interval for event: [start_date midnight, (end_date + 1 day) midnight)
        start_utc, _, _ = get_local_day_utc_bounds(start_date_str, target_timezone=target_timezone)
        _, end_utc, _ = get_local_day_utc_bounds(end_date_str, target_timezone=target_timezone)
        total_hours = int(round((end_utc - start_utc).total_seconds() / 3600.0))

        # Peak date and temperature (earliest tie-break)
        sorted_by_temp = sorted(run, key=lambda x: (-x["daily_max_temperature_c"], x["local_date"]))
        peak_rec = sorted_by_temp[0]
        peak_date = peak_rec["local_date"]
        peak_temp = peak_rec["daily_max_temperature_c"]

        temps = [r["daily_max_temperature_c"] for r in run]
        mean_max = float(sum(temps) / len(temps))
        cum_exceed = float(sum(t - threshold_p90_c for t in temps))

        event_rows.append({
            "event_id": event_id,
            "station_id": station_id,
            "timezone": target_timezone,
            "local_start_date": start_date_str,
            "local_end_date": end_date_str,
            "duration_days": dur_days,
            "event_start_utc": start_utc,
            "event_end_utc": end_utc,
            "duration_hours": total_hours,
            "peak_local_date": peak_date,
            "peak_temperature_c": peak_temp,
            "mean_max_temperature_c": mean_max,
            "cumulative_exceedance_c_days": cum_exceed,
            "threshold_p90_c": threshold_p90_c,
        })

    df_events = pd.DataFrame(event_rows, columns=EVENT_CATALOGUE_COLUMNS)
    validate_heatwave_events(
        df_events,
        expected_station=station_id,
        expected_timezone=target_timezone,
        p90_threshold_c=threshold_p90_c,
        min_consecutive_days=min_consecutive_days,
        allow_empty=True,
    )

    return df_events, runs


def build_hourly_phase_labels(
    df_events: pd.DataFrame,
    *,
    target_timezone: str = "America/Los_Angeles",
) -> pd.DataFrame:
    """Build canonical hourly phase labels for all detected heatwave events.
    
    Phases:
      - onset: Full local day immediately preceding local_start_date (T_start - 1 day)
      - peak: All hours of peak_local_date
      - sustained: All other hours of the qualifying event days
      - recovery: Full local day immediately following local_end_date (T_end + 1 day)
      
    Collision Detection:
      - If onset or recovery buffers collide between events, raises ValueError.
      - Each UTC timestamp belongs to at most one event and phase.
    """
    tz = ZoneInfo(target_timezone)
    hourly_records: list[dict[str, Any]] = []

    # Map of timestamp_utc -> (event_id, phase) to detect buffer collisions
    assigned_timestamps: dict[datetime, tuple[str, str]] = {}

    for _, ev in df_events.iterrows():
        eid = str(ev["event_id"])
        station_id = str(ev["station_id"])
        start_date = date.fromisoformat(str(ev["local_start_date"]))
        end_date = date.fromisoformat(str(ev["local_end_date"]))
        peak_date_str = str(ev["peak_local_date"])

        # Determine all days involved: [start_date - 1 day, end_date + 1 day]
        onset_date = start_date - timedelta(days=1)
        recovery_date = end_date + timedelta(days=1)

        # Iterate through calendar dates from onset to recovery inclusive
        curr_d = onset_date
        while curr_d <= recovery_date:
            curr_str = curr_d.isoformat()
            if curr_d == onset_date:
                phase = "onset"
            elif curr_d == recovery_date:
                phase = "recovery"
            elif curr_str == peak_date_str:
                phase = "peak"
            else:
                phase = "sustained"

            # Get exact UTC interval for this local day
            day_start_utc, day_end_utc, _ = get_local_day_utc_bounds(curr_str, target_timezone=target_timezone)

            # Generate top-of-hour timestamps for this day
            cur_ts = day_start_utc
            while cur_ts < day_end_utc:
                # Collision check
                if cur_ts in assigned_timestamps:
                    prev_eid, prev_phase = assigned_timestamps[cur_ts]
                    raise ValueError(
                        f"Phase buffer collision at timestamp {cur_ts.isoformat()}: "
                        f"already assigned to {prev_eid} ({prev_phase}), cannot assign to {eid} ({phase})"
                    )

                assigned_timestamps[cur_ts] = (eid, phase)
                ts_loc = cur_ts.astimezone(tz)
                hourly_records.append({
                    "timestamp_utc": cur_ts,
                    "local_date": curr_str,
                    "hour_local": ts_loc.hour,
                    "event_id": eid,
                    "event_phase": phase,
                    "station_id": station_id,
                })
                cur_ts += timedelta(hours=1)

            curr_d += timedelta(days=1)

    df_labels = pd.DataFrame(hourly_records, columns=HOURLY_EVENT_LABEL_COLUMNS)
    # Sort ascending by timestamp_utc
    df_labels = df_labels.sort_values(by="timestamp_utc").reset_index(drop=True)

    validate_hourly_event_labels(
        df_labels,
        df_events=df_events,
        expected_station=str(df_events["station_id"].iloc[0]),
    )

    return df_labels


def write_event_coverage_csv(
    df_events: pd.DataFrame,
    df_labels: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Generate and write event coverage manifest tracking each event's boundaries and phase counts."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    coverage_rows: list[dict[str, Any]] = []

    for _, ev in df_events.iterrows():
        eid = ev["event_id"]
        ev_labels = df_labels[df_labels["event_id"] == eid]

        onset_hours = len(ev_labels[ev_labels["event_phase"] == "onset"])
        peak_hours = len(ev_labels[ev_labels["event_phase"] == "peak"])
        sustained_hours = len(ev_labels[ev_labels["event_phase"] == "sustained"])
        recovery_hours = len(ev_labels[ev_labels["event_phase"] == "recovery"])
        total_hours = len(ev_labels)

        coverage_rows.append({
            "event_id": eid,
            "station_id": ev["station_id"],
            "timezone": ev["timezone"],
            "local_start_date": ev["local_start_date"],
            "local_end_date": ev["local_end_date"],
            "duration_days": ev["duration_days"],
            "event_start_utc": ev["event_start_utc"].isoformat(),
            "event_end_utc": ev["event_end_utc"].isoformat(),
            "duration_hours": ev["duration_hours"],
            "peak_local_date": ev["peak_local_date"],
            "peak_temperature_c": ev["peak_temperature_c"],
            "mean_max_temperature_c": round(ev["mean_max_temperature_c"], 4),
            "cumulative_exceedance_c_days": round(ev["cumulative_exceedance_c_days"], 4),
            "onset_hours": onset_hours,
            "peak_hours": peak_hours,
            "sustained_hours": sustained_hours,
            "recovery_hours": recovery_hours,
            "total_phase_hours": total_hours,
        })

    fieldnames = list(coverage_rows[0].keys()) if coverage_rows else []
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(coverage_rows)

    return out


def write_event_manifest_json(
    threshold_meta: dict[str, Any],
    df_events: pd.DataFrame,
    df_labels: pd.DataFrame,
    input_files: list[Path | str],
    output_files: dict[str, Path | str],
    manifest_path: Path | str,
) -> Path:
    """Generate and write comprehensive JSON manifest for heatwave catalogue."""
    out = Path(manifest_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    input_meta = {}
    for inp in input_files:
        p = Path(inp)
        if p.exists():
            input_meta[p.name] = {
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

    output_meta = {}
    for k, outp in output_files.items():
        p = Path(outp)
        if p.exists():
            output_meta[k] = {
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

    manifest = {
        "manifest_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "P3",
        "pipeline_step": "P3-01/P3-02",
        "station_id": threshold_meta["station_id"],
        "target_timezone": threshold_meta["target_timezone"],
        "baseline_years": threshold_meta["years"],
        "warm_season_months": threshold_meta["months"],
        "sample_size_days": threshold_meta["sample_size"],
        "percentile": threshold_meta["percentile"],
        "percentile_method": threshold_meta["percentile_method"],
        "threshold_p90_c": threshold_meta["threshold_p90_c"],
        "threshold_p90_display_c": threshold_meta["threshold_p90_display_c"],
        "events_count": len(df_events),
        "total_event_hours": int(df_events["duration_hours"].sum()),
        "total_phase_labeled_hours": len(df_labels),
        "event_ids": df_events["event_id"].tolist(),
        "input_files": input_meta,
        "output_files": output_meta,
    }

    with out.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return out


def build_and_export_events(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
) -> dict[str, Any]:
    """Execute complete Person A P3 pipeline: detect heatwaves, label phases, and export outputs."""
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    sources_cfg = load_yaml(config_dir / "sources.yaml")
    station_id = sources_cfg["qc"]["primary_station_id"]  # USW00023234
    target_timezone = sources_cfg["qc"].get("target_timezone", "America/Los_Angeles")

    years = [2022, 2023, 2024, 2025]
    months = [6, 7, 8, 9]

    input_psv_files = [
        data_dir / f"raw/noaa/GHCNh_{station_id}_{yr}.psv" for yr in years
    ]

    # Compute threshold
    thresh_info = compute_heatwave_percentile_threshold(
        input_psv_files,
        station_id=station_id,
        years=years,
        months=months,
        target_timezone=target_timezone,
        percentile=90.0,
    )

    # Detect events
    df_events, _ = detect_heatwave_events(
        thresh_info["daily_maxima"],
        thresh_info["threshold_p90_c"],
        station_id=station_id,
        target_timezone=target_timezone,
        min_consecutive_days=3,
    )

    # Label hourly phases
    df_labels = build_hourly_phase_labels(
        df_events,
        target_timezone=target_timezone,
    )

    # Define output paths
    events_dir = data_dir / "events"
    manifests_dir = data_dir / "manifests"
    events_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    parquet_events_path = events_dir / "heatwave_events_v0.parquet"
    csv_events_path = events_dir / "heatwave_events_v0.csv"
    parquet_labels_path = events_dir / "hourly_event_labels_v0.parquet"
    csv_labels_sample_path = events_dir / "hourly_event_labels_v0_sample.csv"
    coverage_path = manifests_dir / "event_coverage.csv"
    manifest_path = manifests_dir / "event_catalogue_manifest.json"

    # Export event catalogue
    df_events.to_parquet(parquet_events_path, index=False)
    df_events.to_csv(csv_events_path, index=False)

    # Export hourly labels
    df_labels.to_parquet(parquet_labels_path, index=False)
    # 20 rows head + 20 rows tail sample
    sample_df = pd.concat([df_labels.head(20), df_labels.tail(20)]).drop_duplicates().reset_index(drop=True)
    sample_df.to_csv(csv_labels_sample_path, index=False)

    # Export coverage manifest
    write_event_coverage_csv(df_events, df_labels, coverage_path)

    # Export manifest JSON
    output_files_dict = {
        "heatwave_events_parquet": parquet_events_path,
        "heatwave_events_csv": csv_events_path,
        "hourly_event_labels_parquet": parquet_labels_path,
        "hourly_event_labels_sample_csv": csv_labels_sample_path,
        "event_coverage_csv": coverage_path,
    }
    write_event_manifest_json(
        thresh_info,
        df_events,
        df_labels,
        input_psv_files,
        output_files_dict,
        manifest_path,
    )

    return {
        "threshold_info": thresh_info,
        "events_df": df_events,
        "labels_df": df_labels,
        "parquet_events_path": parquet_events_path,
        "csv_events_path": csv_events_path,
        "parquet_labels_path": parquet_labels_path,
        "sample_csv_path": csv_labels_sample_path,
        "coverage_path": coverage_path,
        "manifest_path": manifest_path,
    }


def inspect_heatwave_events(
    parquet_events_path: Path | str,
    parquet_labels_path: Path | str | None = None,
) -> None:
    """Print human-readable summary of detected heatwave events and phases."""
    path_ev = Path(parquet_events_path)
    if not path_ev.is_file():
        raise FileNotFoundError(f"Heatwave events parquet file not found: {path_ev}")

    df_events = pd.read_parquet(path_ev)
    print("\n========================= HeatTrace P3 Heatwave Catalogue =========================")
    print(f"File: {path_ev}")
    print(f"Total Events Detected: {len(df_events)}")
    print(f"Station:               {df_events['station_id'].iloc[0]}")
    print(f"Timezone:              {df_events['timezone'].iloc[0]}")
    print(f"Threshold (P90):       {df_events['threshold_p90_c'].iloc[0]:.2f}°C")
    print("-----------------------------------------------------------------------------------")
    for _, r in df_events.iterrows():
        print(
            f"Event ID: {r['event_id']:<12} | "
            f"Dates: {r['local_start_date']} to {r['local_end_date']} ({r['duration_days']} days, {r['duration_hours']} hrs) | "
            f"Peak: {r['peak_local_date']} ({r['peak_temperature_c']:.1f}°C) | "
            f"Mean Max: {r['mean_max_temperature_c']:.2f}°C | "
            f"Cum Exceed: {r['cumulative_exceedance_c_days']:.2f}°C-days"
        )
    print("-----------------------------------------------------------------------------------")

    if parquet_labels_path is not None:
        path_lbl = Path(parquet_labels_path)
        if path_lbl.is_file():
            df_lbl = pd.read_parquet(path_lbl)
            print(f"\nHourly Phase Labels: {path_lbl}")
            print(f"Total Labeled Hours: {len(df_lbl)}")
            phase_counts = df_lbl["event_phase"].value_counts().to_dict()
            print("Phase breakdown (hours):")
            for ph in ["onset", "sustained", "peak", "recovery"]:
                print(f"  - {ph:<10}: {phase_counts.get(ph, 0)} hours")
            print("===================================================================================\n")
