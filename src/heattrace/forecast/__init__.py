"""Forecast module package."""

from heattrace.forecast.dataset import (
    ForecastDatasetBundle,
    ScalerMetadata,
    SplitWindow,
    build_canonical_forecast_contract,
    build_temperature_dataset,
    compute_forecast_config_hash,
    compute_split_hash,
    extract_features_and_targets_advanced,
    fit_temperature_scaler,
    load_noaa_hourly_series,
)
from heattrace.forecast.evaluate_temperature import (
    calculate_forecast_gate,
    compute_forecast_metrics,
    evaluate_all_forecast_methods,
)
from heattrace.forecast.historical import (
    HistoricalPersistenceForecastProvider,
    build_historical_forecast_dataset,
)
from heattrace.forecast.schema import FORECAST_COLUMNS, validate_forecast_dataframe
from heattrace.forecast.tiny_lstm import (
    TinyTemperatureLSTM,
    forecast_ewma,
    forecast_last_observation,
    forecast_same_hour_previous_day,
)
from heattrace.forecast.calibration import (
    CalibrationResult,
    calibrate_safety_margin,
    compute_calibrated_safety_margin,
    compute_pue_residuals,
    compute_safe_pue,
    load_calibration_artifact,
    save_calibration_artifact,
)
from heattrace.forecast.train_temperature import (
    load_verified_checkpoint,
    predict_unscaled,
    save_checkpoint_and_artifacts,
    train_tiny_lstm,
)

__all__ = [
    "FORECAST_COLUMNS",
    "HistoricalPersistenceForecastProvider",
    "build_historical_forecast_dataset",
    "validate_forecast_dataframe",
    "ForecastDatasetBundle",
    "ScalerMetadata",
    "SplitWindow",
    "build_canonical_forecast_contract",
    "build_temperature_dataset",
    "compute_forecast_config_hash",
    "compute_split_hash",
    "extract_features_and_targets_advanced",
    "fit_temperature_scaler",
    "load_noaa_hourly_series",
    "calculate_forecast_gate",
    "compute_forecast_metrics",
    "evaluate_all_forecast_methods",
    "TinyTemperatureLSTM",
    "forecast_ewma",
    "forecast_last_observation",
    "forecast_same_hour_previous_day",
    "load_verified_checkpoint",
    "predict_unscaled",
    "save_checkpoint_and_artifacts",
    "train_tiny_lstm",
    "CalibrationResult",
    "compute_pue_residuals",
    "compute_calibrated_safety_margin",
    "compute_safe_pue",
    "calibrate_safety_margin",
    "save_calibration_artifact",
    "load_calibration_artifact",
]
