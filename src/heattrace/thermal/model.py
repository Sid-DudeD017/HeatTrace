"""Controlled thermal-stress model: temperature to PUE and facility capacities.

Core equations:
    excess_temperature = max(temperature_c - threshold_temperature_c, 0)
    pue = min(base_pue + slope_per_c * excess_temperature, max_pue)
    facility_cap_kw = nominal_compute_cap_kw * base_pue
    effective_compute_capacity_kw = facility_cap_kw / pue
    facility_power_kw = compute_power_kw * pue
    facility_energy_kwh = compute_energy_kwh * pue

DISCLAIMER: Controlled simulation sensitivity, not calibrated data-center empirical telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ThermalScenario:
    """Frozen dataclass representing thermal sensitivity parameters."""
    scenario_id: str
    base_pue: float
    threshold_temperature_c: float
    slope_per_c: float
    max_pue: float

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ValueError(f"scenario_id must be a non-empty string, got {self.scenario_id!r}")

        # Check boolean types first because isinstance(True, (int, float)) is True in Python
        for name, val in [
            ("base_pue", self.base_pue),
            ("threshold_temperature_c", self.threshold_temperature_c),
            ("slope_per_c", self.slope_per_c),
            ("max_pue", self.max_pue),
        ]:
            if isinstance(val, bool):
                raise TypeError(f"{name} cannot be a boolean, got {val!r}")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be a numeric float, got {type(val)}")
            if not math.isfinite(val):
                raise ValueError(f"{name} must be finite, got {val}")

        if self.base_pue < 1.0:
            raise ValueError(f"base_pue must be >= 1.0, got {self.base_pue}")
        if self.slope_per_c < 0.0:
            raise ValueError(f"slope_per_c must be >= 0.0, got {self.slope_per_c}")
        if self.max_pue < self.base_pue:
            raise ValueError(
                f"max_pue ({self.max_pue}) must be >= base_pue ({self.base_pue})"
            )


def pue_from_temperature(
    temperature_c: float | np.ndarray | pd.Series,
    scenario: ThermalScenario,
) -> float | np.ndarray | pd.Series:
    """Compute PUE from ambient temperature under a ThermalScenario.

    Piecewise linear formula:
        excess_temp = max(temperature_c - threshold_temperature_c, 0)
        pue = min(base_pue + slope_per_c * excess_temp, max_pue)

    Always PUE >= 1.0. Deterministic float output.
    """
    if isinstance(temperature_c, (int, float)):
        val = float(temperature_c)
        if not math.isfinite(val):
            raise ValueError(f"temperature_c must be finite, got {val}")
        excess = max(val - scenario.threshold_temperature_c, 0.0)
        pue = min(scenario.base_pue + scenario.slope_per_c * excess, scenario.max_pue)
        return float(pue)

    # Array or Series
    is_series = isinstance(temperature_c, pd.Series)
    arr = np.asarray(temperature_c, dtype=float)

    if not np.all(np.isfinite(arr)):
        raise ValueError("temperature_c contains missing or non-finite values (NaN/Inf)")

    excess = np.maximum(arr - scenario.threshold_temperature_c, 0.0)
    pue_arr = np.minimum(scenario.base_pue + scenario.slope_per_c * excess, scenario.max_pue)
    pue_arr = np.maximum(pue_arr, 1.0)

    if is_series:
        return pd.Series(pue_arr, index=temperature_c.index, name="pue")
    return pue_arr


def facility_power_kw(
    compute_power_kw: float | np.ndarray | pd.Series,
    pue: float | np.ndarray | pd.Series,
) -> float | np.ndarray | pd.Series:
    """Compute facility power: compute_power_kw * pue."""
    if isinstance(compute_power_kw, (int, float)) and isinstance(pue, (int, float)):
        c_val = float(compute_power_kw)
        p_val = float(pue)
        if not math.isfinite(c_val) or not math.isfinite(p_val):
            raise ValueError("Values must be finite")
        if c_val < 0.0:
            raise ValueError(f"compute_power_kw must be non-negative, got {c_val}")
        if p_val < 1.0:
            raise ValueError(f"pue must be >= 1.0, got {p_val}")
        return float(c_val * p_val)

    is_series = isinstance(compute_power_kw, pd.Series) or isinstance(pue, pd.Series)
    c_arr = np.asarray(compute_power_kw, dtype=float)
    p_arr = np.asarray(pue, dtype=float)

    if c_arr.shape != p_arr.shape:
        raise ValueError(f"Array shape mismatch: {c_arr.shape} vs {p_arr.shape}")
    if not np.all(np.isfinite(c_arr)) or not np.all(np.isfinite(p_arr)):
        raise ValueError("Input arrays must contain finite numbers")
    if np.any(c_arr < 0.0):
        raise ValueError("compute_power_kw cannot contain negative values")
    if np.any(p_arr < 1.0):
        raise ValueError("pue values must be >= 1.0")

    res = c_arr * p_arr
    if is_series:
        idx = compute_power_kw.index if isinstance(compute_power_kw, pd.Series) else pue.index
        return pd.Series(res, index=idx)
    return res


def facility_energy_kwh(
    compute_energy_kwh: float | np.ndarray | pd.Series,
    pue: float | np.ndarray | pd.Series,
) -> float | np.ndarray | pd.Series:
    """Compute facility energy: compute_energy_kwh * pue."""
    if isinstance(compute_energy_kwh, (int, float)) and isinstance(pue, (int, float)):
        c_val = float(compute_energy_kwh)
        p_val = float(pue)
        if not math.isfinite(c_val) or not math.isfinite(p_val):
            raise ValueError("Values must be finite")
        if c_val < 0.0:
            raise ValueError(f"compute_energy_kwh must be non-negative, got {c_val}")
        if p_val < 1.0:
            raise ValueError(f"pue must be >= 1.0, got {p_val}")
        return float(c_val * p_val)

    is_series = isinstance(compute_energy_kwh, pd.Series) or isinstance(pue, pd.Series)
    c_arr = np.asarray(compute_energy_kwh, dtype=float)
    p_arr = np.asarray(pue, dtype=float)

    if c_arr.shape != p_arr.shape:
        raise ValueError(f"Array shape mismatch: {c_arr.shape} vs {p_arr.shape}")
    if not np.all(np.isfinite(c_arr)) or not np.all(np.isfinite(p_arr)):
        raise ValueError("Input arrays must contain finite numbers")
    if np.any(c_arr < 0.0):
        raise ValueError("compute_energy_kwh cannot contain negative values")
    if np.any(p_arr < 1.0):
        raise ValueError("pue values must be >= 1.0")

    res = c_arr * p_arr
    if is_series:
        idx = compute_energy_kwh.index if isinstance(compute_energy_kwh, pd.Series) else pue.index
        return pd.Series(res, index=idx)
    return res


def effective_compute_capacity_kw(
    facility_power_cap_kw: float | np.ndarray | pd.Series,
    pue: float | np.ndarray | pd.Series,
) -> float | np.ndarray | pd.Series:
    """Compute effective compute capacity: facility_power_cap_kw / pue."""
    if isinstance(facility_power_cap_kw, (int, float)) and isinstance(pue, (int, float)):
        f_cap = float(facility_power_cap_kw)
        p_val = float(pue)
        if not math.isfinite(f_cap) or not math.isfinite(p_val):
            raise ValueError("Values must be finite")
        if f_cap <= 0.0:
            raise ValueError(f"facility_power_cap_kw must be positive, got {f_cap}")
        if p_val < 1.0:
            raise ValueError(f"pue must be >= 1.0, got {p_val}")
        return float(f_cap / p_val)

    is_series = isinstance(facility_power_cap_kw, pd.Series) or isinstance(pue, pd.Series)
    f_arr = np.asarray(facility_power_cap_kw, dtype=float)
    p_arr = np.asarray(pue, dtype=float)

    if f_arr.shape != p_arr.shape and f_arr.ndim > 0 and p_arr.ndim > 0:
        raise ValueError(f"Array shape mismatch: {f_arr.shape} vs {p_arr.shape}")
    if not np.all(np.isfinite(f_arr)) or not np.all(np.isfinite(p_arr)):
        raise ValueError("Input arrays must contain finite numbers")
    if np.any(f_arr <= 0.0):
        raise ValueError("facility_power_cap_kw must be positive")
    if np.any(p_arr < 1.0):
        raise ValueError("pue values must be >= 1.0")

    res = f_arr / p_arr
    if is_series:
        idx = pue.index if isinstance(pue, pd.Series) else facility_power_cap_kw.index
        return pd.Series(res, index=idx)
    return res


def build_hourly_thermal_state(
    realized_df: pd.DataFrame,
    scenario: ThermalScenario,
    nominal_compute_cap_kw: float,
) -> pd.DataFrame:
    """Construct hourly thermal state table from realized DataFrame.

    Derives:
        facility_cap_kw = nominal_compute_cap_kw * scenario.base_pue
        pue = pue_from_temperature(temperature_c, scenario)
        effective_compute_capacity_kw = facility_cap_kw / pue

    Requirements:
    - Preserves hourly order of realized_df.
    - Validates nominal_compute_cap_kw > 0.
    - Rejects missing / non-finite temperature_c.
    - Returns table with:
        timestamp_utc, temperature_c, thermal_scenario_id, pue,
        nominal_compute_capacity_kw, facility_power_cap_kw,
        effective_compute_capacity_kw
    """
    if nominal_compute_cap_kw <= 0:
        raise ValueError(f"nominal_compute_cap_kw must be positive, got {nominal_compute_cap_kw}")
    if "temperature_c" not in realized_df.columns:
        raise ValueError("realized_df must contain 'temperature_c' column")
    if "timestamp_utc" not in realized_df.columns:
        raise ValueError("realized_df must contain 'timestamp_utc' column")

    temp_s = realized_df["temperature_c"]
    if temp_s.isna().any() or not np.all(np.isfinite(temp_s.to_numpy(dtype=float))):
        raise ValueError("temperature_c contains missing or non-finite values")

    pue_s = pue_from_temperature(temp_s, scenario)
    facility_power_cap = float(nominal_compute_cap_kw * scenario.base_pue)
    eff_cap_s = effective_compute_capacity_kw(facility_power_cap, pue_s)

    state_df = pd.DataFrame(
        {
            "timestamp_utc": realized_df["timestamp_utc"].copy(),
            "temperature_c": temp_s.astype(float).values,
            "thermal_scenario_id": scenario.scenario_id,
            "pue": np.asarray(pue_s, dtype=float),
            "nominal_compute_capacity_kw": float(nominal_compute_cap_kw),
            "facility_power_cap_kw": facility_power_cap,
            "effective_compute_capacity_kw": np.asarray(eff_cap_s, dtype=float),
        },
        index=realized_df.index,
    )
    return state_df
