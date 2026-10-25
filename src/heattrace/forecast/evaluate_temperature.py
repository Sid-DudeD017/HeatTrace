"""Evaluation and Forecast Gate calculation for HeatTrace Phase 4."""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from heattrace.forecast.tiny_lstm import (
    forecast_ewma,
    forecast_last_observation,
    forecast_same_hour_previous_day,
)


def compute_forecast_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    extreme_p95_threshold: float,
) -> dict[str, float]:
    """Compute overall MAE, overall RMSE, horizon-specific errors, and extreme underprediction.

    Parameters:
    - y_true: shape [N, 24] unscaled ground truth degrees C
    - y_pred: shape [N, 24] unscaled predictions degrees C
    - extreme_p95_threshold: 95th percentile threshold computed strictly from training data

    Returns dictionary with:
    - mae
    - rmse
    - mae_h1, mae_h6, mae_h12, mae_h24
    - rmse_h1, rmse_h6, rmse_h12, rmse_h24
    - extreme_underprediction_mae
    """
    y_t = np.asarray(y_true, dtype=np.float64)
    y_p = np.asarray(y_pred, dtype=np.float64)

    if y_t.shape != y_p.shape:
        raise ValueError(f"Shape mismatch: y_true {y_t.shape} vs y_pred {y_p.shape}")

    n_samples, horizon = y_t.shape
    errors = y_p - y_t
    abs_errors = np.abs(errors)
    sq_errors = errors ** 2

    overall_mae = float(np.mean(abs_errors))
    overall_rmse = float(np.sqrt(np.mean(sq_errors)))

    horizons_to_eval = [1, 6, 12, 24]
    metrics: dict[str, float] = {
        "mae": round(overall_mae, 4),
        "rmse": round(overall_rmse, 4),
    }

    for h in horizons_to_eval:
        idx = h - 1
        if idx < horizon:
            h_mae = float(np.mean(abs_errors[:, idx]))
            h_rmse = float(np.sqrt(np.mean(sq_errors[:, idx])))
            metrics[f"mae_h{h}"] = round(h_mae, 4)
            metrics[f"rmse_h{h}"] = round(h_rmse, 4)
        else:
            metrics[f"mae_h{h}"] = float("nan")
            metrics[f"rmse_h{h}"] = float("nan")

    # Extreme temperature underprediction:
    extreme_mask = y_t >= extreme_p95_threshold
    underpred_mask = extreme_mask & (y_p < y_t)
    if np.any(underpred_mask):
        extreme_underpred_mae = float(np.mean(y_t[underpred_mask] - y_p[underpred_mask]))
    else:
        extreme_underpred_mae = 0.0

    metrics["extreme_underprediction_mae"] = round(extreme_underpred_mae, 4)
    return metrics


def evaluate_all_forecast_methods(
    X: np.ndarray,
    y: np.ndarray,
    scaler_mean: float,
    scaler_std: float,
    extreme_p95_threshold: float,
    lstm_predictions: np.ndarray | None = None,
    split_label: str = "validation",
    triplet_id: str = "none",
    context: str = "none",
) -> pd.DataFrame:
    """Evaluate TinyLSTM and three causal baselines on the same set of windows."""
    raw_hist_temp = X[:, :, 0] * scaler_std + scaler_mean

    pred_last = forecast_last_observation(raw_hist_temp, horizon=24)
    pred_prev_day = forecast_same_hour_previous_day(raw_hist_temp, horizon=24)
    pred_ewma = forecast_ewma(raw_hist_temp, alpha=0.20, horizon=24)

    candidates = {
        "last_observation": pred_last,
        "same_hour_previous_day": pred_prev_day,
        "ewma_0.20": pred_ewma,
    }
    if lstm_predictions is not None:
        candidates["TinyTemperatureLSTM"] = lstm_predictions

    rows = []
    for name, preds in candidates.items():
        m = compute_forecast_metrics(y, preds, extreme_p95_threshold)
        m["model"] = name
        m["split"] = split_label
        m["triplet_id"] = triplet_id
        m["context"] = context
        rows.append(m)

    df = pd.DataFrame(rows)
    cols = [
        "model",
        "split",
        "triplet_id",
        "context",
        "mae",
        "rmse",
        "mae_h1",
        "rmse_h1",
        "mae_h6",
        "rmse_h6",
        "mae_h12",
        "rmse_h12",
        "mae_h24",
        "rmse_h24",
        "extreme_underprediction_mae",
    ]
    return df[cols]


def calculate_forecast_gate(
    val_metrics_df: pd.DataFrame,
    correctness_check_passed: bool = True,
    reason: str = "",
) -> dict[str, Any]:
    """Calculate the frozen forecast gate decision from validation metrics only."""
    if not correctness_check_passed:
        return {
            "decision": "STOP",
            "reason": f"Correctness check failed: {reason}",
            "best_baseline": None,
            "selected_provider": None,
            "details": {},
        }

    baselines = val_metrics_df[val_metrics_df["model"] != "TinyTemperatureLSTM"]
    lstm_rows = val_metrics_df[val_metrics_df["model"] == "TinyTemperatureLSTM"]

    if lstm_rows.empty:
        return {
            "decision": "STOP",
            "reason": "TinyTemperatureLSTM metrics missing from validation evaluation.",
            "best_baseline": None,
            "selected_provider": None,
            "details": {},
        }

    best_baseline_row = baselines.sort_values(by="rmse").iloc[0]
    best_baseline_name = str(best_baseline_row["model"])
    best_baseline_rmse = float(best_baseline_row["rmse"])
    best_baseline_extreme = float(best_baseline_row["extreme_underprediction_mae"])

    lstm_row = lstm_rows.iloc[0]
    lstm_rmse = float(lstm_row["rmse"])
    lstm_extreme = float(lstm_row["extreme_underprediction_mae"])

    if not (np.isfinite(lstm_rmse) and np.isfinite(best_baseline_rmse)):
        return {
            "decision": "STOP",
            "reason": "Non-finite validation metric encountered.",
            "best_baseline": best_baseline_name,
            "selected_provider": None,
            "details": {},
        }

    rmse_improvement = (best_baseline_rmse - lstm_rmse) / best_baseline_rmse

    if best_baseline_extreme > 1e-6:
        extreme_improvement = (best_baseline_extreme - lstm_extreme) / best_baseline_extreme
    else:
        extreme_improvement = 0.0

    cond1 = rmse_improvement >= 0.02
    cond2 = (extreme_improvement >= 0.05) and (rmse_improvement >= -0.02)

    details = {
        "best_baseline": best_baseline_name,
        "best_baseline_rmse": best_baseline_rmse,
        "best_baseline_extreme_mae": best_baseline_extreme,
        "lstm_rmse": lstm_rmse,
        "lstm_extreme_mae": lstm_extreme,
        "rmse_improvement_pct": round(rmse_improvement * 100.0, 2),
        "extreme_improvement_pct": round(extreme_improvement * 100.0, 2),
        "cond1_rmse_ge_2pct": bool(cond1),
        "cond2_extreme_ge_5pct_and_rmse_ge_minus_2pct": bool(cond2),
    }

    if cond1 or cond2:
        return {
            "decision": "GO",
            "reason": f"GO criteria met (cond1={cond1}, cond2={cond2}).",
            "best_baseline": best_baseline_name,
            "selected_provider": "TinyTemperatureLSTM",
            "details": details,
        }
    else:
        return {
            "decision": "PIVOT",
            "reason": "Correctness verified, but TinyLSTM did not outperform best baseline by required margins. Pivoting to best simple baseline.",
            "best_baseline": best_baseline_name,
            "selected_provider": best_baseline_name,
            "details": details,
        }
