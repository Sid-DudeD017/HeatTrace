"""P4 forecast schemas and type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import pandas as pd


FORECAST_COLUMNS: list[str] = [
    "window_type",
    "window_id",
    "origin_timestamp_utc",
    "target_timestamp_utc",
    "horizon_hour",
    "predicted_price_usd_per_mwh",
    "predicted_carbon_g_per_kwh",
    "forecast_method",
    "model_name",
    "model_version",
    "history_cutoff_utc",
    "used_fallback",
    "source_history_rows",
]


def validate_forecast_dataframe(df: pd.DataFrame, expected_rows: int = 120) -> list[str]:
    """Strictly validate a forecast dataframe conforming to P4-02 / P4-03 schema."""
    errors: list[str] = []
    if not isinstance(df, pd.DataFrame):
        return ["Forecast object must be a pandas DataFrame"]

    if list(df.columns) != FORECAST_COLUMNS:
        errors.append(f"Forecast columns mismatch. Expected {FORECAST_COLUMNS}, got {list(df.columns)}")
        return errors

    if len(df) != expected_rows:
        errors.append(f"Expected {expected_rows} forecast rows, got {len(df)}")

    # Check primary keys: window_id + horizon_hour or window_id + target_timestamp_utc
    if df.duplicated(subset=["window_id", "horizon_hour"]).any():
        errors.append("Duplicate (window_id, horizon_hour) pairs detected")

    import math

    for idx, row in df.iterrows():
        # Check window_type
        if row["window_type"] not in ("event", "control"):
            errors.append(f"Row {idx}: invalid window_type '{row['window_type']}'")

        # Check origin_timestamp_utc
        orig = row["origin_timestamp_utc"]
        if not isinstance(orig, (datetime, pd.Timestamp)) or orig.tzinfo is None:
            errors.append(f"Row {idx}: origin_timestamp_utc must be timezone-aware UTC datetime")
        elif orig.minute != 0 or orig.second != 0:
            errors.append(f"Row {idx}: origin_timestamp_utc must be top-of-hour")

        # Check target_timestamp_utc
        target = row["target_timestamp_utc"]
        if not isinstance(target, (datetime, pd.Timestamp)) or target.tzinfo is None:
            errors.append(f"Row {idx}: target_timestamp_utc must be timezone-aware UTC datetime")
        elif target.minute != 0 or target.second != 0:
            errors.append(f"Row {idx}: target_timestamp_utc must be top-of-hour")

        # Check history_cutoff_utc
        cutoff = row["history_cutoff_utc"]
        if not isinstance(cutoff, (datetime, pd.Timestamp)) or cutoff.tzinfo is None:
            errors.append(f"Row {idx}: history_cutoff_utc must be timezone-aware UTC datetime")
        elif cutoff > orig:
            errors.append(f"Row {idx}: history_cutoff_utc ({cutoff}) > origin_timestamp_utc ({orig}) - causal leakage!")

        # Check horizon_hour
        h = row["horizon_hour"]
        if not isinstance(h, (int, float)) or int(h) != h or h < 0:
            errors.append(f"Row {idx}: horizon_hour must be a non-negative integer, got {h}")

        # Check values finite
        p = row["predicted_price_usd_per_mwh"]
        if pd.isna(p) or not math.isfinite(float(p)):
            errors.append(f"Row {idx}: predicted_price_usd_per_mwh must be finite, got {p}")

        c = row["predicted_carbon_g_per_kwh"]
        if pd.isna(c) or not math.isfinite(float(c)):
            errors.append(f"Row {idx}: predicted_carbon_g_per_kwh must be finite, got {c}")
        elif float(c) < 0.0:
            errors.append(f"Row {idx}: predicted_carbon_g_per_kwh must be non-negative, got {c}")

        # Fallback check
        fb = row["used_fallback"]
        if not isinstance(fb, (bool,)):
            errors.append(f"Row {idx}: used_fallback must be boolean, got {fb}")

    return errors
