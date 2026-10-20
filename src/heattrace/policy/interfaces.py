"""Typed policy and forecasting interface stubs and test fixtures for HeatTrace P3-04."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
import pandas as pd


@dataclass(frozen=True)
class ForecastPoint:
    """A single forecasted hour point for price and carbon intensity."""
    timestamp_utc: datetime
    horizon_hours: int
    predicted_price_usd_per_mwh: float
    predicted_carbon_g_per_kwh: float


@dataclass(frozen=True)
class ForecastResult:
    """Forecast output from a ForecastProvider with strict origin and horizon semantics."""
    origin_timestamp_utc: datetime
    points: list[ForecastPoint]
    model_name: str
    model_version: str

    def to_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "origin_timestamp_utc": self.origin_timestamp_utc,
                "timestamp_utc": p.timestamp_utc,
                "horizon_hours": p.horizon_hours,
                "predicted_price_usd_per_mwh": p.predicted_price_usd_per_mwh,
                "predicted_carbon_g_per_kwh": p.predicted_carbon_g_per_kwh,
                "model_name": self.model_name,
                "model_version": self.model_version,
            }
            for p in self.points
        ]
        return pd.DataFrame(rows)


@runtime_checkable
class ForecastProvider(Protocol):
    """Protocol for electricity price and carbon intensity forecasting."""

    def forecast(
        self,
        origin_timestamp_utc: datetime,
        horizon_hours: int,
        *,
        history_df: pd.DataFrame | None = None,
    ) -> ForecastResult:
        """Produce forecast for [origin_timestamp_utc, origin_timestamp_utc + horizon_hours).
        
        Must never expose realized future values as forecasts.
        """
        ...


@dataclass(frozen=True)
class SchedulingConstraints:
    """System-level constraints for workload scheduling."""
    max_cluster_power_kw: float
    max_concurrent_jobs: int = 16
    allow_preemption: bool = True


@dataclass(frozen=True)
class ScheduledJobAllocation:
    """Allocation of a job to a specific hourly execution interval."""
    job_id: str
    allocated_hour_offset: int
    execution_power_kw: float
    allocated_energy_kwh: float


@dataclass(frozen=True)
class ScheduleResult:
    """Complete schedule output produced by a SchedulingPolicy."""
    policy_name: str
    policy_version: str
    workload_trace_id: str
    window_duration_hours: int
    allocations: list[ScheduledJobAllocation]
    total_cost_usd: float | None = None
    total_carbon_emissions_kg: float | None = None
    is_feasible: bool = True
    unmet_deadlines: list[str] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "policy_name": self.policy_name,
                "policy_version": self.policy_version,
                "workload_trace_id": self.workload_trace_id,
                "job_id": a.job_id,
                "allocated_hour_offset": a.allocated_hour_offset,
                "execution_power_kw": a.execution_power_kw,
                "allocated_energy_kwh": a.allocated_energy_kwh,
            }
            for a in self.allocations
        ]
        return pd.DataFrame(rows)


@runtime_checkable
class SchedulingPolicy(Protocol):
    """Protocol for workload scheduling policies evaluated during heatwave regimes."""

    @property
    def policy_name(self) -> str:
        ...

    @property
    def policy_version(self) -> str:
        ...

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        """Compute job allocation schedule over the forecast window."""
        ...


# =========================================================================
# Test Fixtures & Stub Implementations (Labeled as Test Stubs)
# =========================================================================

class FixturePersistenceForecastProvider:
    """Deterministic forecast stub for testing that emits static/persistence forecasts.
    
    LABEL: Test Stub Only (Not a real P4 forecasting model).
    """

    def __init__(self, default_price: float = 45.0, default_carbon: float = 220.0):
        self.default_price = default_price
        self.default_carbon = default_carbon

    def forecast(
        self,
        origin_timestamp_utc: datetime,
        horizon_hours: int,
        *,
        history_df: pd.DataFrame | None = None,
    ) -> ForecastResult:
        if origin_timestamp_utc.tzinfo is None:
            raise ValueError("origin_timestamp_utc must be timezone-aware")
        if horizon_hours <= 0:
            raise ValueError("horizon_hours must be > 0")

        price = self.default_price
        carbon = self.default_carbon

        if history_df is not None and not history_df.empty:
            if "price_usd_per_mwh" in history_df and not history_df["price_usd_per_mwh"].dropna().empty:
                price = float(history_df["price_usd_per_mwh"].dropna().iloc[-1])
            if "carbon_g_per_kwh" in history_df and not history_df["carbon_g_per_kwh"].dropna().empty:
                carbon = float(history_df["carbon_g_per_kwh"].dropna().iloc[-1])

        points: list[ForecastPoint] = []
        for h in range(horizon_hours):
            ts = origin_timestamp_utc + pd.Timedelta(hours=h)
            points.append(
                ForecastPoint(
                    timestamp_utc=ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts,
                    horizon_hours=h,
                    predicted_price_usd_per_mwh=price,
                    predicted_carbon_g_per_kwh=carbon,
                )
            )

        return ForecastResult(
            origin_timestamp_utc=origin_timestamp_utc,
            points=points,
            model_name="FixturePersistenceForecast",
            model_version="0.1-stub",
        )


class FixtureEarliestDeadlineFirstPolicy:
    """Earliest-Deadline-First (EDF) greedy scheduling policy stub for testing.
    
    LABEL: Test Stub Only (Not a real P4 optimization policy).
    """

    @property
    def policy_name(self) -> str:
        return "FixtureEDFGreedy"

    @property
    def policy_version(self) -> str:
        return "0.1-stub"

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        if workload_df.empty:
            raise ValueError("workload_df cannot be empty")

        trace_id = str(workload_df["workload_trace_id"].iloc[0])
        window_duration = len(forecast.points)

        allocations: list[ScheduledJobAllocation] = []
        # Sort jobs by arrival then deadline
        sorted_jobs = workload_df.sort_values(by=["arrival_offset_hours", "deadline_offset_hours"])

        for _, job in sorted_jobs.iterrows():
            jid = str(job["job_id"])
            arr = int(job["arrival_offset_hours"])
            dead = int(job["deadline_offset_hours"])
            proc = int(job["processing_requirement"])
            energy = float(job["energy_kwh"])
            pwr = energy / proc

            # Allocate immediately from arrival for proc hours
            for hr in range(arr, min(arr + proc, window_duration)):
                allocations.append(
                    ScheduledJobAllocation(
                        job_id=jid,
                        allocated_hour_offset=hr,
                        execution_power_kw=round(pwr, 2),
                        allocated_energy_kwh=round(pwr, 2),
                    )
                )

        return ScheduleResult(
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            workload_trace_id=trace_id,
            window_duration_hours=window_duration,
            allocations=allocations,
            is_feasible=True,
        )
