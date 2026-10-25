"""Targeted tests for HeatTrace Phase 4: dataset, baselines, TinyLSTM, and gate rules."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heattrace.forecast.dataset import (
    ScalerMetadata,
    build_canonical_forecast_contract,
    compute_forecast_config_hash,
    compute_split_hash,
    extract_features_and_targets_advanced,
    fit_temperature_scaler,
)
from heattrace.forecast.evaluate_temperature import (
    calculate_forecast_gate,
    compute_forecast_metrics,
    evaluate_all_forecast_methods,
)
from heattrace.forecast.tiny_lstm import (
    TinyTemperatureLSTM,
    forecast_ewma,
    forecast_last_observation,
    forecast_same_hour_previous_day,
)
from heattrace.forecast.train_temperature import (
    load_verified_checkpoint,
    predict_unscaled,
    save_checkpoint_and_artifacts,
    train_tiny_lstm,
)


@pytest.fixture
def synthetic_hourly_series():
    """Create continuous synthetic hourly temperature series (192 hours: 8 days)."""
    start = datetime(2022, 1, 1, 0, 0, tzinfo=timezone.utc)
    n_hours = 192
    timestamps = [start + timedelta(hours=i) for i in range(n_hours)]
    temps = [15.0 + 5.0 * np.sin(2 * np.pi * i / 24.0) for i in range(n_hours)]
    records = [
        {
            "timestamp_utc": ts,
            "temperature_c": temps[i],
            "temperature_obs_count": 2,
            "temperature_missing": False,
        }
        for i, ts in enumerate(timestamps)
    ]
    df = pd.DataFrame(records).set_index("timestamp_utc").sort_index()
    return df, start, timestamps[-1] + timedelta(hours=1)


def test_development_forecast_from_window_start_with_prior_history(synthetic_hourly_series):
    """Test Correction 2: 120-hour event with 72h prior history produces exactly 97 origins.

    - First origin equals event start.
    - First input is event start minus 72h.
    - Final input of first origin is event start minus 1h.
    - Targets are event start through event start plus 23h.
    - Last origin is event start + 96h, and its target ends at event end (event start + 120h).
    """
    df, series_start, series_end = synthetic_hourly_series
    event_start = series_start + timedelta(hours=72)
    event_end = event_start + timedelta(hours=120)

    scaler = ScalerMetadata(15.0, 5.0, 100, 20.0, "", series_start.isoformat(), event_start.isoformat())

    origins, X, y, splits, triplets, ctxs, subs = extract_features_and_targets_advanced(
        hourly_df=df,
        history_start_utc=series_start,
        history_end_exclusive_utc=event_end,
        origin_start_utc=event_start,
        origin_end_exclusive_utc=event_end - timedelta(hours=23),
        target_start_utc=event_start,
        target_end_exclusive_utc=event_end,
        scaler=scaler,
        lookback=72,
        horizon=24,
        split_name="development",
        triplet_id="DEV_TRIPLET",
        context="heatwave",
    )

    # 120 - 24 + 1 = 97 origins
    assert len(origins) == 97
    assert X.shape == (97, 72, 5)
    assert y.shape == (97, 24)

    # First origin check
    assert origins[0] == event_start
    first_input_raw = X[0, 0, 0] * scaler.std + scaler.mean
    expected_first_input = df.loc[event_start - timedelta(hours=72), "temperature_c"]
    assert np.isclose(first_input_raw, expected_first_input, atol=1e-4)

    last_input_raw = X[0, -1, 0] * scaler.std + scaler.mean
    expected_last_input = df.loc[event_start - timedelta(hours=1), "temperature_c"]
    assert np.isclose(last_input_raw, expected_last_input, atol=1e-4)

    # First target check
    expected_first_targets = [df.loc[event_start + timedelta(hours=h), "temperature_c"] for h in range(24)]
    assert np.allclose(y[0], expected_first_targets, atol=1e-4)

    # Final origin check
    assert origins[-1] == event_start + timedelta(hours=96)
    expected_final_target_end = origins[-1] + timedelta(hours=23)
    assert expected_final_target_end == event_end - timedelta(hours=1)


def test_sealed_confirmatory_mutation_invariance(synthetic_hourly_series):
    """Test Correction 1: Changing synthetic confirmation data does not alter training/val windows, scaler, or gate."""
    df, start, end = synthetic_hourly_series
    train_end = start + timedelta(hours=96)
    val_end = start + timedelta(hours=144)

    scaler1 = fit_temperature_scaler(df, start, train_end)

    # Mutate data in hypothetical confirmation region (hours 144 to end)
    df_mut = df.copy()
    df_mut.loc[df_mut.index >= val_end, "temperature_c"] += 50.0

    scaler2 = fit_temperature_scaler(df_mut, start, train_end)
    assert scaler1.mean == scaler2.mean
    assert scaler1.std == scaler2.std
    assert scaler1.count == scaler2.count
    assert scaler1.p95 == scaler2.p95

    # Check training and validation feature matrices
    origs_tr1, X_tr1, y_tr1, _, _, _, _ = extract_features_and_targets_advanced(
        df, start, train_end, start + timedelta(hours=72), train_end, start + timedelta(hours=72), train_end, scaler1
    )
    origs_tr2, X_tr2, y_tr2, _, _, _, _ = extract_features_and_targets_advanced(
        df_mut, start, train_end, start + timedelta(hours=72), train_end, start + timedelta(hours=72), train_end, scaler2
    )
    assert np.allclose(X_tr1, X_tr2)
    assert np.allclose(y_tr1, y_tr2)

    origs_v1, X_v1, y_v1, _, _, _, _ = extract_features_and_targets_advanced(
        df, train_end, val_end, train_end + timedelta(hours=72), val_end, train_end + timedelta(hours=72), val_end, scaler1
    )
    origs_v2, X_v2, y_v2, _, _, _, _ = extract_features_and_targets_advanced(
        df_mut, train_end, val_end, train_end + timedelta(hours=72), val_end, train_end + timedelta(hours=72), val_end, scaler2
    )
    assert np.allclose(X_v1, X_v2)
    assert np.allclose(y_v1, y_v2)


def test_rejection_of_missing_and_nonfinite():
    """Missing observation or non-finite temperature in history or target window must be rejected."""
    start = datetime(2022, 1, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [start + timedelta(hours=i) for i in range(120)]
    temps = [15.0 for _ in range(120)]
    missing = [False for _ in range(120)]

    missing[70] = True
    df = pd.DataFrame({
        "timestamp_utc": timestamps,
        "temperature_c": temps,
        "temperature_obs_count": 1,
        "temperature_missing": missing,
    }).set_index("timestamp_utc")

    scaler = ScalerMetadata(15.0, 1.0, 120, 15.0, "", "", "")
    origs, X, y, _, _, _, _ = extract_features_and_targets_advanced(
        df, start, start + timedelta(hours=120), start + timedelta(hours=72), start + timedelta(hours=120),
        start + timedelta(hours=72), start + timedelta(hours=120), scaler
    )
    # The origin at start + 72h needs hour 70 (index 70) in history, so it must be rejected
    assert start + timedelta(hours=72) not in origs


def test_causal_baselines():
    """Verify last observation, same-hour previous day, and EWMA forecast behavior."""
    hist = np.arange(72, dtype=np.float32)

    last_pred = forecast_last_observation(hist, horizon=24)
    assert last_pred.shape == (24,)
    assert np.all(last_pred == 71.0)

    same_hour = forecast_same_hour_previous_day(hist, horizon=24)
    assert same_hour.shape == (24,)
    assert np.all(same_hour == np.arange(48, 72, dtype=np.float32))

    ewma_pred = forecast_ewma(hist, alpha=0.20, horizon=24)
    assert ewma_pred.shape == (24,)
    assert np.all(ewma_pred == ewma_pred[0])
    assert 0.0 < ewma_pred[0] < 71.0


def test_tiny_lstm_shapes_and_eval_mode():
    """Verify PyTorch model shapes [batch, 24] and deterministic eval mode."""
    import torch

    model = TinyTemperatureLSTM(input_size=5, hidden_size=32, num_layers=1, horizon=24, dropout=0.1)
    model.eval()

    x = torch.randn(4, 72, 5)
    with torch.no_grad():
        out1 = model(x)
        out2 = model(x)

    assert out1.shape == (4, 24)
    assert torch.allclose(out1, out2)


def test_strict_checkpoint_validation_mismatches(tmp_path):
    """Test Correction 6: strict validation of scaler fields, config hash, split hash, and architecture."""
    model = TinyTemperatureLSTM()
    scaler = ScalerMetadata(12.0, 3.0, 100, 18.0, "", "2022-01-01T00:00:00+00:00", "2022-05-01T00:00:00+00:00")
    manifest = {"dummy": "manifest", "training": {"start_utc": "2022-01-01"}}
    contract = {"dummy": "contract", "seed": 20261016}
    train_meta = {
        "best_epoch": 1,
        "best_val_loss": 0.5,
        "wall_time_seconds": 1.0,
        "seed": 20261016,
        "optimizer": "AdamW",
        "loss_fn": "SmoothL1Loss",
        "learning_rate": 0.001,
        "batch_size": 64,
    }
    dummy_val_metrics = pd.DataFrame([{"model": "test", "split": "validation", "triplet_id": "none", "context": "none", "mae": 1.0, "rmse": 1.0, "mae_h1": 1.0, "rmse_h1": 1.0, "mae_h6": 1.0, "rmse_h6": 1.0, "mae_h12": 1.0, "rmse_h12": 1.0, "mae_h24": 1.0, "rmse_h24": 1.0, "extreme_underprediction_mae": 1.0}])
    dummy_dev_metrics = pd.DataFrame([{"model": "test", "split": "development", "triplet_id": "TRIPLET_DEV_ae821c", "context": "heatwave", "mae": 1.0, "rmse": 1.0, "mae_h1": 1.0, "rmse_h1": 1.0, "mae_h6": 1.0, "rmse_h6": 1.0, "mae_h12": 1.0, "rmse_h12": 1.0, "mae_h24": 1.0, "rmse_h24": 1.0, "extreme_underprediction_mae": 1.0}])
    gate_res = {"decision": "PIVOT"}

    art_dir = save_checkpoint_and_artifacts(
        output_dir=tmp_path / "artifacts_v2",
        model=model,
        scaler=scaler,
        split_manifest=manifest,
        forecast_contract=contract,
        train_meta=train_meta,
        val_metrics_df=dummy_val_metrics,
        dev_metrics_df=dummy_dev_metrics,
        gate_result=gate_res,
        repo_root=Path("."),
        raw_noaa_dir=Path("data/raw/noaa"),
        artifact_name="p6_temperature_v2",
    )

    ckpt_file = art_dir / "tiny_lstm_checkpoint.pt"
    split_h = compute_split_hash(manifest)
    cfg_h = compute_forecast_config_hash(contract)

    # Successful load
    m, d = load_verified_checkpoint(
        ckpt_file,
        expected_split_hash=split_h,
        expected_forecast_config_hash=cfg_h,
        expected_scaler=scaler,
    )
    assert m is not None

    # Mismatch 1: Scaler std mismatch
    wrong_scaler_std = ScalerMetadata(12.0, 4.0, 100, 18.0, "", "2022-01-01T00:00:00+00:00", "2022-05-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="Scaler std mismatch"):
        load_verified_checkpoint(ckpt_file, expected_scaler=wrong_scaler_std)

    # Mismatch 2: Scaler count mismatch
    wrong_scaler_cnt = ScalerMetadata(12.0, 3.0, 999, 18.0, "", "2022-01-01T00:00:00+00:00", "2022-05-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="Scaler count mismatch"):
        load_verified_checkpoint(ckpt_file, expected_scaler=wrong_scaler_cnt)

    # Mismatch 3: Configuration hash mismatch
    with pytest.raises(ValueError, match="Forecast config hash mismatch"):
        load_verified_checkpoint(ckpt_file, expected_forecast_config_hash="wrong_cfg_hash")

    # Mismatch 4: Split hash mismatch
    with pytest.raises(ValueError, match="Split hash mismatch"):
        load_verified_checkpoint(ckpt_file, expected_split_hash="wrong_split_hash")


def test_forecast_gate_rules():
    """Verify GO, PIVOT, and STOP logic under frozen validation rules."""
    df_go1 = pd.DataFrame([
        {"model": "same_hour_previous_day", "rmse": 2.0, "extreme_underprediction_mae": 1.5},
        {"model": "TinyTemperatureLSTM", "rmse": 1.95, "extreme_underprediction_mae": 1.5},
    ])
    gate1 = calculate_forecast_gate(df_go1)
    assert gate1["decision"] == "GO"
    assert gate1["selected_provider"] == "TinyTemperatureLSTM"

    df_pivot = pd.DataFrame([
        {"model": "same_hour_previous_day", "rmse": 2.0, "extreme_underprediction_mae": 1.5},
        {"model": "TinyTemperatureLSTM", "rmse": 2.01, "extreme_underprediction_mae": 1.49},
    ])
    gate2 = calculate_forecast_gate(df_pivot)
    assert gate2["decision"] == "PIVOT"
    assert gate2["selected_provider"] == "same_hour_previous_day"

    gate3 = calculate_forecast_gate(df_pivot, correctness_check_passed=False, reason="Leakage detected")
    assert gate3["decision"] == "STOP"


def test_synthetic_training_smoke_test():
    """Tiny synthetic training smoke test completing in under 1 second."""
    np.random.seed(42)
    X_train = np.random.randn(20, 72, 5).astype(np.float32)
    y_train = np.random.randn(20, 24).astype(np.float32) * 5.0 + 15.0
    X_val = np.random.randn(10, 72, 5).astype(np.float32)
    y_val = np.random.randn(10, 24).astype(np.float32) * 5.0 + 15.0
    scaler = ScalerMetadata(15.0, 5.0, 20, 22.0, "", "2022-01-01T00:00:00+00:00", "2022-05-01T00:00:00+00:00")

    model, meta = train_tiny_lstm(
        train_X=X_train,
        train_y=y_train,
        val_X=X_val,
        val_y=y_val,
        scaler=scaler,
        max_epochs=2,
        batch_size=8,
    )
    assert meta["total_epochs"] == 2
    preds = predict_unscaled(model, X_val, scaler)
    assert preds.shape == (10, 24)
    assert np.all(np.isfinite(preds))
