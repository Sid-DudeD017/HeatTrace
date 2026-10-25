"""Calibration routines for past-only PUE safety margins in HeatTrace Phase 5."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_sha256_hex(val: Any, name: str) -> str:
    """Validate that val is a 64-character lowercase hexadecimal SHA-256 string."""
    if not isinstance(val, str) or not SHA256_HEX_PATTERN.match(val):
        raise ValueError(
            f"'{name}' must be a valid 64-character lowercase hexadecimal SHA-256 string, got {val!r}"
        )
    return val


@dataclass(frozen=True)
class CalibrationResult:
    """Immutable calibration outcome containing fitted safety margin and provenance."""

    q: float
    quantile_method: str
    calibrated_margin: float
    origin_count: int
    residual_count: int
    calibration_start_utc: str
    calibration_end_exclusive_utc: str
    facility_scenario_id: str
    p4_artifact_manifest_hash: str
    checkpoint_hash: str
    forecast_config_hash: str
    split_hash: str
    created_at_utc: str
    is_fallback: bool = False
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.q, bool) or not isinstance(self.q, (int, float)):
            raise TypeError("q must be numeric float")
        if isinstance(self.calibrated_margin, bool) or not isinstance(self.calibrated_margin, (int, float)):
            raise TypeError("calibrated_margin must be numeric float")
        if not math.isfinite(self.calibrated_margin) or self.calibrated_margin < 0.0:
            raise ValueError(f"calibrated_margin must be finite and >= 0, got {self.calibrated_margin}")

        validate_sha256_hex(self.p4_artifact_manifest_hash, "p4_artifact_manifest_hash")
        validate_sha256_hex(self.checkpoint_hash, "checkpoint_hash")
        validate_sha256_hex(self.forecast_config_hash, "forecast_config_hash")
        validate_sha256_hex(self.split_hash, "split_hash")

    def to_dict(self) -> dict[str, Any]:
        """Convert result to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationResult:
        """Construct CalibrationResult from dictionary."""
        return cls(
            q=float(data["q"]),
            quantile_method=str(data["quantile_method"]),
            calibrated_margin=float(data["calibrated_margin"]),
            origin_count=int(data["origin_count"]),
            residual_count=int(data["residual_count"]),
            calibration_start_utc=str(data["calibration_start_utc"]),
            calibration_end_exclusive_utc=str(data["calibration_end_exclusive_utc"]),
            facility_scenario_id=str(data["facility_scenario_id"]),
            p4_artifact_manifest_hash=validate_sha256_hex(
                data.get("p4_artifact_manifest_hash"), "p4_artifact_manifest_hash"
            ),
            checkpoint_hash=validate_sha256_hex(data.get("checkpoint_hash"), "checkpoint_hash"),
            forecast_config_hash=validate_sha256_hex(
                data.get("forecast_config_hash"), "forecast_config_hash"
            ),
            split_hash=validate_sha256_hex(data.get("split_hash"), "split_hash"),
            created_at_utc=str(data["created_at_utc"]),
            is_fallback=bool(data.get("is_fallback", False)),
            fallback_reason=data.get("fallback_reason"),
        )


def compute_pue_residuals(
    forecast_temperatures: np.ndarray,
    realized_temperatures: np.ndarray,
    thermal_scenario: ThermalScenario,
) -> np.ndarray:
    """Convert forecast and realized temperatures to PUE and compute residuals.

    residual = realized_PUE - forecast_PUE
    """
    f_temps = np.asarray(forecast_temperatures, dtype=np.float64)
    r_temps = np.asarray(realized_temperatures, dtype=np.float64)

    if f_temps.shape != r_temps.shape:
        raise ValueError(
            f"Shape mismatch: forecast {f_temps.shape} vs realized {r_temps.shape}"
        )
    if not np.all(np.isfinite(f_temps)):
        raise ValueError("forecast_temperatures contains non-finite values (NaN/Inf)")
    if not np.all(np.isfinite(r_temps)):
        raise ValueError("realized_temperatures contains non-finite values (NaN/Inf)")

    from heattrace.thermal.model import ThermalScenario, pue_from_temperature

    forecast_pue = pue_from_temperature(f_temps, thermal_scenario)
    realized_pue = pue_from_temperature(r_temps, thermal_scenario)

    residuals = np.asarray(realized_pue, dtype=np.float64) - np.asarray(forecast_pue, dtype=np.float64)
    if not np.all(np.isfinite(residuals)):
        raise ValueError("Computed residuals contain non-finite values")
    return residuals


def compute_calibrated_safety_margin(
    residuals: np.ndarray,
    q: float = 0.90,
    method: str = "higher",
) -> float:
    """Compute calibrated safety margin: max(0, quantile(residuals, q, method=method))."""
    if isinstance(q, bool) or not isinstance(q, (int, float)):
        raise TypeError(f"Quantile q must be numeric float, got {type(q).__name__}")
    q_val = float(q)
    if not math.isfinite(q_val) or not (0.0 < q_val < 1.0):
        raise ValueError(f"Quantile q must be finite and strictly in (0, 1), got {q_val}")

    if method != "higher":
        raise ValueError(f"quantile method must be 'higher', got '{method}'")

    res_arr = np.asarray(residuals, dtype=np.float64).flatten()
    if res_arr.size == 0:
        raise ValueError("residuals array cannot be empty")
    if not np.all(np.isfinite(res_arr)):
        raise ValueError("residuals contains non-finite values")

    raw_quantile = float(np.percentile(res_arr, q_val * 100.0, method=method))
    m_cal = max(0.0, raw_quantile)
    return float(m_cal)


def compute_safe_pue(
    forecast_pue: float | np.ndarray,
    safety_margin: float,
    max_pue: float = 1.70,
) -> float | np.ndarray:
    """Compute pue_safe = min(max_pue, forecast_pue + safety_margin)."""
    if isinstance(safety_margin, bool) or not isinstance(safety_margin, (int, float)):
        raise TypeError("safety_margin must be a numeric float")
    margin_val = float(safety_margin)
    if not math.isfinite(margin_val) or margin_val < 0.0:
        raise ValueError(f"safety_margin must be finite and >= 0, got {margin_val}")

    if isinstance(max_pue, bool) or not isinstance(max_pue, (int, float)):
        raise TypeError("max_pue must be a numeric float")
    max_pue_val = float(max_pue)
    if not math.isfinite(max_pue_val) or max_pue_val < 1.0:
        raise ValueError(f"max_pue must be finite and >= 1.0, got {max_pue_val}")

    if isinstance(forecast_pue, (int, float)):
        val = float(forecast_pue)
        if not math.isfinite(val) or val < 1.0:
            raise ValueError(f"forecast_pue must be finite and >= 1.0, got {val}")
        return float(min(max_pue_val, val + margin_val))

    arr = np.asarray(forecast_pue, dtype=np.float64)
    if not np.all(np.isfinite(arr)) or np.any(arr < 1.0):
        raise ValueError("forecast_pue array contains non-finite values or values < 1.0")
    safe_arr = np.minimum(max_pue_val, arr + margin_val)
    return safe_arr


def calibrate_safety_margin(
    origins: list[datetime],
    forecast_temperatures: np.ndarray | None = None,
    realized_temperatures: np.ndarray | None = None,
    *,
    expected_p4_manifest_hash: str,
    actual_p4_manifest_hash: str,
    expected_checkpoint_hash: str,
    actual_checkpoint_hash: str,
    expected_forecast_config_hash: str,
    actual_forecast_config_hash: str,
    expected_split_hash: str,
    actual_split_hash: str,
    q: float = 0.90,
    method: str = "higher",
    thermal_scenario_id: str = "medium",
    calibration_start_utc: datetime | str = "2022-06-01T00:00:00+00:00",
    calibration_end_exclusive_utc: datetime | str = "2022-06-16T00:00:00+00:00",
    min_distinct_origins: int = 100,
    allow_fixed_fallback: bool = False,
    fixed_pue_margin: float = 0.10,
) -> CalibrationResult:
    """Perform strictly validated, past-only PUE safety margin calibration.

    All contract fields and provenance hashes are validated BEFORE any fallback return:
    - Non-empty 64-char hex SHA-256 strings required for P4 manifest, checkpoint, forecast config, split
    - expected == actual for all provenance hashes
    - q must be finite, non-boolean, and exactly 0.90
    - method must be 'higher'
    - thermal_scenario_id must be 'medium'
    - fixed_pue_margin must be finite, non-boolean, and exactly 0.10
    - min_distinct_origins must be positive integer and exactly 100
    - calibration boundaries must be valid explicit UTC with start < end_exclusive
    - arrays (if provided) must have valid matching shapes (N, 24) and finite values
    - every origin must satisfy:
        calibration_start <= origin and origin + 24 hours <= calibration_end_exclusive
    """
    # 1. Validate required provenance hashes first
    validate_sha256_hex(expected_p4_manifest_hash, "expected_p4_manifest_hash")
    validate_sha256_hex(actual_p4_manifest_hash, "actual_p4_manifest_hash")
    if actual_p4_manifest_hash != expected_p4_manifest_hash:
        raise ValueError(
            f"P4 manifest hash mismatch: actual {actual_p4_manifest_hash} != expected {expected_p4_manifest_hash}"
        )

    validate_sha256_hex(expected_checkpoint_hash, "expected_checkpoint_hash")
    validate_sha256_hex(actual_checkpoint_hash, "actual_checkpoint_hash")
    if actual_checkpoint_hash != expected_checkpoint_hash:
        raise ValueError(
            f"Checkpoint hash mismatch: actual {actual_checkpoint_hash} != expected {expected_checkpoint_hash}"
        )

    validate_sha256_hex(expected_forecast_config_hash, "expected_forecast_config_hash")
    validate_sha256_hex(actual_forecast_config_hash, "actual_forecast_config_hash")
    if actual_forecast_config_hash != expected_forecast_config_hash:
        raise ValueError(
            f"Forecast config hash mismatch: actual {actual_forecast_config_hash} != expected {expected_forecast_config_hash}"
        )

    validate_sha256_hex(expected_split_hash, "expected_split_hash")
    validate_sha256_hex(actual_split_hash, "actual_split_hash")
    if actual_split_hash != expected_split_hash:
        raise ValueError(
            f"Split hash mismatch: actual {actual_split_hash} != expected {expected_split_hash}"
        )

    # 2. Validate contract parameters
    if isinstance(q, bool) or not isinstance(q, (int, float)):
        raise TypeError(f"Quantile q must be numeric float, got {type(q).__name__}")
    q_val = float(q)
    if not math.isfinite(q_val) or not math.isclose(q_val, 0.90, abs_tol=1e-6):
        raise ValueError(f"Quantile q must be finite and exactly 0.90 per frozen contract, got {q_val}")

    if method != "higher":
        raise ValueError(f"quantile method must be 'higher', got '{method}'")

    if thermal_scenario_id != "medium":
        raise ValueError(f"thermal_scenario_id must be 'medium' per frozen contract, got '{thermal_scenario_id}'")

    if isinstance(fixed_pue_margin, bool) or not isinstance(fixed_pue_margin, (int, float)):
        raise TypeError("fixed_pue_margin must be numeric float")
    fixed_margin_val = float(fixed_pue_margin)
    if not math.isfinite(fixed_margin_val) or not math.isclose(fixed_margin_val, 0.10, abs_tol=1e-6):
        raise ValueError(f"fixed_pue_margin must be finite and exactly 0.10 per frozen contract, got {fixed_margin_val}")

    if isinstance(min_distinct_origins, bool) or not isinstance(min_distinct_origins, int):
        raise TypeError(f"min_distinct_origins must be an integer, got {type(min_distinct_origins).__name__}")
    if min_distinct_origins != 100:
        raise ValueError(f"min_distinct_origins must be exactly 100 per frozen contract, got {min_distinct_origins}")

    # 3. Parse and validate calibration boundaries
    if isinstance(calibration_start_utc, str):
        try:
            cal_start = datetime.fromisoformat(calibration_start_utc)
        except Exception as exc:
            raise ValueError(f"Invalid calibration_start_utc timestamp: {exc}") from exc
    elif isinstance(calibration_start_utc, datetime):
        cal_start = calibration_start_utc
    else:
        raise TypeError("calibration_start_utc must be datetime or ISO string")

    if isinstance(calibration_end_exclusive_utc, str):
        try:
            cal_end = datetime.fromisoformat(calibration_end_exclusive_utc)
        except Exception as exc:
            raise ValueError(f"Invalid calibration_end_exclusive_utc timestamp: {exc}") from exc
    elif isinstance(calibration_end_exclusive_utc, datetime):
        cal_end = calibration_end_exclusive_utc
    else:
        raise TypeError("calibration_end_exclusive_utc must be datetime or ISO string")

    if cal_start.tzinfo is None or cal_start.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"calibration_start_utc must be explicit UTC, got {cal_start}")
    if cal_end.tzinfo is None or cal_end.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"calibration_end_exclusive_utc must be explicit UTC, got {cal_end}")
    if cal_start >= cal_end:
        raise ValueError("calibration_start_utc must be strictly earlier than calibration_end_exclusive_utc")

    # 4. Handle empty origins or fallback if requested
    if origins is None or len(origins) == 0:
        if allow_fixed_fallback:
            return CalibrationResult(
                q=q_val,
                quantile_method=method,
                calibrated_margin=fixed_margin_val,
                origin_count=0,
                residual_count=0,
                calibration_start_utc=cal_start.isoformat(),
                calibration_end_exclusive_utc=cal_end.isoformat(),
                facility_scenario_id=thermal_scenario_id,
                p4_artifact_manifest_hash=actual_p4_manifest_hash,
                checkpoint_hash=actual_checkpoint_hash,
                forecast_config_hash=actual_forecast_config_hash,
                split_hash=actual_split_hash,
                created_at_utc=datetime.now(timezone.utc).isoformat(),
                is_fallback=True,
                fallback_reason="Empty calibration origins provided; invoked explicitly labeled fixed fallback",
            )
        raise ValueError("origins list cannot be empty")

    # 5. Validate individual origins and 24-hour target boundaries
    for i, orig in enumerate(origins):
        if not isinstance(orig, datetime):
            raise TypeError(f"Origin at index {i} must be datetime, got {type(orig).__name__}")
        if orig.tzinfo is None or orig.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError(f"Origin {orig} at index {i} must be explicit UTC")

        if orig < cal_start:
            raise ValueError(
                f"Origin {orig.isoformat()} starts before calibration start {cal_start.isoformat()}"
            )
        target_end = orig + timedelta(hours=24)
        if target_end > cal_end:
            raise ValueError(
                f"Origin {orig.isoformat()} with 24-hour target end {target_end.isoformat()} "
                f"crosses calibration reservation boundary {cal_end.isoformat()}"
            )

    # Check unique and strictly chronological
    for i in range(1, len(origins)):
        if origins[i] <= origins[i - 1]:
            raise ValueError(
                f"Origins must be strictly chronological and unique: {origins[i - 1].isoformat()} >= {origins[i].isoformat()}"
            )

    # 6. Validate temperature arrays
    if forecast_temperatures is None or realized_temperatures is None:
        raise ValueError("forecast_temperatures and realized_temperatures must be provided")

    f_temps = np.asarray(forecast_temperatures, dtype=np.float64)
    r_temps = np.asarray(realized_temperatures, dtype=np.float64)

    if f_temps.ndim != 2 or r_temps.ndim != 2:
        raise ValueError(
            f"Expected 2D arrays (N, 24), got forecast ndim={f_temps.ndim}, realized ndim={r_temps.ndim}"
        )
    if f_temps.shape != r_temps.shape:
        raise ValueError(
            f"Shape mismatch: forecast {f_temps.shape} vs realized {r_temps.shape}"
        )
    if f_temps.shape[0] != len(origins):
        raise ValueError(
            f"Origin count ({len(origins)}) does not match temperature rows ({f_temps.shape[0]})"
        )
    if f_temps.shape[1] != 24:
        raise ValueError(f"Horizon must be exactly 24, got {f_temps.shape[1]}")

    if not np.all(np.isfinite(f_temps)):
        raise ValueError("forecast_temperatures contains missing or non-finite values")
    if not np.all(np.isfinite(r_temps)):
        raise ValueError("realized_temperatures contains missing or non-finite values")

    # 7. Check distinct origin count against minimum support
    origin_count = len(origins)
    if origin_count < min_distinct_origins:
        if allow_fixed_fallback:
            return CalibrationResult(
                q=q_val,
                quantile_method=method,
                calibrated_margin=fixed_margin_val,
                origin_count=origin_count,
                residual_count=origin_count * 24,
                calibration_start_utc=cal_start.isoformat(),
                calibration_end_exclusive_utc=cal_end.isoformat(),
                facility_scenario_id=thermal_scenario_id,
                p4_artifact_manifest_hash=actual_p4_manifest_hash,
                checkpoint_hash=actual_checkpoint_hash,
                forecast_config_hash=actual_forecast_config_hash,
                split_hash=actual_split_hash,
                created_at_utc=datetime.now(timezone.utc).isoformat(),
                is_fallback=True,
                fallback_reason=(
                    f"Insufficient distinct calibration origins ({origin_count} < {min_distinct_origins}); "
                    f"invoked fixed fallback margin {fixed_margin_val}"
                ),
            )
        raise ValueError(
            f"Insufficient calibration support: {origin_count} distinct origins < minimum {min_distinct_origins}"
        )

    # 8. Compute residuals and calibrated margin
    from heattrace.thermal.facility import get_preset_thermal_scenario
    thermal_scenario = get_preset_thermal_scenario(thermal_scenario_id)
    residuals = compute_pue_residuals(f_temps, r_temps, thermal_scenario)
    m_cal = compute_calibrated_safety_margin(residuals, q=q_val, method=method)

    return CalibrationResult(
        q=q_val,
        quantile_method=method,
        calibrated_margin=m_cal,
        origin_count=origin_count,
        residual_count=int(residuals.size),
        calibration_start_utc=cal_start.isoformat(),
        calibration_end_exclusive_utc=cal_end.isoformat(),
        facility_scenario_id=thermal_scenario_id,
        p4_artifact_manifest_hash=actual_p4_manifest_hash,
        checkpoint_hash=actual_checkpoint_hash,
        forecast_config_hash=actual_forecast_config_hash,
        split_hash=actual_split_hash,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        is_fallback=False,
        fallback_reason=None,
    )


def save_calibration_artifact(
    calibration_result: CalibrationResult,
    output_dir: Path | str,
    provenance_metadata: dict[str, Any] | None = None,
) -> Path:
    """Save calibration result and manifest deterministically to directory.

    Refuses to write into an existing non-empty directory to prevent accidental mutation.
    """
    out_dir = Path(output_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"Target artifact directory exists and is non-empty: {out_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    cal_path = out_dir / "calibration.json"
    cal_data = calibration_result.to_dict()
    cal_bytes = json.dumps(cal_data, indent=2, sort_keys=True).encode("utf-8")
    with open(cal_path, "wb") as f:
        f.write(cal_bytes)

    cal_sha256 = hashlib.sha256(cal_bytes).hexdigest()

    manifest_data = {
        "artifact_name": out_dir.name,
        "artifact_type": "heatguard_pue_calibration",
        "calibrated_margin": calibration_result.calibrated_margin,
        "q": calibration_result.q,
        "quantile_method": calibration_result.quantile_method,
        "origin_count": calibration_result.origin_count,
        "residual_count": calibration_result.residual_count,
        "calibration_start_utc": calibration_result.calibration_start_utc,
        "calibration_end_exclusive_utc": calibration_result.calibration_end_exclusive_utc,
        "facility_scenario_id": calibration_result.facility_scenario_id,
        "is_fallback": calibration_result.is_fallback,
        "fallback_reason": calibration_result.fallback_reason,
        "provenance": provenance_metadata or {},
        "file_hashes": {
            "calibration.json": cal_sha256,
        },
        "created_at_utc": calibration_result.created_at_utc,
    }

    manifest_path = out_dir / "manifest.json"
    manifest_bytes = json.dumps(manifest_data, indent=2, sort_keys=True).encode("utf-8")
    with open(manifest_path, "wb") as f:
        f.write(manifest_bytes)

    return out_dir


def load_calibration_artifact(
    artifact_dir: Path | str,
    expected_manifest_sha256: str,
    repository_root: Path | str,
) -> tuple[CalibrationResult, dict[str, Any]]:
    """Strictly load and verify a self-verifiable V3 calibration artifact directory.

    Mandatory Production Invariants:
    1. expected_manifest_sha256 is mandatory and must match manifest.json exactly.
    2. repository_root is mandatory and must contain required P4 files and raw source datasets.
    3. manifest.json must declare artifact_name 'p6_heatguard_calibration_v3', artifact_type
       'heatguard_pue_calibration', and artifact_version 'v3'.
    4. Recomputes and verifies SHA-256 for all declared artifact files:
       calibration.json, origins.json, forecast_temperatures.npy, realized_temperatures.npy, residuals.npy.
    5. Checks exact array shapes (265, 24) and declared dtypes (float32, float32, float64).
    6. Verifies 265 unique, chronological, explicit-UTC origins within reservation.
    7. Recomputes residuals through the frozen medium thermal curve and checks array equality.
    8. Recomputes Q0.90 'higher' margin and verifies it matches calibration.json and manifest.json.
    9. Requires data/models/p6_temperature_v2/artifact_manifest.json and
       data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt in repository_root, and verifies
       their SHA-256 hashes against frozen Phase 4 constants.
    10. Recomputes and verifies SHA-256 for all non-empty source_dataset_files.
    """
    if expected_manifest_sha256 is None:
        raise ValueError("expected_manifest_sha256 is mandatory for strict V3 calibration loading")
    if repository_root is None:
        raise ValueError("repository_root is mandatory for strict V3 calibration loading")

    validate_sha256_hex(expected_manifest_sha256, "expected_manifest_sha256")
    repo_root = Path(repository_root)
    if not repo_root.exists():
        raise FileNotFoundError(f"Repository root does not exist: {repo_root}")

    art_dir = Path(artifact_dir)
    if not art_dir.exists():
        raise FileNotFoundError(f"Calibration artifact directory not found: {art_dir}")

    manifest_path = art_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest.json in {art_dir}")

    with open(manifest_path, "rb") as f:
        manifest_bytes = f.read()
    actual_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ValueError(
            f"Manifest SHA-256 mismatch: actual {actual_manifest_sha256} != expected {expected_manifest_sha256}"
        )

    manifest_data = json.loads(manifest_bytes.decode("utf-8"))

    # Strict V3 metadata checks
    if manifest_data.get("artifact_name") != "p6_heatguard_calibration_v3":
        raise ValueError(
            f"artifact_name must be 'p6_heatguard_calibration_v3', got '{manifest_data.get('artifact_name')}'"
        )
    if manifest_data.get("artifact_type") != "heatguard_pue_calibration":
        raise ValueError(
            f"artifact_type must be 'heatguard_pue_calibration', got '{manifest_data.get('artifact_type')}'"
        )
    if manifest_data.get("artifact_version") != "v3":
        raise ValueError(
            f"artifact_version must be 'v3', got '{manifest_data.get('artifact_version')}'"
        )

    file_hashes = manifest_data.get("file_hashes", {})
    if not isinstance(file_hashes, dict):
        raise ValueError("manifest.json missing required 'file_hashes' mapping")

    required_file_entries = {
        "calibration.json",
        "origins.json",
        "forecast_temperatures.npy",
        "realized_temperatures.npy",
        "residuals.npy",
    }
    missing_file_entries = required_file_entries - set(file_hashes.keys())
    if missing_file_entries:
        raise ValueError(f"manifest.json file_hashes missing required entries: {sorted(missing_file_entries)}")

    # Check and verify every declared file
    for filename, expected_hash in file_hashes.items():
        file_path = art_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Declared artifact file missing: {file_path}")
        with open(file_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"Artifact file '{filename}' tamper detected: sha256 {actual_hash} != manifest {expected_hash}"
            )

    cal_path = art_dir / "calibration.json"
    with open(cal_path, "rb") as f:
        cal_data = json.loads(f.read().decode("utf-8"))
    res = CalibrationResult.from_dict(cal_data)

    if res.is_fallback:
        raise ValueError("Strict V3 loading rejects fallback calibration artifacts")

    # Cross-check manifest values against calibration.json
    cross_checks = [
        ("calibrated_margin", res.calibrated_margin),
        ("q", res.q),
        ("quantile_method", res.quantile_method),
        ("origin_count", res.origin_count),
        ("residual_count", res.residual_count),
        ("calibration_start_utc", res.calibration_start_utc),
        ("calibration_end_exclusive_utc", res.calibration_end_exclusive_utc),
        ("facility_scenario_id", res.facility_scenario_id),
        ("is_fallback", res.is_fallback),
    ]
    for key, val in cross_checks:
        if key not in manifest_data:
            raise ValueError(f"manifest.json missing required field '{key}'")
        if manifest_data[key] != val:
            raise ValueError(
                f"Manifest cross-check mismatch for '{key}': manifest {manifest_data[key]} != calibration.json {val}"
            )

    prov = manifest_data.get("provenance", {})
    if not isinstance(prov, dict) or not prov:
        raise ValueError("manifest.json missing required 'provenance' mapping")

    # Validate provenance hashes against CalibrationResult
    for pkey in [
        "p4_artifact_manifest_hash",
        "checkpoint_hash",
        "forecast_config_hash",
        "split_hash",
    ]:
        if pkey not in prov:
            raise ValueError(f"manifest.json provenance missing required '{pkey}'")
        val_p = prov[pkey]
        val_r = getattr(res, pkey)
        if val_p != val_r:
            raise ValueError(
                f"Provenance mismatch for '{pkey}': manifest {val_p} != calibration.json {val_r}"
            )

    # Validate declared array metadata in provenance
    arrays_meta = prov.get("arrays", {})
    if not isinstance(arrays_meta, dict):
        raise ValueError("manifest.json provenance missing 'arrays' metadata")

    expected_array_specs = {
        "forecast_temperatures": {"shape": [265, 24], "dtype": "float32"},
        "realized_temperatures": {"shape": [265, 24], "dtype": "float32"},
        "residuals": {"shape": [265, 24], "dtype": "float64"},
    }
    for arr_name, spec in expected_array_specs.items():
        if arr_name not in arrays_meta:
            raise ValueError(f"manifest.json arrays metadata missing '{arr_name}'")
        arr_info = arrays_meta[arr_name]
        if arr_info.get("shape") != spec["shape"]:
            raise ValueError(
                f"Array '{arr_name}' declared shape mismatch: {arr_info.get('shape')} != {spec['shape']}"
            )
        if arr_info.get("dtype") != spec["dtype"]:
            raise ValueError(
                f"Array '{arr_name}' declared dtype mismatch: {arr_info.get('dtype')} != {spec['dtype']}"
            )

    # 1. origins.json validation
    origins_path = art_dir / "origins.json"
    with open(origins_path, "r", encoding="utf-8") as f:
        origins_raw = json.load(f)
    if not isinstance(origins_raw, list) or len(origins_raw) != 265:
        raise ValueError(f"v3 origins.json must contain exactly 265 origins, got {len(origins_raw)}")

    cal_start = datetime.fromisoformat(res.calibration_start_utc)
    cal_end = datetime.fromisoformat(res.calibration_end_exclusive_utc)

    parsed_origins: list[datetime] = []
    for i, ostr in enumerate(origins_raw):
        odt = datetime.fromisoformat(ostr)
        if odt.tzinfo is None or odt.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError(f"Origin {ostr} must be explicit UTC")
        if odt < cal_start or (odt + timedelta(hours=24)) > cal_end:
            raise ValueError(f"Origin {ostr} target crosses reservation [{cal_start}, {cal_end})")
        if i > 0 and odt <= parsed_origins[i - 1]:
            raise ValueError(f"Origins not unique and strictly chronological: {parsed_origins[i-1]} >= {odt}")
        parsed_origins.append(odt)

    # 2. Arrays validation
    f_temps_path = art_dir / "forecast_temperatures.npy"
    r_temps_path = art_dir / "realized_temperatures.npy"
    resids_path = art_dir / "residuals.npy"

    f_temps = np.load(f_temps_path)
    r_temps = np.load(r_temps_path)
    residuals_loaded = np.load(resids_path)

    if f_temps.shape != (265, 24) or r_temps.shape != (265, 24) or residuals_loaded.shape != (265, 24):
        raise ValueError("v3 array shapes must be (265, 24)")
    if str(f_temps.dtype) != "float32":
        raise ValueError(f"forecast_temperatures.npy dtype must be float32, got {f_temps.dtype}")
    if str(r_temps.dtype) != "float32":
        raise ValueError(f"realized_temperatures.npy dtype must be float32, got {r_temps.dtype}")
    if str(residuals_loaded.dtype) != "float64":
        raise ValueError(f"residuals.npy dtype must be float64, got {residuals_loaded.dtype}")

    # 3. Recompute residuals through frozen medium curve
    from heattrace.thermal.facility import get_preset_thermal_scenario
    scenario = get_preset_thermal_scenario("medium")
    recomputed_residuals = compute_pue_residuals(f_temps, r_temps, scenario)
    if not np.allclose(recomputed_residuals, residuals_loaded, atol=1e-12):
        raise ValueError("Recomputed residuals do not match residuals.npy")

    # 4. Recompute margin
    recomputed_margin = compute_calibrated_safety_margin(recomputed_residuals, q=0.90, method="higher")
    if not math.isclose(recomputed_margin, res.calibrated_margin, abs_tol=1e-12):
        raise ValueError(
            f"Recomputed margin {recomputed_margin} does not match calibrated_margin {res.calibrated_margin}"
        )

    # 5. Resolve and verify external source datasets
    src_files = prov.get("source_dataset_files")
    if not isinstance(src_files, dict) or not src_files:
        raise ValueError("manifest.json provenance missing non-empty 'source_dataset_files'")

    for rel_path, expected_file_hash in src_files.items():
        full_path = repo_root / rel_path
        if not full_path.exists():
            raise FileNotFoundError(f"Source dataset file not found: {full_path}")
        with open(full_path, "rb") as f:
            actual_file_hash = hashlib.sha256(f.read()).hexdigest()
        if actual_file_hash != expected_file_hash:
            raise ValueError(
                f"Source dataset file '{rel_path}' hash mismatch: actual {actual_file_hash} != manifest {expected_file_hash}"
            )

    # 6. Verify required Phase 4 model files strictly
    expected_p4_manifest = "ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79"
    expected_p4_checkpoint = "69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed"

    p4_manifest_path = repo_root / "data/models/p6_temperature_v2/artifact_manifest.json"
    p4_checkpoint_path = repo_root / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"

    if not p4_manifest_path.exists():
        raise FileNotFoundError(f"Required Phase 4 artifact manifest missing: {p4_manifest_path}")
    if not p4_checkpoint_path.exists():
        raise FileNotFoundError(f"Required Phase 4 checkpoint missing: {p4_checkpoint_path}")

    with open(p4_manifest_path, "rb") as f:
        act_p4_manifest_hash = hashlib.sha256(f.read()).hexdigest()
    if act_p4_manifest_hash != expected_p4_manifest:
        raise ValueError(
            f"Phase 4 artifact manifest hash mismatch: actual {act_p4_manifest_hash} != {expected_p4_manifest}"
        )
    if act_p4_manifest_hash != res.p4_artifact_manifest_hash:
        raise ValueError(
            f"P4 artifact manifest hash mismatch with calibration result: actual {act_p4_manifest_hash} != {res.p4_artifact_manifest_hash}"
        )

    with open(p4_checkpoint_path, "rb") as f:
        act_ckpt_hash = hashlib.sha256(f.read()).hexdigest()
    if act_ckpt_hash != expected_p4_checkpoint:
        raise ValueError(
            f"Phase 4 checkpoint hash mismatch: actual {act_ckpt_hash} != {expected_p4_checkpoint}"
        )
    if act_ckpt_hash != res.checkpoint_hash:
        raise ValueError(
            f"P4 checkpoint hash mismatch with calibration result: actual {act_ckpt_hash} != {res.checkpoint_hash}"
        )

    return res, manifest_data


def load_legacy_calibration_artifact(
    artifact_dir: Path | str,
) -> tuple[CalibrationResult, dict[str, Any]]:
    """Legacy/non-production helper for reading older (V1/V2) calibration artifacts without strict V3 verification."""
    art_dir = Path(artifact_dir)
    if not art_dir.exists():
        raise FileNotFoundError(f"Calibration artifact directory not found: {art_dir}")

    manifest_path = art_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest.json in {art_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    cal_path = art_dir / "calibration.json"
    with open(cal_path, "r", encoding="utf-8") as f:
        cal_data = json.load(f)

    res = CalibrationResult.from_dict(cal_data)
    return res, manifest_data
