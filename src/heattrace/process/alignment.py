"""Data alignment, unit normalization, carbon-intensity reconciliation, and manifest generation."""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.caiso import parse_caiso_zip, validate_caiso_lmp_rows
from heattrace.ingest.coverage import compute_hourly_coverage
from heattrace.ingest.eia import (
    LB_TO_GRAMS,
    METRIC_TON_TO_LBS,
    parse_and_validate_eia_ciso_workbook,
    parse_and_validate_eia_json,
)
from heattrace.ingest.noaa import (
    check_noaa_temperature_quality,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
)
from heattrace.ingest.provenance import sha256_file
from heattrace.process.quality import (
    CANONICAL_COLUMNS,
    DEFAULT_RECONCILIATION_TOLERANCE_LB_PER_KWH,
    validate_aligned_dataframe,
)


def get_git_commit_hash() -> str:
    """Safely obtain current git commit hash or working-tree identifier."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def build_canonical_hourly_intervals(
    qc_days_cfg: dict[str, Any],
    target_timezone: str = "America/Los_Angeles",
) -> list[dict[str, Any]]:
    """Build canonical UTC hourly intervals for approved QC days.

    Sorts intervals ascending by timestamp_utc.
    Ensures unique, non-overlapping intervals across all approved days.
    """
    intervals: list[dict[str, Any]] = []

    for day_label, info in qc_days_cfg.items():
        date_str = str(info["date"]).strip()
        start_utc, end_utc, expected_hours = get_local_day_utc_bounds(
            date_str, target_timezone=target_timezone
        )
        curr = start_utc
        while curr < end_utc:
            intervals.append({
                "timestamp_utc": curr,
                "interval_end_utc": curr + timedelta(hours=1),
                "local_date": date_str,
                "qc_day_type": day_label,
            })
            curr += timedelta(hours=1)

    # Sort ascending by timestamp_utc
    intervals.sort(key=lambda x: x["timestamp_utc"])

    # Verify uniqueness
    seen = set()
    for row in intervals:
        ts = row["timestamp_utc"]
        if ts in seen:
            raise ValueError(f"Duplicate hourly interval in QC specification: {ts}")
        seen.add(ts)

    return intervals


def aggregate_noaa_hourly_temperature(
    psv_path: str | Path,
    intervals: list[dict[str, Any]],
    expected_station: str = "USW00023234",
) -> dict[datetime, dict[str, Any]]:
    """Aggregate accepted NOAA observations into hourly intervals.

    Rules:
    - Observations are grouped by UTC hourly interval [start, start + 1h).
    - Only observations accepted by check_noaa_temperature_quality are included.
    - If valid observations exist in the hour:
      - temperature_c is arithmetic mean
      - temperature_obs_count is count of accepted obs
      - temperature_min_c is min of accepted obs
      - temperature_max_c is max of accepted obs
      - temperature_missing is False
    - If no valid observation in the hour:
      - temperature_c, min, max are None
      - temperature_obs_count is 0
      - temperature_missing is True
    - Does NOT interpolate missing hours.
    """
    path = Path(psv_path)
    if not path.exists():
        raise FileNotFoundError(f"NOAA PSV file not found: {path}")

    min_ts = intervals[0]["timestamp_utc"]
    max_ts = intervals[-1]["interval_end_utc"]

    # Parse observations in bounding range
    obs_rows = parse_ghcnh_psv(path, filter_date_start=min_ts, filter_date_end=max_ts)

    # Filter by station and quality
    accepted_by_hour: dict[datetime, list[float]] = {
        inv["timestamp_utc"]: [] for inv in intervals
    }

    for r in obs_rows:
        if r.get("station_id") != expected_station:
            continue
        ts = r["timestamp_utc"].astimezone(timezone.utc)
        temp = r.get("temperature_c")
        qc = r.get("temperature_quality_code", "")

        if check_noaa_temperature_quality(qc) == "accepted" and temp is not None:
            # Find interval
            hour_start = ts.replace(minute=0, second=0, microsecond=0)
            if hour_start in accepted_by_hour and ts < hour_start + timedelta(hours=1):
                accepted_by_hour[hour_start].append(float(temp))

    result: dict[datetime, dict[str, Any]] = {}
    for inv in intervals:
        ts = inv["timestamp_utc"]
        temps = accepted_by_hour.get(ts, [])
        if temps:
            mean_temp = round(sum(temps) / len(temps), 4)
            min_temp = round(min(temps), 4)
            max_temp = round(max(temps), 4)
            result[ts] = {
                "temperature_c": mean_temp,
                "temperature_obs_count": len(temps),
                "temperature_min_c": min_temp,
                "temperature_max_c": max_temp,
                "temperature_missing": False,
            }
        else:
            result[ts] = {
                "temperature_c": None,
                "temperature_obs_count": 0,
                "temperature_min_c": None,
                "temperature_max_c": None,
                "temperature_missing": True,
            }

    return result


def load_caiso_dam_lmp_by_interval(
    caiso_zip_paths: list[str | Path],
    expected_node: str = "TH_NP15_GEN-APND",
) -> dict[datetime, dict[str, Any]]:
    """Parse CAISO DAM LMP zip archives and map by canonical UTC interval start."""
    price_by_ts: dict[datetime, dict[str, Any]] = {}

    for p in caiso_zip_paths:
        path = Path(p)
        if not path.exists():
            raise FileNotFoundError(f"CAISO zip file not found: {path}")

        rows, err = parse_caiso_zip(path, expected_node=expected_node, expected_market="DAM")
        if err:
            raise RuntimeError(f"Error parsing CAISO zip {path}: {err}")

        lmp_rows = [r for r in rows if r.get("lmp_type") == "LMP"]
        for r in lmp_rows:
            ts = r["timestamp_utc"].astimezone(timezone.utc)
            price = r.get("price_usd_per_mwh")
            if ts in price_by_ts:
                raise ValueError(f"Duplicate CAISO price timestamp {ts} across files")
            price_by_ts[ts] = {
                "price_usd_per_mwh": price,
                "price_missing": price is None,
            }

    return price_by_ts


def load_eia_api_data_by_interval(
    json_paths: list[str | Path],
    intervals: list[dict[str, Any]],
    expected_ba: str = "CISO",
) -> dict[datetime, dict[str, Any]]:
    """Parse cached EIA API JSON files using parse_and_validate_eia_json and map by canonical UTC interval start."""
    api_by_ts: dict[datetime, dict[str, Any]] = {}

    dates = sorted(list({inv["local_date"] for inv in intervals}))
    for d in dates:
        day_invs = [inv for inv in intervals if inv["local_date"] == d]
        day_start = day_invs[0]["timestamp_utc"]
        day_end = day_invs[-1]["interval_end_utc"]

        # Find matching json file for date
        matching_files = [p for p in json_paths if day_start.strftime("%Y%m%d") in str(p)]
        if not matching_files:
            raise FileNotFoundError(f"No EIA JSON file found for date {d} ({day_start.strftime('%Y%m%d')})")

        p = Path(matching_files[0])
        if not p.exists():
            raise FileNotFoundError(f"EIA JSON file not found: {p}")

        content = p.read_bytes()
        parsed = parse_and_validate_eia_json(
            content,
            expected_ba=expected_ba,
            requested_start=day_start,
            requested_end=day_end,
        )

        d_by_ts = {r["timestamp_utc"]: r["value_mw"] for r in parsed["demand_rows"]}
        ng_by_ts = {r["timestamp_utc"]: r["value_mw"] for r in parsed["net_gen_rows"]}

        for inv in day_invs:
            ts = inv["timestamp_utc"]
            if ts not in d_by_ts or ts not in ng_by_ts:
                raise ValueError(f"Missing API demand or net generation for canonical interval {ts.isoformat()}")
            api_by_ts[ts] = {
                "eia_api_demand_mw": d_by_ts[ts],
                "eia_api_net_generation_mw": ng_by_ts[ts],
            }

    return api_by_ts


def load_eia_workbook_by_interval(
    workbook_path: str | Path,
    intervals: list[dict[str, Any]],
    expected_ba: str = "CISO",
) -> dict[datetime, dict[str, Any]]:
    """Parse EIA CISO workbook across all intervals.

    Note: workbook UTC time is hour-ending; interval start is UTC time - 1h.
    """
    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"EIA workbook not found: {path}")

    # Process in batches grouped by continuous interval chunks or each day
    dates = sorted(list({inv["local_date"] for inv in intervals}))
    wb_rows_by_ts: dict[datetime, dict[str, Any]] = {}

    for d in dates:
        day_invs = [inv for inv in intervals if inv["local_date"] == d]
        day_start = day_invs[0]["timestamp_utc"]
        day_end = day_invs[-1]["interval_end_utc"]

        res = parse_and_validate_eia_ciso_workbook(
            path,
            requested_start=day_start,
            requested_end=day_end,
            expected_ba=expected_ba,
        )

        for r in res["rows"]:
            ts = r["timestamp_utc"].astimezone(timezone.utc)
            wb_rows_by_ts[ts] = r

    return wb_rows_by_ts


def build_aligned_dataset(
    *,
    sources_cfg: dict[str, Any],
    data_dir: str | Path = "data",
    reconciliation_tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE_LB_PER_KWH,
) -> pd.DataFrame:
    """Build the canonical 48-row aligned DataFrame from cached P1 sources."""
    d_dir = Path(data_dir)
    qc_cfg = sources_cfg.get("qc", {})
    qc_days_cfg = qc_cfg.get("days", {})
    station_id = qc_cfg.get(
        "primary_station_id", sources_cfg["weather"]["stations"][0]["id"]
    )
    target_tz = qc_cfg.get("target_timezone", "America/Los_Angeles")
    node = sources_cfg["price"]["node"]
    ba = sources_cfg["carbon"]["balancing_authority"]

    # 1. Canonical intervals (48 rows)
    intervals = build_canonical_hourly_intervals(qc_days_cfg, target_timezone=target_tz)
    if len(intervals) != 48:
        raise ValueError(f"Expected exactly 48 hourly intervals, got {len(intervals)}")

    # 2. NOAA data
    noaa_psv = d_dir / f"raw/noaa/GHCNh_{station_id}_2024.psv"
    noaa_data = aggregate_noaa_hourly_temperature(noaa_psv, intervals, expected_station=station_id)

    # 3. CAISO data
    caiso_zips = [
        d_dir / f"raw/caiso/caiso_dam_lmp_{node}_20240702_20240703.zip",
        d_dir / f"raw/caiso/caiso_dam_lmp_{node}_20240607_20240608.zip",
    ]
    caiso_data = load_caiso_dam_lmp_by_interval(caiso_zips, expected_node=node)

    # 4. EIA API data (demand & net generation) using parse_and_validate_eia_json
    eia_jsons = [
        d_dir / f"raw/eia/eia930_region_{ba}_20240702.json",
        d_dir / f"raw/eia/eia930_region_{ba}_20240607.json",
    ]
    eia_api_data = load_eia_api_data_by_interval(eia_jsons, intervals=intervals, expected_ba=ba)

    # 5. EIA Workbook data
    eia_workbook = d_dir / f"raw/eia/{ba}.xlsx"
    wb_data = load_eia_workbook_by_interval(eia_workbook, intervals, expected_ba=ba)

    # 6. Merge rows
    rows: list[dict[str, Any]] = []
    for inv in intervals:
        ts = inv["timestamp_utc"]
        local_date = inv["local_date"]
        qc_day_type = inv["qc_day_type"]

        # Weather
        w = noaa_data.get(ts, {
            "temperature_c": None,
            "temperature_obs_count": 0,
            "temperature_min_c": None,
            "temperature_max_c": None,
            "temperature_missing": True,
        })

        # CAISO Price
        p = caiso_data.get(ts, {
            "price_usd_per_mwh": None,
            "price_missing": True,
        })

        # EIA API
        ea = eia_api_data.get(ts, {
            "eia_api_demand_mw": None,
            "eia_api_net_generation_mw": None,
        })

        # EIA Workbook
        wb = wb_data.get(ts)
        if wb is None:
            raise ValueError(f"Missing EIA workbook entry for interval {ts.isoformat()}")

        # Canonical Demand and Net Generation come from EIA API v2
        api_demand = ea.get("eia_api_demand_mw")
        demand_missing = api_demand is None or pd.isna(api_demand)
        demand_mw = float(api_demand) if not demand_missing else None

        api_net_gen = ea.get("eia_api_net_generation_mw")
        net_gen_missing = api_net_gen is None or pd.isna(api_net_gen)
        net_gen_mw = float(api_net_gen) if not net_gen_missing else None

        # Workbook comparison values
        wb_demand = float(wb["demand_mwh"]) if wb.get("demand_mwh") is not None else None
        wb_net_gen = float(wb["net_generation_mwh"]) if wb.get("net_generation_mwh") is not None else None

        demand_diff = (
            abs(demand_mw - wb_demand) if demand_mw is not None and wb_demand is not None else None
        )
        net_gen_diff = (
            abs(net_gen_mw - wb_net_gen) if net_gen_mw is not None and wb_net_gen is not None else None
        )

        # Canonical Carbon Intensity from workbook generated intensity
        # generated_intensity_lb_per_kwh * 453.59237
        gen_int_lb = wb.get("co2_intensity_generated_lb_per_kwh")
        con_int_lb = wb.get("co2_intensity_consumed_lb_per_kwh")
        co2_gen_mt = wb.get("co2_emissions_generated_metric_tons")
        co2_con_mt = wb.get("co2_emissions_consumed_metric_tons")
        pos_gen_mwh = wb.get("positive_generation_mwh")
        con_elec_mwh = wb.get("consumed_electricity_mwh")

        if gen_int_lb is not None:
            carbon_g_per_kwh = float(gen_int_lb) * LB_TO_GRAMS
            carbon_missing = False
        else:
            carbon_g_per_kwh = None
            carbon_missing = True

        consumed_g_per_kwh = (
            float(con_int_lb) * LB_TO_GRAMS if con_int_lb is not None else None
        )

        # Independent recalculation:
        # (co2_emissions_generated_metric_tons * 2204.62262185) / (positive_generation_mwh * 1000)
        if pos_gen_mwh is not None and pos_gen_mwh > 0 and co2_gen_mt is not None:
            recalc_lb = (float(co2_gen_mt) * METRIC_TON_TO_LBS) / (float(pos_gen_mwh) * 1000.0)
            recalc_g = recalc_lb * LB_TO_GRAMS
            reconcil_diff = recalc_lb - float(gen_int_lb) if gen_int_lb is not None else None
        else:
            recalc_lb = None
            recalc_g = None
            reconcil_diff = None

        # Data Issue & Quality flags
        has_issue = bool(wb.get("has_data_issue", False))
        carbon_data_issue = has_issue
        carbon_primary_analysis_eligible = not has_issue
        source_quality = "success_with_data_issues" if has_issue else "success"
        issue_flag_val = str(wb.get("data_issue_flag", "0"))

        row = {
            "timestamp_utc": ts,
            "qc_day_type": qc_day_type,
            "local_date": local_date,
            "temperature_c": w["temperature_c"],
            "temperature_obs_count": int(w["temperature_obs_count"]),
            "temperature_min_c": w["temperature_min_c"],
            "temperature_max_c": w["temperature_max_c"],
            "temperature_missing": bool(w["temperature_missing"]),
            "price_usd_per_mwh": (
                float(p["price_usd_per_mwh"]) if p["price_usd_per_mwh"] is not None else None
            ),
            "price_missing": bool(p["price_missing"]),
            "demand_mw": demand_mw,
            "demand_missing": demand_missing,
            "net_generation_mw": net_gen_mw,
            "net_generation_missing": net_gen_missing,
            "carbon_g_per_kwh": (
                round(carbon_g_per_kwh, 4) if carbon_g_per_kwh is not None else None
            ),
            "carbon_missing": carbon_missing,
            "carbon_data_issue": carbon_data_issue,
            "carbon_primary_analysis_eligible": carbon_primary_analysis_eligible,
            "source_quality": source_quality,
            "co2_emissions_generated_metric_tons": co2_gen_mt,
            "co2_emissions_consumed_metric_tons": co2_con_mt,
            "generated_intensity_lb_per_kwh": gen_int_lb,
            "consumed_intensity_lb_per_kwh": con_int_lb,
            "generated_intensity_g_per_kwh": (
                round(carbon_g_per_kwh, 4) if carbon_g_per_kwh is not None else None
            ),
            "consumed_intensity_g_per_kwh": (
                round(consumed_g_per_kwh, 4) if consumed_g_per_kwh is not None else None
            ),
            "positive_generation_mwh": pos_gen_mwh,
            "consumed_electricity_mwh": con_elec_mwh,
            "eia_api_demand_mw": api_demand,
            "eia_api_net_generation_mw": api_net_gen,
            "workbook_demand_mw": wb_demand,
            "workbook_net_generation_mw": wb_net_gen,
            "demand_source_difference_mw": demand_diff,
            "net_generation_source_difference_mw": net_gen_diff,
            "recalculated_generated_intensity_lb_per_kwh": recalc_lb,
            "recalculated_generated_intensity_g_per_kwh": recalc_g,
            "generated_intensity_reconciliation_difference": reconcil_diff,
            "eia_data_issue_flag": issue_flag_val,
            "source_station_id": station_id,
            "source_caiso_node": node,
            "source_balancing_authority": ba,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    # Ensure exact column order
    df = df[CANONICAL_COLUMNS]

    # Validate DataFrame
    validate_aligned_dataframe(
        df,
        expected_rows=48,
        expected_dates=["2024-06-07", "2024-07-02"],
        reconciliation_tolerance=reconciliation_tolerance,
    )

    return df


def write_aligned_coverage_csv(
    coverage_path: str | Path,
    df: pd.DataFrame,
    sources_cfg: dict[str, Any],
) -> None:
    """Write data/manifests/aligned_coverage.csv documenting window coverage per source and day."""
    out_path = Path(coverage_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    qc_cfg = sources_cfg.get("qc", {})
    qc_days_cfg = qc_cfg.get("days", {})
    station_id = qc_cfg.get(
        "primary_station_id", sources_cfg["weather"]["stations"][0]["id"]
    )
    node = sources_cfg["price"]["node"]
    ba = sources_cfg["carbon"]["balancing_authority"]

    fieldnames = [
        "qc_day_type",
        "local_date",
        "source",
        "dataset",
        "status",
        "requested_start",
        "requested_end",
        "expected_hours",
        "covered_hourly_bins",
        "missing_hours",
        "duplicate_timestamps",
        "notes",
    ]

    rows: list[dict[str, Any]] = []

    for day_label, day_info in qc_days_cfg.items():
        date_str = day_info["date"]
        sub_df = df[df["local_date"] == date_str]
        n_sub = len(sub_df)
        req_start = sub_df["timestamp_utc"].iloc[0].isoformat()
        req_end = (sub_df["timestamp_utc"].iloc[-1] + timedelta(hours=1)).isoformat()

        # 1. NOAA
        t_miss = int(sub_df["temperature_missing"].sum())
        rows.append({
            "qc_day_type": day_label,
            "local_date": date_str,
            "source": "NOAA",
            "dataset": "GHCNh",
            "status": "success" if t_miss == 0 else "partial",
            "requested_start": req_start,
            "requested_end": req_end,
            "expected_hours": 24,
            "covered_hourly_bins": 24 - t_miss,
            "missing_hours": t_miss,
            "duplicate_timestamps": 0,
            "notes": f"Station {station_id} aggregated temperature_c",
        })

        # 2. CAISO
        p_miss = int(sub_df["price_missing"].sum())
        rows.append({
            "qc_day_type": day_label,
            "local_date": date_str,
            "source": "CAISO",
            "dataset": "PRC_LMP",
            "status": "success" if p_miss == 0 else "partial",
            "requested_start": req_start,
            "requested_end": req_end,
            "expected_hours": 24,
            "covered_hourly_bins": 24 - p_miss,
            "missing_hours": p_miss,
            "duplicate_timestamps": 0,
            "notes": f"Node {node} DAM hourly LMP",
        })

        # 3. EIA Demand (API)
        d_miss = int(sub_df["demand_missing"].sum())
        rows.append({
            "qc_day_type": day_label,
            "local_date": date_str,
            "source": "EIA",
            "dataset": "EIA-930-demand",
            "status": "success" if d_miss == 0 else "partial",
            "requested_start": req_start,
            "requested_end": req_end,
            "expected_hours": 24,
            "covered_hourly_bins": 24 - d_miss,
            "missing_hours": d_miss,
            "duplicate_timestamps": 0,
            "notes": f"BA {ba} demand_mw (EIA API v2 /region-data)",
        })

        # 4. EIA Net Generation (API)
        ng_miss = int(sub_df["net_generation_missing"].sum())
        rows.append({
            "qc_day_type": day_label,
            "local_date": date_str,
            "source": "EIA",
            "dataset": "EIA-930-net-generation",
            "status": "success" if ng_miss == 0 else "partial",
            "requested_start": req_start,
            "requested_end": req_end,
            "expected_hours": 24,
            "covered_hourly_bins": 24 - ng_miss,
            "missing_hours": ng_miss,
            "duplicate_timestamps": 0,
            "notes": f"BA {ba} net_generation_mw (EIA API v2 /region-data)",
        })

        # 5. EIA Carbon Intensity (Workbook)
        c_miss = int(sub_df["carbon_missing"].sum())
        c_issue = int(sub_df["carbon_data_issue"].sum())
        c_stat = "success_with_data_issues" if c_issue > 0 else "success"
        rows.append({
            "qc_day_type": day_label,
            "local_date": date_str,
            "source": "EIA",
            "dataset": "EIA-930-intensity-generated",
            "status": c_stat,
            "requested_start": req_start,
            "requested_end": req_end,
            "expected_hours": 24,
            "covered_hourly_bins": 24 - c_miss,
            "missing_hours": c_miss,
            "duplicate_timestamps": 0,
            "notes": f"BA {ba} generated carbon intensity (EIA workbook {ba}.xlsx, data issues flagged: {c_issue}/24)",
        })

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_aligned_manifest_json(
    manifest_path: str | Path,
    df: pd.DataFrame,
    *,
    input_files: list[Path],
    output_files: list[Path],
    sources_cfg: dict[str, Any],
    commit_hash: str,
    reconciliation_tolerance: float,
) -> None:
    """Write data/manifests/aligned_dataset_manifest.json with comprehensive audit metadata."""
    out_path = Path(manifest_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc).isoformat()

    input_hashes = {str(p): sha256_file(p) for p in input_files if p.exists()}
    output_hashes = {str(p): sha256_file(p) for p in output_files if p.exists()}

    missingness_counts = {
        "temperature_missing": int(df["temperature_missing"].sum()),
        "price_missing": int(df["price_missing"].sum()),
        "demand_missing": int(df["demand_missing"].sum()),
        "net_generation_missing": int(df["net_generation_missing"].sum()),
        "carbon_missing": int(df["carbon_missing"].sum()),
    }

    eia_issue_counts = {
        "carbon_data_issue_flagged": int(df["carbon_data_issue"].sum()),
        "carbon_primary_analysis_eligible": int(
            df["carbon_primary_analysis_eligible"].sum()
        ),
    }

    manifest_data = {
        "schema_version": "v0",
        "dataset_name": "hourly_caiso_v0",
        "generated_at": now_utc,
        "code_commit": commit_hash,
        "is_offline_cache_only": True,
        "methodology": {
            "canonical_timestamp": "timezone-aware UTC interval start",
            "weather_station": sources_cfg.get("qc", {}).get(
                "primary_station_id", "USW00023234"
            ),
            "local_qc_timezone": sources_cfg.get("qc", {}).get(
                "target_timezone", "America/Los_Angeles"
            ),
            "caiso_node": sources_cfg["price"]["node"],
            "caiso_product": sources_cfg["price"]["product"],
            "balancing_authority": sources_cfg["carbon"]["balancing_authority"],
            "canonical_demand_source": "EIA API v2 /region-data (type=D)",
            "canonical_net_generation_source": "EIA API v2 /region-data (type=NG)",
            "carbon_metric": "CO2 Emissions Intensity for Generated Electricity",
            "carbon_conversion": "generated_intensity_lb_per_kwh * 453.59237",
            "reconciliation_tolerance_lb_per_kwh": reconciliation_tolerance,
            "max_observed_reconciliation_difference": float(
                df["generated_intensity_reconciliation_difference"].abs().max()
            ),
            "max_demand_source_difference_mw": float(
                df["demand_source_difference_mw"].dropna().max()
            ) if df["demand_source_difference_mw"].notna().any() else 0.0,
            "max_net_generation_source_difference_mw": float(
                df["net_generation_source_difference_mw"].dropna().max()
            ) if df["net_generation_source_difference_mw"].notna().any() else 0.0,
            "eia_data_issue_policy": (
                "Preserve all EIA rows. Flagged rows have carbon_data_issue=True, "
                "carbon_primary_analysis_eligible=False, source_quality='success_with_data_issues'. "
                "P5 must perform sensitivity and exclusion analysis on these rows."
            ),
        },
        "row_count": len(df),
        "timestamp_start": df["timestamp_utc"].iloc[0].isoformat(),
        "timestamp_end": df["timestamp_utc"].iloc[-1].isoformat(),
        "unique_timestamps": int(df["timestamp_utc"].nunique()),
        "duplicate_timestamps": int(df["timestamp_utc"].duplicated().sum()),
        "rows_per_qc_date": df["local_date"].value_counts().to_dict(),
        "columns": list(df.columns),
        "missingness_counts": missingness_counts,
        "eia_issue_counts": eia_issue_counts,
        "input_files": input_hashes,
        "output_files": output_hashes,
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, sort_keys=True)


def write_aligned_outputs(
    df: pd.DataFrame,
    *,
    data_dir: str | Path = "data",
    config_dir: str | Path = "configs",
    reconciliation_tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE_LB_PER_KWH,
) -> dict[str, Any]:
    """Write Parquet, sample CSV, coverage CSV, and aligned manifest JSON.

    Returns manifest record dict.
    """
    d_dir = Path(data_dir)
    c_dir = Path(config_dir)
    sources_cfg = load_yaml(c_dir / "sources.yaml")
    commit_hash = get_git_commit_hash()

    parquet_path = d_dir / "processed/hourly_caiso_v0.parquet"
    sample_csv_path = d_dir / "processed/hourly_caiso_v0_sample.csv"
    coverage_path = d_dir / "manifests/aligned_coverage.csv"
    manifest_path = d_dir / "manifests/aligned_dataset_manifest.json"

    # Ensure directories exist
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Parquet
    df.to_parquet(parquet_path, index=False, engine="pyarrow")

    # 2. Sample CSV (all 48 rows because initial table is small)
    df.to_csv(sample_csv_path, index=False)

    # 3. Coverage CSV
    write_aligned_coverage_csv(coverage_path, df, sources_cfg)

    # Input files to record
    ba = sources_cfg["carbon"]["balancing_authority"]
    node = sources_cfg["price"]["node"]
    station_id = sources_cfg.get("qc", {}).get(
        "primary_station_id", sources_cfg["weather"]["stations"][0]["id"]
    )

    input_files = [
        d_dir / f"raw/noaa/GHCNh_{station_id}_2024.psv",
        d_dir / f"raw/caiso/caiso_dam_lmp_{node}_20240702_20240703.zip",
        d_dir / f"raw/caiso/caiso_dam_lmp_{node}_20240607_20240608.zip",
        d_dir / f"raw/eia/eia930_region_{ba}_20240702.json",
        d_dir / f"raw/eia/eia930_region_{ba}_20240607.json",
        d_dir / f"raw/eia/{ba}.xlsx",
    ]

    output_files = [
        parquet_path,
        sample_csv_path,
        coverage_path,
    ]

    # 4. Manifest JSON
    write_aligned_manifest_json(
        manifest_path,
        df,
        input_files=input_files,
        output_files=output_files,
        sources_cfg=sources_cfg,
        commit_hash=commit_hash,
        reconciliation_tolerance=reconciliation_tolerance,
    )

    return {
        "parquet_path": str(parquet_path),
        "sample_csv_path": str(sample_csv_path),
        "coverage_path": str(coverage_path),
        "manifest_path": str(manifest_path),
        "row_count": len(df),
    }
