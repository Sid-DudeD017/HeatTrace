"""Metrics evaluation and CVaR calculations for HeatTrace P4-07."""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.interfaces import ScheduleResult
from heattrace.schemas import METRIC_JSON_KEYS, validate_metrics_dictionary


def compute_cvar(
    losses: list[float] | np.ndarray,
    alpha: float = 0.90,
) -> float:
    """Compute Conditional Value-at-Risk (Expected Shortfall) at confidence level alpha.

    Loss orientation:
    - Higher values represent greater loss / worse outcomes.
    - VaR_alpha is the alpha-quantile of loss distribution.
    - CVaR_alpha is the expected loss given that loss exceeds or equals VaR_alpha.
    - Uses deterministic sample mean of values >= VaR_alpha.
    - For small samples or ties, deterministic fallback to maximum or values >= quantile is guaranteed.
    """
    arr = np.array(losses, dtype=float)
    if len(arr) == 0:
        return 0.0

    # Sort losses ascending
    sorted_losses = np.sort(arr)
    n = len(sorted_losses)

    # VaR index
    var_threshold = float(np.quantile(sorted_losses, alpha))
    tail_losses = sorted_losses[sorted_losses >= var_threshold]

    if len(tail_losses) == 0:
        return float(sorted_losses[-1])

    return float(np.mean(tail_losses))


def compute_schedule_metrics(
    schedule: ScheduleResult,
    workload_df: pd.DataFrame,
    realized_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    *,
    window_id: str,
    window_type: str,
    cvar_alpha: float = 0.90,
    comparator_objective: float | None = None,
    comparator_gap: float | None = None,
    comparator_status: str = "unsupported",
    comparator_reason: str = "Full 120h/30-job benchmark exceeds exact comparator limit",
    carbon_interpretation_label: str = "quality_limited_sensitivity_only",
) -> dict[str, Any]:
    """Compute realized cost, emissions, SLA completion, CVaR, forecast error, and comparator metrics."""
    allocs = schedule.allocations
    horizon = len(realized_df)

    realized_prices = realized_df["price_usd_per_mwh"].to_numpy()
    realized_carbons = realized_df["carbon_g_per_kwh"].to_numpy()

    # Pre-index forecast values by horizon_hour
    fc_window = forecast_df[forecast_df["window_id"] == window_id].sort_values("horizon_hour")
    if not fc_window.empty and len(fc_window) == horizon:
        fc_prices = fc_window["predicted_price_usd_per_mwh"].to_numpy()
        fc_carbons = fc_window["predicted_carbon_g_per_kwh"].to_numpy()
    else:
        fc_prices = np.full(horizon, 45.0)
        fc_carbons = np.full(horizon, 220.0)

    # Forecast diagnostics
    price_errors = fc_prices - realized_prices
    carbon_errors = fc_carbons - realized_carbons

    fc_price_mae = float(np.mean(np.abs(price_errors)))
    fc_carbon_mae = float(np.mean(np.abs(carbon_errors)))
    fc_price_bias = float(np.mean(price_errors))
    fc_carbon_bias = float(np.mean(carbon_errors))

    # Realized scoring per hour
    hourly_cost = np.zeros(horizon, dtype=float)
    hourly_emissions = np.zeros(horizon, dtype=float)
    hourly_power = np.zeros(horizon, dtype=float)
    hourly_jobs: list[set[str]] = [set() for _ in range(horizon)]

    total_allocated_energy = 0.0

    for a in allocs:
        h = a.allocated_hour_offset
        if 0 <= h < horizon:
            en = a.allocated_energy_kwh
            pwr = a.execution_power_kw
            total_allocated_energy += en

            # Cost: allocated_energy_kwh * actual_price_usd_per_mwh / 1000
            c = (en * realized_prices[h]) / 1000.0
            # Emissions: allocated_energy_kwh * actual_carbon_g_per_kwh / 1000
            e = (en * realized_carbons[h]) / 1000.0

            hourly_cost[h] += c
            hourly_emissions[h] += e
            hourly_power[h] += pwr
            hourly_jobs[h].add(a.job_id)

    tot_cost_usd = float(np.sum(hourly_cost))
    tot_emiss_kg = float(np.sum(hourly_emissions))
    max_pwr = float(np.max(hourly_power)) if horizon > 0 else 0.0
    max_concurrent = max(len(s) for s in hourly_jobs) if horizon > 0 else 0

    # Job SLA accounting
    workload_jobs = {row["job_id"]: row for _, row in workload_df.iterrows()}
    job_alloc_energy: dict[str, float] = {jid: 0.0 for jid in workload_jobs}
    for a in allocs:
        if a.job_id in job_alloc_energy:
            job_alloc_energy[a.job_id] += a.allocated_energy_kwh

    completed_jobs_list: list[str] = []
    incomplete_jobs_list: list[str] = []
    unmet_units = 0.0
    unmet_energy = 0.0

    for jid, job in workload_jobs.items():
        req_energy = float(job["energy_kwh"])
        req_proc = float(job["processing_requirement"])
        act_energy = job_alloc_energy[jid]

        if abs(act_energy - req_energy) <= 1e-3:
            completed_jobs_list.append(jid)
        else:
            incomplete_jobs_list.append(jid)
            diff_en = max(0.0, req_energy - act_energy)
            unmet_energy += diff_en
            unit_en = req_energy / req_proc if req_proc > 0 else 1.0
            unmet_units += diff_en / unit_en

    n_jobs = len(workload_jobs)
    sla_rate = float(len(completed_jobs_list) / n_jobs) if n_jobs > 0 else 1.0

    # CVaR calculations on realized hourly distributions
    cvar_cost = compute_cvar(hourly_cost, alpha=cvar_alpha)
    cvar_emiss = compute_cvar(hourly_emissions, alpha=cvar_alpha)

    # Composite loss: normalized hourly cost + normalized hourly emissions
    cost_range = np.max(hourly_cost) - np.min(hourly_cost)
    emiss_range = np.max(hourly_emissions) - np.min(hourly_emissions)
    norm_h_cost = (hourly_cost - np.min(hourly_cost)) / (cost_range if cost_range > 0 else 1.0)
    norm_h_emiss = (hourly_emissions - np.min(hourly_emissions)) / (emiss_range if emiss_range > 0 else 1.0)
    composite_loss = 0.5 * norm_h_cost + 0.5 * norm_h_emiss
    cvar_composite = compute_cvar(composite_loss, alpha=cvar_alpha)

    # Carbon data issue rows in realized_df
    carb_issues = int(realized_df["carbon_data_issue"].sum()) if "carbon_data_issue" in realized_df else 0
    carb_eligible = int(realized_df["carbon_primary_analysis_eligible"].sum()) if "carbon_primary_analysis_eligible" in realized_df else 0

    metrics = {
        "policy_name": schedule.policy_name,
        "policy_version": schedule.policy_version,
        "window_id": window_id,
        "window_type": window_type,
        "workload_trace_id": schedule.workload_trace_id,
        "total_realized_cost_usd": round(tot_cost_usd, 4),
        "total_realized_emissions_kg": round(tot_emiss_kg, 4),
        "total_allocated_energy_kwh": round(total_allocated_energy, 4),
        "completed_jobs": len(completed_jobs_list),
        "incomplete_jobs": len(incomplete_jobs_list),
        "deadline_misses": len(schedule.unmet_deadlines),
        "unmet_processing_unit_hours": round(unmet_units, 4),
        "unmet_energy_kwh": round(unmet_energy, 4),
        "sla_completion_rate": round(sla_rate, 4),
        "max_cluster_power_kw": round(max_pwr, 4),
        "max_concurrent_jobs": max_concurrent,
        "is_feasible": schedule.is_feasible,
        "violation_count": len(schedule.unmet_deadlines) if not schedule.is_feasible else 0,
        "forecast_price_mae": round(fc_price_mae, 4),
        "forecast_carbon_mae": round(fc_carbon_mae, 4),
        "forecast_price_bias": round(fc_price_bias, 4),
        "forecast_carbon_bias": round(fc_carbon_bias, 4),
        "cvar_cost_90": round(cvar_cost, 4),
        "cvar_emissions_90": round(cvar_emiss, 4),
        "cvar_composite_loss_90": round(cvar_composite, 4),
        "comparator_objective": round(comparator_objective, 4) if comparator_objective is not None else None,
        "comparator_gap": round(comparator_gap, 4) if comparator_gap is not None else None,
        "comparator_status": comparator_status,
        "comparator_reason": comparator_reason,
        "carbon_data_issue_row_count": carb_issues,
        "carbon_primary_analysis_eligible_row_count": carb_eligible,
        "carbon_interpretation_label": carbon_interpretation_label,
    }

    errs = validate_metrics_dictionary(metrics)
    if errs:
        raise ValueError(f"Computed metrics failed validation: {'; '.join(errs)}")

    return metrics
