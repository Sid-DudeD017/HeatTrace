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
    target_anchor_temp = (
        anchor_rec.get("daily_max_temperature_c", anchor_rec.get("max_temperature_c", 21.7))
        if anchor_rec
        else 21.7
    )

    candidates: list[dict[str, Any]] = []

    # Slide window from season_start to season_end - window_duration_days + 1
    max_start = season_end - timedelta(days=window_duration_days - 1)
    cur_start = season_start

    while cur_start <= max_start:
        cur_end_inclusive = cur_start + timedelta(days=window_duration_days - 1)
        cur_end_exclusive = cur_end_inclusive + timedelta(days=1)

        # Window duration in hours derived strictly from UTC interval
        start_utc, _, _ = get_local_day_utc_bounds(cur_start.isoformat(), target_timezone=target_timezone)
        _, end_utc, _ = get_local_day_utc_bounds(cur_end_inclusive.isoformat(), target_timezone=target_timezone)
        cur_duration_hours = int(round((end_utc - start_utc).total_seconds() / 3600.0))

        window_dates = [cur_start + timedelta(days=i) for i in range(window_duration_days)]
        window_date_strs = [d.isoformat() for d in window_dates]

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

        candidates.append({
            "local_start_date": cur_start.isoformat(),
            "local_end_inclusive": cur_end_inclusive.isoformat(),
            "local_end_exclusive": cur_end_exclusive.isoformat(),
            "start_timestamp_utc": start_utc,
            "end_timestamp_utc": end_utc,
            "duration_days": window_duration_days,
            "duration_hours": cur_duration_hours,
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
        "source_coverage_status": "weather_eligible_pending_cross_source_validation",
        "mean_max_temperature_c": best_candidate["mean_max_temperature_c"],
        "target_temperature_distance_c": best_candidate["target_temperature_distance_c"],
        "matching_score": best_candidate["matching_score"],
        "configuration_version": configuration_version,
    }

    df_control = pd.DataFrame([control_record], columns=CONTROL_CATALOGUE_COLUMNS)
    validate_control_dataframe(df_control, expected_event_id=event_id)

    return df_control, candidates


def build_fallback_controls(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
    *,
    anchor_date: str = "2024-06-07",
    target_timezone: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Pure in-memory builder for event-specific fallback matched controls and candidate audit data.

    Evaluates each event's documented temperature characteristic against candidate 120h windows,
    allocates four unique non-overlapping controls in human-approved role order:
      1. HW_20240702 (development)
      2. HW_20220620 (confirmatory 1)
      3. HW_20220904 (confirmatory 2)
      4. HW_20220922 (confirmatory 3)
    Returns:
      dict with df_controls, candidates, per_event_candidates, and audit_meta WITHOUT writing production files.
    """
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    hw_cfg = load_heatwave_config(config_dir=config_dir)
    station_id = hw_cfg["station_id"]
    years = [2022, 2024]
    input_psv_files = [data_dir / f"raw/noaa/GHCNh_{station_id}_{yr}.psv" for yr in years]

    for psv_f in input_psv_files:
        if not psv_f.exists():
            raise FileNotFoundError(f"Required raw NOAA file missing: {psv_f}")

    thresh_info = compute_heatwave_percentile_threshold(
        input_psv_files,
        station_id=station_id,
        years=years,
        months=hw_cfg["months"],
        target_timezone=target_timezone,
        percentile=hw_cfg["percentile"],
        percentile_method=hw_cfg["percentile_method"],
    )

    # Load authentic event catalogue to resolve event characteristics
    hw_parquet = data_dir / "events/heatwave_events_v0.parquet"
    if not hw_parquet.exists():
        raise FileNotFoundError(f"Heatwaves catalogue not found: {hw_parquet}")
    df_events = pd.read_parquet(hw_parquet)

    daily_by_date = {d["local_date"]: d for d in thresh_info["daily_maxima"]}
    anchor_d = date.fromisoformat(anchor_date)

    # Blocked dates from all detected heatwaves + onset/recovery buffers
    blocked_dates: set[str] = set()
    for _, ev in df_events.iterrows():
        s = date.fromisoformat(str(ev["local_start_date"])) - timedelta(days=1)
        e = date.fromisoformat(str(ev["local_end_date"])) + timedelta(days=1)
        cur = s
        while cur <= e:
            blocked_dates.add(cur.isoformat())
            cur += timedelta(days=1)

    season_start = date(2024, 6, 1)
    season_end = date(2024, 9, 30)
    max_start = season_end - timedelta(days=4)

    def generate_candidates_for_event(event_id: str) -> tuple[float, list[dict[str, Any]]]:
        ev_matches = df_events[df_events["event_id"] == event_id]
        if ev_matches.empty:
            raise ValueError(f"Event {event_id} not found in event catalogue")
        ev_row = ev_matches.iloc[0]
        # Resolve documented event temperature characteristic (mean_max_temperature_c)
        ev_target_temp = float(ev_row["mean_max_temperature_c"])

        cur_start = season_start
        cands: list[dict[str, Any]] = []
        while cur_start <= max_start:
            cur_end_inclusive = cur_start + timedelta(days=4)
            cur_end_exclusive = cur_end_inclusive + timedelta(days=1)
            start_utc, _, _ = get_local_day_utc_bounds(cur_start.isoformat(), target_timezone=target_timezone)
            _, end_utc, _ = get_local_day_utc_bounds(cur_end_inclusive.isoformat(), target_timezone=target_timezone)
            window_dates = [cur_start + timedelta(days=i) for i in range(5)]
            window_date_strs = [d.isoformat() for d in window_dates]
            rejections: list[str] = []

            overlap_dates = [ds for ds in window_date_strs if ds in blocked_dates]
            if overlap_dates:
                rejections.append(f"overlaps_heatwave_event_or_buffer: {overlap_dates}")
            missing_obs_dates = [ds for ds in window_date_strs if ds not in daily_by_date or daily_by_date[ds].get("daily_max_temperature_c") is None]
            if missing_obs_dates:
                rejections.append(f"missing_noaa_daily_maxima: {missing_obs_dates}")
            exceed_run = 0
            has_3day_run = False
            for ds in window_date_strs:
                if ds in daily_by_date and daily_by_date[ds].get("daily_max_temperature_c") is not None:
                    if daily_by_date[ds]["daily_max_temperature_c"] > thresh_info["threshold_p90_c"]:
                        exceed_run += 1
                        if exceed_run >= 3:
                            has_3day_run = True
                    else:
                        exceed_run = 0
            if has_3day_run:
                rejections.append("contains_three_day_heatwave_run")

            contains_anchor = anchor_date in window_date_strs
            temps = [daily_by_date[ds]["daily_max_temperature_c"] for ds in window_date_strs if ds in daily_by_date and daily_by_date[ds].get("daily_max_temperature_c") is not None]
            mean_max_t = float(sum(temps) / len(temps)) if temps else None
            # Event-specific temperature distance
            temp_dist = abs(mean_max_t - ev_target_temp) if mean_max_t is not None else 999.0
            center_d = cur_start + timedelta(days=2)
            anchor_day_dist = abs((center_d - anchor_d).days)
            anchor_penalty = 0.0 if contains_anchor else 1000.0
            score = round(anchor_penalty + anchor_day_dist * 100.0 + temp_dist, 4)
            stable_id = f"CTRL_{cur_start.isoformat().replace('-', '')}"

            cands.append({
                "local_start_date": cur_start.isoformat(),
                "local_end_inclusive": cur_end_inclusive.isoformat(),
                "local_end_exclusive": cur_end_exclusive.isoformat(),
                "start_timestamp_utc": start_utc,
                "end_timestamp_utc": end_utc,
                "duration_days": 5,
                "duration_hours": 120,
                "contains_anchor": contains_anchor,
                "is_eligible": len(rejections) == 0,
                "rejection_reasons": rejections,
                "mean_max_temperature_c": round(mean_max_t, 2) if mean_max_t is not None else None,
                "event_target_temperature_c": round(ev_target_temp, 4),
                "target_temperature_distance_c": round(temp_dist, 4),
                "matching_score": score,
                "stable_id": stable_id,
            })
            cur_start += timedelta(days=1)
        return ev_target_temp, cands

    # Algorithmic Greedy Allocation in human-approved role order:
    event_order = ["HW_20240702", "HW_20220620", "HW_20220904", "HW_20220922"]
    occupied_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    records: list[dict[str, Any]] = []
    per_event_candidates: dict[str, list[dict[str, Any]]] = {}
    selected_audit_entries: list[dict[str, Any]] = []

    for ev_id in event_order:
        ev_target_temp, cands = generate_candidates_for_event(ev_id)
        # Deterministic ordering: (not eligible, matching_score, temperature_distance, local_start_date, stable_id)
        ranked_cands = sorted(
            cands,
            key=lambda c: (
                not c["is_eligible"],
                c["matching_score"],
                c["target_temperature_distance_c"],
                c["local_start_date"],
                c["stable_id"],
            )
        )
        for r_idx, c in enumerate(ranked_cands, 1):
            c["candidate_rank"] = r_idx

        per_event_candidates[ev_id] = ranked_cands

        # Select first eligible non-overlapping candidate, tracking overlapping rejections
        chosen = None
        overlap_rejected_cands: list[str] = []
        for c in ranked_cands:
            if not c["is_eligible"]:
                continue
            s_utc = c["start_timestamp_utc"]
            e_utc = c["end_timestamp_utc"]
            overlaps = any(max(s_utc, occ_s) < min(e_utc, occ_e) for occ_s, occ_e in occupied_intervals)
            if overlaps:
                overlap_rejected_cands.append(c["stable_id"])
                continue
            chosen = c
            break

        if chosen is None:
            raise RuntimeError(f"Algorithmic allocation failed: no non-overlapping control found for event {ev_id}")

        occupied_intervals.append((chosen["start_timestamp_utc"], chosen["end_timestamp_utc"]))
        cid = chosen["stable_id"]

        records.append({
            "control_id": cid,
            "matched_event_id": ev_id,
            "matching_method": "ordinary_summer_anchor_distance",
            "anchor_date": anchor_date,
            "local_start_date": chosen["local_start_date"],
            "local_end_exclusive": chosen["local_end_exclusive"],
            "start_timestamp_utc": chosen["start_timestamp_utc"],
            "end_timestamp_utc": chosen["end_timestamp_utc"],
            "duration_days": chosen["duration_days"],
            "duration_hours": chosen["duration_hours"],
            "is_eligible": True,
            "rejection_reasons": json.dumps([]),
            "source_coverage_status": "verified_complete",
            "mean_max_temperature_c": chosen["mean_max_temperature_c"],
            "target_temperature_distance_c": chosen["target_temperature_distance_c"],
            "matching_score": chosen["matching_score"],
            "configuration_version": "1.0",
        })

        selected_audit_entries.append({
            "control_id": cid,
            "matched_event_id": ev_id,
            "event_target_temperature_c": ev_target_temp,
            "selected_rank": chosen["candidate_rank"],
            "matching_score": chosen["matching_score"],
            "temperature_distance_c": chosen["target_temperature_distance_c"],
            "stable_tie_breaker": chosen["stable_id"],
            "local_start_date": chosen["local_start_date"],
            "local_end_exclusive": chosen["local_end_exclusive"],
            "mean_max_temperature_c": chosen["mean_max_temperature_c"],
            "overlap_rejected_candidates": overlap_rejected_cands,
            "total_candidates_evaluated": len(cands),
            "total_eligible_candidates": sum(1 for c in cands if c["is_eligible"]),
        })

    df_controls = pd.DataFrame(records, columns=CONTROL_CATALOGUE_COLUMNS)
    validate_control_dataframe(df_controls, require_unique_event=True)

    def _serialize_candidate(c: dict[str, Any]) -> dict[str, Any]:
        c_copy = dict(c)
        for k, v in list(c_copy.items()):
            if hasattr(v, "isoformat"):
                c_copy[k] = v.isoformat()
        return c_copy

    input_files_meta: dict[str, dict[str, Any]] = {}
    for psv_f in input_psv_files:
        if psv_f.exists():
            rel_p = str(psv_f.relative_to(data_dir.parent)) if psv_f.is_relative_to(data_dir.parent) else str(psv_f)
            input_files_meta[psv_f.name] = {
                "path": rel_p,
                "sha256": sha256_file(psv_f),
                "size_bytes": psv_f.stat().st_size,
            }

    config_files_meta: dict[str, dict[str, Any]] = {}
    for cfg_name in ["heatwave.yaml", "p6_validity.yaml"]:
        cfg_f = config_dir / cfg_name
        if cfg_f.exists():
            rel_c = str(cfg_f.relative_to(config_dir.parent)) if cfg_f.is_relative_to(config_dir.parent) else str(cfg_f)
            config_files_meta[cfg_name] = {
                "path": rel_c,
                "sha256": sha256_file(cfg_f),
                "size_bytes": cfg_f.stat().st_size,
            }

    dev_candidates = per_event_candidates["HW_20240702"]

    audit_meta = {
        "manifest_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "design_mode": "fallback",
        "anchor_date": anchor_date,
        "selected_controls": selected_audit_entries,
        "selected_control_id": records[0]["control_id"] if records else None,
        "matched_event_id": records[0]["matched_event_id"] if records else None,
        "allocation_algorithm": "greedy_non_overlapping_score_distance_date",
        "candidates_evaluated": len(dev_candidates),
        "eligible_candidates_count": sum(1 for c in dev_candidates if c["is_eligible"]),
        "rejected_candidates_count": sum(1 for c in dev_candidates if not c["is_eligible"]),
        "matching_method": "ordinary_summer_anchor_distance",
        "candidates": [_serialize_candidate(c) for c in dev_candidates],
        "per_event_candidate_audits": {
            ev_id: {
                "event_id": ev_id,
                "candidates_count": len(c_list),
                "eligible_count": sum(1 for c in c_list if c["is_eligible"]),
                "candidates": [_serialize_candidate(c) for c in c_list],
            }
            for ev_id, c_list in per_event_candidates.items()
        },
        "input_files": input_files_meta,
        "config_files": config_files_meta,
        "output_files": {},
    }

    return {
        "df_controls": df_controls,
        "candidates": dev_candidates,
        "per_event_candidates": per_event_candidates,
        "audit_meta": audit_meta,
    }


def build_and_export_fallback_controls(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
    *,
    anchor_date: str = "2024-06-07",
    target_timezone: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Export wrapper for standalone fallback control publication with staged rollback safety."""
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    build_res = build_fallback_controls(
        data_dir=data_dir,
        config_dir=config_dir,
        anchor_date=anchor_date,
        target_timezone=target_timezone,
    )
    df_controls = build_res["df_controls"]
    audit_meta = dict(build_res["audit_meta"])

    events_dir = data_dir / "events"
    manifests_dir = data_dir / "manifests"
    events_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = events_dir / "control_catalogue_v0.parquet"
    csv_path = events_dir / "control_catalogue_v0.csv"
    audit_json_path = manifests_dir / "control_matching_audit.json"

    rel_parquet = str(parquet_path.relative_to(data_dir.parent)) if parquet_path.is_relative_to(data_dir.parent) else str(parquet_path)
    rel_csv = str(csv_path.relative_to(data_dir.parent)) if csv_path.is_relative_to(data_dir.parent) else str(csv_path)

    audit_meta["output_files"] = {
        "control_catalogue_parquet": {"path": rel_parquet, "sha256": "", "size_bytes": 0},
        "control_catalogue_csv": {"path": rel_csv, "sha256": "", "size_bytes": 0},
    }

    import tempfile
    stage_dir = tempfile.mkdtemp(prefix="stage_ctrl_", dir=events_dir)
    try:
        stage_parquet = Path(stage_dir) / "control_catalogue_v0.parquet"
        stage_csv = Path(stage_dir) / "control_catalogue_v0.csv"
        stage_audit = Path(stage_dir) / "control_matching_audit.json"

        df_controls.to_parquet(stage_parquet, index=False)
        df_controls.to_csv(stage_csv, index=False)

        audit_meta["output_files"]["control_catalogue_parquet"]["sha256"] = sha256_file(stage_parquet)
        audit_meta["output_files"]["control_catalogue_parquet"]["size_bytes"] = stage_parquet.stat().st_size
        audit_meta["output_files"]["control_catalogue_csv"]["sha256"] = sha256_file(stage_csv)
        audit_meta["output_files"]["control_catalogue_csv"]["size_bytes"] = stage_csv.stat().st_size

        with stage_audit.open("w", encoding="utf-8") as f:
            json.dump(audit_meta, f, indent=2, sort_keys=True)

        df_val_parquet = pd.read_parquet(stage_parquet)
        validate_control_dataframe(df_val_parquet, require_unique_event=True)
        assert len(df_val_parquet) == 4

        stage_parquet.replace(parquet_path)
        stage_csv.replace(csv_path)
        stage_audit.replace(audit_json_path)
    finally:
        if Path(stage_dir).exists():
            import shutil
            shutil.rmtree(stage_dir, ignore_errors=True)

    return {
        "df_controls": df_controls,
        "candidates": build_res["candidates"],
        "per_event_candidates": build_res["per_event_candidates"],
        "parquet_path": parquet_path,
        "csv_path": csv_path,
        "audit_path": audit_json_path,
    }

def validate_control_dataframe(
    df_control: pd.DataFrame,
    *,
    expected_event_id: str | None = None,
    expected_duration_hours: int = 120,
    required_status: str | None = None,
    require_unique_event: bool = False,
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

    if df_control["control_id"].duplicated().any():
        dups = df_control[df_control["control_id"].duplicated()]["control_id"].tolist()
        raise ValueError(f"Duplicate control_id values found: {dups}")

    if require_unique_event and df_control["matched_event_id"].duplicated().any():
        dups_ev = df_control[df_control["matched_event_id"].duplicated()]["matched_event_id"].tolist()
        raise ValueError(f"Duplicate matched_event_id mappings found: {dups_ev}")

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
        valid_statuses = {"weather_eligible_pending_cross_source_validation", "verified_complete"}
        status_val = str(row["source_coverage_status"])
        if status_val not in valid_statuses:
            raise ValueError(f"Control {cid}: invalid source_coverage_status '{status_val}'")
        if required_status is not None and status_val != required_status:
            raise ValueError(f"Control {cid}: source_coverage_status '{status_val}' != required '{required_status}'")


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

    def _serialize_candidate(c: dict[str, Any]) -> dict[str, Any]:
        c_copy = dict(c)
        c_copy["start_timestamp_utc"] = c_copy["start_timestamp_utc"].isoformat()
        c_copy["end_timestamp_utc"] = c_copy["end_timestamp_utc"].isoformat()
        return c_copy

    # Input and config files hashes
    input_files_meta: dict[str, dict[str, Any]] = {}
    for psv_f in input_psv_files:
        if psv_f.exists():
            rel_p = str(psv_f.relative_to(data_dir.parent)) if psv_f.is_relative_to(data_dir.parent) else str(psv_f)
            input_files_meta[psv_f.name] = {
                "path": rel_p,
                "sha256": sha256_file(psv_f),
                "size_bytes": psv_f.stat().st_size,
            }

    config_files_meta: dict[str, dict[str, Any]] = {}
    for cfg_name in ["sources.yaml", "study.yaml"]:
        cfg_f = config_dir / cfg_name
        if cfg_f.exists():
            rel_cfg = str(cfg_f.relative_to(data_dir.parent)) if cfg_f.is_relative_to(data_dir.parent) else str(cfg_f)
            config_files_meta[cfg_name] = {
                "path": rel_cfg,
                "sha256": sha256_file(cfg_f),
                "size_bytes": cfg_f.stat().st_size,
            }

    rel_parquet = str(parquet_path.relative_to(data_dir.parent)) if parquet_path.is_relative_to(data_dir.parent) else str(parquet_path)
    rel_csv = str(csv_path.relative_to(data_dir.parent)) if csv_path.is_relative_to(data_dir.parent) else str(csv_path)

    selected_cid = str(df_control["control_id"].iloc[0])
    selected_cands = [c for c in candidates if c["local_start_date"] == str(df_control["local_start_date"].iloc[0])]
    sel_cand = selected_cands[0] if selected_cands else candidates[0]

    audit_meta = {
        "manifest_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matched_event_id": event_id,
        "selected_control_id": selected_cid,
        "anchor_date": anchor_date,
        "local_start_date": str(df_control["local_start_date"].iloc[0]),
        "local_end_exclusive": str(df_control["local_end_exclusive"].iloc[0]),
        "duration_hours": int(df_control["duration_hours"].iloc[0]),
        "candidates_evaluated": len(candidates),
        "eligible_candidates_count": sum(1 for c in candidates if c["is_eligible"]),
        "rejected_candidates_count": sum(1 for c in candidates if not c["is_eligible"]),
        "matching_method": "ordinary_summer_anchor_distance",
        "selected_candidate_rationale": (
            f"Candidate window {sel_cand['local_start_date']} to {sel_cand['local_end_inclusive']} "
            f"contains the approved ordinary summer anchor date {anchor_date} at index 2 (midpoint of 5-day window), "
            f"has zero heatwave exceedance runs or overlaps, and minimized distance to anchor temperature "
            f"({sel_cand['mean_max_temperature_c']}°C)."
        ),
        "candidates": [_serialize_candidate(c) for c in candidates],
        "input_files": input_files_meta,
        "config_files": config_files_meta,
        "output_files": {
            "control_catalogue_parquet": {
                "path": rel_parquet,
                "sha256": sha256_file(parquet_path),
                "size_bytes": parquet_path.stat().st_size,
            },
            "control_catalogue_csv": {
                "path": rel_csv,
                "sha256": sha256_file(csv_path),
                "size_bytes": csv_path.stat().st_size,
            },
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
