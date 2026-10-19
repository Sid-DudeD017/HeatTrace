from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .manifest import record_provenance
from .coverage import compute_hourly_coverage

USER_AGENT = "HeatTrace-Research/0.1 (+https://github.com/siddharthbhakta/HeatTrace)"
EIA_REGION_DATA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data"
EIA_FUEL_TYPE_DATA_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data"
EIA_GRID_MONITOR_DASHBOARD_URL = "https://www.eia.gov/electricity/gridmonitor/"
DEFAULT_EIA_API_TIMEOUT_SECONDS = 120.0


def get_eia_api_key() -> str | None:
    """Read EIA_API_KEY from environment without logging or persisting."""
    key = os.environ.get("EIA_API_KEY", "").strip()
    return key if key else None


def redact_api_key(url_or_text: str, api_key: str | None = None) -> str:
    """Redact EIA API key from any URL or error string."""
    if not url_or_text:
        return ""
    if api_key and api_key in url_or_text:
        url_or_text = url_or_text.replace(api_key, "[REDACTED]")
    import re
    return re.sub(r'api_key=[^&"\s]+', 'api_key=[REDACTED]', url_or_text)


def build_eia_query_params(
    balancing_authority: str,
    requested_start: datetime,
    requested_end: datetime,
    *,
    api_key: str | None = None,
) -> list[tuple[str, str]]:
    """Build generic query parameters for EIA API v2 region-data.
    
    Translates half-open [requested_start, requested_end) into EIA's inclusive date bounds:
    - start is requested_start (e.g. 2022-06-01T00)
    - end is requested_end minus 1 hour (e.g. 2022-06-01T23)
    
    Explicitly requests both demand (D) and net generation (NG) using repeated
    facets[type][] parameters.
    
    Requires:
    - Timezone-aware start and end datetimes.
    - start < end.
    - Boundaries aligned to full hours (minute=0, second=0, microsecond=0).
    """
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested_start and requested_end must be timezone-aware")
    if requested_start >= requested_end:
        raise ValueError(f"requested_start ({requested_start}) must be before requested_end ({requested_end})")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    if start_utc.minute != 0 or start_utc.second != 0 or start_utc.microsecond != 0:
        raise ValueError(f"requested_start must be aligned to a full hour, got {start_utc}")
    if end_utc.minute != 0 or end_utc.second != 0 or end_utc.microsecond != 0:
        raise ValueError(f"requested_end must be aligned to a full hour, got {end_utc}")

    # Inclusive end period in EIA API v2
    inclusive_end = end_utc - timedelta(hours=1)

    # Use a deterministic list of (key, value) pairs sorted by key, then value
    params: list[tuple[str, str]] = [
        ("data[0]", "value"),
        ("end", inclusive_end.strftime("%Y-%m-%dT%H")),
        ("facets[respondent][]", balancing_authority),
        ("facets[type][]", "D"),
        ("facets[type][]", "NG"),
        ("frequency", "hourly"),
        ("start", start_utc.strftime("%Y-%m-%dT%H")),
    ]
    if api_key:
        params.append(("api_key", api_key))

    # Deterministic sorting for reproducible request identity and manifest deduplication
    params.sort(key=lambda kv: (kv[0], kv[1]))
    return params


def build_eia_region_url(
    balancing_authority: str,
    requested_start: datetime,
    requested_end: datetime,
    *,
    api_key: str | None = None,
) -> str:
    """Format the EIA region-data API request URL with translated inclusive bounds and repeated type facets."""
    params = build_eia_query_params(
        balancing_authority,
        requested_start,
        requested_end,
        api_key=api_key,
    )
    query_str = urllib.parse.urlencode(params, doseq=True)
    return f"{EIA_REGION_DATA_URL}?{query_str}"


def parse_numeric_value(val: Any, record_index: int) -> float:
    """Parse numeric values from EIA API v2 response.
    
    Accepts:
    - Floats and ints (e.g. 24500, -125.5, 0)
    - Valid numeric strings (e.g. "24500", "-125.5", "0")
    
    Rejects:
    - Empty strings
    - None / null values
    - Booleans (True / False)
    - NaN and Infinity
    - Non-numeric strings
    - Implausible values outside [-50000.0, 100000.0] MW
    """
    if val is None:
        raise ValueError(f"Record {record_index}: missing required numeric value (null)")
    if isinstance(val, bool):
        raise ValueError(f"Record {record_index}: boolean values not accepted as numeric: {val}")

    if isinstance(val, (int, float)):
        num = float(val)
    elif isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            raise ValueError(f"Record {record_index}: empty numeric string")
        try:
            num = float(val_str)
        except ValueError as e:
            raise ValueError(f"Record {record_index}: invalid nonnumeric string '{val}': {e}") from e
    else:
        raise ValueError(f"Record {record_index}: unsupported value type {type(val).__name__}: {val}")

    if math.isnan(num) or math.isinf(num):
        raise ValueError(f"Record {record_index}: NaN and Infinity values not accepted: {num}")

    if num < -50000.0 or num > 100000.0:
        raise ValueError(f"Record {record_index}: value {num} MW is outside plausible BA bounds (-50000 to +100000)")

    return num


def parse_emissions_numeric_value(val: Any, record_index: int) -> float:
    """Parse numeric values specifically for CO2 emissions.
    
    Accepts:
    - Finite floats and ints (e.g. 1200.5, 0)
    - Valid numeric strings (e.g. "1200.5", "0")
    
    Rejects:
    - Empty strings
    - None / null values
    - Booleans (True / False)
    - NaN and Infinity
    - Non-numeric strings
    - Negative emissions values (< 0.0)
    """
    if val is None:
        raise ValueError(f"Record {record_index}: missing required emissions numeric value (null)")
    if isinstance(val, bool):
        raise ValueError(f"Record {record_index}: boolean values not accepted as numeric emissions: {val}")

    if isinstance(val, (int, float)):
        num = float(val)
    elif isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            raise ValueError(f"Record {record_index}: empty numeric string for emissions")
        try:
            num = float(val_str)
        except ValueError as e:
            raise ValueError(f"Record {record_index}: invalid nonnumeric emissions string '{val}': {e}") from e
    else:
        raise ValueError(f"Record {record_index}: unsupported emissions value type {type(val).__name__}: {val}")

    if math.isnan(num) or math.isinf(num):
        raise ValueError(f"Record {record_index}: NaN and Infinity values not accepted for emissions: {num}")

    if num < 0.0:
        raise ValueError(f"Record {record_index}: negative emissions value not allowed: {num}")

    return num


def validate_eia_json_cache(
    json_path: Path,
    expected_ba: str,
    requested_start: datetime,
    requested_end: datetime,
) -> bool:
    """Validate that a cached EIA JSON file exists, is non-empty, and satisfies schema requirements."""
    if not json_path.exists() or json_path.stat().st_size == 0:
        return False
    try:
        content = json_path.read_bytes()
        parse_and_validate_eia_json(
            content,
            expected_ba=expected_ba,
            requested_start=requested_start,
            requested_end=requested_end,
        )
        return True
    except Exception:
        return False


def validate_eia_metric_rows(
    rows: list[dict[str, Any]],
    *,
    metric_name: str,
    expected_ba: str,
    requested_start: datetime,
    requested_end: datetime,
) -> None:
    """Validate that a signal has exactly one record per expected hourly interval."""
    expected_hours: list[datetime] = []
    curr = requested_start
    while curr < requested_end:
        expected_hours.append(curr)
        curr += timedelta(hours=1)

    expected_set = set(expected_hours)
    seen_timestamps: list[datetime] = []

    for i, r in enumerate(rows):
        if r.get("balancing_authority") != expected_ba:
            raise ValueError(f"{metric_name} row {i}: wrong balancing authority '{r.get('balancing_authority')}', expected '{expected_ba}'")

        ts = r.get("timestamp_utc")
        if not isinstance(ts, datetime) or ts.tzinfo != timezone.utc:
            raise ValueError(f"{metric_name} row {i}: timestamp must be timezone-aware UTC datetime, got {ts}")

        if ts.minute != 0 or ts.second != 0 or ts.microsecond != 0:
            raise ValueError(f"{metric_name} row {i}: timestamp {ts} is not aligned to the full hour")

        if ts < requested_start or ts >= requested_end:
            raise ValueError(f"{metric_name} row {i}: timestamp {ts} is outside requested interval [{requested_start}, {requested_end})")

        if ts in seen_timestamps:
            raise ValueError(f"{metric_name} row {i}: duplicate record detected for timestamp {ts}")
        seen_timestamps.append(ts)

    seen_set = set(seen_timestamps)
    if seen_set != expected_set:
        missing = expected_set - seen_set
        extra = seen_set - expected_set
        raise ValueError(
            f"Incomplete {metric_name} signal for BA {expected_ba}: missing {len(missing)} hours: {sorted(missing)[:3]}..., extra {len(extra)} hours: {sorted(extra)[:3]}..."
        )


def parse_and_validate_eia_json(
    raw_json_str_or_bytes: str | bytes,
    *,
    expected_ba: str = "CISO",
    requested_start: datetime,
    requested_end: datetime,
) -> dict[str, Any]:
    """Parse and validate EIA API v2 JSON response.
    
    Verifies HTTP/API error objects, structure, expected BA, interval boundaries,
    and extracts complete series for demand (D) and net generation (NG).
    """
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested_start and requested_end must be timezone-aware")
    if requested_start >= requested_end:
        raise ValueError(f"requested_start ({requested_start}) must be before requested_end ({requested_end})")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    if start_utc.minute != 0 or start_utc.second != 0 or start_utc.microsecond != 0:
        raise ValueError(f"requested_start must be aligned to a full hour: {start_utc}")
    if end_utc.minute != 0 or end_utc.second != 0 or end_utc.microsecond != 0:
        raise ValueError(f"requested_end must be aligned to a full hour: {end_utc}")

    if isinstance(raw_json_str_or_bytes, bytes):
        raw_str = raw_json_str_or_bytes.decode("utf-8", errors="replace")
    else:
        raw_str = str(raw_json_str_or_bytes)

    try:
        data = json.loads(raw_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed EIA response: invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Malformed EIA response: root payload must be a JSON object")

    # Detect EIA API error response objects
    if "error" in data:
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"EIA API error: {msg}")

    if "response" not in data or not isinstance(data["response"], dict):
        raise ValueError("Malformed EIA response: missing 'response' object")

    resp_obj = data["response"]
    if "data" not in resp_obj or not isinstance(resp_obj["data"], list):
        raise ValueError("Malformed EIA response: missing 'response.data' list")

    records = resp_obj["data"]
    if not records:
        raise ValueError("EIA API returned empty results for the requested query")

    demand_rows: list[dict[str, Any]] = []
    net_gen_rows: list[dict[str, Any]] = []

    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise ValueError(f"Record {i}: item in 'data' is not a JSON object")

        for req_field in ("period", "respondent", "type", "value"):
            if req_field not in r:
                raise ValueError(f"Record {i}: missing required field '{req_field}'")

        respondent = r["respondent"]
        if respondent != expected_ba:
            raise ValueError(f"Record {i}: wrong balancing authority '{respondent}', expected '{expected_ba}'")

        period_str = str(r["period"]).strip()
        try:
            if "T" in period_str and len(period_str) == 13:
                # Format: 2022-06-01T00
                dt = datetime.strptime(period_str, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(period_str)
                if dt.tzinfo is None:
                    # EIA standard timestamps without offset represent UTC
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
        except Exception as e:
            raise ValueError(f"Record {i}: malformed period timestamp '{period_str}': {e}") from e

        if dt < start_utc or dt >= end_utc:
            raise ValueError(f"Record {i}: timestamp {dt} is outside requested interval [{start_utc}, {end_utc})")

        # Parse numeric value (handles strings, ints, floats)
        num_val = parse_numeric_value(r["value"], i)

        metric_type = str(r["type"]).strip().upper()
        row_dict = {
            "balancing_authority": respondent,
            "timestamp_utc": dt,
            "type": metric_type,
            "type_name": r.get("type-name", ""),
            "value_mw": num_val,
            "value_units": r.get("value-units", "megawatthours"),
        }

        if metric_type in ("D", "DEMAND"):
            demand_rows.append(row_dict)
        elif metric_type in ("NG", "NET GENERATION", "NET_GENERATION"):
            net_gen_rows.append(row_dict)
        elif metric_type in ("DF", "DEMAND FORECAST", "DEMAND_FORECAST", "TI", "TOTAL INTERCHANGE", "TOTAL_INTERCHANGE"):
            # Authentic region-data API payloads may include documented DF and TI series.
            # Defensively ignore them while continuing to collect and validate required D and NG series.
            continue
        else:
            raise ValueError(f"Record {i}: unknown metric type '{metric_type}'")

    # Validate completeness for both demand and net generation
    validate_eia_metric_rows(
        demand_rows,
        metric_name="Demand (D)",
        expected_ba=expected_ba,
        requested_start=start_utc,
        requested_end=end_utc,
    )
    validate_eia_metric_rows(
        net_gen_rows,
        metric_name="Net Generation (NG)",
        expected_ba=expected_ba,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    return {
        "demand_rows": demand_rows,
        "net_gen_rows": net_gen_rows,
        "total_records": len(records),
    }


# =========================================================================
# Native EIA CISO Excel Workbook (.xlsx) Ingestion
# =========================================================================

LB_TO_GRAMS = 453.59237
METRIC_TON_TO_LBS = 2204.62262185


def _excel_serial_to_utc(val: float | str) -> datetime:
    """Convert Excel serial date float (1900 date system) to timezone-aware UTC datetime."""
    base = datetime(1899, 12, 30, tzinfo=timezone.utc)
    days = float(val)
    # Round to nearest microsecond / second to eliminate floating point imprecision
    dt = base + timedelta(days=days)
    # Microsecond rounding to nearest second if within 1 millisecond
    if dt.microsecond > 999000:
        dt = (dt + timedelta(seconds=1)).replace(microsecond=0)
    elif dt.microsecond < 1000:
        dt = dt.replace(microsecond=0)
    return dt


def parse_and_validate_eia_ciso_workbook(
    workbook_path: str | Path,
    requested_start: datetime,
    requested_end: datetime,
    *,
    expected_ba: str = "CISO",
) -> dict[str, Any]:
    """Parse and validate authentic official EIA CISO Excel workbook (.xlsx).
    
    Verifies:
    - File existence, non-empty, and valid ZIP/XLSX structure.
    - Required sheets: 'Published Hourly Data', 'Notes', 'Known Data Issues'.
    - Required columns and headers in 'Published Hourly Data':
      BA, UTC time, Local date, Hour, Local time, Time zone, Demand, Net generation,
      CO2 Emissions Generated, CO2 Emissions Consumed, Positive Generation, Consumed Electricity,
      CO2 Emissions Intensity for Generated Electricity, CO2 Emissions Intensity for Consumed Electricity.
    - Notes sheet verification: confirms units (MWh, metric tons, lbs/kWh) and definitions.
    - Known Data Issues sheet join: joins by BA + UTC time to extract data issue flag.
    - Hour-ending UTC timestamp semantics: canonical interval start is UTC time - 1 hour.
    - Emissions and intensity non-negativity and finite numerical validity.
    - Conversions: lbs CO2/kWh to g CO2/kWh using 1 lb/kWh = 453.59237 g/kWh.
    - Intensity reconciliation: validates that reported intensities match generated/consumed formulas
      within numerical tolerance.
    """
    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"EIA CISO workbook not found: {path}")

    suffix = path.suffix.lower()
    if suffix != ".xlsx":
        raise ValueError(f"Unsupported workbook format '{suffix}'. Expected '.xlsx': {path}")

    if path.stat().st_size == 0:
        raise ValueError(f"EIA CISO workbook is empty: {path}")

    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested_start and requested_end must be timezone-aware")
    if requested_start >= requested_end:
        raise ValueError(f"requested_start ({requested_start}) must be before requested_end ({requested_end})")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    # 1. Open zip container and check sheets
    try:
        z = zipfile.ZipFile(path, "r")
    except Exception as e:
        raise ValueError(f"File {path} is not a valid Excel (.xlsx) zip package: {e}") from e

    try:
        # Inspect xl/workbook.xml to find sheet names and relationship IDs
        try:
            wb_xml = z.read("xl/workbook.xml")
            wb_root = ET.fromstring(wb_xml)
        except Exception as e:
            raise ValueError(f"Failed to read xl/workbook.xml: {e}") from e

        # Extract sheets map: sheet_name -> rId
        sheet_rids: dict[str, str] = {}
        for elem in wb_root.iter():
            if elem.tag.endswith("}sheet"):
                name = elem.attrib.get("name")
                # relationship id can be in {http://schemas.openxmlformats.org/officeDocument/2006/relationships}id
                for attr, val in elem.attrib.items():
                    if attr.endswith("}id") or attr == "r:id" or attr == "id":
                        sheet_rids[name] = val

        required_sheets = {"Published Hourly Data", "Notes", "Known Data Issues"}
        missing_sheets = required_sheets - set(sheet_rids.keys())
        if missing_sheets:
            raise ValueError(f"Workbook missing required sheets: {sorted(missing_sheets)}. Found: {sorted(sheet_rids.keys())}")

        # Resolve relationship targets from xl/_rels/workbook.xml.rels
        rels_xml = z.read("xl/_rels/workbook.xml.rels")
        rels_root = ET.fromstring(rels_xml)
        rid_targets: dict[str, str] = {}
        for rel in rels_root:
            rid = rel.attrib.get("Id")
            tgt = rel.attrib.get("Target")
            if rid and tgt:
                # normalise path: if relative like 'worksheets/sheet1.xml', prepend 'xl/'
                if not tgt.startswith("xl/") and not tgt.startswith("/"):
                    tgt = "xl/" + tgt
                elif tgt.startswith("/"):
                    tgt = tgt.lstrip("/")
                rid_targets[rid] = tgt

        hourly_xml_path = rid_targets.get(sheet_rids["Published Hourly Data"])
        notes_xml_path = rid_targets.get(sheet_rids["Notes"])
        issues_xml_path = rid_targets.get(sheet_rids["Known Data Issues"])

        if not hourly_xml_path or not notes_xml_path or not issues_xml_path:
            raise ValueError("Failed to resolve worksheet XML paths from workbook relationships")

        # Load shared strings table
        sst: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss_root:
                text = "".join([t.text or "" for t in si.iter() if t.tag.endswith("}t")])
                sst.append(text)

        # 2. Validate Notes sheet
        notes_text: list[tuple[str, str]] = []
        with z.open(notes_xml_path) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag.endswith("}row"):
                    cells = []
                    for c in elem.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                        t = c.attrib.get("t")
                        v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                        val = v.text if v is not None else ""
                        if t == "s" and val:
                            val = sst[int(val)]
                        cells.append(val)
                    if len(cells) >= 2:
                        notes_text.append((cells[0].strip(), cells[1].strip()))
                    elem.clear()

        notes_col_map = {k: v for k, v in notes_text if k}
        # Check Notes confirms key units and definitions
        notes_semantic_checks = [
            ("UTC time", lambda t: "end of the hour" in t and ("utc" in t or "coordinated universal time" in t), "end of the hour in UTC"),
            ("Local time", lambda t: "end of the hour" in t and "local" in t, "end of the hour in local time"),
            ("Demand", lambda t: "mwh" in t, "MWh"),
            ("Net generation", lambda t: "mwh" in t, "MWh"),
            ("CO2 Emissions Generated", lambda t: "metric tons" in t, "metric tons"),
            ("CO2 Emissions Consumed", lambda t: "metric tons" in t, "metric tons"),
            ("Positive Generation", lambda t: "mwh" in t, "MWh"),
            ("Consumed Electricity", lambda t: "mwh" in t, "MWh"),
            ("CO2 Emissions Intensity for Generated Electricity", lambda t: "lb/kwh" in t or "lbs/kwh" in t, "lb/kWh or lbs/kWh"),
            ("CO2 Emissions Intensity for Consumed Electricity", lambda t: "lb/kwh" in t or "lbs/kwh" in t, "lb/kWh or lbs/kWh"),
        ]

        for def_name, validator, expected_desc in notes_semantic_checks:
            if def_name not in notes_col_map:
                raise ValueError(f"Notes sheet missing expected definition for '{def_name}'")
            norm_desc = " ".join(notes_col_map[def_name].lower().split())
            if not validator(norm_desc):
                raise ValueError(
                    f"Notes sheet definition for '{def_name}' failed validation. Expected to specify '{expected_desc}', got: '{notes_col_map[def_name]}'"
                )

        # 3. Read Known Data Issues for the requested interval
        # Hour-ending serials needed:
        needed_serials: set[float] = set()
        curr = start_utc
        while curr < end_utc:
            he_utc = curr + timedelta(hours=1)
            serial_val = round((he_utc - datetime(1899, 12, 30, tzinfo=timezone.utc)).total_seconds() / 86400, 6)
            needed_serials.add(serial_val)
            curr += timedelta(hours=1)

        # Keyed by (balancing_authority, hour_ending_utc_serial)
        data_issues_map: dict[tuple[str, float], str] = {}
        with z.open(issues_xml_path) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag.endswith("}row"):
                    row_num = elem.attrib.get("r")
                    if row_num != "1":
                        b_cell = elem.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c[@r="B' + row_num + '"]')
                        if b_cell is not None:
                            v = b_cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                            if v is not None and v.text:
                                s_val = round(float(v.text), 6)
                                if s_val in needed_serials:
                                    a_cell = elem.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c[@r="A' + row_num + '"]')
                                    ba_val = ""
                                    if a_cell is not None:
                                        va = a_cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                                        if va is not None and va.text:
                                            ba_val = va.text
                                            if a_cell.attrib.get("t") == "s":
                                                ba_val = sst[int(ba_val)]
                                    e_cell = elem.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c[@r="E' + row_num + '"]')
                                    issue_val = ""
                                    if e_cell is not None:
                                        ve = e_cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                                        if ve is not None and ve.text:
                                            issue_val = ve.text
                                            if e_cell.attrib.get("t") == "s":
                                                issue_val = sst[int(issue_val)]
                                    data_issues_map[(ba_val.strip(), s_val)] = issue_val.strip()
                    elem.clear()

        # 4. Stream and validate Published Hourly Data
        header_cols: dict[str, str] = {}
        parsed_rows: list[dict[str, Any]] = []

        REQUIRED_WORKBOOK_COLUMNS = {
            "BA", "UTC time", "Local date", "Hour", "Local time", "Time zone",
            "Demand", "Net generation",
            "CO2 Emissions Generated", "CO2 Emissions Consumed",
            "Positive Generation", "Consumed Electricity",
            "CO2 Emissions Intensity for Generated Electricity",
            "CO2 Emissions Intensity for Consumed Electricity",
        }

        issues_matched_count = 0
        issues_flagged_count = 0
        issues_unflagged_count = 0

        with z.open(hourly_xml_path) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag.endswith("}row"):
                    row_num = elem.attrib.get("r")
                    if row_num == "1":
                        # Parse header row
                        for c in elem.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                            col_ref = "".join([ch for ch in c.attrib.get("r", "") if ch.isalpha()])
                            t = c.attrib.get("t")
                            v_elem = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                            val = v_elem.text if v_elem is not None else ""
                            if t == "s" and val:
                                val = sst[int(val)]
                            header_cols[col_ref] = val.strip()

                        missing_cols = REQUIRED_WORKBOOK_COLUMNS - set(header_cols.values())
                        if missing_cols:
                            raise ValueError(f"Published Hourly Data sheet missing required columns: {sorted(missing_cols)}")

                        # Map name to column letter
                        col_by_name = {v: k for k, v in header_cols.items()}
                        ba_col = col_by_name["BA"]
                        utc_col = col_by_name["UTC time"]
                        loc_date_col = col_by_name["Local date"]
                        hour_col = col_by_name["Hour"]
                        loc_time_col = col_by_name["Local time"]
                        tz_col = col_by_name["Time zone"]
                        d_col = col_by_name["Demand"]
                        ng_col = col_by_name["Net generation"]
                        co2_gen_col = col_by_name["CO2 Emissions Generated"]
                        co2_con_col = col_by_name["CO2 Emissions Consumed"]
                        pos_gen_col = col_by_name["Positive Generation"]
                        con_elec_col = col_by_name["Consumed Electricity"]
                        gen_int_col = col_by_name["CO2 Emissions Intensity for Generated Electricity"]
                        con_int_col = col_by_name["CO2 Emissions Intensity for Consumed Electricity"]

                    else:
                        # Data row
                        b_cell = elem.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c[@r="' + utc_col + row_num + '"]')
                        if b_cell is not None:
                            v = b_cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                            if v is not None and v.text:
                                raw_utc_serial = float(v.text)
                                utc_ending_dt = _excel_serial_to_utc(raw_utc_serial)
                                # Canonical interval start is UTC time - 1 hour
                                interval_start_dt = utc_ending_dt - timedelta(hours=1)

                                if start_utc <= interval_start_dt < end_utc:
                                    # Collect row cells
                                    cells: dict[str, str] = {}
                                    for c in elem.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                                        col_ref = "".join([ch for ch in c.attrib.get("r", "") if ch.isalpha()])
                                        t = c.attrib.get("t")
                                        val_elem = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                                        val = val_elem.text if val_elem is not None else ""
                                        if t == "s" and val:
                                            val = sst[int(val)]
                                        cells[col_ref] = val

                                    # Check BA
                                    row_ba = cells.get(ba_col, "").strip()
                                    if row_ba != expected_ba:
                                        raise ValueError(f"Row {row_num}: expected BA '{expected_ba}', got '{row_ba}'")

                                    # Parse numbers
                                    try:
                                        d_val = float(cells.get(d_col, ""))
                                        ng_val = float(cells.get(ng_col, ""))
                                        co2_gen_mt = float(cells.get(co2_gen_col, ""))
                                        co2_con_mt = float(cells.get(co2_con_col, ""))
                                        pos_gen_mwh = float(cells.get(pos_gen_col, ""))
                                        con_elec_mwh = float(cells.get(con_elec_col, ""))
                                        gen_int_lb = float(cells.get(gen_int_col, ""))
                                        con_int_lb = float(cells.get(con_int_col, ""))
                                    except (ValueError, TypeError) as num_err:
                                        raise ValueError(f"Row {row_num} at {interval_start_dt.isoformat()}: invalid numeric value in emissions/intensity row: {num_err}") from num_err

                                    # Reject non-finite values (NaN, Inf) across all numeric columns
                                    numeric_fields = {
                                        "demand": d_val,
                                        "net_generation": ng_val,
                                        "co2_emissions_generated": co2_gen_mt,
                                        "co2_emissions_consumed": co2_con_mt,
                                        "positive_generation": pos_gen_mwh,
                                        "consumed_electricity": con_elec_mwh,
                                        "co2_intensity_generated": gen_int_lb,
                                        "co2_intensity_consumed": con_int_lb,
                                    }
                                    for field_name, f_val in numeric_fields.items():
                                        if math.isnan(f_val) or math.isinf(f_val):
                                            raise ValueError(f"Row {row_num} at {interval_start_dt.isoformat()}: non-finite value ({f_val}) in numeric field '{field_name}'")

                                    # Check plausible / non-negative bounds
                                    if co2_gen_mt < 0 or co2_con_mt < 0:
                                        raise ValueError(f"Row {row_num} at {interval_start_dt.isoformat()}: negative CO2 emissions (gen={co2_gen_mt}, con={co2_con_mt})")
                                    if gen_int_lb < 0 or con_int_lb < 0:
                                        raise ValueError(f"Row {row_num} at {interval_start_dt.isoformat()}: negative CO2 intensity (gen={gen_int_lb}, con={con_int_lb})")

                                    # Intensity conversion: 1 lb/kWh = 453.59237 g/kWh
                                    gen_int_g_kwh = gen_int_lb * LB_TO_GRAMS
                                    con_int_g_kwh = con_int_lb * LB_TO_GRAMS

                                    # Intensity reconciliation check
                                    if pos_gen_mwh > 0:
                                        calc_gen_lb = (co2_gen_mt * METRIC_TON_TO_LBS) / (pos_gen_mwh * 1000.0)
                                        if abs(calc_gen_lb - gen_int_lb) > 1e-4:
                                            raise ValueError(
                                                f"Row {row_num} at {interval_start_dt.isoformat()}: generated intensity reconciliation mismatch: "
                                                f"reported={gen_int_lb} lb/kWh, calculated={calc_gen_lb} lb/kWh"
                                            )
                                    if con_elec_mwh > 0:
                                        calc_con_lb = (co2_con_mt * METRIC_TON_TO_LBS) / (con_elec_mwh * 1000.0)
                                        if abs(calc_con_lb - con_int_lb) > 1e-4:
                                            raise ValueError(
                                                f"Row {row_num} at {interval_start_dt.isoformat()}: consumed intensity reconciliation mismatch: "
                                                f"reported={con_int_lb} lb/kWh, calculated={calc_con_lb} lb/kWh"
                                            )

                                    # Data issue indicator joined by (balancing_authority, serial)
                                    serial_key = round(raw_utc_serial, 6)
                                    issue_key = (row_ba, serial_key)
                                    has_issue_val = data_issues_map.get(issue_key, "0")
                                    is_flagged = False
                                    if issue_key in data_issues_map:
                                        issues_matched_count += 1
                                        try:
                                            is_flagged = float(has_issue_val) != 0
                                        except (ValueError, TypeError):
                                            is_flagged = bool(has_issue_val)
                                        if is_flagged:
                                            issues_flagged_count += 1
                                        else:
                                            issues_unflagged_count += 1

                                    parsed_rows.append({
                                        "balancing_authority": row_ba,
                                        "timestamp_utc": interval_start_dt,
                                        "hour_ending_utc": utc_ending_dt,
                                        "demand_mwh": d_val,
                                        "net_generation_mwh": ng_val,
                                        "co2_emissions_generated_metric_tons": co2_gen_mt,
                                        "co2_emissions_consumed_metric_tons": co2_con_mt,
                                        "positive_generation_mwh": pos_gen_mwh,
                                        "consumed_electricity_mwh": con_elec_mwh,
                                        "co2_intensity_generated_lb_per_kwh": gen_int_lb,
                                        "co2_intensity_consumed_lb_per_kwh": con_int_lb,
                                        "co2_intensity_generated_g_per_kwh": gen_int_g_kwh,
                                        "co2_intensity_consumed_g_per_kwh": con_int_g_kwh,
                                        "data_issue_flag": has_issue_val,
                                        "has_data_issue": is_flagged,
                                    })
                    elem.clear()
    finally:
        z.close()

    # Validate complete hourly interval coverage
    validate_eia_metric_rows(
        [{"timestamp_utc": r["timestamp_utc"], "balancing_authority": r["balancing_authority"]} for r in parsed_rows],
        metric_name="Native EIA CISO Workbook Hourly Interval",
        expected_ba=expected_ba,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    return {
        "rows": parsed_rows,
        "row_count": len(parsed_rows),
        "notes_definitions_count": len(notes_col_map),
        "data_issues_joined_count": len(data_issues_map),
        "data_issues_matched_count": issues_matched_count,
        "data_issues_flagged_count": issues_flagged_count,
        "data_issues_unflagged_count": issues_unflagged_count,
    }


def ingest_eia_workbook(
    workbook_path: str | Path,
    *,
    balancing_authority: str = "CISO",
    requested_start: datetime,
    requested_end: datetime,
    manifest_path: str | Path = "data/manifests/raw_sources.jsonl",
) -> dict[str, Any]:
    """Ingest, validate, and record provenance for authentic official EIA CISO Excel workbook.
    
    Verifies that the original workbook is kept unchanged.
    Computes coverage for generated emissions, consumed emissions, generated intensity, and consumed intensity.
    """
    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"EIA workbook not found: {path}")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    parsed = parse_and_validate_eia_ciso_workbook(
        path,
        requested_start=start_utc,
        requested_end=end_utc,
        expected_ba=balancing_authority,
    )

    sanitized_request = {
        "balancing_authority": balancing_authority,
        "dataset": "EIA-930-CISO-hourly-workbook",
        "end_date": end_utc.isoformat(),
        "mode": "official_workbook_xlsx",
        "provider": "EIA",
        "source_file": str(path.name),
        "start_date": start_utc.isoformat(),
    }

    manifest_rec = record_provenance(
        manifest_path,
        path,
        provider="EIA",
        dataset="EIA-930-CISO-hourly-workbook",
        request=sanitized_request,
        is_cache_hit=True,
    )

    timestamps = [r["timestamp_utc"] for r in parsed["rows"]]
    cov = compute_hourly_coverage(timestamps, requested_start=start_utc, requested_end=end_utc)

    # Set native status based on whether Known Data Issues were flagged
    flagged_cnt = parsed["data_issues_flagged_count"]
    native_stat = "success_with_data_issues" if flagged_cnt > 0 else "success"

    return {
        "cache_hit": True,
        "carbon_status": native_stat,
        "coverage": {
            "emissions_generated": cov,
            "emissions_consumed": cov,
            "intensity_generated": cov,
            "intensity_consumed": cov,
        },
        "data_issues_flagged_count": flagged_cnt,
        "data_issues_joined_count": parsed["data_issues_joined_count"],
        "data_issues_matched_count": parsed["data_issues_matched_count"],
        "data_issues_unflagged_count": parsed["data_issues_unflagged_count"],
        "dataset": "EIA-930-CISO-hourly-workbook",
        "manifest_record": manifest_rec,
        "native_emissions_status": native_stat,
        "provider": "EIA",
        "raw_path": str(path),
        "rows": parsed["rows"],
        "status": native_stat,
    }


def parse_and_validate_eia_emissions_staging_csv(
    file_path: str | Path,
    *,
    expected_ba: str = "CISO",
    requested_start: datetime,
    requested_end: datetime,
) -> dict[str, Any]:
    """Parse and validate a manually prepared HeatTrace EIA emissions staging CSV.

    NOTE: For native EIA CISO Excel workbooks (.xlsx), use parse_and_validate_eia_ciso_workbook.
    This importer strictly accepts a documented intermediate staging CSV contract.

    Mandatory columns:
      - balancing_authority: matching expected_ba (e.g. 'CISO')
      - timestamp: ISO 8601 string (e.g. '2022-06-01T00:00:00Z' or with offset/local time)
      - co2_value: numeric emissions value (parsed via parse_emissions_numeric_value)
      - co2_unit: unit string ('metric_tons', 'mt', 'metric_tonnes', 'short_tons', 'st')
    Optional columns:
      - timezone: IANA timezone string (required if timestamp is naive)
      - fold: 0 or 1 integer (for disambiguating fall-back DST local timestamps)

    Conversions:
      - short_tons / st are converted to metric tonnes via 1 short ton = 0.90718474 metric ton.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"EIA emissions file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        raise ValueError(
            f"Excel workbooks ({suffix}) are not supported as staging CSV. "
            "Use native workbook ingestion (--eia-emissions-workbook) instead."
        )
    if suffix != ".csv":
        raise ValueError(f"Unsupported emissions file format '{suffix}'. Expected '.csv' staging file: {path}")

    if path.stat().st_size == 0:
        raise ValueError(f"EIA emissions staging CSV is empty: {path}")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    ALLOWED_UNITS = {
        "metric_tons": 1.0,
        "mt": 1.0,
        "metric_tonnes": 1.0,
        "short_tons": 0.90718474,
        "st": 0.90718474,
    }

    REQUIRED_COLS = {"balancing_authority", "timestamp", "co2_value", "co2_unit"}
    OPTIONAL_COLS = {"timezone", "fold"}

    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"EIA emissions staging CSV has no header row: {path}")

        # Check column names strictly
        raw_headers = [fn.strip() for fn in reader.fieldnames if fn]
        header_set = set(raw_headers)
        missing_required = REQUIRED_COLS - header_set
        if missing_required:
            raise ValueError(
                f"EIA emissions staging CSV missing required columns: {sorted(missing_required)}. "
                f"Found headers: {raw_headers}. Required schema: {sorted(REQUIRED_COLS)}"
            )

        parsed_rows: list[dict[str, Any]] = []
        for i, row in enumerate(reader):
            ba_val = (row.get("balancing_authority") or "").strip()
            if ba_val != expected_ba:
                raise ValueError(f"Row {i}: wrong balancing authority '{ba_val}', expected '{expected_ba}'")

            ts_raw = (row.get("timestamp") or "").strip()
            if not ts_raw:
                raise ValueError(f"Row {i}: missing timestamp")

            tz_str = (row.get("timezone") or "").strip()
            fold_str = (row.get("fold") or "").strip()
            if fold_str != "" and fold_str not in ("0", "1"):
                raise ValueError(f"Row {i}: invalid fold value '{fold_str}'. Must be '0', '1', or empty.")
            fold_val = int(fold_str) if fold_str in ("0", "1") else 0

            # Strict timestamp parsing and DST validation
            try:
                # 1. Check if ISO string has explicit offset or 'Z'
                if ts_raw.endswith("Z") or "+" in ts_raw or ("-" in ts_raw[10:]):
                    if fold_str != "":
                        raise ValueError(
                            f"Contradictory fold '{fold_str}' provided for explicit-offset timestamp '{ts_raw}'"
                        )
                    if ts_raw.endswith("Z"):
                        dt = datetime.fromisoformat(ts_raw[:-1]).replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(ts_raw)
                else:
                    # Naive string: requires explicit timezone column
                    if not tz_str:
                        raise ValueError(
                            f"Naive timestamp '{ts_raw}' requires an explicit IANA 'timezone' column"
                        )
                    tz = ZoneInfo(tz_str)
                    naive_dt = datetime.fromisoformat(ts_raw)
                    dt_candidate = naive_dt.replace(tzinfo=tz, fold=fold_val)

                    # Check for nonexistent time (spring-forward gap)
                    dt_roundtrip = dt_candidate.astimezone(timezone.utc).astimezone(tz)
                    if dt_roundtrip.replace(tzinfo=None) != naive_dt:
                        raise ValueError(
                            f"Nonexistent local timestamp during DST spring-forward gap: '{ts_raw}' in {tz_str}"
                        )

                    # Check for ambiguous time (fall-back transition)
                    dt_fold0 = naive_dt.replace(tzinfo=tz, fold=0)
                    dt_fold1 = naive_dt.replace(tzinfo=tz, fold=1)
                    if tz.utcoffset(dt_fold0) != tz.utcoffset(dt_fold1):
                        # Ambiguous wall clock time! Must have fold explicitly provided
                        if fold_str not in ("0", "1"):
                            raise ValueError(
                                f"Ambiguous local timestamp during DST fall-back transition: '{ts_raw}' in {tz_str}. "
                                "Disambiguation requires an explicit 'fold' column (0 or 1) or an explicit UTC offset."
                            )
                    dt = dt_candidate
            except Exception as e:
                raise ValueError(f"Row {i}: malformed or invalid timestamp '{ts_raw}': {e}") from e

            dt_utc = dt.astimezone(timezone.utc)
            if dt_utc < start_utc or dt_utc >= end_utc:
                # Outside requested interval
                continue

            # Emissions numeric validation
            co2_raw = row.get("co2_value")
            co2_metric_val = parse_emissions_numeric_value(co2_raw, i)

            # Units validation & conversion
            unit_raw = (row.get("co2_unit") or "").strip().lower()
            if not unit_raw:
                raise ValueError(f"Row {i}: missing mandatory 'co2_unit'")
            if unit_raw not in ALLOWED_UNITS:
                raise ValueError(
                    f"Row {i}: unsupported co2_unit '{unit_raw}'. "
                    f"Allowed units: {sorted(ALLOWED_UNITS.keys())}"
                )

            scale = ALLOWED_UNITS[unit_raw]
            co2_metric_tons = co2_metric_val * scale

            parsed_rows.append({
                "balancing_authority": ba_val,
                "timestamp_utc": dt_utc,
                "co2_metric_tons": co2_metric_tons,
                "units": "metric_tons",
                "original_unit": unit_raw,
                "original_value": co2_metric_val,
            })

    # Validate complete hourly interval coverage
    validate_eia_metric_rows(
        parsed_rows,
        metric_name="CO2 Emissions (staging)",
        expected_ba=expected_ba,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    return {
        "rows": parsed_rows,
        "row_count": len(parsed_rows),
    }


def ingest_eia_emissions_file(
    emissions_file: str | Path,
    *,
    balancing_authority: str = "CISO",
    requested_start: datetime,
    requested_end: datetime,
    data_dir: str | Path = "data/raw/eia",
    manifest_path: str | Path = "data/manifests/raw_sources.jsonl",
) -> dict[str, Any]:
    """Ingest, validate, and record provenance for a manually prepared EIA emissions staging CSV.

    Returns status 'success_user_supplied_staging_csv' to clearly distinguish user-supplied
    staging data from authentic automated EIA downloads.
    """
    src_path = Path(emissions_file)
    if not src_path.exists():
        raise FileNotFoundError(f"Local EIA emissions staging file does not exist: {src_path}")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    # Validate contents strictly against staging CSV contract BEFORE copying or recording provenance
    parsed = parse_and_validate_eia_emissions_staging_csv(
        src_path,
        expected_ba=balancing_authority,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_file = out_dir / f"eia930_emissions_staging_{balancing_authority}_{start_utc.strftime('%Y%m%d')}.csv"

    # If the target file is different from source, copy raw bytes
    if target_file.resolve() != src_path.resolve():
        target_file.write_bytes(src_path.read_bytes())

    sanitized_request = {
        "balancing_authority": balancing_authority,
        "dataset": "EIA-930-emissions-staging",
        "end_date": end_utc.isoformat(),
        "mode": "staging_csv",
        "provider": "EIA-staging",
        "source_file": str(src_path.name),
        "start_date": start_utc.isoformat(),
    }

    manifest_rec = record_provenance(
        manifest_path,
        target_file,
        provider="EIA-staging",
        dataset="EIA-930-emissions-staging",
        request=sanitized_request,
        is_cache_hit=False,
    )

    cov = compute_hourly_coverage(
        [r["timestamp_utc"] for r in parsed["rows"]],
        requested_start=start_utc,
        requested_end=end_utc,
    )

    return {
        "cache_hit": False,
        "coverage": cov,
        "dataset": "EIA-930-emissions-staging",
        "emissions_rows": parsed["rows"],
        "emissions_staging_status": "success_user_supplied_staging_csv",
        "emissions_status": "blocked_pending_emissions_file_discovery",
        "manifest_record": manifest_rec,
        "native_emissions_status": "blocked_pending_emissions_file_discovery",
        "provider": "EIA-staging",
        "raw_path": str(target_file),
        "status": "success_user_supplied_staging_csv",
    }


def run_eia_smoke_test(
    balancing_authority: str = "CISO",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    *,
    use_api: bool = False,
    allow_cache_without_key: bool = False,
    emissions_file: str | Path | None = None,
    emissions_workbook: str | Path | None = None,
    data_dir: str | Path = "data/raw/eia",
    manifest_path: str | Path = "data/manifests/raw_sources.jsonl",
    dry_run: bool = False,
    api_timeout: float = DEFAULT_EIA_API_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run EIA smoke test acquisition."""
    if start_date is None:
        start_date = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    if end_date is None:
        end_date = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)

    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("start_date and end_date must be timezone-aware")
    if start_date >= end_date:
        raise ValueError(f"start_date ({start_date}) must be before end_date ({end_date})")

    start_utc = start_date.astimezone(timezone.utc)
    end_utc = end_date.astimezone(timezone.utc)

    # Generic translation to inclusive bounds
    query_params_unauthenticated = build_eia_query_params(balancing_authority, start_utc, end_utc)
    url_for_dry_run = build_eia_region_url(balancing_authority, start_utc, end_utc)

    sanitized_request = {
        "api_key_configured": bool(get_eia_api_key()),
        "balancing_authority": balancing_authority,
        "dataset": "EIA-930",
        "emissions_file_configured": bool(emissions_file),
        "emissions_workbook_configured": bool(emissions_workbook),
        "end_date": end_utc.isoformat(),
        "mode": "api" if use_api else "bulk_or_api",
        "provider": "EIA",
        "query_params": query_params_unauthenticated,
        "route": "electricity/rto/region-data",
        "start_date": start_utc.isoformat(),
        "url": url_for_dry_run,
    }

    if dry_run:
        return {
            "cache_hit": False,
            "carbon_status": "dry_run" if emissions_workbook else "blocked_pending_emissions_file_discovery",
            "dataset": "EIA-930",
            "demand_status": "dry_run",
            "diagnostic": "EIA interface scaffolded. Dry run executed with sanitized parameters.",
            "emissions_staging_status": "dry_run" if emissions_file else "not_provided",
            "emissions_status": "dry_run" if emissions_workbook else "blocked_pending_emissions_file_discovery",
            "native_emissions_status": "dry_run" if emissions_workbook else "blocked_pending_emissions_file_discovery",
            "net_generation_status": "dry_run",
            "provider": "EIA",
            "request": sanitized_request,
            "status": "dry_run",
        }

    # Handle native official Excel workbook if supplied
    workbook_result: dict[str, Any] | None = None
    if emissions_workbook:
        workbook_result = ingest_eia_workbook(
            emissions_workbook,
            balancing_authority=balancing_authority,
            requested_start=start_utc,
            requested_end=end_utc,
            manifest_path=manifest_path,
        )

    # Handle staging emissions file if explicitly supplied
    emissions_result: dict[str, Any] | None = None
    if emissions_file:
        emissions_result = ingest_eia_emissions_file(
            emissions_file,
            balancing_authority=balancing_authority,
            requested_start=start_utc,
            requested_end=end_utc,
            data_dir=data_dir,
            manifest_path=manifest_path,
        )

    staging_stat = emissions_result["emissions_staging_status"] if emissions_result else "not_provided"
    native_stat = workbook_result["native_emissions_status"] if workbook_result else "blocked_pending_emissions_file_discovery"
    carbon_stat = workbook_result["carbon_status"] if workbook_result else "blocked_pending_emissions_file_discovery"

    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_file = out_dir / f"eia930_region_{balancing_authority}_{start_utc.strftime('%Y%m%d')}.json"

    # Check local cache first
    cache_hit = False
    content: bytes | None = None
    if validate_eia_json_cache(target_file, expected_ba=balancing_authority, requested_start=start_utc, requested_end=end_utc):
        cache_hit = True
        content = target_file.read_bytes()

    api_key = get_eia_api_key() if use_api else None
    can_use_cache = cache_hit and (api_key or allow_cache_without_key)


    diag_msg_blocked = (
        "EIA acquisition is blocked pending API key (EIA_API_KEY). "
        "Official EIA API v2 routes (/electricity/rto/region-data and /electricity/rto/fuel-type-data) "
        "require an official API key for historical sub-daily data queries. "
        "Furthermore, estimated CO2 emissions are not exposed via the hourly API v2 RTO routes; "
        "official documentation indicates they reside in Balancing Authority workbooks under the Hourly Electric Grid Monitor. "
        + ("Native CISO workbook emissions data successfully validated from provided workbook. " if workbook_result else
           "Direct native emissions acquisition remains blocked pending authentic CISO workbook discovery/verification. "
           "Official CISO workbooks (.xlsx) downloaded from "
           f"{EIA_GRID_MONITOR_DASHBOARD_URL} (Download Data -> Balancing Authority/Regional Files -> CISO) "
           "can be ingested natively via --eia-emissions-workbook=<path_to_xlsx>. ")
        + "To enable EIA API live acquisition once a key is acquired, export EIA_API_KEY=<your_key> and pass --eia-api."
    )

    if not can_use_cache and not api_key:
        ret_coverage: dict[str, Any] = {}
        if workbook_result and "coverage" in workbook_result:
            # Only include workbook carbon metrics, not demand or net_generation
            for k in ("emissions_generated", "emissions_consumed", "intensity_generated", "intensity_consumed"):
                if k in workbook_result["coverage"]:
                    ret_coverage[k] = workbook_result["coverage"][k]
        if emissions_result and "coverage" in emissions_result:
            ret_coverage["emissions_staging"] = emissions_result["coverage"]

        return {
            "cache_hit": False,
            "carbon_status": carbon_stat,
            "coverage": ret_coverage if ret_coverage else None,
            "dataset": "EIA-930",
            "demand_status": "blocked_pending_api_key",
            "diagnostic": diag_msg_blocked,
            "emissions_coverage": emissions_result.get("coverage") if emissions_result else None,
            "emissions_staging_status": staging_stat,
            "emissions_status": native_stat,
            "native_emissions_status": native_stat,
            "net_generation_status": "blocked_pending_api_key",
            "provider": "EIA",
            "request": sanitized_request,
            "status": "blocked_pending_api_key",
            "workbook_result": workbook_result,
        }

    if not can_use_cache:
        url = build_eia_region_url(balancing_authority, start_utc, end_utc, api_key=api_key)

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=api_timeout) as resp:
                content = resp.read()
        except Exception as e:
            safe_msg = redact_api_key(str(e), api_key)
            raise RuntimeError(f"EIA API request failed: {safe_msg}") from None

        # Parse and validate response BEFORE writing provenance or saving final file
        try:
            parse_and_validate_eia_json(
                content,
                expected_ba=balancing_authority,
                requested_start=start_utc,
                requested_end=end_utc,
            )
        except Exception as e:
            safe_err = redact_api_key(str(e), api_key)
            raise ValueError(f"EIA response failed validation: {safe_err}") from None

        # Save raw response unchanged
        target_file.write_bytes(content)

    manifest_record = record_provenance(
        manifest_path,
        target_file,
        provider="EIA",
        dataset="EIA-930",
        request=sanitized_request,
        is_cache_hit=cache_hit,
    )

    parsed = parse_and_validate_eia_json(
        content,
        expected_ba=balancing_authority,
        requested_start=start_utc,
        requested_end=end_utc,
    )

    demand_ts = [r["timestamp_utc"] for r in parsed["demand_rows"]]
    net_gen_ts = [r["timestamp_utc"] for r in parsed["net_gen_rows"]]

    cov_demand = compute_hourly_coverage(demand_ts, requested_start=start_utc, requested_end=end_utc)
    cov_net_gen = compute_hourly_coverage(net_gen_ts, requested_start=start_utc, requested_end=end_utc)

    coverage_dict = {
        "demand": cov_demand,
        "net_generation": cov_net_gen,
    }
    if workbook_result and "coverage" in workbook_result:
        for k in ("emissions_generated", "emissions_consumed", "intensity_generated", "intensity_consumed"):
            if k in workbook_result["coverage"]:
                coverage_dict[k] = workbook_result["coverage"][k]
    if emissions_result and "coverage" in emissions_result:
        coverage_dict["emissions_staging"] = emissions_result["coverage"]

    diag_success = (
        "Successfully acquired and validated EIA-930 CISO demand and net generation via /region-data. "
        + ("Native official EIA CISO workbook validated successfully with full hourly emissions and intensity coverage. " if workbook_result else
           ("Staging emissions data successfully validated from provided HeatTrace staging CSV. " if emissions_result else
            "Notice: Estimated CO2 emissions are not exposed via API v2 /electricity/rto routes. "
            "Direct native emissions acquisition remains blocked pending authentic CISO workbook discovery/verification. "
            "Official CISO workbooks (.xlsx) downloaded from the Hourly Electric Grid Monitor may be supplied via --eia-emissions-workbook."))
    )

    return {
        "cache_hit": cache_hit,
        "carbon_status": carbon_stat,
        "coverage": coverage_dict,
        "dataset": "EIA-930",
        "demand_status": "success",
        "diagnostic": diag_success,
        "emissions_staging_status": staging_stat,
        "emissions_status": native_stat,
        "manifest_record": manifest_record,
        "native_emissions_status": native_stat,
        "net_generation_status": "success",
        "provider": "EIA",
        "raw_path": str(target_file),
        "sample_rows_count": parsed["total_records"],
        "status": "success",
        "workbook_result": workbook_result,
    }
