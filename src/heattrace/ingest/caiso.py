"""CAISO OASIS day-ahead hourly LMP data acquisition and parser."""

from __future__ import annotations

import csv
import io
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .manifest import record_provenance
from .coverage import compute_hourly_coverage

USER_AGENT = "HeatTrace-Research/0.1 (+https://github.com/siddharthbhakta/HeatTrace)"
CAISO_OASIS_BASE_URL = "https://oasis.caiso.com/oasisapi/SingleZip"


def build_caiso_oasis_url(
    queryname: str = "PRC_LMP",
    *,
    market_run_id: str = "DAM",
    node: str = "TH_NP15_GEN-APND",
    startdatetime: datetime,
    enddatetime: datetime,
    version: int = 12,
    resultformat: int = 6,
) -> str:
    """Format the CAISO OASIS SingleZip API request URL."""
    if startdatetime.tzinfo is None or enddatetime.tzinfo is None:
        raise ValueError("startdatetime and enddatetime must be timezone-aware")
    if startdatetime >= enddatetime:
        raise ValueError(f"startdatetime ({startdatetime}) must be before enddatetime ({enddatetime})")

    # Normalize aware datetimes to UTC
    start_utc = startdatetime.astimezone(timezone.utc)
    end_utc = enddatetime.astimezone(timezone.utc)

    # Validate alignment to complete hour
    if start_utc.minute != 0 or start_utc.second != 0 or start_utc.microsecond != 0:
        raise ValueError(f"startdatetime must be aligned to a complete hour, got {start_utc}")
    if end_utc.minute != 0 or end_utc.second != 0 or end_utc.microsecond != 0:
        raise ValueError(f"enddatetime must be aligned to a complete hour, got {end_utc}")

    start_str = start_utc.strftime("%Y%m%dT%H:%M-0000")
    end_str = end_utc.strftime("%Y%m%dT%H:%M-0000")

    params = {
        "enddatetime": end_str,
        "market_run_id": market_run_id,
        "node": node,
        "queryname": queryname,
        "resultformat": str(resultformat),
        "startdatetime": start_str,
        "version": str(version),
    }
    sorted_params = {k: params[k] for k in sorted(params.keys())}
    return f"{CAISO_OASIS_BASE_URL}?{urllib.parse.urlencode(sorted_params)}"


# Throttling policy: CAISO requests during batch or sequential operations must respect
# a minimum delay (default 5.0 seconds) to avoid 429 throttling and server load.
DEFAULT_CAISO_REQUEST_DELAY_SECONDS = 5.0
_last_caiso_request_time: float = 0.0


def throttle_caiso_request(min_delay: float = DEFAULT_CAISO_REQUEST_DELAY_SECONDS, sleep_fn: Any = time.sleep) -> None:
    """Enforce a minimum delay between live CAISO requests."""
    global _last_caiso_request_time
    now = time.time()
    elapsed = now - _last_caiso_request_time
    if _last_caiso_request_time > 0 and elapsed < min_delay:
        sleep_fn(min_delay - elapsed)
    _last_caiso_request_time = time.time()


def reset_caiso_throttle() -> None:
    """Reset the last request timestamp (useful for testing)."""
    global _last_caiso_request_time
    _last_caiso_request_time = 0.0


def validate_caiso_zip_file(
    file_path: str | Path,
    *,
    expected_node: str | None = None,
    expected_market: str = "DAM",
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
) -> bool:
    """Validate that a cached ZIP file is readable and strictly satisfies content requirements:
    - Must be a valid zip archive without corruption.
    - If expected_node, requested_start, and requested_end are provided, parses and validates:
      - Archive contains CSV data (not XML error).
      - Rows match expected_node and expected_market.
      - Exact hourly records cover [requested_start, requested_end).
    """
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
            if not names:
                return False
            has_valid_entry = any(n.endswith(".csv") or n.endswith(".xml") for n in names)
            if not has_valid_entry:
                return False
            if z.testzip() is not None:
                return False

        # If detailed identity parameters are provided, perform complete content validation
        if expected_node and requested_start and requested_end:
            rows, error_msg = parse_caiso_zip(path, expected_node=expected_node, expected_market=expected_market)
            if error_msg:
                return False
            lmp_rows = [r for r in rows if r["lmp_type"] == "LMP"]
            validate_caiso_lmp_rows(
                lmp_rows,
                expected_node=expected_node,
                expected_market=expected_market,
                requested_start=requested_start,
                requested_end=requested_end,
            )
        return True
    except Exception:
        return False


CAISO_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
MAX_CAISO_RETRY_DELAY_SECONDS = 30.0


def parse_retry_after(header_value: str | None, default_delay: float) -> float:
    """Parse HTTP Retry-After header as integer seconds or HTTP-date."""
    if not header_value:
        return default_delay
    val = header_value.strip()
    try:
        return float(val)
    except ValueError:
        pass
    import email.utils
    try:
        dt = email.utils.parsedate_to_datetime(val)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except Exception:
        return default_delay


def download_caiso_file(
    url: str,
    output_dir: str | Path,
    file_stem: str,
    *,
    expected_node: str | None = None,
    expected_market: str = "DAM",
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    sleep_fn: Any = time.sleep,
    throttle_delay: float = DEFAULT_CAISO_REQUEST_DELAY_SECONDS,
) -> tuple[Path, bool]:

    """Download and cache CAISO OASIS zip response unchanged.
    
    Retry Policy:
    - Retries only HTTP 429, 500, 502, 503, 504, URLError, and TimeoutError.
    - Fails immediately for all other HTTP status codes.
    - Fails immediately for malformed ZIP or validation failures without retrying.
    - Cleans up temporary files on any failure.
    - Parses Retry-After (numeric or HTTP date) bounded by MAX_CAISO_RETRY_DELAY_SECONDS.
    - Bounds exponential backoff to MAX_CAISO_RETRY_DELAY_SECONDS.
    - Uses injectable sleep_fn for testing.
    
    Returns (target_path, is_cache_hit).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_file = out_dir / f"{file_stem}.zip"

    if target_file.exists():
        if validate_caiso_zip_file(
            target_file,
            expected_node=expected_node,
            expected_market=expected_market,
            requested_start=requested_start,
            requested_end=requested_end,
        ):
            return target_file, True
        # If corrupt or mismatched, remove and safely reacquire
        target_file.unlink(missing_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        throttle_caiso_request(min_delay=throttle_delay, sleep_fn=sleep_fn)
        temp_file = target_file.with_suffix(f".tmp.{attempt}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                temp_file.write_bytes(content)
        except urllib.error.HTTPError as e:
            last_exc = e
            temp_file.unlink(missing_ok=True)
            if e.code not in CAISO_RETRYABLE_HTTP_CODES:
                raise RuntimeError(f"Non-retryable CAISO HTTP error {e.code}: {e.reason}") from e

            # Retryable error
            if attempt < max_retries - 1:
                base_delay = backoff_factor * (2 ** attempt)
                if e.code == 429:
                    raw_ra = e.headers.get("Retry-After") if hasattr(e, "headers") else None
                    delay = parse_retry_after(raw_ra, base_delay)
                else:
                    delay = base_delay
                delay = min(delay, MAX_CAISO_RETRY_DELAY_SECONDS)
                sleep_fn(delay)
                continue
            else:
                break
        except (urllib.error.URLError, TimeoutError) as e:
            last_exc = e
            temp_file.unlink(missing_ok=True)
            if attempt < max_retries - 1:
                delay = min(backoff_factor * (2 ** attempt), MAX_CAISO_RETRY_DELAY_SECONDS)
                sleep_fn(delay)
                continue
            else:
                break
        except Exception:
            temp_file.unlink(missing_ok=True)
            raise

        # Content validation: do NOT catch as transient network retry
        try:
            if not validate_caiso_zip_file(temp_file):
                temp_file.unlink(missing_ok=True)
                raise ValueError(f"Downloaded CAISO response from {url} is not a valid zip archive")
            temp_file.replace(target_file)
            return target_file, False
        except Exception:
            temp_file.unlink(missing_ok=True)
            raise

    raise RuntimeError(f"Failed to download CAISO OASIS response from {url}: {last_exc}") from last_exc



def parse_caiso_zip(
    zip_path_or_bytes: str | Path | bytes,
    expected_node: str = "TH_NP15_GEN-APND",
    expected_market: str = "DAM",
) -> tuple[list[dict[str, Any]], str | None]:
    """Parse CAISO ZIP file containing CSV or XML error/data.
    
    Returns (rows, error_message).
    """
    if isinstance(zip_path_or_bytes, (str, Path)):
        z = zipfile.ZipFile(zip_path_or_bytes)
    elif isinstance(zip_path_or_bytes, bytes):
        z = zipfile.ZipFile(io.BytesIO(zip_path_or_bytes))
    else:
        raise ValueError("Expected path or bytes for zip")

    names = z.namelist()
    if not names:
        return [], "Empty zip archive returned by CAISO OASIS"

    # Check for XML error reports
    for name in names:
        if name.endswith(".xml") or "ERROR" in name or "INVALID" in name:
            content = z.read(name).decode("utf-8", errors="replace")
            try:
                root = ET.fromstring(content)
                err_code = root.find(".//{*}ERR_CODE")
                err_desc = root.find(".//{*}ERR_DESC")
                if err_code is not None or err_desc is not None:
                    code = err_code.text if err_code is not None else "UNKNOWN"
                    desc = err_desc.text if err_desc is not None else "No description"
                    return [], f"CAISO OASIS API Error [{code}]: {desc}"
            except ET.ParseError:
                pass

    # Find CSV file
    csv_names = [n for n in names if n.endswith(".csv")]
    if not csv_names:
        return [], f"No CSV file found in CAISO ZIP. Contained: {names}"

    raw_csv = z.read(csv_names[0]).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows: list[dict[str, Any]] = []

    for r in reader:
        node_val = r.get("NODE") or r.get("NODE_ID") or r.get("NODE_ID_XML")
        market_val = r.get("MARKET_RUN_ID")
        if expected_node and node_val != expected_node:
            continue
        if expected_market and market_val != expected_market:
            continue

        lmp_type = r.get("LMP_TYPE", "")
        start_raw = r.get("INTERVALSTARTTIME_GMT", "").strip()
        end_raw = r.get("INTERVALENDTIME_GMT", "").strip()
        
        # CAISO GMT strings typically contain -00:00 or Z
        start_dt = datetime.fromisoformat(start_raw)
        end_dt = datetime.fromisoformat(end_raw)
        
        start_utc = start_dt.astimezone(timezone.utc) if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc) if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc)

        mw_val = float(r["MW"]) if r.get("MW") is not None and r["MW"] != "" else None

        rows.append({
            "group": r.get("GROUP", ""),
            "interval_end_utc": end_utc,
            "lmp_type": lmp_type,
            "market_run_id": market_val,
            "node": node_val,
            "price_usd_per_mwh": mw_val,
            "timestamp_utc": start_utc,
            "xml_data_item": r.get("XML_DATA_ITEM", ""),
        })

    return rows, None


def validate_caiso_lmp_rows(
    rows: list[dict[str, Any]],
    *,
    expected_node: str,
    expected_market: str,
    requested_start: datetime,
    requested_end: datetime,
) -> None:
    """Validate CAISO LMP rows without runtime assert statements.
    
    Enforces exact hourly timestamps:
    - Set of observed total-LMP timestamps must equal the expected hourly timestamp set exactly.
    - Number of total-LMP rows must equal the expected-hour count.
    - Rejects any sub-hourly timestamps (e.g. 00:30), unaligned timestamps, out-of-window timestamps,
      missing hours, duplicates, or intervals with duration != 3600 seconds.
    """
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested_start and requested_end must be timezone-aware")
    if requested_start >= requested_end:
        raise ValueError(f"requested_start ({requested_start}) must be before requested_end ({requested_end})")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    if start_utc.minute != 0 or start_utc.second != 0 or start_utc.microsecond != 0:
        raise ValueError(f"requested_start must be aligned to complete hour: {start_utc}")
    if end_utc.minute != 0 or end_utc.second != 0 or end_utc.microsecond != 0:
        raise ValueError(f"requested_end must be aligned to complete hour: {end_utc}")

    if not rows:
        raise ValueError(f"No total LMP rows found for node {expected_node} in interval [{start_utc}, {end_utc})")

    # Build exact expected hourly timestamps
    expected_hours: list[datetime] = []
    curr = start_utc
    while curr < end_utc:
        expected_hours.append(curr)
        curr += timedelta(hours=1)

    expected_set = set(expected_hours)

    if len(rows) != len(expected_hours):
        raise ValueError(
            f"Expected exactly {len(expected_hours)} total-LMP rows, but got {len(rows)}"
        )

    seen_timestamps: list[datetime] = []

    for i, r in enumerate(rows):
        if r.get("node") != expected_node:
            raise ValueError(f"Row {i}: unexpected node '{r.get('node')}', expected '{expected_node}'")
        if r.get("market_run_id") != expected_market:
            raise ValueError(f"Row {i}: unexpected market '{r.get('market_run_id')}', expected '{expected_market}'")
        if r.get("lmp_type") != "LMP":
            raise ValueError(f"Row {i}: expected LMP_TYPE 'LMP', got '{r.get('lmp_type')}'")

        ts_start = r.get("timestamp_utc")
        ts_end = r.get("interval_end_utc")
        if not isinstance(ts_start, datetime) or ts_start.tzinfo != timezone.utc:
            raise ValueError(f"Row {i}: timestamp_utc must be timezone-aware UTC datetime, got {ts_start}")
        if not isinstance(ts_end, datetime) or ts_end.tzinfo != timezone.utc:
            raise ValueError(f"Row {i}: interval_end_utc must be timezone-aware UTC datetime, got {ts_end}")

        # Duration check
        duration_sec = (ts_end - ts_start).total_seconds()
        if duration_sec != 3600:
            raise ValueError(f"Row {i}: interval duration must be exactly 3600 seconds (1 hour), got {duration_sec}s")

        # Alignment check: start must be on the hour
        if ts_start.minute != 0 or ts_start.second != 0 or ts_start.microsecond != 0:
            raise ValueError(f"Row {i}: timestamp_utc {ts_start} is not aligned to the top of the hour")
        if ts_end.minute != 0 or ts_end.second != 0 or ts_end.microsecond != 0:
            raise ValueError(f"Row {i}: interval_end_utc {ts_end} is not aligned to the top of the hour")

        if ts_start < start_utc or ts_start >= end_utc:
            raise ValueError(f"Row {i}: timestamp {ts_start} is outside requested interval [{start_utc}, {end_utc})")

        if ts_start in seen_timestamps:
            raise ValueError(f"Row {i}: duplicate hourly interval timestamp detected: {ts_start}")
        seen_timestamps.append(ts_start)

        price = r.get("price_usd_per_mwh")
        if price is None or not isinstance(price, (int, float)):
            raise ValueError(f"Row {i}: missing or non-numeric price_usd_per_mwh: {price}")
        if price < -1000.0 or price > 5000.0:
            raise ValueError(f"Row {i}: price {price} USD/MWh is outside reasonable market bounds (-1000 to +5000)")

    seen_set = set(seen_timestamps)
    if seen_set != expected_set:
        missing = expected_set - seen_set
        extra = seen_set - expected_set
        raise ValueError(
            f"Observed total-LMP timestamps do not match expected hours exactly. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )


def run_caiso_smoke_test(
    node: str = "TH_NP15_GEN-APND",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    *,
    data_dir: str | Path = "data/raw/caiso",
    manifest_path: str | Path = "data/manifests/raw_sources.jsonl",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run CAISO OASIS smoke test acquisition for 1 day of DAM hourly LMP."""
    if start_date is None:
        start_date = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    if end_date is None:
        end_date = datetime(2024, 6, 2, 0, 0, tzinfo=timezone.utc)

    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("start_date and end_date must be timezone-aware")
    if start_date >= end_date:
        raise ValueError(f"start_date ({start_date}) must be before end_date ({end_date})")

    start_utc = start_date.astimezone(timezone.utc)
    end_utc = end_date.astimezone(timezone.utc)

    url = build_caiso_oasis_url(
        queryname="PRC_LMP",
        market_run_id="DAM",
        node=node,
        startdatetime=start_utc,
        enddatetime=end_utc,
        version=12,
        resultformat=6,
    )

    file_stem = f"caiso_dam_lmp_{node}_{start_utc.strftime('%Y%m%d')}_{end_utc.strftime('%Y%m%d')}"

    sanitized_request = {
        "dataset": "PRC_LMP",
        "enddatetime": end_utc.isoformat(),
        "market_run_id": "DAM",
        "node": node,
        "provider": "CAISO",
        "resultformat": 6,
        "startdatetime": start_utc.isoformat(),
        "url": url,
        "version": 12,
    }

    if dry_run:
        return {
            "cache_hit": False,
            "dataset": "PRC_LMP",
            "provider": "CAISO",
            "request": sanitized_request,
            "status": "dry_run",
        }

    try:
        raw_path, is_cache_hit = download_caiso_file(
            url,
            data_dir,
            file_stem,
            expected_node=node,
            expected_market="DAM",
            requested_start=start_utc,
            requested_end=end_utc,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to download CAISO data: {e}") from e

    rows, error_msg = parse_caiso_zip(raw_path, expected_node=node, expected_market="DAM")
    if error_msg:
        # Check if error is CAISO historical rolling-window limitation (error code 1000)
        if "1000" in error_msg or "No data returned" in error_msg:
            return {
                "cache_hit": is_cache_hit,
                "dataset": "PRC_LMP",
                "diagnostic": (
                    f"CAISO SingleZip API returned error: {error_msg}. "
                    "SingleZip enforces a 39-month rolling historical window. "
                    "Queries for older historical dates require manual download via CAISO's "
                    "Historical OASIS Data Downloader (http://oasis.caiso.com/mrioasis/logon.do). "
                    "Save the resulting ZIP or CSV to data/raw/caiso/ and verify provenance."
                ),
                "error": error_msg,
                "provider": "CAISO",
                "raw_path": str(raw_path),
                "request": sanitized_request,
                "status": "blocked_pending_historical_oasis_download",
            }
        raise RuntimeError(f"CAISO OASIS query failed: {error_msg}")

    # Total LMP rows
    lmp_rows = [r for r in rows if r["lmp_type"] == "LMP"]
    validate_caiso_lmp_rows(
        lmp_rows,
        expected_node=node,
        expected_market="DAM",
        requested_start=start_utc,
        requested_end=end_utc,
    )

    # Write provenance record only after source verification passes
    manifest_record = record_provenance(
        manifest_path,
        raw_path,
        provider="CAISO",
        dataset="PRC_LMP",
        request=sanitized_request,
        is_cache_hit=is_cache_hit,
    )

    timestamps = [r["timestamp_utc"] for r in lmp_rows]
    coverage = compute_hourly_coverage(
        timestamps,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    return {
        "cache_hit": is_cache_hit,
        "coverage": coverage,
        "dataset": "PRC_LMP",
        "manifest_record": manifest_record,
        "provider": "CAISO",
        "raw_path": str(raw_path),
        "sample_rows_count": len(lmp_rows),
        "status": "success",
    }
