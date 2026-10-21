"""Common scheduling helpers, tie-breaking, and candidate-hour evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd

from heattrace.policy.interfaces import ForecastResult, ScheduledJobAllocation, SchedulingConstraints


def normalize_series_min_max(series: pd.Series) -> pd.Series:
    """Min-max normalize a series over the horizon to [0, 1].

    If series has zero range (max == min), return neutral 0.5 consistently.
    """
    s_min = series.min()
    s_max = series.max()
    if pd.isna(s_min) or pd.isna(s_max) or s_max == s_min:
        return pd.Series(0.5, index=series.index)
    return (series - s_min) / (s_max - s_min)


def sort_workload_jobs_deterministically(workload_df: pd.DataFrame) -> pd.DataFrame:
    """Sort workload jobs deterministically:
    1. Earliest deadline
    2. Higher priority (descending)
    3. Earlier arrival
    4. job_id (ascending)
    """
    df = workload_df.copy()
    # Ensure correct types
    df["deadline_offset_hours"] = df["deadline_offset_hours"].astype(int)
    df["priority"] = df["priority"].astype(int)
    df["arrival_offset_hours"] = df["arrival_offset_hours"].astype(int)
    df["job_id"] = df["job_id"].astype(str)

    # Sort with priority descending (higher priority first)
    return df.sort_values(
        by=["deadline_offset_hours", "priority", "arrival_offset_hours", "job_id"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)


@dataclass
class ClusterState:
    """Tracks per-hour cluster power and concurrency."""
    window_duration_hours: int
    max_cluster_power_kw: float
    max_concurrent_jobs: int

    def __post_init__(self):
        self.hourly_power = [0.0] * self.window_duration_hours
        self.hourly_jobs: list[set[str]] = [set() for _ in range(self.window_duration_hours)]

    def can_allocate(self, hour: int, job_id: str, power_kw: float) -> bool:
        """Check if an allocation of power_kw to job_id in hour is feasible."""
        if hour < 0 or hour >= self.window_duration_hours:
            return False
        if self.hourly_power[hour] + power_kw > self.max_cluster_power_kw + 1e-4:
            return False
        # Concurrency: if job already runs in this hour, concurrency doesn't increase
        if job_id not in self.hourly_jobs[hour]:
            if len(self.hourly_jobs[hour]) >= self.max_concurrent_jobs:
                return False
        return True

    def commit(self, hour: int, job_id: str, power_kw: float) -> None:
        """Commit an allocation."""
        self.hourly_power[hour] += power_kw
        self.hourly_jobs[hour].add(job_id)
