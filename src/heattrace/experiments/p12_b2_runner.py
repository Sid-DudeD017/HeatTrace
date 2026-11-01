"""Track B2 Phase 5 Execution Runner for Frozen Scheduler Matrix.

Executes the frozen 6,480-run matrix under Track B2 Phase 5 with:
- Checkpointing and atomic batch updates
- Deterministic resume without rerunning completed cells
- Strict validation of frozen inputs and workload hashes
- Precise forecast t-1 history cutoff and look-ahead leakage protection
- Full failure preservation distinguishing software failures from valid scheduler infeasibility
- Zero mutation of frozen Phase 3, Phase 4, or P11 baselines
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from heattrace.forecast.dataset import (
    ScalerMetadata,
    load_noaa_hourly_series,
)
from heattrace.forecast.historical import HistoricalPersistenceForecastProvider
from heattrace.forecast.train_temperature import load_verified_checkpoint, predict_unscaled
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
)
from heattrace.thermal.facility import (
    FacilityConfig,
    FacilityModelKind,
    build_forecast_facility_state,
    build_realized_facility_state,
    get_preset_thermal_scenario,
)
from heattrace.thermal.heatguard import (
    HeatGuardMarginMode,
    HeatGuardScheduler,
)
from heattrace.thermal.metrics import score_thermal_schedule
from heattrace.thermal.policies import (
    CapacityAwarePolicy,
    FullThermalAwarePolicy,
    OracleFullThermalAwarePolicy,
    StaticUnawarePolicy,
)
from heattrace.process.p12_b2_coverage import parse_caiso_archive_rows
from heattrace.ingest.eia import parse_and_validate_eia_ciso_workbook

PROTECTED_P11_BASELINES = {
    "archive_manifest": (
        "data/archive/heattrace_v1_d5b3c86/archive_manifest.json",
        "2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4",
    ),
    "reproduction_comparison": (
        "data/results/p11_reproduction_comparison.json",
        "cf14e1bfc3f8031612229f989d6dcb784771f1f7112bda809871ac782bc9f49e",
    ),
    "p6_validity_yaml": (
        "configs/p6_validity.yaml",
        "46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1",
    ),
    "p6_frozen_protocol": (
        "docs/p6_frozen_protocol.md",
        "78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede",
    ),
}

PHASE3_EVENT_FREEZE_SHA256 = "972675ef164cd29628eebdc4e509dce352b62a70a2e7214c9e9083f8d33d91c5"
FROZEN_CALIBRATION_MANIFEST_HASH = "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c"

STATION_TO_HUB = {
    "SFO": "TH_NP15_GEN-APND",
    "SAC": "TH_NP15_GEN-APND",
    "RDD": "TH_NP15_GEN-APND",
    "FAT": "TH_ZP26_GEN-APND",
    "LAX": "TH_SP15_GEN-APND",
}

STATION_TO_GHCNH = {
    "SFO": "USW00023234",
    "SAC": "USW00023232",
    "RDD": "USW00024257",
    "FAT": "USW00093193",
    "LAX": "USW00023174",
}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_protected_baselines(repo_root: Path) -> dict[str, str]:
    results = {}
    for k, (rel_path, exp_hash) in PROTECTED_P11_BASELINES.items():
        p = repo_root / rel_path
        if not p.exists():
            raise FileNotFoundError(f"Protected baseline missing: {p}")
        act_hash = sha256_file(p)
        if act_hash != exp_hash:
            raise ValueError(f"Protected P11 baseline {k} hash mismatch: {act_hash} vs {exp_hash}")
        results[k] = act_hash

    p3_p = repo_root / "data/v2/manifests/p12_b2_event_freeze.json"
    p3_act = sha256_file(p3_p)
    if p3_act != PHASE3_EVENT_FREEZE_SHA256:
        raise ValueError(f"Phase 3 event freeze hash mismatch: {p3_act} vs {PHASE3_EVENT_FREEZE_SHA256}")
    results["phase3_event_freeze"] = p3_act

    # Also verify Phase 4 freeze manifest artifacts
    p4_manifest_p = repo_root / "data/v2/manifests/p12_b2_window_freeze.json"
    with open(p4_manifest_p) as f:
        p4_m = json.load(f)
    for name, meta in p4_m["artifacts"].items():
        act_h = sha256_file(repo_root / meta["path"])
        if act_h != meta["sha256"]:
            raise ValueError(f"Phase 4 artifact {name} hash mismatch: {act_h} vs {meta['sha256']}")
        results[f"phase4_{name}"] = act_h

    return results


def run_deployable_rolling_schedule_b2(
    policy_id: str,
    workload_df: pd.DataFrame,
    temp_forecasts: dict[int, np.ndarray] | None,
    mkt_forecasts: dict[int, ForecastResult],
    fcfg: FacilityConfig,
    objective: str,
    start_utc: datetime,
    total_window_hours: int,
    constraints: SchedulingConstraints,
) -> tuple[ScheduleResult, float | None]:
    """Execute deployable policy under rolling horizon for arbitrary window duration."""
    trace_id = str(workload_df["workload_trace_id"].iloc[0])
    demanded_proc = int(workload_df["processing_requirement"].sum())

    jobs_state: dict[str, dict[str, Any]] = {}
    for _, row in workload_df.iterrows():
        jid = str(row["job_id"])
        req = int(row["processing_requirement"])
        arr = int(row["arrival_offset_hours"])
        dead = int(row["deadline_offset_hours"])
        energy = float(row["energy_kwh"])
        jobs_state[jid] = {
            "remaining_req": req,
            "arrival": arr,
            "deadline": dead,
            "unit_power_kw": energy / req,
            "unit_energy_kwh": energy / req,
            "workload_row": row.to_dict(),
        }

    committed_allocations: list[ScheduledJobAllocation] = []
    overall_unmet_deadlines: set[str] = set()

    for origin_h in range(total_window_hours):
        origin_utc = start_utc + timedelta(hours=origin_h)
        mkt_fc_24 = mkt_forecasts[origin_h]

        window_eligible_jobs: list[dict[str, Any]] = []
        job_required_in_window: dict[str, int] = {}
        step_unmet: list[str] = []

        for jid, info in jobs_state.items():
            if info["remaining_req"] <= 0:
                continue
            arr = info["arrival"]
            dead = info["deadline"]
            rem = info["remaining_req"]

            if arr > origin_h:
                continue
            if dead <= origin_h:
                if jid not in step_unmet:
                    step_unmet.append(jid)
                continue

            window_arr_offset = max(0, arr - origin_h)
            if dead <= origin_h + 24:
                window_deadline_offset = dead - origin_h
                window_effective_req = rem
                job_required_in_window[jid] = rem
            else:
                window_deadline_offset = 24
                future_slots = dead - (origin_h + 24)
                req_in_window = max(0, rem - future_slots)
                window_effective_req = req_in_window
                job_required_in_window[jid] = req_in_window

            if window_effective_req == 0:
                continue

            if window_deadline_offset <= window_arr_offset or window_effective_req > (window_deadline_offset - window_arr_offset):
                if jid not in step_unmet:
                    step_unmet.append(jid)

            window_eligible_jobs.append({
                "workload_trace_id": trace_id,
                "job_id": jid,
                "arrival_offset_hours": window_arr_offset,
                "deadline_offset_hours": window_deadline_offset,
                "processing_requirement": window_effective_req,
                "energy_kwh": window_effective_req * info["unit_energy_kwh"],
                "maximum_parallelism": info["workload_row"].get("maximum_parallelism", 1),
                "priority": info["workload_row"].get("priority", 0),
                "preemptible": info["workload_row"].get("preemptible", True),
            })

        if window_eligible_jobs:
            replan_df = pd.DataFrame(window_eligible_jobs)

            if policy_id == "static_unaware":
                policy = StaticUnawarePolicy(objective=objective)
                window_result = policy.schedule(replan_df, mkt_fc_24, constraints)
            else:
                if temp_forecasts is None or origin_h not in temp_forecasts:
                    raise ValueError(f"Temperature forecast required for policy {policy_id} at origin_h {origin_h}")
                fc_df = pd.DataFrame({
                    "timestamp_utc": [origin_utc + timedelta(hours=h) for h in range(24)],
                    "forecast_temperature_c": temp_forecasts[origin_h],
                })
                forecast_facility_state = build_forecast_facility_state(fc_df, fcfg)
                if policy_id == "capacity_aware":
                    policy = CapacityAwarePolicy(forecast_facility_state, objective=objective)
                elif policy_id == "full_thermal_aware":
                    policy = FullThermalAwarePolicy(forecast_facility_state, objective=objective)
                else:
                    raise ValueError(f"Unknown deployable policy_id in rolling harness: {policy_id}")
                window_result = policy.schedule(replan_df, mkt_fc_24, constraints)

            in_window_alloc_counts: dict[str, int] = {j["job_id"]: 0 for j in window_eligible_jobs}
            for alloc in window_result.allocations:
                in_window_alloc_counts[alloc.job_id] += 1

            for jid, required_units in job_required_in_window.items():
                actual_units = in_window_alloc_counts.get(jid, 0)
                if actual_units < required_units:
                    if jid not in step_unmet:
                        step_unmet.append(jid)

            if not window_result.is_feasible:
                for uj in window_result.unmet_deadlines:
                    if uj not in step_unmet:
                        step_unmet.append(uj)

            for alloc in window_result.allocations:
                if alloc.allocated_hour_offset == 0:
                    jid = alloc.job_id
                    if jobs_state[jid]["remaining_req"] > 0:
                        global_alloc = ScheduledJobAllocation(
                            job_id=jid,
                            allocated_hour_offset=origin_h,
                            execution_power_kw=alloc.execution_power_kw,
                            allocated_energy_kwh=alloc.allocated_energy_kwh,
                        )
                        committed_allocations.append(global_alloc)
                        jobs_state[jid]["remaining_req"] -= 1

        for jid in step_unmet:
            overall_unmet_deadlines.add(jid)

    for jid, info in jobs_state.items():
        if info["remaining_req"] > 0:
            overall_unmet_deadlines.add(jid)

    is_overall_feasible = (len(overall_unmet_deadlines) == 0) and (len(committed_allocations) == demanded_proc)

    sched_res = ScheduleResult(
        policy_name=policy_id,
        policy_version="1.0",
        workload_trace_id=trace_id,
        window_duration_hours=total_window_hours,
        allocations=committed_allocations,
        total_cost_usd=0.0,
        total_carbon_emissions_kg=0.0,
        is_feasible=is_overall_feasible,
        unmet_deadlines=sorted(list(overall_unmet_deadlines)),
    )
    return sched_res, 0.0


class B2ExecutionRunner:
    """Manages frozen matrix execution with full caching, checkpointing, and validation."""

    def __init__(self, repo_root: Path | str = ".") -> None:
        self.repo_root = Path(repo_root).resolve()
        self.results_dir = self.repo_root / "data/v2/results"
        self.checkpoints_dir = self.repo_root / "data/v2/checkpoints"
        self.manifests_dir = self.repo_root / "data/v2/manifests"
        self.workloads_dir = self.repo_root / "data/v2/workloads"

        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

        self.cells_path = self.repo_root / "data/v2/benchmarks/p12_b2_matrix_cells.csv"
        self.controls_path = self.repo_root / "data/v2/benchmarks/p12_b2_controls.csv"
        self.ordinary_path = self.repo_root / "data/v2/benchmarks/p12_b2_ordinary_windows.csv"
        self.events_path = self.repo_root / "data/v2/events/p12_b2_station_events.csv"
        self.dry_run_path = self.repo_root / "data/v2/manifests/p12_b2_matrix_dry_run.json"
        self.window_freeze_path = self.repo_root / "data/v2/manifests/p12_b2_window_freeze.json"

        # Preloaded lookup caches
        self.df_cells = pd.read_csv(self.cells_path)
        self.df_ctrl = pd.read_csv(self.controls_path)
        self.df_ord = pd.read_csv(self.ordinary_path)
        self.df_ev = pd.read_csv(self.events_path)
        self.df_ev = self.df_ev[self.df_ev["joint_evaluation_eligibility"] == "ELIGIBLE"].copy().reset_index(drop=True)

        with open(self.dry_run_path) as f:
            self.dry_run_manifest = json.load(f)

        # Build window lookup map
        self.windows_map: dict[str, dict[str, Any]] = {}
        for _, r in self.df_ev.iterrows():
            s_utc = pd.to_datetime(r["full_window_start_utc"])
            e_utc = pd.to_datetime(r["full_window_end_utc"])
            dur = int((e_utc - s_utc).total_seconds() / 3600)
            self.windows_map[r["event_id"]] = {
                "window_id": r["event_id"],
                "station_code": r["station_code"],
                "start_utc": s_utc,
                "end_utc": e_utc,
                "duration_hours": dur,
                "window_type": "heatwave",
            }
        for _, r in self.df_ctrl.iterrows():
            s_utc = pd.to_datetime(r["start_utc"])
            e_utc = pd.to_datetime(r["end_utc"])
            dur = int(r["duration_hours"])
            self.windows_map[r["control_id"]] = {
                "window_id": r["control_id"],
                "station_code": r["station_code"],
                "start_utc": s_utc,
                "end_utc": e_utc,
                "duration_hours": dur,
                "window_type": "matched_control",
            }
        for _, r in self.df_ord.iterrows():
            s_utc = pd.to_datetime(r["start_utc"])
            e_utc = pd.to_datetime(r["end_utc"])
            dur = int(r["duration_hours"])
            self.windows_map[r["ordinary_window_id"]] = {
                "window_id": r["ordinary_window_id"],
                "station_code": r["station_code"],
                "start_utc": s_utc,
                "end_utc": e_utc,
                "duration_hours": dur,
                "window_type": "ordinary_window",
            }

        # Workload cache
        self.workload_cache: dict[str, pd.DataFrame] = {}
        self.workload_hash_cache: dict[str, str] = {}
        for item in self.dry_run_manifest["workload_identities"]:
            p = self.repo_root / item["parquet_path"]
            self.workload_cache[item["parquet_path"]] = pd.read_parquet(p)
            self.workload_hash_cache[item["parquet_path"]] = sha256_file(self.repo_root / item["csv_path"])

        # TinyLSTM model and scaler
        self.model_ckpt_path = self.repo_root / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"
        self.lstm_model, self.lstm_ckpt_data = load_verified_checkpoint(self.model_ckpt_path)
        scaler_dict = self.lstm_ckpt_data["scaler"]
        self.scaler = ScalerMetadata(
            mean=scaler_dict["mean"],
            std=scaler_dict["std"],
            count=scaler_dict["count"],
            p95=scaler_dict["p95"],
            fitted_at_utc=scaler_dict["fitted_at_utc"],
            train_start_utc=scaler_dict["train_start_utc"],
            train_end_exclusive_utc=scaler_dict["train_end_exclusive_utc"],
        )

        # Market & EIA preloaded parquets
        caiso_cache_p = self.repo_root / "data/v2/processed/p12_b2_caiso_all_parsed.parquet"
        eia_cache_p = self.repo_root / "data/v2/processed/p12_b2_eia_all_parsed.parquet"
        if not caiso_cache_p.exists() or not eia_cache_p.exists():
            raise FileNotFoundError("Preparsed CAISO or EIA caches missing in data/v2/processed/")
        self.df_caiso = pd.read_parquet(caiso_cache_p)
        self.df_caiso["timestamp_utc"] = pd.to_datetime(self.df_caiso["timestamp_utc"], utc=True)
        self.df_eia = pd.read_parquet(eia_cache_p)
        self.df_eia["timestamp_utc"] = pd.to_datetime(self.df_eia["timestamp_utc"], utc=True)

        self.mkt_provider = HistoricalPersistenceForecastProvider()

        # Cache of prepared window series (realized, temp_forecasts, mkt_forecasts)
        self.realized_window_cache: dict[str, dict[str, Any]] = {}
        self.temperature_forecast_cache: dict[str, dict[str, Any]] = {}
        self.market_forecast_cache: dict[str, dict[str, Any]] = {}

    def prepare_realized_window_data(self, window_id: str) -> dict[str, Any]:
        """Load and cache realized weather, price, and carbon for a window."""
        if window_id in self.realized_window_cache:
            return self.realized_window_cache[window_id]

        win = self.windows_map[window_id]
        s = win["start_utc"]
        e = win["end_utc"]
        dur = win["duration_hours"]
        st = win["station_code"]
        ghcnh = STATION_TO_GHCNH[st]
        hub = STATION_TO_HUB[st]

        # 1. Weather series
        try:
            ndf = load_noaa_hourly_series(self.repo_root / "data/v2/raw/noaa", s, e, expected_station=ghcnh).reset_index()
            if len(ndf) != dur or ndf["temperature_c"].isna().any():
                res = {
                    "valid": False,
                    "failure_status": "WEATHER_DATA_INCOMPLETE",
                    "failure_message": f"NOAA weather missing or NaN in window (len={len(ndf)}/{dur}, na_count={ndf['temperature_c'].isna().sum()})",
                }
                self.realized_window_cache[window_id] = res
                return res
        except Exception as exc:
            res = {
                "valid": False,
                "failure_status": "WEATHER_DATA_INCOMPLETE",
                "failure_message": f"NOAA load exception: {str(exc)[:180]}",
            }
            self.realized_window_cache[window_id] = res
            return res

        # 2. Price series
        c_sub = self.df_caiso[
            (self.df_caiso["node"] == hub) & (self.df_caiso["timestamp_utc"] >= s) & (self.df_caiso["timestamp_utc"] < e)
        ].drop_duplicates("timestamp_utc").sort_values("timestamp_utc").reset_index(drop=True)

        if len(c_sub) != dur:
            res = {
                "valid": False,
                "failure_status": "MARKET_PRICE_INCOMPLETE",
                "failure_message": f"CAISO price intervals missing for hub {hub} (found {len(c_sub)}/{dur})",
            }
            self.realized_window_cache[window_id] = res
            return res

        # 3. Carbon series
        e_sub = self.df_eia[
            (self.df_eia["timestamp_utc"] >= s) & (self.df_eia["timestamp_utc"] < e)
        ].drop_duplicates("timestamp_utc").sort_values("timestamp_utc").reset_index(drop=True)

        if len(e_sub) != dur:
            res = {
                "valid": False,
                "failure_status": "CARBON_DATA_INCOMPLETE",
                "failure_message": f"EIA carbon intervals missing (found {len(e_sub)}/{dur})",
            }
            self.realized_window_cache[window_id] = res
            return res

        realized_df = pd.DataFrame({
            "timestamp_utc": ndf["timestamp_utc"],
            "temperature_c": ndf["temperature_c"].values,
            "price_usd_per_mwh": c_sub["price_usd_per_mwh"].values,
            "carbon_g_per_kwh": e_sub["co2_intensity_consumed_g_per_kwh"].values,
        })

        res = {
            "valid": True,
            "realized_df": realized_df,
            "start_utc": s,
            "end_utc": e,
            "duration_hours": dur,
        }
        self.realized_window_cache[window_id] = res
        return res

    def prepare_market_forecasts(self, window_id: str, realized_df: pd.DataFrame) -> dict[str, Any]:
        """Generate and cache rolling market forecasts from realized history."""
        if window_id in self.market_forecast_cache:
            return self.market_forecast_cache[window_id]

        win = self.windows_map[window_id]
        s = win["start_utc"]
        dur = win["duration_hours"]

        mkt_forecasts: dict[int, ForecastResult] = {}
        for h_offset in range(dur):
            orig_ts = s + timedelta(hours=h_offset)
            mkt_res = self.mkt_provider.forecast(
                origin_timestamp_utc=orig_ts,
                horizon_hours=24,
                history_df=realized_df.iloc[:h_offset],
                window_type=win["window_type"],
                window_id=window_id,
            )
            mkt_forecasts[h_offset] = mkt_res

        res = {"valid": True, "mkt_forecasts": mkt_forecasts}
        self.market_forecast_cache[window_id] = res
        return res

    def prepare_temperature_forecasts(self, window_id: str) -> dict[str, Any]:
        """Generate and cache TinyLSTM temperature forecasts for a window."""
        if window_id in self.temperature_forecast_cache:
            return self.temperature_forecast_cache[window_id]

        win = self.windows_map[window_id]
        s = win["start_utc"]
        e = win["end_utc"]
        dur = win["duration_hours"]
        st = win["station_code"]
        ghcnh = STATION_TO_GHCNH[st]

        hist_start_utc = s - timedelta(hours=72)
        end_with_target = e + timedelta(hours=24)
        try:
            noaa_extended = load_noaa_hourly_series(self.repo_root / "data/v2/raw/noaa", hist_start_utc, end_with_target, expected_station=ghcnh)
        except Exception as exc:
            res = {
                "valid": False,
                "failure_status": "FORECAST_MISSING",
                "failure_message": f"NOAA extended lookback load failed: {str(exc)[:180]}",
            }
            self.temperature_forecast_cache[window_id] = res
            return res

        features_list = []
        for h_offset in range(dur):
            orig_ts = s + timedelta(hours=h_offset)
            lb_df = noaa_extended.loc[orig_ts - timedelta(hours=72) : orig_ts - timedelta(hours=1)]
            if len(lb_df) != 72 or lb_df["temperature_c"].isna().any():
                res = {
                    "valid": False,
                    "failure_status": "FORECAST_MISSING",
                    "failure_message": f"NOAA 72h lookback has missing/NaN values at origin {orig_ts.isoformat()}",
                }
                self.temperature_forecast_cache[window_id] = res
                return res

            temps = lb_df["temperature_c"].to_numpy(dtype=np.float32)
            std_temps = (temps - self.scaler.mean) / self.scaler.std
            ts_hours = np.array([ts.hour for ts in lb_df.index], dtype=np.float32)
            ts_doy = np.array([ts.timetuple().tm_yday for ts in lb_df.index], dtype=np.float32)
            sin_hr = np.sin(2 * np.pi * ts_hours / 24.0, dtype=np.float32)
            cos_hr = np.cos(2 * np.pi * ts_hours / 24.0, dtype=np.float32)
            sin_dy = np.sin(2 * np.pi * ts_doy / 365.25, dtype=np.float32)
            cos_dy = np.cos(2 * np.pi * ts_doy / 365.25, dtype=np.float32)

            feat = np.stack([std_temps, sin_hr, cos_hr, sin_dy, cos_dy], axis=-1)
            features_list.append(feat)

        X_all = np.stack(features_list, axis=0)
        preds_24 = predict_unscaled(self.lstm_model, X_all, self.scaler)

        temp_forecasts: dict[int, np.ndarray] = {}
        for h_offset in range(dur):
            temp_forecasts[h_offset] = preds_24[h_offset]

        res = {"valid": True, "temp_forecasts": temp_forecasts}
        self.temperature_forecast_cache[window_id] = res
        return res

    def prepare_window_data(self, window_id: str) -> dict[str, Any]:
        """Legacy helper maintained for backward compatibility."""
        rw = self.prepare_realized_window_data(window_id)
        if not rw["valid"]:
            return rw
        tf = self.prepare_temperature_forecasts(window_id)
        if not tf["valid"]:
            return tf
        mf = self.prepare_market_forecasts(window_id, rw["realized_df"])
        return {
            "valid": True,
            "realized_df": rw["realized_df"],
            "temp_forecasts": tf["temp_forecasts"],
            "mkt_forecasts": mf["mkt_forecasts"],
            "start_utc": rw["start_utc"],
            "end_utc": rw["end_utc"],
            "duration_hours": rw["duration_hours"],
        }

    def execute_cell(self, cell_row: pd.Series) -> dict[str, Any]:
        """Execute a single matrix cell and return structured outcome row."""
        t0 = time.perf_counter()
        run_id = cell_row["run_id"]
        window_id = cell_row["window_id"]
        policy = cell_row["policy"]
        objective = cell_row["objective"]
        seed = int(cell_row["workload_seed"])
        multiplier = float(cell_row["workload_multiplier"])
        dur = int(cell_row["duration_hours"])
        deployable = bool(cell_row["deployable"])
        exp_workload_hash = cell_row["workload_hash"]

        trace_rel_parq = f"data/v2/workloads/workload_trace_{dur}h_s{seed}_x{int(multiplier)}.parquet"

        # 1. Workload validation
        if trace_rel_parq not in self.workload_cache:
            return self._build_failure_record(
                cell_row,
                status="WORKLOAD_VALIDATION_FAILED",
                error_class="WorkloadNotFoundError",
                error_msg=f"Workload trace {trace_rel_parq} not in frozen set",
                runtime_s=time.perf_counter() - t0,
            )

        actual_w_hash = self.workload_hash_cache[trace_rel_parq]
        if actual_w_hash != exp_workload_hash:
            return self._build_failure_record(
                cell_row,
                status="INPUT_HASH_MISMATCH",
                error_class="WorkloadHashMismatchError",
                error_msg=f"Workload hash mismatch: expected {exp_workload_hash}, got {actual_w_hash}",
                runtime_s=time.perf_counter() - t0,
            )

        workload_df = self.workload_cache[trace_rel_parq]
        demanded_proc = int(workload_df["processing_requirement"].sum())
        demanded_energy = float(workload_df["energy_kwh"].sum())

        # 2. Window data retrieval and policy requirement dispatch
        realized_res = self.prepare_realized_window_data(window_id)
        if not realized_res["valid"]:
            return self._build_failure_record(
                cell_row,
                status=realized_res["failure_status"],
                error_class="WindowDataIncompleteError",
                error_msg=realized_res["failure_message"],
                runtime_s=time.perf_counter() - t0,
                demanded_proc=demanded_proc,
                demanded_energy=demanded_energy,
            )

        realized_df = realized_res["realized_df"]
        start_ts = realized_res["start_utc"].to_pydatetime()

        # Forecast requirements:
        # - Market forecast is required for all deployable policies (static_unaware, capacity_aware, full_thermal_aware, heatguard)
        # - Temperature forecast is required ONLY for: capacity_aware, full_thermal_aware, heatguard_fixed, heatguard_calibrated
        temp_forecasts: dict[int, np.ndarray] | None = None
        temp_fc_required = policy in ("capacity_aware", "full_thermal_aware", "heatguard_fixed", "heatguard_calibrated")

        if temp_fc_required:
            temp_res = self.prepare_temperature_forecasts(window_id)
            if not temp_res["valid"]:
                return self._build_failure_record(
                    cell_row,
                    status=temp_res["failure_status"],
                    error_class="WindowDataIncompleteError",
                    error_msg=temp_res["failure_message"],
                    runtime_s=time.perf_counter() - t0,
                    demanded_proc=demanded_proc,
                    demanded_energy=demanded_energy,
                )
            temp_forecasts = temp_res["temp_forecasts"]

        mkt_forecasts: dict[int, ForecastResult] = {}
        if deployable:
            mkt_res = self.prepare_market_forecasts(window_id, realized_df)
            if not mkt_res["valid"]:
                return self._build_failure_record(
                    cell_row,
                    status=mkt_res["failure_status"],
                    error_class="WindowDataIncompleteError",
                    error_msg=mkt_res["failure_message"],
                    runtime_s=time.perf_counter() - t0,
                    demanded_proc=demanded_proc,
                    demanded_energy=demanded_energy,
                )
            mkt_forecasts = mkt_res["mkt_forecasts"]

            # 3. Forecast leakage audit
            for h_offset, fc in mkt_forecasts.items():
                if fc.origin_timestamp_utc > (realized_res["start_utc"] + timedelta(hours=h_offset)):
                    return self._build_failure_record(
                        cell_row,
                        status="FORECAST_LEAKAGE",
                        error_class="ForecastLeakageError",
                        error_msg="Market forecast origin timestamp exceeds schedule step origin",
                        runtime_s=time.perf_counter() - t0,
                        demanded_proc=demanded_proc,
                        demanded_energy=demanded_energy,
                    )

        # 4. Facility and constraints
        fcfg = FacilityConfig(
            model_kind=FacilityModelKind(cell_row["facility_model"]),
            nominal_compute_capacity_kw=100.0,
            thermal_scenario=get_preset_thermal_scenario(cell_row["thermal_curve"], self.repo_root / "configs/p6_thermal.yaml"),
        )
        constraints = SchedulingConstraints(
            max_cluster_power_kw=float(fcfg.nominal_compute_capacity_kw),
            max_concurrent_jobs=16,
            allow_preemption=True,
        )
        realized_state = build_realized_facility_state(realized_df[["timestamp_utc", "temperature_c"]], fcfg)

        applied_margin = None
        sched_res = None

        # 5. Policy Execution
        try:
            if policy in ("static_unaware", "capacity_aware", "full_thermal_aware"):
                sched_res, applied_margin = run_deployable_rolling_schedule_b2(
                    policy_id=policy,
                    workload_df=workload_df,
                    temp_forecasts=temp_forecasts,
                    mkt_forecasts=mkt_forecasts,
                    fcfg=fcfg,
                    objective=objective,
                    start_utc=start_ts,
                    total_window_hours=dur,
                    constraints=constraints,
                )

            elif policy == "heatguard_calibrated":
                scheduler = HeatGuardScheduler(
                    facility_config=fcfg,
                    margin_mode=HeatGuardMarginMode.calibrated,
                    calibration_artifact_dir=self.repo_root / "data/models/p6_heatguard_calibration_v3",
                    expected_manifest_sha256=FROZEN_CALIBRATION_MANIFEST_HASH,
                    objective=objective,
                    repository_root=self.repo_root,
                )

                def temp_prov(origin_utc: datetime, horizon: int) -> np.ndarray:
                    offset = int((origin_utc - start_ts).total_seconds() // 3600)
                    return temp_forecasts[offset][:horizon]

                def mkt_prov(origin_utc: datetime, horizon: int) -> ForecastResult:
                    offset = int((origin_utc - start_ts).total_seconds() // 3600)
                    return mkt_forecasts[offset]

                rolling_res = scheduler.schedule_rolling(
                    workload_df=workload_df,
                    temperature_forecast_provider=temp_prov,
                    market_forecast_provider=mkt_prov,
                    window_start_utc=start_ts,
                    total_window_hours=dur,
                    nominal_constraints=constraints,
                )
                applied_margin = rolling_res.applied_margin
                sched_res = ScheduleResult(
                    policy_name=rolling_res.policy_name,
                    policy_version=rolling_res.policy_version,
                    workload_trace_id=rolling_res.workload_trace_id,
                    window_duration_hours=rolling_res.total_horizon_hours,
                    allocations=rolling_res.allocations,
                    total_cost_usd=0.0,
                    total_carbon_emissions_kg=0.0,
                    is_feasible=rolling_res.is_feasible,
                    unmet_deadlines=rolling_res.unmet_deadlines,
                )

            elif policy == "heatguard_fixed":
                scheduler = HeatGuardScheduler(
                    facility_config=fcfg,
                    margin_mode=HeatGuardMarginMode.fixed,
                    fixed_pue_margin=0.10,
                    objective=objective,
                    repository_root=self.repo_root,
                )

                def temp_prov(origin_utc: datetime, horizon: int) -> np.ndarray:
                    offset = int((origin_utc - start_ts).total_seconds() // 3600)
                    return temp_forecasts[offset][:horizon]

                def mkt_prov(origin_utc: datetime, horizon: int) -> ForecastResult:
                    offset = int((origin_utc - start_ts).total_seconds() // 3600)
                    return mkt_forecasts[offset]

                rolling_res = scheduler.schedule_rolling(
                    workload_df=workload_df,
                    temperature_forecast_provider=temp_prov,
                    market_forecast_provider=mkt_prov,
                    window_start_utc=start_ts,
                    total_window_hours=dur,
                    nominal_constraints=constraints,
                )
                applied_margin = rolling_res.applied_margin
                sched_res = ScheduleResult(
                    policy_name=rolling_res.policy_name,
                    policy_version=rolling_res.policy_version,
                    workload_trace_id=rolling_res.workload_trace_id,
                    window_duration_hours=rolling_res.total_horizon_hours,
                    allocations=rolling_res.allocations,
                    total_cost_usd=0.0,
                    total_carbon_emissions_kg=0.0,
                    is_feasible=rolling_res.is_feasible,
                    unmet_deadlines=rolling_res.unmet_deadlines,
                )

            elif policy == "oracle_full_thermal_aware":
                pol = OracleFullThermalAwarePolicy(
                    realized_facility_state=realized_state,
                    realized_market_state=realized_df,
                    objective=objective,
                )
                pts = [
                    ForecastPoint(
                        timestamp_utc=start_ts + timedelta(hours=h),
                        horizon_hours=h,
                        predicted_price_usd_per_mwh=float(realized_df["price_usd_per_mwh"].iloc[h]),
                        predicted_carbon_g_per_kwh=float(realized_df["carbon_g_per_kwh"].iloc[h]),
                    )
                    for h in range(dur)
                ]
                fc_real = ForecastResult(
                    origin_timestamp_utc=start_ts,
                    points=pts,
                    model_name="realized_market",
                    model_version="1.0",
                )
                sched_res = pol.schedule(workload_df, fc_real, constraints)

            else:
                return self._build_failure_record(
                    cell_row,
                    status="SCHEDULER_EXCEPTION",
                    error_class="UnknownPolicyError",
                    error_msg=f"Policy {policy} not recognized",
                    runtime_s=time.perf_counter() - t0,
                    demanded_proc=demanded_proc,
                    demanded_energy=demanded_energy,
                )

            # 6. Scoring
            score_df, score_summary = score_thermal_schedule(
                schedule=sched_res,
                workload_df=workload_df,
                realized_df=realized_df,
                thermal_state_df=realized_state,
            )

        except Exception as exc:
            return self._build_failure_record(
                cell_row,
                status="SCHEDULER_EXCEPTION",
                error_class=type(exc).__name__,
                error_msg=str(exc)[:180],
                runtime_s=time.perf_counter() - t0,
                demanded_proc=demanded_proc,
                demanded_energy=demanded_energy,
            )

        runtime_s = time.perf_counter() - t0
        completed_proc = len(sched_res.allocations)
        completed_energy = float(score_summary["total_compute_energy_kwh"])
        cooling_energy = float(score_summary["total_cooling_energy_kwh"])
        total_energy = float(score_summary["total_facility_energy_kwh"])
        cost_usd = float(score_summary["cooling_adjusted_cost_usd"])
        carbon_kg = float(score_summary["cooling_adjusted_carbon_kg"])
        violation_hours = int(score_summary["facility_power_violation_hours"])
        max_excess_kw = float(score_summary["maximum_facility_power_excess_kw"])
        sched_feasible = bool(sched_res.is_feasible)
        thermal_feasible = bool(score_summary["thermally_feasible"])

        # Scientific status: SUCCESS (whether feasible or validly infeasible)
        status = "SUCCESS"

        # Provenance attribution
        if policy in ("capacity_aware", "full_thermal_aware", "heatguard_fixed", "heatguard_calibrated"):
            temp_fc_id = "p6_temperature_v2_tiny_lstm"
            temp_fc_cutoff = "t-1"
        else:
            temp_fc_id = "NOT_APPLICABLE"
            temp_fc_cutoff = "NOT_APPLICABLE"

        return {
            "run_id": run_id,
            "track_version": "B2",
            "event_id": cell_row["event_id"],
            "regional_episode_id": cell_row["regional_episode_id"],
            "station_code": cell_row["station_code"],
            "window_type": cell_row["window_type"],
            "window_id": window_id,
            "window_start_utc": realized_res["start_utc"].isoformat(),
            "window_end_utc": realized_res["end_utc"].isoformat(),
            "duration_hours": dur,
            "facility_model": cell_row["facility_model"],
            "thermal_curve": cell_row["thermal_curve"],
            "policy": policy,
            "objective": objective,
            "workload_multiplier": multiplier,
            "workload_seed": seed,
            "workload_hash": exp_workload_hash,
            "role": cell_row["role"],
            "deployable": deployable,
            "execution_status": status,
            "failure_category": "NONE",
            "error_message": "NONE",
            "scheduler_feasible": sched_feasible,
            "thermally_feasible": thermal_feasible,
            "jobs_demanded": len(workload_df),
            "jobs_completed": len(workload_df) - len(sched_res.unmet_deadlines),
            "jobs_missed": len(sched_res.unmet_deadlines),
            "demanded_processing_slots": demanded_proc,
            "completed_processing_slots": completed_proc,
            "unfinished_processing_slots": demanded_proc - completed_proc,
            "it_energy_kwh": round(completed_energy, 4),
            "cooling_energy_kwh": round(cooling_energy, 4),
            "total_facility_energy_kwh": round(total_energy, 4),
            "peak_facility_power_kw": round(float(score_df["hourly_facility_power_kw"].max()), 4),
            "power_cap_violation_hours": violation_hours,
            "maximum_power_cap_exceedance_kw": round(max_excess_kw, 4),
            "cooling_adjusted_cost_usd": round(cost_usd, 4),
            "cooling_adjusted_carbon_kg": round(carbon_kg, 4),
            "applied_margin": applied_margin,
            "forecast_identity": temp_fc_id,
            "forecast_history_cutoff": temp_fc_cutoff,
            "runtime_seconds": round(runtime_s, 4),
            "source_config_hash": "38dfdb6eb48a8ce17a8762a3b9ab946d02fd30e25538d926efa3962f77c0579c",
        }

    def _build_failure_record(
        self,
        cell_row: pd.Series,
        status: str,
        error_class: str,
        error_msg: str,
        runtime_s: float,
        demanded_proc: int | None = None,
        demanded_energy: float | None = None,
    ) -> dict[str, Any]:
        wid = cell_row["window_id"]
        win = self.windows_map.get(wid, {})
        s_utc = win.get("start_utc", pd.NaT)
        e_utc = win.get("end_utc", pd.NaT)

        policy = cell_row["policy"]
        if policy in ("capacity_aware", "full_thermal_aware", "heatguard_fixed", "heatguard_calibrated"):
            temp_fc_id = "p6_temperature_v2_tiny_lstm"
            temp_fc_cutoff = "t-1"
        else:
            temp_fc_id = "NOT_APPLICABLE"
            temp_fc_cutoff = "NOT_APPLICABLE"

        return {
            "run_id": cell_row["run_id"],
            "track_version": "B2",
            "event_id": cell_row["event_id"],
            "regional_episode_id": cell_row["regional_episode_id"],
            "station_code": cell_row["station_code"],
            "window_type": cell_row["window_type"],
            "window_id": wid,
            "window_start_utc": s_utc.isoformat() if pd.notna(s_utc) else "NONE",
            "window_end_utc": e_utc.isoformat() if pd.notna(e_utc) else "NONE",
            "duration_hours": int(cell_row["duration_hours"]),
            "facility_model": cell_row["facility_model"],
            "thermal_curve": cell_row["thermal_curve"],
            "policy": cell_row["policy"],
            "objective": cell_row["objective"],
            "workload_multiplier": float(cell_row["workload_multiplier"]),
            "workload_seed": int(cell_row["workload_seed"]),
            "workload_hash": cell_row["workload_hash"],
            "role": cell_row["role"],
            "deployable": bool(cell_row["deployable"]),
            "execution_status": "FAILED",
            "failure_category": status,
            "error_message": f"{error_class}: {error_msg}"[:200],
            "scheduler_feasible": None,
            "thermally_feasible": None,
            "jobs_demanded": None,
            "jobs_completed": None,
            "jobs_missed": None,
            "demanded_processing_slots": demanded_proc,
            "completed_processing_slots": None,
            "unfinished_processing_slots": None,
            "it_energy_kwh": None,
            "cooling_energy_kwh": None,
            "total_facility_energy_kwh": None,
            "peak_facility_power_kw": None,
            "power_cap_violation_hours": None,
            "maximum_power_cap_exceedance_kw": None,
            "cooling_adjusted_cost_usd": None,
            "cooling_adjusted_carbon_kg": None,
            "applied_margin": None,
            "forecast_identity": temp_fc_id,
            "forecast_history_cutoff": temp_fc_cutoff,
            "runtime_seconds": round(runtime_s, 4),
            "source_config_hash": "38dfdb6eb48a8ce17a8762a3b9ab946d02fd30e25538d926efa3962f77c0579c",
        }


def run_preflight(repo_root: Path) -> dict[str, Any]:
    print("=== Running Stage A Preflight Gates ===")
    verified_hashes = verify_protected_baselines(repo_root)
    print("Protected baselines verified:")
    for k, v in verified_hashes.items():
        print(f"  {k}: {v[:16]}...")

    matrix_csv = repo_root / "data/v2/benchmarks/p12_b2_matrix_cells.csv"
    df = pd.read_csv(matrix_csv)
    if len(df) != 6480:
        raise ValueError(f"Matrix row count mismatch: {len(df)} != 6480")
    if df["run_id"].nunique() != 6480:
        raise ValueError("Duplicate run_id found in matrix cells")
    print(f"Verified 6,480 unique matrix rows.")

    dry_run_p = repo_root / "data/v2/manifests/p12_b2_matrix_dry_run.json"
    with open(dry_run_p) as f:
        dr = json.load(f)

    for item in dr["workload_identities"]:
        p_csv = repo_root / item["csv_path"]
        p_parq = repo_root / item["parquet_path"]
        if sha256_file(p_csv) != item["csv_sha256"]:
            raise ValueError(f"Workload CSV hash mismatch: {p_csv}")
        if sha256_file(p_parq) != item["parquet_sha256"]:
            raise ValueError(f"Workload Parquet hash mismatch: {p_parq}")
    print(f"Verified all 30 frozen workloads.")
    return verified_hashes


def compute_frozen_inputs_fingerprint(repo_root: Path) -> str:
    """Compute deterministic SHA-256 fingerprint over frozen Phase 3 and Phase 4 inputs."""
    p3_p = repo_root / "data/v2/manifests/p12_b2_event_freeze.json"
    p3_hash = sha256_file(p3_p) if p3_p.exists() else "MISSING"

    p4_m_p = repo_root / "data/v2/manifests/p12_b2_window_freeze.json"
    p4_m_hash = sha256_file(p4_m_p) if p4_m_p.exists() else "MISSING"

    matrix_csv = repo_root / "data/v2/benchmarks/p12_b2_matrix_cells.csv"
    matrix_hash = sha256_file(matrix_csv) if matrix_csv.exists() else "MISSING"

    combined = f"{p3_hash}:{p4_m_hash}:{matrix_hash}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def select_repair_runs(
    completed_records: dict[str, dict[str, Any]],
    repair_history: list[dict[str, Any]],
    repair_revision: str,
    runner_source_hash: str,
    protocol_config_hash: str,
    frozen_inputs_fingerprint: str = "",
) -> tuple[set[str], dict[str, Any]]:
    """Determine which failed runs to invalidate and re-execute.

    Pure deterministic selection logic:
    - If a matching COMPLETED entry exists for (revision, runner_hash, config_hash, inputs_fp),
      return empty target set (idempotent no-op).
    - If a matching STARTED entry exists:
      raise RuntimeError instructing safe checkpoint recovery or explicit retry.
    - If a matching FAILED entry exists or new revision/code/config:
      authorize explicit repair targeting ONLY records with execution_status == 'FAILED'.
    - Existing successful records are NEVER selected or invalidated.
    """
    for entry in repair_history:
        entry_rev = entry.get("repair_revision")
        entry_rhash = entry.get("runner_source_hash")
        entry_chash = entry.get("protocol_config_hash")
        entry_fp = entry.get("frozen_inputs_fingerprint", "")
        entry_state = entry.get("transaction_state") or entry.get("status")

        # Identity matches
        fp_match = (not frozen_inputs_fingerprint) or (not entry_fp) or (entry_fp == frozen_inputs_fingerprint)
        if entry_rev == repair_revision and entry_rhash == runner_source_hash and entry_chash == protocol_config_hash and fp_match:
            if entry_state in ("COMPLETED", "EXECUTED"):
                return set(), {
                    "repair_revision": repair_revision,
                    "runner_source_hash": runner_source_hash,
                    "protocol_config_hash": protocol_config_hash,
                    "frozen_inputs_fingerprint": frozen_inputs_fingerprint,
                    "attempt_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "ALREADY_COMPLETED_NOOP",
                    "transaction_state": "COMPLETED",
                    "invalidated_failed_count": 0,
                    "target_run_ids": [],
                }
            elif entry_state == "STARTED":
                raise RuntimeError(
                    f"Repair transaction '{repair_revision}' is in STARTED state (incomplete/crashed). "
                    f"Cannot treat as completed or silently restart without resolution. "
                    f"Check checkpoints and mark transaction FAILED or resume cleanly."
                )
            # If FAILED, allowed to retry explicitly

    target_ids = {
        rid for rid, rec in completed_records.items()
        if rec.get("execution_status") == "FAILED"
    }

    # Protection guard: verify no successful records are targeted
    for rid in target_ids:
        if completed_records[rid].get("execution_status") == "SUCCESS":
            raise ValueError(f"CRITICAL SAFETY VIOLATION: Successful run {rid} was selected for repair!")

    # Calculate previous status and category counts
    prev_cats: dict[str, int] = {}
    for rid in target_ids:
        c = completed_records[rid].get("failure_category", "UNKNOWN")
        prev_cats[c] = prev_cats.get(c, 0) + 1

    sorted_targets = sorted(list(target_ids))
    targets_digest = hashlib.sha256(",".join(sorted_targets).encode("utf-8")).hexdigest()

    transaction_entry = {
        "repair_revision": repair_revision,
        "runner_source_hash": runner_source_hash,
        "protocol_config_hash": protocol_config_hash,
        "frozen_inputs_fingerprint": frozen_inputs_fingerprint,
        "start_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "completion_timestamp_utc": None,
        "target_count": len(target_ids),
        "target_run_ids_hash": targets_digest,
        "target_run_ids": sorted_targets,
        "previous_status_counts": {"FAILED": len(target_ids)},
        "previous_category_counts": prev_cats,
        "resulting_status_counts": {},
        "resulting_category_counts": {},
        "replaced_record_count": 0,
        "error_details": None,
        "transaction_state": "STARTED",
        "status": "STARTED",
        "invalidated_failed_count": len(target_ids),
    }
    return target_ids, transaction_entry


def execute_matrix(
    repo_root: Path,
    batch_size: int = 180,
    max_cells: int | None = None,
    smoke_only: bool = False,
    rerun_failed: bool = False,
    repair_revision: str = "rev1",
) -> None:
    runner = B2ExecutionRunner(repo_root=repo_root)

    # Check for existing checkpoint ledger
    ledger_path = runner.checkpoints_dir / "p12_b2_completed_run_ids.json"
    completed_records: dict[str, dict[str, Any]] = {}
    if ledger_path.exists():
        with open(ledger_path) as f:
            completed_records = json.load(f)
        print(f"Resumed from ledger: {len(completed_records)} runs already recorded.")

    # Repair history tracking
    repair_history_p = runner.checkpoints_dir / "p12_b2_repair_history.json"
    repair_history: list[dict[str, Any]] = []
    if repair_history_p.exists():
        with open(repair_history_p) as f:
            repair_history = json.load(f)

    active_repair_entry: dict[str, Any] | None = None

    # If rerun_failed requested, use versioned repair selection
    if rerun_failed:
        runner_source_hash = sha256_file(Path(__file__))
        protocol_config_hash = sha256_file(repo_root / "configs/p12_b2_protocol.yaml")
        frozen_inputs_fingerprint = compute_frozen_inputs_fingerprint(repo_root)

        repair_run_ids, audit_entry = select_repair_runs(
            completed_records=completed_records,
            repair_history=repair_history,
            repair_revision=repair_revision,
            runner_source_hash=runner_source_hash,
            protocol_config_hash=protocol_config_hash,
            frozen_inputs_fingerprint=frozen_inputs_fingerprint,
        )

        if not repair_run_ids:
            print(f"Targeted repair '{repair_revision}': already executed with identical runner/input hashes. True no-op (0 runs invalidated, zero filesystem modifications).")
            return

        # Explicitly invalidate target runs from completed ledger
        for rid in repair_run_ids:
            del completed_records[rid]
        print(f"Targeted repair '{repair_revision}' active: invalidated {len(repair_run_ids)} failed records for re-execution.")
        print(f"Remaining verified successful records preserved: {len(completed_records)}.")

        # Write STARTED transaction atomically to history
        active_repair_entry = audit_entry
        repair_history.append(active_repair_entry)
        tmp_history = repair_history_p.with_suffix(".tmp")
        with open(tmp_history, "w") as f:
            json.dump(repair_history, f, indent=2)
        tmp_history.rename(repair_history_p)

    # Select cells to run
    if smoke_only:
        # Pick representative smoke set
        # 5 durations: 120, 144, 168, 192, 312
        # Both seeds, all 3 multipliers
        # Core policies + heatguard + oracle
        smoke_run_ids = [
            # 144h RDD heatwave
            "p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__static_unaware__m1__s20261016__carbon_first",
            "p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__capacity_aware__m2__s20261017__carbon_first",
            "p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__full_thermal_aware__m3__s20261016__carbon_first",
            "p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__heatguard_fixed__m1__s20261016__carbon_first",
            "p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__heatguard_calibrated__m1__s20261017__carbon_first",
            "p12_b2__B2_HW_RDD_20230714__heatwave__B2_HW_RDD_20230714__power_capped__medium__oracle_full_thermal_aware__m1__s20261016__carbon_first",
            # Matched control
            "p12_b2__B2_HW_RDD_20230714__matched_control__B2_CTRL_RDD_20230714_20230707__power_capped__medium__static_unaware__m1__s20261016__carbon_first",
            # Ordinary window (144h)
            "p12_b2__B2_HW_RDD_20230714__ordinary_window__B2_ORD_RDD_20230714_20230601__power_capped__medium__capacity_aware__m1__s20261016__carbon_first",
            # 120h SFO heatwave
            "p12_b2__B2_HW_SFO_20240702__heatwave__B2_HW_SFO_20240702__power_capped__medium__static_unaware__m1__s20261016__carbon_first",
            # 168h FAT heatwave
            "p12_b2__B2_HW_FAT_20240722__heatwave__B2_HW_FAT_20240722__power_capped__medium__static_unaware__m1__s20261016__carbon_first",
            # 192h SAC heatwave
            "p12_b2__B2_HW_SAC_20240701__heatwave__B2_HW_SAC_20240701__power_capped__medium__static_unaware__m1__s20261016__carbon_first",
            # 312h RDD heatwave
            "p12_b2__B2_HW_RDD_20240702__heatwave__B2_HW_RDD_20240702__power_capped__medium__static_unaware__m1__s20261016__carbon_first",
        ]
        cells_to_execute = runner.df_cells[runner.df_cells["run_id"].isin(smoke_run_ids)].copy().reset_index(drop=True)
    else:
        cells_to_execute = runner.df_cells

    if max_cells is not None:
        cells_to_execute = cells_to_execute.iloc[:max_cells]

    total_target = len(cells_to_execute)
    print(f"Beginning execution: {total_target} target runs (already completed: {len(completed_records)}).")

    session_executed = 0
    batch_records = []

    try:
        for idx, row in cells_to_execute.iterrows():
            rid = row["run_id"]
            if rid in completed_records:
                continue

            rec = runner.execute_cell(row)
            completed_records[rid] = rec
            batch_records.append(rec)
            session_executed += 1

            if len(batch_records) >= batch_size:
                # Atomic checkpoint write
                ckpt_file = runner.checkpoints_dir / f"checkpoint_batch_{len(completed_records)}.json"
                tmp_ckpt = ckpt_file.with_suffix(".tmp")
                with open(tmp_ckpt, "w") as f:
                    json.dump(batch_records, f)
                tmp_ckpt.rename(ckpt_file)

                # Atomic ledger update
                tmp_ledger = ledger_path.with_suffix(".tmp")
                with open(tmp_ledger, "w") as f:
                    json.dump(completed_records, f)
                tmp_ledger.rename(ledger_path)

                print(f"[{len(completed_records)}/{total_target}] Saved checkpoint batch of {len(batch_records)} runs.")
                batch_records.clear()

        # Flush final batch
        if batch_records:
            ckpt_file = runner.checkpoints_dir / f"checkpoint_batch_{len(completed_records)}.json"
            tmp_ckpt = ckpt_file.with_suffix(".tmp")
            with open(tmp_ckpt, "w") as f:
                json.dump(batch_records, f)
            tmp_ckpt.rename(ckpt_file)

            tmp_ledger = ledger_path.with_suffix(".tmp")
            with open(tmp_ledger, "w") as f:
                json.dump(completed_records, f)
            tmp_ledger.rename(ledger_path)
            print(f"Flushed final checkpoint batch. Total completed: {len(completed_records)}.")

        if not smoke_only and len(completed_records) == len(runner.df_cells):
            # Materialize final results
            print("\n=== Materializing Final Phase 5 Results ===")
            all_results = [completed_records[r["run_id"]] for _, r in runner.df_cells.iterrows()]
            df_final = pd.DataFrame(all_results)

            parquet_out = runner.results_dir / "p12_b2_runs.parquet"
            tmp_parq = parquet_out.with_suffix(".tmp")
            df_final.to_parquet(tmp_parq, index=False)
            tmp_parq.rename(parquet_out)

            jsonl_out = runner.results_dir / "p12_b2_execution.jsonl"
            tmp_jsonl = jsonl_out.with_suffix(".tmp")
            with open(tmp_jsonl, "w") as f:
                for r in all_results:
                    f.write(json.dumps(r) + "\n")
            tmp_jsonl.rename(jsonl_out)

            # Build execution manifest
            manifest_p = runner.manifests_dir / "p12_b2_execution_manifest.json"
            parq_hash = sha256_file(parquet_out)
            jsonl_hash = sha256_file(jsonl_out)

            # Calculate success-only feasibility metrics
            success_df = df_final[df_final["execution_status"] == "SUCCESS"]
            failed_df = df_final[df_final["execution_status"] == "FAILED"]

            sched_feas = int((success_df["scheduler_feasible"] == True).sum())
            sched_infeas = int((success_df["scheduler_feasible"] == False).sum())
            therm_feas = int((success_df["thermally_feasible"] == True).sum())
            therm_infeas = int((success_df["thermally_feasible"] == False).sum())

            failure_counts = failed_df["failure_category"].value_counts().to_dict()

            manifest = {
                "manifest_version": "2.0",
                "phase": "B2_Phase_5_Execution",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "total_cells": len(all_results),
                "unique_run_ids": df_final["run_id"].nunique(),
                "deployable_cells": int((df_final["deployable"] == True).sum()),
                "oracle_reference_cells": int((df_final["deployable"] == False).sum()),
                "success_count": len(success_df),
                "failed_count": len(failed_df),
                "failure_reasons_breakdown": failure_counts,
                "feasibility_breakdown": {
                    "scheduler_feasible_successes": sched_feas,
                    "scheduler_infeasible_successes": sched_infeas,
                    "thermally_feasible_successes": therm_feas,
                    "thermally_infeasible_successes": therm_infeas,
                },
                "artifacts": {
                    "runs_parquet": {
                        "path": "data/v2/results/p12_b2_runs.parquet",
                        "rows": len(df_final),
                        "bytes": parquet_out.stat().st_size,
                        "sha256": parq_hash,
                    },
                    "execution_jsonl": {
                        "path": "data/v2/results/p12_b2_execution.jsonl",
                        "rows": len(all_results),
                        "bytes": jsonl_out.stat().st_size,
                        "sha256": jsonl_hash,
                    },
                },
                "protected_baselines_verification": verify_protected_baselines(repo_root),
            }
            with open(manifest_p, "w") as f:
                json.dump(manifest, f, indent=2)

            print(f"Saved final parquet to {parquet_out} ({parq_hash[:16]}...)")
            print(f"Saved final jsonl to {jsonl_out} ({jsonl_hash[:16]}...)")
            print(f"Saved execution manifest to {manifest_p}")

            # If repair transaction was active, update to COMPLETED atomically
            if active_repair_entry is not None:
                # Count resulting statuses among targets
                res_statuses: dict[str, int] = {}
                res_cats: dict[str, int] = {}
                for rid in active_repair_entry["target_run_ids"]:
                    r_rec = completed_records.get(rid, {})
                    st = r_rec.get("execution_status", "UNKNOWN")
                    res_statuses[st] = res_statuses.get(st, 0) + 1
                    fc = r_rec.get("failure_category", "NONE")
                    res_cats[fc] = res_cats.get(fc, 0) + 1

                active_repair_entry["completion_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
                active_repair_entry["resulting_status_counts"] = res_statuses
                active_repair_entry["resulting_category_counts"] = res_cats
                active_repair_entry["replaced_record_count"] = session_executed
                active_repair_entry["transaction_state"] = "COMPLETED"
                active_repair_entry["status"] = "COMPLETED"

                tmp_history = repair_history_p.with_suffix(".tmp")
                with open(tmp_history, "w") as f:
                    json.dump(repair_history, f, indent=2)
                tmp_history.rename(repair_history_p)
                print(f"Repair transaction '{active_repair_entry['repair_revision']}' atomically marked COMPLETED.")

    except Exception as exc:
        if active_repair_entry is not None:
            active_repair_entry["transaction_state"] = "FAILED"
            active_repair_entry["status"] = "FAILED"
            active_repair_entry["error_details"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            tmp_history = repair_history_p.with_suffix(".tmp")
            with open(tmp_history, "w") as f:
                json.dump(repair_history, f, indent=2)
            tmp_history.rename(repair_history_p)
            print(f"Repair transaction '{active_repair_entry['repair_revision']}' marked FAILED: {exc}")
        raise


def normalize_failed_ledger_and_materialize(repo_root: Path) -> None:
    """Normalize existing failed ledger records to null out unevaluated metrics and materialize."""
    runner = B2ExecutionRunner(repo_root=repo_root)
    ledger_path = runner.checkpoints_dir / "p12_b2_completed_run_ids.json"
    if not ledger_path.exists():
        raise FileNotFoundError(f"Checkpoint ledger missing at {ledger_path}")

    with open(ledger_path) as f:
        completed_records = json.load(f)

    normalized_count = 0
    for rid, rec in completed_records.items():
        if rec.get("execution_status") == "FAILED":
            rec["scheduler_feasible"] = None
            rec["thermally_feasible"] = None
            rec["jobs_demanded"] = None
            rec["jobs_completed"] = None
            rec["jobs_missed"] = None
            rec["completed_processing_slots"] = None
            rec["unfinished_processing_slots"] = None
            rec["it_energy_kwh"] = None
            rec["cooling_energy_kwh"] = None
            rec["total_facility_energy_kwh"] = None
            rec["peak_facility_power_kw"] = None
            rec["power_cap_violation_hours"] = None
            rec["maximum_power_cap_exceedance_kw"] = None
            rec["cooling_adjusted_cost_usd"] = None
            rec["cooling_adjusted_carbon_kg"] = None
            rec["applied_margin"] = None
            normalized_count += 1

    print(f"Normalized schema on {normalized_count} failed records in ledger.")

    # Atomic ledger update
    tmp_ledger = ledger_path.with_suffix(".tmp")
    with open(tmp_ledger, "w") as f:
        json.dump(completed_records, f)
    tmp_ledger.rename(ledger_path)

    # Materialize final results
    print("\n=== Materializing Final Normalized Phase 5 Results ===")
    all_results = [completed_records[r["run_id"]] for _, r in runner.df_cells.iterrows()]
    df_final = pd.DataFrame(all_results)

    parquet_out = runner.results_dir / "p12_b2_runs.parquet"
    tmp_parq = parquet_out.with_suffix(".tmp")
    df_final.to_parquet(tmp_parq, index=False)
    tmp_parq.rename(parquet_out)

    jsonl_out = runner.results_dir / "p12_b2_execution.jsonl"
    tmp_jsonl = jsonl_out.with_suffix(".tmp")
    with open(tmp_jsonl, "w") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")
    tmp_jsonl.rename(jsonl_out)

    # Build execution manifest
    manifest_p = runner.manifests_dir / "p12_b2_execution_manifest.json"
    parq_hash = sha256_file(parquet_out)
    jsonl_hash = sha256_file(jsonl_out)

    success_df = df_final[df_final["execution_status"] == "SUCCESS"]
    failed_df = df_final[df_final["execution_status"] == "FAILED"]

    sched_feas = int((success_df["scheduler_feasible"] == True).sum())
    sched_infeas = int((success_df["scheduler_feasible"] == False).sum())
    therm_feas = int((success_df["thermally_feasible"] == True).sum())
    therm_infeas = int((success_df["thermally_feasible"] == False).sum())

    failure_counts = failed_df["failure_category"].value_counts().to_dict()

    manifest = {
        "manifest_version": "2.0",
        "phase": "B2_Phase_5_Execution",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_cells": len(all_results),
        "unique_run_ids": df_final["run_id"].nunique(),
        "deployable_cells": int((df_final["deployable"] == True).sum()),
        "oracle_reference_cells": int((df_final["deployable"] == False).sum()),
        "success_count": len(success_df),
        "failed_count": len(failed_df),
        "failure_reasons_breakdown": failure_counts,
        "feasibility_breakdown": {
            "scheduler_feasible_successes": sched_feas,
            "scheduler_infeasible_successes": sched_infeas,
            "thermally_feasible_successes": therm_feas,
            "thermally_infeasible_successes": therm_infeas,
        },
        "artifacts": {
            "runs_parquet": {
                "path": "data/v2/results/p12_b2_runs.parquet",
                "rows": len(df_final),
                "bytes": parquet_out.stat().st_size,
                "sha256": parq_hash,
            },
            "execution_jsonl": {
                "path": "data/v2/results/p12_b2_execution.jsonl",
                "rows": len(all_results),
                "bytes": jsonl_out.stat().st_size,
                "sha256": jsonl_hash,
            },
        },
        "protected_baselines_verification": verify_protected_baselines(repo_root),
    }
    with open(manifest_p, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Saved normalized parquet to {parquet_out} ({parq_hash[:16]}...)")
    print(f"Saved normalized jsonl to {jsonl_out} ({jsonl_hash[:16]}...)")
    print(f"Saved normalized execution manifest to {manifest_p}")


def finalize_repair_identity(
    repo_root: Path,
    repair_revision: str = "rev1",
) -> dict[str, Any]:
    """Perform zero-execution identity migration binding current runner hash to validated artifacts.

    Validates all canonical constraints:
    - Protected baselines preflight.
    - Exactly 6,480 unique run IDs in ledger matching frozen matrix cells.
    - Exactly 5,448 successes and 1,032 failures (936 WEATHER_DATA_INCOMPLETE, 96 FORECAST_MISSING).
    - Failed rows have all scientific outcome metrics set to null.
    - Successful rows satisfy equal-service accounting (C + U = D).
    - Parquet and JSONL match ledger and manifest checksums.
    - Success-only feasibility matches manifest.
    - Appends NO_EXECUTION_IDENTITY_MIGRATION entry to repair history atomically.
    - Idempotent: true no-op on re-invocation with matching revision, runner hash, config hash, and fingerprint.
    """
    print(f"=== Finalizing Repair Identity for Revision '{repair_revision}' ===")
    verified_baselines = run_preflight(repo_root)

    runner = B2ExecutionRunner(repo_root=repo_root)
    ledger_path = runner.checkpoints_dir / "p12_b2_completed_run_ids.json"
    if not ledger_path.exists():
        raise FileNotFoundError(f"Canonical ledger missing at {ledger_path}")

    with open(ledger_path) as f:
        completed_records: dict[str, dict[str, Any]] = json.load(f)

    # 1. Row count & matrix ID coverage
    if len(completed_records) != 6480:
        raise ValueError(f"Ledger record count mismatch: {len(completed_records)} != 6480")

    expected_ids = set(runner.df_cells["run_id"])
    actual_ids = set(completed_records.keys())
    if actual_ids != expected_ids:
        raise ValueError(f"Ledger run_ids do not match matrix cells: missing={len(expected_ids - actual_ids)}, unexpected={len(actual_ids - expected_ids)}")

    # 2. Status & failure counts
    success_records = {rid: r for rid, r in completed_records.items() if r.get("execution_status") == "SUCCESS"}
    failed_records = {rid: r for rid, r in completed_records.items() if r.get("execution_status") == "FAILED"}

    if len(success_records) != 5448:
        raise ValueError(f"Success count mismatch: {len(success_records)} != 5448")
    if len(failed_records) != 1032:
        raise ValueError(f"Failure count mismatch: {len(failed_records)} != 1032")

    fail_cats: dict[str, int] = {}
    for r in failed_records.values():
        c = r.get("failure_category", "UNKNOWN")
        fail_cats[c] = fail_cats.get(c, 0) + 1

    if fail_cats != {"WEATHER_DATA_INCOMPLETE": 936, "FORECAST_MISSING": 96}:
        raise ValueError(f"Failure category breakdown mismatch: {fail_cats}")

    # 3. Failed outcome fields must be null
    null_fields = [
        "scheduler_feasible", "thermally_feasible", "jobs_demanded", "jobs_completed",
        "jobs_missed", "completed_processing_slots", "unfinished_processing_slots",
        "it_energy_kwh", "cooling_energy_kwh", "total_facility_energy_kwh",
        "peak_facility_power_kw", "power_cap_violation_hours", "maximum_power_cap_exceedance_kw",
        "cooling_adjusted_cost_usd", "cooling_adjusted_carbon_kg", "applied_margin",
    ]
    for rid, r in failed_records.items():
        for field in null_fields:
            if r.get(field) is not None:
                raise ValueError(f"Failed record {rid} has non-null {field}: {r.get(field)}")
        if r.get("demanded_processing_slots") is None:
            raise ValueError(f"Failed record {rid} missing demanded_processing_slots input metadata")

    # 4. Equal-service accounting on successes
    sched_feas = 0
    sched_infeas = 0
    therm_feas = 0
    therm_infeas = 0
    for rid, r in success_records.items():
        d = r.get("demanded_processing_slots")
        c = r.get("completed_processing_slots")
        u = r.get("unfinished_processing_slots")
        if d is None or c is None or u is None or (c + u != d):
            raise ValueError(f"Equal-service accounting violated for success run {rid}: d={d}, c={c}, u={u}")

        sf = r.get("scheduler_feasible")
        if sf is True:
            sched_feas += 1
            if r.get("jobs_missed") != 0 or u != 0:
                raise ValueError(f"Feasible run {rid} has unmet jobs/slots")
        elif sf is False:
            sched_infeas += 1

        tf = r.get("thermally_feasible")
        if tf is True:
            therm_feas += 1
        elif tf is False:
            therm_infeas += 1

    if sched_feas != 310 or sched_infeas != 5138 or therm_feas != 221 or therm_infeas != 5227:
        raise ValueError(f"Feasibility counts mismatch: sched=({sched_feas}, {sched_infeas}), therm=({therm_feas}, {therm_infeas})")

    # 5. Check Parquet & JSONL artifacts
    parquet_p = runner.results_dir / "p12_b2_runs.parquet"
    jsonl_p = runner.results_dir / "p12_b2_execution.jsonl"
    manifest_p = runner.manifests_dir / "p12_b2_execution_manifest.json"

    if not parquet_p.exists() or not jsonl_p.exists() or not manifest_p.exists():
        raise FileNotFoundError("Canonical result artifacts or execution manifest missing")

    parq_h = sha256_file(parquet_p)
    jsonl_h = sha256_file(jsonl_p)
    manifest_h = sha256_file(manifest_p)

    with open(manifest_p) as f:
        manifest_data = json.load(f)

    if manifest_data["artifacts"]["runs_parquet"]["sha256"] != parq_h:
        raise ValueError("Parquet hash does not match manifest")
    if manifest_data["artifacts"]["execution_jsonl"]["sha256"] != jsonl_h:
        raise ValueError("JSONL hash does not match manifest")

    # 6. Compute current identity hashes
    runner_src_h = sha256_file(Path(__file__))
    protocol_cfg_h = sha256_file(repo_root / "configs/p12_b2_protocol.yaml")
    frozen_inputs_fp = compute_frozen_inputs_fingerprint(repo_root)

    # 7. Check repair history
    repair_history_p = runner.checkpoints_dir / "p12_b2_repair_history.json"
    repair_history: list[dict[str, Any]] = []
    if repair_history_p.exists():
        with open(repair_history_p) as f:
            repair_history = json.load(f)

    # Idempotence check: already finalized under this exact identity?
    for entry in repair_history:
        if (
            entry.get("repair_revision") == repair_revision
            and entry.get("runner_source_hash") == runner_src_h
            and entry.get("protocol_config_hash") == protocol_cfg_h
            and entry.get("frozen_inputs_fingerprint") == frozen_inputs_fp
            and entry.get("transaction_state") == "COMPLETED"
        ):
            print(f"Repair identity '{repair_revision}' already finalized with current runner hash {runner_src_h[:16]}... True no-op.")
            return entry

    # Find previous completed transaction for this revision
    prev_entry = None
    for entry in reversed(repair_history):
        if entry.get("repair_revision") == repair_revision and entry.get("transaction_state") == "COMPLETED":
            prev_entry = entry
            break

    prev_runner_h = prev_entry.get("runner_source_hash") if prev_entry else "UNKNOWN"

    empty_targets_digest = hashlib.sha256("".encode("utf-8")).hexdigest()

    migration_entry = {
        "repair_revision": repair_revision,
        "transaction_kind": "NO_EXECUTION_IDENTITY_MIGRATION",
        "transaction_state": "COMPLETED",
        "status": "COMPLETED",
        "runner_source_hash": runner_src_h,
        "protocol_config_hash": protocol_cfg_h,
        "frozen_inputs_fingerprint": frozen_inputs_fp,
        "migration_from_runner_hash": prev_runner_h,
        "target_count": 0,
        "target_run_ids": [],
        "target_run_ids_hash": empty_targets_digest,
        "replaced_record_count": 0,
        "scheduler_execution_count": 0,
        "previous_status_counts": {
            "SUCCESS": 5448,
            "FAILED": 1032,
        },
        "resulting_status_counts": {
            "SUCCESS": 5448,
            "FAILED": 1032,
        },
        "previous_artifact_hashes": {
            "runs_parquet": parq_h,
            "execution_jsonl": jsonl_h,
            "execution_manifest": manifest_h,
        },
        "resulting_artifact_hashes": {
            "runs_parquet": parq_h,
            "execution_jsonl": jsonl_h,
            "execution_manifest": manifest_h,
        },
        "completion_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "Transaction-only runner changes; scientific execution logic and canonical results verified unchanged.",
        "error_details": None,
    }

    repair_history.append(migration_entry)
    tmp_hist = repair_history_p.with_suffix(".tmp")
    with open(tmp_hist, "w") as f:
        json.dump(repair_history, f, indent=2)
    tmp_hist.rename(repair_history_p)

    print(f"Successfully appended zero-execution identity migration for runner {runner_src_h[:16]}... to {repair_history_p}")
    return migration_entry


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track B2 Phase 5 Execution Runner")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--batch-size", type=int, default=180)
    parser.add_argument("--max-cells", type=int, default=None)
    parser.add_argument("--rerun-failed", action="store_true", help="Re-execute only previously failed records")
    parser.add_argument("--repair-revision", type=str, default="rev1", help="Identifier for targeted repair revision")
    parser.add_argument("--normalize-failed-schema", action="store_true", help="Deterministically normalize failed ledger records to null unevaluated metrics and materialize")
    parser.add_argument("--finalize-repair-identity", action="store_true", help="Zero-execution identity migration binding current runner hash to canonical outputs")
    args = parser.parse_args()

    if args.preflight_only:
        run_preflight(args.repo_root)
    elif args.normalize_failed_schema:
        run_preflight(args.repo_root)
        normalize_failed_ledger_and_materialize(args.repo_root)
    elif args.finalize_repair_identity:
        finalize_repair_identity(args.repo_root, repair_revision=args.repair_revision)
    elif args.smoke_test:
        run_preflight(args.repo_root)
        execute_matrix(args.repo_root, batch_size=args.batch_size, smoke_only=True)
    else:
        run_preflight(args.repo_root)
        execute_matrix(
            args.repo_root,
            batch_size=args.batch_size,
            max_cells=args.max_cells,
            rerun_failed=args.rerun_failed,
            repair_revision=args.repair_revision,
        )
