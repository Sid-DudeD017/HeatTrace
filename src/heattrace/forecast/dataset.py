"""Leakage-controlled temperature dataset and split contract for HeatTrace Phase 4."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from heattrace.process.alignment import aggregate_noaa_hourly_temperature


@dataclass(frozen=True)
class SplitWindow:
    """Explicit chronological split observation boundary."""

    name: str
    start_utc: datetime
    end_exclusive_utc: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "start_utc": self.start_utc.isoformat(),
            "end_exclusive_utc": self.end_exclusive_utc.isoformat(),
        }


@dataclass
class ScalerMetadata:
    """Mean and standard deviation fitted strictly on training observations."""

    mean: float
    std: float
    count: int
    p95: float
    fitted_at_utc: str
    train_start_utc: str
    train_end_exclusive_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScalerMetadata:
        return cls(
            mean=float(data["mean"]),
            std=float(data["std"]),
            count=int(data["count"]),
            p95=float(data["p95"]),
            fitted_at_utc=str(data["fitted_at_utc"]),
            train_start_utc=str(data["train_start_utc"]),
            train_end_exclusive_utc=str(data["train_end_exclusive_utc"]),
        )


@dataclass
class ForecastDatasetBundle:
    """Container for built forecast windows, origins, scaler, and provenance."""

    origins: list[datetime]
    X: np.ndarray  # shape: [N, 72, 5], float32
    y: np.ndarray  # shape: [N, 24], float32 (unscaled degrees Celsius)
    split_names: list[str]  # parallel to origins ('training', 'validation', 'calibration_reservation', 'development')
    triplet_ids: list[str]  # parallel to origins (e.g., 'TRIPLET_DEV_ae821c' or 'none')
    contexts: list[str]  # parallel to origins ('heatwave', 'control', 'blind', or 'none')
    sub_window_ids: list[str]  # descriptive window tag
    scaler: ScalerMetadata
    split_manifest: dict[str, Any]
    provenance: dict[str, Any]
    split_hash: str
    forecast_config_hash: str


def compute_split_hash(split_manifest: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of split boundary configurations."""
    raw = json.dumps(split_manifest, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_forecast_config_hash(forecast_contract: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of the complete canonical forecast configuration."""
    raw = json.dumps(forecast_contract, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_canonical_forecast_contract(validity_cfg: dict[str, Any]) -> dict[str, Any]:
    """Construct canonical, deterministically serializable dictionary of all forecast settings."""
    tf_cfg = validity_cfg.get("temperature_forecast", {})
    splits_cfg = tf_cfg.get("splits", {})
    arch_cfg = tf_cfg.get("architecture", {})
    train_cfg = tf_cfg.get("training", {})
    base_cfg = tf_cfg.get("baselines", {})
    ext_cfg = tf_cfg.get("extreme_temperature", {})
    gate_cfg = tf_cfg.get("gate", {})

    contract = {
        "boundary_semantics": str(splits_cfg.get("boundary_semantics", "half_open_start_inclusive_end_exclusive")),
        "splits": {
            "training": {
                "start_utc": str(splits_cfg["training"]["start_utc"]),
                "end_exclusive_utc": str(splits_cfg["training"]["end_exclusive_utc"]),
            },
            "validation": {
                "start_utc": str(splits_cfg["validation"]["start_utc"]),
                "end_exclusive_utc": str(splits_cfg["validation"]["end_exclusive_utc"]),
            },
            "calibration_reservation": {
                "start_utc": str(splits_cfg["calibration_reservation"]["start_utc"]),
                "end_exclusive_utc": str(splits_cfg["calibration_reservation"]["end_exclusive_utc"]),
            },
        },
        "feature_order": [
            "standardized_temperature",
            "sin_hour_of_day",
            "cos_hour_of_day",
            "sin_day_of_year",
            "cos_day_of_year",
        ],
        "lookback_hours": 72,
        "horizon_hours": 24,
        "architecture": {
            "model": str(arch_cfg.get("model", "TinyTemperatureLSTM")),
            "input_size": int(arch_cfg.get("input_size", 5)),
            "hidden_size": int(arch_cfg.get("hidden_size", 32)),
            "num_layers": int(arch_cfg.get("num_layers", 1)),
            "horizon": int(arch_cfg.get("horizon", 24)),
            "dropout": float(arch_cfg.get("dropout", 0.1)),
        },
        "scaler_rule": "training_observations_only_mean_std_ddof0",
        "training": {
            "device": str(train_cfg.get("device", "cpu")),
            "seed": int(train_cfg.get("seed", 20261016)),
            "optimizer": str(train_cfg.get("optimizer", "AdamW")),
            "learning_rate": float(train_cfg.get("learning_rate", 0.001)),
            "loss": str(train_cfg.get("loss", "SmoothL1")),
            "batch_size": int(train_cfg.get("batch_size", 64)),
            "max_epochs": int(train_cfg.get("max_epochs", 50)),
            "early_stopping_patience": int(train_cfg.get("early_stopping_patience", 5)),
            "early_stopping_min_delta": float(train_cfg.get("early_stopping_min_delta", 1e-4)),
        },
        "baselines": {
            "methods": list(base_cfg.get("methods", ["last_observation", "same_hour_previous_day", "ewma_0.20"])),
            "ewma_alpha": float(base_cfg.get("ewma_alpha", 0.20)),
        },
        "extreme_temperature": {
            "threshold_rule": str(ext_cfg.get("threshold_rule", "training_p95_strictly")),
        },
        "gate": {
            "rmse_improvement_threshold": float(gate_cfg.get("rmse_improvement_threshold", 0.02)),
            "extreme_improvement_threshold": float(gate_cfg.get("extreme_improvement_threshold", 0.05)),
            "extreme_rmse_slack": float(gate_cfg.get("extreme_rmse_slack", -0.02)),
        },
    }
    return contract


def load_noaa_hourly_series(
    raw_noaa_dir: Path | str,
    start_utc: datetime,
    end_exclusive_utc: datetime,
    expected_station: str = "USW00023234",
) -> pd.DataFrame:
    """Load and aggregate NOAA hourly observations across the required year span.

    Reuses heattrace.process.alignment.aggregate_noaa_hourly_temperature.
    Rejects duplicate UTC hours, non-finite temperatures, and invalid timestamps.
    Returns a DataFrame indexed by UTC datetime with columns:
      - temperature_c: float or NaN
      - temperature_obs_count: int
      - temperature_missing: bool
    """
    raw_dir = Path(raw_noaa_dir)
    years = range(start_utc.year, (end_exclusive_utc - timedelta(seconds=1)).year + 1)

    # Build continuous list of UTC hourly intervals
    curr = start_utc
    intervals: list[dict[str, Any]] = []
    while curr < end_exclusive_utc:
        intervals.append(
            {
                "timestamp_utc": curr,
                "interval_end_utc": curr + timedelta(hours=1),
                "interval_label": curr.isoformat(),
            }
        )
        curr += timedelta(hours=1)

    all_results: dict[datetime, dict[str, Any]] = {}
    for yr in years:
        psv_file = raw_dir / f"GHCNh_{expected_station}_{yr}.psv"
        if not psv_file.exists():
            raise FileNotFoundError(f"Authoritative NOAA PSV missing: {psv_file}")

        yr_intervals = [inv for inv in intervals if inv["timestamp_utc"].year == yr]
        if not yr_intervals:
            continue
        yr_res = aggregate_noaa_hourly_temperature(
            psv_file, yr_intervals, expected_station=expected_station
        )
        all_results.update(yr_res)

    records = []
    seen_ts = set()
    for inv in intervals:
        ts = inv["timestamp_utc"]
        if ts in seen_ts:
            raise ValueError(f"Duplicate UTC hour detected: {ts}")
        seen_ts.add(ts)
        info = all_results.get(ts)
        if info is None:
            records.append({
                "timestamp_utc": ts,
                "temperature_c": np.nan,
                "temperature_obs_count": 0,
                "temperature_missing": True,
            })
        else:
            temp = info["temperature_c"]
            is_missing = info["temperature_missing"] or (temp is None)
            if not is_missing and (not np.isfinite(temp)):
                raise ValueError(f"Non-finite temperature detected at {ts}: {temp}")
            records.append({
                "timestamp_utc": ts,
                "temperature_c": float(temp) if temp is not None else np.nan,
                "temperature_obs_count": int(info["temperature_obs_count"]),
                "temperature_missing": bool(is_missing),
            })

    df = pd.DataFrame(records).set_index("timestamp_utc").sort_index()
    return df


def fit_temperature_scaler(
    df: pd.DataFrame,
    train_start: datetime,
    train_end_exclusive: datetime,
) -> ScalerMetadata:
    """Fit mean and std strictly using observations inside [train_start, train_end_exclusive)."""
    mask = (df.index >= train_start) & (df.index < train_end_exclusive)
    train_df = df.loc[mask]
    valid_temps = train_df.loc[~train_df["temperature_missing"], "temperature_c"].values

    if len(valid_temps) == 0:
        raise ValueError("Cannot fit scaler: zero valid observations in training range.")

    mean = float(np.mean(valid_temps))
    std = float(np.std(valid_temps, ddof=0))
    if std <= 1e-6:
        raise ValueError(f"Degenerate temperature standard deviation: {std}")
    p95 = float(np.percentile(valid_temps, 95.0))

    return ScalerMetadata(
        mean=round(mean, 6),
        std=round(std, 6),
        count=int(len(valid_temps)),
        p95=round(p95, 6),
        fitted_at_utc=datetime.now(timezone.utc).isoformat(),
        train_start_utc=train_start.isoformat(),
        train_end_exclusive_utc=train_end_exclusive.isoformat(),
    )


def extract_features_and_targets_advanced(
    hourly_df: pd.DataFrame,
    history_start_utc: datetime,
    history_end_exclusive_utc: datetime,
    origin_start_utc: datetime,
    origin_end_exclusive_utc: datetime,
    target_start_utc: datetime,
    target_end_exclusive_utc: datetime,
    scaler: ScalerMetadata,
    lookback: int = 72,
    horizon: int = 24,
    split_name: str = "training",
    triplet_id: str = "none",
    context: str = "none",
    sub_window_id: str = "default",
) -> tuple[list[datetime], np.ndarray, np.ndarray, list[str], list[str], list[str], list[str]]:
    """Extract causal lookback x 5 input windows and horizon target vectors under explicit boundary constraints.

    Distinguishes:
      - history boundary: [history_start_utc, history_end_exclusive_utc)
      - allowed origin boundary: [origin_start_utc, origin_end_exclusive_utc)
      - allowed target boundary: [target_start_utc, target_end_exclusive_utc)

    Causality and coverage rules:
      - For origin t:
        - Must satisfy origin_start_utc <= t < origin_end_exclusive_utc.
        - History timestamps are [t - lookback, ..., t - 1].
          All must be >= history_start_utc and < history_end_exclusive_utc (and t).
        - Target timestamps are [t, ..., t + horizon - 1].
          All must be >= target_start_utc and < target_end_exclusive_utc.
        - No required history or target hour may be missing or non-finite.
    """
    origins: list[datetime] = []
    X_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    splits: list[str] = []
    triplets: list[str] = []
    ctxs: list[str] = []
    sub_windows: list[str] = []

    mean = scaler.mean
    std = scaler.std

    # Determine candidate origins by stepping hourly from origin_start_utc to origin_end_exclusive_utc
    curr_orig = origin_start_utc
    while curr_orig < origin_end_exclusive_utc:
        # Check target boundary
        last_target = curr_orig + timedelta(hours=horizon)
        if last_target > target_end_exclusive_utc:
            curr_orig += timedelta(hours=1)
            continue

        first_hist = curr_orig - timedelta(hours=lookback)
        if first_hist < history_start_utc:
            curr_orig += timedelta(hours=1)
            continue

        # Build list of history hours and target hours
        hist_hours = [first_hist + timedelta(hours=h) for h in range(lookback)]
        target_hours = [curr_orig + timedelta(hours=h) for h in range(horizon)]

        # Check in hourly_df
        try:
            hist_sub = hourly_df.loc[hist_hours]
            target_sub = hourly_df.loc[target_hours]
        except KeyError:
            curr_orig += timedelta(hours=1)
            continue

        if hist_sub["temperature_missing"].any() or target_sub["temperature_missing"].any():
            curr_orig += timedelta(hours=1)
            continue

        hist_temps = hist_sub["temperature_c"].values
        target_temps = target_sub["temperature_c"].values

        if not np.all(np.isfinite(hist_temps)) or not np.all(np.isfinite(target_temps)):
            curr_orig += timedelta(hours=1)
            continue

        # Standardized temperature feature
        std_temp = (hist_temps - mean) / std

        # Cyclical diurnal & annual features
        hours = np.array([ts.hour for ts in hist_hours], dtype=np.float64)
        sin_hour = np.sin(2.0 * np.pi * hours / 24.0)
        cos_hour = np.cos(2.0 * np.pi * hours / 24.0)

        doys = np.array([ts.timetuple().tm_yday for ts in hist_hours], dtype=np.float64)
        sin_doy = np.sin(2.0 * np.pi * doys / 366.0)
        cos_doy = np.cos(2.0 * np.pi * doys / 366.0)

        features = np.column_stack([std_temp, sin_hour, cos_hour, sin_doy, cos_doy]).astype(np.float32)

        origins.append(curr_orig)
        X_list.append(features)
        y_list.append(target_temps.astype(np.float32))
        splits.append(split_name)
        triplets.append(triplet_id)
        ctxs.append(context)
        sub_windows.append(sub_window_id)

        curr_orig += timedelta(hours=1)

    if not X_list:
        return (
            [],
            np.empty((0, lookback, 5), dtype=np.float32),
            np.empty((0, horizon), dtype=np.float32),
            [],
            [],
            [],
            [],
        )

    return origins, np.stack(X_list, axis=0), np.stack(y_list, axis=0), splits, triplets, ctxs, sub_windows


def build_temperature_dataset(
    raw_noaa_dir: Path | str,
    validity_cfg: dict[str, Any],
    p6_index_path: Path | str = "data/benchmarks/p6_event_control_index.csv",
) -> ForecastDatasetBundle:
    """Build the Phase 4 temperature dataset conforming to frozen split contracts.

    Invariants:
    - Explicit half-open boundaries: [start_utc, end_exclusive_utc).
    - Training, validation, and calibration splits are chronological and disjoint.
    - Confirmatory triplets are strictly SEALED: metadata recorded, zero data materialized.
    - Development triplet builds forecasts starting from the window start (origin 0),
      drawing lookback from the preceding 72 causal hours.
    - Provenance and complete configuration hashes computed deterministically.
    """
    tf_cfg = validity_cfg.get("temperature_forecast", {})
    splits_cfg = tf_cfg.get("splits", {})

    boundary_semantics = splits_cfg.get("boundary_semantics", "half_open_start_inclusive_end_exclusive")
    if boundary_semantics != "half_open_start_inclusive_end_exclusive":
        raise ValueError(f"Unsupported boundary semantics: {boundary_semantics}")

    train_start = datetime.fromisoformat(splits_cfg["training"]["start_utc"])
    train_end_ex = datetime.fromisoformat(splits_cfg["training"]["end_exclusive_utc"])
    val_start = datetime.fromisoformat(splits_cfg["validation"]["start_utc"])
    val_end_ex = datetime.fromisoformat(splits_cfg["validation"]["end_exclusive_utc"])
    cal_start = datetime.fromisoformat(splits_cfg["calibration_reservation"]["start_utc"])
    cal_end_ex = datetime.fromisoformat(splits_cfg["calibration_reservation"]["end_exclusive_utc"])

    # Disjoint chronological ordering check
    if not (train_start < train_end_ex <= val_start < val_end_ex <= cal_start < cal_end_ex):
        raise ValueError("Core split chronological ordering violated.")

    triplet_df = pd.read_csv(p6_index_path)

    # Validate confirmatory triplets presence without materializing them
    conf_triplets = triplet_df[triplet_df["role"] == "confirmatory"]
    if len(conf_triplets) != 3:
        raise ValueError(f"Expected exactly 3 confirmatory triplets, found {len(conf_triplets)}")

    earliest_conf_hw = min(datetime.fromisoformat(ts) for ts in conf_triplets["heatwave_start_utc"])
    embargo_start = cal_end_ex
    embargo_end_ex = earliest_conf_hw
    if embargo_start > embargo_end_ex:
        raise ValueError(f"Embargo start {embargo_start} is after earliest confirmatory {embargo_end_ex}")

    # Development triplet
    dev_triplets = triplet_df[triplet_df["role"] == "development"]
    if len(dev_triplets) != 1:
        raise ValueError(f"Expected exactly 1 development triplet, found {len(dev_triplets)}")
    dev_row = dev_triplets.iloc[0]

    # Load NOAA data ONLY for training, validation, calibration, and development (plus 72h history)
    # Never load or aggregate confirmatory intervals!
    # Load contiguous segment for 2022 train/val/cal:
    core_df_2022 = load_noaa_hourly_series(raw_noaa_dir, train_start, cal_end_ex)

    # Fit scaler strictly on training observations
    scaler = fit_temperature_scaler(core_df_2022, train_start, train_end_ex)

    all_origins: list[datetime] = []
    all_X: list[np.ndarray] = []
    all_y: list[np.ndarray] = []
    all_splits: list[str] = []
    all_triplets: list[str] = []
    all_contexts: list[str] = []
    all_sub_windows: list[str] = []

    # 1. Training split: origins and targets strictly inside [train_start, train_end_ex)
    t_orig, t_X, t_y, t_sp, t_tr, t_cx, t_sub = extract_features_and_targets_advanced(
        hourly_df=core_df_2022,
        history_start_utc=train_start,
        history_end_exclusive_utc=train_end_ex,
        origin_start_utc=train_start + timedelta(hours=72),
        origin_end_exclusive_utc=train_end_ex,
        target_start_utc=train_start + timedelta(hours=72),
        target_end_exclusive_utc=train_end_ex,
        scaler=scaler,
        split_name="training",
        triplet_id="none",
        context="none",
        sub_window_id="train_2022",
    )
    if len(t_orig) == 0:
        raise RuntimeError("Authoritative training range produced zero valid windows!")
    all_origins.extend(t_orig)
    all_X.append(t_X)
    all_y.append(t_y)
    all_splits.extend(t_sp)
    all_triplets.extend(t_tr)
    all_contexts.extend(t_cx)
    all_sub_windows.extend(t_sub)

    # 2. Validation split: origins and targets strictly inside [val_start, val_end_ex)
    v_orig, v_X, v_y, v_sp, v_tr, v_cx, v_sub = extract_features_and_targets_advanced(
        hourly_df=core_df_2022,
        history_start_utc=val_start,
        history_end_exclusive_utc=val_end_ex,
        origin_start_utc=val_start + timedelta(hours=72),
        origin_end_exclusive_utc=val_end_ex,
        target_start_utc=val_start + timedelta(hours=72),
        target_end_exclusive_utc=val_end_ex,
        scaler=scaler,
        split_name="validation",
        triplet_id="none",
        context="none",
        sub_window_id="val_2022",
    )
    all_origins.extend(v_orig)
    all_X.append(v_X)
    all_y.append(v_y)
    all_splits.extend(v_sp)
    all_triplets.extend(v_tr)
    all_contexts.extend(v_cx)
    all_sub_windows.extend(v_sub)

    # 3. Calibration reservation: origins and targets strictly inside [cal_start, cal_end_ex)
    c_orig, c_X, c_y, c_sp, c_tr, c_cx, c_sub = extract_features_and_targets_advanced(
        hourly_df=core_df_2022,
        history_start_utc=cal_start,
        history_end_exclusive_utc=cal_end_ex,
        origin_start_utc=cal_start + timedelta(hours=72),
        origin_end_exclusive_utc=cal_end_ex,
        target_start_utc=cal_start + timedelta(hours=72),
        target_end_exclusive_utc=cal_end_ex,
        scaler=scaler,
        split_name="calibration_reservation",
        triplet_id="none",
        context="none",
        sub_window_id="cal_2022",
    )
    all_origins.extend(c_orig)
    all_X.append(c_X)
    all_y.append(c_y)
    all_splits.extend(c_sp)
    all_triplets.extend(c_tr)
    all_contexts.extend(c_cx)
    all_sub_windows.extend(c_sub)

    # 4. Development triplet: origins in [event_start, event_end - 24h], targets within [event_start, event_end),
    # history drawn from preceding 72 causal hours [event_start - 72h, event_end)
    dev_triplet_id = dev_row["triplet_id"]
    for ctx in ["heatwave", "control", "blind"]:
        w_start = datetime.fromisoformat(dev_row[f"{ctx}_start_utc"])
        w_end_ex = datetime.fromisoformat(dev_row[f"{ctx}_end_utc"])
        hist_start = w_start - timedelta(hours=72)
        dev_df = load_noaa_hourly_series(raw_noaa_dir, hist_start, w_end_ex)

        target_key = "event_id" if ctx == "heatwave" else f"{ctx}_id"
        sub_id = f"{dev_triplet_id}_{ctx}_{dev_row[target_key]}"

        d_orig, d_X, d_y, d_sp, d_tr, d_cx, d_sub = extract_features_and_targets_advanced(
            hourly_df=dev_df,
            history_start_utc=hist_start,
            history_end_exclusive_utc=w_end_ex,
            origin_start_utc=w_start,
            origin_end_exclusive_utc=w_end_ex - timedelta(hours=23),
            target_start_utc=w_start,
            target_end_exclusive_utc=w_end_ex,
            scaler=scaler,
            split_name="development",
            triplet_id=dev_triplet_id,
            context=ctx,
            sub_window_id=sub_id,
        )
        if len(d_orig) > 0:
            all_origins.extend(d_orig)
            all_X.append(d_X)
            all_y.append(d_y)
            all_splits.extend(d_sp)
            all_triplets.extend(d_tr)
            all_contexts.extend(d_cx)
            all_sub_windows.extend(d_sub)

    concat_X = np.concatenate(all_X, axis=0) if all_X else np.empty((0, 72, 5), dtype=np.float32)
    concat_y = np.concatenate(all_y, axis=0) if all_y else np.empty((0, 24), dtype=np.float32)

    # Build sealed confirmatory metadata without materializing any data
    conf_metadata = []
    for _, r in conf_triplets.iterrows():
        conf_metadata.append({
            "triplet_id": r["triplet_id"],
            "heatwave_window": {"start_utc": r["heatwave_start_utc"], "end_utc": r["heatwave_end_utc"]},
            "control_window": {"start_utc": r["control_start_utc"], "end_utc": r["control_end_utc"]},
            "blind_window": {"start_utc": r["blind_start_utc"], "end_utc": r["blind_end_utc"]},
        })

    split_manifest = {
        "boundary_semantics": "half_open_start_inclusive_end_exclusive",
        "training": {
            "start_utc": train_start.isoformat(),
            "end_exclusive_utc": train_end_ex.isoformat(),
            "valid_windows": len(t_orig),
        },
        "validation": {
            "start_utc": val_start.isoformat(),
            "end_exclusive_utc": val_end_ex.isoformat(),
            "valid_windows": len(v_orig),
        },
        "calibration_reservation": {
            "start_utc": cal_start.isoformat(),
            "end_exclusive_utc": cal_end_ex.isoformat(),
            "valid_windows": len(c_orig),
        },
        "embargo": {
            "start_utc": embargo_start.isoformat(),
            "end_exclusive_utc": embargo_end_ex.isoformat(),
            "valid_windows": 0,
        },
        "development_triplets": [
            {
                "triplet_id": dev_triplet_id,
                "heatwave_window": {"start_utc": dev_row["heatwave_start_utc"], "end_utc": dev_row["heatwave_end_utc"]},
                "control_window": {"start_utc": dev_row["control_start_utc"], "end_utc": dev_row["control_end_utc"]},
                "blind_window": {"start_utc": dev_row["blind_start_utc"], "end_utc": dev_row["blind_end_utc"]},
            }
        ],
        "confirmatory_triplets": conf_metadata,
        "confirmatory_status": "sealed_not_materialized",
        "feature_schema": [
            "standardized_temperature",
            "sin_hour_of_day",
            "cos_hour_of_day",
            "sin_day_of_year",
            "cos_day_of_year",
        ],
        "lookback_hours": 72,
        "horizon_hours": 24,
    }

    split_hash = compute_split_hash(split_manifest)
    canonical_contract = build_canonical_forecast_contract(validity_cfg)
    forecast_config_hash = compute_forecast_config_hash(canonical_contract)

    bundle = ForecastDatasetBundle(
        origins=all_origins,
        X=concat_X,
        y=concat_y,
        split_names=all_splits,
        triplet_ids=all_triplets,
        contexts=all_contexts,
        sub_window_ids=all_sub_windows,
        scaler=scaler,
        split_manifest=split_manifest,
        provenance={
            "raw_noaa_dir": str(raw_noaa_dir),
            "p6_index_path": str(p6_index_path),
            "total_windows_materialized": len(all_origins),
            "confirmatory_materialized": False,
        },
        split_hash=split_hash,
        forecast_config_hash=forecast_config_hash,
    )
    return bundle
