"""Training script, strict checkpoint validation, and artifact serialization for TinyTemperatureLSTM."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None

from heattrace.forecast.dataset import (
    ForecastDatasetBundle,
    ScalerMetadata,
    compute_forecast_config_hash,
    compute_split_hash,
)
from heattrace.forecast.evaluate_temperature import (
    calculate_forecast_gate,
    evaluate_all_forecast_methods,
)
from heattrace.forecast.tiny_lstm import TinyTemperatureLSTM


def sha256_file(path: Path | str) -> str:
    """Compute sha256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_info(repo_dir: Path | str) -> str:
    """Get current git commit hash or working tree identifier."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unversioned_git_working_tree"


def train_tiny_lstm(
    train_X: np.ndarray,
    train_y: np.ndarray,
    val_X: np.ndarray,
    val_y: np.ndarray,
    scaler: ScalerMetadata,
    seed: int = 20261016,
    lr: float = 0.001,
    batch_size: int = 64,
    max_epochs: int = 50,
    patience: int = 5,
    min_delta: float = 1e-4,
) -> tuple[TinyTemperatureLSTM, dict[str, Any]]:
    """Train TinyTemperatureLSTM strictly on CPU following the frozen contract."""
    if not _TORCH_AVAILABLE:
        raise ImportError("PyTorch required for train_tiny_lstm.")

    device = torch.device("cpu")
    torch.manual_seed(seed)
    np.random.seed(seed)
    if hasattr(torch, "use_deterministic_algorithms"):
        try:
            torch.use_deterministic_algorithms(True)
        except Exception:
            pass

    train_y_std = (train_y - scaler.mean) / scaler.std
    val_y_std = (val_y - scaler.mean) / scaler.std

    train_dataset = TensorDataset(torch.from_numpy(train_X), torch.from_numpy(train_y_std))
    val_dataset = TensorDataset(torch.from_numpy(val_X), torch.from_numpy(val_y_std))

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=False)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    model = TinyTemperatureLSTM(
        input_size=5,
        hidden_size=32,
        num_layers=1,
        horizon=24,
        dropout=0.1,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    criterion = nn.SmoothL1Loss()

    best_val_loss = float("inf")
    best_epoch = -1
    best_model_weights = None
    epochs_no_improve = 0

    history: list[dict[str, Any]] = []
    start_time = time.perf_counter()

    for epoch in range(1, max_epochs + 1):
        model.train()
        train_loss_total = 0.0
        n_train_batches = 0
        for bx, by in train_loader:
            bx = bx.to(device)
            by = by.to(device)

            optimizer.zero_grad()
            pred = model(bx)
            loss = criterion(pred, by)
            loss.backward()
            optimizer.step()

            train_loss_total += float(loss.item())
            n_train_batches += 1

        avg_train_loss = train_loss_total / max(1, n_train_batches)

        model.eval()
        val_loss_total = 0.0
        n_val_batches = 0
        with torch.no_grad():
            for vx, vy in val_loader:
                vx = vx.to(device)
                vy = vy.to(device)
                v_pred = model(vx)
                v_loss = criterion(v_pred, vy)
                val_loss_total += float(v_loss.item())
                n_val_batches += 1

        avg_val_loss = val_loss_total / max(1, n_val_batches)

        history.append({
            "epoch": epoch,
            "train_loss": round(avg_train_loss, 6),
            "val_loss": round(avg_val_loss, 6),
        })

        if (best_val_loss - avg_val_loss) > min_delta:
            best_val_loss = avg_val_loss
            best_epoch = epoch
            best_model_weights = copy.deepcopy(model.state_dict())
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= patience:
                break

    wall_time = time.perf_counter() - start_time

    if best_model_weights is not None:
        model.load_state_dict(best_model_weights)
    model.eval()

    meta = {
        "best_epoch": best_epoch,
        "best_val_loss": round(best_val_loss, 6),
        "total_epochs": len(history),
        "wall_time_seconds": round(wall_time, 2),
        "history": history,
        "seed": seed,
        "learning_rate": lr,
        "batch_size": batch_size,
        "loss_fn": "SmoothL1Loss",
        "optimizer": "AdamW",
        "device": "cpu",
    }
    return model, meta


def predict_unscaled(
    model: TinyTemperatureLSTM,
    X: np.ndarray,
    scaler: ScalerMetadata,
) -> np.ndarray:
    """Run model inference on X and return unscaled predictions in degrees Celsius."""
    if not _TORCH_AVAILABLE:
        raise ImportError("PyTorch required for inference.")
    model.eval()
    with torch.no_grad():
        tx = torch.from_numpy(X).to(torch.device("cpu"))
        std_preds = model(tx).cpu().numpy()
    unscaled = std_preds * scaler.std + scaler.mean
    return unscaled.astype(np.float32)


def save_checkpoint_and_artifacts(
    output_dir: Path,
    model: TinyTemperatureLSTM,
    scaler: ScalerMetadata,
    split_manifest: dict[str, Any],
    forecast_contract: dict[str, Any],
    train_meta: dict[str, Any],
    val_metrics_df: pd.DataFrame,
    dev_metrics_df: pd.DataFrame,
    gate_result: dict[str, Any],
    repo_root: Path,
    raw_noaa_dir: Path,
    artifact_name: str = "p6_temperature_v2",
    supersedes: str | None = "p6_temperature_v1",
    supersede_reason: str = "v1 was superseded due to split-endpoint ambiguity, incomplete event-window coverage, and premature confirmatory-target materialization.",
) -> Path:
    """Save all Phase 4 artifacts atomically with strict manifest and hash validation."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Target artifact directory exists and is non-empty: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir.parent / f".tmp_{output_dir.name}_{int(time.time())}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        split_hash = compute_split_hash(split_manifest)
        forecast_config_hash = compute_forecast_config_hash(forecast_contract)

        # 1. Checkpoint
        checkpoint_path = tmp_dir / "tiny_lstm_checkpoint.pt"
        checkpoint_data = {
            "model_state_dict": model.state_dict(),
            "architecture": {
                "class": "TinyTemperatureLSTM",
                "input_size": 5,
                "hidden_size": 32,
                "num_layers": 1,
                "horizon": 24,
                "dropout": 0.1,
            },
            "feature_order": [
                "standardized_temperature",
                "sin_hour_of_day",
                "cos_hour_of_day",
                "sin_day_of_year",
                "cos_day_of_year",
            ],
            "lookback": 72,
            "horizon": 24,
            "split_hash": split_hash,
            "forecast_config_hash": forecast_config_hash,
            "scaler": scaler.to_dict(),
            "seed": train_meta["seed"],
        }
        torch.save(checkpoint_data, checkpoint_path)

        # 2. Scaler JSON
        scaler_path = tmp_dir / "scaler.json"
        with open(scaler_path, "w", encoding="utf-8") as f:
            json.dump(scaler.to_dict(), f, indent=2)

        # 3. Split manifest JSON
        split_path = tmp_dir / "split_manifest.json"
        with open(split_path, "w", encoding="utf-8") as f:
            json.dump(split_manifest, f, indent=2)

        # 4. Training history JSON
        history_path = tmp_dir / "training_history.json"
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(train_meta, f, indent=2)

        # 5. Metrics CSV (validation + context-separated development)
        combined_metrics = pd.concat([val_metrics_df, dev_metrics_df], ignore_index=True)
        metrics_path = tmp_dir / "evaluation_metrics.csv"
        combined_metrics.to_csv(metrics_path, index=False)

        # Raw NOAA hashes
        noaa_hashes: dict[str, str] = {}
        for yr in [2022, 2023, 2024, 2025]:
            psv = raw_noaa_dir / f"GHCNh_USW00023234_{yr}.psv"
            if psv.exists():
                noaa_hashes[psv.name] = sha256_file(psv)

        ckpt_sha = sha256_file(checkpoint_path)
        scaler_sha = sha256_file(scaler_path)
        split_sha = sha256_file(split_path)
        hist_sha = sha256_file(history_path)
        metrics_sha = sha256_file(metrics_path)

        # 6. Artifact manifest JSON
        git_commit = get_git_info(repo_root)
        manifest_data = {
            "artifact_name": artifact_name,
            "supersedes": supersedes,
            "supersede_reason": supersede_reason,
            "confirmatory_status": "sealed_not_materialized",
            "model_architecture": checkpoint_data["architecture"],
            "feature_order": checkpoint_data["feature_order"],
            "lookback": 72,
            "horizon": 24,
            "optimizer": train_meta["optimizer"],
            "loss_fn": train_meta["loss_fn"],
            "learning_rate": train_meta["learning_rate"],
            "batch_size": train_meta["batch_size"],
            "max_epochs": train_meta.get("max_epochs", 50),
            "patience": train_meta.get("patience", 5),
            "seed": train_meta["seed"],
            "best_epoch": train_meta["best_epoch"],
            "best_val_loss": train_meta["best_val_loss"],
            "training_wall_time_seconds": train_meta["wall_time_seconds"],
            "device": "cpu",
            "split_boundaries": split_manifest,
            "split_hash": split_hash,
            "forecast_config_hash": forecast_config_hash,
            "extreme_temperature_p95_threshold_c": scaler.p95,
            "forecast_gate": gate_result,
            "environment": {
                "python_version": sys.version,
                "pandas_version": pd.__version__,
                "torch_version": torch.__version__,
                "platform": platform.platform(),
            },
            "git_commit": git_commit,
            "source_noaa_files": noaa_hashes,
            "file_hashes": {
                "tiny_lstm_checkpoint.pt": ckpt_sha,
                "scaler.json": scaler_sha,
                "split_manifest.json": split_sha,
                "training_history.json": hist_sha,
                "evaluation_metrics.csv": metrics_sha,
            },
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "provenance_statement": (
                "This is a newly trained direct multi-horizon HeatTrace model, "
                "not a Ruparel checkpoint or reproduction."
            ),
        }

        manifest_path = tmp_dir / "artifact_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        # Atomic move
        for item in tmp_dir.iterdir():
            target = output_dir / item.name
            if target.exists():
                target.unlink()
            item.rename(target)
        tmp_dir.rmdir()

    except Exception:
        if tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return output_dir


def load_verified_checkpoint(
    checkpoint_path: Path | str,
    expected_split_hash: str | None = None,
    expected_forecast_config_hash: str | None = None,
    expected_scaler: ScalerMetadata | None = None,
    expected_architecture: dict[str, Any] | None = None,
) -> tuple[TinyTemperatureLSTM, dict[str, Any]]:
    """Strictly load and validate checkpoint against metadata and configuration invariants."""
    if not _TORCH_AVAILABLE:
        raise ImportError("PyTorch required to load checkpoint.")

    ckpt_path = Path(checkpoint_path)
    if not ckpt_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")

    data = torch.load(ckpt_path, map_location=torch.device("cpu"), weights_only=False)

    expected_features = [
        "standardized_temperature",
        "sin_hour_of_day",
        "cos_hour_of_day",
        "sin_day_of_year",
        "cos_day_of_year",
    ]
    if data.get("feature_order") != expected_features:
        raise ValueError(f"Incompatible feature order in checkpoint: {data.get('feature_order')}")

    if data.get("lookback") != 72:
        raise ValueError(f"Incompatible lookback: {data.get('lookback')}")
    if data.get("horizon") != 24:
        raise ValueError(f"Incompatible horizon: {data.get('horizon')}")

    arch = data.get("architecture", {})
    if arch.get("input_size") != 5:
        raise ValueError(f"Incompatible input_size: {arch.get('input_size')}")
    if arch.get("hidden_size") != 32:
        raise ValueError(f"Incompatible hidden_size: {arch.get('hidden_size')}")
    if arch.get("num_layers") != 1:
        raise ValueError(f"Incompatible num_layers: {arch.get('num_layers')}")
    if arch.get("dropout") != 0.1:
        raise ValueError(f"Incompatible dropout: {arch.get('dropout')}")

    if expected_architecture is not None:
        for k, v in expected_architecture.items():
            if arch.get(k) != v:
                raise ValueError(f"Architecture mismatch for {k}: {arch.get(k)} != {v}")

    # Validate split hash
    if expected_split_hash is not None and data.get("split_hash") != expected_split_hash:
        raise ValueError(
            f"Split hash mismatch: checkpoint {data.get('split_hash')} != expected {expected_split_hash}"
        )

    # Validate forecast config hash
    if expected_forecast_config_hash is not None and data.get("forecast_config_hash") != expected_forecast_config_hash:
        raise ValueError(
            f"Forecast config hash mismatch: checkpoint {data.get('forecast_config_hash')} != expected {expected_forecast_config_hash}"
        )

    # Validate complete scaler metadata
    if expected_scaler is not None:
        ckpt_scaler = data.get("scaler", {})
        if round(float(ckpt_scaler.get("mean", 0.0)), 4) != round(expected_scaler.mean, 4):
            raise ValueError(f"Scaler mean mismatch: {ckpt_scaler.get('mean')} vs {expected_scaler.mean}")
        if round(float(ckpt_scaler.get("std", 0.0)), 4) != round(expected_scaler.std, 4):
            raise ValueError(f"Scaler std mismatch: {ckpt_scaler.get('std')} vs {expected_scaler.std}")
        if int(ckpt_scaler.get("count", 0)) != expected_scaler.count:
            raise ValueError(f"Scaler count mismatch: {ckpt_scaler.get('count')} vs {expected_scaler.count}")
        if round(float(ckpt_scaler.get("p95", 0.0)), 4) != round(expected_scaler.p95, 4):
            raise ValueError(f"Scaler p95 mismatch: {ckpt_scaler.get('p95')} vs {expected_scaler.p95}")
        if ckpt_scaler.get("train_start_utc") != expected_scaler.train_start_utc:
            raise ValueError(f"Scaler train_start_utc mismatch: {ckpt_scaler.get('train_start_utc')} vs {expected_scaler.train_start_utc}")
        if ckpt_scaler.get("train_end_exclusive_utc") != expected_scaler.train_end_exclusive_utc:
            raise ValueError(f"Scaler train_end_exclusive_utc mismatch: {ckpt_scaler.get('train_end_exclusive_utc')} vs {expected_scaler.train_end_exclusive_utc}")

    model = TinyTemperatureLSTM(
        input_size=arch.get("input_size", 5),
        hidden_size=arch.get("hidden_size", 32),
        num_layers=arch.get("num_layers", 1),
        horizon=arch.get("horizon", 24),
        dropout=arch.get("dropout", 0.1),
    )
    model.load_state_dict(data["model_state_dict"])
    model.eval()

    return model, data
