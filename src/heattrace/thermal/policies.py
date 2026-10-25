"""P6 thermal scheduling policy wrappers and factories.

Implements the four Phase 3 policies:
1. static_unaware (deployable=true)
2. capacity_aware (deployable=true)
3. full_thermal_aware (deployable=true)
4. oracle_full_thermal_aware (deployable=false)
"""

from __future__ import annotations

import copy
import math
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.greedy import CarbonFirstGreedyPolicy, CostFirstGreedyPolicy
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduleResult,
    SchedulingConstraints,
    SchedulingPolicy,
)
from heattrace.thermal.scheduler import HeatAwareCapacityAdapter


REQUIRED_FACILITY_COLUMNS: tuple[str, ...] = (
    "timestamp_utc",
    "pue",
    "effective_compute_capacity_kw",
    "source_context",
)

REQUIRED_REALIZED_MARKET_COLUMNS: tuple[str, ...] = (
    "timestamp_utc",
    "price_usd_per_mwh",
    "carbon_g_per_kwh",
)


def _validate_facility_state(
    facility_df: pd.DataFrame,
    *,
    expected_horizon_hours: int | None = None,
    expected_timestamps: list[Any] | None = None,
    expected_source_context: str | None = None,
) -> None:
    """Validate facility state DataFrame for policy consumption."""
    if not isinstance(facility_df, pd.DataFrame):
        raise TypeError(f"facility_state must be a pd.DataFrame, got {type(facility_df).__name__}")
    if facility_df.empty:
        raise ValueError("facility_state cannot be empty")

    missing = set(REQUIRED_FACILITY_COLUMNS) - set(facility_df.columns)
    if missing:
        raise ValueError(f"facility_state missing required columns: {sorted(missing)}")

    # Check source_context
    contexts = facility_df["source_context"].unique()
    if len(contexts) != 1:
        raise ValueError(f"facility_state has mixed or empty source_context values: {contexts}")
    actual_context = str(contexts[0])

    if expected_source_context is not None:
        if actual_context != expected_source_context:
            raise ValueError(
                f"Invalid facility state source_context '{actual_context}'. Expected '{expected_source_context}'"
            )

    # Check finite and valid PUE and capacity
    pue_arr = np.asarray(facility_df["pue"], dtype=float)
    if not np.all(np.isfinite(pue_arr)):
        raise ValueError("facility_state pue column contains NaN or Inf values")
    if np.any(pue_arr < 1.0):
        raise ValueError("facility_state pue values cannot be less than 1.0")

    cap_arr = np.asarray(facility_df["effective_compute_capacity_kw"], dtype=float)
    if not np.all(np.isfinite(cap_arr)):
        raise ValueError("facility_state effective_compute_capacity_kw contains NaN or Inf values")
    if np.any(cap_arr <= 0.0):
        raise ValueError("facility_state effective_compute_capacity_kw must be strictly positive")

    # Check length
    if expected_horizon_hours is not None and len(facility_df) != expected_horizon_hours:
        raise ValueError(
            f"facility_state length ({len(facility_df)}) != expected horizon ({expected_horizon_hours})"
        )

    # Check timestamp alignment if provided
    if expected_timestamps is not None:
        actual_ts = list(facility_df["timestamp_utc"])
        if len(actual_ts) != len(expected_timestamps):
            raise ValueError(
                f"facility_state timestamp count ({len(actual_ts)}) != forecast timestamp count ({len(expected_timestamps)})"
            )
        for i, (act, exp) in enumerate(zip(actual_ts, expected_timestamps)):
            if act != exp:
                raise ValueError(
                    f"facility_state timestamp at index {i} ({act}) does not match forecast timestamp ({exp})"
                )


def _validate_realized_market_state(
    market_df: pd.DataFrame,
    *,
    expected_horizon_hours: int | None = None,
    expected_timestamps: list[Any] | None = None,
) -> None:
    """Validate realized market state DataFrame (price and carbon intensity)."""
    if not isinstance(market_df, pd.DataFrame):
        raise TypeError(f"realized_market_state must be a pd.DataFrame, got {type(market_df).__name__}")
    if market_df.empty:
        raise ValueError("realized_market_state cannot be empty")

    missing = set(REQUIRED_REALIZED_MARKET_COLUMNS) - set(market_df.columns)
    if missing:
        raise ValueError(f"realized_market_state missing required columns: {sorted(missing)}")

    ts = market_df["timestamp_utc"]
    if ts.isna().any():
        raise ValueError("realized_market_state contains null timestamps")
    if not hasattr(ts.dt, "tz") or ts.dt.tz is None:
        raise ValueError("realized_market_state timestamp_utc must be timezone-aware UTC")
    tz_str = str(ts.dt.tz)
    if tz_str not in ("UTC", "datetime.timezone.utc"):
        raise ValueError(f"realized_market_state timestamp_utc timezone must be UTC, got {tz_str}")

    if not ts.is_monotonic_increasing:
        raise ValueError("realized_market_state timestamp_utc must be strictly monotonically increasing")
    if ts.duplicated().any():
        raise ValueError("realized_market_state timestamp_utc contains duplicate timestamps")

    # Hourly contiguity
    for i in range(len(ts)):
        t = ts.iloc[i]
        if t.minute != 0 or t.second != 0 or t.microsecond != 0:
            raise ValueError(f"realized_market_state timestamp at row {i} ({t}) is not hour-aligned")
        if i > 0:
            prev = ts.iloc[i - 1]
            diff = (t - prev).total_seconds()
            if diff != 3600.0:
                raise ValueError(
                    f"realized_market_state non-contiguous hourly interval between row {i-1} ({prev}) and {i} ({t})"
                )

    if expected_horizon_hours is not None and len(market_df) != expected_horizon_hours:
        raise ValueError(
            f"realized_market_state length ({len(market_df)}) != expected horizon ({expected_horizon_hours})"
        )

    if expected_timestamps is not None:
        actual_ts = list(ts)
        if len(actual_ts) != len(expected_timestamps):
            raise ValueError(
                f"realized_market_state timestamp count ({len(actual_ts)}) != expected timestamp count ({len(expected_timestamps)})"
            )
        for i, (act, exp) in enumerate(zip(actual_ts, expected_timestamps)):
            if act != exp:
                raise ValueError(
                    f"realized_market_state timestamp at index {i} ({act}) does not match expected timestamp ({exp})"
                )

    # Validate price: finite numeric; negative prices permitted
    price_s = market_df["price_usd_per_mwh"]
    if price_s.isna().any():
        raise ValueError("realized_market_state price_usd_per_mwh contains missing/NaN values")
    try:
        price_arr = np.asarray(price_s, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"realized_market_state price_usd_per_mwh must be numeric: {exc}") from exc
    if not np.all(np.isfinite(price_arr)):
        raise ValueError("realized_market_state price_usd_per_mwh contains non-finite values (NaN/Inf)")

    # Validate carbon: finite numeric and non-negative
    carbon_s = market_df["carbon_g_per_kwh"]
    if carbon_s.isna().any():
        raise ValueError("realized_market_state carbon_g_per_kwh contains missing/NaN values")
    try:
        carbon_arr = np.asarray(carbon_s, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"realized_market_state carbon_g_per_kwh must be numeric: {exc}") from exc
    if not np.all(np.isfinite(carbon_arr)):
        raise ValueError("realized_market_state carbon_g_per_kwh contains non-finite values (NaN/Inf)")
    if np.any(carbon_arr < 0.0):
        raise ValueError("realized_market_state carbon_g_per_kwh cannot contain negative values")


def _validate_schedule_workload_accounting(
    result: ScheduleResult,
    workload_df: pd.DataFrame,
    horizon: int,
) -> None:
    """Validate completeness, uniqueness, and feasibility accounting for schedule results."""
    workload_jobs = {str(row["job_id"]): row for _, row in workload_df.iterrows()}
    seen_pairs: set[tuple[str, int]] = set()
    alloc_count_per_job: dict[str, int] = {jid: 0 for jid in workload_jobs}

    for a in result.allocations:
        jid = str(a.job_id)
        if jid not in workload_jobs:
            raise ValueError(f"Schedule allocation contains unknown job_id: '{jid}'")

        h = a.allocated_hour_offset
        if h < 0 or h >= horizon:
            raise ValueError(f"Job '{jid}' allocation hour {h} out of horizon [0, {horizon})")

        pair = (jid, h)
        if pair in seen_pairs:
            raise ValueError(f"Job '{jid}' has duplicate allocation at hour {h}")
        seen_pairs.add(pair)

        job_info = workload_jobs[jid]
        arr = int(job_info["arrival_offset_hours"])
        dead = int(job_info["deadline_offset_hours"])

        if h < arr:
            raise ValueError(f"Job '{jid}' allocated at hour {h} before arrival {arr}")
        if h >= dead:
            raise ValueError(f"Job '{jid}' allocated at hour {h} at/after deadline {dead}")

        alloc_count_per_job[jid] += 1

    # Check completeness
    for jid, job_info in workload_jobs.items():
        req = int(job_info["processing_requirement"])
        actual_alloc = alloc_count_per_job[jid]
        if actual_alloc < req:
            # Must appear in unmet_deadlines
            if jid not in result.unmet_deadlines:
                raise ValueError(
                    f"Job '{jid}' is incomplete ({actual_alloc}/{req} slots) but missing from unmet_deadlines"
                )
            if result.is_feasible:
                raise ValueError(
                    f"Schedule marked feasible but job '{jid}' is incomplete ({actual_alloc}/{req} slots)"
                )
        elif actual_alloc > req:
            raise ValueError(
                f"Job '{jid}' has more allocations ({actual_alloc}) than required ({req})"
            )


class StaticUnawarePolicy:
    """Static temperature-unaware deployable scheduling policy.

    ID: static_unaware
    deployable: True
    Uses nominal SchedulingConstraints.
    Receives no forecast or realized temperature, PUE, or effective capacity.
    """

    def __init__(self, objective: str = "carbon_first") -> None:
        if objective == "carbon_first":
            self.base_policy: SchedulingPolicy = CarbonFirstGreedyPolicy()
        elif objective == "cost_first":
            self.base_policy = CostFirstGreedyPolicy()
        else:
            raise ValueError(f"Unsupported objective '{objective}'. Expected 'carbon_first' or 'cost_first'")
        self.objective = objective

    @property
    def policy_id(self) -> str:
        return "static_unaware"

    @property
    def policy_name(self) -> str:
        return "static_unaware"

    @property
    def policy_version(self) -> str:
        return "1.0"

    @property
    def deployable(self) -> bool:
        return True

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        if workload_df.empty:
            raise ValueError("workload_df cannot be empty")
        horizon = len(forecast.points)

        res = self.base_policy.schedule(workload_df, forecast, constraints)
        final_res = ScheduleResult(
            policy_name=self.policy_id,
            policy_version=self.policy_version,
            workload_trace_id=res.workload_trace_id,
            window_duration_hours=res.window_duration_hours,
            allocations=res.allocations,
            total_cost_usd=res.total_cost_usd,
            total_carbon_emissions_kg=res.total_carbon_emissions_kg,
            is_feasible=res.is_feasible,
            unmet_deadlines=res.unmet_deadlines,
        )
        _validate_schedule_workload_accounting(final_res, workload_df, horizon)
        return final_res


class CapacityAwarePolicy:
    """Capacity-aware deployable scheduling policy.

    ID: capacity_aware
    deployable: True
    Uses effective capacity derived ONLY from forecast facility state.
    Does not use forecast PUE to change the objective.
    Reuses HeatAwareCapacityAdapter.
    """

    def __init__(
        self,
        forecast_facility_state: pd.DataFrame,
        objective: str = "carbon_first",
    ) -> None:
        _validate_facility_state(
            forecast_facility_state,
            expected_source_context="forecast",
        )
        self.facility_state = forecast_facility_state.copy(deep=True)
        if objective == "carbon_first":
            self.base_policy: SchedulingPolicy = CarbonFirstGreedyPolicy()
        elif objective == "cost_first":
            self.base_policy = CostFirstGreedyPolicy()
        else:
            raise ValueError(f"Unsupported objective '{objective}'. Expected 'carbon_first' or 'cost_first'")
        self.objective = objective

    @property
    def policy_id(self) -> str:
        return "capacity_aware"

    @property
    def policy_name(self) -> str:
        return "capacity_aware"

    @property
    def policy_version(self) -> str:
        return "1.0"

    @property
    def deployable(self) -> bool:
        return True

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        if workload_df.empty:
            raise ValueError("workload_df cannot be empty")
        horizon = len(forecast.points)
        forecast_ts = [p.timestamp_utc for p in forecast.points]

        _validate_facility_state(
            self.facility_state,
            expected_horizon_hours=horizon,
            expected_timestamps=forecast_ts,
            expected_source_context="forecast",
        )

        eff_cap = np.asarray(self.facility_state["effective_compute_capacity_kw"], dtype=float)
        adapter = HeatAwareCapacityAdapter(
            base_policy=self.base_policy,
            hourly_effective_capacity_kw=eff_cap,
        )

        raw_res = adapter.schedule(workload_df, forecast, constraints)
        final_res = ScheduleResult(
            policy_name=self.policy_id,
            policy_version=self.policy_version,
            workload_trace_id=raw_res.workload_trace_id,
            window_duration_hours=raw_res.window_duration_hours,
            allocations=raw_res.allocations,
            total_cost_usd=raw_res.total_cost_usd,
            total_carbon_emissions_kg=raw_res.total_carbon_emissions_kg,
            is_feasible=raw_res.is_feasible,
            unmet_deadlines=raw_res.unmet_deadlines,
        )
        _validate_schedule_workload_accounting(final_res, workload_df, horizon)
        return final_res


class FullThermalAwarePolicy:
    """Full thermal-aware deployable scheduling policy.

    ID: full_thermal_aware
    deployable: True
    Uses forecast facility state only.
    Applies forecast PUE consistently to forecast energy/objective accounting:
    - effective price: price * forecast_pue
    - effective carbon: carbon * forecast_pue
    Uses forecast effective capacity through the existing adapter.
    Does NOT mutate the original ForecastResult.
    """

    def __init__(
        self,
        forecast_facility_state: pd.DataFrame,
        objective: str = "carbon_first",
    ) -> None:
        _validate_facility_state(
            forecast_facility_state,
            expected_source_context="forecast",
        )
        self.facility_state = forecast_facility_state.copy(deep=True)
        if objective == "carbon_first":
            self.base_policy: SchedulingPolicy = CarbonFirstGreedyPolicy()
        elif objective == "cost_first":
            self.base_policy = CostFirstGreedyPolicy()
        else:
            raise ValueError(f"Unsupported objective '{objective}'. Expected 'carbon_first' or 'cost_first'")
        self.objective = objective

    @property
    def policy_id(self) -> str:
        return "full_thermal_aware"

    @property
    def policy_name(self) -> str:
        return "full_thermal_aware"

    @property
    def policy_version(self) -> str:
        return "1.0"

    @property
    def deployable(self) -> bool:
        return True

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        if workload_df.empty:
            raise ValueError("workload_df cannot be empty")
        horizon = len(forecast.points)
        forecast_ts = [p.timestamp_utc for p in forecast.points]

        _validate_facility_state(
            self.facility_state,
            expected_horizon_hours=horizon,
            expected_timestamps=forecast_ts,
            expected_source_context="forecast",
        )

        pue_arr = np.asarray(self.facility_state["pue"], dtype=float)
        eff_cap = np.asarray(self.facility_state["effective_compute_capacity_kw"], dtype=float)

        # Construct new ForecastResult scaled by PUE without mutating original
        scaled_points: list[ForecastPoint] = []
        for i, pt in enumerate(forecast.points):
            scaled_p = pt.predicted_price_usd_per_mwh * pue_arr[i]
            scaled_c = pt.predicted_carbon_g_per_kwh * pue_arr[i]
            scaled_points.append(
                ForecastPoint(
                    timestamp_utc=pt.timestamp_utc,
                    horizon_hours=pt.horizon_hours,
                    predicted_price_usd_per_mwh=scaled_p,
                    predicted_carbon_g_per_kwh=scaled_c,
                )
            )

        scaled_forecast = ForecastResult(
            origin_timestamp_utc=forecast.origin_timestamp_utc,
            points=scaled_points,
            model_name=f"{forecast.model_name}_pue_scaled",
            model_version=forecast.model_version,
        )

        adapter = HeatAwareCapacityAdapter(
            base_policy=self.base_policy,
            hourly_effective_capacity_kw=eff_cap,
        )

        raw_res = adapter.schedule(workload_df, scaled_forecast, constraints)
        final_res = ScheduleResult(
            policy_name=self.policy_id,
            policy_version=self.policy_version,
            workload_trace_id=raw_res.workload_trace_id,
            window_duration_hours=raw_res.window_duration_hours,
            allocations=raw_res.allocations,
            total_cost_usd=raw_res.total_cost_usd,
            total_carbon_emissions_kg=raw_res.total_carbon_emissions_kg,
            is_feasible=raw_res.is_feasible,
            unmet_deadlines=raw_res.unmet_deadlines,
        )
        _validate_schedule_workload_accounting(final_res, workload_df, horizon)
        return final_res


class OracleFullThermalAwarePolicy:
    """Oracle full thermal-aware reference policy.

    ID: oracle_full_thermal_aware
    deployable: False (strictly non-deployable reference policy)
    Requires realized facility state (source_context="realized") AND realized market state.
    Uses realized price and carbon values (not forecast values), scaled by realized PUE,
    and realized effective capacity.
    """

    def __init__(
        self,
        realized_facility_state: pd.DataFrame,
        realized_market_state: pd.DataFrame,
        objective: str = "carbon_first",
    ) -> None:
        _validate_facility_state(
            realized_facility_state,
            expected_source_context="realized",
        )
        _validate_realized_market_state(
            realized_market_state,
            expected_horizon_hours=len(realized_facility_state),
            expected_timestamps=list(realized_facility_state["timestamp_utc"]),
        )
        self.facility_state = realized_facility_state.copy(deep=True)
        self.market_state = realized_market_state.copy(deep=True)
        if objective == "carbon_first":
            self.base_policy: SchedulingPolicy = CarbonFirstGreedyPolicy()
        elif objective == "cost_first":
            self.base_policy = CostFirstGreedyPolicy()
        else:
            raise ValueError(f"Unsupported objective '{objective}'. Expected 'carbon_first' or 'cost_first'")
        self.objective = objective

    @property
    def policy_id(self) -> str:
        return "oracle_full_thermal_aware"

    @property
    def policy_name(self) -> str:
        return "oracle_full_thermal_aware"

    @property
    def policy_version(self) -> str:
        return "1.0"

    @property
    def deployable(self) -> bool:
        return False

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        if workload_df.empty:
            raise ValueError("workload_df cannot be empty")
        horizon = len(forecast.points)
        forecast_ts = [p.timestamp_utc for p in forecast.points]

        # Validate alignment of both facility state and market state against schedule horizon
        _validate_facility_state(
            self.facility_state,
            expected_horizon_hours=horizon,
            expected_timestamps=forecast_ts,
            expected_source_context="realized",
        )
        _validate_realized_market_state(
            self.market_state,
            expected_horizon_hours=horizon,
            expected_timestamps=forecast_ts,
        )

        pue_arr = np.asarray(self.facility_state["pue"], dtype=float)
        eff_cap = np.asarray(self.facility_state["effective_compute_capacity_kw"], dtype=float)
        real_prices = np.asarray(self.market_state["price_usd_per_mwh"], dtype=float)
        real_carbons = np.asarray(self.market_state["carbon_g_per_kwh"], dtype=float)

        # Build internal ForecastResult from realized market values scaled by realized PUE
        # Perfect information hindsight reference
        oracle_points: list[ForecastPoint] = []
        for i in range(horizon):
            ts = forecast_ts[i]
            scaled_p = real_prices[i] * pue_arr[i]
            scaled_c = real_carbons[i] * pue_arr[i]
            oracle_points.append(
                ForecastPoint(
                    timestamp_utc=ts,
                    horizon_hours=i,
                    predicted_price_usd_per_mwh=scaled_p,
                    predicted_carbon_g_per_kwh=scaled_c,
                )
            )

        oracle_forecast = ForecastResult(
            origin_timestamp_utc=forecast.origin_timestamp_utc,
            points=oracle_points,
            model_name="oracle_perfect_hindsight",
            model_version="1.0",
        )

        adapter = HeatAwareCapacityAdapter(
            base_policy=self.base_policy,
            hourly_effective_capacity_kw=eff_cap,
        )

        raw_res = adapter.schedule(workload_df, oracle_forecast, constraints)
        final_res = ScheduleResult(
            policy_name=self.policy_id,
            policy_version=self.policy_version,
            workload_trace_id=raw_res.workload_trace_id,
            window_duration_hours=raw_res.window_duration_hours,
            allocations=raw_res.allocations,
            total_cost_usd=raw_res.total_cost_usd,
            total_carbon_emissions_kg=raw_res.total_carbon_emissions_kg,
            is_feasible=raw_res.is_feasible,
            unmet_deadlines=raw_res.unmet_deadlines,
        )
        _validate_schedule_workload_accounting(final_res, workload_df, horizon)
        return final_res


def get_p6_policy(
    policy_id: str,
    *,
    facility_state: pd.DataFrame | None = None,
    realized_market_state: pd.DataFrame | None = None,
    objective: str = "carbon_first",
) -> SchedulingPolicy:
    """Factory creating one of the 4 approved P6 policies.

    Enforces information boundaries:
    - static_unaware: rejects facility_state and realized_market_state.
    - capacity_aware: requires forecast facility_state; rejects realized_market_state.
    - full_thermal_aware: requires forecast facility_state; rejects realized_market_state.
    - oracle_full_thermal_aware: requires realized facility_state AND realized_market_state.
    """
    if policy_id == "static_unaware":
        if facility_state is not None:
            raise ValueError("static_unaware rejects any supplied facility_state")
        if realized_market_state is not None:
            raise ValueError("static_unaware rejects any supplied realized_market_state")
        return StaticUnawarePolicy(objective=objective)

    elif policy_id == "capacity_aware":
        if realized_market_state is not None:
            raise ValueError("capacity_aware deployable policy rejects realized_market_state")
        if facility_state is None:
            raise ValueError("capacity_aware requires facility_state with source_context='forecast'")
        return CapacityAwarePolicy(forecast_facility_state=facility_state, objective=objective)

    elif policy_id == "full_thermal_aware":
        if realized_market_state is not None:
            raise ValueError("full_thermal_aware deployable policy rejects realized_market_state")
        if facility_state is None:
            raise ValueError("full_thermal_aware requires facility_state with source_context='forecast'")
        return FullThermalAwarePolicy(forecast_facility_state=facility_state, objective=objective)

    elif policy_id == "oracle_full_thermal_aware":
        if facility_state is None:
            raise ValueError("oracle_full_thermal_aware requires facility_state with source_context='realized'")
        if realized_market_state is None:
            raise ValueError("oracle_full_thermal_aware requires realized_market_state")
        return OracleFullThermalAwarePolicy(
            realized_facility_state=facility_state,
            realized_market_state=realized_market_state,
            objective=objective,
        )

    else:
        raise ValueError(
            f"Unknown policy_id '{policy_id}'. Expected one of ['static_unaware', 'capacity_aware', 'full_thermal_aware', 'oracle_full_thermal_aware']"
        )
