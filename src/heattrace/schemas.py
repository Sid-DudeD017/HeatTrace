"""Strict P4 schema definitions and validators."""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.forecast.schema import FORECAST_COLUMNS, validate_forecast_dataframe
from heattrace.manifests import validate_p4_experiment_manifest


SCHEDULE_COLUMNS: list[str] = [
    "policy_name",
    "policy_version",
    "workload_trace_id",
    "job_id",
    "allocated_hour_offset",
    "execution_power_kw",
    "allocated_energy_kwh",
]


METRIC_JSON_KEYS: list[str] = [
    "policy_name",
    "policy_version",
    "window_id",
    "window_type",
    "workload_trace_id",
    "total_realized_cost_usd",
    "total_realized_emissions_kg",
    "total_allocated_energy_kwh",
    "completed_jobs",
    "incomplete_jobs",
    "deadline_misses",
    "unmet_processing_unit_hours",
    "unmet_energy_kwh",
    "sla_completion_rate",
    "max_cluster_power_kw",
    "max_concurrent_jobs",
    "is_feasible",
    "violation_count",
    "forecast_price_mae",
    "forecast_carbon_mae",
    "forecast_price_bias",
    "forecast_carbon_bias",
    "cvar_cost_90",
    "cvar_emissions_90",
    "cvar_composite_loss_90",
    "comparator_objective",
    "comparator_gap",
    "comparator_status",
    "comparator_reason",
    "carbon_data_issue_row_count",
    "carbon_primary_analysis_eligible_row_count",
    "carbon_interpretation_label",
]


def validate_schedule_dataframe(df: pd.DataFrame, workload_df: pd.DataFrame) -> list[str]:
    """Validate scheduled job allocations against schedule schema."""
    errors: list[str] = []
    if not isinstance(df, pd.DataFrame):
        return ["Schedule object must be a pandas DataFrame"]

    if list(df.columns) != SCHEDULE_COLUMNS:
        errors.append(f"Schedule columns mismatch. Expected {SCHEDULE_COLUMNS}, got {list(df.columns)}")
        return errors

    valid_jobs = set(workload_df["job_id"].unique())

    for idx, row in df.iterrows():
        jid = str(row["job_id"])
        if jid not in valid_jobs:
            errors.append(f"Row {idx}: unknown job_id '{jid}' not in workload")

        hr = row["allocated_hour_offset"]
        if not isinstance(hr, (int, float)) or int(hr) != hr or hr < 0 or hr >= 120:
            errors.append(f"Row {idx}: allocated_hour_offset must be integer in [0, 119], got {hr}")

        pwr = row["execution_power_kw"]
        if pd.isna(pwr) or not math.isfinite(float(pwr)) or float(pwr) <= 0.0:
            errors.append(f"Row {idx}: execution_power_kw must be positive finite number, got {pwr}")

        en = row["allocated_energy_kwh"]
        if pd.isna(en) or not math.isfinite(float(en)) or float(en) <= 0.0:
            errors.append(f"Row {idx}: allocated_energy_kwh must be positive finite number, got {en}")

    # Duplicate job allocation in same hour check
    if df.duplicated(subset=["job_id", "allocated_hour_offset"]).any():
        errors.append("Duplicate (job_id, allocated_hour_offset) entries found in schedule")

    return errors


def validate_metrics_dictionary(metrics: dict[str, Any]) -> list[str]:
    """Validate P4 metric dictionary keys, types, and values."""
    errors: list[str] = []
    if not isinstance(metrics, dict):
        return ["Metrics must be a dictionary"]

    for k in METRIC_JSON_KEYS:
        if k not in metrics:
            errors.append(f"Missing required metric key '{k}'")

    if errors:
        return errors

    # Check finite floats for key metrics
    float_keys = [
        "total_realized_cost_usd",
        "total_realized_emissions_kg",
        "total_allocated_energy_kwh",
        "sla_completion_rate",
        "max_cluster_power_kw",
        "cvar_cost_90",
        "cvar_emissions_90",
        "cvar_composite_loss_90",
    ]
    for fk in float_keys:
        val = metrics.get(fk)
        if val is None or not math.isfinite(float(val)):
            errors.append(f"Metric '{fk}' must be finite float, got {val}")

    if metrics.get("carbon_interpretation_label") != "quality_limited_sensitivity_only":
        errors.append(f"Metric carbon_interpretation_label must be 'quality_limited_sensitivity_only', got '{metrics.get('carbon_interpretation_label')}'")

    return errors
