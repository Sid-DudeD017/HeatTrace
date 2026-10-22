"""Statistical paired difference and block-bootstrap analysis (P5-10)."""

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
    """Compute deterministic bootstrap confidence interval for paired differences."""
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


def compute_block_bootstrap_ci(
    hourly_diffs: np.ndarray,
    block_length_hours: int = 24,
    seed: int = 20261016,
    repetitions: int = 2000,
    confidence_level: float = 0.95,
) -> dict[str, float]:
    """Compute moving-block bootstrap confidence interval to account for serial dependence.

    Uses 24-hour diurnal blocks.
    """
    n = len(hourly_diffs)
    if n < block_length_hours:
        return compute_paired_bootstrap_ci(hourly_diffs, seed=seed, repetitions=repetitions, confidence_level=confidence_level)

    num_blocks = int(np.ceil(n / block_length_hours))
    # Extract all possible overlapping contiguous blocks of length block_length_hours
    max_start = n - block_length_hours + 1
    blocks = [hourly_diffs[i : i + block_length_hours] for i in range(max_start)]

    rng = np.random.RandomState(seed)
    boot_means = np.empty(repetitions, dtype=float)

    for i in range(repetitions):
        chosen_indices = rng.choice(len(blocks), size=num_blocks, replace=True)
        sampled_series = np.concatenate([blocks[idx] for idx in chosen_indices])[:n]
        boot_means[i] = np.mean(sampled_series)

    alpha = 1.0 - confidence_level
    ci_low = float(np.percentile(boot_means, 100 * (alpha / 2.0)))
    ci_high = float(np.percentile(boot_means, 100 * (1.0 - alpha / 2.0)))
    std_err = float(np.std(boot_means, ddof=1)) if repetitions > 1 else 0.0

    return {
        "mean": float(np.mean(hourly_diffs)),
        "ci_lower": round(ci_low, 4),
        "ci_upper": round(ci_high, 4),
        "std_err": round(std_err, 4),
        "block_length_hours": block_length_hours,
    }


def compute_policy_paired_differences(
    df_metrics: pd.DataFrame,
    hourly_outcomes: dict[tuple[str, str], pd.DataFrame] | None = None,
    seed: int = 20261016,
    repetitions: int = 2000,
) -> pd.DataFrame:
    """Compute paired policy performance differences between event and matched control windows.

    Evaluates across all policies for:
    - realized cost
    - realized emissions
    - SLA completion
    - CVaR cost
    - CVaR emissions
    - peak power
    - peak concurrency
    - unmet energy
    - deadline misses
    - operational/constraint violations

    Limitation: Exactly one aggregate 120h event/control window pair per policy.
    Inferential status labeled 'descriptive_single_window_pair'.
    When hourly outcomes exist, block-bootstrap (24h blocks) is calculated as exploratory.
    """
    policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]
    rows: list[dict[str, Any]] = []

    metrics_list = [
        ("total_realized_cost_usd", "cost_usd", True),
        ("total_realized_emissions_kg", "emissions_kg", True),
        ("sla_completion_rate", "sla_completion", False),
        ("cvar_cost_90", "cvar_cost_90", True),
        ("cvar_emissions_90", "cvar_emissions_90", True),
        ("max_cluster_power_kw", "peak_power_kw", True),
        ("max_concurrent_jobs", "peak_concurrency", False),
        ("unmet_energy_kwh", "unmet_energy_kwh", False),
        ("deadline_misses", "deadline_misses", False),
        ("violation_count", "violation_count", False),
    ]

    for pol in policies:
        ev_row = df_metrics[(df_metrics["policy_name"] == pol) & (df_metrics["window_id"] == "HW_20240702")]
        ctrl_row = df_metrics[(df_metrics["policy_name"] == pol) & (df_metrics["window_id"] == "CTRL_20240605")]

        if ev_row.empty or ctrl_row.empty:
            continue

        ev = ev_row.iloc[0]
        ctrl = ctrl_row.iloc[0]

        for col_name, label, pct_meaningful in metrics_list:
            ev_val = float(ev.get(col_name, 0.0))
            ctrl_val = float(ctrl.get(col_name, 0.0))
            raw_diff = ev_val - ctrl_val

            if pct_meaningful and abs(ctrl_val) > 1e-4:
                pct_diff = round(((ev_val - ctrl_val) / ctrl_val) * 100.0, 2)
            else:
                pct_diff = None

            # Check if hourly outcomes exist for block-bootstrap of hourly metrics
            hourly_ci_low = float("nan")
            hourly_ci_high = float("nan")
            hourly_std_err = float("nan")

            if hourly_outcomes is not None and col_name in ["total_realized_cost_usd", "total_realized_emissions_kg"]:
                ev_hourly = hourly_outcomes.get(("HW_20240702", pol))
                ctrl_hourly = hourly_outcomes.get(("CTRL_20240605", pol))
                if ev_hourly is not None and ctrl_hourly is not None:
                    h_col = "hourly_cost_usd" if "cost" in col_name else "hourly_emissions_kg"
                    diff_series = ev_hourly[h_col].values - ctrl_hourly[h_col].values
                    block_ci = compute_block_bootstrap_ci(diff_series, block_length_hours=24, seed=seed, repetitions=repetitions)
                    hourly_ci_low = block_ci["ci_lower"]
                    hourly_ci_high = block_ci["ci_upper"]
                    hourly_std_err = block_ci["std_err"]

            rows.append({
                "policy_name": pol,
                "metric": label,
                "event_window_id": "HW_20240702",
                "control_window_id": "CTRL_20240605",
                "event_value": round(ev_val, 4),
                "control_value": round(ctrl_val, 4),
                "raw_difference": round(raw_diff, 4),
                "percentage_difference": pct_diff,
                "hourly_block_bootstrap_ci_95_lower": hourly_ci_low,
                "hourly_block_bootstrap_ci_95_upper": hourly_ci_high,
                "hourly_block_bootstrap_std_err": hourly_std_err,
                "valid_pairs_count": 1,
                "inferential_status": "descriptive_single_window_pair",
                "limitation_or_exclusion_reason": (
                    "Single 120h event/control window pair; aggregate inferential p-values unsupported. "
                    "Hourly block-bootstrap uses 24h blocks and is exploratory."
                ),
                "carbon_quality_label": "quality_limited_sensitivity_only" if "emissions" in label else "primary_eligible",
            })

    return pd.DataFrame(rows)


def compute_hourly_paired_signal_differences(
    benchmark_df: pd.DataFrame,
    seed: int = 20261016,
    repetitions: int = 2000,
) -> pd.DataFrame:
    """Compute paired differences across the 120 matched hourly physical observations."""
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
            # Use block bootstrap (24h blocks) for physical signals due to diurnal cycle
            ci = compute_block_bootstrap_ci(clean_diffs, block_length_hours=24, seed=seed, repetitions=repetitions)

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
                "inferential_status": "exploratory_paired_hourly_block_bootstrap",
                "limitation": "Repeated hourly observations within one matched 120h pair (not 120 independent events).",
            })

    return pd.DataFrame(rows)
