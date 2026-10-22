"""Deterministic data treatment variants generator (P5-02 / E3).

Produces 3 variants without modifying upstream files:
1. raw: Baseline unmodified benchmark data.
2. clipped: 1st and 99th percentiles fitted strictly from pre-origin/historical data.
3. causal_imputed: Causal forward fill (never backward fill; fallback to pre-origin median).
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


def fit_historical_clipping_bounds(
    history_df: pd.DataFrame,
    signals: list[str] = TREATMENT_SIGNALS,
    lower_pct: float = 1.0,
    upper_pct: float = 99.0,
) -> dict[str, dict[str, float]]:
    """Fit clipping bounds strictly from historical pre-target data.

    Returns mapping: signal -> {"lower": float, "upper": float, "source_n": int}
    """
    bounds: dict[str, dict[str, float]] = {}
    for sig in signals:
        if sig in history_df.columns:
            s = history_df[sig].dropna()
            if not s.empty:
                low = float(np.percentile(s, lower_pct))
                high = float(np.percentile(s, upper_pct))
                bounds[sig] = {
                    "lower_bound": round(low, 4),
                    "upper_bound": round(high, 4),
                    "source_rows": len(s),
                }
            else:
                bounds[sig] = {"lower_bound": float("-inf"), "upper_bound": float("inf"), "source_rows": 0}
        else:
            bounds[sig] = {"lower_bound": float("-inf"), "upper_bound": float("inf"), "source_rows": 0}
    return bounds


def fit_historical_medians(
    history_df: pd.DataFrame,
    signals: list[str] = TREATMENT_SIGNALS,
) -> dict[str, float]:
    """Fit baseline medians strictly from historical data for fallback imputation."""
    medians: dict[str, float] = {}
    for sig in signals:
        if sig in history_df.columns:
            s = history_df[sig].dropna()
            if not s.empty:
                medians[sig] = round(float(s.median()), 4)
            else:
                medians[sig] = 0.0
        else:
            medians[sig] = 0.0
    return medians


def create_raw_variant(benchmark_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create raw unmodified variant."""
    df_raw = benchmark_df.copy()
    meta = {
        "variant": "raw",
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
    clipping_bounds: dict[str, dict[str, float]],
    signals: list[str] = TREATMENT_SIGNALS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create clipped variant using pre-fitted historical bounds.

    Original values and quality flags are strictly preserved in original columns.
    New clipped columns and flags are added: `<sig>_clipped`, `<sig>_is_clipped`.
    """
    df_clipped = benchmark_df.copy()
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

            # Preserve original value; update signal in-place for the variant and record flag
            clipped_vals = np.clip(orig_vals, low, high)
            df_clipped[f"{sig}_orig"] = orig_vals
            df_clipped[f"{sig}_is_clipped"] = is_clipped
            df_clipped[sig] = clipped_vals

    meta = {
        "variant": "clipped",
        "row_count": len(df_clipped),
        "timestamp_min_utc": str(df_clipped["timestamp_utc"].min()),
        "timestamp_max_utc": str(df_clipped["timestamp_utc"].max()),
        "modified_cell_count": clipped_cell_count,
        "clipped_cell_count": clipped_cell_count,
        "imputed_cell_count": 0,
        "per_column_clipped_count": per_col_clipped,
        "fitted_bounds": clipping_bounds,
        "remaining_missing_count": int(df_clipped[signals].isna().sum().sum()),
        "carbon_quality_label": "quality_limited_sensitivity_only",
        "treatment_description": "Values outside 1st/99th percentiles clipped using historical bounds.",
    }
    return df_clipped, meta


def create_causal_imputed_variant(
    benchmark_df: pd.DataFrame,
    fallback_medians: dict[str, float],
    signals: list[str] = TREATMENT_SIGNALS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create causal imputed variant.

    Rules:
    - Never backward fill.
    - Never borrow future target-window values.
    - Causal forward fill only within each continuous window.
    - If initial values are missing, use frozen historical median.
    - Track imputation method and source per cell.
    - Original missing flags and source quality flags are preserved.
    """
    df_imputed = benchmark_df.copy()
    imputed_cell_count = 0
    per_col_imputed: dict[str, int] = {}

    for sig in signals:
        if sig not in df_imputed.columns:
            continue

        imputed_flags = []
        impute_sources = []
        col_imputed_count = 0

        # Preserve original values
        df_imputed[f"{sig}_orig"] = df_imputed[sig].values
        fallback_med = fallback_medians.get(sig, 0.0)

        # Process per window independently to prevent cross-window leakage
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
        "row_count": len(df_imputed),
        "timestamp_min_utc": str(df_imputed["timestamp_utc"].min()),
        "timestamp_max_utc": str(df_imputed["timestamp_utc"].max()),
        "modified_cell_count": imputed_cell_count,
        "clipped_cell_count": 0,
        "imputed_cell_count": imputed_cell_count,
        "per_column_imputed_count": per_col_imputed,
        "fallback_medians": fallback_medians,
        "remaining_missing_count": int(df_imputed[signals].isna().sum().sum()),
        "carbon_quality_label": "quality_limited_sensitivity_only",
        "treatment_description": "Causal forward fill within window; frozen historical median fallback.",
    }
    return df_imputed, meta


def build_treatment_variants(
    benchmark_df: pd.DataFrame,
    history_df: pd.DataFrame,
) -> dict[str, Any]:
    """Generate all 3 treatment variants and their metadata."""
    # Fit historical bounds and medians strictly from historical pre-target data
    bounds = fit_historical_clipping_bounds(history_df)
    medians = fit_historical_medians(history_df)

    df_raw, meta_raw = create_raw_variant(benchmark_df)
    df_clipped, meta_clipped = create_clipped_variant(benchmark_df, bounds)
    df_imputed, meta_imputed = create_causal_imputed_variant(benchmark_df, medians)

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
        "history_bounds": bounds,
        "history_medians": medians,
    }
