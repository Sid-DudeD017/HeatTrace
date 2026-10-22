"""Forecast scenarios for P5.5: Flat authentic baseline, Perfect oracle, and Seeded noisy oracle.

LABELS & METHODOLOGICAL CONTRACT:
- Flat forecast (original 1x, unconstrained, baseline deadline): authentic_historical_baseline
- Flat forecast (stressed settings): controlled_simulation_flat_forecast
- Perfect-information oracle: controlled_hindsight_upper_bound (never a deployable forecast)
- Seeded noisy oracle: controlled_simulation_noisy_oracle
- Forecast inputs and realized scoring fields remain structurally separate.
- Forecast noise seed is strictly isolated from workload/capacity/deadline stress parameters.
"""

from __future__ import annotations

import hashlib
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.interfaces import ForecastPoint, ForecastResult


def generate_flat_forecast(
    realized_window_df: pd.DataFrame,
    *,
    fallback_price: float = 45.0,
    fallback_carbon: float = 220.0,
) -> ForecastResult:
    """Generate flat persistence forecast matching authentic P5 baseline.
    
    Produces static projections across the horizon.
    """
    sorted_df = realized_window_df.sort_values("timestamp_utc").reset_index(drop=True)
    origin_ts = pd.to_datetime(sorted_df["timestamp_utc"].iloc[0], utc=True).to_pydatetime()
    horizon = len(sorted_df)

    wid = sorted_df["window_id"].iloc[0]
    if wid == "CTRL_20240605":
        p_val = fallback_price
        c_val = fallback_carbon
    else:
        # Pre-origin persistence from control window (matching P4/P5 authentic baseline)
        p_val = 28.98081
        c_val = 87.18878487

    pts = []
    for h in range(horizon):
        target_ts = origin_ts + pd.Timedelta(hours=h)
        target_dt = target_ts.to_pydatetime() if isinstance(target_ts, pd.Timestamp) else target_ts
        pts.append(
            ForecastPoint(
                timestamp_utc=target_dt,
                horizon_hours=h,
                predicted_price_usd_per_mwh=float(p_val),
                predicted_carbon_g_per_kwh=float(c_val),
            )
        )

    return ForecastResult(
        origin_timestamp_utc=origin_ts,
        points=pts,
        model_name="flat_forecast",
        model_version="2.0-persistence",
    )


def generate_oracle_forecast(
    realized_window_df: pd.DataFrame,
) -> ForecastResult:
    """Generate perfect-information oracle forecast using realized values.
    
    LABEL: controlled_hindsight_upper_bound
    NOTE: For controlled hindsight benchmarking only. Not a deployable forecasting model.
    """
    sorted_df = realized_window_df.sort_values("timestamp_utc").reset_index(drop=True)
    origin_ts = pd.to_datetime(sorted_df["timestamp_utc"].iloc[0], utc=True).to_pydatetime()
    horizon = len(sorted_df)

    pts = []
    for h, row in sorted_df.iterrows():
        target_ts = pd.to_datetime(row["timestamp_utc"], utc=True).to_pydatetime()
        pts.append(
            ForecastPoint(
                timestamp_utc=target_ts,
                horizon_hours=h,
                predicted_price_usd_per_mwh=float(row["price_usd_per_mwh"]),
                predicted_carbon_g_per_kwh=float(row["carbon_g_per_kwh"]),
            )
        )

    return ForecastResult(
        origin_timestamp_utc=origin_ts,
        points=pts,
        model_name="oracle_forecast",
        model_version="2.0-controlled-hindsight",
    )


def compute_forecast_seed(
    base_seed: int,
    window_id: str,
    forecast_scenario_id: str,
    replicate_id: int = 0,
) -> int:
    """Derive isolated deterministic forecast seed dependent ONLY on base seed, window, and forecast scenario.

    Strictly independent of workload, capacity, and deadline settings.
    """
    key = f"{base_seed}_{window_id}_{forecast_scenario_id}_rep{replicate_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def generate_noisy_oracle_forecast(
    realized_window_df: pd.DataFrame,
    *,
    noise_sigma: float,
    seed: int,
    noise_scenario_id: str = "noisy_oracle",
) -> tuple[ForecastResult, dict[str, float], str]:
    """Generate deterministic seeded perturbation of the realized signal.
    
    LABEL: controlled_simulation_noisy_oracle
    Model:
      predicted_price = actual_price * (1 + N(0, noise_sigma))
      predicted_carbon = actual_carbon * (1 + N(0, noise_sigma))
      Clipping:
      carbon >= 0.0 g/kWh.
      price bounded below at min(-100.0, actual_min - 10.0).
    Returns (forecast_result, error_metrics, forecast_points_sha256).
    """
    if noise_sigma < 0:
        raise ValueError(f"noise_sigma must be >= 0, got {noise_sigma}")

    sorted_df = realized_window_df.sort_values("timestamp_utc").reset_index(drop=True)
    origin_ts = pd.to_datetime(sorted_df["timestamp_utc"].iloc[0], utc=True).to_pydatetime()
    horizon = len(sorted_df)

    rng = np.random.default_rng(seed)

    actual_prices = sorted_df["price_usd_per_mwh"].to_numpy(dtype=float)
    actual_carbons = sorted_df["carbon_g_per_kwh"].to_numpy(dtype=float)

    if noise_sigma == 0.0:
        price_noise = np.zeros(horizon)
        carbon_noise = np.zeros(horizon)
    else:
        price_noise = rng.normal(0.0, noise_sigma, horizon)
        carbon_noise = rng.normal(0.0, noise_sigma, horizon)

    pred_prices = actual_prices * (1.0 + price_noise)
    pred_carbons = actual_carbons * (1.0 + carbon_noise)

    # Physical clipping
    pred_carbons = np.maximum(0.0, pred_carbons)
    min_price_bound = min(-100.0, float(np.min(actual_prices)) - 10.0)
    pred_prices = np.maximum(min_price_bound, pred_prices)

    pts = []
    points_repr = []
    for h, row in sorted_df.iterrows():
        target_ts = pd.to_datetime(row["timestamp_utc"], utc=True).to_pydatetime()
        p_val = float(round(pred_prices[h], 4))
        c_val = float(round(pred_carbons[h], 4))
        pts.append(
            ForecastPoint(
                timestamp_utc=target_ts,
                horizon_hours=h,
                predicted_price_usd_per_mwh=p_val,
                predicted_carbon_g_per_kwh=c_val,
            )
        )
        points_repr.append(f"{h}:{p_val:.4f}:{c_val:.4f}")

    forecast_hash = hashlib.sha256(",".join(points_repr).encode("utf-8")).hexdigest()

    mae_price = float(np.mean(np.abs(pred_prices - actual_prices)))
    mae_carbon = float(np.mean(np.abs(pred_carbons - actual_carbons)))
    bias_price = float(np.mean(pred_prices - actual_prices))
    bias_carbon = float(np.mean(pred_carbons - actual_carbons))

    error_metrics = {
        "forecast_price_mae": round(mae_price, 4),
        "forecast_carbon_mae": round(mae_carbon, 4),
        "forecast_price_bias": round(bias_price, 4),
        "forecast_carbon_bias": round(bias_carbon, 4),
        "noise_sigma": noise_sigma,
    }

    result = ForecastResult(
        origin_timestamp_utc=origin_ts,
        points=pts,
        model_name=f"{noise_scenario_id}_sigma_{noise_sigma:.2f}",
        model_version="2.0-controlled-simulation",
    )
    return result, error_metrics, forecast_hash
