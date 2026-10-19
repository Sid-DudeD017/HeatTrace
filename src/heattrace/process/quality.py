"""Validation and quality-control logic for HeatTrace aligned datasets."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd

# Expected canonical column order
CANONICAL_COLUMNS: list[str] = [
    "timestamp_utc",
    "qc_day_type",
    "local_date",
    "temperature_c",
    "temperature_obs_count",
    "temperature_min_c",
    "temperature_max_c",
    "temperature_missing",
    "price_usd_per_mwh",
    "price_missing",
    "demand_mw",
    "demand_missing",
    "net_generation_mw",
    "net_generation_missing",
    "carbon_g_per_kwh",
    "carbon_missing",
    "carbon_data_issue",
    "carbon_primary_analysis_eligible",
    "source_quality",
    "co2_emissions_generated_metric_tons",
    "co2_emissions_consumed_metric_tons",
    "generated_intensity_lb_per_kwh",
    "consumed_intensity_lb_per_kwh",
    "generated_intensity_g_per_kwh",
    "consumed_intensity_g_per_kwh",
    "positive_generation_mwh",
    "consumed_electricity_mwh",
    "eia_api_net_generation_mw",
    "recalculated_generated_intensity_lb_per_kwh",
    "recalculated_generated_intensity_g_per_kwh",
    "generated_intensity_reconciliation_difference",
    "eia_data_issue_flag",
    "source_station_id",
    "source_caiso_node",
    "source_balancing_authority",
]

DEFAULT_RECONCILIATION_TOLERANCE_LB_PER_KWH = 1e-4


def validate_aligned_dataframe(
    df: pd.DataFrame,
    *,
    expected_rows: int = 48,
    expected_dates: list[str] | None = None,
    reconciliation_tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE_LB_PER_KWH,
) -> dict[str, Any]:
    """Deterministically validate an aligned DataFrame against canonical data contract and physics rules.

    Raises ValueError with descriptive failure details if any check fails.
    Returns a summary dictionary of validation metrics if all checks pass.
    """
    if expected_dates is None:
        expected_dates = ["2024-06-07", "2024-07-02"]

    # 1. Schema and deterministic column order
    actual_columns = list(df.columns)
    if actual_columns != CANONICAL_COLUMNS:
        missing = [c for c in CANONICAL_COLUMNS if c not in actual_columns]
        extra = [c for c in actual_columns if c not in CANONICAL_COLUMNS]
        order_mismatch = (
            f"Columns not in exact canonical order." if not missing and not extra else ""
        )
        raise ValueError(
            f"Aligned DataFrame schema mismatch. Missing: {missing}, Extra: {extra}. {order_mismatch}"
        )

    # 2. Row count
    n_rows = len(df)
    if n_rows != expected_rows:
        raise ValueError(f"Expected exactly {expected_rows} rows, but got {n_rows}")

    # 3. Timezone-aware UTC timestamps & interval-start semantics
    ts_series = df["timestamp_utc"]
    for idx, ts in enumerate(ts_series):
        if not isinstance(ts, (datetime, pd.Timestamp)):
            raise ValueError(
                f"Row {idx}: timestamp_utc must be datetime/Timestamp, got {type(ts)}"
            )
        if ts.tzinfo is None or str(ts.tzinfo).upper() not in ("UTC", "TIMEZONE.UTC", "+00:00"):
            raise ValueError(
                f"Row {idx}: timestamp_utc must be timezone-aware UTC, got tzinfo={ts.tzinfo}"
            )
        if ts.minute != 0 or ts.second != 0 or ts.microsecond != 0:
            raise ValueError(
                f"Row {idx}: timestamp_utc {ts} is not aligned to the top of the hour"
            )

    # 4. Duplicate timestamps and monotonic ordering check
    dup_mask = ts_series.duplicated()
    dup_count = int(dup_mask.sum())
    if dup_count > 0:
        dups = ts_series[dup_mask].tolist()
        raise ValueError(f"Found {dup_count} duplicate timestamp_utc entries: {dups}")
    if not ts_series.is_monotonic_increasing:
        raise ValueError("timestamp_utc is not monotonically increasing")

    # 5. Local date coverage & 24 rows per local date
    date_counts = df["local_date"].value_counts().to_dict()
    for d in expected_dates:
        cnt = date_counts.get(d, 0)
        if cnt != 24:
            raise ValueError(f"Local date {d} has {cnt} rows, expected exactly 24")

    # 6. Physical and domain value ranges
    # Temperature: terrestrial bounds [-60, +65] C
    for idx, row in df.iterrows():
        t_miss = row["temperature_missing"]
        t_val = row["temperature_c"]
        if t_miss:
            if pd.notna(t_val):
                raise ValueError(
                    f"Row {idx}: temperature_missing is True but temperature_c is {t_val}"
                )
        else:
            if pd.isna(t_val) or math.isnan(t_val):
                raise ValueError(
                    f"Row {idx}: temperature_missing is False but temperature_c is NaN"
                )
            if not (-60.0 <= t_val <= 65.0):
                raise ValueError(
                    f"Row {idx}: temperature {t_val}°C outside plausible terrestrial bounds"
                )
            if row["temperature_obs_count"] <= 0:
                raise ValueError(
                    f"Row {idx}: temperature_obs_count must be > 0 when not missing"
                )
            if not (row["temperature_min_c"] <= t_val <= row["temperature_max_c"]):
                raise ValueError(
                    f"Row {idx}: temperature mean {t_val} not in [min={row['temperature_min_c']}, max={row['temperature_max_c']}]"
                )

        # Price: negative prices are valid; check reasonable bounds [-1000, +5000] USD/MWh
        p_miss = row["price_missing"]
        p_val = row["price_usd_per_mwh"]
        if p_miss:
            if pd.notna(p_val):
                raise ValueError(
                    f"Row {idx}: price_missing is True but price_usd_per_mwh is {p_val}"
                )
        else:
            if pd.isna(p_val) or math.isnan(p_val):
                raise ValueError(
                    f"Row {idx}: price_missing is False but price_usd_per_mwh is NaN"
                )
            if not (-1000.0 <= p_val <= 5000.0):
                raise ValueError(
                    f"Row {idx}: price {p_val} USD/MWh outside reasonable market bounds"
                )

        # Demand: non-negative
        d_miss = row["demand_missing"]
        d_val = row["demand_mw"]
        if d_miss:
            if pd.notna(d_val):
                raise ValueError(
                    f"Row {idx}: demand_missing is True but demand_mw is {d_val}"
                )
        else:
            if pd.isna(d_val) or math.isnan(d_val):
                raise ValueError(
                    f"Row {idx}: demand_missing is False but demand_mw is NaN"
                )
            if d_val < 0.0:
                raise ValueError(
                    f"Row {idx}: demand {d_val} MW is negative"
                )

        # Net generation: finite number (may be negative if pump-storage/charging exceeds generation)
        ng_miss = row["net_generation_missing"]
        ng_val = row["net_generation_mw"]
        if ng_miss:
            if pd.notna(ng_val):
                raise ValueError(
                    f"Row {idx}: net_generation_missing is True but net_generation_mw is {ng_val}"
                )
        else:
            if pd.isna(ng_val) or math.isnan(ng_val):
                raise ValueError(
                    f"Row {idx}: net_generation_missing is False but net_generation_mw is NaN"
                )
            if not (-50000.0 <= ng_val <= 100000.0):
                raise ValueError(
                    f"Row {idx}: net_generation {ng_val} MW outside plausible bounds"
                )

        # Carbon intensity: non-negative, finite
        c_miss = row["carbon_missing"]
        c_val = row["carbon_g_per_kwh"]
        if c_miss:
            if pd.notna(c_val):
                raise ValueError(
                    f"Row {idx}: carbon_missing is True but carbon_g_per_kwh is {c_val}"
                )
        else:
            if pd.isna(c_val) or math.isnan(c_val):
                raise ValueError(
                    f"Row {idx}: carbon_missing is False but carbon_g_per_kwh is NaN"
                )
            if c_val < 0.0:
                raise ValueError(
                    f"Row {idx}: carbon intensity {c_val} g CO2/kWh is negative"
                )

        # Carbon reconciliation
        reconcil_diff = row["generated_intensity_reconciliation_difference"]
        if pd.notna(reconcil_diff) and abs(reconcil_diff) > reconciliation_tolerance:
            raise ValueError(
                f"Row {idx}: carbon reconciliation diff {reconcil_diff} exceeds tolerance {reconciliation_tolerance}"
            )

        # EIA data issue policy check:
        # carbon_data_issue must align with carbon_primary_analysis_eligible and source_quality
        is_issue = bool(row["carbon_data_issue"])
        eligible = bool(row["carbon_primary_analysis_eligible"])
        sq = str(row["source_quality"])
        if is_issue:
            if eligible:
                raise ValueError(
                    f"Row {idx}: carbon_data_issue is True but carbon_primary_analysis_eligible is True"
                )
            if sq != "success_with_data_issues":
                raise ValueError(
                    f"Row {idx}: carbon_data_issue is True but source_quality is '{sq}' (expected 'success_with_data_issues')"
                )
        else:
            if not eligible:
                raise ValueError(
                    f"Row {idx}: carbon_data_issue is False but carbon_primary_analysis_eligible is False"
                )
            if sq != "success":
                raise ValueError(
                    f"Row {idx}: carbon_data_issue is False but source_quality is '{sq}' (expected 'success')"
                )

    # 7. Summary metrics
    missingness = {
        "temperature_missing_count": int(df["temperature_missing"].sum()),
        "price_missing_count": int(df["price_missing"].sum()),
        "demand_missing_count": int(df["demand_missing"].sum()),
        "net_generation_missing_count": int(df["net_generation_missing"].sum()),
        "carbon_missing_count": int(df["carbon_missing"].sum()),
    }
    eia_issues = {
        "carbon_data_issue_count": int(df["carbon_data_issue"].sum()),
        "carbon_primary_analysis_eligible_count": int(
            df["carbon_primary_analysis_eligible"].sum()
        ),
    }

    max_reconcil_diff = float(
        df["generated_intensity_reconciliation_difference"].abs().max()
    )

    return {
        "row_count": n_rows,
        "timestamp_start": ts_series.iloc[0].isoformat(),
        "timestamp_end": ts_series.iloc[-1].isoformat(),
        "duplicate_timestamps": dup_count,
        "date_counts": date_counts,
        "missingness": missingness,
        "eia_issues": eia_issues,
        "max_reconciliation_diff_lb_per_kwh": max_reconcil_diff,
        "reconciliation_tolerance_lb_per_kwh": reconciliation_tolerance,
    }
