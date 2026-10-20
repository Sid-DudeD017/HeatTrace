"""Stage 5 and 6: Aligned 2024 Event/Control Benchmark Construction, Verification, and Audit."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.caiso import parse_caiso_zip, validate_caiso_lmp_rows
from heattrace.ingest.coverage import compute_hourly_coverage
from heattrace.ingest.eia import (
    LB_TO_GRAMS,
    parse_and_validate_eia_ciso_workbook,
    parse_and_validate_eia_json,
)
from heattrace.ingest.noaa import (
    check_noaa_temperature_quality,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
)
from heattrace.ingest.provenance import sha256_file
from heattrace.process.controls import match_deterministic_control
from heattrace.process.events import compute_heatwave_percentile_threshold, detect_heatwave_events, load_heatwave_config


BENCHMARK_COLUMNS: list[str] = [
    "timestamp_utc",
    "local_timestamp",
    "local_date",
    "hour_local",
    "window_type",
    "window_id",
    "phase_label",
    "temperature_c",
    "temperature_obs_count",
    "temperature_missing",
    "price_usd_per_mwh",
    "price_missing",
    "demand_mw",
    "demand_missing",
    "net_generation_mw",
    "net_generation_missing",
    "carbon_g_per_kwh",
    "carbon_missing",
    "carbon_data_issue",
    "carbon_primary_analysis_eligible",
    "source_quality",
    "source_station_id",
    "source_caiso_node",
    "source_balancing_authority",
]


VALID_EVENT_PHASES = frozenset({"onset", "peak", "sustained", "recovery"})
VALID_CONTROL_PHASES = frozenset({"control", "control_anchor"})
VALID_WINDOW_TYPES = frozenset({"event", "control"})
VALID_SOURCE_QUALITIES = frozenset({"success", "success_with_data_issues", "missing"})


def build_benchmark_hourly_rows(
    *,
    window_type: str,  # "event" or "control"
    window_id: str,    # "HW_20240702" or "CTRL_20240605"
    start_date_str: str,
    end_date_inclusive_str: str,
    phase_mapping: dict[str, str],  # local_date -> phase_label
    data_dir: Path,
    station_id: str = "USW00023234",
    caiso_node: str = "TH_NP15_GEN-APND",
    balancing_authority: str = "CISO",
    target_timezone: str = "America/Los_Angeles",
) -> list[dict[str, Any]]:
    """Build aligned 120 hourly rows for one benchmark window from cached authentic sources."""
    tz = ZoneInfo(target_timezone)

    # Compute UTC bounds
    start_utc, _, _ = get_local_day_utc_bounds(start_date_str, target_timezone=target_timezone)
    _, end_utc, _ = get_local_day_utc_bounds(end_date_inclusive_str, target_timezone=target_timezone)

    expected_hours = int(round((end_utc - start_utc).total_seconds() / 3600.0))
    if expected_hours != 120:
        raise ValueError(f"Window {window_id} ({start_date_str} to {end_date_inclusive_str}) expected 120h, got {expected_hours}h")

    # 1. NOAA Observations
    # Look for matching station file across years
    noaa_file = data_dir / f"raw/noaa/GHCNh_{station_id}_{start_date_str[:4]}.psv"
    if not noaa_file.exists():
        # Fallback to search any matching station file
        cands = list((data_dir / "raw/noaa").glob(f"GHCNh_{station_id}_*.psv"))
        if not cands:
            raise FileNotFoundError(f"NOAA file not found for station {station_id} in {data_dir / 'raw/noaa'}")
        noaa_file = cands[0]

    noaa_all = parse_ghcnh_psv(noaa_file, filter_date_start=start_utc, filter_date_end=end_utc)
    # Group by interval-start UTC
    noaa_by_hour: dict[datetime, list[float]] = {}
    for r in noaa_all:
        qc = check_noaa_temperature_quality(r.get("temperature_quality_code", ""))
        temp = r.get("temperature_c")
        if qc == "accepted" and temp is not None:
            ts = r["timestamp_utc"]
            bin_start = datetime(ts.year, ts.month, ts.day, ts.hour, 0, tzinfo=timezone.utc)
            noaa_by_hour.setdefault(bin_start, []).append(float(temp))

    # 2. CAISO OASIS LMP
    start_tag = start_date_str.replace("-", "")
    end_tag = (date.fromisoformat(end_date_inclusive_str) + timedelta(days=1)).strftime("%Y%m%d")
    caiso_file = data_dir / f"raw/caiso/caiso_dam_lmp_{caiso_node}_{start_tag}_{end_tag}.zip"
    if not caiso_file.exists():
        raise FileNotFoundError(f"CAISO zip file not found: {caiso_file}")

    caiso_parsed, err = parse_caiso_zip(caiso_file, expected_node=caiso_node, expected_market="DAM")
    if err:
        raise ValueError(f"Error parsing CAISO zip {caiso_file}: {err}")
    lmp_rows = [r for r in caiso_parsed if r["lmp_type"] == "LMP"]
    validate_caiso_lmp_rows(
        lmp_rows,
        expected_node=caiso_node,
        expected_market="DAM",
        requested_start=start_utc,
        requested_end=end_utc,
    )
    caiso_by_hour = {r["timestamp_utc"]: float(r["price_usd_per_mwh"]) for r in lmp_rows}

    # 3. EIA API Demand and Net Gen
    eia_json_file = data_dir / f"raw/eia/eia930_region_{balancing_authority}_{start_tag}.json"
    if not eia_json_file.exists():
        raise FileNotFoundError(f"EIA json file not found: {eia_json_file}")
    eia_api_data = parse_and_validate_eia_json(
        eia_json_file.read_text(encoding="utf-8"),
        expected_ba=balancing_authority,
        requested_start=start_utc,
        requested_end=end_utc,
    )
    demand_by_hour = {r["timestamp_utc"]: float(r["value_mw"]) for r in eia_api_data["demand_rows"]}
    net_gen_by_hour = {r["timestamp_utc"]: float(r["value_mw"]) for r in eia_api_data["net_gen_rows"]}

    # 4. EIA Workbook Emissions and Intensity
    workbook_file = data_dir / f"raw/eia/{balancing_authority}.xlsx"
    if not workbook_file.exists():
        workbook_file = data_dir / "raw/eia/CISO.xlsx"
    eia_wb_data = parse_and_validate_eia_ciso_workbook(
        workbook_file,
        requested_start=start_utc,
        requested_end=end_utc,
        expected_ba=balancing_authority,
    )
    wb_by_hour = {r["timestamp_utc"]: r for r in eia_wb_data["rows"]}

    rows: list[dict[str, Any]] = []
    curr = start_utc
    while curr < end_utc:
        loc_dt = curr.astimezone(tz)
        loc_ts_str = loc_dt.strftime("%Y-%m-%dT%H:%M:%S")
        loc_d_str = loc_dt.strftime("%Y-%m-%d")
        loc_hour = loc_dt.hour

        phase_val = phase_mapping.get(loc_d_str, "control" if window_type == "control" else "sustained")

        # Weather
        obs = noaa_by_hour.get(curr, [])
        if obs:
            temp_c = round(float(sum(obs) / len(obs)), 2)
            temp_obs_cnt = len(obs)
            temp_missing = False
        else:
            temp_c = None
            temp_obs_cnt = 0
            temp_missing = True

        # Price
        if curr in caiso_by_hour:
            price_val = caiso_by_hour[curr]
            price_missing = False
        else:
            price_val = None
            price_missing = True

        # Demand & Net Gen
        if curr in demand_by_hour:
            demand_val = demand_by_hour[curr]
            demand_missing = False
        else:
            demand_val = None
            demand_missing = True

        if curr in net_gen_by_hour:
            net_gen_val = net_gen_by_hour[curr]
            net_gen_missing = False
        else:
            net_gen_val = None
            net_gen_missing = True

        # Carbon
        if curr in wb_by_hour:
            wb_rec = wb_by_hour[curr]
            carbon_val = wb_rec["co2_intensity_generated_g_per_kwh"]
            carbon_missing = False
            has_issue = wb_rec["has_data_issue"]
            carbon_eligible = not has_issue
            source_q = "success_with_data_issues" if has_issue else "success"
        else:
            carbon_val = None
            carbon_missing = True
            has_issue = False
            carbon_eligible = False
            source_q = "missing"

        rows.append({
            "timestamp_utc": curr,
            "local_timestamp": loc_ts_str,
            "local_date": loc_d_str,
            "hour_local": loc_hour,
            "window_type": window_type,
            "window_id": window_id,
            "phase_label": phase_val,
            "temperature_c": temp_c,
            "temperature_obs_count": temp_obs_cnt,
            "temperature_missing": temp_missing,
            "price_usd_per_mwh": price_val,
            "price_missing": price_missing,
            "demand_mw": demand_val,
            "demand_missing": demand_missing,
            "net_generation_mw": net_gen_val,
            "net_generation_missing": net_gen_missing,
            "carbon_g_per_kwh": carbon_val,
            "carbon_missing": carbon_missing,
            "carbon_data_issue": has_issue,
            "carbon_primary_analysis_eligible": carbon_eligible,
            "source_quality": source_q,
            "source_station_id": station_id,
            "source_caiso_node": caiso_node,
            "source_balancing_authority": balancing_authority,
        })

        curr += timedelta(hours=1)

    return rows


def build_and_export_p3_benchmark(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
) -> dict[str, Any]:
    """Build, validate, and export the complete 240-row 2024 event/control benchmark."""
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    # 1. Load frozen configurations
    sources_cfg = load_yaml(config_dir / "sources.yaml")
    study_cfg = load_yaml(config_dir / "study.yaml")
    hw_cfg = load_heatwave_config(sources_cfg=sources_cfg, study_cfg=study_cfg, config_dir=config_dir)

    station_id = hw_cfg["station_id"]
    target_timezone = hw_cfg["target_timezone"]

    price_cfg = sources_cfg.get("price")
    if not isinstance(price_cfg, dict) or not price_cfg.get("node"):
        raise ValueError("Missing required configuration 'price.node' in configs/sources.yaml")
    caiso_node = price_cfg["node"]

    carbon_cfg = sources_cfg.get("carbon")
    if not isinstance(carbon_cfg, dict) or not carbon_cfg.get("balancing_authority"):
        raise ValueError("Missing required configuration 'carbon.balancing_authority' in configs/sources.yaml")
    balancing_authority = carbon_cfg["balancing_authority"]

    # 2. Dynamically derive event, control, and phase mappings from catalogues
    events_parquet = data_dir / "events/heatwave_events_v0.parquet"
    control_parquet = data_dir / "events/control_catalogue_v0.parquet"
    labels_parquet = data_dir / "events/hourly_event_labels_v0.parquet"
    workload_parquet = data_dir / "workloads/workload_trace_v0.parquet"

    if not events_parquet.exists():
        raise FileNotFoundError(f"Event catalogue missing: {events_parquet}")
    if not control_parquet.exists():
        raise FileNotFoundError(f"Control catalogue missing: {control_parquet}")
    if not labels_parquet.exists():
        raise FileNotFoundError(f"Hourly labels missing: {labels_parquet}")

    df_events = pd.read_parquet(events_parquet)
    df_control = pd.read_parquet(control_parquet)
    df_labels = pd.read_parquet(labels_parquet)

    # Validate approved 2024 benchmark event
    hw_2024_rows = df_events[df_events["event_id"] == "HW_20240702"]
    if hw_2024_rows.empty:
        raise ValueError("Event HW_20240702 not found in heatwave event catalogue")
    ev_row = hw_2024_rows.iloc[0]

    # Check station metadata agreement
    if str(ev_row["station_id"]) != station_id:
        raise ValueError(f"Event station '{ev_row['station_id']}' != config station '{station_id}'")

    # Validate approved 2024 benchmark control
    ctrl_rows = df_control[df_control["matched_event_id"] == "HW_20240702"]
    if ctrl_rows.empty:
        raise ValueError("Matched control for HW_20240702 not found in control catalogue")
    ctrl_row = ctrl_rows.iloc[0]
    if ctrl_row["control_id"] != "CTRL_20240605":
        raise ValueError(f"Expected control CTRL_20240605, got {ctrl_row['control_id']}")

    # Derive event window boundaries: onset (1 day pre) to recovery (1 day post)
    ev_start_d = date.fromisoformat(str(ev_row["local_start_date"])) - timedelta(days=1)
    ev_end_d = date.fromisoformat(str(ev_row["local_end_date"])) + timedelta(days=1)
    event_start_str = ev_start_d.isoformat()
    event_end_str = ev_end_d.isoformat()

    # Extract phase map dynamically from df_labels for HW_20240702
    hw_labels = df_labels[df_labels["event_id"] == "HW_20240702"]
    event_phase_map: dict[str, str] = {}
    for d_str, grp in hw_labels.groupby("local_date"):
        phases = grp["event_phase"].unique().tolist()
        event_phase_map[str(d_str)] = phases[0]

    # Derive control window boundaries and phase mapping
    ctrl_start_str = str(ctrl_row["local_start_date"])
    ctrl_end_exclusive = date.fromisoformat(str(ctrl_row["local_end_exclusive"]))
    ctrl_end_str = (ctrl_end_exclusive - timedelta(days=1)).isoformat()
    anchor_str = str(ctrl_row["anchor_date"])

    control_phase_map: dict[str, str] = {}
    cur_c_d = date.fromisoformat(ctrl_start_str)
    while cur_c_d < ctrl_end_exclusive:
        cur_iso = cur_c_d.isoformat()
        control_phase_map[cur_iso] = "control_anchor" if cur_iso == anchor_str else "control"
        cur_c_d += timedelta(days=1)

    combined_phase_map = {**event_phase_map, **control_phase_map}

    event_rows = build_benchmark_hourly_rows(
        window_type="event",
        window_id="HW_20240702",
        start_date_str=event_start_str,
        end_date_inclusive_str=event_end_str,
        phase_mapping=event_phase_map,
        data_dir=data_dir,
        station_id=station_id,
        caiso_node=caiso_node,
        balancing_authority=balancing_authority,
        target_timezone=target_timezone,
    )

    control_rows = build_benchmark_hourly_rows(
        window_type="control",
        window_id=str(ctrl_row["control_id"]),
        start_date_str=ctrl_start_str,
        end_date_inclusive_str=ctrl_end_str,
        phase_mapping=control_phase_map,
        data_dir=data_dir,
        station_id=station_id,
        caiso_node=caiso_node,
        balancing_authority=balancing_authority,
        target_timezone=target_timezone,
    )

    all_rows = control_rows + event_rows  # 120 control + 120 event = 240 rows
    df_benchmark = pd.DataFrame(all_rows, columns=BENCHMARK_COLUMNS)

    validate_benchmark_dataframe(
        df_benchmark,
        expected_event_id="HW_20240702",
        expected_control_id="CTRL_20240605",
        expected_station_id=station_id,
        expected_caiso_node=caiso_node,
        expected_balancing_authority=balancing_authority,
        expected_timezone=target_timezone,
        expected_anchor_date=anchor_str,
        phase_mapping_by_date=combined_phase_map,
    )

    benchmarks_dir = data_dir / "benchmarks"
    manifests_dir = data_dir / "manifests"
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    # 1. Prepare and validate control updates before writing to disk
    ctrl_audit_path = data_dir / "manifests/control_matching_audit.json"
    if not ctrl_audit_path.exists():
        raise FileNotFoundError(
            f"Required provenance manifest '{ctrl_audit_path}' not found prior to benchmark finalization"
        )

    try:
        with ctrl_audit_path.open("r", encoding="utf-8") as f:
            c_audit = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in '{ctrl_audit_path}': {e}") from e

    if not isinstance(c_audit, dict):
        raise TypeError(f"'{ctrl_audit_path}' must parse as a JSON object, got {type(c_audit).__name__}")

    if "output_files" not in c_audit or not isinstance(c_audit["output_files"], dict):
        raise ValueError(f"'{ctrl_audit_path}' missing required 'output_files' dictionary")

    for req_out in ["control_catalogue_parquet", "control_catalogue_csv"]:
        if req_out not in c_audit["output_files"] or not isinstance(c_audit["output_files"][req_out], dict):
            raise ValueError(f"'{ctrl_audit_path}' missing required output entry '{req_out}'")

    sel_ctrl_id = str(c_audit.get("selected_control_id"))
    match_ev_id = str(c_audit.get("matched_event_id"))
    exp_ctrl_id = str(ctrl_row["control_id"])
    exp_ev_id = str(ev_row["event_id"])
    if sel_ctrl_id != exp_ctrl_id:
        raise ValueError(
            f"'{ctrl_audit_path}' selected_control_id '{sel_ctrl_id}' does not match benchmark control ID '{exp_ctrl_id}'"
        )
    if match_ev_id != exp_ev_id:
        raise ValueError(
            f"'{ctrl_audit_path}' matched_event_id '{match_ev_id}' does not match benchmark event ID '{exp_ev_id}'"
        )

    # 2. Prepare atomic outputs in temporary files
    parquet_path = benchmarks_dir / "benchmark_2024_event_control_v0.parquet"
    csv_sample_path = benchmarks_dir / "benchmark_2024_event_control_v0_sample.csv"
    manifest_path = manifests_dir / "benchmark_manifest.json"

    tmp_parquet = benchmarks_dir / ".tmp_benchmark_2024_event_control_v0.parquet"
    tmp_csv = benchmarks_dir / ".tmp_benchmark_2024_event_control_v0_sample.csv"
    tmp_manifest = manifests_dir / ".tmp_benchmark_manifest.json"

    df_benchmark.to_parquet(tmp_parquet, index=False)
    sample_df = pd.concat([df_benchmark.head(20), df_benchmark.tail(20)]).drop_duplicates().reset_index(drop=True)
    sample_df.to_csv(tmp_csv, index=False)

    ctrl_parquet_path = data_dir / "events/control_catalogue_v0.parquet"
    ctrl_csv_path = data_dir / "events/control_catalogue_v0.csv"
    tmp_ctrl_parquet = data_dir / "events/.tmp_control_catalogue_v0.parquet"
    tmp_ctrl_csv = data_dir / "events/.tmp_control_catalogue_v0.csv"
    tmp_ctrl_audit = data_dir / "manifests/.tmp_control_matching_audit.json"

    df_control_updated = df_control.copy()
    df_control_updated["source_coverage_status"] = "verified_complete"
    df_control_updated.to_parquet(tmp_ctrl_parquet, index=False)
    df_control_updated.to_csv(tmp_ctrl_csv, index=False)

    # Calculate hashes on temporary control outputs
    new_ctrl_parquet_sha = sha256_file(tmp_ctrl_parquet)
    new_ctrl_parquet_size = tmp_ctrl_parquet.stat().st_size
    new_ctrl_csv_sha = sha256_file(tmp_ctrl_csv)
    new_ctrl_csv_size = tmp_ctrl_csv.stat().st_size

    c_audit["output_files"]["control_catalogue_parquet"]["sha256"] = new_ctrl_parquet_sha
    c_audit["output_files"]["control_catalogue_parquet"]["size_bytes"] = new_ctrl_parquet_size
    c_audit["output_files"]["control_catalogue_csv"]["sha256"] = new_ctrl_csv_sha
    c_audit["output_files"]["control_catalogue_csv"]["size_bytes"] = new_ctrl_csv_size
    c_audit["final_cross_source_coverage_status"] = "verified_complete"

    with tmp_ctrl_audit.open("w", encoding="utf-8") as f:
        json.dump(c_audit, f, indent=2, sort_keys=True)

    # Collect project-relative input files lineage
    repo_root = data_dir.parent
    def _rel(p: Path) -> str:
        return str(p.relative_to(repo_root)) if p.is_relative_to(repo_root) else str(p)

    raw_inputs: dict[str, dict[str, Any]] = {}
    candidate_raw = [
        data_dir / f"raw/noaa/GHCNh_{station_id}_2024.psv",
        data_dir / f"raw/caiso/caiso_dam_lmp_{caiso_node}_20240605_20240610.zip",
        data_dir / f"raw/caiso/caiso_dam_lmp_{caiso_node}_20240701_20240706.zip",
        data_dir / f"raw/eia/eia930_region_{balancing_authority}_20240605.json",
        data_dir / f"raw/eia/eia930_region_{balancing_authority}_20240701.json",
        data_dir / f"raw/eia/{balancing_authority}.xlsx",
    ]
    for rf in candidate_raw:
        if rf.exists():
            raw_inputs[rf.name] = {
                "path": _rel(rf),
                "sha256": sha256_file(rf),
                "size_bytes": rf.stat().st_size,
            }

    catalogue_inputs: dict[str, dict[str, Any]] = {}
    # Use tmp_ctrl_parquet hash for the manifest input entry since it replaces control_catalogue_v0.parquet
    for cf in [events_parquet, labels_parquet, workload_parquet]:
        if cf.exists():
            catalogue_inputs[cf.name] = {
                "path": _rel(cf),
                "sha256": sha256_file(cf),
                "size_bytes": cf.stat().st_size,
            }
    catalogue_inputs["control_catalogue_v0.parquet"] = {
        "path": _rel(ctrl_parquet_path),
        "sha256": new_ctrl_parquet_sha,
        "size_bytes": new_ctrl_parquet_size,
    }

    config_inputs: dict[str, dict[str, Any]] = {}
    for cname in ["sources.yaml", "study.yaml"]:
        cfg_p = config_dir / cname
        if cfg_p.exists():
            config_inputs[cname] = {
                "path": _rel(cfg_p),
                "sha256": sha256_file(cfg_p),
                "size_bytes": cfg_p.stat().st_size,
            }

    manifest = {
        "manifest_version": "1.0",
        "gate": "G3-a",
        "methodology_version": "1.0",
        "validator_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(df_benchmark),
        "event_rows": len(event_rows),
        "control_rows": len(control_rows),
        "event_window_id": str(ev_row["event_id"]),
        "control_window_id": str(ctrl_row["control_id"]),
        "event_interval_utc": [
            event_rows[0]["timestamp_utc"].isoformat(),
            (event_rows[-1]["timestamp_utc"] + timedelta(hours=1)).isoformat(),
        ],
        "control_interval_utc": [
            control_rows[0]["timestamp_utc"].isoformat(),
            (control_rows[-1]["timestamp_utc"] + timedelta(hours=1)).isoformat(),
        ],
        "source_summary": {
            "noaa_station": station_id,
            "caiso_node": caiso_node,
            "eia_balancing_authority": balancing_authority,
            "timezone": target_timezone,
            "canonical_timezone": "UTC",
        },
        "coverage_metrics": {
            "temperature_covered": int((~df_benchmark["temperature_missing"]).sum()),
            "price_covered": int((~df_benchmark["price_missing"]).sum()),
            "demand_covered": int((~df_benchmark["demand_missing"]).sum()),
            "net_generation_covered": int((~df_benchmark["net_generation_missing"]).sum()),
            "carbon_covered": int((~df_benchmark["carbon_missing"]).sum()),
            "carbon_data_issue_count": int(df_benchmark["carbon_data_issue"].sum()),
            "carbon_primary_analysis_eligible_count": int(df_benchmark["carbon_primary_analysis_eligible"].sum()),
        },
        "input_files": {
            "raw_sources": raw_inputs,
            "catalogues_and_workloads": catalogue_inputs,
            "configuration": config_inputs,
        },
        "output_files": {
            "benchmark_parquet": {
                "path": _rel(parquet_path),
                "sha256": sha256_file(tmp_parquet),
                "size_bytes": tmp_parquet.stat().st_size,
            },
            "benchmark_sample_csv": {
                "path": _rel(csv_sample_path),
                "sha256": sha256_file(tmp_csv),
                "size_bytes": tmp_csv.stat().st_size,
            },
        },
    }

    with tmp_manifest.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    # 3. Atomically replace final destinations
    tmp_ctrl_parquet.replace(ctrl_parquet_path)
    tmp_ctrl_csv.replace(ctrl_csv_path)
    tmp_ctrl_audit.replace(ctrl_audit_path)
    tmp_parquet.replace(parquet_path)
    tmp_csv.replace(csv_sample_path)
    tmp_manifest.replace(manifest_path)

    # 4. Reload and verify written files
    with ctrl_audit_path.open("r", encoding="utf-8") as f:
        reloaded_c_audit = json.load(f)
    if reloaded_c_audit.get("final_cross_source_coverage_status") != "verified_complete":
        raise ValueError(
            f"Verification failed: '{ctrl_audit_path}' final_cross_source_coverage_status is not 'verified_complete'"
        )
    if reloaded_c_audit["output_files"]["control_catalogue_parquet"]["sha256"] != sha256_file(ctrl_parquet_path):
        raise ValueError(f"Verification failed: hash mismatch on written '{ctrl_parquet_path}'")
    if reloaded_c_audit["output_files"]["control_catalogue_csv"]["sha256"] != sha256_file(ctrl_csv_path):
        raise ValueError(f"Verification failed: hash mismatch on written '{ctrl_csv_path}'")

    return {
        "df_benchmark": df_benchmark,
        "parquet_path": parquet_path,
        "csv_sample_path": csv_sample_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def validate_benchmark_dataframe(
    df: pd.DataFrame,
    *,
    expected_event_id: str | None = None,
    expected_control_id: str | None = None,
    expected_station_id: str | None = None,
    expected_caiso_node: str | None = None,
    expected_balancing_authority: str | None = None,
    expected_timezone: str = "America/Los_Angeles",
    expected_anchor_date: str | None = None,
    phase_mapping_by_date: dict[str, str] | None = None,
) -> None:
    """Validate the 240-row benchmark DataFrame according to G3-a specifications."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    actual_cols = list(df.columns)
    if actual_cols != BENCHMARK_COLUMNS:
        raise ValueError(
            f"Benchmark columns mismatch.\nExpected: {BENCHMARK_COLUMNS}\nActual:   {actual_cols}"
        )

    if len(df) != 240:
        raise ValueError(f"Benchmark row count {len(df)} != 240")

    # A. Window types and IDs
    unique_types = set(df["window_type"].unique())
    if not unique_types.issubset(VALID_WINDOW_TYPES) or unique_types != VALID_WINDOW_TYPES:
        raise ValueError(f"Benchmark window_types must be exactly {VALID_WINDOW_TYPES}, got {unique_types}")

    ev_df = df[df["window_type"] == "event"]
    ctrl_df = df[df["window_type"] == "control"]

    if len(ev_df) != 120:
        raise ValueError(f"Event window rows {len(ev_df)} != 120")
    if len(ctrl_df) != 120:
        raise ValueError(f"Control window rows {len(ctrl_df)} != 120")

    ev_window_ids = set(ev_df["window_id"].unique())
    if len(ev_window_ids) != 1:
        raise ValueError(f"Event window must contain exactly 1 unique window_id, got {ev_window_ids}")
    actual_ev_id = list(ev_window_ids)[0]
    if expected_event_id is not None and actual_ev_id != expected_event_id:
        raise ValueError(f"Event window_id '{actual_ev_id}' != expected '{expected_event_id}'")

    ctrl_window_ids = set(ctrl_df["window_id"].unique())
    if len(ctrl_window_ids) != 1:
        raise ValueError(f"Control window must contain exactly 1 unique window_id, got {ctrl_window_ids}")
    actual_ctrl_id = list(ctrl_window_ids)[0]
    if expected_control_id is not None and actual_ctrl_id != expected_control_id:
        raise ValueError(f"Control window_id '{actual_ctrl_id}' != expected '{expected_control_id}'")

    # B. Phase labels validation
    ev_phases = set(ev_df["phase_label"].unique())
    if not ev_phases.issubset(VALID_EVENT_PHASES):
        invalid_phases = ev_phases - VALID_EVENT_PHASES
        raise ValueError(f"Event rows contain invalid phase_label(s): {invalid_phases}")

    ctrl_phases = set(ctrl_df["phase_label"].unique())
    if not ctrl_phases.issubset(VALID_CONTROL_PHASES):
        invalid_c_phases = ctrl_phases - VALID_CONTROL_PHASES
        raise ValueError(f"Control rows contain invalid phase_label(s): {invalid_c_phases}")

    # Exactly one control-anchor local day
    anchor_rows = ctrl_df[ctrl_df["phase_label"] == "control_anchor"]
    if anchor_rows.empty:
        raise ValueError("Control window must contain control_anchor phase rows")
    anchor_dates = anchor_rows["local_date"].unique().tolist()
    if len(anchor_dates) != 1:
        raise ValueError(f"Control window must contain exactly 1 control-anchor date, got {anchor_dates}")
    actual_anchor_d = anchor_dates[0]
    if len(anchor_rows) != 24:
        raise ValueError(f"Control anchor must cover full 24 hours of {actual_anchor_d}, got {len(anchor_rows)} rows")
    if expected_anchor_date is not None and actual_anchor_d != expected_anchor_date:
        raise ValueError(f"Control anchor date '{actual_anchor_d}' != expected '{expected_anchor_date}'")

    # Check timestamps: monotonic within each window, top-of-hour, UTC-aware
    tz_la = ZoneInfo(expected_timezone)

    for name, sub_df in [("event", ev_df), ("control", ctrl_df)]:
        ts_list = sub_df["timestamp_utc"].tolist()
        if ts_list != sorted(ts_list):
            raise ValueError(f"{name} window timestamps are not sorted monotonic ascending")
        if sub_df["timestamp_utc"].duplicated().any():
            raise ValueError(f"{name} window contains duplicate timestamps")

        # Verify continuous 120-hour hourly sequence
        for i in range(1, len(ts_list)):
            step_hours = (ts_list[i] - ts_list[i - 1]).total_seconds() / 3600.0
            if step_hours != 1.0:
                raise ValueError(
                    f"{name} window contains non-continuous step: {ts_list[i-1]} to {ts_list[i]} ({step_hours}h)"
                )

        for idx, row in sub_df.iterrows():
            ts = row["timestamp_utc"]
            if not isinstance(ts, (datetime, pd.Timestamp)) or ts.tzinfo is None:
                raise ValueError(f"Row {idx}: timestamp_utc must be timezone-aware UTC datetime")
            if ts.utcoffset() != timedelta(0):
                raise ValueError(f"Row {idx}: timestamp_utc must have UTC offset 0, got {ts.utcoffset()}")
            if ts.minute != 0 or ts.second != 0:
                raise ValueError(f"Row {idx}: timestamp_utc {ts} is not top-of-hour")

            # Validate local timestamps consistency with configured timezone
            expected_dt_la = ts.astimezone(tz_la)
            expected_local_ts = expected_dt_la.strftime("%Y-%m-%dT%H:%M:%S")
            expected_local_d = expected_dt_la.strftime("%Y-%m-%d")
            expected_local_h = expected_dt_la.hour

            if row["local_timestamp"] != expected_local_ts:
                raise ValueError(
                    f"Row {idx} ({name}): local_timestamp '{row['local_timestamp']}' != expected '{expected_local_ts}'"
                )
            if row["local_date"] != expected_local_d:
                raise ValueError(
                    f"Row {idx} ({name}): local_date '{row['local_date']}' != expected '{expected_local_d}'"
                )
            if int(row["hour_local"]) != expected_local_h:
                raise ValueError(
                    f"Row {idx} ({name}): hour_local {row['hour_local']} != expected {expected_local_h}"
                )

            # Phase mapping agreement if passed
            if phase_mapping_by_date is not None and expected_local_d in phase_mapping_by_date:
                expected_p = phase_mapping_by_date[expected_local_d]
                if row["phase_label"] != expected_p:
                    raise ValueError(
                        f"Row {idx} ({name}): phase_label '{row['phase_label']}' != expected '{expected_p}' for date {expected_local_d}"
                    )

            # F. Source metadata validation
            if expected_station_id is not None and row["source_station_id"] != expected_station_id:
                raise ValueError(f"Row {idx}: unexpected source_station_id '{row['source_station_id']}' != '{expected_station_id}'")
            if expected_caiso_node is not None and row["source_caiso_node"] != expected_caiso_node:
                raise ValueError(f"Row {idx}: unexpected source_caiso_node '{row['source_caiso_node']}' != '{expected_caiso_node}'")
            if expected_balancing_authority is not None and row["source_balancing_authority"] != expected_balancing_authority:
                raise ValueError(f"Row {idx}: unexpected source_balancing_authority '{row['source_balancing_authority']}' != '{expected_balancing_authority}'")

            # C. NOAA observation counts
            temp_obs = row["temperature_obs_count"]
            if not isinstance(temp_obs, (int, pd.Int64Dtype, type(pd.Series([1]).iloc[0]))) or temp_obs <= 0:
                raise ValueError(f"Row {idx} ({name}): temperature_obs_count must be a positive integer, got {temp_obs}")

            # E. Measurement and missingness consistency
            for col_val, col_missing, col_name in [
                (row["temperature_c"], row["temperature_missing"], "temperature"),
                (row["price_usd_per_mwh"], row["price_missing"], "price"),
                (row["demand_mw"], row["demand_missing"], "demand"),
                (row["net_generation_mw"], row["net_generation_missing"], "net_generation"),
                (row["carbon_g_per_kwh"], row["carbon_missing"], "carbon_intensity"),
            ]:
                if not isinstance(col_missing, (bool, pd.BooleanDtype)) and col_missing not in (True, False):
                    raise ValueError(f"Row {idx} ({name}): {col_name}_missing must be boolean, got {col_missing}")
                if col_missing is not False:
                    raise ValueError(f"Row {idx} ({name}): {col_name}_missing must be False for covered benchmark row")
                if pd.isna(col_val) or col_val is None:
                    raise ValueError(f"Row {idx} ({name}): missing {col_name} observation (None/NaN)")
                if not math.isfinite(float(col_val)):
                    raise ValueError(f"Row {idx} ({name}): non-finite {col_name} observation ({col_val})")

            # Logical consistency check for carbon flags
            has_issue = bool(row["carbon_data_issue"])
            is_eligible = bool(row["carbon_primary_analysis_eligible"])
            if has_issue and is_eligible:
                raise ValueError(
                    f"Row {idx} ({name}): logical contradiction: carbon_data_issue is True but carbon_primary_analysis_eligible is True"
                )

            # D. Source quality consistency
            sq = str(row["source_quality"])
            if sq not in VALID_SOURCE_QUALITIES or sq == "missing":
                raise ValueError(f"Row {idx} ({name}): invalid source_quality '{sq}'")
            if has_issue and sq != "success_with_data_issues":
                raise ValueError(
                    f"Row {idx} ({name}): source_quality must be 'success_with_data_issues' when carbon_data_issue=True, got '{sq}'"
                )
            if not has_issue and sq != "success":
                raise ValueError(
                    f"Row {idx} ({name}): source_quality must be 'success' when carbon_data_issue=False, got '{sq}'"
                )


def inspect_benchmark_dataset(parquet_path: Path | str) -> None:
    """Print human-readable summary of the 240-row benchmark table."""
    p = Path(parquet_path)
    if not p.is_file():
        raise FileNotFoundError(f"Benchmark file not found: {p}")

    df = pd.read_parquet(p)
    validate_benchmark_dataframe(df)

    print("\n=================== HeatTrace G3-a Aligned 2024 Benchmark ===================")
    print(f"File:                      {p}")
    print(f"Total Rows:                {len(df)} (120 event + 120 control)")
    print(f"Columns:                   {len(df.columns)}")
    print(f"Event Window:              HW_20240702 (2024-07-01 to 2024-07-05 local)")
    print(f"Control Window:            CTRL_20240605 (2024-06-05 to 2024-06-09 local)")
    print(f"Mean Event Temp:           {df[df['window_type'] == 'event']['temperature_c'].mean():.2f}°C")
    print(f"Mean Control Temp:         {df[df['window_type'] == 'control']['temperature_c'].mean():.2f}°C")
    print(f"Mean Event Price:          ${df[df['window_type'] == 'event']['price_usd_per_mwh'].mean():.2f}/MWh")
    print(f"Mean Control Price:        ${df[df['window_type'] == 'control']['price_usd_per_mwh'].mean():.2f}/MWh")
    print(f"Mean Event Carbon:         {df[df['window_type'] == 'event']['carbon_g_per_kwh'].mean():.2f} g/kWh")
    print(f"Mean Control Carbon:       {df[df['window_type'] == 'control']['carbon_g_per_kwh'].mean():.2f} g/kWh")
    print("-----------------------------------------------------------------------------")
    print("Validation Status:         PASSED (Clean loader verified, complete coverage)")
    print("=============================================================================\n")
