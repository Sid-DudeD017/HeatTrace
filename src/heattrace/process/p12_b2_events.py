"""Track B2 Phase 3 multi-station heatwave event detection and regional-episode catalogue.

Strictly weather-only:
- Station-specific empirical June-September P90 baseline from 2022-2025.
- Multi-day heatwave detection (Tmax > P90 for >= 3 consecutive local days).
- Phase labeling (onset, peak, sustained, recovery).
- Deterministic B2 station event identities (B2_HW_<STATION_CODE>_<YYYYMMDD>).
- Deterministic regional episode clustering (transitive connected components via 24h UTC expansion).
- Frozen eligibility classification (2022 joint-ineligible, SFO 2025 excluded, 2026 provisional).
- Zero imputation / zero interpolation.
- Closed to price, carbon, scheduler, or policy outcome data.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from heattrace.ingest.noaa import (
    extract_daily_maxima,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
)
from heattrace.ingest.provenance import sha256_file

# Primary candidate stations approved for Track B2
PRIMARY_STATIONS = [
    {
        "station_code": "SFO",
        "official_station_name": "SAN FRANCISCO INTL AP",
        "noaa_ghcnh_id": "USW00023234",
        "climate_class": "northern coastal",
        "caiso_proxy_hub": "TH_NP15_GEN-APND",
    },
    {
        "station_code": "SAC",
        "official_station_name": "SACRAMENTO AP ASOS",
        "noaa_ghcnh_id": "USW00023232",
        "climate_class": "northern inland",
        "caiso_proxy_hub": "TH_NP15_GEN-APND",
    },
    {
        "station_code": "FAT",
        "official_station_name": "FRESNO YOSEMITE INTL",
        "noaa_ghcnh_id": "USW00093193",
        "climate_class": "central inland",
        "caiso_proxy_hub": "TH_ZP26_GEN-APND",
    },
    {
        "station_code": "RDD",
        "official_station_name": "REDDING AP",
        "noaa_ghcnh_id": "USW00024257",
        "climate_class": "far-northern inland",
        "caiso_proxy_hub": "TH_NP15_GEN-APND",
    },
    {
        "station_code": "LAX",
        "official_station_name": "LOS ANGELES INTL AP",
        "noaa_ghcnh_id": "USW00023174",
        "climate_class": "southern coastal",
        "caiso_proxy_hub": "TH_SP15_GEN-APND",
    },
]

INACTIVE_FALLBACK = {
    "station_code": "SAC_FALLBACK",
    "official_station_name": "SACRAMENTO METRO AP",
    "noaa_ghcnh_id": "USW00093225",
    "climate_class": "northern inland fallback",
    "caiso_proxy_hub": "TH_NP15_GEN-APND",
    "status": "inactive_audit_only",
    "reason": "Primary SAC passed Phase 2 gate; fallback activation trigger not met",
}

BASELINE_YEARS = [2022, 2023, 2024, 2025]
WARM_SEASON_MONTHS = [6, 7, 8, 9]
TARGET_TIMEZONE = "America/Los_Angeles"
DEFAULT_RAW_NOAA_DIR = Path("data/v2/raw/noaa")


def compute_station_p90_threshold(
    noaa_dir: Path | str,
    noaa_ghcnh_id: str,
    station_code: str,
    *,
    baseline_years: list[int] | None = None,
    months: list[int] | None = None,
    target_timezone: str = TARGET_TIMEZONE,
    percentile: float = 90.0,
) -> dict[str, Any]:
    """Compute empirical P90 threshold using valid daily maxima from baseline years."""
    if baseline_years is None:
        baseline_years = BASELINE_YEARS
    if months is None:
        months = WARM_SEASON_MONTHS

    noaa_dir = Path(noaa_dir)
    tz = ZoneInfo(target_timezone)
    pooled_rows: list[dict[str, Any]] = []
    source_files: list[str] = []

    # Calculate expected days
    expected_days = 0
    all_expected_dates: set[str] = set()
    for y in baseline_years:
        cur_d = date(y, months[0], 1)
        end_d = date(y, months[-1], 30)
        while cur_d <= end_d:
            if cur_d.month in months:
                all_expected_dates.add(cur_d.isoformat())
                expected_days += 1
            cur_d += timedelta(days=1)

    for y in baseline_years:
        psv_file = noaa_dir / f"GHCNh_{noaa_ghcnh_id}_{y}.psv"
        if not psv_file.is_file():
            raise FileNotFoundError(f"Missing baseline NOAA raw file: {psv_file}")
        source_files.append(str(psv_file))
        raw_rows = parse_ghcnh_psv(psv_file)
        for r in raw_rows:
            ts_loc = r["timestamp_utc"].astimezone(tz)
            if ts_loc.year == y and ts_loc.month in months:
                pooled_rows.append(r)

    if not pooled_rows:
        raise ValueError(f"No weather observations found for {station_code} in baseline {baseline_years}")

    daily_maxima = extract_daily_maxima(pooled_rows, target_timezone=target_timezone)
    daily_by_date = {d["local_date"]: d for d in daily_maxima}

    valid_dates = set(daily_by_date.keys())
    missing_dates = sorted(list(all_expected_dates - valid_dates))

    sorted_max = sorted([d["daily_max_temperature_c"] for d in daily_maxima if d["daily_max_temperature_c"] is not None])
    n = len(sorted_max)
    if n == 0:
        raise ValueError(f"No valid daily maxima extracted for {station_code}")

    # Empirical percentile with linear interpolation
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
        "station_code": station_code,
        "noaa_ghcnh_id": noaa_ghcnh_id,
        "target_timezone": target_timezone,
        "baseline_years": baseline_years,
        "baseline_months": months,
        "percentile": percentile,
        "percentile_method": "linear_interpolation",
        "expected_baseline_days": expected_days,
        "valid_baseline_days": n,
        "missing_baseline_days": len(missing_dates),
        "missing_dates": missing_dates,
        "sample_size": n,
        "threshold_p90_c": threshold_val,
        "threshold_p90_display_c": round(threshold_val, 4),
        "min_daily_max_c": float(sorted_max[0]),
        "max_daily_max_c": float(sorted_max[-1]),
        "source_files": source_files,
        "daily_maxima_baseline": daily_maxima,
    }


def detect_b2_station_events(
    daily_maxima: list[dict[str, Any]],
    station_meta: dict[str, Any],
    threshold_info: dict[str, Any],
    year: int,
    source_psv_path: str,
    *,
    min_consecutive_days: int = 3,
    target_timezone: str = TARGET_TIMEZONE,
) -> list[dict[str, Any]]:
    """Detect strict multi-day heatwaves for a single station-year."""
    station_code = station_meta["station_code"]
    ghcnh_id = station_meta["noaa_ghcnh_id"]
    thresh_c = threshold_info["threshold_p90_c"]

    # Filter daily maxima to requested year and JJAS months
    daily_by_date = {
        d["local_date"]: d
        for d in daily_maxima
        if date.fromisoformat(d["local_date"]).year == year
        and date.fromisoformat(d["local_date"]).month in WARM_SEASON_MONTHS
    }
    sorted_dates = sorted(daily_by_date.keys())
    parsed_dates = [date.fromisoformat(d) for d in sorted_dates]

    runs: list[list[dict[str, Any]]] = []
    current_run: list[dict[str, Any]] = []

    for curr_d in parsed_dates:
        d_str = curr_d.isoformat()
        day_rec = daily_by_date[d_str]
        t_max = day_rec["daily_max_temperature_c"]

        # Strict exceedance: Tmax > P90
        is_qualifying = (t_max is not None and t_max > thresh_c)

        if is_qualifying:
            if not current_run:
                current_run.append(day_rec)
            else:
                prev_date = date.fromisoformat(current_run[-1]["local_date"])
                if curr_d == prev_date + timedelta(days=1):
                    current_run.append(day_rec)
                else:
                    if len(current_run) >= min_consecutive_days:
                        runs.append(current_run)
                    current_run = [day_rec]
        else:
            if len(current_run) >= min_consecutive_days:
                runs.append(current_run)
            current_run = []

    if len(current_run) >= min_consecutive_days:
        runs.append(current_run)

    event_records: list[dict[str, Any]] = []

    for run in runs:
        start_date_str = run[0]["local_date"]
        end_date_str = run[-1]["local_date"]
        dur_days = len(run)

        # Deterministic B2 event ID: B2_HW_<STATION_CODE>_<YYYYMMDD>
        eid_date = start_date_str.replace("-", "")
        event_id = f"B2_HW_{station_code}_{eid_date}"

        # Event start and end UTC bounds
        start_utc, _, _ = get_local_day_utc_bounds(start_date_str, target_timezone=target_timezone)
        _, end_utc, _ = get_local_day_utc_bounds(end_date_str, target_timezone=target_timezone)
        duration_hours = int(round((end_utc - start_utc).total_seconds() / 3600.0))

        # Peak date: maximum daily max; tie broken by earliest date
        sorted_by_temp = sorted(run, key=lambda x: (-x["daily_max_temperature_c"], x["local_date"]))
        peak_rec = sorted_by_temp[0]
        peak_date = peak_rec["local_date"]
        peak_temp = float(peak_rec["daily_max_temperature_c"])

        temps = [float(r["daily_max_temperature_c"]) for r in run]
        mean_max = float(sum(temps) / len(temps))
        cum_exceed = float(sum(t - thresh_c for t in temps))

        # Full window bounds including 1 local day onset and 1 local day recovery
        onset_date_str = (date.fromisoformat(start_date_str) - timedelta(days=1)).isoformat()
        recovery_date_str = (date.fromisoformat(end_date_str) + timedelta(days=1)).isoformat()

        onset_start_utc, _, _ = get_local_day_utc_bounds(onset_date_str, target_timezone=target_timezone)
        _, recovery_end_utc, _ = get_local_day_utc_bounds(recovery_date_str, target_timezone=target_timezone)

        # Eligibility flags
        is_provisional = (year == 2026)
        weather_eligibility = "PROVISIONAL" if is_provisional else "PASS"
        if year == 2022:
            joint_eval_eligibility = "EXCLUDED"
            exclusion_reason = "EIA 2022 balancing authority carbon data excluded due to missing 2022-06-13 17:00 UTC interval at federal source"
        elif is_provisional:
            joint_eval_eligibility = "PROVISIONAL"
            exclusion_reason = "2026 data provisional pending full calendar certification"
        else:
            joint_eval_eligibility = "ELIGIBLE"
            exclusion_reason = "NONE"

        event_records.append({
            "event_id": event_id,
            "station_code": station_code,
            "noaa_ghcnh_id": ghcnh_id,
            "climate_class": station_meta["climate_class"],
            "caiso_proxy_hub": station_meta["caiso_proxy_hub"],
            "local_timezone": target_timezone,
            "threshold_percentile": threshold_info["percentile"],
            "threshold_temperature_c": threshold_info["threshold_p90_c"],
            "threshold_sample_size": threshold_info["sample_size"],
            "local_start_date": start_date_str,
            "local_end_date": end_date_str,
            "peak_local_date": peak_date,
            "event_start_utc": start_utc,
            "event_end_utc": end_utc,
            "qualifying_day_count": dur_days,
            "duration_days": dur_days,
            "duration_hours": duration_hours,
            "peak_temperature_c": peak_temp,
            "mean_max_temperature_c": mean_max,
            "cumulative_exceedance_c_days": cum_exceed,
            "onset_start_utc": onset_start_utc,
            "recovery_end_utc": recovery_end_utc,
            "full_window_start_utc": onset_start_utc,
            "full_window_end_utc": recovery_end_utc,
            "regional_episode_id": "",  # Assigned during episode clustering
            "source_year": year,
            "weather_eligibility_status": weather_eligibility,
            "joint_evaluation_eligibility": joint_eval_eligibility,
            "provisional": is_provisional,
            "exclusion_reason": exclusion_reason,
            "source_file_references": source_psv_path,
        })

    return event_records


def cluster_regional_episodes(
    events: list[dict[str, Any]],
    *,
    buffer_hours: int = 24,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group station events into regional episodes using connected components on expanded intervals.

    Returns:
        (updated_events, episode_records)
    """
    if not events:
        return [], []

    # Nodes represent station events
    n = len(events)
    adj: dict[int, set[int]] = {i: set() for i in range(n)}

    for i in range(n):
        for j in range(i + 1, n):
            ev1 = events[i]
            ev2 = events[j]

            exp1_s = ev1["event_start_utc"] - timedelta(hours=buffer_hours)
            exp1_e = ev1["event_end_utc"] + timedelta(hours=buffer_hours)
            exp2_s = ev2["event_start_utc"] - timedelta(hours=buffer_hours)
            exp2_e = ev2["event_end_utc"] + timedelta(hours=buffer_hours)

            # Intervals overlap if max(starts) < min(ends)
            if max(exp1_s, exp2_s) < min(exp1_e, exp2_e):
                adj[i].add(j)
                adj[j].add(i)

    # Transitive connected components
    visited: set[int] = set()
    components: list[list[int]] = []

    for i in range(n):
        if i not in visited:
            comp: list[int] = []
            queue = [i]
            visited.add(i)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in sorted(list(adj[curr])):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(comp)

    # Sort components deterministically by earliest event start, then earliest event_id
    def component_sort_key(comp_indices: list[int]) -> tuple[datetime, str]:
        comp_evs = [events[idx] for idx in comp_indices]
        min_start = min(ev["event_start_utc"] for ev in comp_evs)
        min_eid = min(ev["event_id"] for ev in comp_evs)
        return (min_start, min_eid)

    components.sort(key=component_sort_key)

    # Construct regional episode records
    episode_records: list[dict[str, Any]] = []
    updated_events = [dict(ev) for ev in events]

    for ep_idx, comp_indices in enumerate(components, 1):
        comp_evs = [updated_events[idx] for idx in comp_indices]
        # Sort member events deterministically
        comp_evs.sort(key=lambda x: (x["event_start_utc"], x["event_id"]))

        earliest_start_utc = min(ev["event_start_utc"] for ev in comp_evs)
        latest_end_utc = max(ev["event_end_utc"] for ev in comp_evs)
        component_start_utc = earliest_start_utc - timedelta(hours=buffer_hours)
        component_end_utc = latest_end_utc + timedelta(hours=buffer_hours)

        ep_date_str = earliest_start_utc.strftime("%Y%m%d")
        regional_episode_id = f"B2_EP_{ep_date_str}_{ep_idx:02d}"

        # Assign episode ID to each member station event
        for ev in comp_evs:
            ev["regional_episode_id"] = regional_episode_id

        member_eids = [ev["event_id"] for ev in comp_evs]
        station_codes = sorted(list(set(ev["station_code"] for ev in comp_evs)))
        years = sorted(list(set(ev["source_year"] for ev in comp_evs)))

        # Summary of eligibility
        any_provisional = any(ev["provisional"] for ev in comp_evs)
        all_excluded = all(ev["joint_evaluation_eligibility"] == "EXCLUDED" for ev in comp_evs)
        any_eligible = any(ev["joint_evaluation_eligibility"] == "ELIGIBLE" for ev in comp_evs)

        if all_excluded:
            ep_eligibility = "EXCLUDED_FROM_JOINT_EVALUATION"
        elif any_provisional:
            ep_eligibility = "PROVISIONAL"
        elif any_eligible:
            ep_eligibility = "ELIGIBLE"
        else:
            ep_eligibility = "UNKNOWN"

        episode_records.append({
            "regional_episode_id": regional_episode_id,
            "expanded_buffer_hours": buffer_hours,
            "component_start_utc": component_start_utc,
            "component_end_utc": component_end_utc,
            "earliest_event_start_utc": earliest_start_utc,
            "latest_event_end_utc": latest_end_utc,
            "member_event_count": len(member_eids),
            "distinct_station_count": len(station_codes),
            "station_codes": ";".join(station_codes),
            "event_ids": ";".join(member_eids),
            "represented_years": ";".join(str(y) for y in years),
            "primary_independent_unit": True,
            "eligibility_summary": ep_eligibility,
        })

    # Sort updated events deterministically: event_start_utc, event_id
    updated_events.sort(key=lambda x: (x["event_start_utc"], x["event_id"]))

    return updated_events, episode_records


def build_b2_hourly_phase_labels(
    events: list[dict[str, Any]],
    daily_records_by_station: dict[str, dict[str, dict[str, Any]]],
    thresholds_by_station: dict[str, float],
    *,
    target_timezone: str = TARGET_TIMEZONE,
) -> pd.DataFrame:
    """Build canonical hourly phase labels for all detected station heatwave events.

    Labels every hour in [onset_start_utc, recovery_end_utc) with:
    - onset
    - sustained
    - peak
    - recovery
    """
    tz = ZoneInfo(target_timezone)
    hourly_records: list[dict[str, Any]] = []

    # Track assigned timestamps per station to detect overlaps within the same station
    assigned_by_station: dict[str, dict[datetime, tuple[str, str]]] = {}

    for ev in events:
        eid = str(ev["event_id"])
        st_code = str(ev["station_code"])
        ghcnh_id = str(ev["noaa_ghcnh_id"])
        reg_ep_id = str(ev["regional_episode_id"])
        start_date = date.fromisoformat(str(ev["local_start_date"]))
        end_date = date.fromisoformat(str(ev["local_end_date"]))
        peak_date_str = str(ev["peak_local_date"])
        thresh = thresholds_by_station[st_code]

        if st_code not in assigned_by_station:
            assigned_by_station[st_code] = {}

        onset_date = start_date - timedelta(days=1)
        recovery_date = end_date + timedelta(days=1)

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

            day_start_utc, day_end_utc, _ = get_local_day_utc_bounds(curr_str, target_timezone=target_timezone)

            d_rec = daily_records_by_station.get(st_code, {}).get(curr_str)
            daily_max_t = d_rec.get("daily_max_temperature_c") if d_rec else None
            t_missing = daily_max_t is None
            exceeds = (daily_max_t is not None and daily_max_t > thresh)

            cur_ts = day_start_utc
            while cur_ts < day_end_utc:
                if cur_ts in assigned_by_station[st_code]:
                    prev_eid, prev_phase = assigned_by_station[st_code][cur_ts]
                    raise ValueError(
                        f"Phase buffer collision at {st_code} timestamp {cur_ts.isoformat()}: "
                        f"already assigned to {prev_eid} ({prev_phase}), cannot assign to {eid} ({phase})"
                    )

                assigned_by_station[st_code][cur_ts] = (eid, phase)
                ts_loc = cur_ts.astimezone(tz)
                loc_ts_str = ts_loc.strftime("%Y-%m-%dT%H:%M:%S")

                hourly_records.append({
                    "station_code": st_code,
                    "noaa_ghcnh_id": ghcnh_id,
                    "event_id": eid,
                    "regional_episode_id": reg_ep_id,
                    "timestamp_utc": cur_ts,
                    "local_timestamp": loc_ts_str,
                    "local_date": curr_str,
                    "phase": phase,
                    "is_onset": (phase == "onset"),
                    "is_peak": (phase == "peak"),
                    "is_sustained": (phase == "sustained"),
                    "is_recovery": (phase == "recovery"),
                    "is_active_heatwave": (phase in ("peak", "sustained")),
                    "daily_max_temperature_c": daily_max_t,
                    "threshold_temperature_c": thresh,
                    "is_exceedance": exceeds,
                    "temperature_missing": t_missing,
                })
                cur_ts += timedelta(hours=1)

            curr_d += timedelta(days=1)

    df_hourly = pd.DataFrame(hourly_records)
    # Sort deterministically
    if not df_hourly.empty:
        df_hourly.sort_values(by=["station_code", "timestamp_utc"], inplace=True)
        df_hourly.reset_index(drop=True, inplace=True)

    return df_hourly
