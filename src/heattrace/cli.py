"""Command line interface for HeatTrace P1 smoke tests and data acquisition."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from heattrace.config import load_yaml
from heattrace.ingest.coverage import write_coverage_report
from heattrace.ingest.noaa import (
    check_noaa_temperature_quality,
    extract_daily_maxima,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
    run_noaa_smoke_test,
)
from heattrace.ingest.caiso import run_caiso_smoke_test
from heattrace.ingest.eia import get_eia_api_key, run_eia_smoke_test, validate_eia_json_cache


def compute_baseline_summer_percentile(
    psv_path: str | Path | list[str | Path],
    station_id: str,
    *,
    baseline_years: list[int] = [2024],
    summer_months: list[int] = [6, 7, 8, 9],
    target_timezone: str = "America/Los_Angeles",
    percentile_val: float = 98.0,
) -> dict[str, Any]:
    """Compute baseline summer daily maximum statistics and percentile threshold from authentic cached NOAA data."""
    if isinstance(psv_path, (str, Path)):
        paths = [Path(psv_path)]
    else:
        paths = [Path(p) for p in psv_path]

    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Baseline NOAA PSV not found: {p}")

    from zoneinfo import ZoneInfo
    tz = ZoneInfo(target_timezone)

    # Parse all rows across all baseline year files
    summer_rows: list[dict[str, Any]] = []
    for p in paths:
        rows = parse_ghcnh_psv(p)
        for r in rows:
            ts = r["timestamp_utc"].astimezone(tz)
            if ts.year in baseline_years and ts.month in summer_months:
                summer_rows.append(r)

    if not summer_rows:
        raise ValueError(f"No summer rows found for station {station_id} in {paths}")

    # Extract daily maxima using authoritative quality and local-day policy
    daily_maxima = extract_daily_maxima(summer_rows, target_timezone=target_timezone)
    sorted_max = sorted([d["daily_max_temperature_c"] for d in daily_maxima])
    n = len(sorted_max)
    if n == 0:
        raise ValueError(f"Zero valid summer daily maxima in {path}")

    import statistics
    median_val = statistics.median(sorted_max)

    # Linear interpolation percentile
    k = (n - 1) * (percentile_val / 100.0)
    f = int(k)
    c = f + 1
    if c >= n:
        pct_threshold = sorted_max[-1]
    else:
        d0 = sorted_max[f] * (c - k)
        d1 = sorted_max[c] * (k - f)
        pct_threshold = d0 + d1

    return {
        "baseline_years": baseline_years,
        "daily_maxima_by_date": {d["local_date"]: d for d in daily_maxima},
        "heatwave_percentile": percentile_val,
        "heatwave_threshold_c": round(pct_threshold, 2),
        "percentile_method": "linear_interpolation",
        "station_id": station_id,
        "summer_median_c": round(median_val, 2),
        "summer_months": summer_months,
        "target_timezone": target_timezone,
        "valid_baseline_days": n,
    }



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HeatTrace P1 smoke tests and data-acquisition runner."
    )
    parser.add_argument(
        "--source",
        choices=["all", "noaa", "caiso", "eia"],
        default="all",
        help="Source to test (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print sanitized request parameters without performing network requests",
    )
    parser.add_argument(
        "--eia-api",
        action="store_true",
        help="Enable live EIA API acquisition using EIA_API_KEY from environment",
    )
    parser.add_argument(
        "--eia-emissions-file",
        default=None,
        help="Path to a manually prepared HeatTrace EIA emissions staging CSV",
    )
    parser.add_argument(
        "--eia-emissions-workbook",
        default=None,
        help="Path to authentic official EIA CISO Excel workbook (.xlsx)",
    )
    parser.add_argument(
        "--qc",
        action="store_true",
        help="Run P1-QC cross-source validation on 1 heatwave day (2022-09-05) and 1 ordinary day (2022-06-01)",
    )
    parser.add_argument(
        "--build-aligned",
        action="store_true",
        help="Build canonical aligned dataset (P2 v0 table) from cached P1 sources",
    )
    parser.add_argument(
        "--load-aligned",
        action="store_true",
        help="Load, validate, and summarize the canonical aligned dataset for verification",
    )
    parser.add_argument(
        "--build-events",
        action="store_true",
        help="Detect multi-day heatwaves and build canonical event catalogue and hourly phase labels (P3 Person A)",
    )
    parser.add_argument(
        "--inspect-events",
        action="store_true",
        help="Inspect and summarize detected heatwave events and phase labels (P3 Person A)",
    )
    parser.add_argument(
        "--build-workloads",
        action="store_true",
        help="Generate deterministic mock workload trace (P3-03)",
    )
    parser.add_argument(
        "--inspect-workloads",
        action="store_true",
        help="Inspect deterministic mock workload trace (P3-03)",
    )
    parser.add_argument(
        "--build-p3",
        action="store_true",
        help="Build full P3 event catalogue, controls, workloads, and 2024 benchmark (G3-a)",
    )
    parser.add_argument(
        "--audit-p3",
        action="store_true",
        help="Run P3-06 audit on events, controls, benchmarks, and chronological splits",
    )
    parser.add_argument(
        "--load-p3-benchmark",
        action="store_true",
        help="Load, validate, and inspect the 240-row 2024 event/control benchmark table (G3-a)",
    )
    parser.add_argument(
        "--build-p4",
        action="store_true",
        help="Build P4 manifests and historical-only forecast inputs (P4-01, P4-02)",
    )
    parser.add_argument(
        "--run-p4",
        action="store_true",
        help="Execute authentic event/control benchmark across all P4 policies (P4-08, P4-09)",
    )
    parser.add_argument(
        "--audit-p4",
        action="store_true",
        help="Run gate G4-a comprehensive verification audit",
    )
    parser.add_argument(
        "--load-p4-results",
        action="store_true",
        help="Load and print P4 policy comparison metrics and carbon data-quality caveats",
    )
    parser.add_argument(
        "--build-p5",
        action="store_true",
        help="Execute full P5 pipeline: characterization, treatments, sampling, and experiment runners",
    )
    parser.add_argument(
        "--source-commit",
        default=None,
        help="Explicit Git commit hash corresponding to the verified P5 source code revision",
    )
    parser.add_argument(
        "--run-p5",
        action="store_true",
        help="Execute P5 experiments and produce results package",
    )
    parser.add_argument(
        "--audit-p5",
        action="store_true",
        help="Execute Gate G5-a comprehensive verification audit",
    )
    parser.add_argument(
        "--load-p5-results",
        action="store_true",
        help="Load, summarize, and display P5 experiment findings",
    )
    parser.add_argument(
        "--build-p5-5",
        action="store_true",
        help="Execute full P5.5 pipeline: freeze grid, run experiment, generate tables, and figures",
    )
    parser.add_argument(
        "--run-p5-5",
        action="store_true",
        help="Execute P5.5 experiment grid and write result artifacts",
    )
    parser.add_argument(
        "--audit-p5-5",
        action="store_true",
        help="Execute Gate G5.5-a comprehensive verification audit",
    )
    parser.add_argument(
        "--load-p5-5-results",
        action="store_true",
        help="Load, summarize, and display P5.5 experiment findings and stress testing results",
    )
    parser.add_argument(
        "--run-p6-thermal-smoke",
        action="store_true",
        help="Execute Day 1 P6 thermal stress smoke test and record artifacts",
    )
    parser.add_argument(
        "--materialize-gate1",
        action="store_true",
        help="Regenerate all Gate 1 fallback controls, blind pool, index, and 1,440-row benchmark artifacts",
    )
    parser.add_argument(
        "--run-p6-pilot",
        action="store_true",
        help="Execute Day 8 P6 development-only pilot (TRIPLET_DEV_ae821c) and produce audit artifacts",
    )
    parser.add_argument(
        "--run-p6-confirmation",
        action="store_true",
        help="Execute Phase 8 / Day 10 frozen 756-cell confirmatory matrix exactly once",
    )
    parser.add_argument(
        "--execution-commit",
        default=None,
        help="Explicit 40-character git commit hash for Phase 8 confirmatory execution",
    )
    parser.add_argument(
        "--fail-on-eia-data-issues",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Whether flagged EIA Known Data Issues fail the final QC gate (default: True or configured in sources.yaml)",
    )
    parser.add_argument(
        "--config-dir",
        default="configs",
        help="Directory containing frozen sources.yaml and study.yaml (default: configs)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory for local raw data and manifests (default: data)",
    )
    return parser.parse_args(argv)



def run_smoke_tests(args: argparse.Namespace) -> int:
    config_dir = Path(args.config_dir)
    sources_cfg = load_yaml(config_dir / "sources.yaml")
    study_cfg = load_yaml(config_dir / "study.yaml")

    data_dir = Path(args.data_dir)
    manifest_path = data_dir / "manifests/raw_sources.jsonl"
    coverage_path = data_dir / "manifests/coverage.csv"

    results: dict[str, Any] = {}
    coverage_rows: list[dict[str, Any]] = []
    failure_occurred = False

    # 1. NOAA
    if args.source in ("all", "noaa"):
        station = sources_cfg["weather"]["stations"][0]["id"]  # USW00023234
        year = sources_cfg["study"]["years"][0]  # 2022
        day_start = datetime(year, 6, 1, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(year, 6, 2, 0, 0, tzinfo=timezone.utc)
        try:
            res = run_noaa_smoke_test(
                station_id=station,
                year=year,
                day_start=day_start,
                day_end=day_end,
                data_dir=data_dir / "raw/noaa",
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            results["noaa"] = res
            if not args.dry_run and res.get("coverage"):
                cov = res["coverage"]
                coverage_rows.append({
                    "source": "NOAA",
                    "dataset": "GHCNh",
                    "status": res["status"],
                    "requested_start": cov["requested_start"],
                    "requested_end": cov["requested_end"],
                    "observed_start": cov["observed_start"],
                    "observed_end": cov["observed_end"],
                    "row_count": cov["row_count"],
                    "unique_timestamps": cov["unique_timestamps"],
                    "covered_hourly_bins": cov["covered_hourly_bins"],
                    "expected_hours": cov["expected_hours"],
                    "missing_hours": cov["missing_hours"],
                    "duplicate_timestamps": cov["duplicate_timestamps"],
                    "notes": f"Station {station} (Cache hit: {res.get('cache_hit')})",
                })
        except Exception as e:
            results["noaa"] = {"status": "failure", "error": str(e)}
            coverage_rows.append({
                "source": "NOAA",
                "dataset": "GHCNh",
                "status": "failure",
                "requested_start": day_start.isoformat(),
                "requested_end": day_end.isoformat(),
                "notes": str(e),
            })
            failure_occurred = True

    # 2. CAISO
    if args.source in ("all", "caiso"):
        node = sources_cfg["price"]["node"]
        start_date = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2024, 6, 2, 0, 0, tzinfo=timezone.utc)
        try:
            res = run_caiso_smoke_test(
                node=node,
                start_date=start_date,
                end_date=end_date,
                data_dir=data_dir / "raw/caiso",
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            results["caiso"] = res
            if not args.dry_run and res.get("coverage"):
                cov = res["coverage"]
                coverage_rows.append({
                    "source": "CAISO",
                    "dataset": "PRC_LMP",
                    "status": res["status"],
                    "requested_start": cov["requested_start"],
                    "requested_end": cov["requested_end"],
                    "observed_start": cov["observed_start"],
                    "observed_end": cov["observed_end"],
                    "row_count": cov["row_count"],
                    "unique_timestamps": cov["unique_timestamps"],
                    "covered_hourly_bins": cov["covered_hourly_bins"],
                    "expected_hours": cov["expected_hours"],
                    "missing_hours": cov["missing_hours"],
                    "duplicate_timestamps": cov["duplicate_timestamps"],
                    "notes": f"Node {node} DAM hourly LMP (Cache hit: {res.get('cache_hit')})",
                })
        except Exception as e:
            results["caiso"] = {"status": "failure", "error": str(e)}
            coverage_rows.append({
                "source": "CAISO",
                "dataset": "PRC_LMP",
                "status": "failure",
                "requested_start": start_date.isoformat(),
                "requested_end": end_date.isoformat(),
                "notes": str(e),
            })
            failure_occurred = True

    # 3. EIA
    if args.source in ("all", "eia"):
        ba = sources_cfg["carbon"]["balancing_authority"]
        start_date = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
        try:
            workbook_arg = args.eia_emissions_workbook
            if not workbook_arg and (data_dir / "raw/eia/CISO.xlsx").exists():
                workbook_arg = data_dir / "raw/eia/CISO.xlsx"

            res = run_eia_smoke_test(
                balancing_authority=ba,
                start_date=start_date,
                end_date=end_date,
                use_api=args.eia_api,
                emissions_file=args.eia_emissions_file,
                emissions_workbook=workbook_arg,
                data_dir=data_dir / "raw/eia",
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            results["eia"] = res
            status = res["status"]
            cov_dict = res.get("coverage") or {}
            has_native_success = res.get("native_emissions_status") in ("success", "success_with_data_issues")
            wb_res = res.get("workbook_result") or {}
            matched_cnt = wb_res.get("data_issues_matched_count") if wb_res else res.get("data_issues_matched_count")
            flagged_cnt = wb_res.get("data_issues_flagged_count") if wb_res else res.get("data_issues_flagged_count")
            unflagged_cnt = wb_res.get("data_issues_unflagged_count") if wb_res else res.get("data_issues_unflagged_count")

            # Always emit individual metric coverage rows if available
            for metric, cov in cov_dict.items():
                if metric == "emissions_staging":
                    coverage_rows.append({
                        "source": "EIA-staging",
                        "dataset": "EIA-930-emissions-staging",
                        "status": res.get("emissions_staging_status", "success_user_supplied_staging_csv"),
                        "requested_start": cov["requested_start"],
                        "requested_end": cov["requested_end"],
                        "observed_start": cov["observed_start"],
                        "observed_end": cov["observed_end"],
                        "row_count": cov["row_count"],
                        "unique_timestamps": cov["unique_timestamps"],
                        "covered_hourly_bins": cov["covered_hourly_bins"],
                        "expected_hours": cov["expected_hours"],
                        "missing_hours": cov["missing_hours"],
                        "duplicate_timestamps": cov["duplicate_timestamps"],
                        "notes": f"BA {ba} staging emissions",
                    })
                elif metric in ("emissions_generated", "emissions_consumed", "intensity_generated", "intensity_consumed"):
                    row_notes = f"BA {ba} native workbook {metric}"
                    if matched_cnt is not None and flagged_cnt is not None:
                        row_notes += f" (data issues flagged: {flagged_cnt}/{matched_cnt})"
                    coverage_rows.append({
                        "source": "EIA",
                        "dataset": f"EIA-930-{metric.replace('_', '-')}",
                        "status": res.get("native_emissions_status", "success"),
                        "requested_start": cov["requested_start"],
                        "requested_end": cov["requested_end"],
                        "observed_start": cov["observed_start"],
                        "observed_end": cov["observed_end"],
                        "row_count": cov["row_count"],
                        "unique_timestamps": cov["unique_timestamps"],
                        "covered_hourly_bins": cov["covered_hourly_bins"],
                        "expected_hours": cov["expected_hours"],
                        "missing_hours": cov["missing_hours"],
                        "duplicate_timestamps": cov["duplicate_timestamps"],
                        "notes": row_notes,
                        "data_issues_matched_count": matched_cnt if matched_cnt is not None else "",
                        "data_issues_flagged_count": flagged_cnt if flagged_cnt is not None else "",
                        "data_issues_unflagged_count": unflagged_cnt if unflagged_cnt is not None else "",
                    })
                elif metric in ("demand", "net_generation"):
                    metric_stat = res.get(f"{metric}_status", status)
                    ds_name = "EIA-930-demand" if metric == "demand" else "EIA-930-net-generation"
                    coverage_rows.append({
                        "source": "EIA",
                        "dataset": ds_name,
                        "status": metric_stat,
                        "requested_start": cov["requested_start"],
                        "requested_end": cov["requested_end"],
                        "observed_start": cov["observed_start"],
                        "observed_end": cov["observed_end"],
                        "row_count": cov["row_count"],
                        "unique_timestamps": cov["unique_timestamps"],
                        "covered_hourly_bins": cov["covered_hourly_bins"],
                        "expected_hours": cov["expected_hours"],
                        "missing_hours": cov["missing_hours"],
                        "duplicate_timestamps": cov["duplicate_timestamps"],
                        "notes": f"BA {ba} {metric}",
                    })

            # If demand/net_generation were not in cov_dict (e.g. API was blocked and no API coverage dict exists)
            if "demand" not in cov_dict:
                coverage_rows.append({
                    "source": "EIA",
                    "dataset": "EIA-930-demand",
                    "status": res.get("demand_status", status),
                    "requested_start": start_date.isoformat(),
                    "requested_end": end_date.isoformat(),
                    "notes": f"BA {ba} demand: {res.get('diagnostic', '')}",
                })
            if "net_generation" not in cov_dict:
                coverage_rows.append({
                    "source": "EIA",
                    "dataset": "EIA-930-net-generation",
                    "status": res.get("net_generation_status", status),
                    "requested_start": start_date.isoformat(),
                    "requested_end": end_date.isoformat(),
                    "notes": f"BA {ba} net generation: {res.get('diagnostic', '')}",
                })

            # If native emissions workbook was NOT successfully ingested, record the blocker row
            if not has_native_success:
                coverage_rows.append({
                    "source": "EIA",
                    "dataset": "EIA-930-emissions-native",
                    "status": res.get("native_emissions_status", "blocked_pending_emissions_file_discovery"),
                    "requested_start": start_date.isoformat(),
                    "requested_end": end_date.isoformat(),
                    "notes": "Native EIA emissions acquisition blocked pending authentic CISO workbook discovery",
                })

            # If explicit EIA API run was requested and failed, or if emissions parsing failed
            if args.eia_api and status != "dry_run" and status != "success":
                failure_occurred = True
            if args.eia_emissions_file and res.get("emissions_staging_status") != "success_user_supplied_staging_csv" and status != "dry_run":
                failure_occurred = True
        except Exception as e:
            results["eia"] = {"status": "failure", "error": str(e)}
            coverage_rows.append({
                "source": "EIA",
                "dataset": "EIA-930",
                "status": "failure",
                "requested_start": start_date.isoformat(),
                "requested_end": end_date.isoformat(),
                "notes": str(e),
            })
            failure_occurred = True

    # Write coverage CSV if not dry-run
    if not args.dry_run and coverage_rows:
        write_coverage_report(coverage_path, coverage_rows)

    # Print summary output
    print("\n=================== HeatTrace P1 Smoke Test Report ===================")
    for src, res in results.items():
        status = res.get("status")
        print(f"[{src.upper()}] Status: {status}")
        if status == "success":
            print(f"  Raw file: {res.get('raw_path')}")
            print(f"  Cache hit: {res.get('cache_hit')}")
            man_rec = res.get("manifest_record", {})
            ret_known = man_rec.get("retrieval_time_known")
            if ret_known is not None:
                print(f"  Retrieval time known: {ret_known}")
            if "demand_status" in res:
                print(f"  Demand status: {res.get('demand_status')}")
            if "net_generation_status" in res:
                print(f"  Net-generation status: {res.get('net_generation_status')}")
            if "native_emissions_status" in res:
                print(f"  Native emissions status: {res.get('native_emissions_status')}")
            if "emissions_staging_status" in res:
                print(f"  Staging emissions status: {res.get('emissions_staging_status')}")
            if "carbon_status" in res:
                print(f"  Carbon status: {res.get('carbon_status')}")
            if "coverage" in res:
                cov = res["coverage"]
                if "row_count" in cov:
                    print(f"  Observations: {cov['row_count']} in interval, unique timestamps: {cov['unique_timestamps']}, covered hours: {cov['covered_hourly_bins']}/{cov['expected_hours']}, missing: {cov['missing_hours']}, duplicates: {cov['duplicate_timestamps']}")
                else:
                    for k, sub_cov in cov.items():
                        print(f"  {k}: {sub_cov['row_count']} in interval, covered hours: {sub_cov['covered_hourly_bins']}/{sub_cov['expected_hours']}")
            if res.get("daily_maxima"):
                for dm in res["daily_maxima"]:
                    print(f"  Daily maximum: {dm['daily_max_temperature_c']}°C on {dm['local_date']} ({dm['timezone']}) at UTC timestamps: {dm['timestamps_utc']}")
            if res.get("diagnostic"):
                print(f"  Diagnostic: {res.get('diagnostic')}")
        elif status == "blocked_pending_api_key":
            if "demand_status" in res:
                print(f"  Demand status: {res.get('demand_status')}")
            if "net_generation_status" in res:
                print(f"  Net-generation status: {res.get('net_generation_status')}")
            if "native_emissions_status" in res:
                print(f"  Native emissions status: {res.get('native_emissions_status')}")
            if "emissions_staging_status" in res:
                print(f"  Staging emissions status: {res.get('emissions_staging_status')}")
            print(f"  Diagnostic: {res.get('diagnostic')}")
        elif status == "dry_run":
            if "demand_status" in res:
                print(f"  Demand status: {res.get('demand_status')}")
            if "net_generation_status" in res:
                print(f"  Net-generation status: {res.get('net_generation_status')}")
            if "native_emissions_status" in res:
                print(f"  Native emissions status: {res.get('native_emissions_status')}")
            if "emissions_staging_status" in res:
                print(f"  Staging emissions status: {res.get('emissions_staging_status')}")
            print(f"  Request: {json.dumps(res.get('request'), indent=4)}")
        elif status == "failure":
            print(f"  Error: {res.get('error')}")

    if not args.dry_run:
        print(f"\nManifest path: {manifest_path}")
        print(f"Coverage CSV:  {coverage_path}")
    print("======================================================================\n")

    return 1 if failure_occurred else 0


def run_qc_tests(args: argparse.Namespace) -> int:
    """Run P1-QC cross-source evaluation for 1 heatwave day and 1 ordinary day."""
    config_dir = Path(args.config_dir)
    sources_cfg = load_yaml(config_dir / "sources.yaml")
    data_dir = Path(args.data_dir)
    manifest_path = data_dir / "manifests/raw_sources.jsonl"
    coverage_path = data_dir / "manifests/coverage.csv"

    qc_cfg = sources_cfg.get("qc", {})
    station_id = qc_cfg.get("primary_station_id", sources_cfg["weather"]["stations"][0]["id"])
    target_tz = qc_cfg.get("target_timezone", "America/Los_Angeles")
    node = sources_cfg["price"]["node"]
    ba = sources_cfg["carbon"]["balancing_authority"]

    days_cfg = qc_cfg.get("days", {
        "heatwave": {
            "date": "2022-09-05",
            "type": "heatwave",
            "rationale": "California Labor Day 2022 heatwave peak; 35.6°C max at SFO",
            "expected_max_temperature_c": 35.6,
        },
        "ordinary": {
            "date": "2022-06-01",
            "type": "ordinary",
            "rationale": "Typical marine-layer moderated summer day; 21.7°C max at SFO",
            "expected_max_temperature_c": 21.7,
        },
    })


    baseline_cfg = qc_cfg.get("baseline", {
        "years": [2022],
        "months": [6, 7, 8, 9],
        "heatwave_percentile": 98.0,
        "tolerance_c": 0.5,
        "heatwave_threshold_min_c": 34.0,
        "ordinary_day_range_c": [20.0, 24.0],
        "threshold_label": "P1 provisional operational threshold (single baseline year 2022)",
    })

    # Validate baseline summer statistics from cached NOAA data according to qc.baseline.years
    baseline_stats: dict[str, Any] | None = None
    baseline_years_list = baseline_cfg.get("years", [2024])
    baseline_paths: list[Path] = [
        data_dir / f"raw/noaa/GHCNh_{station_id}_{yr}.psv" for yr in baseline_years_list
    ]

    missing_baseline_files = [p for p in baseline_paths if not p.exists()]
    if missing_baseline_files:
        if not args.dry_run:
            print(f"Notice: Baseline NOAA PSV file(s) missing: {missing_baseline_files}. Will attempt acquisition during QC.")
    else:
        try:
            baseline_stats = compute_baseline_summer_percentile(
                baseline_paths,
                station_id,
                baseline_years=baseline_years_list,
                summer_months=baseline_cfg.get("months", [6, 7, 8, 9]),
                target_timezone=target_tz,
                percentile_val=baseline_cfg.get("heatwave_percentile", 98.0),
            )
        except Exception as e:
            print(f"Notice: Baseline summer calculation skipped: {e}")

    coverage_rows: list[dict[str, Any]] = []
    failure_occurred = False

    print("\n=================== HeatTrace P1-QC Quality Control Runner ===================")
    print(f"Primary Station: {station_id} | Node: {node} | BA: {ba} | Timezone: {target_tz}")
    hw_date_str = days_cfg.get("heatwave", {}).get("date", "unknown")
    ord_date_str = days_cfg.get("ordinary", {}).get("date", "unknown")
    print(f"Evaluating 2 explicit days: Heatwave ({hw_date_str}) and Ordinary Summer Day ({ord_date_str})")
    if baseline_stats:
        print(
            f"Baseline Summer ({baseline_stats['baseline_years']}, N={baseline_stats['valid_baseline_days']} days): "
            f"Median={baseline_stats['summer_median_c']}°C, "
            f"P{baseline_stats['heatwave_percentile']} Threshold={baseline_stats['heatwave_threshold_c']}°C "
            f"[{baseline_cfg.get('threshold_label', 'P1 provisional operational threshold')}]"
        )
    print()

    for day_label in ("heatwave", "ordinary"):
        day_info = days_cfg[day_label]
        date_str = day_info["date"]
        start_utc, end_utc, expected_hours = get_local_day_utc_bounds(date_str, target_timezone=target_tz)
        expected_hours_int = int(expected_hours)

        print(f"--- Running QC for {day_label.upper()} DAY: {date_str} ({day_info.get('rationale', '')}) ---")
        print(f"    Local day interval: [{start_utc.isoformat()}, {end_utc.isoformat()}) ({expected_hours} hours)")

        # 1. NOAA
        daily_max_c = None
        qc_day_status = "provisional"
        noaa_status = "provisional"
        try:
            noaa_res = run_noaa_smoke_test(
                station_id=station_id,
                year=int(date_str.split("-")[0]),
                day_start=start_utc,
                day_end=end_utc,
                data_dir=data_dir / "raw/noaa",
                manifest_path=manifest_path,
                target_timezone=target_tz,
                dry_run=args.dry_run,
            )
            noaa_status = noaa_res["status"]
            print(f"  [NOAA GHCNh] Status: {noaa_status}")

            if noaa_res.get("daily_maxima"):
                for dm in noaa_res["daily_maxima"]:
                    if dm["local_date"] == date_str:
                        daily_max_c = dm["daily_max_temperature_c"]
                        print(
                            f"    Daily maximum at {station_id}: {daily_max_c}°C at UTC: {dm['timestamps_utc']} "
                            f"(valid obs: {dm['valid_observation_count']}, dups: {dm.get('duplicate_observation_count', 0)}, conflicts: {dm.get('conflict_observation_count', 0)})"
                        )

            # Reproducibly classify and validate status using evidence
            if daily_max_c is not None and baseline_stats:
                tol = baseline_cfg.get("tolerance_c", 0.5)
                exp_c = day_info.get("expected_max_temperature_c")
                hw_thresh = baseline_stats["heatwave_threshold_c"]
                med_c = baseline_stats["summer_median_c"]
                ord_range = baseline_cfg.get("ordinary_day_range_c", [20.0, 24.0])

                if day_label == "heatwave":
                    hw_min = baseline_cfg.get("heatwave_threshold_min_c")
                    if hw_min is not None:
                        effective_threshold = max(hw_thresh, float(hw_min))
                    else:
                        effective_threshold = hw_thresh
                    meets_threshold = daily_max_c >= effective_threshold
                    matches_expected = exp_c is None or abs(daily_max_c - exp_c) <= tol
                    if meets_threshold and matches_expected:
                        qc_day_status = "verified"
                    else:
                        qc_day_status = "failure"
                elif day_label == "ordinary":
                    in_range = ord_range[0] <= daily_max_c <= ord_range[1]
                    matches_expected = exp_c is None or abs(daily_max_c - exp_c) <= tol
                    if in_range and matches_expected:
                        qc_day_status = "verified"
                    else:
                        qc_day_status = "failure"
            elif not args.dry_run:
                qc_day_status = "provisional"

            print(f"    QC Day Classification: {qc_day_status}")

            cov = noaa_res.get("coverage", {})
            if not args.dry_run:
                coverage_rows.append({
                    "source": "NOAA",
                    "dataset": "GHCNh",
                    "status": noaa_res["status"],
                    "requested_start": start_utc.isoformat(),
                    "requested_end": end_utc.isoformat(),
                    "observed_start": cov.get("observed_start", ""),
                    "observed_end": cov.get("observed_end", ""),
                    "row_count": cov.get("row_count", ""),
                    "unique_timestamps": cov.get("unique_timestamps", ""),
                    "covered_hourly_bins": cov.get("covered_hourly_bins", ""),
                    "expected_hours": expected_hours_int,
                    "missing_hours": cov.get("missing_hours", ""),
                    "duplicate_timestamps": cov.get("duplicate_timestamps", ""),
                    "notes": f"QC {day_label} day ({date_str}) Station {station_id}",
                    "qc_day_type": day_label,
                    "qc_day_status": qc_day_status,
                    "local_date": date_str,
                    "daily_max_temperature_c": daily_max_c if daily_max_c is not None else "",
                })
        except Exception as e:
            print(f"  [NOAA GHCNh] Failed: {e}")
            failure_occurred = True
            coverage_rows.append({
                "source": "NOAA",
                "dataset": "GHCNh",
                "status": "failure",
                "requested_start": start_utc.isoformat(),
                "requested_end": end_utc.isoformat(),
                "expected_hours": expected_hours_int,
                "notes": str(e),
                "qc_day_type": day_label,
                "qc_day_status": "failure",
                "local_date": date_str,
            })

        # 2. CAISO
        try:
            caiso_res = run_caiso_smoke_test(
                node=node,
                start_date=start_utc,
                end_date=end_utc,
                data_dir=data_dir / "raw/caiso",
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            print(f"  [CAISO OASIS] Status: {caiso_res['status']}")
            if caiso_res.get("diagnostic"):
                print(f"    Diagnostic: {caiso_res['diagnostic']}")
            cov = caiso_res.get("coverage", {})
            if not args.dry_run:
                coverage_rows.append({
                    "source": "CAISO",
                    "dataset": "PRC_LMP",
                    "status": caiso_res["status"],
                    "requested_start": start_utc.isoformat(),
                    "requested_end": end_utc.isoformat(),
                    "observed_start": cov.get("observed_start", ""),
                    "observed_end": cov.get("observed_end", ""),
                    "row_count": cov.get("row_count", 0),
                    "unique_timestamps": cov.get("unique_timestamps", 0),
                    "covered_hourly_bins": cov.get("covered_hourly_bins", 0),
                    "expected_hours": expected_hours_int,
                    "missing_hours": cov.get("missing_hours", expected_hours_int),
                    "duplicate_timestamps": cov.get("duplicate_timestamps", 0),
                    "notes": f"QC {day_label} day ({date_str}) Node {node} DAM hourly LMP",
                    "qc_day_type": day_label,
                    "qc_day_status": qc_day_status,
                    "local_date": date_str,
                })
        except Exception as e:
            print(f"  [CAISO OASIS] Failed: {e}")
            failure_occurred = True
            coverage_rows.append({
                "source": "CAISO",
                "dataset": "PRC_LMP",
                "status": "failure",
                "requested_start": start_utc.isoformat(),
                "requested_end": end_utc.isoformat(),
                "expected_hours": expected_hours_int,
                "notes": str(e),
                "qc_day_type": day_label,
                "qc_day_status": qc_day_status,
                "local_date": date_str,
            })

        # 3. EIA (Automatic cache hit or API key usage)
        target_eia_cache = data_dir / f"raw/eia/eia930_region_{ba}_{start_utc.strftime('%Y%m%d')}.json"
        has_eia_cache = validate_eia_json_cache(target_eia_cache, expected_ba=ba, requested_start=start_utc, requested_end=end_utc)
        has_eia_key = bool(get_eia_api_key())
        use_eia_api = args.eia_api or has_eia_cache or has_eia_key

        try:
            workbook_arg = args.eia_emissions_workbook
            if not workbook_arg and (data_dir / "raw/eia/CISO.xlsx").exists():
                workbook_arg = data_dir / "raw/eia/CISO.xlsx"

            eia_res = run_eia_smoke_test(
                balancing_authority=ba,
                start_date=start_utc,
                end_date=end_utc,
                use_api=use_eia_api,
                allow_cache_without_key=has_eia_cache,
                emissions_file=args.eia_emissions_file,
                emissions_workbook=workbook_arg,
                data_dir=data_dir / "raw/eia",
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )

            print(f"  [EIA-930 Demand] Status: {eia_res.get('demand_status')}")
            print(f"  [EIA-930 Net Generation] Status: {eia_res.get('net_generation_status')}")
            print(f"  [EIA-930 Native Emissions] Status: {eia_res.get('native_emissions_status')}")
            print(f"  [EIA-930 Staging Emissions] Status: {eia_res.get('emissions_staging_status')}")

            if not args.dry_run:
                cov_dict = eia_res.get("coverage", {})
                for metric in ("demand", "net_generation"):
                    sub_cov = cov_dict.get(metric, {})
                    metric_stat = eia_res.get(f"{metric}_status", eia_res.get("status"))
                    ds_name = "EIA-930-demand" if metric == "demand" else "EIA-930-net-generation"
                    coverage_rows.append({
                        "source": "EIA",
                        "dataset": ds_name,
                        "status": metric_stat,
                        "requested_start": start_utc.isoformat(),
                        "requested_end": end_utc.isoformat(),
                        "observed_start": sub_cov.get("observed_start", ""),
                        "observed_end": sub_cov.get("observed_end", ""),
                        "row_count": sub_cov.get("row_count", 0),
                        "unique_timestamps": sub_cov.get("unique_timestamps", 0),
                        "covered_hourly_bins": sub_cov.get("covered_hourly_bins", 0),
                        "expected_hours": expected_hours_int,
                        "missing_hours": sub_cov.get("missing_hours", expected_hours_int),
                        "duplicate_timestamps": sub_cov.get("duplicate_timestamps", 0),
                        "notes": f"QC {day_label} day ({date_str}) BA {ba} {metric}",
                        "qc_day_type": day_label,
                        "qc_day_status": qc_day_status,
                        "local_date": date_str,
                    })

                # If workbook was validated, record distinct native metrics
                native_em_stat = eia_res.get("native_emissions_status", "blocked_pending_emissions_file_discovery")
                if workbook_arg and native_em_stat in ("success", "success_with_data_issues"):
                    matched_cnt = eia_res.get("workbook_result", {}).get("data_issues_matched_count", 0)
                    flagged_cnt = eia_res.get("workbook_result", {}).get("data_issues_flagged_count", 0)
                    unflagged_cnt = eia_res.get("workbook_result", {}).get("data_issues_unflagged_count", 0)
                    for metric, label in [
                        ("emissions_generated", "emissions-generated"),
                        ("emissions_consumed", "emissions-consumed"),
                        ("intensity_generated", "intensity-generated"),
                        ("intensity_consumed", "intensity-consumed"),
                    ]:
                        sub_cov = cov_dict.get(metric, {})
                        coverage_rows.append({
                            "source": "EIA",
                            "dataset": f"EIA-930-{label}",
                            "status": native_em_stat,
                            "requested_start": start_utc.isoformat(),
                            "requested_end": end_utc.isoformat(),
                            "observed_start": sub_cov.get("observed_start", ""),
                            "observed_end": sub_cov.get("observed_end", ""),
                            "row_count": sub_cov.get("row_count", 0),
                            "unique_timestamps": sub_cov.get("unique_timestamps", 0),
                            "covered_hourly_bins": sub_cov.get("covered_hourly_bins", 0),
                            "expected_hours": expected_hours_int,
                            "missing_hours": sub_cov.get("missing_hours", expected_hours_int),
                            "duplicate_timestamps": sub_cov.get("duplicate_timestamps", 0),
                            "notes": f"QC {day_label} day ({date_str}) BA {ba} native workbook {metric} (data issues flagged: {flagged_cnt}/{matched_cnt})",
                            "qc_day_type": day_label,
                            "qc_day_status": qc_day_status,
                            "local_date": date_str,
                            "data_issues_matched_count": matched_cnt,
                            "data_issues_flagged_count": flagged_cnt,
                            "data_issues_unflagged_count": unflagged_cnt,
                        })
                else:
                    # Native emissions blocker row (recorded if workbook not provided or failed)
                    coverage_rows.append({
                        "source": "EIA",
                        "dataset": "EIA-930-emissions-native",
                        "status": native_em_stat,
                        "requested_start": start_utc.isoformat(),
                        "requested_end": end_utc.isoformat(),
                        "expected_hours": expected_hours_int,
                        "notes": f"QC {day_label} day ({date_str}) Native EIA emissions blocked pending authentic CISO workbook discovery",
                        "qc_day_type": day_label,
                        "qc_day_status": qc_day_status,
                        "local_date": date_str,
                    })

                # Staging emissions row if provided
                if eia_res.get("emissions_coverage"):
                    st_cov = eia_res["emissions_coverage"]
                    coverage_rows.append({
                        "source": "EIA-staging",
                        "dataset": "EIA-930-emissions-staging",
                        "status": eia_res.get("emissions_staging_status", "success_user_supplied_staging_csv"),
                        "requested_start": start_utc.isoformat(),
                        "requested_end": end_utc.isoformat(),
                        "observed_start": st_cov.get("observed_start", ""),
                        "observed_end": st_cov.get("observed_end", ""),
                        "row_count": st_cov.get("row_count", 0),
                        "unique_timestamps": st_cov.get("unique_timestamps", 0),
                        "covered_hourly_bins": st_cov.get("covered_hourly_bins", 0),
                        "expected_hours": expected_hours_int,
                        "missing_hours": st_cov.get("missing_hours", expected_hours_int),
                        "duplicate_timestamps": st_cov.get("duplicate_timestamps", 0),
                        "notes": f"QC {day_label} day ({date_str}) BA {ba} staging emissions",
                        "qc_day_type": day_label,
                        "qc_day_status": qc_day_status,
                        "local_date": date_str,
                    })
        except Exception as e:
            print(f"  [EIA-930] Failed: {e}")
            failure_occurred = True
            coverage_rows.append({
                "source": "EIA",
                "dataset": "EIA-930",
                "status": "failure",
                "requested_start": start_utc.isoformat(),
                "requested_end": end_utc.isoformat(),
                "expected_hours": expected_hours_int,
                "notes": str(e),
                "qc_day_type": day_label,
                "qc_day_status": qc_day_status,
                "local_date": date_str,
            })
        print()

    # Write coverage CSV if not dry-run
    if not args.dry_run and coverage_rows:
        write_coverage_report(coverage_path, coverage_rows)

    if not args.dry_run:
        print(f"Manifest path: {manifest_path}")
        print(f"Coverage CSV:  {coverage_path}")
    print("==============================================================================\n")

    if args.dry_run:
        return 0

    if failure_occurred:
        return 1

    # Check coverage rows per day for non-dry-run QC execution:
    # Both configured QC days must satisfy all required conditions:
    # - NOAA acquisition succeeds and daily classification is "verified"
    # - CAISO DAM LMP succeeds with complete expected hourly coverage (missing_hours == 0, dups == 0)
    # - EIA demand succeeds with complete expected hourly coverage (missing_hours == 0, dups == 0)
    # - EIA net generation succeeds with complete expected hourly coverage (missing_hours == 0, dups == 0)
    # - Native EIA generated emissions succeeds with complete coverage (missing_hours == 0, dups == 0)
    # - Native EIA consumed emissions succeeds with complete coverage (missing_hours == 0, dups == 0)
    # - Native EIA generated intensity succeeds with complete coverage (missing_hours == 0, dups == 0)
    # - Native EIA consumed intensity succeeds with complete coverage (missing_hours == 0, dups == 0)
    required_datasets = {
        "GHCNh",
        "PRC_LMP",
        "EIA-930-demand",
        "EIA-930-net-generation",
        "EIA-930-emissions-generated",
        "EIA-930-emissions-consumed",
        "EIA-930-intensity-generated",
        "EIA-930-intensity-consumed",
    }

    # EIA data issues gate configuration policy:
    # Default is conservative: fail_on_eia_data_issues = True
    fail_on_data_issues = True
    if args.fail_on_eia_data_issues is not None:
        fail_on_data_issues = bool(args.fail_on_eia_data_issues)
    elif "fail_on_eia_data_issues" in qc_cfg:
        fail_on_data_issues = bool(qc_cfg["fail_on_eia_data_issues"])

    allowed_native_statuses = {"success"} if fail_on_data_issues else {"success", "success_with_data_issues"}

    days_evaluated = set()
    for day_label in ("heatwave", "ordinary"):
        day_date = days_cfg[day_label]["date"]
        day_rows = [r for r in coverage_rows if r.get("local_date") == day_date or r.get("qc_day_type") == day_label]
        if not day_rows:
            return 1

        noaa_rows = [r for r in day_rows if r.get("dataset") == "GHCNh"]
        if not noaa_rows or noaa_rows[0].get("qc_day_status") != "verified" or noaa_rows[0].get("status") != "success":
            return 1

        found_datasets = set()
        for r in day_rows:
            ds = r.get("dataset")
            if ds in required_datasets:
                stat = r.get("status")
                if ds.startswith("EIA-930-emissions-") or ds.startswith("EIA-930-intensity-"):
                    if stat not in allowed_native_statuses:
                        return 1
                else:
                    if stat != "success":
                        return 1
                try:
                    exp = int(r.get("expected_hours", 0))
                    cov_bins = int(r.get("covered_hourly_bins", 0))
                    miss = int(r.get("missing_hours", 0))
                    dups = int(r.get("duplicate_timestamps", 0))
                except (ValueError, TypeError):
                    return 1
                if exp <= 0 or cov_bins < exp or miss != 0 or dups != 0:
                    return 1
                found_datasets.add(ds)

        if found_datasets != required_datasets:
            return 1
        days_evaluated.add(day_label)

    if days_evaluated != {"heatwave", "ordinary"}:
        return 1

    return 0


def run_build_aligned(args: argparse.Namespace) -> int:
    """Build, validate, and write the P2 canonical aligned dataset from cached P1 sources."""
    from heattrace.process.alignment import build_aligned_dataset, write_aligned_outputs

    config_dir = Path(args.config_dir)
    data_dir = Path(args.data_dir)
    sources_cfg = load_yaml(config_dir / "sources.yaml")

    print("\n=================== HeatTrace P2 Aligned Dataset Builder ===================")
    print("Building canonical v0 aligned dataset from cached authentic P1 sources...")

    try:
        df = build_aligned_dataset(
            sources_cfg=sources_cfg,
            data_dir=data_dir,
        )
        outputs = write_aligned_outputs(
            df,
            data_dir=data_dir,
            config_dir=config_dir,
        )
        print(f"Successfully built and validated {len(df)} aligned rows.")
        print(f"Parquet output:    {outputs['parquet_path']}")
        print(f"Sample CSV output: {outputs['sample_csv_path']}")
        print(f"Coverage CSV:      {outputs['coverage_path']}")
        print(f"Manifest JSON:     {outputs['manifest_path']}")
        print("============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[BUILD ERROR] Failed to build aligned dataset: {e}\n")
        return 1


def run_load_aligned(args: argparse.Namespace) -> int:
    """Load, validate, and display sample of the canonical aligned dataset."""
    from heattrace.process.loader import inspect_aligned_dataset

    data_dir = Path(args.data_dir)
    parquet_path = data_dir / "processed/hourly_caiso_v0.parquet"

    try:
        inspect_aligned_dataset(parquet_path)
        return 0
    except Exception as e:
        print(f"\n[LOAD ERROR] Failed to load aligned dataset: {e}\n")
        return 1


def run_build_events(args: argparse.Namespace) -> int:
    """Build, validate, and write P3 heatwave event catalogue and hourly phase labels."""
    from heattrace.process.events import build_and_export_events

    config_dir = Path(args.config_dir)
    data_dir = Path(args.data_dir)

    print("\n=================== HeatTrace P3 Heatwave Event Builder ===================")
    print("Executing Person A P3 multi-day heatwave detection and phase labeling...")

    try:
        res = build_and_export_events(data_dir=data_dir, config_dir=config_dir)
        thresh_info = res["threshold_info"]
        print(f"P90 Threshold:            {thresh_info['threshold_p90_display_c']}°C (exact: {thresh_info['threshold_p90_c']:.6f}°C)")
        print(f"Sample Size (days):       {thresh_info['sample_size']}")
        print(f"Events Detected:          {len(res['events_df'])}")
        print(f"Total Phase Hours:        {len(res['labels_df'])}")
        print(f"Events Parquet Output:    {res['parquet_events_path']}")
        print(f"Events CSV Output:        {res['csv_events_path']}")
        print(f"Hourly Labels Parquet:    {res['parquet_labels_path']}")
        print(f"Hourly Labels Sample CSV: {res['sample_csv_path']}")
        print(f"Coverage CSV:             {res['coverage_path']}")
        print(f"Manifest JSON:            {res['manifest_path']}")
        print("===========================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[BUILD ERROR] Failed to build heatwave events: {e}\n")
        return 1


def run_inspect_events(args: argparse.Namespace) -> int:
    """Inspect and display summary of detected heatwave events and phases."""
    from heattrace.process.events import inspect_heatwave_events

    data_dir = Path(args.data_dir)
    parquet_events = data_dir / "events/heatwave_events_v0.parquet"
    parquet_labels = data_dir / "events/hourly_event_labels_v0.parquet"

    try:
        inspect_heatwave_events(parquet_events, parquet_labels)
        return 0
    except Exception as e:
        print(f"\n[INSPECT ERROR] Failed to inspect heatwave events: {e}\n")
        return 1


def run_build_workloads(args: argparse.Namespace) -> int:
    """Generate deterministic workload trace."""
    from heattrace.workload import build_and_export_workloads

    data_dir = Path(args.data_dir)
    config_dir = Path(args.config_dir)
    try:
        res = build_and_export_workloads(data_dir=data_dir, config_dir=config_dir)
        print(f"Generated {len(res['df'])} workload jobs.")
        print(f"Workload Parquet: {res['parquet_path']}")
        print(f"Workload CSV:     {res['csv_path']}")
        return 0
    except Exception as e:
        print(f"\n[WORKLOAD ERROR] Failed to build workloads: {e}\n")
        return 1


def run_inspect_workloads(args: argparse.Namespace) -> int:
    """Inspect workload trace."""
    from heattrace.workload import inspect_workload_trace

    data_dir = Path(args.data_dir)
    parquet_path = data_dir / "workloads/workload_trace_v0.parquet"
    try:
        inspect_workload_trace(parquet_path)
        return 0
    except Exception as e:
        print(f"\n[WORKLOAD ERROR] Failed to inspect workloads: {e}\n")
        return 1


def run_build_p3(args: argparse.Namespace) -> int:
    """Build full P3 event catalogue, controls, workloads, and 2024 benchmark."""
    from heattrace.process.events import build_and_export_events
    from heattrace.process.controls import build_and_export_controls
    from heattrace.workload import build_and_export_workloads
    from heattrace.process.benchmark import build_and_export_p3_benchmark

    data_dir = Path(args.data_dir)
    config_dir = Path(args.config_dir)

    print("\n======================= HeatTrace P3 Full Suite Builder =======================")
    try:
        print("[1/4] Building heatwave events...")
        build_and_export_events(data_dir=data_dir, config_dir=config_dir)

        print("[2/4] Building deterministic controls...")
        build_and_export_controls(data_dir=data_dir, config_dir=config_dir)

        print("[3/4] Building synthetic workloads...")
        build_and_export_workloads(data_dir=data_dir, config_dir=config_dir)

        print("[4/4] Building 2024 event/control benchmark table...")
        b_res = build_and_export_p3_benchmark(data_dir=data_dir, config_dir=config_dir)

        print(f"Success! Benchmark generated: {b_res['parquet_path']} ({len(b_res['df_benchmark'])} rows)")
        print("===============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[BUILD P3 ERROR] Failed: {e}\n")
        return 1


def run_audit_p3(args: argparse.Namespace) -> int:
    """Execute and display P3-06 comprehensive audit."""
    from heattrace.process.audit import run_p3_audit, print_p3_audit_report

    data_dir = Path(args.data_dir)
    config_dir = Path(args.config_dir)
    try:
        audit_res = run_p3_audit(data_dir=data_dir, config_dir=config_dir)
        print_p3_audit_report(audit_res)
        return 0
    except Exception as e:
        print(f"\n[AUDIT P3 ERROR] Failed: {e}\n")
        return 1


def run_load_p3_benchmark(args: argparse.Namespace) -> int:
    """Load and inspect 2024 event/control benchmark dataset."""
    from heattrace.process.benchmark import inspect_benchmark_dataset

    data_dir = Path(args.data_dir)
    parquet_path = data_dir / "benchmarks/benchmark_2024_event_control_v0.parquet"
    try:
        inspect_benchmark_dataset(parquet_path)
        return 0
    except Exception as e:
        print(f"\n[LOAD BENCHMARK ERROR] Failed: {e}\n")
        return 1


def run_build_p4(args: argparse.Namespace) -> int:
    """Build P4 experiment manifest and historical-only forecasts."""
    from heattrace.forecast.historical import build_historical_forecast_dataset
    from heattrace.manifests import (
        build_p4_experiment_manifest,
        build_p4_forecast_manifest,
        write_atomic_json,
    )
    import pandas as pd

    repo_root = Path(".").resolve()
    data_dir = Path(args.data_dir).resolve()
    config_dir = Path(args.config_dir).resolve()

    print("\n======================= HeatTrace P4 Suite Builder =======================")
    try:
        p4_cfg_path = config_dir / "p4.yaml"
        bench_path = data_dir / "benchmarks/benchmark_2024_event_control_v0.parquet"
        bench_df = pd.read_parquet(bench_path)

        print("[1/3] Building historical-only forecasts (no future actuals)...")
        fc_df = build_historical_forecast_dataset(bench_df)

        fc_dir = data_dir / "forecasts"
        fc_dir.mkdir(parents=True, exist_ok=True)
        fc_p = fc_dir / "p4_historical_forecasts_v0.parquet"
        fc_s = fc_dir / "p4_historical_forecasts_v0_sample.csv"
        fc_df.to_parquet(fc_p, index=False)
        fc_df.head(20).to_csv(fc_s, index=False)

        print("[2/3] Writing forecast manifest...")
        fc_m = build_p4_forecast_manifest(fc_p, fc_s, p4_config_path=p4_cfg_path, repo_root=repo_root)
        write_atomic_json(data_dir / "manifests/p4_forecast_manifest.json", fc_m)

        print("[3/3] Writing experiment manifest...")
        exp_m = build_p4_experiment_manifest(repo_root=repo_root, p4_config_path=p4_cfg_path)
        write_atomic_json(data_dir / "manifests/p4_experiment_manifest.json", exp_m)

        print("Success! P4 manifests and forecasts successfully built.")
        print("==========================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[BUILD P4 ERROR] Failed: {e}\n")
        return 1


def run_run_p4(args: argparse.Namespace) -> int:
    """Execute authentic P4 benchmark across event and control windows."""
    from heattrace.evaluation.runner import run_p4_benchmark

    repo_root = Path(".").resolve()
    p4_cfg = Path(args.config_dir).resolve() / "p4.yaml"

    print("\n======================= HeatTrace P4 Benchmark Runner =======================")
    try:
        res = run_p4_benchmark(repo_root=repo_root, p4_config_path=p4_cfg)
        print(f"Success! Executed {res['metrics_count']} policy evaluations across event & control windows.")
        print(f"Outputs written to: {res['output_run_dir']}")
        print("==============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[RUN P4 ERROR] Failed: {e}\n")
        return 1


def run_audit_p4(args: argparse.Namespace) -> int:
    """Execute Gate G4-a comprehensive verification audit."""
    from heattrace.process.p4_audit import run_g4_audit

    repo_root = Path(".").resolve()
    data_dir = Path(args.data_dir).resolve()
    config_dir = Path(args.config_dir).resolve()

    print("\n======================= Gate G4-a Comprehensive Audit =======================")
    try:
        audit_res = run_g4_audit(repo_root=repo_root, data_dir=data_dir, config_dir=config_dir)
        status = audit_res["status"]
        print(f"Audit Status: {status}")
        print(f"Checked Policies: {', '.join(audit_res['checked_policies'])}")
        print(f"Checked Windows: {', '.join(audit_res['checked_windows'])}")
        print(f"Carbon Quality Label: {audit_res['carbon_data_quality']['interpretation_label']}")
        if audit_res["failure_count"] > 0:
            print(f"Failures ({audit_res['failure_count']}):")
            for f in audit_res["failure_reasons"]:
                print(f"  - {f}")
            print("==============================================================================\n")
            return 1
        print("==============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[AUDIT P4 ERROR] Failed: {e}\n")
        return 1


def run_load_p4_results(args: argparse.Namespace) -> int:
    """Load and print concise P4 comparison table and data caveats."""
    import pandas as pd
    repo_root = Path(".").resolve()
    metrics_path = repo_root / "runs/p4_v0/comparison_metrics.csv"
    if not metrics_path.exists():
        print(f"\n[LOAD P4 ERROR] Results not found at {metrics_path}. Please run --run-p4 first.\n")
        return 1

    df = pd.read_csv(metrics_path)
    print("\n======================= HeatTrace P4 Benchmark Results =======================")
    cols = [
        "window_id",
        "policy_name",
        "total_realized_cost_usd",
        "total_realized_emissions_kg",
        "sla_completion_rate",
        "cvar_cost_90",
        "cvar_emissions_90",
        "comparator_status",
    ]
    display_cols = [c for c in cols if c in df.columns]
    print(df[display_cols].to_string(index=False))
    print("\n------------------------- Carbon Data Quality Disclosure -------------------------")
    print("NOTE: All 240 benchmark rows carry EIA known-data-issue flags (0 primary-eligible).")
    print("Emissions metrics are calculated for algorithmic sensitivity only ('quality_limited_sensitivity_only').")
    print("They must not be interpreted as clean primary causal evidence.")
    print("==============================================================================\n")
    return 0


def run_build_p5(args: argparse.Namespace) -> int:
    """Execute full P5 pipeline."""
    from heattrace.experiments.pipeline import run_complete_p5_pipeline

    repo_root = Path(".").resolve()
    print("\n======================= HeatTrace P5 Pipeline Runner =======================")
    try:
        res = run_complete_p5_pipeline(repo_root=repo_root, source_code_commit=args.source_commit)
        print(f"Success! Generated P5 experimental outputs and manifest at {res['manifest_path']}.")
        print(f"Total tracked output files generated: {res['results_generated']}.")
        print("============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[BUILD P5 ERROR] Failed: {e}\n")
        return 1


def run_audit_p5(args: argparse.Namespace) -> int:
    """Execute Gate G5-a comprehensive audit."""
    from heattrace.process.p5_audit import run_g5_audit

    repo_root = Path(".").resolve()
    print("\n======================= Gate G5-a Comprehensive Audit =======================")
    try:
        audit_res = run_g5_audit(repo_root=repo_root)
        status = audit_res["status"]
        print(f"Audit Status: {status}")
        print(f"Checked Experiments: {', '.join(audit_res['checked_experiments'])}")
        print(f"Full Benchmark Comparator Status: {audit_res['comparator_audit']['full_benchmark_status']}")
        print(f"Carbon Quality Label: {audit_res['carbon_data_quality']['interpretation_label']}")
        if audit_res["failure_count"] > 0:
            print(f"Failures ({audit_res['failure_count']}):")
            for f in audit_res["failure_reasons"]:
                print(f"  - {f}")
            print("============================================================================\n")
            return 1
        print("============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[AUDIT P5 ERROR] Failed: {e}\n")
        return 1


def run_load_p5_results(args: argparse.Namespace) -> int:
    """Load and summarize P5 experimental results."""
    import pandas as pd
    repo_root = Path(".").resolve()
    results_dir = repo_root / "data/results"

    e2_path = results_dir / "p5_e2_policy_comparison_metrics.csv"
    if not e2_path.exists():
        print(f"\n[LOAD P5 ERROR] Results not found at {e2_path}. Please run --build-p5 first.\n")
        return 1

    df_e2 = pd.read_csv(e2_path)
    print("\n======================= HeatTrace P5-E2 Benchmark Results =======================")
    cols = ["window_id", "policy_name", "total_realized_cost_usd", "total_realized_emissions_kg", "cvar_cost_90", "comparator_status"]
    print(df_e2[[c for c in cols if c in df_e2.columns]].to_string(index=False))

    strat_path = results_dir / "p5_e4_strategy_comparison_summary.csv"
    if strat_path.exists():
        df_strat = pd.read_csv(strat_path)
        print("\n================== HeatTrace P5-E4 Equal-Budget Sampling Summary =================")
        print(df_strat[["sampling_strategy", "target_budget_hours", "achieved_budget_hours", "ranking_identical_across_policies"]].to_string(index=False))

    print("\n------------------------- Carbon Data Quality Disclosure -------------------------")
    print("NOTE: Carbon intensity data contains EIA Known Data Issue flags across all rows.")
    print("Carbon results are strictly 'quality_limited_sensitivity_only'.")
    print("=================================================================================\n")
    return 0


def run_build_p5_5(args: argparse.Namespace) -> int:
    """Execute full P5.5 pipeline: freeze grid v2, run experiment, generate tables, reports, and figures."""
    from heattrace.analysis.p5_5_figures import compute_headline_findings, write_headline_findings, generate_p5_5_figures_v2, generate_p5_5_summary_tables_v2
    from heattrace.analysis.p5_5_reports import generate_p5_5_reports
    from heattrace.experiments.p5_5_comparator_validation import run_small_instance_comparator_validation
    from heattrace.experiments.p5_5_grid import freeze_experiment_grid_v2
    from heattrace.experiments.p5_5_runner import run_full_p5_5_experiment_v2
    from heattrace.process.p5_5_audit import run_g5_5_audit

    repo_root = Path(".").resolve()
    print("\n======================= HeatTrace P5.5 Pipeline Runner (v2) =======================")
    try:
        print("[1/6] Freezing preregistered experiment grid v2...")
        freeze_experiment_grid_v2(
            config_path=repo_root / "configs/p5_5.yaml",
            output_path=repo_root / "data/manifests/p5_5_experiment_grid.json",
        )

        print("[2/6] Executing 270 scenarios across 5 policies (1,350 total runs with schedule artifacts)...")
        results_df, manifest = run_full_p5_5_experiment_v2(
            benchmark_parquet_path=repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet",
            config_path=repo_root / "configs/p5_5.yaml",
            output_dir=repo_root / "data/results",
            manifest_dir=repo_root / "data/manifests",
        )
        print(f"      Completed {len(results_df)} runs in {manifest['total_runtime_seconds']}s.")
        print(f"      Feasible runs: {manifest['summary']['feasible_runs']}, Infeasible runs: {manifest['summary']['infeasible_runs']}.")

        print("[3/6] Running exact small-instance comparator validation...")
        comp_df, comp_summary = run_small_instance_comparator_validation(
            benchmark_parquet_path=repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet",
            config_path=repo_root / "configs/p5_5.yaml",
            output_dir=repo_root / "data/results",
        )
        print(f"      Comparator validation: {comp_summary['status']} ({len(comp_df)} policy evaluations across {comp_summary['total_instances_evaluated']} instances).")

        print("[4/6] Generating summary tables across 3 result views and headline findings...")
        findings = compute_headline_findings(results_df, comp_df)
        write_headline_findings(findings, repo_root / "data/results")
        tables = generate_p5_5_summary_tables_v2(results_df, output_dir=repo_root / "data/results")
        figs = generate_p5_5_figures_v2(results_df, comp_df, output_fig_dir=repo_root / "data/figures", output_results_dir=repo_root / "data/results")
        print(f"      Generated {len(tables)} tables and {len(figs)} figures.")

        print("[5/6] Generating findings report and professor briefing from machine-readable findings...")
        rep_path, brief_path = generate_p5_5_reports(
            headline_findings_path=repo_root / "data/results/p5_5_headline_findings.json",
            docs_dir=repo_root / "docs",
        )
        print(f"      Reports written to {rep_path} and {brief_path}.")

        print("[6/6] Running Gate G5.5-a verification audit (23 fail-closed checks)...")
        audit_res = run_g5_5_audit(repo_root=repo_root)
        print(f"      Gate G5.5-a status: {audit_res['status']}.")
        if audit_res["status"] != "VERIFIED_PASS":
            print(f"      Failures: {audit_res['failure_reasons']}")
            return 1

        print("====================================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[BUILD P5.5 ERROR] Failed: {e}\n")
        return 1


def run_run_p5_5(args: argparse.Namespace) -> int:
    """Execute P5.5 experiment grid and record results."""
    from heattrace.experiments.p5_5_runner import run_full_p5_5_experiment
    repo_root = Path(".").resolve()
    print("\n======================= HeatTrace P5.5 Experiment Runner =======================")
    try:
        results_df, manifest = run_full_p5_5_experiment(
            benchmark_parquet_path=repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet",
            config_path=repo_root / "configs/p5_5.yaml",
            output_dir=repo_root / "data/results",
            manifest_dir=repo_root / "data/manifests",
        )
        print(f"Success! Evaluated {len(results_df)} runs across {manifest['total_scenarios']} scenarios.")
        print("=================================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[RUN P5.5 ERROR] Failed: {e}\n")
        return 1


def run_audit_p5_5(args: argparse.Namespace) -> int:
    """Execute Gate G5.5-a comprehensive verification audit."""
    from heattrace.process.p5_5_audit import run_g5_5_audit
    repo_root = Path(".").resolve()
    print("\n======================= Gate G5.5-a Comprehensive Audit =======================")
    try:
        audit_res = run_g5_5_audit(repo_root=repo_root)
        status = audit_res["status"]
        print(f"Audit Status: {status}")
        print(f"Total Scenarios Evaluated: {audit_res['total_scenarios_evaluated']}")
        print(f"Total Runs Evaluated:      {audit_res['total_runs_evaluated']}")
        print(f"Feasible Runs:             {audit_res['feasible_runs_count']}")
        print(f"Infeasible Runs:           {audit_res['infeasible_runs_count']}")
        print(f"Checks Passed:             {sum(1 for v in audit_res['checks'].values() if v)} / {len(audit_res['checks'])}")
        print(f"Carbon Quality Label:      {audit_res['carbon_data_quality']['interpretation_label']}")
        if audit_res["failure_reasons"]:
            print(f"Failure Reasons:           {audit_res['failure_reasons']}")
        print("===============================================================================\n")
        return 0 if status == "VERIFIED_PASS" else 1
    except Exception as e:
        print(f"\n[AUDIT P5.5 ERROR] Failed: {e}\n")
        return 1


def run_load_p5_5_results(args: argparse.Namespace) -> int:
    """Load, summarize, and display P5.5 experiment findings."""
    import pandas as pd
    repo_root = Path(".").resolve()
    summary_path = repo_root / "data/results/p5_5_policy_comparison_summary.csv"
    if not summary_path.exists():
        print(f"\n[LOAD P5.5 ERROR] Results summary not found at {summary_path}. Run --build-p5-5 first.\n")
        return 1

    df = pd.read_csv(summary_path)
    print("\n======================= HeatTrace P5.5 Policy Performance Summary =======================")
    key_cols = ["window_type", "policy_name", "forecast_scenario_id", "total_realized_cost_usd_mean", "total_realized_emissions_kg_mean", "is_feasible_mean"]
    print(df[[c for c in key_cols if c in df.columns]].head(20).to_string(index=False))

    print("\n------------------------- Carbon Data Quality Disclosure -------------------------")
    print("NOTE: Carbon intensity data contains EIA Known Data Issue flags across all rows.")
    print("Carbon results are strictly 'quality_limited_sensitivity_only'.")
    print("==================================================================================\n")
    return 0


def run_run_p6_thermal_smoke(args: argparse.Namespace) -> int:
    """Execute Day 1 P6 thermal stress smoke test."""
    from heattrace.experiments.p6_thermal_grid import run_p6_thermal_smoke
    repo_root = Path(".").resolve()
    print("\n================== HeatTrace P6 Day 1 Thermal Stress Smoke ==================")
    try:
        results_df, manifest = run_p6_thermal_smoke(
            benchmark_parquet_path=repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet",
            workload_parquet_path=repo_root / "data/workloads/workload_trace_v0.parquet",
            forecast_parquet_path=repo_root / "data/forecasts/p4_historical_forecasts_v0.parquet",
            config_path=repo_root / "configs/p6_thermal.yaml",
            output_dir=repo_root / "data/results",
            manifest_dir=repo_root / "data/manifests",
        )
        print(f"Success! Executed {len(results_df)} runs.")
        print(f"Results written to: {manifest['results_files']['csv']['path']}")
        print(f"Manifest written to: {repo_root / 'data/manifests/p6_day1_smoke_manifest.json'}")
        print(f"Feasible runs: {manifest['summary']['feasible_runs']}/{len(results_df)}")
        print("============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[P6 THERMAL SMOKE ERROR] Failed: {e}\n")
        return 1


def run_materialize_gate1(args: argparse.Namespace) -> int:
    """Execute end-to-end reproducible Gate 1 materialization pipeline."""
    from heattrace.process.p6_event_bundle import materialize_p6_gate1_benchmarks
    repo_root = Path(".").resolve()
    print("\n================== HeatTrace P6 Gate 1 Materializer ==================")
    try:
        manifest = materialize_p6_gate1_benchmarks(
            repo_root=repo_root,
            config_dir=repo_root / args.config_dir,
            data_dir=repo_root / args.data_dir,
            random_seed=20261016,
            design_mode="fallback",
        )
        print("Success! Materialized all Gate 1 benchmarks.")
        print(f"Hourly pairs: {manifest['output_files']['pairs_parquet']['path']} ({manifest['summary']['total_benchmark_rows']} rows)")
        print(f"Index: {manifest['output_files']['index_csv']['path']} ({manifest['summary']['total_triplets']} triplets)")
        print(f"Blind pool: {manifest['output_files']['blind_pool_csv']['path']} ({manifest['summary']['total_blind_candidates']} candidates)")
        print(f"Manifest: {manifest['manifest_path']}")
        print("======================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[GATE 1 MATERIALIZER ERROR] Failed: {e}\n")
        return 1


def run_run_p6_pilot(args: argparse.Namespace) -> int:
    """Execute Day 8 P6 development-only pilot."""
    from heattrace.experiments.p6_validity_runner import execute_development_pilot
    repo_root = Path(".").resolve()
    print("\n================== HeatTrace P6 Development Pilot Runner ==================")
    try:
        pilot_df, meta = execute_development_pilot(
            repo_root=repo_root,
            config_path=repo_root / args.config_dir / "p6_validity.yaml",
            output_dir=repo_root / args.data_dir / "results",
        )
        print("Success! Executed development-only pilot.")
        print(f"Total cells: {meta['total_cells']} (Unique run IDs: {meta['unique_run_ids']})")
        print(f"Successful: {meta['successful_runs']}, Failed: {meta['failed_runs']}")
        print(f"Wall time: {meta['total_wall_time_seconds']}s")
        print(f"Deliverable 1: {repo_root / args.data_dir / 'results/p6_development_pilot.parquet'}")
        print(f"Deliverable 2: {repo_root / args.data_dir / 'results/p6_forecast_metrics.csv'}")
        print("===========================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[P6 PILOT RUNNER ERROR] Failed: {e}\n")
        return 1


def run_run_p6_confirmation(args: argparse.Namespace) -> int:
    """Execute Day 10 P8 frozen 756-cell confirmation matrix."""
    from heattrace.experiments.p6_validity_runner import execute_frozen_confirmation
    repo_root = Path(".").resolve()
    print("\n================== HeatTrace P8 Frozen Confirmation Runner ==================")
    try:
        commit = args.execution_commit
        if not commit:
            print("\n[P6 CONFIRMATION ERROR] --execution-commit <40-char-sha> is strictly required.\n")
            return 1
        final_df, meta = execute_frozen_confirmation(
            repo_root=repo_root,
            execution_commit=commit,
            output_dir=repo_root / args.data_dir / "results",
        )
        print("Success! Processed confirmatory matrix.")
        if meta.get("status") == "ALREADY_COMPLETED":
            print(f"Status: {meta['status']} ({meta.get('message')})")
            print(f"Scheduled cells: {meta.get('scheduled_cells', 0)}")
        print(f"Total cells: {meta['total_confirmatory_cells']} (Unique run IDs: {meta['unique_run_ids']})")
        print(f"Successful: {meta['successful_runs']}, Failed: {meta['failed_runs']}")
        print(f"Execution commit: {meta['execution_commit']}")
        print(f"Deliverable 1: {repo_root / args.data_dir / 'results/p6_validity_runs.parquet'}")
        print(f"Deliverable 2: {repo_root / args.data_dir / 'results/p6_validity_manifest.json'}")
        print(f"Deliverable 3: {repo_root / args.data_dir / 'results/p6_validity_execution.jsonl'}")
        print("============================================================================\n")
        return 0
    except Exception as e:
        print(f"\n[P6 CONFIRMATION ERROR] Failed: {e}\n")
        return 1


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.run_p6_confirmation:
        code = run_run_p6_confirmation(args)
    elif args.run_p6_pilot:
        code = run_run_p6_pilot(args)
    elif args.materialize_gate1:
        code = run_materialize_gate1(args)
    elif args.run_p6_thermal_smoke:
        code = run_run_p6_thermal_smoke(args)
    elif args.build_p5_5:
        code = run_build_p5_5(args)
    elif args.run_p5_5:
        code = run_run_p5_5(args)
    elif args.audit_p5_5:
        code = run_audit_p5_5(args)
    elif args.load_p5_5_results:
        code = run_load_p5_5_results(args)
    elif args.build_p5 or args.run_p5:
        code = run_build_p5(args)
    elif args.audit_p5:
        code = run_audit_p5(args)
    elif args.load_p5_results:
        code = run_load_p5_results(args)
    elif args.build_p4:
        code = run_build_p4(args)
    elif args.run_p4:
        code = run_run_p4(args)
    elif args.audit_p4:
        code = run_audit_p4(args)
    elif args.load_p4_results:
        code = run_load_p4_results(args)
    elif args.build_p3:
        code = run_build_p3(args)
    elif args.audit_p3:
        code = run_audit_p3(args)
    elif args.load_p3_benchmark:
        code = run_load_p3_benchmark(args)
    elif args.build_workloads:
        code = run_build_workloads(args)
    elif args.inspect_workloads:
        code = run_inspect_workloads(args)
    elif args.build_events:
        code = run_build_events(args)
    elif args.inspect_events:
        code = run_inspect_events(args)
    elif args.build_aligned:
        code = run_build_aligned(args)
    elif args.load_aligned:
        code = run_load_aligned(args)
    elif args.qc:
        code = run_qc_tests(args)
    else:
        code = run_smoke_tests(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
