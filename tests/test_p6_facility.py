"""Unit and invariant tests for Phase 2 facility models."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from heattrace.thermal.facility import (
    FacilityConfig,
    FacilityModelKind,
    build_forecast_facility_state,
    build_realized_facility_state,
    get_preset_thermal_scenario,
)
from heattrace.thermal.model import (
    ThermalScenario,
    build_hourly_thermal_state,
    effective_compute_capacity_kw,
    facility_energy_kwh,
    pue_from_temperature,
)


@pytest.fixture
def low_scenario() -> ThermalScenario:
    return get_preset_thermal_scenario("low")


@pytest.fixture
def medium_scenario() -> ThermalScenario:
    return get_preset_thermal_scenario("medium")


@pytest.fixture
def sample_timestamps() -> pd.DatetimeIndex:
    return pd.date_range("2024-07-02 00:00:00", periods=5, freq="h", tz="UTC")


# =========================================================================
# 1. Energy-Only Invariant Tests
# =========================================================================

def test_energy_only_capacity_remains_nominal_at_all_temperatures(
    low_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Energy-only capacity remains exactly nominal at cool, threshold, and hot temperatures."""
    nom_cap = 500.0
    config = FacilityConfig(
        model_kind=FacilityModelKind.energy_only,
        nominal_compute_capacity_kw=nom_cap,
        thermal_scenario=low_scenario,
    )

    temps = [15.0, 22.0, 30.0, 40.0, 50.0]
    df = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})
    state = build_realized_facility_state(df, config)

    # Invariant: effective capacity must strictly equal nominal capacity at every hour
    assert np.all(state["effective_compute_capacity_kw"] == nom_cap)
    assert not state["is_facility_cap_binding"].any()

    # Derived accounting cap: facility_power_cap_kw / pue == nominal_compute_capacity_kw
    ratio = state["facility_power_cap_kw"] / state["pue"]
    np.testing.assert_allclose(ratio, nom_cap, rtol=1e-9)


def test_energy_only_pue_and_energy_increase_with_temperature(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Energy-only PUE and facility energy increase appropriately with temperature without curtailment."""
    nom_cap = 500.0
    config = FacilityConfig(
        model_kind=FacilityModelKind.energy_only,
        nominal_compute_capacity_kw=nom_cap,
        thermal_scenario=medium_scenario,
    )

    temps = [20.0, 22.0, 25.0, 30.0, 35.0]
    df = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})
    state = build_realized_facility_state(df, config)

    pues = state["pue"].values
    assert pues[0] == 1.20
    assert pues[1] == 1.20
    assert pues[2] > pues[1]
    assert pues[3] > pues[2]
    assert pues[4] > pues[3]

    # Facility energy increases under full compute workload
    compute_energy = 100.0  # kWh
    fac_energies = [facility_energy_kwh(compute_energy, p) for p in pues]
    assert fac_energies[-1] > fac_energies[0]


# =========================================================================
# 2. Power-Capped Invariant Tests
# =========================================================================

def test_power_capped_capacity_equals_explicit_formula(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Power-capped effective capacity equals min(nominal_cap, facility_cap / pue)."""
    nom_cap = 500.0
    # Custom facility cap below base PUE requirement
    fac_cap = 550.0
    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=nom_cap,
        thermal_scenario=medium_scenario,
        facility_power_cap_kw=fac_cap,
    )

    temps = [20.0, 22.0, 25.0, 30.0, 35.0]
    df = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})
    state = build_realized_facility_state(df, config)

    expected = np.minimum(nom_cap, fac_cap / state["pue"])
    np.testing.assert_allclose(state["effective_compute_capacity_kw"], expected, rtol=1e-9)


def test_power_capped_capacity_never_exceeds_nominal_and_non_increasing_with_pue(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Power-capped capacity never exceeds nominal capacity and is non-increasing as PUE rises."""
    nom_cap = 500.0
    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=nom_cap,
        thermal_scenario=medium_scenario,
    )

    temps = [10.0, 22.0, 25.0, 30.0, 35.0]
    df = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})
    state = build_realized_facility_state(df, config)

    eff_cap = state["effective_compute_capacity_kw"].values
    # Never exceeds nominal
    assert np.all(eff_cap <= nom_cap)

    # Monotonically non-increasing with temperature / PUE
    diffs = np.diff(eff_cap)
    assert np.all(diffs <= 1e-9)


def test_power_capped_at_base_pue_produces_nominal_compute_capacity(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """At base PUE, the approved derived cap (nominal * base_pue) produces nominal capacity."""
    nom_cap = 500.0
    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=nom_cap,
        thermal_scenario=medium_scenario,
    )

    temps = [15.0, 20.0, 22.0, 22.0, 20.0]
    df = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})
    state = build_realized_facility_state(df, config)

    np.testing.assert_allclose(state["effective_compute_capacity_kw"], nom_cap, rtol=1e-9)
    assert not state["is_facility_cap_binding"].any()


# =========================================================================
# 3. Determinism and Thermal Curve Hierarchy Tests
# =========================================================================

def test_preset_thermal_scenarios_deterministic_and_hierarchy():
    """Low and medium curves produce deterministic values and satisfy medium >= low."""
    low1 = get_preset_thermal_scenario("low")
    low2 = get_preset_thermal_scenario("low")
    med1 = get_preset_thermal_scenario("medium")
    med2 = get_preset_thermal_scenario("medium")

    assert low1 == low2
    assert med1 == med2

    # Check exact frozen parameters
    assert low1.base_pue == 1.20
    assert low1.threshold_temperature_c == 22.0
    assert low1.slope_per_c == 0.010
    assert low1.max_pue == 1.45

    assert med1.base_pue == 1.20
    assert med1.threshold_temperature_c == 22.0
    assert med1.slope_per_c == 0.020
    assert med1.max_pue == 1.70

    # At the same hot temperature, medium PUE >= low PUE
    hot_temp = 35.0
    pue_low = pue_from_temperature(hot_temp, low1)
    pue_med = pue_from_temperature(hot_temp, med1)
    assert pue_med >= pue_low
    assert math.isclose(pue_low, 1.20 + 13 * 0.010)
    assert math.isclose(pue_med, 1.20 + 13 * 0.020)


# =========================================================================
# 4. Forecast vs Realized Builders Separation Tests
# =========================================================================

def test_forecast_and_realized_builders_separate_and_identical_on_same_temps(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Forecast and realized builders match only when given identical temperatures and record context."""
    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=500.0,
        thermal_scenario=medium_scenario,
    )

    temps = [20.0, 22.0, 25.0, 30.0, 35.0]
    df_fc = pd.DataFrame({"timestamp_utc": sample_timestamps, "forecast_temperature_c": temps})
    df_rz = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})

    state_fc = build_forecast_facility_state(df_fc, config)
    state_rz = build_realized_facility_state(df_rz, config)

    assert (state_fc["source_context"] == "forecast").all()
    assert (state_rz["source_context"] == "realized").all()

    # Numerical outputs match
    np.testing.assert_allclose(state_fc["pue"], state_rz["pue"])
    np.testing.assert_allclose(
        state_fc["effective_compute_capacity_kw"], state_rz["effective_compute_capacity_kw"]
    )


def test_forecast_and_realized_builders_reject_wrong_or_missing_columns(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Never silently substitute realized for forecast or vice versa."""
    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=500.0,
        thermal_scenario=medium_scenario,
    )

    temps = [20.0, 22.0, 25.0, 30.0, 35.0]
    df_rz = pd.DataFrame({"timestamp_utc": sample_timestamps, "temperature_c": temps})
    df_fc = pd.DataFrame({"timestamp_utc": sample_timestamps, "forecast_temperature_c": temps})

    # Forecast builder given only temperature_c should reject substitution
    with pytest.raises(ValueError, match="cannot silently substitute"):
        build_forecast_facility_state(df_rz, config)

    # Realized builder given only forecast_temperature_c should reject substitution
    with pytest.raises(ValueError, match="cannot silently substitute"):
        build_realized_facility_state(df_fc, config)


# =========================================================================
# 5. Timestamp and Input Validation Tests
# =========================================================================

def test_builders_reject_invalid_timestamps(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Both builders reject naive, duplicate, unsorted, and non-contiguous timestamps."""
    config = FacilityConfig(
        model_kind=FacilityModelKind.energy_only,
        nominal_compute_capacity_kw=500.0,
        thermal_scenario=medium_scenario,
    )

    temps = [20.0, 22.0, 25.0, 30.0, 35.0]

    # 1. Naive timestamps
    df_naive = pd.DataFrame({
        "timestamp_utc": sample_timestamps.tz_localize(None),
        "temperature_c": temps,
    })
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        build_realized_facility_state(df_naive, config)

    # 2. Duplicate timestamps
    dup_ts = sample_timestamps.copy()
    dup_df = pd.DataFrame({
        "timestamp_utc": [dup_ts[0], dup_ts[0], dup_ts[2], dup_ts[3], dup_ts[4]],
        "temperature_c": temps,
    })
    with pytest.raises(ValueError, match="duplicate timestamps"):
        build_realized_facility_state(dup_df, config)

    # 3. Unsorted timestamps
    unsorted_df = pd.DataFrame({
        "timestamp_utc": [dup_ts[1], dup_ts[0], dup_ts[2], dup_ts[3], dup_ts[4]],
        "temperature_c": temps,
    })
    with pytest.raises(ValueError, match="strictly monotonically increasing"):
        build_realized_facility_state(unsorted_df, config)

    # 4. Non-contiguous intervals (gap)
    gap_ts = [
        dup_ts[0],
        dup_ts[1],
        dup_ts[2] + pd.Timedelta(hours=2),
        dup_ts[3] + pd.Timedelta(hours=2),
        dup_ts[4] + pd.Timedelta(hours=2),
    ]
    gap_df = pd.DataFrame({
        "timestamp_utc": gap_ts,
        "temperature_c": temps,
    })
    with pytest.raises(ValueError, match="Non-contiguous"):
        build_realized_facility_state(gap_df, config)

    # 5. Missing / NaN / Inf temperature
    nan_df = pd.DataFrame({
        "timestamp_utc": sample_timestamps,
        "temperature_c": [20.0, np.nan, 25.0, 30.0, 35.0],
    })
    with pytest.raises(ValueError, match="missing/NaN values"):
        build_realized_facility_state(nan_df, config)

    inf_df = pd.DataFrame({
        "timestamp_utc": sample_timestamps,
        "temperature_c": [20.0, np.inf, 25.0, 30.0, 35.0],
    })
    with pytest.raises(ValueError, match="non-finite"):
        build_realized_facility_state(inf_df, config)


def test_facility_config_parameter_validation(medium_scenario: ThermalScenario):
    """Invalid enum, boolean numeric values, zero/negative capacity, NaN and Inf fail loudly."""
    # Unknown model kind
    with pytest.raises(ValueError, match="Unknown facility model kind"):
        FacilityConfig(
            model_kind="unknown_model",  # type: ignore
            nominal_compute_capacity_kw=500.0,
            thermal_scenario=medium_scenario,
        )

    # Bad type model kind
    with pytest.raises(TypeError, match="FacilityModelKind or str"):
        FacilityConfig(
            model_kind=123,  # type: ignore
            nominal_compute_capacity_kw=500.0,
            thermal_scenario=medium_scenario,
        )

    # Boolean as nominal capacity
    with pytest.raises(TypeError, match="boolean"):
        FacilityConfig(
            model_kind=FacilityModelKind.energy_only,
            nominal_compute_capacity_kw=True,  # type: ignore
            thermal_scenario=medium_scenario,
        )

    # Zero or negative nominal capacity
    with pytest.raises(ValueError, match="> 0"):
        FacilityConfig(
            model_kind=FacilityModelKind.energy_only,
            nominal_compute_capacity_kw=0.0,
            thermal_scenario=medium_scenario,
        )
    with pytest.raises(ValueError, match="> 0"):
        FacilityConfig(
            model_kind=FacilityModelKind.energy_only,
            nominal_compute_capacity_kw=-100.0,
            thermal_scenario=medium_scenario,
        )

    # NaN / Inf nominal capacity
    with pytest.raises(ValueError, match="finite"):
        FacilityConfig(
            model_kind=FacilityModelKind.energy_only,
            nominal_compute_capacity_kw=float("nan"),
            thermal_scenario=medium_scenario,
        )
    with pytest.raises(ValueError, match="finite"):
        FacilityConfig(
            model_kind=FacilityModelKind.energy_only,
            nominal_compute_capacity_kw=float("inf"),
            thermal_scenario=medium_scenario,
        )

    # Invalid scenario
    with pytest.raises(TypeError, match="ThermalScenario instance"):
        FacilityConfig(
            model_kind=FacilityModelKind.energy_only,
            nominal_compute_capacity_kw=500.0,
            thermal_scenario="bad_scenario",  # type: ignore
        )

    # Boolean facility cap
    with pytest.raises(TypeError, match="boolean"):
        FacilityConfig(
            model_kind=FacilityModelKind.power_capped,
            nominal_compute_capacity_kw=500.0,
            thermal_scenario=medium_scenario,
            facility_power_cap_kw=False,  # type: ignore
        )

    # Negative or non-finite facility cap
    with pytest.raises(ValueError, match="> 0"):
        FacilityConfig(
            model_kind=FacilityModelKind.power_capped,
            nominal_compute_capacity_kw=500.0,
            thermal_scenario=medium_scenario,
            facility_power_cap_kw=-50.0,
        )
    with pytest.raises(ValueError, match="finite"):
        FacilityConfig(
            model_kind=FacilityModelKind.power_capped,
            nominal_compute_capacity_kw=500.0,
            thermal_scenario=medium_scenario,
            facility_power_cap_kw=float("nan"),
        )


# =========================================================================
# 6. Compatibility & Non-Mutation Tests
# =========================================================================

def test_existing_build_hourly_thermal_state_unchanged(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Existing build_hourly_thermal_state behavior remains completely unchanged."""
    df = pd.DataFrame({
        "timestamp_utc": sample_timestamps,
        "temperature_c": [20.0, 22.0, 25.0, 30.0, 35.0],
    })
    state = build_hourly_thermal_state(df, medium_scenario, nominal_compute_cap_kw=500.0)

    assert len(state) == 5
    assert (state["facility_power_cap_kw"] == 600.0).all()
    assert state.loc[0, "pue"] == 1.20
    assert state.loc[0, "effective_compute_capacity_kw"] == 500.0
    assert math.isclose(state.loc[4, "pue"], 1.46)
    assert math.isclose(state.loc[4, "effective_compute_capacity_kw"], 600.0 / 1.46)


def test_input_dataframe_not_mutated(
    medium_scenario: ThermalScenario, sample_timestamps: pd.DatetimeIndex
):
    """Input DataFrames are not mutated during builder execution."""
    df = pd.DataFrame({
        "timestamp_utc": sample_timestamps.copy(),
        "temperature_c": [20.0, 22.0, 25.0, 30.0, 35.0],
        "extra_col": ["a", "b", "c", "d", "e"],
    })
    orig_copy = df.copy(deep=True)

    config = FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=500.0,
        thermal_scenario=medium_scenario,
    )
    _ = build_realized_facility_state(df, config)

    pd.testing.assert_frame_equal(df, orig_copy)
