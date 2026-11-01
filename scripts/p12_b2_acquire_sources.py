"""Acquire, validate, and build Track B2 Phase 2 multi-station manifests and artifacts.

Outputs:
- data/v2/manifests/p12_b2_station_metadata.json
- data/v2/manifests/p12_b2_source_coverage.csv
- data/v2/manifests/p12_b2_price_carbon_coverage.csv
- data/v2/manifests/p12_b2_raw_sources.jsonl
- data/v2/processed/p12_b2_hourly_<station>_<year>.parquet

Fully reproducible, supports --repo-root, distinguishes retrieved_at_utc from processed_at_utc,
computes real content hashes for CAISO raw archives, and reuses official EIA workbook parsing.
Distinguishes valid market archives from CAISO error responses.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

from heattrace.process.p12_b2_coverage import (
    calculate_noaa_station_year_coverage,
    calculate_price_carbon_coverage_record,
    classify_caiso_archive,
    parse_caiso_archive_rows,
    build_caiso_coverage_for_hub_year,
    file_sha256,
)
from heattrace.ingest.eia import parse_and_validate_eia_ciso_workbook


CANDIDATE_STATIONS = [
    {
        "station_id": "SFO",
        "station_name": "San Francisco International Airport",
        "noaa_ghcnh_id": "USW00023234",
        "caiso_proxy": "TH_NP15_GEN-APND",
        "climate_class": "northern coastal",
        "representativeness_limitation": "Marine-influenced coastal airport; does not reflect inland extreme heat of San Francisco Bay Area interior valleys.",
        "predeclared_fallback": None,
    },
    {
        "station_id": "SAC",
        "station_name": "Sacramento Executive Airport",
        "noaa_ghcnh_id": "USW00023232",
        "caiso_proxy": "TH_NP15_GEN-APND",
        "climate_class": "northern inland",
        "representativeness_limitation": "Urban-adjacent valley airport with localized urban heat island effects; evaluated as primary northern inland station.",
        "predeclared_fallback": "USW00093225",
    },
    {
        "station_id": "SAC_FALLBACK",
        "station_name": "Sacramento Metropolitan Airport",
        "noaa_ghcnh_id": "USW00093225",
        "caiso_proxy": "TH_NP15_GEN-APND",
        "climate_class": "northern inland",
        "representativeness_limitation": "Predeclared fallback northern inland station located in open agricultural basin north of Sacramento.",
        "predeclared_fallback": None,
    },
    {
        "station_id": "FAT",
        "station_name": "Fresno Yosemite International Airport",
        "noaa_ghcnh_id": "USW00093193",
        "caiso_proxy": "TH_ZP26_GEN-APND",
        "climate_class": "central valley inland",
        "representativeness_limitation": "Deep Central Valley continental regime with sustained nighttime heat traps and agricultural inversion layers.",
        "predeclared_fallback": None,
    },
    {
        "station_id": "RDD",
        "station_name": "Redding Municipal Airport",
        "noaa_ghcnh_id": "USW00024257",
        "caiso_proxy": "TH_NP15_GEN-APND",
        "climate_class": "far northern inland",
        "representativeness_limitation": "Topographically confined northern basin subject to extreme diurnal swings, dry föhn winds, and severe summer maximums.",
        "predeclared_fallback": None,
    },
    {
        "station_id": "LAX",
        "station_name": "Los Angeles International Airport",
        "noaa_ghcnh_id": "USW00023174",
        "caiso_proxy": "TH_SP15_GEN-APND",
        "climate_class": "southern coastal",
        "representativeness_limitation": "Pacific shoreline marine layer creates significant microclimate damping relative to the greater Los Angeles Basin.",
        "predeclared_fallback": None,
    },
]

YEARS = [2022, 2023, 2024, 2025, 2026]
PROVISIONAL_YEARS = {2026}
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def run_pipeline(repo_root: Path | None = None, caiso_only: bool = False) -> None:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    manifests_dir = repo_root / "data/v2/manifests"
    processed_dir = repo_root / "data/v2/processed"
    raw_noaa_dir = repo_root / "data/v2/raw/noaa"
    raw_caiso_dir = repo_root / "data/v2/raw/caiso"
    raw_eia_dir = repo_root / "data/v2/raw/eia"

    manifests_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    weather_records = []
    raw_sources_log = []

    if not caiso_only:
        print("=== Step 1: Building Station Metadata Snapshot ===")
        station_meta_snapshot = []
        for st in CANDIDATE_STATIONS:
            ghcnh_id = st["noaa_ghcnh_id"]
            psv_sample = raw_noaa_dir / f"GHCNh_{ghcnh_id}_2024.psv"
            lat, lon, elev, official_name = None, None, None, st["station_name"]
            if psv_sample.exists():
                with open(psv_sample, "r", encoding="utf-8", errors="replace") as f:
                    f.readline()
                    line = f.readline().strip().split("|")
                    if len(line) > 10:
                        official_name = line[1].strip()
                        lat = float(line[8])
                        lon = float(line[9])
                        elev = float(line[10])

            station_meta_snapshot.append({
                "station_code": st["station_id"],
                "official_station_name": official_name,
                "noaa_ghcnh_id": ghcnh_id,
                "latitude": lat,
                "longitude": lon,
                "elevation_m": elev,
                "caiso_proxy_hub": st["caiso_proxy"],
                "climate_class": st["climate_class"],
                "predeclared_fallback": st["predeclared_fallback"],
                "representativeness_limitation": st["representativeness_limitation"],
                "market_proxy_limitation": "Regional wholesale trading hub (NP15/ZP26/SP15) represents wholesale energy clearing; does not constitute a retail facility tariff or distribution delivery rate.",
                "carbon_proxy_limitation": "Shared CISO balancing authority production average; does not represent marginal emissions, avoided emissions, or station-local grid carbon intensity.",
            })

        meta_path = manifests_dir / "p12_b2_station_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": "2.0",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "stations": station_meta_snapshot,
            }, f, indent=2)
        print(f"Saved station metadata to {meta_path}")

        print("\n=== Step 2: Processing NOAA Weather Coverage Records & Parquet ===")
        for st in CANDIDATE_STATIONS:
            ghcnh_id = st["noaa_ghcnh_id"]
            st_code = st["station_id"]
            for y in YEARS:
                is_prov = y in PROVISIONAL_YEARS
                psv_file = raw_noaa_dir / f"GHCNh_{ghcnh_id}_{y}.psv"

                retrieved_at = "unknown"
                if st_code == "SFO" and y in (2022, 2023, 2024, 2025):
                    retrieved_at = "unknown (pre-existing in data/raw/noaa/)"
                else:
                    retrieved_at = "2026-10-30T09:30:28Z"

                cov_rec, hourly_df, daily_max_records = calculate_noaa_station_year_coverage(
                    psv_file_path=psv_file,
                    station_id=ghcnh_id,
                    station_name=st["station_name"],
                    year=y,
                    retrieved_at_utc=retrieved_at,
                    provisional=is_prov,
                )
                cov_rec["station_code"] = st_code
                weather_records.append(cov_rec)

                raw_sources_log.append({
                    "source": "NOAA_GHCNh",
                    "identifier": ghcnh_id,
                    "year": y,
                    "hub": None,
                    "market": None,
                    "lmp_type": None,
                    "xml_data_item": None,
                    "requested_start_utc": cov_rec["season_start_local"],
                    "requested_end_utc": cov_rec["season_end_local"],
                    "covered_start_utc": cov_rec["season_start_local"],
                    "covered_end_utc": cov_rec["season_end_local"],
                    "relative_path": str(psv_file.relative_to(repo_root)),
                    "bytes": cov_rec["bytes"],
                    "sha256": cov_rec["sha256"],
                    "retrieval_url": cov_rec["source_url"],
                    "query_parameters": f"station={ghcnh_id}&year={y}",
                    "retrieved_at_utc": retrieved_at,
                    "processed_at_utc": cov_rec["processed_timestamp_utc"],
                    "retrieval_status": "SUCCESS_DATA",
                    "caiso_error_code": None,
                    "caiso_error_message": None,
                    "valid_interval_count": cov_rec["valid_temperature_hours"],
                })

                # Save normalized Parquet dataset
                parquet_path = processed_dir / f"p12_b2_hourly_{st_code}_{y}.parquet"
                hourly_df["station_code"] = st_code
                hourly_df.to_parquet(parquet_path, index=False)
                print(f"Created {parquet_path.name} ({len(hourly_df)} rows, missing={hourly_df['is_missing'].sum()})")

        # Write weather coverage CSV
        weather_csv_path = manifests_dir / "p12_b2_source_coverage.csv"
        weather_fieldnames = [
            "station_id", "station_code", "station_name", "latitude", "longitude", "elevation_m",
            "year", "season_start_local", "season_end_local",
            "expected_hours", "observed_hours", "valid_temperature_hours",
            "missing_hours", "duplicate_hours", "conflict_hours", "subhourly_observations",
            "expected_local_days", "valid_daily_max_days",
            "source_url", "retrieval_timestamp_utc", "processed_timestamp_utc", "sha256", "bytes",
            "provisional", "eligibility_status", "rejection_reasons"
        ]
        with open(weather_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=weather_fieldnames)
            writer.writeheader()
            for r in weather_records:
                writer.writerow(r)
        print(f"Saved weather coverage to {weather_csv_path}")
    else:
        print("\n=== Skipping NOAA Weather Coverage (CAISO-only mode) ===")
        # Preserve weather records in raw_sources_log by loading previous entries if exist
        raw_sources_path = manifests_dir / "p12_b2_raw_sources.jsonl"
        if raw_sources_path.exists():
            with open(raw_sources_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "NOAA" in line:
                        raw_sources_log.append(json.loads(line))

    print("\n=== Step 3: Processing CAISO and EIA Coverage Records ===")
    price_carbon_records = []

    caiso_hubs = [
        ("NP15", "TH_NP15_GEN-APND"),
        ("ZP26", "TH_ZP26_GEN-APND"),
        ("SP15", "TH_SP15_GEN-APND"),
    ]

    # Inventory all CAISO archives across data/v2/raw/caiso, historical, and bulk_historical
    search_dirs = [
        raw_caiso_dir,
        raw_caiso_dir / "historical",
        raw_caiso_dir / "bulk_historical",
    ]
    seen_archive_paths = set()
    caiso_archives: list[Path] = []
    for sdir in search_dirs:
        if sdir.exists():
            for ext in ("*.zip", "*.csv"):
                for p in sorted(sdir.rglob(ext)):
                    if p.is_file() and p not in seen_archive_paths:
                        seen_archive_paths.add(p)
                        caiso_archives.append(p)
    caiso_archives.sort()

    caiso_archive_info = {}
    caiso_parsed_rows: list[dict[str, Any]] = []

    for cap in caiso_archives:
        c_bytes = cap.stat().st_size
        c_sha = file_sha256(cap)
        rel_p = str(cap.relative_to(repo_root))

        # Classify archive using authoritative classifier
        cinfo = classify_caiso_archive(cap)
        retrieval_status = cinfo["status"]
        err_code = cinfo["error_code"]
        err_msg = cinfo["error_message"]
        is_err = retrieval_status == "CAISO_ERROR_RESPONSE"

        # Parse valid rows if SUCCESS_DATA
        archive_rows: list[dict[str, Any]] = []
        min_ts = None
        max_ts = None
        if retrieval_status == "SUCCESS_DATA":
            archive_rows = parse_caiso_archive_rows(
                cap,
                target_nodes=[hf for _, hf in caiso_hubs],
                market_run_id="DAM",
                lmp_type="LMP",
                xml_data_item="LMP_PRC",
                source_identity=rel_p,
            )
            if archive_rows:
                ts_sorted = sorted(r["timestamp_utc"] for r in archive_rows)
                min_ts = ts_sorted[0].isoformat()
                max_ts = ts_sorted[-1].isoformat()
                caiso_parsed_rows.extend(archive_rows)

        # Infer year and hub from path / filename or from parsed rows
        m_hub = None
        if archive_rows:
            nodes = {r["node"] for r in archive_rows}
            if len(nodes) == 1:
                m_hub = list(nodes)[0]
            else:
                m_hub = "MULTI_NODE_GROUP"
        else:
            for hc, hf in caiso_hubs:
                if hc in cap.name or hf in cap.name:
                    m_hub = hf
                    break

        m_year = None
        if archive_rows:
            years = {r["timestamp_utc"].year for r in archive_rows}
            if len(years) == 1:
                m_year = list(years)[0]
        if m_year is None:
            m_y = re.search(r'(202[2-6])', cap.name)
            if m_y:
                m_year = int(m_y.group(1))

        # Extract request interval from filename if present
        req_start_utc = None
        req_end_utc = None
        m_dt = re.findall(r'(\d{8}|\d{10})', cap.name)
        if len(m_dt) >= 2:
            s_tag = m_dt[0]
            e_tag = m_dt[1]
            try:
                if len(s_tag) == 8:
                    req_start_utc = datetime.strptime(s_tag, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
                    req_end_utc = datetime.strptime(e_tag, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
                elif len(s_tag) == 10:
                    req_start_utc = datetime.strptime(s_tag, "%Y%m%d%H").replace(tzinfo=timezone.utc).isoformat()
                    req_end_utc = datetime.strptime(e_tag, "%Y%m%d%H").replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

        retrieval_time = (
            "2026-10-30T09:46:51Z" if ("caiso_dam_lmp" in cap.name)
            else "2026-10-30T20:33:42Z" if ("attempt_" in cap.name)
            else "unknown (pre-existing historical archive)"
        )

        caiso_archive_info[rel_p] = {
            "bytes": c_bytes,
            "sha256": c_sha,
            "path": cap,
            "is_err": is_err,
            "err_code": err_code,
            "err_msg": err_msg,
            "valid_intervals": len(archive_rows),
            "retrieval_status": retrieval_status,
        }

        # Add granular record to raw sources log
        raw_sources_log.append({
            "source": "CAISO_OASIS_PRC_LMP",
            "identifier": cap.name,
            "year": m_year if m_year else "2022-2026",
            "hub": m_hub if m_hub else "MULTI_NODE_GROUP",
            "market": "DAM",
            "lmp_type": "LMP",
            "xml_data_item": "LMP_PRC",
            "requested_start_utc": req_start_utc,
            "requested_end_utc": req_end_utc,
            "covered_start_utc": min_ts,
            "covered_end_utc": max_ts,
            "relative_path": rel_p,
            "bytes": c_bytes,
            "sha256": c_sha,
            "retrieval_url": "http://oasis.caiso.com/oasisapi/SingleZip?queryname=PRC_LMP" if "SingleZip" in cap.name or "caiso_dam_lmp" in cap.name else "http://oasis.caiso.com/oasisapi/GroupZip",
            "query_parameters": f"node={m_hub}&start={req_start_utc}&end={req_end_utc}&market_run_id=DAM",
            "retrieved_at_utc": retrieval_time,
            "processed_at_utc": datetime.now(timezone.utc).isoformat(),
            "retrieval_status": retrieval_status,
            "caiso_error_code": err_code,
            "caiso_error_message": err_msg,
            "valid_interval_count": len(archive_rows),
        })

    # Convert all valid rows into DataFrame
    if caiso_parsed_rows:
        all_caiso_df = pd.DataFrame(caiso_parsed_rows)
    else:
        all_caiso_df = pd.DataFrame(columns=["timestamp_utc", "node", "market_run_id", "lmp_type", "xml_data_item", "price_usd_per_mwh", "source_file"])

    gap_inventory_after_rows = []

    # Build hub-year coverage summaries across all valid archives
    for hub_code, hub_full in caiso_hubs:
        for y in YEARS:
            is_prov = y in PROVISIONAL_YEARS
            s_local = datetime(y, 6, 1, 0, 0, tzinfo=LOCAL_TZ)
            e_local = datetime(y, 10, 1, 0, 0, tzinfo=LOCAL_TZ)
            s_utc = s_local.astimezone(timezone.utc)
            e_utc = e_local.astimezone(timezone.utc)

            prec, gap_rec = build_caiso_coverage_for_hub_year(
                parsed_rows=caiso_parsed_rows,
                caiso_archive_info=caiso_archive_info,
                hub_full=hub_full,
                hub_code=hub_code,
                year=y,
                expected_start_utc=s_utc,
                expected_end_utc=e_utc,
                is_provisional=is_prov,
            )
            gap_inventory_after_rows.append(gap_rec)
            price_carbon_records.append(prec)

    # Save gap inventory after CSV
    gap_after_path = manifests_dir / "p12_b2_caiso_gap_inventory_after.csv"
    with open(gap_after_path, "w", newline="", encoding="utf-8") as f:
        gap_fields = [
            "hub", "hub_code", "year", "expected_intervals",
            "existing_valid_intervals", "missing_intervals",
            "first_missing_utc", "last_missing_utc",
            "contiguous_missing_ranges_count", "contiguous_missing_ranges"
        ]
        writer = csv.DictWriter(f, fieldnames=gap_fields)
        writer.writeheader()
        for gr in gap_inventory_after_rows:
            writer.writerow(gr)
    print(f"Saved post-acquisition CAISO gap inventory to {gap_after_path}")

    # Save acquisition attempts manifest
    attempts_path = manifests_dir / "p12_b2_caiso_acquisition_attempts.jsonl"
    attempts_records = []
    # Identify attempt files in bulk_historical
    for p in sorted((raw_caiso_dir / "bulk_historical").glob("*.zip")):
        ainfo = classify_caiso_archive(p)
        rel_p = str(p.relative_to(repo_root))
        c_sha = file_sha256(p)
        c_bytes = p.stat().st_size
        
        # Match hub and request from name
        m_hub = "TH_NP15_GEN-APND"
        for hc, hf in caiso_hubs:
            if hc in p.name:
                m_hub = hf
                break
        
        req_start_utc = None
        req_end_utc = None
        m_dt = re.findall(r'(\d{8})', p.name)
        if len(m_dt) >= 2:
            req_start_utc = datetime.strptime(m_dt[0], "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
            req_end_utc = datetime.strptime(m_dt[1], "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()

        attempts_records.append({
            "attempt_id": p.stem,
            "endpoint_url": "http://oasis.caiso.com/oasisapi/SingleZip?queryname=PRC_LMP",
            "requested_hub": m_hub,
            "requested_start_utc": req_start_utc,
            "requested_end_utc": req_end_utc,
            "market": "DAM",
            "component": "LMP_PRC",
            "request_parameters": f"queryname=PRC_LMP&market_run_id=DAM&node={m_hub}&startdatetime={req_start_utc}&enddatetime={req_end_utc}&version=12&resultformat=6",
            "request_timestamp_utc": "unknown (pre-existing automated run)",
            "response_timestamp_utc": "unknown (pre-existing automated run)",
            "status": ainfo["status"],
            "metadata_provenance": "inferred_from_filename",
            "output_path": rel_p,
            "bytes": c_bytes,
            "sha256": c_sha,
            "caiso_error_code": ainfo["error_code"],
            "caiso_error_message": ainfo["error_message"],
        })
    with open(attempts_path, "w", encoding="utf-8") as f:
        for ar in attempts_records:
            f.write(json.dumps(ar) + "\n")
    print(f"Saved CAISO acquisition attempts manifest to {attempts_path}")

    # 3.2 EIA CISO Balancing Authority Grid & Carbon Inputs
    ciso_xlsx_path = raw_eia_dir / "CISO.xlsx"
    ciso_xlsx_sha256 = file_sha256(ciso_xlsx_path)
    ciso_xlsx_bytes = ciso_xlsx_path.stat().st_size

    raw_sources_log.append({
        "source": "EIA_930_WORKBOOK",
        "identifier": "CISO",
        "year": "2022-2026",
        "hub": "CISO",
        "market": "Balancing_Authority_Operations",
        "lmp_type": None,
        "xml_data_item": "Demand_NetGen_ConsumedCarbonIntensity",
        "requested_start_utc": "2022-06-01T07:00:00+00:00",
        "requested_end_utc": "2026-10-01T07:00:00+00:00",
        "covered_start_utc": "2015-07-01T08:00:00+00:00",
        "covered_end_utc": "2026-10-18T06:00:00+00:00",
        "relative_path": str(ciso_xlsx_path.relative_to(repo_root)),
        "bytes": ciso_xlsx_bytes,
        "sha256": ciso_xlsx_sha256,
        "retrieval_url": "https://www.eia.gov/electricity/gridmonitor/ CISO.xlsx",
        "query_parameters": "region=CISO&format=xlsx",
        "retrieved_at_utc": "unknown (pre-existing in data/raw/eia/)",
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval_status": "SUCCESS_DATA",
        "caiso_error_code": None,
        "caiso_error_message": None,
        "valid_interval_count": 99048,
    })

    # Inventory official recovery EIA API evidence files
    eia_recovery_dir = raw_eia_dir / "official_recovery"
    if eia_recovery_dir.exists():
        for ep in sorted(eia_recovery_dir.glob("*.json")):
            ep_bytes = ep.stat().st_size
            ep_sha = file_sha256(ep)
            ep_rel = str(ep.relative_to(repo_root))
            with open(ep, "r", encoding="utf-8") as ef:
                try:
                    edata = json.load(ef)
                    erows = edata.get("response", {}).get("data", [])
                    num_rows = len(erows)
                except Exception:
                    num_rows = 0

            raw_sources_log.append({
                "source": "EIA_OPEN_DATA_API_V2",
                "identifier": ep.name,
                "year": 2022,
                "hub": "CISO",
                "market": "Balancing_Authority_Operations",
                "lmp_type": None,
                "xml_data_item": "region-data" if "region" in ep.name else "fuel-type-data",
                "requested_start_utc": "2022-06-13T16:00:00Z",
                "requested_end_utc": "2022-06-13T20:00:00Z",
                "covered_start_utc": "2022-06-13T16:00:00Z",
                "covered_end_utc": "2022-06-13T20:00:00Z",
                "relative_path": ep_rel,
                "bytes": ep_bytes,
                "sha256": ep_sha,
                "retrieval_url": f"https://api.eia.gov/v2/electricity/rto/{'region-data' if 'region' in ep.name else 'fuel-type-data'}/data",
                "query_parameters": "frequency=hourly&data[0]=value&facets[respondent][]=CISO&start=2022-06-13T16&end=2022-06-13T20&api_key=[REDACTED]",
                "retrieved_at_utc": "2026-10-31T05:08:13Z",
                "processed_at_utc": datetime.now(timezone.utc).isoformat(),
                "retrieval_status": "SUCCESS_DATA",
                "caiso_error_code": None,
                "caiso_error_message": None,
                "valid_interval_count": num_rows,
            })

    # Read EIA CISO warm-season intervals via parse_and_validate_eia_ciso_workbook
    for y in YEARS:
        is_prov = y in PROVISIONAL_YEARS
        s_local = datetime(y, 6, 1, 0, 0, tzinfo=LOCAL_TZ)
        e_local = datetime(y, 10, 1, 0, 0, tzinfo=LOCAL_TZ)
        s_utc = s_local.astimezone(timezone.utc)
        e_utc = e_local.astimezone(timezone.utc)
        exp_intervals = int((e_utc - s_utc).total_seconds() / 3600)

        if y == 2022:
            split_point = datetime(2022, 6, 13, 17, 0, tzinfo=timezone.utc)
            split_next = datetime(2022, 6, 13, 18, 0, tzinfo=timezone.utc)
            part1 = parse_and_validate_eia_ciso_workbook(ciso_xlsx_path, s_utc, split_point)
            part2 = parse_and_validate_eia_ciso_workbook(ciso_xlsx_path, split_next, e_utc)
            valid_rows = part1["rows"] + part2["rows"]
            flagged_count = sum(1 for r in valid_rows if r.get("has_data_issue"))
            valid_intervals = len(valid_rows)
            missing_intervals = exp_intervals - valid_intervals
            reasons = [f"Missing 1 unpopulated interval (2022-06-13 17:00 UTC) in CISO.xlsx; incomplete warm-season coverage ({valid_intervals}/{exp_intervals})"]
        else:
            res = parse_and_validate_eia_ciso_workbook(ciso_xlsx_path, s_utc, e_utc)
            valid_rows = res["rows"]
            flagged_count = sum(1 for r in valid_rows if r.get("has_data_issue"))
            valid_intervals = len(valid_rows)
            missing_intervals = exp_intervals - valid_intervals
            reasons = () if valid_intervals >= exp_intervals else [f"Missing {missing_intervals} intervals"]

        erec = calculate_price_carbon_coverage_record(
            source_name="EIA_930_CISO",
            hub_or_ba="CISO",
            year=y,
            market_product="Demand_NetGen_ConsumedCarbonIntensity",
            expected_intervals=exp_intervals,
            observed_intervals=valid_intervals,
            valid_intervals=valid_intervals,
            missing_intervals=missing_intervals,
            duplicate_intervals=0,
            conflict_intervals=0,
            issue_flag_count=flagged_count,
            unit="MW (Demand/NetGen), gCO2/kWh (ConsumedCarbonIntensity)",
            timestamp_convention="interval-start UTC (converted from hour-ending)",
            retrieval_provenance="Authentic CISO.xlsx workbook parsed via parse_and_validate_eia_ciso_workbook",
            sha256_hash=ciso_xlsx_sha256,
            bytes_count=ciso_xlsx_bytes,
            provisional=is_prov,
            rejection_reasons=reasons,
        )
        price_carbon_records.append(erec)

    # Write price/carbon coverage CSV
    price_carbon_csv_path = manifests_dir / "p12_b2_price_carbon_coverage.csv"
    pc_fieldnames = [
        "source", "hub_or_balancing_authority", "year", "market_product",
        "expected_intervals", "observed_intervals", "valid_intervals",
        "missing_intervals", "duplicate_intervals", "conflicts",
        "issue_flag_counts", "unit", "timestamp_convention",
        "retrieval_provenance", "sha256", "bytes",
        "provisional", "eligibility_status", "rejection_reasons"
    ]
    with open(price_carbon_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=pc_fieldnames)
        writer.writeheader()
        for r in price_carbon_records:
            writer.writerow(r)
    print(f"Saved price and carbon coverage to {price_carbon_csv_path}")

    # Write raw sources JSONL
    raw_sources_path = manifests_dir / "p12_b2_raw_sources.jsonl"
    with open(raw_sources_path, "w", encoding="utf-8") as f:
        for r in raw_sources_log:
            f.write(json.dumps(r) + "\n")
    print(f"Saved raw sources manifest to {raw_sources_path}")

    print("\n=== Phase 2 Manifest & Processing Pipeline Complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track B2 Phase 2 Acquisition and Coverage Pipeline")
    parser.add_argument("--repo-root", type=Path, default=None, help="Root path of the repository")
    parser.add_argument("--caiso-only", action="store_true", help="Process only CAISO and EIA, skipping weather parquets")
    args = parser.parse_args()
    run_pipeline(args.repo_root, caiso_only=args.caiso_only)
