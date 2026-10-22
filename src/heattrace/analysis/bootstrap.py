"""Statistical paired difference and bootstrap analysis (P5-10)."""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


def compute_paired_bootstrap_ci(
    diffs: np.ndarray,
    seed: int = 20261016,
    repetitions: int = 2000,
    confidence_level: float = 0.95,
) -> dict[str, float]:
    """Compute deterministic bootstrap confidence interval for the mean of paired differences."""
    n = len(diffs)
    if n == 0:
        return {
            "mean": float("nan"),
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
            "std_err": float("nan"),
        }

    rng = np.random.RandomState(seed)
    boot_means = np.empty(repetitions, dtype=float)

    for i in range(repetitions):
        sample = rng.choice(diffs, size=n, replace=True)
        boot_means[i] = np.mean(sample)

    alpha = 1.0 - confidence_level
    ci_low = float(np.percentile(boot_means, 100 * (alpha / 2.0)))
    ci_high = float(np.percentile(boot_means, 100 * (1.0 - alpha / 2.0)))
    std_err = float(np.std(boot_means, ddof=1)) if repetitions > 1 else 0.0

    return {
        "mean": float(np.mean(diffs)),
        "ci_lower": round(ci_low, 4),
        "ci_upper": round(ci_high, 4),
        "std_err": round(std_err, 4),
    }


def compute_paired_metrics_differences(
    event_metrics: dict[str, Any],
    control_metrics: dict[str, Any],
    metric_keys: list[str] | None = None,
    seed: int = 20261016,
    repetitions: int = 2000,
) -> list[dict[str, Any]]:
    """Compute differences between genuinely paired event and control metrics."""
    if metric_keys is None:
        metric_keys = [
            "total_realized_cost_usd",
            "total_realized_emissions_kg",
            "sla_completion_rate",
            "cvar_cost_90",
            "cvar_emissions_90",
            "max_cluster_power_kw",
            "max_concurrent_jobs",
            "unmet_energy_kwh",
            "violation_count",
        ]

    rows: list[dict[str, Any]] = []

    for k in metric_keys:
        ev_val = event_metrics.get(k)
        ctrl_val = control_metrics.get(k)

        if ev_val is None or ctrl_val is None:
            continue

        raw_diff = float(ev_val) - float(ctrl_val)
        # Note: across single 120h windows, n=1 paired instance per policy.
        # With n=1, bootstrap CI equals the single point estimate.
        rows.append({
            "metric": k,
            "event_value": float(ev_val),
            "control_value": float(ctrl_val),
            "raw_difference": round(raw_diff, 4),
            "valid_pairs_count": 1,
            "status": "descriptive_single_pair",
            "limitation": "Single 120h benchmark window pair; inferential p-values unsupported, report as descriptive.",
        })

    return rows


def compute_hourly_paired_signal_differences(
    benchmark_df: pd.DataFrame,
    seed: int = 20261016,
    repetitions: int = 2000,
) -> pd.DataFrame:
    """Compute paired differences across the 120 matched hourly timepoints of event vs control."""
    ctrl_df = benchmark_df[benchmark_df["window_id"] == "CTRL_20240605"].sort_values("timestamp_utc").reset_index(drop=True)
    hw_df = benchmark_df[benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)

    signals = [
        "temperature_c",
        "demand_mw",
        "net_generation_mw",
        "price_usd_per_mwh",
        "carbon_g_per_kwh",
    ]

    rows: list[dict[str, Any]] = []
    n = min(len(ctrl_df), len(hw_df))

    for sig in signals:
        diffs = hw_df[sig].values[:n] - ctrl_df[sig].values[:n]
        valid_mask = ~np.isnan(diffs)
        clean_diffs = diffs[valid_mask]
        n_valid = len(clean_diffs)

        if n_valid > 0:
            mean_diff = float(np.mean(clean_diffs))
            med_diff = float(np.median(clean_diffs))
            ci = compute_paired_bootstrap_ci(clean_diffs, seed=seed, repetitions=repetitions)

            # Effect size (Cohen's d for paired differences)
            std_diff = float(np.std(clean_diffs, ddof=1)) if n_valid > 1 else 0.0
            cohens_d = round(mean_diff / std_diff, 4) if std_diff > 1e-9 else 0.0

            rows.append({
                "signal": sig,
                "valid_pairs_count": n_valid,
                "mean_paired_difference": round(mean_diff, 4),
                "median_paired_difference": round(med_diff, 4),
                "std_paired_difference": round(std_diff, 4),
                "bootstrap_ci_95_lower": ci["ci_lower"],
                "bootstrap_ci_95_upper": ci["ci_upper"],
                "bootstrap_std_err": ci["std_err"],
                "cohens_d": cohens_d,
                "carbon_quality": "quality_limited_sensitivity_only" if sig == "carbon_g_per_kwh" else "primary_eligible",
                "inferential_status": "exploratory_paired_hourly",
            })

    return pd.DataFrame(rows)
