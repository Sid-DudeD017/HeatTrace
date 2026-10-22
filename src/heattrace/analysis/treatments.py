"""Deterministic data treatment variants generator (P5-02 / E3).

Produces 3 variants without modifying upstream files:
1. raw: Baseline unmodified benchmark data.
2. clipped: 1st and 99th percentiles fitted strictly from pre-cutoff historical data.
3. causal_imputed: Causal forward fill (never backward fill; fallback to pre-cutoff median).

Strict No-Leakage Contract:
- Fitting cutoff: Earliest evaluated target-window origin (CTRL_20240605 = 2024-06-05 07:00:00 UTC).
- Fitting sources must strictly have timestamp_utc < fit_cutoff_utc.
- If pre-cutoff data is empty/insufficient, variants dependent on fitted historical parameters
  are explicitly marked 'unsupported_insufficient_pre_target_history' and excluded from claims.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from heattrace.ingest.provenance import sha256_file


TREATMENT_SIGNALS = [
    "temperature_c",
    "demand_mw",
    "net_generation_mw",
    "price_usd_per_mwh",
    "carbon_g_per_kwh",
]

# Earliest evaluated target window origin (CTRL_20240605 start)
EARLIEST_TARGET_ORIGIN_UTC = "2024-06-05T07:00:00+00:00"


def fit_historical_treatment_parameters(
    history_df: pd.DataFrame,
    fit_cutoff_utc: str = EARLIEST_TARGET_ORIGIN_UTC,
    signals: list[str] = TREATMENT_SIGNALS,
    lower_pct: float = 1.0,
    upper_pct: float = 99.0,
    source_file_hash: str = "",
) -> dict[str, Any]:
    """Fit clipping bounds and medians strictly from historical pre-cutoff observations.

    Enforces:
    - timestamp_utc < fit_cutoff_utc strictly.
    - Asserts no fitting rows >= fit_cutoff_utc.
    - Records fit cutoff, eligible row count, excluded row count, source min/max timestamps.
    - If eligible rows are 0 or insufficient (< 3), marks status as unsupported_insufficient_pre_target_history.
    """
    cutoff_ts = pd.to_datetime(fit_cutoff_utc, utc=True)

    if history_df.empty or "timestamp_utc" not in history_df.columns:
        return {
            "status": "unsupported_insufficient_pre_target_history",
            "fit_cutoff_utc": fit_cutoff_utc,
            "eligible_row_count": 0,
            "excluded_target_future_row_count": len(history_df),
            "source_min_timestamp_utc": None,
            "source_max_timestamp_utc": None,
            "source_file_hash": source_file_hash,
            "reason": "History dataframe is empty or lacks timestamp_utc",
            "bounds": {},
            "medians": {},
        }

    ts_col = pd.to_datetime(history_df["timestamp_utc"], utc=True)
    eligible_mask = ts_col < cutoff_ts
    excluded_count = int((~eligible_mask).sum())
    eligible_df = history_df[eligible_mask].copy()

    # STRICT ASSERTION: No row in eligible_df may be >= cutoff_ts
    if not eligible_df.empty:
        assert (pd.to_datetime(eligible_df["timestamp_utc"], utc=True) < cutoff_ts).all(), (
            f"Target leakage violation! Found rows >= {fit_cutoff_utc} in treatment fitting data."
        )

    eligible_count = len(eligible_df)
    source_min_ts = str(eligible_df["timestamp_utc"].min()) if eligible_count > 0 else None
    source_max_ts = str(eligible_df["timestamp_utc"].max()) if eligible_count > 0 else None

    # Check if we have sufficient observations
    if eligible_count < 3:
        return {
            "status": "unsupported_insufficient_pre_target_history",
            "fit_cutoff_utc": fit_cutoff_utc,
            "eligible_row_count": eligible_count,
            "excluded_target_future_row_count": excluded_count,
            "source_min_timestamp_utc": source_min_ts,
            "source_max_timestamp_utc": source_max_ts,
            "source_file_hash": source_file_hash,
            "reason": (
                f"Zero or insufficient pre-cutoff observations ({eligible_count} eligible rows before {fit_cutoff_utc}; "
                f"{excluded_count} rows excluded as target/future). Historical clipping and median imputation unsupported."
            ),
            "bounds": {},
            "medians": {},
        }

    # If valid pre-cutoff history exists, fit parameters
    bounds: dict[str, dict[str, float]] = {}
    medians: dict[str, float] = {}

    for sig in signals:
        if sig in eligible_df.columns:
            s = eligible_df[sig].dropna()
            if len(s) >= 3:
                bounds[sig] = {
                    "lower_bound": round(float(np.percentile(s, lower_pct)), 4),
                    "upper_bound": round(float(np.percentile(s, upper_pct)), 4),
                    "source_rows": len(s),
                }
                medians[sig] = round(float(s.median()), 4)
            else:
                bounds[sig] = {"lower_bound": float("-inf"), "upper_bound": float("inf"), "source_rows": len(s)}
                medians[sig] = float("nan")

    return {
        "status": "supported",
        "fit_cutoff_utc": fit_cutoff_utc,
        "eligible_row_count": eligible_count,
        "excluded_target_future_row_count": excluded_count,
        "source_min_timestamp_utc": source_min_ts,
        "source_max_timestamp_utc": source_max_ts,
        "source_file_hash": source_file_hash,
        "bounds": bounds,
        "medians": medians,
    }


def create_raw_variant(benchmark_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create raw unmodified variant."""
    df_raw = benchmark_df.copy()
    meta = {
        "variant": "raw",
        "status": "supported",
        "row_count": len(df_raw),
        "timestamp_min_utc": str(df_raw["timestamp_utc"].min()),
        "timestamp_max_utc": str(df_raw["timestamp_utc"].max()),
        "modified_cell_count": 0,
        "clipped_cell_count": 0,
        "imputed_cell_count": 0,
        "remaining_missing_count": int(df_raw[TREATMENT_SIGNALS].isna().sum().sum()),
        "carbon_quality_label": "quality_limited_sensitivity_only",
        "treatment_description": "Unmodified original benchmark data.",
    }
    return df_raw, meta


def create_clipped_variant(
    benchmark_df: pd.DataFrame,
    treatment_fit_info: dict[str, Any],
    signals: list[str] = TREATMENT_SIGNALS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create clipped variant.

    If historical fitting is unsupported, marks variant unsupported and preserves original data.
    """
    df_clipped = benchmark_df.copy()
    fit_status = treatment_fit_info.get("status", "unsupported_insufficient_pre_target_history")

    if fit_status != "supported":
        meta = {
            "variant": "clipped",
            "status": "unsupported_insufficient_pre_target_history",
            "row_count": len(df_clipped),
            "timestamp_min_utc": str(df_clipped["timestamp_utc"].min()),
            "timestamp_max_utc": str(df_clipped["timestamp_utc"].max()),
            "modified_cell_count": 0,
            "clipped_cell_count": 0,
            "imputed_cell_count": 0,
            "remaining_missing_count": int(df_clipped[signals].isna().sum().sum()),
            "carbon_quality_label": "quality_limited_sensitivity_only",
            "limitation": treatment_fit_info.get("reason", "Insufficient pre-target history"),
            "treatment_description": "Historical clipping bounds unsupported due to zero pre-target observations.",
        }
        return df_clipped, meta

    # When supported:
    clipping_bounds = treatment_fit_info["bounds"]
    clipped_cell_count = 0
    per_col_clipped: dict[str, int] = {}

    for sig in signals:
        if sig in df_clipped.columns and sig in clipping_bounds:
            low = clipping_bounds[sig]["lower_bound"]
            high = clipping_bounds[sig]["upper_bound"]

            orig_vals = df_clipped[sig].values
            is_clipped = (orig_vals < low) | (orig_vals > high)
            num_clipped = int(np.sum(is_clipped))
            clipped_cell_count += num_clipped
            per_col_clipped[sig] = num_clipped

            clipped_vals = np.clip(orig_vals, low, high)
            df_clipped[f"{sig}_orig"] = orig_vals
            df_clipped[f"{sig}_is_clipped"] = is_clipped
            df_clipped[sig] = clipped_vals

    meta = {
        "variant": "clipped",
        "status": "supported",
        "row_count": len(df_clipped),
        "timestamp_min_utc": str(df_clipped["timestamp_utc"].min()),
        "timestamp_max_utc": str(df_clipped["timestamp_utc"].max()),
        "modified_cell_count": clipped_cell_count,
        "clipped_cell_count": clipped_cell_count,
        "imputed_cell_count": 0,
        "per_column_clipped_count": per_col_clipped,
        "remaining_missing_count": int(df_clipped[signals].isna().sum().sum()),
        "carbon_quality_label": "quality_limited_sensitivity_only",
        "treatment_description": "Values outside 1st/99th percentiles clipped using historical bounds.",
    }
    return df_clipped, meta


def create_causal_imputed_variant(
    benchmark_df: pd.DataFrame,
    treatment_fit_info: dict[str, Any],
    signals: list[str] = TREATMENT_SIGNALS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create causal imputed variant.

    Rules:
    - Never backward fill.
    - Never borrow future target-window values.
    - Causal forward fill only within each continuous window.
    - If initial values are missing and pre-target median is unsupported,
      mark as unsupported_insufficient_pre_target_history.
    """
    df_imputed = benchmark_df.copy()
    fit_status = treatment_fit_info.get("status", "unsupported_insufficient_pre_target_history")

    # In benchmark_df, are there any missing values in signals?
    has_missing = bool(benchmark_df[signals].isna().any().any())

    if not has_missing:
        # Benchmark has complete observations (0 missing cells).
        # Forward fill / imputation has 0 cells to modify regardless of median availability.
        for sig in signals:
            df_imputed[f"{sig}_orig"] = df_imputed[sig].values
            df_imputed[f"{sig}_is_imputed"] = False
            df_imputed[f"{sig}_impute_source"] = "original_observation"

        meta = {
            "variant": "causal_imputed",
            "status": "supported",
            "row_count": len(df_imputed),
            "timestamp_min_utc": str(df_imputed["timestamp_utc"].min()),
            "timestamp_max_utc": str(df_imputed["timestamp_utc"].max()),
            "modified_cell_count": 0,
            "clipped_cell_count": 0,
            "imputed_cell_count": 0,
            "remaining_missing_count": 0,
            "carbon_quality_label": "quality_limited_sensitivity_only",
            "treatment_description": "Causal forward fill (0 missing values in benchmark table; 100% complete observations).",
        }
        return df_imputed, meta

    # If benchmark actually had missing values and fit is unsupported:
    if fit_status != "supported":
        meta = {
            "variant": "causal_imputed",
            "status": "unsupported_insufficient_pre_target_history",
            "row_count": len(df_imputed),
            "timestamp_min_utc": str(df_imputed["timestamp_utc"].min()),
            "timestamp_max_utc": str(df_imputed["timestamp_utc"].max()),
            "modified_cell_count": 0,
            "clipped_cell_count": 0,
            "imputed_cell_count": 0,
            "remaining_missing_count": int(df_imputed[signals].isna().sum().sum()),
            "carbon_quality_label": "quality_limited_sensitivity_only",
            "limitation": "Missing values present but pre-target historical median is unavailable.",
            "treatment_description": "Causal imputation unsupported due to missing pre-target history.",
        }
        return df_imputed, meta

    # When supported and missing values exist:
    fallback_medians = treatment_fit_info["medians"]
    imputed_cell_count = 0
    per_col_imputed: dict[str, int] = {}

    for sig in signals:
        if sig not in df_imputed.columns:
            continue

        imputed_flags = []
        impute_sources = []
        col_imputed_count = 0
        df_imputed[f"{sig}_orig"] = df_imputed[sig].values
        fallback_med = fallback_medians.get(sig, float("nan"))

        imputed_series_list = []
        for wid, grp in df_imputed.groupby("window_id", sort=False):
            grp_sorted = grp.sort_values("timestamp_utc")
            last_val = None
            series_vals = []

            for val in grp_sorted[sig].values:
                if pd.isna(val):
                    col_imputed_count += 1
                    if last_val is not None:
                        series_vals.append(last_val)
                        imputed_flags.append(True)
                        impute_sources.append("causal_forward_fill")
                    else:
                        series_vals.append(fallback_med)
                        imputed_flags.append(True)
                        impute_sources.append("historical_median_fallback")
                else:
                    series_vals.append(val)
                    last_val = val
                    imputed_flags.append(False)
                    impute_sources.append("original_observation")

            imputed_series_list.extend(series_vals)

        df_imputed[sig] = imputed_series_list
        df_imputed[f"{sig}_is_imputed"] = imputed_flags
        df_imputed[f"{sig}_impute_source"] = impute_sources
        per_col_imputed[sig] = col_imputed_count
        imputed_cell_count += col_imputed_count

    meta = {
        "variant": "causal_imputed",
        "status": "supported",
        "row_count": len(df_imputed),
        "timestamp_min_utc": str(df_imputed["timestamp_utc"].min()),
        "timestamp_max_utc": str(df_imputed["timestamp_utc"].max()),
        "modified_cell_count": imputed_cell_count,
        "clipped_cell_count": 0,
        "imputed_cell_count": imputed_cell_count,
        "per_column_imputed_count": per_col_imputed,
        "remaining_missing_count": int(df_imputed[signals].isna().sum().sum()),
        "carbon_quality_label": "quality_limited_sensitivity_only",
        "treatment_description": "Causal forward fill within window; pre-cutoff historical median fallback.",
    }
    return df_imputed, meta


def build_treatment_variants(
    benchmark_df: pd.DataFrame,
    history_df: pd.DataFrame,
    fit_cutoff_utc: str = EARLIEST_TARGET_ORIGIN_UTC,
    source_file_hash: str = "",
) -> dict[str, Any]:
    """Generate all 3 treatment variants with strict no-leakage verification."""
    fit_info = fit_historical_treatment_parameters(
        history_df=history_df,
        fit_cutoff_utc=fit_cutoff_utc,
        source_file_hash=source_file_hash,
    )

    df_raw, meta_raw = create_raw_variant(benchmark_df)
    df_clipped, meta_clipped = create_clipped_variant(benchmark_df, fit_info)
    df_imputed, meta_imputed = create_causal_imputed_variant(benchmark_df, fit_info)

    return {
        "variants": {
            "raw": df_raw,
            "clipped": df_clipped,
            "causal_imputed": df_imputed,
        },
        "metadata": {
            "raw": meta_raw,
            "clipped": meta_clipped,
            "causal_imputed": meta_imputed,
        },
        "treatment_fit_info": fit_info,
    }
