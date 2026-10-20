"""Deterministic non-heatwave control matching and validation for HeatTrace P3-05."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.noaa import extract_daily_maxima, get_local_day_utc_bounds, parse_ghcnh_psv
from heattrace.ingest.provenance import sha256_file
from heattrace.process.events import compute_heatwave_percentile_threshold, detect_heatwave_events, load_heatwave_config


CONTROL_CATALOGUE_COLUMNS: list[str] = [
    "control_id",
    "matched_event_id",
    "matching_method",
    "anchor_date",
    "local_start_date",
    "local_end_exclusive",
    "start_timestamp_utc",
    "end_timestamp_utc",
    "duration_days",
    "duration_hours",
    "is_eligible",
    "rejection_reasons",
    "source_coverage_status",
    "mean_max_temperature_c",
    "target_temperature_distance_c",
    "matching_score",
    "configuration_version",
]


def match_deterministic_control(
    event_id: str,
    df_events: pd.DataFrame,
    daily_records: list[dict[str, Any]],
    threshold_p90_c: float,
    *,
    target_year: int = 2024,
    anchor_date: str = "2024-06-07",
    matching_method: str = "ordinary_summer_anchor_distance",
    target_timezone: str = "America/Los_Angeles",
    configuration_version: str = "1.0",
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Deterministically match an eligible non-heatwave control window for an event.
    
    Control criteria:
    - Same duration_days and duration_hours as the event benchmark window (onset to recovery inclusive).
    - Entirely within June–September of target_year.
    - No overlap with any heatwave event, onset, or recovery interval.
    - No missing NOAA daily maxima.
    - No 3-day qualifying heatwave run (daily_max > P90).
    - Anchored around a verified ordinary summer day (e.g. 2024-06-07).
    - Does not match on price, demand, generation, or carbon outcomes.
    - Retains scoring and rejection reasons for all candidate windows.
    """
    ev_matches = df_events[df_events["event_id"] == event_id]
    if ev_matches.empty:
        raise ValueError(f"Event {event_id} not found in event catalogue")
    ev_row = ev_matches.iloc[0]

    # Event benchmark window includes onset (1 day pre) and recovery (1 day post)
    # Total duration = ev_row["duration_days"] + 2
    ev_start_d = date.fromisoformat(str(ev_row["local_start_date"]))
    ev_end_d = date.fromisoformat(str(ev_row["local_end_date"]))
    event_window_start_d = ev_start_d - timedelta(days=1)
    event_window_end_d = ev_end_d + timedelta(days=1)
    window_duration_days = (event_window_end_d - event_window_start_d).days + 1
    window_duration_hours = window_duration_days * 24

    daily_by_date = {d["local_date"]: d for d in daily_records}

    # Blocked dates: all dates in any event, onset, or recovery window
    blocked_dates: set[str] = set()
    for _, ev in df_events.iterrows():
        s = date.fromisoformat(str(ev["local_start_date"])) - timedelta(days=1)
        e = date.fromisoformat(str(ev["local_end_date"])) + timedelta(days=1)
        cur = s
        while cur <= e:
            blocked_dates.add(cur.isoformat())
            cur += timedelta(days=1)

    # Candidate search space: any window of window_duration_days in June-Sept of target_year
    season_start = date(target_year, 6, 1)
    season_end = date(target_year, 9, 30)

    anchor_d = date.fromisoformat(anchor_date)
    anchor_rec = daily_by_date.get(anchor_date)
    target_anchor_temp = anchor_rec["daily_max_temperature_c"] if anchor_rec else 21.7

    candidates: list[dict[str, Any]] = []

    # Slide window from season_start to season_end - window_duration_days + 1
    max_start = season_end - timedelta(days=window_duration_days - 1)
    cur_start = season_start

    while cur_start <= max_start:
        cur_end_inclusive = cur_start + timedelta(days=window_duration_days - 1)
        cur_end_exclusive = cur_end_inclusive + timedelta(days=1)

        window_dates = [cur_start + timedelta(days=i) for i in range(window_duration_days)]
        window_date_strs = [d.isoformat()] if False else [d.isoformat() for d in window_dates]

        rejections: list[str] = []

        # 1. Check overlap with heatwave/buffer dates
        overlap_dates = [ds for ds in window_date_strs if ds in blocked_dates]
        if overlap_dates:
            rejections.append(f"overlaps_heatwave_event_or_buffer: {overlap_dates}")

        # 2. Check missing observations
        missing_obs_dates = [ds for ds in window_date_strs if ds not in daily_by_date or daily_by_date[ds].get("daily_max_temperature_c") is None]
        if missing_obs_dates:
            rejections.append(f"missing_noaa_daily_maxima: {missing_obs_dates}")

        # 3. Check for 3-day consecutive exceedance run inside window
        exceed_run = 0
        has_3day_run = False
        for ds in window_date_strs:
            if ds in daily_by_date and daily_by_date[ds].get("daily_max_temperature_c") is not None:
                if daily_by_date[ds]["daily_max_temperature_c"] > threshold_p90_c:
                    exceed_run += 1
                    if exceed_run >= 3:
                        has_3day_run = True
                else:
                    exceed_run = 0
        if has_3day_run:
            rejections.append("contains_three_day_heatwave_run")

        # 4. Check if anchor_date is contained in window
        contains_anchor = anchor_date in window_date_strs

        # Calculate metrics if no missing observations
        temps = [daily_by_date[ds]["daily_max_temperature_c"] for ds in window_date_strs if ds in daily_by_date and daily_by_date[ds].get("daily_max_temperature_c") is not None]
        mean_max_t = float(sum(temps) / len(temps)) if temps else None

        # Distance from target anchor temperature
        temp_dist = abs(mean_max_t - target_anchor_temp) if mean_max_t is not None else 999.0

        # Anchor distance in calendar days from center of window
        center_d = cur_start + timedelta(days=window_duration_days // 2)
        anchor_day_dist = abs((center_d - anchor_d).days)

        # Primary matching score: 0.0 if centered on anchor date (anchor_day_dist == 0)
        # Weight anchor centration heavily (100.0) so the anchor is the midpoint of the 5-day window
        anchor_penalty = 0.0 if contains_anchor else 1000.0
        score = round(anchor_penalty + anchor_day_dist * 100.0 + temp_dist, 4)

        is_eligible = len(rejections) == 0

        start_utc, _, _ = get_local_day_utc_bounds(cur_start.isoformat(), target_timezone=target_timezone)
        _, end_utc, _ = get_local_day_utc_bounds(cur_end_inclusive.isoformat(), target_timezone=target_timezone)

        candidates.append({
            "local_start_date": cur_start.isoformat(),
            "local_end_inclusive": cur_end_inclusive.isoformat(),
            "local_end_exclusive": cur_end_exclusive.isoformat(),
            "start_timestamp_utc": start_utc,
            "end_timestamp_utc": end_utc,
            "duration_days": window_duration_days,
            "duration_hours": window_duration_hours,
            "contains_anchor": contains_anchor,
            "is_eligible": is_eligible,
            "rejection_reasons": rejections,
            "mean_max_temperature_c": round(mean_max_t, 2) if mean_max_t is not None else None,
            "target_temperature_distance_c": round(temp_dist, 4),
            "matching_score": score,
        })

        cur_start += timedelta(days=1)

    # Filter eligible candidates that contain the approved anchor date
    eligible_anchor_candidates = [c for c in candidates if c["is_eligible"] and c["contains_anchor"]]
    if not eligible_anchor_candidates:
        # Fall back to eligible candidates
        eligible_candidates = [c for c in candidates if c["is_eligible"]]
        if not eligible_candidates:
            raise RuntimeError(f"No eligible non-heatwave control window found in {target_year} for event {event_id}")
        best_candidate = sorted(eligible_candidates, key=lambda c: (c["matching_score"], c["local_start_date"]))[0]
    else:
        best_candidate = sorted(eligible_anchor_candidates, key=lambda c: (c["matching_score"], c["local_start_date"]))[0]

    cid_date = best_candidate["local_start_date"].replace("-", "")
    control_id = f"CTRL_{cid_date}"

    control_record = {
        "control_id": control_id,
        "matched_event_id": event_id,
        "matching_method": matching_method,
        "anchor_date": anchor_date,
        "local_start_date": best_candidate["local_start_date"],
        "local_end_exclusive": best_candidate["local_end_exclusive"],
        "start_timestamp_utc": best_candidate["start_timestamp_utc"],
        "end_timestamp_utc": best_candidate["end_timestamp_utc"],
        "duration_days": best_candidate["duration_days"],
        "duration_hours": best_candidate["duration_hours"],
        "is_eligible": True,
        "rejection_reasons": json.dumps([]),
        "source_coverage_status": "verified_complete",
        "mean_max_temperature_c": best_candidate["mean_max_temperature_c"],
        "target_temperature_distance_c": best_candidate["target_temperature_distance_c"],
        "matching_score": best_candidate["matching_score"],
        "configuration_version": configuration_version,
    }

    df_control = pd.DataFrame([control_record], columns=CONTROL_CATALOGUE_COLUMNS)
    validate_control_dataframe(df_control, expected_event_id=event_id)

    return df_control, candidates


def validate_control_dataframe(
    df_control: pd.DataFrame,
    *,
    expected_event_id: str | None = None,
    expected_duration_hours: int = 120,
) -> None:
    """Validate control catalogue DataFrame according to P3-05 contract."""
    if not isinstance(df_control, pd.DataFrame):
        raise TypeError("df_control must be a pandas DataFrame")

    actual_cols = list(df_control.columns)
    if actual_cols != CONTROL_CATALOGUE_COLUMNS:
        raise ValueError(
            f"Control columns mismatch.\nExpected: {CONTROL_CATALOGUE_COLUMNS}\nActual:   {actual_cols}"
        )

    if df_control.empty:
        raise ValueError("Control catalogue cannot be empty")

    for idx, row in df_control.iterrows():
        cid = str(row["control_id"])
        if not cid.startswith("CTRL_"):
            raise ValueError(f"Control {cid}: must start with CTRL_")

        if expected_event_id is not None and row["matched_event_id"] != expected_event_id:
            raise ValueError(f"Control {cid}: matched_event_id '{row['matched_event_id']}' != expected '{expected_event_id}'")

        dur_days = int(row["duration_days"])
        dur_hours = int(row["duration_hours"])
        if dur_hours != expected_duration_hours:
            raise ValueError(f"Control {cid}: duration_hours {dur_hours} != expected {expected_duration_hours}")
        if dur_hours != dur_days * 24:
            raise ValueError(f"Control {cid}: duration_hours {dur_hours} != duration_days * 24 ({dur_days * 24})")

        t_start = row["start_timestamp_utc"]
        t_end = row["end_timestamp_utc"]
        if not isinstance(t_start, (datetime, pd.Timestamp)) or t_start.tzinfo is None:
            raise ValueError(f"Control {cid}: start_timestamp_utc must be timezone-aware UTC datetime")
        if not isinstance(t_end, (datetime, pd.Timestamp)) or t_end.tzinfo is None:
            raise ValueError(f"Control {cid}: end_timestamp_utc must be timezone-aware UTC datetime")
        if t_start >= t_end:
            raise ValueError(f"Control {cid}: start_timestamp_utc ({t_start}) >= end_timestamp_utc ({t_end})")
        if bool(row["is_eligible"]) is not True:
            raise ValueError(f"Control {cid}: is_eligible must be True")


def build_and_export_controls(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
    event_id: str = "HW_20240702",
    anchor_date: str = "2024-06-07",
) -> dict[str, Any]:
    """Execute complete P3-05 control window matching and export outputs."""
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    hw_cfg = load_heatwave_config(config_dir=config_dir)
    station_id = hw_cfg["station_id"]
    target_timezone = hw_cfg["target_timezone"]
    years = hw_cfg["years"]

    input_psv_files = [data_dir / f"raw/noaa/GHCNh_{station_id}_{yr}.psv" for yr in years]
    thresh_info = compute_heatwave_percentile_threshold(
        input_psv_files,
        station_id=station_id,
        years=years,
        months=hw_cfg["months"],
        target_timezone=target_timezone,
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
    )

    df_events, _ = detect_heatwave_events(
        thresh_info["daily_maxima"],
        thresh_info["threshold_p90_c"],
        station_id=station_id,
        target_timezone=target_timezone,
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
        min_consecutive_days=hw_cfg["min_consecutive_days"],
    )

    df_control, candidates = match_deterministic_control(
        event_id=event_id,
        df_events=df_events,
        daily_records=thresh_info["daily_maxima"],
        threshold_p90_c=thresh_info["threshold_p90_c"],
        target_year=2024,
        anchor_date=anchor_date,
        target_timezone=target_timezone,
    )

    events_dir = data_dir / "events"
    manifests_dir = data_dir / "manifests"
    events_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = events_dir / "control_catalogue_v0.parquet"
    csv_path = events_dir / "control_catalogue_v0.csv"
    audit_json_path = manifests_dir / "control_matching_audit.json"

    df_control.to_parquet(parquet_path, index=False)
    df_control.to_csv(csv_path, index=False)

    audit_meta = {
        "matched_event_id": event_id,
        "selected_control_id": str(df_control["control_id"].iloc[0]),
        "anchor_date": anchor_date,
        "local_start_date": str(df_control["local_start_date"].iloc[0]),
        "local_end_exclusive": str(df_control["local_end_exclusive"].iloc[0]),
        "duration_hours": int(df_control["duration_hours"].iloc[0]),
        "candidates_evaluated": len(candidates),
        "eligible_candidates_count": sum(1 for c in candidates if c["is_eligible"]),
        "rejected_candidates_count": sum(1 for c in candidates if not c["is_eligible"]),
        "matching_method": "ordinary_summer_anchor_distance",
        "output_files": {
            "control_catalogue_parquet": str(parquet_path),
            "control_catalogue_csv": str(csv_path),
        },
    }

    with audit_json_path.open("w", encoding="utf-8") as f:
        json.dump(audit_meta, f, indent=2, sort_keys=True)

    return {
        "df_control": df_control,
        "candidates": candidates,
        "parquet_path": parquet_path,
        "csv_path": csv_path,
        "audit_path": audit_json_path,
    }
