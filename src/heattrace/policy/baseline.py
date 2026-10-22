"""Baseline reference policy for HeatTrace P5.5.

Schedules jobs on an earliest-arrival / as-soon-as-possible (ASAP) basis
while respecting cluster capacity and concurrency constraints.
Serves as an authentic baseline/reference comparator.
"""

from __future__ import annotations

import pandas as pd

from heattrace.policy.greedy import _schedule_greedy_with_scoring
from heattrace.policy.interfaces import (
    ForecastResult,
    ScheduleResult,
    SchedulingConstraints,
    SchedulingPolicy,
)


class BaselineReferencePolicy:
    """Authentic baseline reference policy scheduling as soon as possible (ASAP / greedy earliest hour)."""

    @property
    def policy_name(self) -> str:
        return "baseline_reference"

    @property
    def policy_version(self) -> str:
        return "1.0"

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        # Score increases strictly with hour offset h, prioritizing earliest feasible hours
        return _schedule_greedy_with_scoring(
            workload_df,
            forecast,
            constraints,
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            hour_score_fn=lambda h, norm_p, norm_c: float(h),
        )
