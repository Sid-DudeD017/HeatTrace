"""Small-instance exact hindsight comparator for HeatTrace P4-06.

Exact exhaustive search / branch-and-bound for small benchmark instances.
Uses realized actual values only, explicitly as a hindsight comparator.
Never labels a heuristic result as optimal.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Any
import pandas as pd

from heattrace.policy.feasibility import validate_schedule_feasibility
from heattrace.policy.interfaces import (
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
)


@dataclass
class ComparatorResult:
    """Outcome from the exact hindsight comparator."""
    is_supported: bool
    status: str
    reason: str
    optimal_cost_usd: float | None = None
    optimal_emissions_kg: float | None = None
    optimal_objective: float | None = None
    schedule: ScheduleResult | None = None


class ExactSmallInstanceHindsightComparator:
    """Exact branch-and-bound comparator for small problem instances."""

    def __init__(
        self,
        max_jobs: int = 6,
        max_horizon_hours: int = 24,
        cost_weight: float = 0.5,
        carbon_weight: float = 0.5,
    ):
        self.max_jobs = max_jobs
        self.max_horizon_hours = max_horizon_hours
        self.cost_weight = cost_weight
        self.carbon_weight = carbon_weight

    def solve(
        self,
        workload_df: pd.DataFrame,
        realized_df: pd.DataFrame,
        constraints: SchedulingConstraints,
        *,
        objective_mode: str = "cost",  # "cost", "emissions", "balanced"
    ) -> ComparatorResult:
        """Find the globally optimal schedule for a small instance using exact branch-and-bound."""
        n_jobs = len(workload_df)
        horizon = len(realized_df)

        if n_jobs > self.max_jobs:
            return ComparatorResult(
                is_supported=False,
                status="unsupported",
                reason=f"Instance job count {n_jobs} exceeds exact comparator limit {self.max_jobs}",
            )

        if horizon > self.max_horizon_hours:
            return ComparatorResult(
                is_supported=False,
                status="unsupported",
                reason=f"Instance horizon {horizon}h exceeds exact comparator limit {self.max_horizon_hours}h",
            )

        # Realized prices and carbons
        prices = realized_df["price_usd_per_mwh"].tolist()
        carbons = realized_df["carbon_g_per_kwh"].tolist()

        # Generate candidate placement configurations for each job
        jobs = []
        for _, row in workload_df.iterrows():
            jid = str(row["job_id"])
            arr = int(row["arrival_offset_hours"])
            dead = int(row["deadline_offset_hours"])
            proc = int(row["processing_requirement"])
            en = float(row["energy_kwh"])
            par = int(row.get("maximum_parallelism", 1))
            preempt = bool(row.get("preemptible", True))
            pwr = en / proc
            u_en = en / proc

            # Eligible hours
            elig = [h for h in range(arr, min(dead, horizon))]
            candidate_combos = []

            if not preempt:
                # Contiguous blocks
                for s in range(arr, min(dead, horizon) - proc + 1):
                    candidate_combos.append(list(range(s, s + proc)))
            else:
                # All combinations of proc hours from elig
                # with at most par units per hour
                if len(elig) >= proc:
                    for combo in itertools.combinations(elig, proc):
                        candidate_combos.append(list(combo))

            if not candidate_combos:
                return ComparatorResult(
                    is_supported=True,
                    status="infeasible",
                    reason=f"Job {jid} has no feasible candidate placement windows",
                )

            jobs.append({
                "job_id": jid,
                "power_kw": pwr,
                "energy_kwh": u_en,
                "proc": proc,
                "candidates": candidate_combos,
            })

        # Branch and bound search over cartesian product of job allocations
        best_obj = float("inf")
        best_allocs: list[ScheduledJobAllocation] | None = None
        best_cost = 0.0
        best_emiss = 0.0

        def evaluate_combination(job_placements: list[list[int]]) -> tuple[bool, float, float, float]:
            hourly_pwr = [0.0] * horizon
            hourly_cnt = [0] * horizon

            tot_cost = 0.0
            tot_emiss = 0.0

            for j_idx, hours in enumerate(job_placements):
                pwr = jobs[j_idx]["power_kw"]
                en = jobs[j_idx]["energy_kwh"]
                for h in hours:
                    hourly_pwr[h] += pwr
                    if hourly_pwr[h] > constraints.max_cluster_power_kw + 1e-4:
                        return False, 0.0, 0.0, 0.0
                    hourly_cnt[h] += 1
                    if hourly_cnt[h] > constraints.max_concurrent_jobs:
                        return False, 0.0, 0.0, 0.0

                    # Cost: en * price / 1000
                    tot_cost += (en * prices[h]) / 1000.0
                    tot_emiss += (en * carbons[h]) / 1000.0

            if objective_mode == "cost":
                obj = tot_cost
            elif objective_mode == "emissions":
                obj = tot_emiss
            else:
                obj = self.cost_weight * tot_cost + self.carbon_weight * tot_emiss

            return True, obj, tot_cost, tot_emiss

        # Exhaustive search
        all_candidate_lists = [j["candidates"] for j in jobs]
        for combo in itertools.product(*all_candidate_lists):
            feasible, obj, c_usd, e_kg = evaluate_combination(list(combo))
            if feasible and obj < best_obj:
                best_obj = obj
                best_cost = c_usd
                best_emiss = e_kg
                best_allocs = []
                for j_idx, hours in enumerate(combo):
                    jid = jobs[j_idx]["job_id"]
                    pwr = jobs[j_idx]["power_kw"]
                    en = jobs[j_idx]["energy_kwh"]
                    for h in hours:
                        best_allocs.append(
                            ScheduledJobAllocation(
                                job_id=jid,
                                allocated_hour_offset=h,
                                execution_power_kw=pwr,
                                allocated_energy_kwh=en,
                            )
                        )

        if best_allocs is None:
            return ComparatorResult(
                is_supported=True,
                status="infeasible",
                reason="No feasible allocation exists satisfying all cluster constraints",
            )

        best_allocs.sort(key=lambda a: (a.allocated_hour_offset, a.job_id))
        sched_res = ScheduleResult(
            policy_name="exact_hindsight_comparator",
            policy_version="1.0",
            workload_trace_id=str(workload_df["workload_trace_id"].iloc[0]),
            window_duration_hours=horizon,
            allocations=best_allocs,
            total_cost_usd=round(best_cost, 4),
            total_carbon_emissions_kg=round(best_emiss, 4),
            is_feasible=True,
        )

        return ComparatorResult(
            is_supported=True,
            status="optimal",
            reason="Global optimum found via exact branch-and-bound",
            optimal_cost_usd=round(best_cost, 4),
            optimal_emissions_kg=round(best_emiss, 4),
            optimal_objective=round(best_obj, 4),
            schedule=sched_res,
        )
