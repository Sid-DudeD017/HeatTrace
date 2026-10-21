"""Production greedy scheduling policies: Cost-First, Carbon-First, and Balanced."""

from __future__ import annotations

from typing import Callable
import pandas as pd

from heattrace.policy.common import (
    ClusterState,
    normalize_series_min_max,
    sort_workload_jobs_deterministically,
)
from heattrace.policy.feasibility import validate_schedule_feasibility
from heattrace.policy.interfaces import (
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
    SchedulingPolicy,
)


def _schedule_greedy_with_scoring(
    workload_df: pd.DataFrame,
    forecast: ForecastResult,
    constraints: SchedulingConstraints,
    *,
    policy_name: str,
    policy_version: str,
    hour_score_fn: Callable[[int, float, float], float],
) -> ScheduleResult:
    """Core greedy scheduling implementation using a pluggable hour-scoring function.

    Common behavior:
    - Deterministic job ordering: earliest deadline, higher priority, earlier arrival, job_id.
    - Deterministic candidate-hour tie-breaking: lower score, then earlier hour, then job_id.
    - Non-preemptible jobs: contiguous block minimizing total score.
    - Preemptible jobs: allocate unit-hours by ascending score.
    - Failure handling: validates schedule feasibility; reports unmet jobs/deadlines.
    """
    if workload_df.empty:
        raise ValueError("workload_df cannot be empty")

    trace_id = str(workload_df["workload_trace_id"].iloc[0])
    horizon = len(forecast.points)

    # Compute hourly scores from forecast points
    # Forecast points: horizon_hours, predicted_price_usd_per_mwh, predicted_carbon_g_per_kwh
    prices = pd.Series([p.predicted_price_usd_per_mwh for p in forecast.points])
    carbons = pd.Series([p.predicted_carbon_g_per_kwh for p in forecast.points])

    norm_prices = normalize_series_min_max(prices)
    norm_carbons = normalize_series_min_max(carbons)

    hourly_scores: list[float] = []
    for h in range(horizon):
        p_pt = forecast.points[h]
        # Allow hour_score_fn to use raw or normalized as needed
        score = hour_score_fn(h, norm_prices.iloc[h], norm_carbons.iloc[h])
        hourly_scores.append(score)

    sorted_jobs = sort_workload_jobs_deterministically(workload_df)
    cluster = ClusterState(
        window_duration_hours=horizon,
        max_cluster_power_kw=constraints.max_cluster_power_kw,
        max_concurrent_jobs=constraints.max_concurrent_jobs,
    )

    allocations: list[ScheduledJobAllocation] = []
    unmet_deadlines: list[str] = []

    for _, job in sorted_jobs.iterrows():
        jid = str(job["job_id"])
        arr = int(job["arrival_offset_hours"])
        dead = int(job["deadline_offset_hours"])
        proc_req = int(job["processing_requirement"])
        energy_kwh = float(job["energy_kwh"])
        max_parallelism = int(job.get("maximum_parallelism", 1))
        preemptible = bool(job.get("preemptible", True))

        # Each unit-hour consumes power = energy / proc_req
        unit_power_kw = energy_kwh / proc_req
        unit_energy_kwh = energy_kwh / proc_req

        # Eligible candidate hours: arr <= h < min(dead, horizon)
        eligible_hours = [h for h in range(arr, min(dead, horizon))]

        if not eligible_hours or len(eligible_hours) < proc_req and not preemptible:
            unmet_deadlines.append(jid)
            continue

        job_allocs: list[ScheduledJobAllocation] = []

        if not preemptible:
            # Contiguous sequence of proc_req active hours
            best_block = None
            best_block_score = float("inf")

            # Try every contiguous block [s, s + proc_req)
            for s in range(arr, min(dead, horizon) - proc_req + 1):
                candidate_block = list(range(s, s + proc_req))
                # Check feasibility of all hours in block
                all_feasible = True
                block_score = 0.0
                for h in candidate_block:
                    if not cluster.can_allocate(h, jid, unit_power_kw):
                        all_feasible = False
                        break
                    block_score += hourly_scores[h]

                if all_feasible:
                    # Deterministic tie-breaking: lower score, then earlier starting hour s
                    if block_score < best_block_score:
                        best_block_score = block_score
                        best_block = candidate_block

            if best_block is not None:
                for h in best_block:
                    cluster.commit(h, jid, unit_power_kw)
                    job_allocs.append(
                        ScheduledJobAllocation(
                            job_id=jid,
                            allocated_hour_offset=h,
                            execution_power_kw=unit_power_kw,
                            allocated_energy_kwh=unit_energy_kwh,
                        )
                    )
            else:
                unmet_deadlines.append(jid)
        else:
            # Preemptible: allocate unit-hours by ascending score
            # A job may execute at most max_parallelism units in one hour
            # We greedily pick the lowest-score available slots
            # Available candidate slots: (hour, score)
            # Up to max_parallelism units per hour
            candidate_slots: list[tuple[float, int]] = []
            for h in eligible_hours:
                candidate_slots.append((hourly_scores[h], h))

            # Deterministic sorting: ascending score, then ascending hour (earliest hour tie-break)
            candidate_slots.sort(key=lambda x: (x[0], x[1]))

            units_to_allocate = proc_req
            for score, h in candidate_slots:
                if units_to_allocate <= 0:
                    break
                # How many units can we allocate to this hour?
                # Capped by remaining units, max_parallelism, and cluster capacity
                current_units_in_hour = sum(1 for a in job_allocs if a.allocated_hour_offset == h)
                allowed_units = max_parallelism - current_units_in_hour
                if allowed_units <= 0:
                    continue

                # Can cluster allocate at least 1 unit?
                if cluster.can_allocate(h, jid, unit_power_kw):
                    cluster.commit(h, jid, unit_power_kw)
                    job_allocs.append(
                        ScheduledJobAllocation(
                            job_id=jid,
                            allocated_hour_offset=h,
                            execution_power_kw=unit_power_kw,
                            allocated_energy_kwh=unit_energy_kwh,
                        )
                    )
                    units_to_allocate -= 1

            # If not all units allocated, record deadline miss
            if units_to_allocate > 0:
                unmet_deadlines.append(jid)

        allocations.extend(job_allocs)

    # Sort allocations deterministically by hour then job_id
    allocations.sort(key=lambda a: (a.allocated_hour_offset, a.job_id))

    # Preliminary schedule result
    sched = ScheduleResult(
        policy_name=policy_name,
        policy_version=policy_version,
        workload_trace_id=trace_id,
        window_duration_hours=horizon,
        allocations=allocations,
        unmet_deadlines=unmet_deadlines,
        is_feasible=(len(unmet_deadlines) == 0),
    )

    # Strict feasibility check
    feasibility_rep = validate_schedule_feasibility(
        sched,
        workload_df,
        constraints,
        window_duration_hours=horizon,
    )

    return ScheduleResult(
        policy_name=policy_name,
        policy_version=policy_version,
        workload_trace_id=trace_id,
        window_duration_hours=horizon,
        allocations=allocations,
        unmet_deadlines=feasibility_rep.deadline_misses,
        is_feasible=feasibility_rep.is_feasible,
    )


class CostFirstGreedyPolicy:
    """Cost-First greedy policy prioritizing candidate hours with lowest electricity price."""

    @property
    def policy_name(self) -> str:
        return "cost_first"

    @property
    def policy_version(self) -> str:
        return "1.0"

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        # Score is raw predicted price (handles negative electricity prices directly)
        prices = [p.predicted_price_usd_per_mwh for p in forecast.points]
        return _schedule_greedy_with_scoring(
            workload_df,
            forecast,
            constraints,
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            hour_score_fn=lambda h, norm_p, norm_c: prices[h],
        )


class CarbonFirstGreedyPolicy:
    """Carbon-First greedy policy prioritizing candidate hours with lowest carbon intensity."""

    @property
    def policy_name(self) -> str:
        return "carbon_first"

    @property
    def policy_version(self) -> str:
        return "1.0"

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        # Score is raw predicted carbon intensity
        carbons = [p.predicted_carbon_g_per_kwh for p in forecast.points]
        return _schedule_greedy_with_scoring(
            workload_df,
            forecast,
            constraints,
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            hour_score_fn=lambda h, norm_p, norm_c: carbons[h],
        )


class BalancedGreedyPolicy:
    """Balanced greedy policy weighting normalized price and carbon equally."""

    def __init__(self, cost_weight: float = 0.5, carbon_weight: float = 0.5):
        self.cost_weight = cost_weight
        self.carbon_weight = carbon_weight

    @property
    def policy_name(self) -> str:
        return "balanced"

    @property
    def policy_version(self) -> str:
        return "1.0"

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
    ) -> ScheduleResult:
        # 0.5 * norm_price + 0.5 * norm_carbon
        return _schedule_greedy_with_scoring(
            workload_df,
            forecast,
            constraints,
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            hour_score_fn=lambda h, norm_p, norm_c: self.cost_weight * norm_p + self.carbon_weight * norm_c,
        )
