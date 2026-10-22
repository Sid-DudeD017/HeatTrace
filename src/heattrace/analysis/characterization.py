"""Characterization analysis for heatwave and control events (P5-01 / E1)."""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd
from scipy import stats


SIGNALS = [
    "temperature_c",
    "demand_mw",
    "net_generation_mw",
    "price_usd_per_mwh",
    "carbon_g_per_kwh",
]


def compute_distribution_summary(
    df: pd.DataFrame,
    group_cols: list[str],
    signals: list[str] = SIGNALS,
) -> pd.DataFrame:
    """Compute summary statistics (min, max, mean, median, std, quantiles, missing) per group and signal."""
    rows: list[dict[str, Any]] = []

    for group_vals, grp in df.groupby(group_cols, as_index=False):
        if not isinstance(group_vals, tuple):
            group_vals = (group_vals,)
        group_meta = dict(zip(group_cols, group_vals))

        for sig in signals:
            if sig not in grp.columns:
                continue
            s = grp[sig].dropna()
            missing_count = int(grp[sig].isna().sum())
            total_count = len(grp)
            valid_count = len(s)

            # Carbon quality counting
            if sig == "carbon_g_per_kwh":
                quality_limited_count = int(grp.get("carbon_data_issue", pd.Series([False]*len(grp))).sum())
                quality_eligible_count = int(grp.get("carbon_primary_analysis_eligible", pd.Series([False]*len(grp))).sum())
            else:
                quality_limited_count = 0
                quality_eligible_count = valid_count

            if valid_count > 0:
                min_v = float(s.min())
                max_v = float(s.max())
                mean_v = float(s.mean())
                med_v = float(s.median())
                std_v = float(s.std(ddof=1)) if valid_count > 1 else 0.0
                q25 = float(np.quantile(s, 0.25))
                q75 = float(np.quantile(s, 0.75))
                q90 = float(np.quantile(s, 0.90))
                q95 = float(np.quantile(s, 0.95))
            else:
                min_v = max_v = mean_v = med_v = std_v = q25 = q75 = q90 = q95 = float("nan")

            row = {
                **group_meta,
                "signal": sig,
                "total_hours": total_count,
                "valid_count": valid_count,
                "missing_count": missing_count,
                "quality_eligible_count": quality_eligible_count,
                "quality_limited_count": quality_limited_count,
                "min": round(min_v, 4),
                "max": round(max_v, 4),
                "mean": round(mean_v, 4),
                "median": round(med_v, 4),
                "std": round(std_v, 4),
                "q25": round(q25, 4),
                "q75": round(q75, 4),
                "q90": round(q90, 4),
                "q95": round(q95, 4),
            }
            rows.append(row)

    return pd.DataFrame(rows)


def compute_exceedance_and_persistence(
    df: pd.DataFrame,
    threshold_c: float = 25.60,
) -> pd.DataFrame:
    """Compute temperature threshold exceedance hours and persistence measures by window."""
    results: list[dict[str, Any]] = []

    for wid, grp in df.groupby("window_id"):
        grp_sorted = grp.sort_values("timestamp_utc")
        temps = grp_sorted["temperature_c"].values
        exceed_mask = temps > threshold_c
        exceed_hours = int(np.sum(exceed_mask))

        # Persistence: run lengths of consecutive exceedance hours
        run_lengths: list[int] = []
        cur_run = 0
        for is_ex in exceed_mask:
            if is_ex:
                cur_run += 1
            else:
                if cur_run > 0:
                    run_lengths.append(cur_run)
                    cur_run = 0
        if cur_run > 0:
            run_lengths.append(cur_run)

        max_persistence = max(run_lengths) if run_lengths else 0
        mean_persistence = float(np.mean(run_lengths)) if run_lengths else 0.0

        # Autocorrelation lag 1 for temperature and price
        def calc_autocorr(series_vals: np.ndarray) -> float:
            if len(series_vals) < 2:
                return float("nan")
            s = pd.Series(series_vals)
            return float(s.autocorr(lag=1))

        temp_autocorr_1 = calc_autocorr(temps)
        price_autocorr_1 = calc_autocorr(grp_sorted["price_usd_per_mwh"].values)
        demand_autocorr_1 = calc_autocorr(grp_sorted["demand_mw"].values)

        results.append({
            "window_id": wid,
            "window_type": str(grp_sorted["window_type"].iloc[0]),
            "duration_hours": len(grp_sorted),
            "threshold_temperature_c": threshold_c,
            "threshold_exceedance_hours": exceed_hours,
            "exceedance_fraction": round(exceed_hours / max(1, len(grp_sorted)), 4),
            "max_consecutive_exceedance_hours": max_persistence,
            "mean_consecutive_exceedance_hours": round(mean_persistence, 2),
            "temp_lag1_autocorrelation": round(temp_autocorr_1, 4),
            "price_lag1_autocorrelation": round(price_autocorr_1, 4),
            "demand_lag1_autocorrelation": round(demand_autocorr_1, 4),
        })

    return pd.DataFrame(results)


def compute_lagged_associations(
    df: pd.DataFrame,
    sig_x: str = "temperature_c",
    sig_y: str = "price_usd_per_mwh",
    max_lag: int = 24,
    min_valid_pairs: int = 15,
) -> pd.DataFrame:
    """Compute Pearson and Spearman associations over integer lags from -max_lag to +max_lag.

    Lag Definition:
      lag = k: Association between X(t) and Y(t + k).
      k > 0: X leads Y (e.g., temperature leads price by k hours).
      k < 0: Y leads X (e.g., price leads temperature by |k| hours).
      k = 0: Contemporaneous association X(t) and Y(t).
    """
    rows: list[dict[str, Any]] = []

    for wid, grp in df.groupby("window_id"):
        grp_sorted = grp.sort_values("timestamp_utc")
        x_vals = grp_sorted[sig_x].values
        y_vals = grp_sorted[sig_y].values
        n = len(grp_sorted)

        for lag in range(-max_lag, max_lag + 1):
            if lag > 0:
                # X(0 .. n-lag-1) paired with Y(lag .. n-1)
                x_sub = x_vals[:n - lag]
                y_sub = y_vals[lag:]
                direction = f"{sig_x}_leads_{sig_y}_by_{lag}h"
            elif lag < 0:
                # X(-lag .. n-1) paired with Y(0 .. n+lag-1)
                abs_lag = abs(lag)
                x_sub = x_vals[abs_lag:]
                y_sub = y_vals[:n - abs_lag]
                direction = f"{sig_y}_leads_{sig_x}_by_{abs_lag}h"
            else:
                x_sub = x_vals
                y_sub = y_vals
                direction = "contemporaneous_t0"

            # Filter valid pairs
            mask = (~np.isnan(x_sub)) & (~np.isnan(y_sub))
            valid_pairs = int(np.sum(mask))

            pearson_r = float("nan")
            pearson_p = float("nan")
            spearman_r = float("nan")
            spearman_p = float("nan")
            is_eligible = False
            limitation_reason = ""

            if valid_pairs < min_valid_pairs:
                is_eligible = False
                limitation_reason = f"Insufficient paired observations ({valid_pairs} < {min_valid_pairs})"
            else:
                x_clean = x_sub[mask]
                y_clean = y_sub[mask]
                # Check for constant variance
                if np.std(x_clean) < 1e-9 or np.std(y_clean) < 1e-9:
                    is_eligible = False
                    limitation_reason = "Zero variance in one or both paired signals"
                else:
                    is_eligible = True
                    limitation_reason = "None (descriptive/exploratory association)"
                    pr, pp = stats.pearsonr(x_clean, y_clean)
                    sr, sp = stats.spearmanr(x_clean, y_clean)
                    pearson_r = round(float(pr), 4)
                    pearson_p = round(float(pp), 6)
                    spearman_r = round(float(sr), 4)
                    spearman_p = round(float(sp), 6)

            rows.append({
                "window_id": wid,
                "signal_x": sig_x,
                "signal_y": sig_y,
                "lag_hours": lag,
                "lag_definition": f"association between {sig_x}(t) and {sig_y}(t + lag)",
                "lag_direction": direction,
                "valid_pairs_count": valid_pairs,
                "pearson_r": pearson_r,
                "pearson_p_value": pearson_p,
                "spearman_rho": spearman_r,
                "spearman_p_value": spearman_p,
                "is_eligible": is_eligible,
                "limitation_or_exclusion_reason": limitation_reason,
            })

    return pd.DataFrame(rows)


def run_event_characterization_pipeline(
    benchmark_df: pd.DataFrame,
    threshold_c: float = 25.60,
    max_lag: int = 24,
) -> dict[str, pd.DataFrame]:
    """Execute complete deterministic event characterization pipeline."""
    # 1. Hourly source table
    hourly_df = benchmark_df.copy().sort_values(["window_id", "timestamp_utc"]).reset_index(drop=True)

    # 2. Window summary table
    window_summary_df = compute_distribution_summary(hourly_df, group_cols=["window_id", "window_type"])

    # 3. Phase summary table
    phase_summary_df = compute_distribution_summary(hourly_df, group_cols=["window_id", "window_type", "phase_label"])

    # 4. Persistence and exceedance table
    persistence_df = compute_exceedance_and_persistence(hourly_df, threshold_c=threshold_c)

    # 5. Lag analysis: temperature vs price, temperature vs demand, demand vs price
    lag_pairs = [
        ("temperature_c", "price_usd_per_mwh"),
        ("temperature_c", "demand_mw"),
        ("demand_mw", "price_usd_per_mwh"),
        ("temperature_c", "carbon_g_per_kwh"),
    ]
    lag_dfs = []
    for sx, sy in lag_pairs:
        lag_df = compute_lagged_associations(hourly_df, sig_x=sx, sig_y=sy, max_lag=max_lag)
        lag_dfs.append(lag_df)
    lag_analysis_df = pd.concat(lag_dfs, ignore_index=True)

    return {
        "hourly_source_table": hourly_df,
        "window_summary_table": window_summary_df,
        "phase_summary_table": phase_summary_df,
        "persistence_table": persistence_df,
        "lag_analysis_table": lag_analysis_df,
    }
