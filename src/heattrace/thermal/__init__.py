"""Thermal stress package for HeatTrace."""

from heattrace.thermal.model import (
    ThermalScenario,
    build_hourly_thermal_state,
    effective_compute_capacity_kw,
    facility_energy_kwh,
    facility_power_kw,
    pue_from_temperature,
)
from heattrace.thermal.facility import (
    FacilityConfig,
    FacilityModelKind,
    build_forecast_facility_state,
    build_realized_facility_state,
    get_preset_thermal_scenario,
)
from heattrace.thermal.metrics import score_thermal_schedule
from heattrace.thermal.scheduler import (
    HeatAwareCapacityAdapter,
    create_temperature_unaware_schedule,
)
from heattrace.thermal.policies import (
    CapacityAwarePolicy,
    FullThermalAwarePolicy,
    OracleFullThermalAwarePolicy,
    StaticUnawarePolicy,
    get_p6_policy,
)
from heattrace.thermal.heatguard import (
    FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256,
    HeatGuardCommitmentStep,
    HeatGuardMarginMode,
    HeatGuardRollingResult,
    HeatGuardScheduler,
    compute_safe_capacity_vector,
    validate_heatguard_workload_df,
)
from heattrace.thermal.validation import (
    compute_configuration_digest,
    compute_workload_digest,
    validate_heatguard_config,
    validate_matched_inputs,
    validate_p6_validity_config,
    validate_schedule_bounds,
    validate_window_series,
)

__all__ = [
    "ThermalScenario",
    "pue_from_temperature",
    "facility_power_kw",
    "facility_energy_kwh",
    "effective_compute_capacity_kw",
    "build_hourly_thermal_state",
    "FacilityModelKind",
    "FacilityConfig",
    "get_preset_thermal_scenario",
    "build_forecast_facility_state",
    "build_realized_facility_state",
    "score_thermal_schedule",
    "HeatAwareCapacityAdapter",
    "create_temperature_unaware_schedule",
    "StaticUnawarePolicy",
    "CapacityAwarePolicy",
    "FullThermalAwarePolicy",
    "OracleFullThermalAwarePolicy",
    "get_p6_policy",
    "compute_workload_digest",
    "compute_configuration_digest",
    "validate_matched_inputs",
    "validate_window_series",
    "validate_schedule_bounds",
    "HeatGuardScheduler",
    "HeatGuardMarginMode",
    "HeatGuardCommitmentStep",
    "HeatGuardRollingResult",
    "compute_safe_capacity_vector",
    "validate_heatguard_workload_df",
    "validate_heatguard_config",
    "validate_p6_validity_config",
]
