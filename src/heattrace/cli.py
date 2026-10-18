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
    psv_path: str | Path,
    station_id: str,
    *,
    baseline_years: list[int] = [2022],
    summer_months: list[int] = [6, 7, 8, 9],
    target_timezone: str = "America/Los_Angeles",
    percentile_val: float = 98.0,
) -> dict[str, Any]:
    """Compute baseline summer daily maximum statistics and percentile threshold from authentic cached NOAA data."""
    path = Path(psv_path)
    if not path.exists():
        raise FileNotFoundError(f"Baseline NOAA PSV not found: {path}")

    from zoneinfo import ZoneInfo
    tz = ZoneInfo(target_timezone)

    # Parse all rows in baseline years and summer months
    all_rows = parse_ghcnh_psv(path)
    summer_rows: list[dict[str, Any]] = []
    for r in all_rows:
        ts = r["timestamp_utc"].astimezone(tz)
        if ts.year in baseline_years and ts.month in summer_months:
            summer_rows.append(r)

    if not summer_rows:
        raise ValueError(f"No summer rows found for station {station_id} in {path}")

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
            cov_dict = res.get("coverage", {})
            has_native_success = res.get("native_emissions_status") == "success"

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
                        "notes": f"BA {ba} native workbook {metric}",
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

    # Validate baseline summer statistics from cached NOAA data if available
    baseline_stats: dict[str, Any] | None = None
    noaa_psv_cache = data_dir / f"raw/noaa/GHCNh_{station_id}_{sources_cfg['study']['years'][0]}.psv"
    if noaa_psv_cache.exists():
        try:
            baseline_stats = compute_baseline_summer_percentile(
                noaa_psv_cache,
                station_id,
                baseline_years=baseline_cfg.get("years", [2022]),
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
    print("Evaluating 2 explicit days: Heatwave (2022-09-05) and Ordinary Summer Day (2022-06-01)")
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
                    hw_min = baseline_cfg.get("heatwave_threshold_min_c", 34.0)
                    effective_threshold = max(hw_thresh, hw_min)
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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.qc:
        code = run_qc_tests(args)
    else:
        code = run_smoke_tests(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
