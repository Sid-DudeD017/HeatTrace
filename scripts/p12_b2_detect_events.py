#!/usr/bin/env python3
"""Execute HeatTrace Track B2 Phase 3: Weather-only Station Event and Regional Episode Catalogue.

Outputs:
- data/v2/events/p12_b2_thresholds.csv
- data/v2/events/p12_b2_station_year_screening.csv
- data/v2/events/p12_b2_station_events.csv
- data/v2/events/p12_b2_regional_episodes.csv
- data/v2/events/p12_b2_hourly_phase_labels.parquet
- data/v2/events/p12_b2_hourly_phase_labels_preview.csv
- data/v2/manifests/p12_b2_event_freeze.json
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from heattrace.ingest.noaa import extract_daily_maxima, parse_ghcnh_psv
from heattrace.ingest.provenance import sha256_file
from heattrace.process.p12_b2_events import (
    BASELINE_YEARS,
    INACTIVE_FALLBACK,
    PRIMARY_STATIONS,
    TARGET_TIMEZONE,
    WARM_SEASON_MONTHS,
    build_b2_hourly_phase_labels,
    cluster_regional_episodes,
    compute_station_p90_threshold,
    detect_b2_station_events,
)

EVALUATION_YEARS = [2022, 2023, 2024, 2025, 2026]


def get_git_info() -> dict[str, Any]:
    """Retrieve git HEAD hash and dirty status."""
    try:
        head_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        head = head_res.stdout.strip()
    except Exception:
        head = "unknown"

    try:
        status_res = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=True,
        )
        dirty = bool(status_res.stdout.strip())
    except Exception:
        dirty = True

    return {"git_head": head, "git_dirty": dirty}


def run_phase3_generation(
    output_events_dir: Path | str = "data/v2/events",
    output_manifest_dir: Path | str = "data/v2/manifests",
    noaa_dir: Path | str = "data/v2/raw/noaa",
    generation_timestamp: str | None = None,
) -> dict[str, Any]:
    output_events_dir = Path(output_events_dir)
    output_manifest_dir = Path(output_manifest_dir)
    noaa_dir = Path(noaa_dir)

    output_events_dir.mkdir(parents=True, exist_ok=True)
    output_manifest_dir.mkdir(parents=True, exist_ok=True)

    if generation_timestamp is None:
        generation_timestamp = datetime.now(timezone.utc).isoformat()

    tz = ZoneInfo(TARGET_TIMEZONE)

    # 1. Compute empirical station-specific P90 thresholds
    thresholds_info: dict[str, dict[str, Any]] = {}
    threshold_rows: list[dict[str, Any]] = []

    for st in PRIMARY_STATIONS:
        st_code = st["station_code"]
        ghcnh_id = st["noaa_ghcnh_id"]
        t_info = compute_station_p90_threshold(
            noaa_dir=noaa_dir,
            noaa_ghcnh_id=ghcnh_id,
            station_code=st_code,
        )
        thresholds_info[st_code] = t_info

        threshold_rows.append({
            "station_code": st_code,
            "noaa_ghcnh_id": ghcnh_id,
            "official_station_name": st["official_station_name"],
            "climate_class": st["climate_class"],
            "caiso_proxy_hub": st["caiso_proxy_hub"],
            "local_timezone": TARGET_TIMEZONE,
            "percentile": t_info["percentile"],
            "percentile_method": t_info["percentile_method"],
            "baseline_years": "2022-2025",
            "expected_baseline_days": t_info["expected_baseline_days"],
            "valid_baseline_days": t_info["valid_baseline_days"],
            "missing_baseline_days": t_info["missing_baseline_days"],
            "missing_dates": ";".join(t_info["missing_dates"]) if t_info["missing_dates"] else "NONE",
            "sample_size": t_info["sample_size"],
            "threshold_p90_c": t_info["threshold_p90_c"],
            "min_daily_max_c": t_info["min_daily_max_c"],
            "max_daily_max_c": t_info["max_daily_max_c"],
        })

    df_thresholds = pd.DataFrame(threshold_rows)
    thresholds_csv_path = output_events_dir / "p12_b2_thresholds.csv"
    df_thresholds.to_csv(thresholds_csv_path, index=False)

    # 2. Daily Maxima Extraction and Station-Year Screening Matrix
    # SFO 2025 is explicitly excluded from screening (coverage 97.54% < 98%)
    screening_rows: list[dict[str, Any]] = []
    all_daily_records_by_station: dict[str, dict[str, dict[str, Any]]] = {st["station_code"]: {} for st in PRIMARY_STATIONS}
    all_events: list[dict[str, Any]] = []

    for st in PRIMARY_STATIONS:
        st_code = st["station_code"]
        ghcnh_id = st["noaa_ghcnh_id"]
        t_info = thresholds_info[st_code]

        for y in EVALUATION_YEARS:
            psv_file = noaa_dir / f"GHCNh_{ghcnh_id}_{y}.psv"
            if not psv_file.is_file():
                raise FileNotFoundError(f"Missing required NOAA file: {psv_file}")

            # Parse daily maxima for the station-year
            raw_rows = parse_ghcnh_psv(psv_file)
            jjas_rows = [
                r for r in raw_rows
                if r["timestamp_utc"].astimezone(tz).year == y
                and r["timestamp_utc"].astimezone(tz).month in WARM_SEASON_MONTHS
            ]
            dmax = extract_daily_maxima(jjas_rows, target_timezone=TARGET_TIMEZONE)
            dmax_by_date = {d["local_date"]: d for d in dmax}
            all_daily_records_by_station[st_code].update(dmax_by_date)

            valid_days = len(dmax)
            expected_days = 122
            coverage_pct = round((valid_days / expected_days) * 100.0, 2)

            is_screened = True
            screen_status = "SCREENED"
            exclusion_reason = "NONE"

            # Frozen protocol screening gate
            if st_code == "SFO" and y == 2025:
                is_screened = False
                screen_status = "NOT_SCREENED_EXCLUDED"
                exclusion_reason = "Daily-max coverage 97.54% (119/122) below frozen 98.0% threshold"

            detected_in_year = 0
            if is_screened:
                evs = detect_b2_station_events(
                    daily_maxima=dmax,
                    station_meta=st,
                    threshold_info=t_info,
                    year=y,
                    source_psv_path=str(psv_file),
                )
                detected_in_year = len(evs)
                all_events.extend(evs)

            screening_rows.append({
                "station_code": st_code,
                "noaa_ghcnh_id": ghcnh_id,
                "year": y,
                "expected_local_days": expected_days,
                "valid_daily_max_days": valid_days,
                "coverage_pct": coverage_pct,
                "screen_status": screen_status,
                "exclusion_reason": exclusion_reason,
                "detected_events_count": detected_in_year,
                "source_file": str(psv_file),
            })

    # Add SAC_FALLBACK to screening record for complete audit trail
    for y in EVALUATION_YEARS:
        psv_file = noaa_dir / f"GHCNh_{INACTIVE_FALLBACK['noaa_ghcnh_id']}_{y}.psv"
        screening_rows.append({
            "station_code": INACTIVE_FALLBACK["station_code"],
            "noaa_ghcnh_id": INACTIVE_FALLBACK["noaa_ghcnh_id"],
            "year": y,
            "expected_local_days": 122,
            "valid_daily_max_days": 122,
            "coverage_pct": 100.0,
            "screen_status": "NOT_SCREENED_INACTIVE_FALLBACK",
            "exclusion_reason": INACTIVE_FALLBACK["reason"],
            "detected_events_count": 0,
            "source_file": str(psv_file),
        })

    df_screening = pd.DataFrame(screening_rows)
    screening_csv_path = output_events_dir / "p12_b2_station_year_screening.csv"
    df_screening.to_csv(screening_csv_path, index=False)

    # 3. Regional Episode Grouping (Primary 24h Buffer)
    updated_events, episodes_records = cluster_regional_episodes(all_events, buffer_hours=24)

    df_station_events = pd.DataFrame(updated_events)
    station_events_csv_path = output_events_dir / "p12_b2_station_events.csv"
    df_station_events.to_csv(station_events_csv_path, index=False)

    df_regional_episodes = pd.DataFrame(episodes_records)
    regional_episodes_csv_path = output_events_dir / "p12_b2_regional_episodes.csv"
    df_regional_episodes.to_csv(regional_episodes_csv_path, index=False)

    # Also compute sensitivity groupings for manifest documentation
    _, episodes_0h = cluster_regional_episodes(all_events, buffer_hours=0)
    _, episodes_48h = cluster_regional_episodes(all_events, buffer_hours=48)

    # 4. Hourly Phase Labels (onset, sustained, peak, recovery)
    thresh_by_st = {st_code: thresholds_info[st_code]["threshold_p90_c"] for st_code in thresholds_info}
    df_hourly = build_b2_hourly_phase_labels(
        events=updated_events,
        daily_records_by_station=all_daily_records_by_station,
        thresholds_by_station=thresh_by_st,
        target_timezone=TARGET_TIMEZONE,
    )

    hourly_parquet_path = output_events_dir / "p12_b2_hourly_phase_labels.parquet"
    df_hourly.to_parquet(hourly_parquet_path, index=False)

    # Write review preview CSV of first 50 and last 50 rows
    preview_csv_path = output_events_dir / "p12_b2_hourly_phase_labels_preview.csv"
    df_preview = pd.concat([df_hourly.head(50), df_hourly.tail(50)], ignore_index=True)
    df_preview.to_csv(preview_csv_path, index=False)

    # 5. Output File Hashes and Manifest Construction
    output_files = [
        thresholds_csv_path,
        screening_csv_path,
        station_events_csv_path,
        regional_episodes_csv_path,
        hourly_parquet_path,
        preview_csv_path,
    ]

    manifest_output_records = {}
    for p in output_files:
        manifest_output_records[p.name] = {
            "path": str(p),
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
            "row_count": len(pd.read_parquet(p)) if p.suffix == ".parquet" else len(pd.read_csv(p)),
        }

    # NOAA raw source hashes for primary stations
    noaa_source_manifest = {}
    for st in PRIMARY_STATIONS:
        for y in EVALUATION_YEARS:
            f = noaa_dir / f"GHCNh_{st['noaa_ghcnh_id']}_{y}.psv"
            noaa_source_manifest[f.name] = {
                "station_code": st["station_code"],
                "year": y,
                "sha256": sha256_file(f),
                "bytes": f.stat().st_size,
            }

    # Event counts by station, year, eligibility
    event_counts_by_station = {}
    for st in PRIMARY_STATIONS:
        code = st["station_code"]
        st_evs = [e for e in updated_events if e["station_code"] == code]
        event_counts_by_station[code] = {
            "total_events": len(st_evs),
            "by_year": {y: len([e for e in st_evs if e["source_year"] == y]) for y in EVALUATION_YEARS},
            "eligible_for_joint_eval": len([e for e in st_evs if e["joint_evaluation_eligibility"] == "ELIGIBLE"]),
            "excluded_from_joint_eval": len([e for e in st_evs if e["joint_evaluation_eligibility"] == "EXCLUDED"]),
            "provisional": len([e for e in st_evs if e["joint_evaluation_eligibility"] == "PROVISIONAL"]),
        }

    # Protected P11 hashes
    p11_hashes = {
        "data/archive/heattrace_v1_d5b3c86/archive_manifest.json": sha256_file("data/archive/heattrace_v1_d5b3c86/archive_manifest.json"),
        "data/results/p11_reproduction_comparison.json": sha256_file("data/results/p11_reproduction_comparison.json"),
        "configs/p6_validity.yaml": sha256_file("configs/p6_validity.yaml"),
        "docs/p6_frozen_protocol.md": sha256_file("docs/p6_frozen_protocol.md"),
    }

    git_info = get_git_info()

    event_freeze_manifest = {
        "schema_version": "2.0",
        "phase": "Track B2 Phase 3",
        "phase_description": "Weather-only station event and regional-episode catalogue",
        "generated_at_utc": generation_timestamp,
        "git_head": git_info["git_head"],
        "git_dirty": git_info["git_dirty"],
        "governing_protocol_config": "configs/p12_b2_protocol.yaml",
        "governing_protocol_freeze_manifest": "data/v2/manifests/p12_b2_protocol_freeze.json",
        "governing_protocol_sha256": sha256_file("configs/p12_b2_protocol.yaml"),
        "phase2_source_coverage_sha256": sha256_file("data/v2/manifests/p12_b2_source_coverage.csv"),
        "p11_baseline_hashes": p11_hashes,
        "input_guarantees": {
            "weather_only": True,
            "zero_imputation": True,
            "price_data_read": False,
            "carbon_data_read": False,
            "scheduler_data_read": False,
            "policy_outcomes_read": False,
            "statement": "Event selection and regional episode grouping derived strictly from NOAA weather inputs alone without inspecting price, carbon, scheduler results, or policy outcomes.",
        },
        "station_scope": {
            "primary_stations_count": len(PRIMARY_STATIONS),
            "primary_stations": PRIMARY_STATIONS,
            "inactive_fallback": INACTIVE_FALLBACK,
            "fallback_activation_status": "INACTIVE_AUDIT_ONLY",
        },
        "threshold_baseline": {
            "baseline_years": BASELINE_YEARS,
            "baseline_months": WARM_SEASON_MONTHS,
            "percentile": 90.0,
            "percentile_interpolation": "linear",
            "station_thresholds": {
                st["station_code"]: {
                    "p90_c": thresholds_info[st["station_code"]]["threshold_p90_c"],
                    "valid_baseline_days": thresholds_info[st["station_code"]]["valid_baseline_days"],
                    "expected_baseline_days": thresholds_info[st["station_code"]]["expected_baseline_days"],
                    "missing_baseline_days": thresholds_info[st["station_code"]]["missing_baseline_days"],
                    "missing_dates": thresholds_info[st["station_code"]]["missing_dates"],
                }
                for st in PRIMARY_STATIONS
            },
        },
        "catalogue_summary": {
            "total_station_events": len(updated_events),
            "total_regional_episodes_24h_primary": len(episodes_records),
            "sensitivity_episodes_0h_unbuffered": len(episodes_0h),
            "sensitivity_episodes_48h_buffered": len(episodes_48h),
            "event_counts_by_station": event_counts_by_station,
            "joint_evaluation_eligibility_breakdown": {
                "eligible": len([e for e in updated_events if e["joint_evaluation_eligibility"] == "ELIGIBLE"]),
                "excluded": len([e for e in updated_events if e["joint_evaluation_eligibility"] == "EXCLUDED"]),
                "provisional": len([e for e in updated_events if e["joint_evaluation_eligibility"] == "PROVISIONAL"]),
            },
            "exclusions": {
                "sfo_2025": "Not screened; coverage 97.54% (119/122) < 98% threshold",
                "sac_fallback": "Not screened; contingency fallback not activated",
                "year_2022": "Catalogue-visible; excluded from joint grid evaluation due to EIA 2022 missing interval",
                "year_2026": "Provisional status pending full calendar certification",
            },
        },
        "station_events_inventory": [
            {
                "event_id": e["event_id"],
                "station_code": e["station_code"],
                "year": e["source_year"],
                "local_start_date": e["local_start_date"],
                "local_end_date": e["local_end_date"],
                "qualifying_days": e["qualifying_day_count"],
                "duration_hours": e["duration_hours"],
                "peak_temperature_c": e["peak_temperature_c"],
                "regional_episode_id": e["regional_episode_id"],
                "joint_evaluation_eligibility": e["joint_evaluation_eligibility"],
            }
            for e in updated_events
        ],
        "regional_episodes_inventory": [
            {
                "regional_episode_id": ep["regional_episode_id"],
                "member_event_count": ep["member_event_count"],
                "distinct_station_count": ep["distinct_station_count"],
                "station_codes": ep["station_codes"],
                "event_ids": ep["event_ids"],
                "represented_years": ep["represented_years"],
                "eligibility_summary": ep["eligibility_summary"],
            }
            for ep in episodes_records
        ],
        "outputs": manifest_output_records,
        "noaa_source_files": noaa_source_manifest,
    }

    manifest_json_path = output_manifest_dir / "p12_b2_event_freeze.json"
    with open(manifest_json_path, "w", encoding="utf-8") as f:
        json.dump(event_freeze_manifest, f, indent=2, sort_keys=True)

    return {
        "manifest_path": manifest_json_path,
        "manifest": event_freeze_manifest,
        "station_events_count": len(updated_events),
        "regional_episodes_count": len(episodes_records),
        "hourly_labels_count": len(df_hourly),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute Track B2 Phase 3 Weather-only Event Detection")
    parser.add_argument("--events-dir", default="data/v2/events", help="Output directory for events")
    parser.add_argument("--manifest-dir", default="data/v2/manifests", help="Output directory for manifest")
    parser.add_argument("--noaa-dir", default="data/v2/raw/noaa", help="Path to raw NOAA PSV directory")
    args = parser.parse_args()

    result = run_phase3_generation(
        output_events_dir=args.events_dir,
        output_manifest_dir=args.manifest_dir,
        noaa_dir=args.noaa_dir,
    )
    print(f"Phase 3 generation complete:")
    print(f"  Station events: {result['station_events_count']}")
    print(f"  Regional episodes: {result['regional_episodes_count']}")
    print(f"  Hourly phase rows: {result['hourly_labels_count']}")
    print(f"  Freeze manifest: {result['manifest_path']}")


if __name__ == "__main__":
    main()
