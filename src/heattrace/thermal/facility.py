"""Facility model abstractions: energy-only and power-capped models.

Phase 2 deliverables:
- FacilityModelKind enum ('energy_only', 'power_capped')
- FacilityConfig immutable configuration
- Deterministic hourly facility-state builders for forecast and realized data
- Low and medium thermal curves loaded deterministically from configuration
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from heattrace.thermal.model import (
    ThermalScenario,
    effective_compute_capacity_kw,
    facility_energy_kwh,
    facility_power_kw,
    pue_from_temperature,
)


class FacilityModelKind(str, Enum):
    """Supported facility-model kinds."""
    energy_only = "energy_only"
    power_capped = "power_capped"


@dataclass(frozen=True)
class FacilityConfig:
    """Immutable facility configuration for hourly facility-state construction.

    Parameters:
    - model_kind: FacilityModelKind enum or valid string ('energy_only', 'power_capped')
    - nominal_compute_capacity_kw: strictly positive float
    - thermal_scenario: ThermalScenario instance
    - facility_power_cap_kw: strictly positive float when specified. If None for
      power_capped, derives default nominal_compute_capacity_kw * scenario.base_pue.
    """
    model_kind: FacilityModelKind
    nominal_compute_capacity_kw: float
    thermal_scenario: ThermalScenario
    facility_power_cap_kw: float | None = None

    def __post_init__(self) -> None:
        # Validate model_kind
        kind = self.model_kind
        if isinstance(kind, str):
            try:
                kind = FacilityModelKind(kind)
                object.__setattr__(self, "model_kind", kind)
            except ValueError:
                raise ValueError(
                    f"Unknown facility model kind: {kind!r}. Expected one of "
                    f"{[k.value for k in FacilityModelKind]}"
                )
        elif not isinstance(kind, FacilityModelKind):
            raise TypeError(
                f"model_kind must be FacilityModelKind or str, got {type(kind).__name__}"
            )

        # Reject booleans used as numbers
        if isinstance(self.nominal_compute_capacity_kw, bool):
            raise TypeError(
                f"nominal_compute_capacity_kw cannot be a boolean, got {self.nominal_compute_capacity_kw!r}"
            )
        if not isinstance(self.nominal_compute_capacity_kw, (int, float)):
            raise TypeError(
                f"nominal_compute_capacity_kw must be numeric float, got {type(self.nominal_compute_capacity_kw).__name__}"
            )
        nom_cap = float(self.nominal_compute_capacity_kw)
        if not math.isfinite(nom_cap):
            raise ValueError(f"nominal_compute_capacity_kw must be finite, got {nom_cap}")
        if nom_cap <= 0.0:
            raise ValueError(f"nominal_compute_capacity_kw must be > 0, got {nom_cap}")
        object.__setattr__(self, "nominal_compute_capacity_kw", nom_cap)

        # Validate thermal_scenario
        if not isinstance(self.thermal_scenario, ThermalScenario):
            raise TypeError(
                f"thermal_scenario must be ThermalScenario instance, got {type(self.thermal_scenario).__name__}"
            )

        # Validate facility_power_cap_kw
        cap = self.facility_power_cap_kw
        if cap is not None:
            if isinstance(cap, bool):
                raise TypeError(f"facility_power_cap_kw cannot be a boolean, got {cap!r}")
            if not isinstance(cap, (int, float)):
                raise TypeError(
                    f"facility_power_cap_kw must be numeric float, got {type(cap).__name__}"
                )
            cap_val = float(cap)
            if not math.isfinite(cap_val):
                raise ValueError(f"facility_power_cap_kw must be finite, got {cap_val}")
            if cap_val <= 0.0:
                raise ValueError(f"facility_power_cap_kw must be > 0, got {cap_val}")
            object.__setattr__(self, "facility_power_cap_kw", cap_val)
        else:
            if kind == FacilityModelKind.power_capped:
                # Approved interpretation: facility_cap_kw = nominal_compute_capacity_kw * base_pue
                derived_cap = float(nom_cap * self.thermal_scenario.base_pue)
                object.__setattr__(self, "facility_power_cap_kw", derived_cap)


def get_preset_thermal_scenario(
    scenario_id: str,
    config_path: str | Path = "configs/p6_thermal.yaml",
) -> ThermalScenario:
    """Load or construct a deterministic ThermalScenario from configs/p6_thermal.yaml.

    Verifies exact frozen values:
    Shared:
        base_pue = 1.20
        threshold_temperature_c = 22.0
    Low:
        slope_per_c = 0.010
        max_pue = 1.45
    Medium:
        slope_per_c = 0.020
        max_pue = 1.70

    NOTE: Controlled simulation sensitivity, not calibrated empirical facility behavior.
    """
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError(f"scenario_id must be a non-empty string, got {scenario_id!r}")

    scenario_key = scenario_id.strip().lower()

    # Pre-registered frozen values
    frozen_specs: dict[str, dict[str, float]] = {
        "low": {
            "base_pue": 1.20,
            "threshold_temperature_c": 22.0,
            "slope_per_c": 0.010,
            "max_pue": 1.45,
        },
        "medium": {
            "base_pue": 1.20,
            "threshold_temperature_c": 22.0,
            "slope_per_c": 0.020,
            "max_pue": 1.70,
        },
        "high": {
            "base_pue": 1.20,
            "threshold_temperature_c": 22.0,
            "slope_per_c": 0.035,
            "max_pue": 2.00,
        },
    }

    p = Path(config_path)
    if p.is_file():
        import yaml
        with p.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        tm = cfg.get("thermal_model", {})
        base_pue = float(tm.get("base_pue", 1.20))
        thresh = float(tm.get("threshold_temperature_c", 22.0))
        scens = tm.get("scenarios", {})
        if scenario_key not in scens:
            raise ValueError(f"Thermal scenario '{scenario_key}' not found in {config_path}")
        scen_dict = scens[scenario_key]
        slope = float(scen_dict["slope_per_c"])
        max_pue = float(scen_dict["max_pue"])

        # Check against frozen specifications
        if scenario_key in frozen_specs:
            expected = frozen_specs[scenario_key]
            if not (
                math.isclose(base_pue, expected["base_pue"], rel_tol=1e-7)
                and math.isclose(thresh, expected["threshold_temperature_c"], rel_tol=1e-7)
                and math.isclose(slope, expected["slope_per_c"], rel_tol=1e-7)
                and math.isclose(max_pue, expected["max_pue"], rel_tol=1e-7)
            ):
                raise ValueError(
                    f"Config values in {config_path} for '{scenario_key}' do not match frozen contract"
                )
    else:
        if scenario_key not in frozen_specs:
            raise ValueError(f"Unknown preset thermal scenario: {scenario_id!r}")
        spec = frozen_specs[scenario_key]
        base_pue = spec["base_pue"]
        thresh = spec["threshold_temperature_c"]
        slope = spec["slope_per_c"]
        max_pue = spec["max_pue"]

    return ThermalScenario(
        scenario_id=scenario_key,
        base_pue=base_pue,
        threshold_temperature_c=thresh,
        slope_per_c=slope,
        max_pue=max_pue,
    )


def _validate_facility_input_df(
    df: pd.DataFrame,
    temperature_col: str,
) -> None:
    """Validate DataFrame timestamps and temperature column for facility state building.

    Rejects:
    - missing timestamps
    - missing temperature
    - duplicate timestamps
    - non-UTC or timezone-naive timestamps
    - non-hourly or non-contiguous timestamps
    - missing/non-finite temperature values
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Input must be a pd.DataFrame, got {type(df).__name__}")
    if "timestamp_utc" not in df.columns:
        raise ValueError("DataFrame is missing required column 'timestamp_utc'")
    if temperature_col not in df.columns:
        raise ValueError(f"DataFrame is missing required temperature column '{temperature_col}'")
    if len(df) == 0:
        raise ValueError("DataFrame is empty")

    ts = df["timestamp_utc"]

    # Timezone check
    if not hasattr(ts.dt, "tz") or ts.dt.tz is None:
        raise ValueError("timestamp_utc must be timezone-aware UTC, got naive timestamps")
    tz_str = str(ts.dt.tz)
    if tz_str not in ("UTC", "datetime.timezone.utc"):
        raise ValueError(f"timestamp_utc timezone must be UTC, got {tz_str}")

    # Monotonicity & duplicates
    if not ts.is_monotonic_increasing:
        raise ValueError("timestamp_utc is not strictly monotonically increasing")
    if ts.duplicated().any():
        raise ValueError("timestamp_utc contains duplicate timestamps")

    # Contiguity & hour alignment
    for i in range(len(ts)):
        t = ts.iloc[i]
        if t.minute != 0 or t.second != 0 or t.microsecond != 0:
            raise ValueError(f"timestamp_utc at row {i} ({t}) is not hour-aligned")
        if i > 0:
            prev = ts.iloc[i - 1]
            diff = (t - prev).total_seconds()
            if diff != 3600.0:
                raise ValueError(
                    f"Non-contiguous hourly interval between row {i-1} ({prev}) and {i} ({t})"
                )

    # Temperature non-finite / missing check
    temp_s = df[temperature_col]
    if temp_s.isna().any():
        raise ValueError(f"'{temperature_col}' contains missing/NaN values")

    try:
        temp_arr = np.asarray(temp_s, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"'{temperature_col}' contains non-numeric values: {exc}") from exc

    if not np.all(np.isfinite(temp_arr)):
        raise ValueError(f"'{temperature_col}' contains non-finite values (NaN/Inf)")


def _build_facility_state_internal(
    df: pd.DataFrame,
    temperature_col: str,
    config: FacilityConfig,
    source_context: str,
) -> pd.DataFrame:
    """Internal implementation for hourly facility-state construction."""
    _validate_facility_input_df(df, temperature_col)

    temp_s = df[temperature_col].astype(float)
    scenario = config.thermal_scenario
    nominal_cap = config.nominal_compute_capacity_kw

    # Compute PUE using existing pue_from_temperature (reuse existing equation)
    pue_series = pue_from_temperature(temp_s, scenario)
    pue_arr = np.asarray(pue_series, dtype=float)

    if config.model_kind == FacilityModelKind.energy_only:
        # Energy-only model:
        # effective capacity equals nominal capacity at every temperature
        effective_capacity_arr = np.full_like(pue_arr, nominal_cap, dtype=float)
        # Derived non-binding accounting cap such that facility_power_cap_kw / pue == nominal_compute_capacity_kw
        # This is a derived accounting value, not a frozen physical cap.
        facility_cap_arr = nominal_cap * pue_arr
        is_cap_binding_arr = np.zeros(len(df), dtype=bool)
    elif config.model_kind == FacilityModelKind.power_capped:
        # Power-capped model:
        # facility_power_cap_kw is fixed (frozen)
        cap = (
            config.facility_power_cap_kw
            if config.facility_power_cap_kw is not None
            else nominal_cap * scenario.base_pue
        )
        facility_cap_arr = np.full_like(pue_arr, cap, dtype=float)
        # effective_compute_capacity_kw = min(nominal_compute_capacity_kw, facility_power_cap_kw / pue)
        derived_cap_per_pue = effective_compute_capacity_kw(facility_cap_arr, pue_arr)
        effective_capacity_arr = np.minimum(nominal_cap, np.asarray(derived_cap_per_pue, dtype=float))
        is_cap_binding_arr = np.asarray(derived_cap_per_pue < (nominal_cap - 1e-9), dtype=bool)
    else:
        raise ValueError(f"Unsupported facility model kind: {config.model_kind}")

    # Build output DataFrame preserving input row order and index
    result_df = pd.DataFrame(
        {
            "timestamp_utc": df["timestamp_utc"].copy(),
            "temperature_c": temp_s.values,
            "thermal_scenario_id": scenario.scenario_id,
            "facility_model": config.model_kind.value,
            "source_context": source_context,
            "pue": pue_arr,
            "nominal_compute_capacity_kw": float(nominal_cap),
            "facility_power_cap_kw": facility_cap_arr,
            "effective_compute_capacity_kw": effective_capacity_arr,
            "is_facility_cap_binding": is_cap_binding_arr,
        },
        index=df.index,
    )
    return result_df


def build_forecast_facility_state(
    forecast_df: pd.DataFrame,
    config: FacilityConfig,
    temperature_col: str = "forecast_temperature_c",
) -> pd.DataFrame:
    """Build hourly facility state from forecast data.

    Must consume a forecast-temperature column explicitly.
    Does not substitute realized temperature for missing forecast temperature.
    """
    if "temperature_c" in forecast_df.columns and temperature_col not in forecast_df.columns:
        raise ValueError(
            f"Forecast builder requires explicit forecast temperature column '{temperature_col}'; "
            "cannot silently substitute 'temperature_c'"
        )
    return _build_facility_state_internal(
        df=forecast_df,
        temperature_col=temperature_col,
        config=config,
        source_context="forecast",
    )


def build_realized_facility_state(
    realized_df: pd.DataFrame,
    config: FacilityConfig,
    temperature_col: str = "temperature_c",
) -> pd.DataFrame:
    """Build hourly facility state from realized data.

    Must consume the realized temperature_c column explicitly.
    Does not substitute forecast temperature for missing realized temperature.
    """
    if "forecast_temperature_c" in realized_df.columns and temperature_col not in realized_df.columns:
        raise ValueError(
            f"Realized builder requires explicit realized temperature column '{temperature_col}'; "
            "cannot silently substitute 'forecast_temperature_c'"
        )
    return _build_facility_state_internal(
        df=realized_df,
        temperature_col=temperature_col,
        config=config,
        source_context="realized",
    )
