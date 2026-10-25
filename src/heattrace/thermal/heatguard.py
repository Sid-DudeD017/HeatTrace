"""HeatGuard rolling scheduling adapter with calibrated PUE safety margin.

Mechanics at each rolling origin:
1. Use only causal information available at or before that origin.
2. Produce/use the causal 24-hour temperature forecast.
3. Convert forecast temperature to forecast PUE using frozen facility model.
4. Apply selected margin mode:
   - "calibrated": m_cal (from calibration result)
   - "fixed": fixed 0.10 margin comparator
   - "none": no margin (0.0)
5. Compute pue_safe = min(max_pue, forecast_pue + margin).
6. Compute safe capacity:
   - energy_only: safe_capacity[t] = nominal_capacity[t]
   - power_capped: safe_capacity[t] = min(nominal_capacity[t], facility_cap_kw / pue_safe[t])
7. Replan only unfinished, released, eligible work.
8. Commit only the next one-hour interval.
9. Carry remaining work into next replan.
10. Preserve completed/committed work exactly; never allow it to reappear or be reallocated.
11. Explicitly check beyond-horizon deadlines:
    - calculate minimum in-window work required to retain later feasibility;
    - schedule/reserve that work in the window;
    - report projected infeasibility when sufficient capacity does not exist.
12. Fail loudly on invalid inputs; no silent job drops.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from heattrace.policy.common import sort_workload_jobs_deterministically
from heattrace.policy.greedy import CarbonFirstGreedyPolicy, CostFirstGreedyPolicy
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
    SchedulingPolicy,
)
from heattrace.thermal.facility import FacilityConfig, FacilityModelKind, get_preset_thermal_scenario
from heattrace.thermal.model import ThermalScenario, pue_from_temperature
from heattrace.thermal.scheduler import HeatAwareCapacityAdapter

from heattrace.forecast.calibration import (
    CalibrationResult,
    load_calibration_artifact,
    validate_sha256_hex,
)


def compute_safe_pue(
    forecast_pue: float | np.ndarray,
    safety_margin: float,
    max_pue: float = 1.70,
) -> float | np.ndarray:
    """Compute pue_safe = min(max_pue, forecast_pue + safety_margin)."""
    if isinstance(safety_margin, bool) or not isinstance(safety_margin, (int, float)):
        raise TypeError("safety_margin must be a numeric float")
    margin_val = float(safety_margin)
    if not math.isfinite(margin_val) or margin_val < 0.0:
        raise ValueError(f"safety_margin must be finite and >= 0, got {margin_val}")

    if isinstance(max_pue, bool) or not isinstance(max_pue, (int, float)):
        raise TypeError("max_pue must be a numeric float")
    max_pue_val = float(max_pue)
    if not math.isfinite(max_pue_val) or max_pue_val < 1.0:
        raise ValueError(f"max_pue must be finite and >= 1.0, got {max_pue_val}")

    if isinstance(forecast_pue, (int, float)):
        val = float(forecast_pue)
        if not math.isfinite(val) or val < 1.0:
            raise ValueError(f"forecast_pue must be finite and >= 1.0, got {val}")
        return float(min(max_pue_val, val + margin_val))

    arr = np.asarray(forecast_pue, dtype=np.float64)
    if not np.all(np.isfinite(arr)) or np.any(arr < 1.0):
        raise ValueError("forecast_pue array contains non-finite values or values < 1.0")
    safe_arr = np.minimum(max_pue_val, arr + margin_val)
    return safe_arr



FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256 = (
    "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c"
)


class HeatGuardMarginMode(str, Enum):
    """Supported margin modes for HeatGuard."""
    calibrated = "calibrated"
    fixed = "fixed"
    none = "none"


@dataclass(frozen=True)
class HeatGuardCommitmentStep:
    """Outcome of one rolling replan and one-hour commitment step."""
    replan_origin_hour: int
    replan_timestamp_utc: datetime
    committed_hour_offset: int
    committed_allocations: list[ScheduledJobAllocation]
    forecast_pue: list[float]
    pue_safe: list[float]
    safe_capacity_kw: list[float]
    active_jobs_remaining: dict[str, int]
    is_projected_feasible: bool
    unmet_deadlines: list[str]


@dataclass(frozen=True)
class HeatGuardRollingResult:
    """Complete multi-hour rolling scheduling result."""
    policy_name: str
    policy_version: str
    workload_trace_id: str
    total_horizon_hours: int
    commit_interval_hours: int
    allocations: list[ScheduledJobAllocation]
    steps: list[HeatGuardCommitmentStep]
    is_feasible: bool
    unmet_deadlines: list[str]
    margin_mode: HeatGuardMarginMode
    applied_margin: float


def validate_heatguard_workload_df(workload_df: pd.DataFrame) -> None:
    """Validate canonical workload fields and bounds strictly.

    Enforces:
    - Non-empty DataFrame
    - Exactly one unique non-empty workload_trace_id
    - Unique non-empty job IDs (no duplicate job IDs)
    - Valid integer arrival, deadline, processing requirement
    - Valid numeric finite non-negative energy
    - Non-preemption / parallelism contract (maximum_parallelism == 1 if specified)
    - processing_requirement <= (deadline - arrival)
    """
    if not isinstance(workload_df, pd.DataFrame) or workload_df.empty:
        raise ValueError("workload_df must be a non-empty DataFrame")

    required_cols = [
        "workload_trace_id",
        "job_id",
        "arrival_offset_hours",
        "deadline_offset_hours",
        "processing_requirement",
        "energy_kwh",
    ]
    for c in required_cols:
        if c not in workload_df.columns:
            raise ValueError(f"workload_df missing required column '{c}'")

    trace_ids = []
    for idx, row in workload_df.iterrows():
        tid_raw = row["workload_trace_id"]
        if not isinstance(tid_raw, str) or not tid_raw.strip():
            raise ValueError(
                f"workload_df row {idx} has invalid workload_trace_id: {tid_raw!r} (must be non-empty string, no nulls/NaNs)"
            )
        trace_ids.append(tid_raw.strip())

    unique_trace_ids = sorted(list(set(trace_ids)))
    if len(unique_trace_ids) != 1:
        raise ValueError(
            f"workload_df must contain exactly one non-empty workload_trace_id across all rows, found {unique_trace_ids}"
        )

    seen_job_ids: set[str] = set()

    for _, row in workload_df.iterrows():
        jid_raw = row["job_id"]
        if not isinstance(jid_raw, str) or not jid_raw.strip():
            raise ValueError(f"Job ID must be non-empty string, got {jid_raw!r}")
        jid = jid_raw.strip()
        if jid in seen_job_ids:
            raise ValueError(f"Duplicate job_id detected in workload: '{jid}'")
        seen_job_ids.add(jid)

        arr = row["arrival_offset_hours"]
        dead = row["deadline_offset_hours"]
        req = row["processing_requirement"]
        energy = row["energy_kwh"]

        if isinstance(arr, bool) or not isinstance(arr, (int, np.integer)):
            raise TypeError(f"Job '{jid}' arrival_offset_hours must be int, got {type(arr).__name__}")
        if isinstance(dead, bool) or not isinstance(dead, (int, np.integer)):
            raise TypeError(f"Job '{jid}' deadline_offset_hours must be int, got {type(dead).__name__}")
        if isinstance(req, bool) or not isinstance(req, (int, np.integer)):
            raise TypeError(f"Job '{jid}' processing_requirement must be int, got {type(req).__name__}")
        if isinstance(energy, bool) or not isinstance(energy, (int, float, np.floating)):
            raise TypeError(f"Job '{jid}' energy_kwh must be numeric float, got {type(energy).__name__}")

        arr_int = int(arr)
        dead_int = int(dead)
        req_int = int(req)
        energy_flt = float(energy)

        if arr_int < 0:
            raise ValueError(f"Job '{jid}' arrival_offset_hours must be >= 0, got {arr_int}")
        if dead_int <= arr_int:
            raise ValueError(
                f"Job '{jid}' deadline ({dead_int}) must be strictly greater than arrival ({arr_int})"
            )
        if req_int <= 0:
            raise ValueError(f"Job '{jid}' processing_requirement must be > 0, got {req_int}")
        if not math.isfinite(energy_flt) or energy_flt < 0.0:
            raise ValueError(f"Job '{jid}' energy_kwh must be finite and >= 0, got {energy_flt}")
        if req_int > (dead_int - arr_int):
            raise ValueError(
                f"Job '{jid}' processing_requirement ({req_int}) exceeds duration window ({dead_int - arr_int})"
            )

        if "maximum_parallelism" in row and not pd.isna(row["maximum_parallelism"]):
            max_par = row["maximum_parallelism"]
            if isinstance(max_par, bool) or not isinstance(max_par, (int, np.integer)):
                raise TypeError(f"Job '{jid}' maximum_parallelism must be int, got {type(max_par).__name__}")
            if not math.isfinite(float(max_par)) or int(max_par) < 1:
                raise ValueError(
                    f"Job '{jid}' maximum_parallelism {max_par} must be a finite integer >= 1"
                )


def validate_heatguard_forecast_inputs(
    origin_utc: datetime,
    forecast_horizon_hours: int,
    temperature_forecast: np.ndarray | list[float],
    market_forecast: ForecastResult,
) -> tuple[np.ndarray, ForecastResult]:
    """Strictly validate temperature and market forecast inputs for deployable HeatGuard.

    Rejects non-finite values, shifted/duplicate/non-UTC timestamps, mismatched origins,
    or wrong horizon counts.
    """
    if origin_utc.tzinfo is None or origin_utc.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"Rolling origin timestamp must be explicit UTC, got {origin_utc}")

    # 1. Temperature forecast
    temp_arr = np.asarray(temperature_forecast, dtype=np.float64).flatten()
    if len(temp_arr) != forecast_horizon_hours:
        raise ValueError(
            f"Temperature forecast at {origin_utc.isoformat()} returned {len(temp_arr)} values; expected {forecast_horizon_hours}"
        )
    if not np.all(np.isfinite(temp_arr)):
        raise ValueError(f"Temperature forecast at {origin_utc.isoformat()} contains non-finite values")

    # 2. Market forecast
    if not isinstance(market_forecast, ForecastResult):
        raise TypeError(f"market_forecast must be ForecastResult, got {type(market_forecast).__name__}")

    if market_forecast.origin_timestamp_utc != origin_utc:
        raise ValueError(
            f"Market forecast origin ({market_forecast.origin_timestamp_utc.isoformat()}) "
            f"does not match rolling origin ({origin_utc.isoformat()})"
        )

    pts = market_forecast.points
    if len(pts) != forecast_horizon_hours:
        raise ValueError(
            f"Market forecast point count ({len(pts)}) != expected horizon ({forecast_horizon_hours})"
        )

    seen_ts: set[datetime] = set()
    for h, pt in enumerate(pts):
        if not isinstance(pt, ForecastPoint):
            raise TypeError(f"Forecast point {h} must be ForecastPoint, got {type(pt).__name__}")

        if pt.horizon_hours != h:
            raise ValueError(f"Point {h} has horizon_hours {pt.horizon_hours}; expected {h}")

        expected_ts = origin_utc + timedelta(hours=h)
        if pt.timestamp_utc != expected_ts:
            raise ValueError(
                f"Point {h} timestamp {pt.timestamp_utc.isoformat()} does not match expected contiguous hour {expected_ts.isoformat()}"
            )

        if pt.timestamp_utc.tzinfo is None or pt.timestamp_utc.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError(f"Point {h} timestamp must be explicit UTC, got {pt.timestamp_utc}")

        if pt.timestamp_utc in seen_ts:
            raise ValueError(f"Duplicate timestamp {pt.timestamp_utc.isoformat()} in market forecast")
        seen_ts.add(pt.timestamp_utc)

        p = pt.predicted_price_usd_per_mwh
        c = pt.predicted_carbon_g_per_kwh
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p):
            raise ValueError(f"Point {h} predicted_price_usd_per_mwh must be finite numeric, got {p}")
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c):
            raise ValueError(f"Point {h} predicted_carbon_g_per_kwh must be finite numeric, got {c}")

    return temp_arr, market_forecast



def compute_safe_capacity_vector(
    nominal_capacity_kw: float,
    pue_safe: np.ndarray,
    facility_model_kind: FacilityModelKind | str,
    facility_cap_kw: float | None = None,
) -> np.ndarray:
    """Compute safe capacity vector for the forecast horizon.

    energy_only:
        safe_capacity[t] = nominal_capacity[t]
    power_capped:
        safe_capacity[t] = min(nominal_capacity[t], facility_cap_kw / pue_safe[t])
    """
    kind = FacilityModelKind(facility_model_kind) if isinstance(facility_model_kind, str) else facility_model_kind
    pue_arr = np.asarray(pue_safe, dtype=np.float64)

    if not np.all(np.isfinite(pue_arr)) or np.any(pue_arr < 1.0):
        raise ValueError("pue_safe contains non-finite values or values < 1.0")

    if not math.isfinite(nominal_capacity_kw) or nominal_capacity_kw <= 0.0:
        raise ValueError(f"nominal_capacity_kw must be finite and > 0, got {nominal_capacity_kw}")

    if kind == FacilityModelKind.energy_only:
        return np.full_like(pue_arr, nominal_capacity_kw, dtype=np.float64)

    elif kind == FacilityModelKind.power_capped:
        if facility_cap_kw is None or not math.isfinite(facility_cap_kw) or facility_cap_kw <= 0.0:
            raise ValueError(f"facility_cap_kw must be finite and > 0 for power_capped, got {facility_cap_kw}")
        capped_cap = facility_cap_kw / pue_arr
        safe_cap = np.minimum(nominal_capacity_kw, capped_cap)
        return safe_cap
    else:
        raise ValueError(f"Unsupported facility model kind: {kind}")


class HeatGuardScheduler:
    """Deployable HeatGuard rolling scheduler adapter.

    In production calibrated mode, requires verified V3 artifact loading from disk:
    - calibration_artifact_dir
    - expected_manifest_sha256
    - repository_root
    Rejects directly supplied calibration_result, raw numeric margins, manual objects,
    duck typing, missing arguments, or unverified artifacts.

    Attributes:
        facility_config: FacilityConfig containing thermal scenario and capacity rules.
        margin_mode: HeatGuardMarginMode ("calibrated", "fixed", "none").
        forecast_horizon_hours: Horizon for each rolling replan (default 24).
        commit_hours: Number of hours committed per replan (default 1).
        objective: Primary evaluation objective ("carbon_first" or "cost_first").
    """

    def __init__(
        self,
        facility_config: FacilityConfig,
        margin_mode: HeatGuardMarginMode | str = HeatGuardMarginMode.calibrated,
        forecast_horizon_hours: int = 24,
        commit_hours: int = 1,
        fixed_pue_margin: float = 0.10,
        objective: str = "carbon_first",
        calibration_artifact_dir: Path | str | None = None,
        expected_manifest_sha256: str | None = None,
        repository_root: Path | str | None = None,
        calibration_result: Any = None,
    ) -> None:
        if not isinstance(facility_config, FacilityConfig):
            raise TypeError("facility_config must be FacilityConfig instance")

        mode = HeatGuardMarginMode(margin_mode) if isinstance(margin_mode, str) else margin_mode
        if mode not in HeatGuardMarginMode:
            raise ValueError(f"Invalid margin_mode: {margin_mode}")

        if forecast_horizon_hours != 24:
            raise ValueError(f"forecast_horizon_hours must be 24 per contract, got {forecast_horizon_hours}")
        if commit_hours != 1:
            raise ValueError(f"commit_hours must be 1 per contract, got {commit_hours}")

        if objective not in ("carbon_first", "cost_first"):
            raise ValueError(f"objective must be 'carbon_first' or 'cost_first', got '{objective}'")

        self.facility_config = facility_config
        self.margin_mode = mode
        self.forecast_horizon_hours = forecast_horizon_hours
        self.commit_hours = commit_hours
        self.objective = objective

        if mode == HeatGuardMarginMode.calibrated:
            if calibration_result is not None:
                raise TypeError(
                    "calibrated mode rejects directly supplied calibration_result; "
                    "production API requires loading verified V3 artifact via "
                    "calibration_artifact_dir, expected_manifest_sha256, and repository_root"
                )
            if calibration_artifact_dir is None:
                raise ValueError("calibration_artifact_dir is required in calibrated mode")
            if expected_manifest_sha256 is None:
                raise ValueError("expected_manifest_sha256 is required in calibrated mode")
            if repository_root is None:
                raise ValueError("repository_root is required in calibrated mode")

            # Strict production frozen manifest check
            validate_sha256_hex(expected_manifest_sha256, "expected_manifest_sha256")
            if expected_manifest_sha256 != FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256:
                raise ValueError(
                    f"Production calibrated HeatGuard requires frozen V3 manifest hash "
                    f"'{FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256}', got '{expected_manifest_sha256}'. "
                    "Caller-supplied alternative or re-signed manifest hashes are rejected in production."
                )

            # Load strictly through V3 artifact loader
            cal_res, manifest_data = load_calibration_artifact(
                artifact_dir=calibration_artifact_dir,
                expected_manifest_sha256=expected_manifest_sha256,
                repository_root=repository_root,
            )

            if cal_res.is_fallback:
                raise ValueError("Production calibrated HeatGuard rejects fallback calibration results")
            if not math.isclose(float(cal_res.q), 0.90, abs_tol=1e-6):
                raise ValueError(f"CalibrationResult q must be 0.90, got {cal_res.q}")
            if str(cal_res.quantile_method) != "higher":
                raise ValueError(f"CalibrationResult quantile_method must be 'higher', got {cal_res.quantile_method}")
            if str(cal_res.facility_scenario_id) != "medium":
                raise ValueError(f"CalibrationResult facility_scenario_id must be 'medium', got {cal_res.facility_scenario_id}")

            m = float(cal_res.calibrated_margin)
            if not math.isfinite(m) or m < 0.0:
                raise ValueError(f"Calibrated margin must be finite and non-negative, got {m}")
            self.applied_margin = m
            self.fixed_pue_margin = 0.10

        elif mode == HeatGuardMarginMode.fixed:
            if isinstance(fixed_pue_margin, bool) or not isinstance(fixed_pue_margin, (int, float)):
                raise TypeError(f"fixed_pue_margin must be numeric float, got {type(fixed_pue_margin).__name__}")
            fixed_val = float(fixed_pue_margin)
            if not math.isfinite(fixed_val) or fixed_val < 0.0 or not math.isclose(fixed_val, 0.10, abs_tol=1e-6):
                raise ValueError(f"fixed_pue_margin must be finite and exactly 0.10, got {fixed_val}")
            self.applied_margin = 0.10
            self.fixed_pue_margin = 0.10

        elif mode == HeatGuardMarginMode.none:
            self.applied_margin = 0.0
            self.fixed_pue_margin = 0.10

        else:
            raise ValueError(f"Unknown margin mode {mode}")

    @property
    def policy_name(self) -> str:
        return f"heatguard_{self.margin_mode.value}"

    @property
    def policy_version(self) -> str:
        return "1.0"

    @property
    def deployable(self) -> bool:
        return True

    def schedule_rolling(
        self,
        workload_df: pd.DataFrame,
        temperature_forecast_provider: Callable[[datetime, int], np.ndarray],
        market_forecast_provider: Callable[[datetime, int], ForecastResult],
        window_start_utc: datetime,
        total_window_hours: int = 120,
        nominal_constraints: SchedulingConstraints | None = None,
    ) -> HeatGuardRollingResult:
        """Run rolling commit loop over total_window_hours.

        Parameters:
            workload_df: Canonical workload trace DataFrame.
            temperature_forecast_provider: Callable(origin_utc, horizon_hours) -> 1D array of 24 forecast temperatures (degrees C).
            market_forecast_provider: Callable(origin_utc, horizon_hours) -> ForecastResult for price/carbon.
            window_start_utc: UTC timestamp of simulation start.
            total_window_hours: Total window length to schedule (default 120).
            nominal_constraints: Nominal constraints (power cap, max concurrent jobs).
        """
        validate_heatguard_workload_df(workload_df)

        if window_start_utc.tzinfo is None or window_start_utc.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError(f"window_start_utc must be explicit UTC, got {window_start_utc}")
        if total_window_hours <= 0:
            raise ValueError(f"total_window_hours must be > 0, got {total_window_hours}")

        trace_id = str(workload_df["workload_trace_id"].iloc[0])

        if nominal_constraints is None:
            nominal_constraints = SchedulingConstraints(
                max_cluster_power_kw=self.facility_config.nominal_compute_capacity_kw,
                max_concurrent_jobs=16,
                allow_preemption=True,
            )

        # Track job states across rolling replans
        # job_id -> {remaining_req: int, arrival: int, deadline: int, energy_per_unit: float, power_per_unit: float}
        jobs_state: dict[str, dict[str, Any]] = {}
        for _, row in workload_df.iterrows():
            jid = str(row["job_id"])
            req = int(row["processing_requirement"])
            arr = int(row["arrival_offset_hours"])
            dead = int(row["deadline_offset_hours"])
            energy = float(row["energy_kwh"])
            unit_power = energy / req
            unit_energy = energy / req
            jobs_state[jid] = {
                "remaining_req": req,
                "arrival": arr,
                "deadline": dead,
                "unit_power_kw": unit_power,
                "unit_energy_kwh": unit_energy,
                "workload_row": row.to_dict(),
            }

        committed_allocations: list[ScheduledJobAllocation] = []
        steps: list[HeatGuardCommitmentStep] = []
        overall_unmet_deadlines: set[str] = set()

        # Step through each hour: origin t = 0 .. total_window_hours - 1
        for origin_h in range(total_window_hours):
            origin_utc = window_start_utc + timedelta(hours=origin_h)

            # 1. Check if all work already completed
            active_jobs = {
                jid: info for jid, info in jobs_state.items() if info["remaining_req"] > 0
            }

            # Check for any expired jobs that reached deadline before completing
            for jid, info in active_jobs.items():
                if origin_h >= info["deadline"]:
                    overall_unmet_deadlines.add(jid)

            # 2 & 3. Temperature & Market Forecast validation
            raw_temp_fc = temperature_forecast_provider(origin_utc, self.forecast_horizon_hours)
            raw_mkt_fc = market_forecast_provider(origin_utc, self.forecast_horizon_hours)

            temp_arr, mkt_fc = validate_heatguard_forecast_inputs(
                origin_utc=origin_utc,
                forecast_horizon_hours=self.forecast_horizon_hours,
                temperature_forecast=raw_temp_fc,
                market_forecast=raw_mkt_fc,
            )

            # 4. Forecast PUE
            f_pue = pue_from_temperature(temp_arr, self.facility_config.thermal_scenario)
            f_pue_arr = np.asarray(f_pue, dtype=np.float64)

            # 5. pue_safe
            pue_safe = compute_safe_pue(
                f_pue_arr,
                safety_margin=self.applied_margin,
                max_pue=self.facility_config.thermal_scenario.max_pue,
            )
            pue_safe_arr = np.asarray(pue_safe, dtype=np.float64)

            # 6. Safe capacity vector
            safe_cap = compute_safe_capacity_vector(
                nominal_capacity_kw=self.facility_config.nominal_compute_capacity_kw,
                pue_safe=pue_safe_arr,
                facility_model_kind=self.facility_config.model_kind,
                facility_cap_kw=self.facility_config.facility_power_cap_kw,
            )

            # 7. Identify eligible, released, unfinished work for this 24h horizon
            # Released-job information set rule:
            # At rolling origin t (origin_h), optimize only jobs satisfying:
            #   arrival_offset_hours <= t
            #   remaining_requirement > 0
            #   deadline_offset_hours > t
            window_eligible_jobs: list[dict[str, Any]] = []
            horizon_end_h = origin_h + self.forecast_horizon_hours
            step_unmet: list[str] = list(overall_unmet_deadlines)
            job_required_in_window: dict[str, int] = {}

            for jid, info in jobs_state.items():
                if info["remaining_req"] <= 0:
                    continue
                arr = info["arrival"]
                dead = info["deadline"]

                if dead <= origin_h:
                    if jid not in step_unmet:
                        step_unmet.append(jid)
                    continue

                # STRICT INFORMATION SET BARRIER:
                # Do NOT plan not-yet-released jobs (arr > origin_h)
                if arr > origin_h:
                    continue

                # Beyond-horizon deadline handling:
                # If deadline > horizon_end_h:
                #   future_slots_after_horizon = max(0, deadline - horizon_end_h)
                #   required_in_current_window = max(0, remaining_req - future_slots_after_horizon)
                rem_req = info["remaining_req"]
                if dead > horizon_end_h:
                    future_slots = dead - horizon_end_h
                    req_in_window = max(0, rem_req - future_slots)
                    job_required_in_window[jid] = req_in_window
                    window_deadline_offset = self.forecast_horizon_hours
                    window_effective_req = req_in_window
                else:
                    req_in_window = rem_req
                    job_required_in_window[jid] = req_in_window
                    window_deadline_offset = dead - origin_h
                    window_effective_req = rem_req

                if window_effective_req == 0:
                    # Job has no mandatory current-window allocation; carry forward without entering window optimization
                    continue

                window_arr_offset = 0  # Already released at origin_h

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

            # 8. Replan window with base policy adapter if work exists
            committed_this_hour: list[ScheduledJobAllocation] = []
            is_step_feasible = (len(step_unmet) == 0)

            if window_eligible_jobs:
                replan_df = pd.DataFrame(window_eligible_jobs)

                if self.objective == "carbon_first":
                    base_policy: SchedulingPolicy = CarbonFirstGreedyPolicy()
                else:
                    base_policy = CostFirstGreedyPolicy()

                # Scale forecast points by safe PUE for thermal awareness
                scaled_points: list[ForecastPoint] = []
                for idx, pt in enumerate(mkt_fc.points):
                    scaled_points.append(
                        ForecastPoint(
                            timestamp_utc=pt.timestamp_utc,
                            horizon_hours=pt.horizon_hours,
                            predicted_price_usd_per_mwh=pt.predicted_price_usd_per_mwh * pue_safe_arr[idx],
                            predicted_carbon_g_per_kwh=pt.predicted_carbon_g_per_kwh * pue_safe_arr[idx],
                        )
                    )
                scaled_fc = ForecastResult(
                    origin_timestamp_utc=mkt_fc.origin_timestamp_utc,
                    points=scaled_points,
                    model_name=f"{mkt_fc.model_name}_heatguard",
                    model_version=mkt_fc.model_version,
                )

                adapter = HeatAwareCapacityAdapter(
                    base_policy=base_policy,
                    hourly_effective_capacity_kw=safe_cap,
                )

                window_result = adapter.schedule(replan_df, scaled_fc, nominal_constraints)

                # Verify actual in-window allocations meet each required-in-window amount
                in_window_alloc_counts: dict[str, int] = {j["job_id"]: 0 for j in window_eligible_jobs}
                for alloc in window_result.allocations:
                    in_window_alloc_counts[alloc.job_id] += 1

                for jid, required_units in job_required_in_window.items():
                    actual_units = in_window_alloc_counts.get(jid, 0)
                    if actual_units < required_units:
                        is_step_feasible = False
                        if jid not in step_unmet:
                            step_unmet.append(jid)

                if not window_result.is_feasible:
                    is_step_feasible = False
                    for uj in window_result.unmet_deadlines:
                        if uj not in step_unmet:
                            step_unmet.append(uj)

                # 9. Commit only allocations for the next one-hour interval (offset 0 in window)
                for alloc in window_result.allocations:
                    if alloc.allocated_hour_offset == 0:
                        jid = alloc.job_id
                        # Double-check that job has remaining work
                        if jobs_state[jid]["remaining_req"] > 0:
                            # Commit allocation at global offset origin_h
                            global_alloc = ScheduledJobAllocation(
                                job_id=jid,
                                allocated_hour_offset=origin_h,
                                execution_power_kw=alloc.execution_power_kw,
                                allocated_energy_kwh=alloc.allocated_energy_kwh,
                            )
                            committed_this_hour.append(global_alloc)
                            committed_allocations.append(global_alloc)
                            # Decrement remaining requirement
                            jobs_state[jid]["remaining_req"] -= 1

            # Update overall unmet deadlines
            for jid in step_unmet:
                overall_unmet_deadlines.add(jid)

            active_remaining = {
                jid: info["remaining_req"] for jid, info in jobs_state.items() if info["remaining_req"] > 0
            }

            step = HeatGuardCommitmentStep(
                replan_origin_hour=origin_h,
                replan_timestamp_utc=origin_utc,
                committed_hour_offset=origin_h,
                committed_allocations=committed_this_hour,
                forecast_pue=[float(x) for x in f_pue_arr],
                pue_safe=[float(x) for x in pue_safe_arr],
                safe_capacity_kw=[float(x) for x in safe_cap],
                active_jobs_remaining=active_remaining,
                is_projected_feasible=is_step_feasible,
                unmet_deadlines=sorted(list(set(step_unmet))),
            )
            steps.append(step)

        # Final check across all jobs
        for jid, info in jobs_state.items():
            if info["remaining_req"] > 0:
                overall_unmet_deadlines.add(jid)

        is_overall_feasible = (len(overall_unmet_deadlines) == 0) and (
            len(committed_allocations) == int(workload_df["processing_requirement"].sum())
        )

        return HeatGuardRollingResult(
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            workload_trace_id=trace_id,
            total_horizon_hours=total_window_hours,
            commit_interval_hours=self.commit_hours,
            allocations=committed_allocations,
            steps=steps,
            is_feasible=is_overall_feasible,
            unmet_deadlines=sorted(list(overall_unmet_deadlines)),
            margin_mode=self.margin_mode,
            applied_margin=self.applied_margin,
        )
