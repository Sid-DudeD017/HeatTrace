"""Track B2 Phase 2 multi-station and multi-year coverage validation.

Explicitly namespaced for p12_b2 / data/v2/.
Provides robust coverage calculation, schema definition, and deferred selected-window check.
Reuses official NOAA and EIA ingestion logic from src/heattrace/ingest/.
"""

from __future__ import annotations

import collections
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo
import pandas as pd

from heattrace.ingest.noaa import (
    parse_ghcnh_psv,
    extract_daily_maxima,
    check_noaa_temperature_quality,
    NOAA_ACCEPTED_QUALITY_CODES,
    NOAA_REJECTED_QUALITY_CODES,
)
from heattrace.ingest.eia import parse_and_validate_eia_ciso_workbook


def file_sha256(path: Path | str) -> str:
    """Compute hex-encoded SHA-256 hash of file content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def calculate_noaa_station_year_coverage(
    psv_file_path: str | Path,
    station_id: str,
    station_name: str,
    year: int,
    *,
    local_tz_str: str = "America/Los_Angeles",
    source_url: str = "",
    retrieved_at_utc: str = "unknown",
    provisional: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]]]:
    """Compute comprehensive warm-season coverage and hourly aggregation for a NOAA station-year.

    Reuses authoritative parse_ghcnh_psv, extract_daily_maxima, and check_noaa_temperature_quality.

    Warm season: local June 1 00:00 through September 30 23:59:59 (inclusive),
    represented as UTC interval-start [season_start_utc, season_end_utc).

    Returns:
      (coverage_summary_dict, hourly_processed_dataframe, daily_maxima_list)
    """
    path = Path(psv_file_path)
    if not path.is_file():
        raise FileNotFoundError(f"NOAA PSV file not found: {path}")

    file_bytes = path.stat().st_size
    psv_hash = file_sha256(path)

    local_tz = ZoneInfo(local_tz_str)
    season_start_local = datetime(year, 6, 1, 0, 0, tzinfo=local_tz)
    season_end_local = datetime(year, 10, 1, 0, 0, tzinfo=local_tz)

    start_utc = season_start_local.astimezone(timezone.utc)
    end_utc = season_end_local.astimezone(timezone.utc)

    expected_hours = int((end_utc - start_utc).total_seconds() / 3600)
    expected_local_days = (season_end_local.date() - season_start_local.date()).days
    expected_hour_set = {start_utc + timedelta(hours=i) for i in range(expected_hours)}
    expected_day_set = {season_start_local.date() + timedelta(days=i) for i in range(expected_local_days)}

    # Parse raw observations in warm season using authoritative parser
    raw_obs = parse_ghcnh_psv(path, filter_date_start=start_utc, filter_date_end=end_utc)

    # Filter to matching station
    matching_obs = [r for r in raw_obs if r.get("station_id") == station_id]
    observed_records_count = len(matching_obs)

    # Read station coordinates from first valid observation
    lat, lon, elev, official_name = None, None, None, station_name
    for r in matching_obs:
        if r.get("latitude") is not None:
            lat = float(r["latitude"])
            lon = float(r["longitude"])
            elev = float(r["elevation"])
            if r.get("station_name"):
                official_name = r["station_name"]
            break

    # Analyze exact timestamp duplicates and timestamp conflicts
    by_exact_ts: dict[datetime, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in matching_obs:
        ts = r["timestamp_utc"].astimezone(timezone.utc)
        by_exact_ts[ts].append(r)

    exact_duplicate_obs_count = 0
    conflicting_duplicate_obs_count = 0
    for ts, grp in by_exact_ts.items():
        if len(grp) > 1:
            exact_duplicate_obs_count += len(grp) - 1
            temps = [x["temperature_c"] for x in grp if x.get("temperature_c") is not None]
            if len(set(temps)) > 1:
                conflicting_duplicate_obs_count += 1

    # Extract daily maxima using authoritative HeatTrace daily max extractor
    daily_maxima_records: list[dict[str, Any]] = []
    if matching_obs:
        try:
            daily_maxima_records = extract_daily_maxima(matching_obs, target_timezone=local_tz_str)
        except Exception as e:
            # If extraction fails (e.g. invalid quality code), daily max derivation fails closed
            daily_maxima_records = []

    derived_days_set = {
        datetime.strptime(dm["local_date"], "%Y-%m-%d").date()
        for dm in daily_maxima_records
    }
    # Restrict derived daily maxima to the warm-season day set
    valid_season_days = derived_days_set.intersection(expected_day_set)
    valid_daily_max_days = len(valid_season_days)
    missing_days_count = len(expected_day_set - valid_season_days)

    # Hourly deterministic aggregation:
    # Group accepted observations into UTC hourly bins [H, H + 1 hour)
    hourly_accepted_bins: dict[datetime, list[float]] = collections.defaultdict(list)
    subhourly_obs_count = 0

    for r in matching_obs:
        temp = r.get("temperature_c")
        qc = str(r.get("temperature_quality_code", ""))
        if check_noaa_temperature_quality(qc) == "accepted" and temp is not None:
            ts = r["timestamp_utc"].astimezone(timezone.utc)
            h_bin = ts.replace(minute=0, second=0, microsecond=0)
            if start_utc <= h_bin < end_utc:
                hourly_accepted_bins[h_bin].append(float(temp))
                if ts.minute != 0 or ts.second != 0:
                    subhourly_obs_count += 1

    valid_temperature_hours = len(hourly_accepted_bins)
    missing_hours = len(expected_hour_set - set(hourly_accepted_bins.keys()))

    hourly_pct = 100.0 * valid_temperature_hours / expected_hours if expected_hours > 0 else 0.0
    daily_pct = 100.0 * valid_daily_max_days / expected_local_days if expected_local_days > 0 else 0.0

    # Build continuous normalized hourly dataframe for this station-year
    grid_hours = [start_utc + timedelta(hours=i) for i in range(expected_hours)]
    parquet_rows: list[dict[str, Any]] = []

    for h in grid_hours:
        local_dt = h.astimezone(local_tz)
        if h in hourly_accepted_bins:
            temps = hourly_accepted_bins[h]
            mean_temp = round(sum(temps) / len(temps), 4)
            min_temp = round(min(temps), 4)
            max_temp = round(max(temps), 4)
            parquet_rows.append({
                "timestamp_utc": h,
                "local_datetime": local_dt.isoformat(),
                "local_date": local_dt.date().isoformat(),
                "station_id": station_id,
                "temperature_c": mean_temp,
                "temperature_min_c": min_temp,
                "temperature_max_c": max_temp,
                "obs_count": len(temps),
                "has_conflict": False,  # Exact conflicting duplicates at same timestamp
                "is_missing": False,
                "raw_source_sha256": psv_hash,
            })
        else:
            parquet_rows.append({
                "timestamp_utc": h,
                "local_datetime": local_dt.isoformat(),
                "local_date": local_dt.date().isoformat(),
                "station_id": station_id,
                "temperature_c": None,
                "temperature_min_c": None,
                "temperature_max_c": None,
                "obs_count": 0,
                "has_conflict": False,
                "is_missing": True,
                "raw_source_sha256": psv_hash,
            })

    hourly_df = pd.DataFrame(parquet_rows)

    # Evaluate eligibility gates
    rejection_reasons = []
    if hourly_pct < 95.0:
        rejection_reasons.append(
            f"Hourly temperature coverage {hourly_pct:.2f}% < 95.0% threshold ({valid_temperature_hours}/{expected_hours})"
        )
    if daily_pct < 98.0:
        rejection_reasons.append(
            f"Daily max coverage {daily_pct:.2f}% < 98.0% threshold ({valid_daily_max_days}/{expected_local_days})"
        )
    if conflicting_duplicate_obs_count > 0:
        rejection_reasons.append(
            f"Contains {conflicting_duplicate_obs_count} unresolved exact duplicate timestamp conflicts"
        )

    if not rejection_reasons:
        status = "PROVISIONAL" if provisional else "PASS"
    else:
        status = "EXCLUDED"

    coverage_summary = {
        "station_id": station_id,
        "station_name": official_name,
        "latitude": lat,
        "longitude": lon,
        "elevation_m": elev,
        "year": year,
        "season_start_local": season_start_local.isoformat(),
        "season_end_local": season_end_local.isoformat(),
        "expected_hours": expected_hours,
        "observed_hours": observed_records_count,
        "valid_temperature_hours": valid_temperature_hours,
        "missing_hours": missing_hours,
        "duplicate_hours": exact_duplicate_obs_count,
        "conflict_hours": conflicting_duplicate_obs_count,
        "subhourly_observations": subhourly_obs_count,
        "expected_local_days": expected_local_days,
        "valid_daily_max_days": valid_daily_max_days,
        "source_url": source_url or f"https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/access/by-year/{year}/psv/GHCNh_{station_id}_{year}.psv",
        "retrieval_timestamp_utc": retrieved_at_utc,
        "processed_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": psv_hash,
        "bytes": file_bytes,
        "provisional": provisional,
        "eligibility_status": status,
        "rejection_reasons": "; ".join(rejection_reasons) if rejection_reasons else "NONE",
    }

    return coverage_summary, hourly_df, daily_maxima_records


def calculate_price_carbon_coverage_record(
    source_name: str,
    hub_or_ba: str,
    year: int,
    market_product: str,
    expected_intervals: int,
    observed_intervals: int,
    valid_intervals: int,
    missing_intervals: int,
    duplicate_intervals: int,
    conflict_intervals: int,
    issue_flag_count: int,
    unit: str,
    timestamp_convention: str,
    retrieval_provenance: str,
    sha256_hash: str,
    bytes_count: int,
    provisional: bool,
    rejection_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """Format and return a standardized price / carbon coverage record.
    
    Fail-closed validation:
    - Automatically adds rejection reason if conflict_intervals > 0.
    - Automatically adds rejection reason if valid_intervals < expected_intervals.
    - Automatically adds rejection reason if counts are inconsistent (negative missing, valid > expected, etc.).
    """
    reasons = list(rejection_reasons)

    # 1. Automatic conflict detection
    if conflict_intervals > 0:
        conflict_msg = f"Contains {conflict_intervals} conflicting duplicate interval(s) with mismatched values"
        if conflict_msg not in reasons and not any("conflict" in r.lower() for r in reasons):
            reasons.append(conflict_msg)

    # 2. Incomplete coverage
    if valid_intervals < expected_intervals:
        cov_msg = f"Incomplete interval coverage: {valid_intervals}/{expected_intervals} ({100.0 * valid_intervals / expected_intervals:.1f}%)"
        if cov_msg not in reasons and not any("incomplete" in r.lower() or "missing" in r.lower() for r in reasons):
            reasons.append(cov_msg)

    # 3. Inconsistent interval count arithmetic
    if missing_intervals < 0:
        reasons.append(f"Inconsistent interval count: negative missing intervals ({missing_intervals})")
    if valid_intervals > expected_intervals:
        reasons.append(f"Inconsistent interval count: valid intervals ({valid_intervals}) exceeds expected ({expected_intervals})")
    if (valid_intervals + missing_intervals) != expected_intervals:
        reasons.append(
            f"Inconsistent interval count: valid ({valid_intervals}) + missing ({missing_intervals}) != expected ({expected_intervals})"
        )

    if reasons:
        status = "EXCLUDED"
    elif provisional:
        status = "PROVISIONAL"
    else:
        status = "PASS"

    return {
        "source": source_name,
        "hub_or_balancing_authority": hub_or_ba,
        "year": year,
        "market_product": market_product,
        "expected_intervals": expected_intervals,
        "observed_intervals": observed_intervals,
        "valid_intervals": valid_intervals,
        "missing_intervals": missing_intervals,
        "duplicate_intervals": duplicate_intervals,
        "conflicts": conflict_intervals,
        "issue_flag_counts": issue_flag_count,
        "unit": unit,
        "timestamp_convention": timestamp_convention,
        "retrieval_provenance": retrieval_provenance,
        "sha256": sha256_hash,
        "bytes": bytes_count,
        "provisional": provisional,
        "eligibility_status": status,
        "rejection_reasons": "; ".join(reasons) if reasons else "NONE",
    }


def validate_selected_window_inputs(
    window_id: str,
    station_id: str,
    caiso_hub: str,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Any]:
    """Reusable acceptance check for selected event/control/ordinary windows.

    Status in Phase 2 is DEFERRED_TO_PHASE_3_AND_4 because no episodes or controls
    exist prior to Phase 3 heatwave detection.
    """
    return {
        "window_id": window_id,
        "station_id": station_id,
        "caiso_hub": caiso_hub,
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "status": "DEFERRED_TO_PHASE_3_AND_4",
        "reason": "Event catalogue and matched controls are generated during Phase 3 and scheduled in Phase 4.",
    }


def classify_caiso_archive(archive_path: Path | str) -> dict[str, Any]:
    """Inspect and classify a CAISO archive (.zip or .csv).

    Returns metadata dictionary with classification:
      - status: SUCCESS_DATA, SUCCESS_EMPTY, CAISO_ERROR_RESPONSE, INVALID_ARCHIVE, WRONG_PRODUCT, AUTH_REQUIRED
      - error_code: str | None
      - error_message: str | None
      - members: list[str]
      - valid_intervals_count: int
    """
    path = Path(archive_path)
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "status": "INVALID_ARCHIVE",
            "error_code": "EMPTY_OR_MISSING",
            "error_message": f"File is missing or zero bytes: {path}",
            "members": [],
            "valid_intervals_count": 0,
        }

    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if zf.testzip() is not None:
                    return {
                        "status": "INVALID_ARCHIVE",
                        "error_code": "CORRUPT_ZIP",
                        "error_message": "Zip archive corrupted (failed testzip)",
                        "members": [],
                        "valid_intervals_count": 0,
                    }
                members = zf.namelist()
                if not members:
                    return {
                        "status": "SUCCESS_EMPTY",
                        "error_code": None,
                        "error_message": "Zip archive contains no entries",
                        "members": [],
                        "valid_intervals_count": 0,
                    }

                # Check for XML error responses
                for m in members:
                    if m.endswith(".xml") or "ERROR" in m or "INVALID" in m:
                        try:
                            content = zf.read(m)
                            if b"<m:ERROR>" in content or b"INVALID_REQUEST" in m.encode("utf-8") or b"ERR_CODE" in content:
                                root = ET.fromstring(content)
                                err_code_el = root.find(".//{*}ERR_CODE")
                                err_desc_el = root.find(".//{*}ERR_DESC")
                                code = err_code_el.text if err_code_el is not None else "1000"
                                desc = err_desc_el.text if err_desc_el is not None else "No data returned for the specified selection"
                                return {
                                    "status": "CAISO_ERROR_RESPONSE",
                                    "error_code": code,
                                    "error_message": desc,
                                    "members": members,
                                    "valid_intervals_count": 0,
                                }
                        except Exception as e:
                            return {
                                "status": "CAISO_ERROR_RESPONSE",
                                "error_code": "XML_PARSE_ERROR",
                                "error_message": f"Could not parse XML error response: {e}",
                                "members": members,
                                "valid_intervals_count": 0,
                            }

                # Check CSV members
                csv_members = [m for m in members if m.endswith(".csv")]
                if not csv_members:
                    return {
                        "status": "WRONG_PRODUCT",
                        "error_code": "NO_CSV",
                        "error_message": f"No CSV members found in archive: {members}",
                        "members": members,
                        "valid_intervals_count": 0,
                    }

                # Check if CSV contains matching product headers
                total_lmp_rows = 0
                has_matching_headers = False
                for cm in csv_members:
                    # In CAISO GRP archives, only PRC_LMP_*_DAM_LMP_* contains the LMP prices; other files are MCE/MCC/MCL
                    if "_DAM_MCE_" in cm or "_DAM_MCC_" in cm or "_DAM_MCL_" in cm:
                        continue
                    with zf.open(cm) as cf:
                        # Quick check on header line
                        header_line = cf.readline().decode("utf-8", errors="replace")
                        fieldnames = [c.strip() for c in header_line.split(",")]
                        if "INTERVALSTARTTIME_GMT" in fieldnames and "MW" in fieldnames:
                            has_matching_headers = True
                            # Seek back and use pandas read_csv for high performance C-speed parsing
                            cf.seek(0)
                            use_cols = [c for c in ["INTERVALSTARTTIME_GMT", "NODE", "NODE_ID", "NODE_ID_XML", "MARKET_RUN_ID", "LMP_TYPE", "XML_DATA_ITEM", "MW"] if c in fieldnames]
                            df = pd.read_csv(cf, usecols=use_cols, dtype=str)
                            node_col = next((c for c in ["NODE", "NODE_ID", "NODE_ID_XML"] if c in df.columns), None)
                            if node_col:
                                df = df[df[node_col].isin(["TH_NP15_GEN-APND", "TH_ZP26_GEN-APND", "TH_SP15_GEN-APND"])]
                            if "MARKET_RUN_ID" in df.columns:
                                df = df[df["MARKET_RUN_ID"] == "DAM"]
                            if "LMP_TYPE" in df.columns:
                                df = df[df["LMP_TYPE"] == "LMP"]
                            if "XML_DATA_ITEM" in df.columns:
                                df = df[df["XML_DATA_ITEM"] == "LMP_PRC"]
                            total_lmp_rows += len(df)

                if not has_matching_headers:
                    return {
                        "status": "WRONG_PRODUCT",
                        "error_code": "MISSING_REQUIRED_COLUMNS",
                        "error_message": "CSV lacks INTERVALSTARTTIME_GMT or MW",
                        "members": members,
                        "valid_intervals_count": 0,
                    }

                if total_lmp_rows == 0:
                    return {
                        "status": "SUCCESS_EMPTY",
                        "error_code": None,
                        "error_message": "Archive has headers but contains zero matching DAM LMP_PRC rows",
                        "members": members,
                        "valid_intervals_count": 0,
                    }

                return {
                    "status": "SUCCESS_DATA",
                    "error_code": None,
                    "error_message": None,
                    "members": members,
                    "valid_intervals_count": total_lmp_rows,
                }
        except zipfile.BadZipFile:
            return {
                "status": "INVALID_ARCHIVE",
                "error_code": "BAD_ZIP",
                "error_message": "Bad Zip file",
                "members": [],
                "valid_intervals_count": 0,
            }
    elif path.suffix.lower() == ".csv":
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as cf:
                reader = csv.DictReader(cf)
                fieldnames = set(reader.fieldnames or [])
                if not ("INTERVALSTARTTIME_GMT" in fieldnames and "MW" in fieldnames):
                    return {
                        "status": "WRONG_PRODUCT",
                        "error_code": "MISSING_REQUIRED_COLUMNS",
                        "error_message": "CSV lacks required columns",
                        "members": [path.name],
                        "valid_intervals_count": 0,
                    }
                total_lmp_rows = sum(
                    1 for r in reader
                    if r.get("MARKET_RUN_ID") == "DAM" and r.get("LMP_TYPE") == "LMP" and r.get("XML_DATA_ITEM") == "LMP_PRC"
                )
                return {
                    "status": "SUCCESS_DATA" if total_lmp_rows > 0 else "SUCCESS_EMPTY",
                    "error_code": None,
                    "error_message": None,
                    "members": [path.name],
                    "valid_intervals_count": total_lmp_rows,
                }
        except Exception as e:
            return {
                "status": "INVALID_ARCHIVE",
                "error_code": "READ_ERROR",
                "error_message": str(e),
                "members": [path.name],
                "valid_intervals_count": 0,
            }

    return {
        "status": "INVALID_ARCHIVE",
        "error_code": "UNSUPPORTED_TYPE",
        "error_message": f"Unsupported file extension: {path.suffix}",
        "members": [],
        "valid_intervals_count": 0,
    }


def parse_caiso_archive_rows(
    archive_path: Path | str,
    target_nodes: Sequence[str] = ("TH_NP15_GEN-APND", "TH_ZP26_GEN-APND", "TH_SP15_GEN-APND"),
    market_run_id: str = "DAM",
    lmp_type: str = "LMP",
    xml_data_item: str = "LMP_PRC",
    source_identity: str | None = None,
) -> list[dict[str, Any]]:
    """Parse all valid price rows from a CAISO archive using header-driven dynamic DictReader.
    
    Extracts rows matching target_nodes, market_run_id, lmp_type, and xml_data_item.
    Normalizes timestamps to timezone-aware UTC interval start.
    Records source_file using repository/raw-relative source_identity.
    """
    path = Path(archive_path)
    file_id = source_identity if source_identity is not None else str(path)
    rows: list[dict[str, Any]] = []
    target_nodes_set = set(target_nodes)

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            csv_members = [m for m in zf.namelist() if m.endswith(".csv")]
            for cm in csv_members:
                if "_DAM_MCE_" in cm or "_DAM_MCC_" in cm or "_DAM_MCL_" in cm:
                    continue
                with zf.open(cm) as cf:
                    header_line = cf.readline().decode("utf-8", errors="replace")
                    fieldnames = [c.strip() for c in header_line.split(",")]
                    cf.seek(0)
                    use_cols = [c for c in ["INTERVALSTARTTIME_GMT", "NODE", "NODE_ID", "NODE_ID_XML", "MARKET_RUN_ID", "LMP_TYPE", "XML_DATA_ITEM", "MW"] if c in fieldnames]
                    df = pd.read_csv(cf, usecols=use_cols, dtype=str)
                    node_col = next((c for c in ["NODE", "NODE_ID", "NODE_ID_XML"] if c in df.columns), None)
                    if node_col and target_nodes_set:
                        df = df[df[node_col].isin(target_nodes_set)]
                    if "MARKET_RUN_ID" in df.columns:
                        df = df[df["MARKET_RUN_ID"] == market_run_id]
                    if "LMP_TYPE" in df.columns:
                        df = df[df["LMP_TYPE"] == lmp_type]
                    if "XML_DATA_ITEM" in df.columns:
                        df = df[df["XML_DATA_ITEM"] == xml_data_item]

                    for _, r in df.iterrows():
                        raw_ts = str(r.get("INTERVALSTARTTIME_GMT", "")).strip()
                        if not raw_ts or raw_ts == "nan":
                            continue
                        try:
                            ts_dt = datetime.fromisoformat(raw_ts)
                            ts_utc = ts_dt.astimezone(timezone.utc) if ts_dt.tzinfo else ts_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            continue

                        mw_str = str(r.get("MW", "")).strip()
                        if not mw_str or mw_str == "nan":
                            continue
                        try:
                            price_val = float(mw_str)
                        except ValueError:
                            continue

                        node_val = r.get(node_col) if node_col else r.get("NODE")
                        rows.append({
                            "timestamp_utc": ts_utc,
                            "node": node_val,
                            "market_run_id": r.get("MARKET_RUN_ID"),
                            "lmp_type": r.get("LMP_TYPE"),
                            "xml_data_item": r.get("XML_DATA_ITEM"),
                            "price_usd_per_mwh": price_val,
                            "source_file": file_id,
                        })
    elif path.suffix.lower() == ".csv":
        with open(path, "r", encoding="utf-8", errors="replace") as cf:
            reader = csv.DictReader(cf)
            for r in reader:
                node = r.get("NODE") or r.get("NODE_ID") or r.get("NODE_ID_XML")
                if target_nodes_set and node not in target_nodes_set:
                    continue
                if r.get("MARKET_RUN_ID") != market_run_id:
                    continue
                if r.get("LMP_TYPE") != lmp_type:
                    continue
                if r.get("XML_DATA_ITEM") != xml_data_item:
                    continue

                raw_ts = r.get("INTERVALSTARTTIME_GMT", "").strip()
                if not raw_ts:
                    continue
                try:
                    ts_dt = datetime.fromisoformat(raw_ts)
                    ts_utc = ts_dt.astimezone(timezone.utc) if ts_dt.tzinfo else ts_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                mw_str = r.get("MW", "").strip()
                if not mw_str:
                    continue
                try:
                    price_val = float(mw_str)
                except ValueError:
                    continue

                rows.append({
                    "timestamp_utc": ts_utc,
                    "node": node,
                    "market_run_id": r.get("MARKET_RUN_ID"),
                    "lmp_type": r.get("LMP_TYPE"),
                    "xml_data_item": r.get("XML_DATA_ITEM"),
                    "price_usd_per_mwh": price_val,
                    "source_file": file_id,
                })

    return rows


def build_caiso_coverage_for_hub_year(
    parsed_rows: list[dict[str, Any]],
    caiso_archive_info: dict[str, dict[str, Any]],
    hub_full: str,
    hub_code: str,
    year: int,
    expected_start_utc: datetime,
    expected_end_utc: datetime,
    is_provisional: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute deterministic CAISO coverage and gap inventory for a single hub-year.
    
    Returns (coverage_record, gap_record).
    """
    exp_intervals = int((expected_end_utc - expected_start_utc).total_seconds() / 3600)
    expected_grid = [expected_start_utc + timedelta(hours=i) for i in range(exp_intervals)]
    expected_set = set(expected_grid)

    # Filter rows matching hub and time window
    hub_rows = [
        r for r in parsed_rows
        if r.get("node") == hub_full and expected_start_utc <= r.get("timestamp_utc") < expected_end_utc
    ]
    obs_count = len(hub_rows)

    contributing_source_files: set[str] = set()
    used_archive_provenance: list[tuple[str, str]] = []  # (relative_path, sha256)
    total_bytes = 0

    if obs_count > 0:
        obs_df = pd.DataFrame(hub_rows)
        unique_ts_set = set(obs_df["timestamp_utc"].unique())
        duplicate_intervals = obs_count - len(unique_ts_set)
        dedup_df = obs_df.drop_duplicates(subset=["timestamp_utc"])
        valid_intervals = len(dedup_df)
        missing_intervals = exp_intervals - valid_intervals

        # Conflicts: identical timestamp with different prices
        conflicts = 0
        for _, grp in obs_df.groupby("timestamp_utc"):
            if grp["price_usd_per_mwh"].nunique() > 1:
                conflicts += 1

        contributing_source_files = set(obs_df["source_file"].unique())
        for rel_p in sorted(contributing_source_files):
            if rel_p in caiso_archive_info:
                ainfo = caiso_archive_info[rel_p]
                used_archive_provenance.append((rel_p, ainfo["sha256"]))
                total_bytes += ainfo["bytes"]

        missing_ts = sorted(list(expected_set - unique_ts_set))
    else:
        unique_ts_set = set()
        duplicate_intervals = 0
        valid_intervals = 0
        missing_intervals = exp_intervals
        conflicts = 0
        missing_ts = expected_grid

    # Contiguous missing ranges
    contiguous_ranges = []
    if missing_ts:
        r_start = missing_ts[0]
        prev = missing_ts[0]
        for cur in missing_ts[1:]:
            if cur == prev + timedelta(hours=1):
                prev = cur
            else:
                contiguous_ranges.append(f"{r_start.isoformat()} to {(prev + timedelta(hours=1)).isoformat()}")
                r_start = cur
                prev = cur
        contiguous_ranges.append(f"{r_start.isoformat()} to {(prev + timedelta(hours=1)).isoformat()}")

    gap_record = {
        "hub": hub_full,
        "hub_code": hub_code,
        "year": year,
        "expected_intervals": exp_intervals,
        "existing_valid_intervals": valid_intervals,
        "missing_intervals": missing_intervals,
        "first_missing_utc": missing_ts[0].isoformat() if missing_ts else "NONE",
        "last_missing_utc": missing_ts[-1].isoformat() if missing_ts else "NONE",
        "contiguous_missing_ranges_count": len(contiguous_ranges),
        "contiguous_missing_ranges": "; ".join(contiguous_ranges) if contiguous_ranges else "NONE",
    }

    # Canonical sequence composite hasher: relative_path + sha256
    canonical_hasher = hashlib.sha256()
    for rel_p, h in sorted(set(used_archive_provenance)):
        canonical_hasher.update(f"{rel_p}:{h}".encode("utf-8"))
    composite_hash = canonical_hasher.hexdigest()

    reasons: list[str] = []
    if valid_intervals < exp_intervals:
        reasons.append(
            f"Incomplete interval coverage: {valid_intervals}/{exp_intervals} ({100.0 * valid_intervals / exp_intervals:.1f}%)"
        )
    if conflicts > 0:
        reasons.append(f"Contains {conflicts} conflicting duplicate price interval(s)")

    cov_record = calculate_price_carbon_coverage_record(
        source_name="CAISO_OASIS_PRC_LMP",
        hub_or_ba=hub_full,
        year=year,
        market_product="DAM_LMP_PRC",
        expected_intervals=exp_intervals,
        observed_intervals=obs_count,
        valid_intervals=valid_intervals,
        missing_intervals=missing_intervals,
        duplicate_intervals=duplicate_intervals,
        conflict_intervals=conflicts,
        issue_flag_count=0,
        unit="USD/MWh",
        timestamp_convention="interval-start UTC",
        retrieval_provenance="CAISO OASIS SingleZip API v12 & Historical Group Archives",
        sha256_hash=composite_hash,
        bytes_count=total_bytes,
        provisional=is_provisional,
        rejection_reasons=reasons,
    )

    return cov_record, gap_record
