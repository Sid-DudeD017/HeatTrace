"""NOAA GHCNh (Global Historical Climatology Network hourly) data acquisition and parser."""

from __future__ import annotations

import csv
import io
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .manifest import record_provenance
from .coverage import compute_hourly_coverage

USER_AGENT = "HeatTrace-Research/0.1 (+https://github.com/siddharthbhakta/HeatTrace)"
NOAA_S3_BASE_URL = "https://noaa-ghcnh-pds.s3.amazonaws.com/hourly/access/by-year"


def get_ghcnh_url(station_id: str, year: int) -> str:
    """Construct the official NOAA NODD S3 URL for a station and year PSV file."""
    return f"{NOAA_S3_BASE_URL}/{year}/psv/GHCNh_{station_id}_{year}.psv"


def validate_noaa_psv_file(file_path: str | Path, expected_station: str, expected_year: int) -> bool:
    """Validate that a cached PSV file contains the expected header and matches station and year."""
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            header_line = f.readline()
            if not header_line.startswith("STATION|"):
                return False
            first_data_line = f.readline()
            if not first_data_line:
                return False
            parts = first_data_line.split("|")
            if len(parts) < 4:
                return False
            if parts[0] != expected_station:
                return False
            # Check year
            if parts[3] != str(expected_year):
                return False
        return True
    except Exception:
        return False


def download_ghcnh_file(
    station_id: str,
    year: int,
    output_dir: str | Path,
    *,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
) -> tuple[Path, bool]:
    """Download full station-year PSV file, caching it on disk.
    
    Returns (target_path, is_cache_hit).
    Validates cache integrity before returning.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_file = out_dir / f"GHCNh_{station_id}_{year}.psv"

    if target_file.exists():
        if validate_noaa_psv_file(target_file, station_id, year):
            return target_file, True
        # If corrupt or invalid, safely remove and re-acquire
        target_file.unlink(missing_ok=True)

    url = get_ghcnh_url(station_id, year)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                temp_file = target_file.with_suffix(".tmp")
                temp_file.write_bytes(content)
                if not validate_noaa_psv_file(temp_file, station_id, year):
                    temp_file.unlink(missing_ok=True)
                    raise ValueError(f"Downloaded NOAA GHCNh file from {url} failed validation")
                temp_file.replace(target_file)
                return target_file, False
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(backoff_factor * (2 ** attempt))

    raise RuntimeError(f"Failed to download NOAA GHCNh file from {url}: {last_exc}") from last_exc


def parse_ghcnh_psv(
    psv_content_or_path: str | Path,
    *,
    filter_date_start: datetime | None = None,
    filter_date_end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Parse GHCNh PSV format and extract observations.
    
    Preserves quality codes and metadata.
    Normalizes timestamps to UTC timezone-aware datetimes.
    Note: NOAA GHCNh DATE strings (e.g. 2022-01-01T00:00:00) represent UTC observation times
    per NOAA NCEI GHCNh documentation; timestamps without explicit offsets are assigned UTC tzinfo.
    Any timestamp with an explicit offset is converted to UTC using .astimezone(timezone.utc).
    """
    if filter_date_start is not None and filter_date_start.tzinfo is None:
        raise ValueError("filter_date_start must be timezone-aware")
    if filter_date_end is not None and filter_date_end.tzinfo is None:
        raise ValueError("filter_date_end must be timezone-aware")
    if filter_date_start is not None and filter_date_end is not None and filter_date_start >= filter_date_end:
        raise ValueError(f"filter_date_start ({filter_date_start}) must be before filter_date_end ({filter_date_end})")

    filter_start_utc = filter_date_start.astimezone(timezone.utc) if filter_date_start else None
    filter_end_utc = filter_date_end.astimezone(timezone.utc) if filter_date_end else None

    if isinstance(psv_content_or_path, Path):
        handle = psv_content_or_path.open("r", encoding="utf-8", errors="replace")
        close_handle = True
    elif isinstance(psv_content_or_path, str):
        if "\n" not in psv_content_or_path and Path(psv_content_or_path).exists():
            handle = Path(psv_content_or_path).open("r", encoding="utf-8", errors="replace")
            close_handle = True
        else:
            handle = io.StringIO(psv_content_or_path)
            close_handle = False
    else:
        raise ValueError("psv_content_or_path must be a file path or PSV string")

    try:
        reader = csv.DictReader(handle, delimiter="|")
        rows: list[dict[str, Any]] = []

        for r in reader:
            date_str = r.get("DATE", "").strip()
            if not date_str:
                y = int(r["Year"])
                m = int(r["Month"])
                d = int(r["Day"])
                h = int(r["Hour"])
                mi = int(r["Minute"])
                ts_utc = datetime(y, m, d, h, mi, tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(date_str)
                if dt.tzinfo is not None:
                    ts_utc = dt.astimezone(timezone.utc)
                else:
                    # GHCNh standard: all observation timestamps are UTC
                    ts_utc = dt.replace(tzinfo=timezone.utc)

            if filter_start_utc and ts_utc < filter_start_utc:
                continue
            if filter_end_utc and ts_utc >= filter_end_utc:
                continue

            temp_raw = r.get("temperature", "").strip()
            temp_c = float(temp_raw) if temp_raw != "" else None
            quality_code = r.get("temperature_Quality_Code", "").strip()
            meas_code = r.get("temperature_Measurement_Code", "").strip()
            report_type = r.get("temperature_Report_Type", "").strip()
            source_code = r.get("temperature_Source_Code", "").strip()

            rows.append({
                "station_id": r.get("STATION", "").strip(),
                "station_name": r.get("Station_name", "").strip(),
                "timestamp_utc": ts_utc,
                "temperature_c": temp_c,
                "temperature_quality_code": quality_code,
                "temperature_measurement_code": meas_code,
                "temperature_report_type": report_type,
                "temperature_source_code": source_code,
                "latitude": float(r["LATITUDE"]) if r.get("LATITUDE") else None,
                "longitude": float(r["LONGITUDE"]) if r.get("LONGITUDE") else None,
                "elevation": float(r["ELEVATION"]) if r.get("ELEVATION") else None,
            })
        return rows
    finally:
        if close_handle:
            handle.close()


def validate_noaa_sample_rows(
    rows: list[dict[str, Any]],
    *,
    expected_station: str,
    requested_start: datetime,
    requested_end: datetime,
) -> None:
    """Validate NOAA sample rows without runtime assert statements."""
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested_start and requested_end must be timezone-aware")
    if requested_start >= requested_end:
        raise ValueError(f"requested_start ({requested_start}) must be before requested_end ({requested_end})")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    if not rows:
        raise ValueError(f"No records found for station {expected_station} in interval [{start_utc}, {end_utc})")

    for i, row in enumerate(rows):
        if row.get("station_id") != expected_station:
            raise ValueError(f"Row {i}: unexpected station '{row.get('station_id')}', expected '{expected_station}'")
        
        ts = row.get("timestamp_utc")
        if not isinstance(ts, datetime) or ts.tzinfo is None:
            raise ValueError(f"Row {i}: timestamp must be a timezone-aware UTC datetime, got {ts}")
        if ts.tzinfo != timezone.utc:
            raise ValueError(f"Row {i}: timestamp timezone must be UTC, got {ts.tzinfo}")
        if ts < start_utc or ts >= end_utc:
            raise ValueError(f"Row {i}: timestamp {ts} is outside requested interval [{start_utc}, {end_utc})")

        if "temperature_quality_code" not in row:
            raise ValueError(f"Row {i}: missing temperature_quality_code field")

        temp = row.get("temperature_c")
        if temp is not None:
            if not isinstance(temp, (int, float)):
                raise ValueError(f"Row {i}: temperature_c must be numeric or None, got {type(temp)}")
            if temp < -60.0 or temp > 65.0:
                raise ValueError(f"Row {i}: temperature_c {temp}°C is outside plausible terrestrial bounds (-60 to +65°C)")


# =========================================================================
# NOAA GHCNh Quality Code Policy (Authoritative)
# =========================================================================
# GHCNh aggregates observations across ~110 international data streams.
# Quality codes are source-dependent according to NCEI GHCNh Documentation:
# - Blank ('') : Unflagged observation or passed automated quality baseline.
# - '1'        : Value passed automated/manual quality checks.
# - '5'        : Passed/acceptable in USAF / international surface streams (e.g. sources 313, 314, 343).
# - 'A'        : Passed / accepted in specific reporting streams.
# - 'Passed'   : Explicit passed indicator in processed representations.
#
# Explicitly rejected codes (failed / erroneous):
# - '2'        : Suspect / questionable / failed consistency.
# - '3', '4', '6', '7', 'Failed': Failed quality check / erroneous.
#
# Conservative policy:
# Any code not explicitly accepted or unflagged is treated as unresolved/conservative rather than
# assuming global acceptance across heterogeneous GHCNh sources.
NOAA_ACCEPTED_QUALITY_CODES = frozenset({"", "1", "5", "A", "Passed", "passed"})
NOAA_REJECTED_QUALITY_CODES = frozenset({"2", "3", "4", "6", "7", "Failed", "failed"})


def check_noaa_temperature_quality(quality_code: str) -> str:
    """Evaluate a NOAA GHCNh temperature quality code with source-stream-aware policy.
    
    Returns:
      'accepted' if code is in NOAA_ACCEPTED_QUALITY_CODES (e.g. unflagged '' or passed '1', '5', 'A').
      'rejected' if code is in NOAA_REJECTED_QUALITY_CODES (suspect or failed checks).
      'unknown'  otherwise (treated conservatively / unresolved rather than assumed valid).
    """
    qc_clean = (quality_code or "").strip()
    if qc_clean in NOAA_ACCEPTED_QUALITY_CODES:
        return "accepted"
    if qc_clean in NOAA_REJECTED_QUALITY_CODES:
        return "rejected"
    return "unknown"


def get_local_day_utc_bounds(
    local_date_str: str,
    target_timezone: str = "America/Los_Angeles",
) -> tuple[datetime, datetime, float]:
    """Convert local calendar day [midnight, next midnight) to half-open UTC interval [start_utc, end_utc).
    
    Correctly accounts for Daylight Saving Time (DST):
    - Normal day: 24.0 hours
    - Spring-forward day: 23.0 hours
    - Fall-back day: 25.0 hours
    
    Returns (start_utc, end_utc, expected_hours).
    """
    from datetime import date
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(target_timezone)
    y, m, d = [int(p) for p in local_date_str.split("-")]
    curr_date = date(y, m, d)
    next_date = curr_date + timedelta(days=1)

    t0_loc = datetime(curr_date.year, curr_date.month, curr_date.day, 0, 0, tzinfo=tz)
    t1_loc = datetime(next_date.year, next_date.month, next_date.day, 0, 0, tzinfo=tz)

    start_utc = t0_loc.astimezone(timezone.utc)
    end_utc = t1_loc.astimezone(timezone.utc)
    hours = (end_utc - start_utc).total_seconds() / 3600.0
    return start_utc, end_utc, hours


def extract_daily_maxima(
    rows: list[dict[str, Any]],
    *,
    target_timezone: str = "America/Los_Angeles",
) -> list[dict[str, Any]]:
    """Extract daily maximum temperature for each calendar day in the target timezone.

    Policy:
    - Observations are grouped by calendar day using target_timezone (never silently assumes UTC).
      Local station days align with meteorological diurnal heating cycles.
    - Quality Code Policy:
      - Validates each observation using check_noaa_temperature_quality.
      - 'accepted' codes ('', '1', '5', 'A', 'Passed') are retained.
      - 'rejected' codes ('2', '3', '4', '6', '7', 'Failed') or None temperatures are excluded.
      - 'unknown' codes raise ValueError to prevent silently ingesting unverified flags.
    - Deterministic Duplicate-Timestamp Handling:
      - Observations are grouped by exact UTC timestamp.
      - If duplicate observations have identical temperatures, one is retained and duplicate_count incremented.
      - If duplicate observations have conflicting temperatures:
        - Resolves using an explicit HeatTrace project policy for NOAA Report Types (not an official NOAA standard):
          Regular aviation METAR reports (FM15) / SPECI (FM16) are prioritized over generic synoptic (FM12) reports.
        - If report types agree or priority does not break the tie, uses a conservative policy:
          Chooses the higher temperature (max) to avoid accidentally underestimating the daily maximum,
          marks has_conflicts=True, and increments conflict_count.
      - Returns metadata including duplicate_observation_count and conflict_observation_count.
    """
    if not rows:
        raise ValueError("Cannot extract daily maxima from empty observation list")

    from zoneinfo import ZoneInfo
    tz = ZoneInfo(target_timezone)

    # Group valid observations by local calendar day (YYYY-MM-DD)
    # day_key -> list of raw observation rows
    days_map: dict[str, list[dict[str, Any]]] = {}
    stations_map: dict[str, str] = {}

    for r in rows:
        st_id = r.get("station_id", "")
        ts_utc = r.get("timestamp_utc")
        if not isinstance(ts_utc, datetime) or ts_utc.tzinfo is None:
            raise ValueError(f"Invalid timestamp_utc in row: {ts_utc}")

        ts_utc = ts_utc.astimezone(timezone.utc)
        ts_loc = ts_utc.astimezone(tz)
        day_key = ts_loc.strftime("%Y-%m-%d")

        if day_key not in days_map:
            days_map[day_key] = []
        if day_key not in stations_map and st_id:
            stations_map[day_key] = st_id

        temp = r.get("temperature_c")
        qc = str(r.get("temperature_quality_code", ""))

        # Check quality code
        qc_status = check_noaa_temperature_quality(qc)
        if qc_status == "unknown":
            raise ValueError(
                f"Unknown NOAA temperature quality code '{qc}' at {ts_utc.isoformat()} for station {st_id}. "
                "Must be an authoritative NOAA code."
            )
        if qc_status == "rejected" or temp is None:
            continue

        days_map[day_key].append(r)

    # Report type preference order: FM15 (METAR) > FM16 (SPECI) > FM12 (SYNOP) > other
    REPORT_PREFERENCE = {"FM15": 3, "FM16": 2, "FM12": 1}

    results: list[dict[str, Any]] = []
    for day_key in sorted(days_map.keys()):
        obs_rows = days_map[day_key]
        if not obs_rows:
            raise ValueError(f"No valid temperature observations found for local date {day_key} in {target_timezone}")

        # Group by exact UTC timestamp to handle duplicates deterministically
        by_ts: dict[datetime, list[dict[str, Any]]] = {}
        for r in obs_rows:
            ts = r["timestamp_utc"].astimezone(timezone.utc)
            by_ts.setdefault(ts, []).append(r)

        deduped: list[tuple[float, datetime]] = []
        duplicate_count = 0
        conflict_count = 0

        for ts in sorted(by_ts.keys()):
            ts_group = by_ts[ts]
            if len(ts_group) == 1:
                deduped.append((float(ts_group[0]["temperature_c"]), ts))
            else:
                # Multiple observations for same timestamp
                duplicate_count += len(ts_group) - 1
                temps = [float(x["temperature_c"]) for x in ts_group]
                all_same_temp = all(abs(t - temps[0]) < 1e-6 for t in temps)
                if all_same_temp:
                    deduped.append((temps[0], ts))
                else:
                    # Conflicting temperature values at same timestamp
                    conflict_count += 1
                    # Attempt report-type priority resolution
                    sorted_by_report = sorted(
                        ts_group,
                        key=lambda x: REPORT_PREFERENCE.get(str(x.get("temperature_report_type", "")).strip(), 0),
                        reverse=True,
                    )
                    top_report = str(sorted_by_report[0].get("temperature_report_type", "")).strip()
                    second_report = str(sorted_by_report[1].get("temperature_report_type", "")).strip()

                    top_pref = REPORT_PREFERENCE.get(top_report, 0)
                    second_pref = REPORT_PREFERENCE.get(second_report, 0)

                    if top_pref > second_pref:
                        chosen_temp = float(sorted_by_report[0]["temperature_c"])
                    else:
                        # Conservative tie-break: take the max temperature so daily max is not underestimated
                        chosen_temp = max(temps)

                    deduped.append((chosen_temp, ts))

        max_temp = max(t for t, dt in deduped)
        max_ts_list = sorted([dt.isoformat() for t, dt in deduped if abs(t - max_temp) < 1e-6])

        results.append({
            "conflict_observation_count": conflict_count,
            "daily_max_temperature_c": max_temp,
            "duplicate_observation_count": duplicate_count,
            "local_date": day_key,
            "quality_status": "valid",
            "station_id": stations_map.get(day_key, rows[0].get("station_id", "")),
            "timestamps_utc": max_ts_list,
            "timezone": target_timezone,
            "valid_observation_count": len(deduped),
        })

    return results



def run_noaa_smoke_test(
    station_id: str = "USW00023234",
    year: int = 2022,
    day_start: datetime | None = None,
    day_end: datetime | None = None,
    *,
    data_dir: str | Path = "data/raw/noaa",
    manifest_path: str | Path = "data/manifests/raw_sources.jsonl",
    target_timezone: str = "America/Los_Angeles",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run NOAA GHCNh smoke test acquisition for one station, year, and single day."""
    if day_start is None:
        day_start = datetime(year, 6, 1, 0, 0, tzinfo=timezone.utc)
    if day_end is None:
        day_end = datetime(year, 6, 2, 0, 0, tzinfo=timezone.utc)

    if day_start.tzinfo is None or day_end.tzinfo is None:
        raise ValueError("day_start and day_end must be timezone-aware")
    if day_start >= day_end:
        raise ValueError(f"day_start ({day_start}) must be before day_end ({day_end})")

    start_utc = day_start.astimezone(timezone.utc)
    end_utc = day_end.astimezone(timezone.utc)

    url = get_ghcnh_url(station_id, year)
    sanitized_request = {
        "dataset": "GHCNh",
        "provider": "NOAA",
        "sample_day_end": end_utc.isoformat(),
        "sample_day_start": start_utc.isoformat(),
        "station_id": station_id,
        "url": url,
        "year": year,
    }

    if dry_run:
        return {
            "cache_hit": False,
            "dataset": "GHCNh",
            "provider": "NOAA",
            "request": sanitized_request,
            "status": "dry_run",
        }

    raw_path, is_cache_hit = download_ghcnh_file(station_id, year, data_dir)

    # Parse and verify the 1-day sample
    sample_rows = parse_ghcnh_psv(raw_path, filter_date_start=start_utc, filter_date_end=end_utc)
    validate_noaa_sample_rows(
        sample_rows,
        expected_station=station_id,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    # Extract daily maxima for the sample
    daily_maxima = extract_daily_maxima(sample_rows, target_timezone=target_timezone)

    # Write provenance record only after source verification passes
    manifest_record = record_provenance(
        manifest_path,
        raw_path,
        provider="NOAA",
        dataset="GHCNh",
        request=sanitized_request,
        is_cache_hit=is_cache_hit,
    )

    timestamps = [r["timestamp_utc"] for r in sample_rows]
    coverage = compute_hourly_coverage(
        timestamps,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    return {
        "cache_hit": is_cache_hit,
        "coverage": coverage,
        "daily_maxima": daily_maxima,
        "dataset": "GHCNh",
        "manifest_record": manifest_record,
        "provider": "NOAA",
        "raw_path": str(raw_path),
        "sample_rows_count": len(sample_rows),
        "status": "success",
    }
