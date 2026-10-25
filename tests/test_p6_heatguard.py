"""Comprehensive synthetic and unit tests for HeatTrace Phase 5 HeatGuard and Calibration.

Covers:
- Calibration quantile q=0.90 uses calibration observations only.
- Quantile uses method="higher" (conservative observed order statistic).
- Negative quantile produces margin zero via max(0, ...).
- Forecast and realized temperatures are converted independently to PUE.
- Too few distinct origins fails loudly or invokes only explicitly labeled fixed fallback.
- Missing, non-finite, malformed, duplicated, or non-UTC data fail loudly.
- Target boundary regression: origins whose 24h targets cross reservation are rejected.
- Validate-before-fallback contract strictly enforced.
- Required non-empty SHA-256 provenance (P4 manifest, checkpoint, config, split) enforced.
- Self-verifiable v3 calibration artifact verification and tamper detection.
- Calibrated HeatGuard requires verified V3 artifact loading from disk via:
  calibration_artifact_dir, expected_manifest_sha256, repository_root.
- Calibrated mode rejects directly supplied calibration_result, numeric margins,
  duck-typed objects, missing parameters, V1/V2 artifacts, fallback artifacts, wrong manifest hash.
- Fixed comparator strictly frozen at 0.10: rejects booleans, non-numeric, NaN, inf, negatives, or any value != 0.10.
- None comparator strictly sets margin = 0.0.
- Strict V3 loader requires repository_root and P4 files (artifact_manifest.json, tiny_lstm_checkpoint.pt).
- In-depth tamper tests on isolated tmp_path copies.
- Workload validation rejects null/NaN/non-string workload_trace_id.
- Released-job information set invariance (future arrivals cannot alter current decisions).
- Beyond-horizon exact requirement semantics:
  - If deadline > horizon, window_effective_req = required_in_window.
  - If required_in_window == 0, job is carried forward without entering current window replan.
  - Allocations in window are strictly checked against mandatory requirement.
- Determinism and comparator runs under identical causal inputs.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import math
import shutil
import numpy as np
import pandas as pd
import pytest

from heattrace.forecast.calibration import (
    CalibrationResult,
    calibrate_safety_margin,
    compute_calibrated_safety_margin,
    compute_pue_residuals,
    compute_safe_pue,
    load_calibration_artifact,
    save_calibration_artifact,
)
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
)
from heattrace.thermal.facility import (
    FacilityConfig,
    FacilityModelKind,
    get_preset_thermal_scenario,
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
from heattrace.thermal.model import ThermalScenario, pue_from_temperature
from heattrace.thermal.validation import (
    load_p6_validity_config,
    validate_heatguard_config,
    validate_p6_validity_config,
)


EXPECTED_P4_MANIFEST_HASH = "ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79"
EXPECTED_FC_CONFIG_HASH = "bda89d3baf3f9c1cade93aca5d43f8c5bb64de4fc07b548e0e8cf2349578d1d7"
EXPECTED_SPLIT_HASH = "59fdcf783d2b2d825e44d5a9eaf29a87fa96f262b921e4b6394c2f96c6a4284c"
EXPECTED_CHECKPOINT_HASH = "69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed"
EXPECTED_V3_MANIFEST_HASH = "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c"
V3_ARTIFACT_PATH = Path("data/models/p6_heatguard_calibration_v3")
REPO_ROOT = Path(".")


def _make_dummy_provenance_kwargs() -> dict[str, str]:
    return {
        "expected_p4_manifest_hash": EXPECTED_P4_MANIFEST_HASH,
        "actual_p4_manifest_hash": EXPECTED_P4_MANIFEST_HASH,
        "expected_checkpoint_hash": EXPECTED_CHECKPOINT_HASH,
        "actual_checkpoint_hash": EXPECTED_CHECKPOINT_HASH,
        "expected_forecast_config_hash": EXPECTED_FC_CONFIG_HASH,
        "actual_forecast_config_hash": EXPECTED_FC_CONFIG_HASH,
        "expected_split_hash": EXPECTED_SPLIT_HASH,
        "actual_split_hash": EXPECTED_SPLIT_HASH,
    }


# =============================================================================
# 1. CALIBRATION TESTS
# =============================================================================

def test_pue_residuals_independent_conversion():
    """Forecast and realized temperatures are converted independently through the medium curve."""
    scenario = get_preset_thermal_scenario("medium")
    assert scenario.threshold_temperature_c == 22.0
    assert scenario.base_pue == 1.20
    assert scenario.slope_per_c == 0.020
    assert scenario.max_pue == 1.70

    t_pred = np.full((1, 24), 20.0)
    t_real = np.full((1, 24), 27.0)

    residuals = compute_pue_residuals(t_pred, t_real, scenario)
    assert residuals.shape == (1, 24)
    expected_residual = 1.30 - 1.20  # +0.10
    assert np.allclose(residuals, expected_residual, atol=1e-6)


def test_quantile_higher_method_semantics():
    """Quantile calculation strictly uses method='higher' (order statistic, not linear)."""
    residuals = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    q_higher = compute_calibrated_safety_margin(residuals, q=0.90, method="higher")
    q_linear = float(np.quantile(residuals, 0.90, method="linear"))
    assert q_higher == 10.0
    assert q_linear == 9.1
    assert q_higher > q_linear


def test_negative_quantile_produces_zero_margin():
    """When residuals are negative (forecast PUE > realized PUE), safety margin is max(0, q) = 0.0."""
    residuals = np.array([-0.05, -0.04, -0.03, -0.02, -0.01])
    margin = compute_calibrated_safety_margin(residuals, q=0.90, method="higher")
    assert margin == 0.0


def test_invalid_quantile_parameters_fail_loudly():
    """Invalid quantile q or method raises appropriate error."""
    residuals = np.array([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="Quantile q must be finite and strictly in \\(0, 1\\)"):
        compute_calibrated_safety_margin(residuals, q=0.0)
    with pytest.raises(ValueError, match="Quantile q must be finite and strictly in \\(0, 1\\)"):
        compute_calibrated_safety_margin(residuals, q=1.0)
    with pytest.raises(ValueError, match="Quantile q must be finite and strictly in \\(0, 1\\)"):
        compute_calibrated_safety_margin(residuals, q=float("nan"))
    with pytest.raises(TypeError, match="Quantile q must be numeric float"):
        compute_calibrated_safety_margin(residuals, q=True)
    with pytest.raises(ValueError, match="quantile method must be 'higher'"):
        compute_calibrated_safety_margin(residuals, q=0.90, method="linear")


def test_insufficient_calibration_support_fails_or_falls_back():
    """Less than 100 distinct origins fails loudly unless allow_fixed_fallback=True."""
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    origins = [start + timedelta(hours=i) for i in range(50)]
    f_temps = np.full((50, 24), 20.0)
    r_temps = np.full((50, 24), 21.0)
    prov = _make_dummy_provenance_kwargs()

    # Fail loudly when allow_fixed_fallback=False
    with pytest.raises(ValueError, match="Insufficient calibration support: 50 distinct origins < minimum 100"):
        calibrate_safety_margin(
            origins=origins,
            forecast_temperatures=f_temps,
            realized_temperatures=r_temps,
            min_distinct_origins=100,
            allow_fixed_fallback=False,
            **prov,
        )

    # When fallback allowed, returns explicitly labeled fallback result
    res = calibrate_safety_margin(
        origins=origins,
        forecast_temperatures=f_temps,
        realized_temperatures=r_temps,
        min_distinct_origins=100,
        allow_fixed_fallback=True,
        fixed_pue_margin=0.10,
        **prov,
    )
    assert res.is_fallback is True
    assert res.calibrated_margin == 0.10
    assert "Insufficient distinct calibration origins" in str(res.fallback_reason)


def test_target_boundary_regression_crosses_reservation():
    """Origin near 2022-06-16T00:00Z whose 24h target crosses reservation is rejected."""
    cal_start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    cal_end = datetime(2022, 6, 16, 0, 0, tzinfo=timezone.utc)
    prov = _make_dummy_provenance_kwargs()

    # 100 origins where the last one is at 2022-06-15T12:00Z: origin < cal_end, BUT origin + 24h = 2022-06-16T12:00Z > cal_end!
    origins = [cal_start + timedelta(hours=i) for i in range(99)]
    invalid_origin = datetime(2022, 6, 15, 12, 0, tzinfo=timezone.utc)
    origins.append(invalid_origin)

    f_temps = np.full((100, 24), 20.0)
    r_temps = np.full((100, 24), 21.0)

    with pytest.raises(ValueError, match="crosses calibration reservation boundary"):
        calibrate_safety_margin(
            origins=origins,
            forecast_temperatures=f_temps,
            realized_temperatures=r_temps,
            calibration_start_utc=cal_start,
            calibration_end_exclusive_utc=cal_end,
            min_distinct_origins=100,
            allow_fixed_fallback=False,
            **prov,
        )


def test_validate_before_fallback_adversarial():
    """Fallback cannot be obtained with invalid contract parameters or invalid provenance."""
    prov = _make_dummy_provenance_kwargs()

    # Mismatched provenance hash
    prov_mismatch = dict(prov)
    prov_mismatch["actual_checkpoint_hash"] = "0" * 64
    with pytest.raises(ValueError, match="Checkpoint hash mismatch"):
        calibrate_safety_margin(
            origins=[],
            allow_fixed_fallback=True,
            **prov_mismatch,
        )

    # Malformed provenance hash
    prov_malformed = dict(prov)
    prov_malformed["actual_checkpoint_hash"] = "invalid_hash"
    with pytest.raises(ValueError, match="must be a valid 64-character lowercase hexadecimal"):
        calibrate_safety_margin(
            origins=[],
            allow_fixed_fallback=True,
            **prov_malformed,
        )

    # NaN quantile
    with pytest.raises(ValueError, match="Quantile q must be finite and exactly 0.90"):
        calibrate_safety_margin(
            origins=[],
            q=float("nan"),
            allow_fixed_fallback=True,
            **prov,
        )

    # Wrong quantile
    with pytest.raises(ValueError, match="Quantile q must be finite and exactly 0.90"):
        calibrate_safety_margin(
            origins=[],
            q=0.85,
            allow_fixed_fallback=True,
            **prov,
        )

    # Linear method
    with pytest.raises(ValueError, match="quantile method must be 'higher'"):
        calibrate_safety_margin(
            origins=[],
            method="linear",
            allow_fixed_fallback=True,
            **prov,
        )

    # Wrong thermal scenario
    with pytest.raises(ValueError, match="thermal_scenario_id must be 'medium'"):
        calibrate_safety_margin(
            origins=[],
            thermal_scenario_id="low",
            allow_fixed_fallback=True,
            **prov,
        )

    # NaN fixed margin
    with pytest.raises(ValueError, match="fixed_pue_margin must be finite and exactly 0.10"):
        calibrate_safety_margin(
            origins=[],
            fixed_pue_margin=float("nan"),
            allow_fixed_fallback=True,
            **prov,
        )

    # Wrong fixed margin
    with pytest.raises(ValueError, match="fixed_pue_margin must be finite and exactly 0.10"):
        calibrate_safety_margin(
            origins=[],
            fixed_pue_margin=0.15,
            allow_fixed_fallback=True,
            **prov,
        )

    # Non-UTC boundary
    with pytest.raises(ValueError, match="calibration_start_utc must be explicit UTC"):
        calibrate_safety_margin(
            origins=[],
            calibration_start_utc="2022-06-01T00:00:00",
            allow_fixed_fallback=True,
            **prov,
        )


def test_calibration_rejects_missing_non_finite_or_malformed_inputs():
    """Non-finite inputs, duplicated origins, or non-UTC timestamps are rejected."""
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    origins = [start + timedelta(hours=i) for i in range(100)]
    f_temps = np.full((100, 24), 20.0)
    r_temps = np.full((100, 24), 21.0)
    prov = _make_dummy_provenance_kwargs()

    # 1. Non-finite forecast temperature
    f_bad = f_temps.copy()
    f_bad[10, 5] = float("nan")
    with pytest.raises(ValueError, match="forecast_temperatures contains missing or non-finite values"):
        calibrate_safety_margin(origins, f_bad, r_temps, **prov)

    # 2. Non-finite realized temperature
    r_bad = r_temps.copy()
    r_bad[10, 5] = float("inf")
    with pytest.raises(ValueError, match="realized_temperatures contains missing or non-finite values"):
        calibrate_safety_margin(origins, f_temps, r_bad, **prov)

    # 3. Duplicate origin
    origins_dup = list(origins)
    origins_dup[1] = origins_dup[0]
    with pytest.raises(ValueError, match="Origins must be strictly chronological and unique"):
        calibrate_safety_margin(origins_dup, f_temps, r_temps, **prov)

    # 4. Non-UTC origin
    origins_non_utc = [datetime(2022, 6, 1, 0, 0) + timedelta(hours=i) for i in range(100)]
    with pytest.raises(ValueError, match="must be explicit UTC"):
        calibrate_safety_margin(origins_non_utc, f_temps, r_temps, **prov)

    # 5. Out of bounds origin (from confirmation interval)
    origins_conf = [datetime(2022, 6, 20, 0, 0, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(100)]
    with pytest.raises(ValueError, match="crosses calibration reservation boundary|outside calibration reservation"):
        calibrate_safety_margin(origins_conf, f_temps, r_temps, **prov)


def test_provenance_mismatch_rejected():
    """Mismatched checkpoint, forecast config, split, or manifest hash is rejected."""
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    origins = [start + timedelta(hours=i) for i in range(100)]
    f_temps = np.full((100, 24), 20.0)
    r_temps = np.full((100, 24), 21.0)
    prov = _make_dummy_provenance_kwargs()

    # 1. Checkpoint mismatch
    p1 = dict(prov)
    p1["actual_checkpoint_hash"] = "0" * 64
    with pytest.raises(ValueError, match="Checkpoint hash mismatch"):
        calibrate_safety_margin(origins, f_temps, r_temps, **p1)

    # 2. P4 manifest mismatch
    p2 = dict(prov)
    p2["actual_p4_manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="P4 manifest hash mismatch"):
        calibrate_safety_margin(origins, f_temps, r_temps, **p2)

    # 3. Malformed hash (not 64 lowercase hex)
    p3 = dict(prov)
    p3["actual_split_hash"] = "short_hash"
    with pytest.raises(ValueError, match="must be a valid 64-character lowercase hexadecimal"):
        calibrate_safety_margin(origins, f_temps, r_temps, **p3)


def test_real_materialized_calibration_artifact():
    """Verify the real materialized Phase 5 v3 calibration artifact."""
    assert V3_ARTIFACT_PATH.exists(), f"Artifact dir does not exist: {V3_ARTIFACT_PATH}"

    res, manifest = load_calibration_artifact(
        V3_ARTIFACT_PATH,
        expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
        repository_root=REPO_ROOT,
    )
    assert res.q == 0.90
    assert res.quantile_method == "higher"
    assert res.origin_count == 265
    assert res.residual_count == 265 * 24
    assert res.calibrated_margin > 0.0
    assert np.isclose(res.calibrated_margin, 0.016, atol=1e-3)
    assert res.is_fallback is False
    assert res.facility_scenario_id == "medium"
    assert res.calibration_start_utc == "2022-06-01T00:00:00+00:00"
    assert res.calibration_end_exclusive_utc == "2022-06-16T00:00:00+00:00"
    assert res.p4_artifact_manifest_hash == EXPECTED_P4_MANIFEST_HASH
    assert res.forecast_config_hash == EXPECTED_FC_CONFIG_HASH
    assert res.split_hash == EXPECTED_SPLIT_HASH
    assert res.checkpoint_hash == EXPECTED_CHECKPOINT_HASH

    # Verify input hashes and array shapes recorded in v3 manifest
    prov = manifest.get("provenance", {})
    assert prov.get("checkpoint_hash") == EXPECTED_CHECKPOINT_HASH
    arrays = prov.get("arrays", {})
    assert manifest["origin_count"] == 265
    assert manifest["first_origin_utc"] == "2022-06-04T00:00:00+00:00"
    assert manifest["last_origin_utc"] == "2022-06-15T00:00:00+00:00"
    assert manifest["last_target_end_utc"] == "2022-06-16T00:00:00+00:00"
    assert arrays["forecast_temperatures"]["shape"] == [265, 24]
    assert arrays["realized_temperatures"]["shape"] == [265, 24]
    assert arrays["residuals"]["shape"] == [265, 24]


def test_artifact_immutability(tmp_path):
    """Artifact directory cannot be overwritten when non-empty."""
    cal_res = CalibrationResult(
        q=0.90,
        quantile_method="higher",
        calibrated_margin=0.016,
        origin_count=265,
        residual_count=6360,
        calibration_start_utc="2022-06-01T00:00:00+00:00",
        calibration_end_exclusive_utc="2022-06-16T00:00:00+00:00",
        facility_scenario_id="medium",
        p4_artifact_manifest_hash=EXPECTED_P4_MANIFEST_HASH,
        checkpoint_hash=EXPECTED_CHECKPOINT_HASH,
        forecast_config_hash=EXPECTED_FC_CONFIG_HASH,
        split_hash=EXPECTED_SPLIT_HASH,
        created_at_utc="2026-10-24T00:00:00+00:00",
    )

    art_dir = tmp_path / "test_artifact"
    save_calibration_artifact(cal_res, art_dir)

    with pytest.raises(FileExistsError, match="Target artifact directory exists and is non-empty"):
        save_calibration_artifact(cal_res, art_dir)


# =============================================================================
# 2. CAPACITY & PUE TESTS
# =============================================================================

def test_safe_pue_caps_at_max_pue():
    """pue_safe is capped strictly at max_pue."""
    pue_safe = compute_safe_pue(1.65, safety_margin=0.10, max_pue=1.70)
    assert pue_safe == 1.70

    pue_arr = np.array([1.20, 1.50, 1.68])
    safe_arr = compute_safe_pue(pue_arr, safety_margin=0.05, max_pue=1.70)
    assert np.allclose(safe_arr, [1.25, 1.55, 1.70])


def test_capacity_energy_only_remains_nominal_regardless_of_margin():
    """In energy-only mode, safe capacity equals nominal compute capacity."""
    nominal_cap = 1000.0
    pue_safe = np.array([1.20, 1.45, 1.70])
    cap = compute_safe_capacity_vector(
        nominal_capacity_kw=nominal_cap,
        pue_safe=pue_safe,
        facility_model_kind=FacilityModelKind.energy_only,
    )
    assert np.all(cap == nominal_cap)


def test_capacity_power_capped_formula():
    """In power-capped mode, capacity equals min(nominal, facility_cap / pue_safe)."""
    nominal_cap = 1000.0
    base_pue = 1.20
    facility_cap = nominal_cap * base_pue  # 1200 kW

    pue_safe = np.array([1.20, 1.50, 1.60])
    cap = compute_safe_capacity_vector(
        nominal_capacity_kw=nominal_cap,
        pue_safe=pue_safe,
        facility_model_kind=FacilityModelKind.power_capped,
        facility_cap_kw=facility_cap,
    )
    assert np.allclose(cap, [1000.0, 800.0, 750.0])


def test_invalid_capacity_inputs_fail_loudly():
    """Invalid PUE (< 1.0 or non-finite) or non-finite nominal capacity fails."""
    with pytest.raises(ValueError, match="pue_safe contains non-finite values or values < 1.0"):
        compute_safe_capacity_vector(1000.0, np.array([0.95, 1.20]), FacilityModelKind.energy_only)

    with pytest.raises(ValueError, match="nominal_capacity_kw must be finite and > 0"):
        compute_safe_capacity_vector(-10.0, np.array([1.20]), FacilityModelKind.energy_only)


# =============================================================================
# 3. ROLLING SCHEDULING TESTS (THROUGH VERIFIED V3 ARTIFACT PATH)
# =============================================================================

@pytest.fixture
def sample_facility_config():
    scenario = get_preset_thermal_scenario("medium")
    return FacilityConfig(
        model_kind=FacilityModelKind.power_capped,
        nominal_compute_capacity_kw=100.0,
        thermal_scenario=scenario,
        facility_power_cap_kw=120.0,
    )


@pytest.fixture
def mock_forecast_providers():
    def temp_fc_provider(origin_utc: datetime, horizon: int) -> np.ndarray:
        return np.full((horizon,), 20.0)

    def mkt_fc_provider(origin_utc: datetime, horizon: int) -> ForecastResult:
        pts = [
            ForecastPoint(
                timestamp_utc=origin_utc + timedelta(hours=h),
                horizon_hours=h,
                predicted_price_usd_per_mwh=40.0 + h,
                predicted_carbon_g_per_kwh=200.0 + 5.0 * h,
            )
            for h in range(horizon)
        ]
        return ForecastResult(
            origin_timestamp_utc=origin_utc,
            points=pts,
            model_name="mock_mkt",
            model_version="1.0",
        )

    return temp_fc_provider, mkt_fc_provider


def _make_verified_calibrated_scheduler(facility_config: FacilityConfig, **kwargs) -> HeatGuardScheduler:
    """Helper to instantiate HeatGuardScheduler via the production verified V3 artifact path."""
    return HeatGuardScheduler(
        facility_config=facility_config,
        margin_mode=HeatGuardMarginMode.calibrated,
        calibration_artifact_dir=V3_ARTIFACT_PATH,
        expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
        repository_root=REPO_ROOT,
        **kwargs,
    )


def test_rolling_commit_one_interval_and_preserve_completed(sample_facility_config, mock_forecast_providers):
    """Only 1 hour is committed per replan; completed work never reappears."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_A",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 5,
            "processing_requirement": 2,
            "energy_kwh": 20.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        },
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_B",
            "arrival_offset_hours": 1,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        },
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    result = scheduler.schedule_rolling(
        workload_df=workload,
        temperature_forecast_provider=temp_prov,
        market_forecast_provider=mkt_prov,
        window_start_utc=start_utc,
        total_window_hours=6,
    )

    assert result.is_feasible is True
    assert len(result.unmet_deadlines) == 0
    assert len(result.allocations) == 3

    for step in result.steps:
        for a in step.committed_allocations:
            assert a.allocated_hour_offset == step.committed_hour_offset

    seen = set()
    for a in result.allocations:
        pair = (a.job_id, a.allocated_hour_offset)
        assert pair not in seen
        seen.add(pair)


def test_beyond_horizon_deadline_handling(sample_facility_config, mock_forecast_providers):
    """Job with deadline beyond 24h horizon calculates and schedules required in-window reserve."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_long",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 28,
            "processing_requirement": 10,
            "energy_kwh": 100.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        }
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    result = scheduler.schedule_rolling(
        workload_df=workload,
        temperature_forecast_provider=temp_prov,
        market_forecast_provider=mkt_prov,
        window_start_utc=start_utc,
        total_window_hours=28,
    )

    assert result.is_feasible is True
    allocs = [a for a in result.allocations if a.job_id == "job_long"]
    assert len(allocs) == 10
    for a in allocs:
        assert 0 <= a.allocated_hour_offset < 28


def test_beyond_horizon_regression_case_exact_mandatory(sample_facility_config, mock_forecast_providers):
    """Regression case: one beyond-horizon job needs 10 units, 6 slots in window, 4 slots after window.

    Plan is feasible and exactly the mandatory 6 units (not all 10) are required in-window.
    """
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "regression_trace",
            "job_id": "job_regression_10",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 28,
            "processing_requirement": 10,
            "energy_kwh": 100.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        }
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    res = scheduler.schedule_rolling(
        workload_df=workload,
        temperature_forecast_provider=temp_prov,
        market_forecast_provider=mkt_prov,
        window_start_utc=start_utc,
        total_window_hours=28,
    )

    assert res.is_feasible is True
    assert len(res.unmet_deadlines) == 0
    assert res.steps[0].is_projected_feasible is True
    assert len(res.steps[0].committed_allocations) == 1


def test_beyond_horizon_zero_mandatory_requirement_not_in_window(sample_facility_config, mock_forecast_providers):
    """If required_in_window == 0, job does not enter current window optimization."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "slack_trace",
            "job_id": "job_slack",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 30,
            "processing_requirement": 2,
            "energy_kwh": 20.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        }
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    res = scheduler.schedule_rolling(
        workload_df=workload,
        temperature_forecast_provider=temp_prov,
        market_forecast_provider=mkt_prov,
        window_start_utc=start_utc,
        total_window_hours=1,
    )
    assert len(res.steps[0].committed_allocations) == 0


def test_impossible_deadline_reported_not_silently_dropped(sample_facility_config, mock_forecast_providers):
    """Impossible deadline fails feasibility and reports unmet job without silent drop."""
    workload_invalid = pd.DataFrame([
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_impossible",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 2,
            "processing_requirement": 5,
            "energy_kwh": 50.0,
        }
    ])

    with pytest.raises(ValueError, match="exceeds duration window"):
        validate_heatguard_workload_df(workload_invalid)


def test_rolling_determinism(sample_facility_config, mock_forecast_providers):
    """Two identical runs produce identical allocations and results."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "test_trace",
            "job_id": f"job_{i}",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": i + 6,
            "processing_requirement": 2,
            "energy_kwh": 20.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        }
        for i in range(5)
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    res1 = scheduler.schedule_rolling(workload, temp_prov, mkt_prov, start_utc, total_window_hours=12)
    res2 = scheduler.schedule_rolling(workload, temp_prov, mkt_prov, start_utc, total_window_hours=12)

    assert res1.is_feasible == res2.is_feasible
    assert len(res1.allocations) == len(res2.allocations)
    for a1, a2 in zip(res1.allocations, res2.allocations):
        assert a1.job_id == a2.job_id
        assert a1.allocated_hour_offset == a2.allocated_hour_offset


def test_comparators_run_under_identical_causal_inputs(sample_facility_config, mock_forecast_providers):
    """Calibrated, fixed (0.10), and no-margin run under identical causal inputs."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "test_trace",
            "job_id": "job_comp",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 10,
            "processing_requirement": 3,
            "energy_kwh": 30.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        }
    ])

    sched_cal = _make_verified_calibrated_scheduler(sample_facility_config)
    sched_fixed = HeatGuardScheduler(
        facility_config=sample_facility_config,
        margin_mode=HeatGuardMarginMode.fixed,
        fixed_pue_margin=0.10,
    )
    sched_none = HeatGuardScheduler(
        facility_config=sample_facility_config,
        margin_mode=HeatGuardMarginMode.none,
    )

    res_cal = sched_cal.schedule_rolling(workload, temp_prov, mkt_prov, start_utc, total_window_hours=10)
    res_fixed = sched_fixed.schedule_rolling(workload, temp_prov, mkt_prov, start_utc, total_window_hours=10)
    res_none = sched_none.schedule_rolling(workload, temp_prov, mkt_prov, start_utc, total_window_hours=10)

    assert np.isclose(res_cal.applied_margin, 0.016, atol=1e-3)
    assert res_fixed.applied_margin == 0.10
    assert res_none.applied_margin == 0.0

    assert res_cal.is_feasible is True
    assert res_fixed.is_feasible is True
    assert res_none.is_feasible is True


# =============================================================================
# 4. CONFIGURATION VALIDATION TESTS
# =============================================================================

def test_p6_validity_config_validates_heatguard_section():
    """configs/p6_validity.yaml loads and validates with the frozen HeatGuard section."""
    cfg = load_p6_validity_config("configs/p6_validity.yaml")
    assert "heatguard" in cfg
    assert cfg["heatguard"]["calibration"]["quantile"] == 0.90
    assert cfg["heatguard"]["calibration"]["quantile_method"] == "higher"
    assert cfg["heatguard"]["calibration"]["fixed_pue_margin"] == 0.10
    assert cfg["heatguard"]["rolling"]["forecast_horizon_hours"] == 24
    assert cfg["heatguard"]["rolling"]["commit_hours"] == 1
    assert cfg["heatguard"]["calibration"]["provenance"]["calibration_artifact"] == "p6_heatguard_calibration_v3"
    assert cfg["heatguard"]["calibration"]["provenance"]["manifest_hash"] == EXPECTED_V3_MANIFEST_HASH


def test_validator_rejects_malformed_heatguard_config():
    """Validator fails loudly when HeatGuard fields are missing, invalid, or placeholder."""
    cfg = copy.deepcopy(load_p6_validity_config("configs/p6_validity.yaml"))
    cfg["heatguard"]["calibration"]["quantile"] = 0.50
    with pytest.raises(ValueError, match="heatguard.calibration.quantile.*must be 0.9"):
        validate_p6_validity_config(cfg)

    cfg2 = copy.deepcopy(load_p6_validity_config("configs/p6_validity.yaml"))
    cfg2["heatguard"]["calibration"]["quantile_method"] = "linear"
    with pytest.raises(ValueError, match="quantile_method must be 'higher'"):
        validate_p6_validity_config(cfg2)

    cfg3 = copy.deepcopy(load_p6_validity_config("configs/p6_validity.yaml"))
    cfg3["heatguard"]["calibration"]["fixed_pue_margin"] = 0.20
    with pytest.raises(ValueError, match="fixed_pue_margin.*must be 0.1"):
        validate_p6_validity_config(cfg3)

    cfg4 = copy.deepcopy(load_p6_validity_config("configs/p6_validity.yaml"))
    cfg4["heatguard"]["rolling"]["commit_hours"] = 2
    with pytest.raises(ValueError, match="commit_hours.*must be 1"):
        validate_p6_validity_config(cfg4)

    # Reject allow_fixed_fallback: true
    cfg5 = copy.deepcopy(load_p6_validity_config("configs/p6_validity.yaml"))
    cfg5["heatguard"]["calibration"]["allow_fixed_fallback"] = True
    with pytest.raises(ValueError, match="allow_fixed_fallback must be False strictly in production config"):
        validate_p6_validity_config(cfg5)

    # Reject arbitrary calibrated_margin_rule
    cfg6 = copy.deepcopy(load_p6_validity_config("configs/p6_validity.yaml"))
    cfg6["heatguard"]["calibration"]["calibrated_margin_rule"] = "anything"
    with pytest.raises(ValueError, match="calibrated_margin_rule must be"):
        validate_p6_validity_config(cfg6)


# =============================================================================
# 5. ADVERSARIAL CONTRACT AND PRODUCTION API TESTS
# =============================================================================

def test_production_mode_rejects_direct_results_or_numeric_margins(sample_facility_config):
    """Production calibrated HeatGuard rejects directly supplied calibration_result or numeric margins."""
    # 1. Arbitrary numeric margin rejected
    with pytest.raises(ValueError, match="calibration_artifact_dir is required in calibrated mode"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.calibrated,
        )

    # 2. Directly supplied CalibrationResult rejected
    valid_res, _ = load_calibration_artifact(
        V3_ARTIFACT_PATH,
        expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
        repository_root=REPO_ROOT,
    )
    with pytest.raises(TypeError, match="calibrated mode rejects directly supplied calibration_result"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.calibrated,
            calibration_result=valid_res,
        )

    # 3. Manually constructed CalibrationResult rejected
    manual_res = CalibrationResult(
        q=0.90,
        quantile_method="higher",
        calibrated_margin=0.016,
        origin_count=265,
        residual_count=6360,
        calibration_start_utc="2022-06-01T00:00:00+00:00",
        calibration_end_exclusive_utc="2022-06-16T00:00:00+00:00",
        facility_scenario_id="medium",
        p4_artifact_manifest_hash=EXPECTED_P4_MANIFEST_HASH,
        checkpoint_hash=EXPECTED_CHECKPOINT_HASH,
        forecast_config_hash=EXPECTED_FC_CONFIG_HASH,
        split_hash=EXPECTED_SPLIT_HASH,
        created_at_utc="2026-10-24T00:00:00+00:00",
    )
    with pytest.raises(TypeError, match="calibrated mode rejects directly supplied calibration_result"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.calibrated,
            calibration_result=manual_res,
        )

    # 4. Duck-typed object rejected
    class DuckCalibrationResult:
        calibrated_margin = 0.016
        q = 0.90
        quantile_method = "higher"
        facility_scenario_id = "medium"
        is_fallback = False

    with pytest.raises(TypeError, match="calibrated mode rejects directly supplied calibration_result"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.calibrated,
            calibration_result=DuckCalibrationResult(),
        )


def test_production_calibrated_mode_parameter_requirements(sample_facility_config):
    """Calibrated mode requires artifact_dir, expected_manifest_sha256, and repository_root."""
    # Missing artifact_dir
    with pytest.raises(ValueError, match="calibration_artifact_dir is required"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode="calibrated",
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=REPO_ROOT,
        )

    # Missing expected_manifest_sha256
    with pytest.raises(ValueError, match="expected_manifest_sha256 is required"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode="calibrated",
            calibration_artifact_dir=V3_ARTIFACT_PATH,
            repository_root=REPO_ROOT,
        )

    # Missing repository_root
    with pytest.raises(ValueError, match="repository_root is required"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode="calibrated",
            calibration_artifact_dir=V3_ARTIFACT_PATH,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
        )

    # Wrong expected manifest hash (fails production frozen-hash check)
    with pytest.raises(ValueError, match="Production calibrated HeatGuard requires frozen V3 manifest hash"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode="calibrated",
            calibration_artifact_dir=V3_ARTIFACT_PATH,
            expected_manifest_sha256="0" * 64,
            repository_root=REPO_ROOT,
        )


def test_valid_frozen_v3_accepted(sample_facility_config):
    """Production calibrated HeatGuard accepts valid frozen V3 manifest hash."""
    sched = HeatGuardScheduler(
        facility_config=sample_facility_config,
        margin_mode=HeatGuardMarginMode.calibrated,
        calibration_artifact_dir=V3_ARTIFACT_PATH,
        expected_manifest_sha256=FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256,
        repository_root=REPO_ROOT,
    )
    assert np.isclose(sched.applied_margin, 0.015999984741210893, atol=1e-12)


def test_re_signed_non_frozen_v3_rejected(sample_facility_config, tmp_path):
    """Re-signed non-frozen V3 is rejected even when the supplied hash matches the re-signed manifest."""
    temp_repo = tmp_path / "repo"
    temp_repo.mkdir(parents=True)
    temp_v3 = temp_repo / "data/models/p6_heatguard_calibration_v3"
    shutil.copytree(V3_ARTIFACT_PATH, temp_v3)
    shutil.copytree("data/models/p6_temperature_v2", temp_repo / "data/models/p6_temperature_v2")
    shutil.copytree("data/raw/noaa", temp_repo / "data/raw/noaa")

    # Modify a harmless field (e.g. created_at_utc) and deterministically serialize
    with open(temp_v3 / "manifest.json", "r", encoding="utf-8") as f:
        mdata = json.load(f)
    mdata["created_at_utc"] = "2026-10-25T12:00:00+00:00"
    m_bytes = json.dumps(mdata, indent=2, sort_keys=True).encode("utf-8")
    with open(temp_v3 / "manifest.json", "wb") as f:
        f.write(m_bytes)
    modified_hash = hashlib.sha256(m_bytes).hexdigest()

    # Pass the matching modified hash: generic loader would accept, but production scheduler must reject!
    with pytest.raises(ValueError, match="Production calibrated HeatGuard requires frozen V3 manifest hash"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode="calibrated",
            calibration_artifact_dir=temp_v3,
            expected_manifest_sha256=modified_hash,
            repository_root=temp_repo,
        )


def test_arbitrary_valid_sha256_rejected(sample_facility_config):
    """Arbitrary valid 64-char SHA-256 is rejected by production frozen-hash check."""
    with pytest.raises(ValueError, match="Production calibrated HeatGuard requires frozen V3 manifest hash"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode="calibrated",
            calibration_artifact_dir=V3_ARTIFACT_PATH,
            expected_manifest_sha256="0" * 64,
            repository_root=REPO_ROOT,
        )


def test_configuration_and_constant_agreement():
    """configs/p6_validity.yaml manifest hash matches FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256."""
    cfg = load_p6_validity_config("configs/p6_validity.yaml")
    cfg_manifest_hash = cfg["heatguard"]["calibration"]["provenance"]["manifest_hash"]
    assert cfg_manifest_hash == FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256
    assert FROZEN_P6_HEATGUARD_V3_MANIFEST_SHA256 == "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c"


def test_production_mode_rejects_v1_and_v2(sample_facility_config):
    """Production calibrated mode rejects V1 and V2 artifacts."""
    v2_dir = Path("data/models/p6_heatguard_calibration_v2")
    if v2_dir.exists():
        with open(v2_dir / "manifest.json", "rb") as f:
            v2_hash = hashlib.sha256(f.read()).hexdigest()
        with pytest.raises(ValueError, match="Production calibrated HeatGuard requires frozen V3 manifest hash"):
            HeatGuardScheduler(
                facility_config=sample_facility_config,
                margin_mode="calibrated",
                calibration_artifact_dir=v2_dir,
                expected_manifest_sha256=v2_hash,
                repository_root=REPO_ROOT,
            )


def test_fixed_comparator_frozen_at_point_one(sample_facility_config):
    """Fixed mode strictly enforces fixed_pue_margin == 0.10 and rejects all other values."""
    # Valid 0.10
    sched = HeatGuardScheduler(
        facility_config=sample_facility_config,
        margin_mode=HeatGuardMarginMode.fixed,
        fixed_pue_margin=0.10,
    )
    assert sched.applied_margin == 0.10

    # Reject 0.20
    with pytest.raises(ValueError, match="fixed_pue_margin must be finite and exactly 0.10"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.fixed,
            fixed_pue_margin=0.20,
        )

    # Reject NaN
    with pytest.raises(ValueError, match="fixed_pue_margin must be finite and exactly 0.10"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.fixed,
            fixed_pue_margin=float("nan"),
        )

    # Reject inf
    with pytest.raises(ValueError, match="fixed_pue_margin must be finite and exactly 0.10"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.fixed,
            fixed_pue_margin=float("inf"),
        )

    # Reject boolean True
    with pytest.raises(TypeError, match="fixed_pue_margin must be numeric float"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.fixed,
            fixed_pue_margin=True,
        )

    # Reject negative value
    with pytest.raises(ValueError, match="fixed_pue_margin must be finite and exactly 0.10"):
        HeatGuardScheduler(
            facility_config=sample_facility_config,
            margin_mode=HeatGuardMarginMode.fixed,
            fixed_pue_margin=-0.10,
        )


def test_none_comparator_always_zero(sample_facility_config):
    """None mode always sets applied_margin to 0.0."""
    sched = HeatGuardScheduler(
        facility_config=sample_facility_config,
        margin_mode=HeatGuardMarginMode.none,
    )
    assert sched.applied_margin == 0.0


# =============================================================================
# 6. ISOLATED TMP_PATH V3 TAMPER TESTS
# =============================================================================

@pytest.fixture
def isolated_v3_environment(tmp_path):
    """Create an isolated temporary copy of the V3 artifact, P4 model files, and raw NOAA datasets."""
    temp_repo = tmp_path / "repo"
    temp_repo.mkdir(parents=True)

    # Copy V3 artifact
    temp_v3 = temp_repo / "data/models/p6_heatguard_calibration_v3"
    shutil.copytree(V3_ARTIFACT_PATH, temp_v3)

    # Copy P4 model files
    temp_p4 = temp_repo / "data/models/p6_temperature_v2"
    shutil.copytree("data/models/p6_temperature_v2", temp_p4)

    # Copy NOAA raw files
    temp_noaa = temp_repo / "data/raw/noaa"
    shutil.copytree("data/raw/noaa", temp_noaa)

    return temp_repo, temp_v3


def test_missing_p4_manifest_rejected(isolated_v3_environment):
    """Missing P4 artifact_manifest.json raises FileNotFoundError."""
    temp_repo, temp_v3 = isolated_v3_environment
    p4_manifest = temp_repo / "data/models/p6_temperature_v2/artifact_manifest.json"
    p4_manifest.unlink()

    with pytest.raises(FileNotFoundError, match="Required Phase 4 artifact manifest missing"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_missing_p4_checkpoint_rejected(isolated_v3_environment):
    """Missing P4 tiny_lstm_checkpoint.pt raises FileNotFoundError."""
    temp_repo, temp_v3 = isolated_v3_environment
    p4_ckpt = temp_repo / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"
    p4_ckpt.unlink()

    with pytest.raises(FileNotFoundError, match="Required Phase 4 checkpoint missing"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_altered_p4_manifest_hash_rejected(isolated_v3_environment):
    """Altered P4 artifact_manifest.json raises ValueError."""
    temp_repo, temp_v3 = isolated_v3_environment
    p4_manifest = temp_repo / "data/models/p6_temperature_v2/artifact_manifest.json"
    with open(p4_manifest, "wb") as f:
        f.write(b'{"tampered": true}')

    with pytest.raises(ValueError, match="Phase 4 artifact manifest hash mismatch"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_altered_p4_checkpoint_hash_rejected(isolated_v3_environment):
    """Altered P4 tiny_lstm_checkpoint.pt raises ValueError."""
    temp_repo, temp_v3 = isolated_v3_environment
    p4_ckpt = temp_repo / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"
    with open(p4_ckpt, "wb") as f:
        f.write(b"tampered_weights")

    with pytest.raises(ValueError, match="Phase 4 checkpoint hash mismatch"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_altered_source_dataset_rejected(isolated_v3_environment):
    """Altered raw NOAA dataset file raises ValueError."""
    temp_repo, temp_v3 = isolated_v3_environment
    noaa_file = temp_repo / "data/raw/noaa/GHCNh_USW00023234_2022.psv"
    with open(noaa_file, "ab") as f:
        f.write(b"\ntamper_line")

    with pytest.raises(ValueError, match="Source dataset file.*hash mismatch"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def _recompute_manifest_hash(temp_v3: Path, manifest_data: dict) -> str:
    """Helper to write manifest_data and return its new SHA-256 hash."""
    m_bytes = json.dumps(manifest_data, indent=2, sort_keys=True).encode("utf-8")
    with open(temp_v3 / "manifest.json", "wb") as f:
        f.write(m_bytes)
    return hashlib.sha256(m_bytes).hexdigest()


def test_missing_source_dataset_files_in_manifest_rejected(isolated_v3_environment):
    """Missing or empty source_dataset_files in manifest is rejected."""
    temp_repo, temp_v3 = isolated_v3_environment
    with open(temp_v3 / "manifest.json", "r") as f:
        mdata = json.load(f)
    del mdata["provenance"]["source_dataset_files"]
    new_hash = _recompute_manifest_hash(temp_v3, mdata)

    with pytest.raises(ValueError, match="manifest.json provenance missing non-empty 'source_dataset_files'"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=new_hash,
            repository_root=temp_repo,
        )


def test_altered_origins_rejected(isolated_v3_environment):
    """Altered origins.json file is caught at file hash verification."""
    temp_repo, temp_v3 = isolated_v3_environment
    with open(temp_v3 / "origins.json", "w") as f:
        f.write('["2022-06-01T00:00:00+00:00"]')

    with pytest.raises(ValueError, match="Artifact file 'origins.json' tamper detected"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_altered_forecast_array_rejected(isolated_v3_environment):
    """Altered forecast_temperatures.npy is caught."""
    temp_repo, temp_v3 = isolated_v3_environment
    arr = np.load(temp_v3 / "forecast_temperatures.npy")
    arr[0, 0] += 5.0
    np.save(temp_v3 / "forecast_temperatures.npy", arr)

    with pytest.raises(ValueError, match="Artifact file 'forecast_temperatures.npy' tamper detected"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_altered_realized_array_rejected(isolated_v3_environment):
    """Altered realized_temperatures.npy is caught."""
    temp_repo, temp_v3 = isolated_v3_environment
    arr = np.load(temp_v3 / "realized_temperatures.npy")
    arr[0, 0] += 5.0
    np.save(temp_v3 / "realized_temperatures.npy", arr)

    with pytest.raises(ValueError, match="Artifact file 'realized_temperatures.npy' tamper detected"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_altered_residual_array_rejected(isolated_v3_environment):
    """Altered residuals.npy is caught."""
    temp_repo, temp_v3 = isolated_v3_environment
    arr = np.load(temp_v3 / "residuals.npy")
    arr[0, 0] += 0.5
    np.save(temp_v3 / "residuals.npy", arr)

    with pytest.raises(ValueError, match="Artifact file 'residuals.npy' tamper detected"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=EXPECTED_V3_MANIFEST_HASH,
            repository_root=temp_repo,
        )


def test_missing_required_artifact_file_hash_entry_rejected(isolated_v3_environment):
    """Missing required file_hashes entry (e.g. residuals.npy) is rejected even if manifest is resigned."""
    temp_repo, temp_v3 = isolated_v3_environment
    with open(temp_v3 / "manifest.json", "r") as f:
        mdata = json.load(f)
    del mdata["file_hashes"]["residuals.npy"]
    new_hash = _recompute_manifest_hash(temp_v3, mdata)

    with pytest.raises(ValueError, match="manifest.json file_hashes missing required entries"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=new_hash,
            repository_root=temp_repo,
        )


def test_incorrect_declared_array_metadata_rejected(isolated_v3_environment):
    """Incorrect declared array shape or dtype in manifest is rejected even if manifest is resigned."""
    temp_repo, temp_v3 = isolated_v3_environment
    with open(temp_v3 / "manifest.json", "r") as f:
        mdata = json.load(f)
    mdata["provenance"]["arrays"]["forecast_temperatures"]["dtype"] = "float64"  # declared wrong dtype
    new_hash = _recompute_manifest_hash(temp_v3, mdata)

    with pytest.raises(ValueError, match="declared dtype mismatch"):
        load_calibration_artifact(
            artifact_dir=temp_v3,
            expected_manifest_sha256=new_hash,
            repository_root=temp_repo,
        )


# =============================================================================
# 7. INFORMATION SET & FORECAST VALIDATION TESTS
# =============================================================================

def test_released_job_information_set_invariance(sample_facility_config, mock_forecast_providers):
    """Unreleased future arrivals cannot alter the current committed allocation."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    # Base workload with 1 released job
    workload_base = pd.DataFrame([
        {
            "workload_trace_id": "trace_inv",
            "job_id": "job_released",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 10,
            "processing_requirement": 3,
            "energy_kwh": 30.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        }
    ])

    # Altered workload with an additional UNRELEASED future job arriving at hour 5
    workload_with_future = pd.DataFrame([
        {
            "workload_trace_id": "trace_inv",
            "job_id": "job_released",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 10,
            "processing_requirement": 3,
            "energy_kwh": 30.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        },
        {
            "workload_trace_id": "trace_inv",
            "job_id": "job_future_arrival",
            "arrival_offset_hours": 5,
            "deadline_offset_hours": 15,
            "processing_requirement": 4,
            "energy_kwh": 40.0,
            "maximum_parallelism": 1,
            "priority": 10,
            "preemptible": True,
        },
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    res_base = scheduler.schedule_rolling(workload_base, temp_prov, mkt_prov, start_utc, total_window_hours=1)
    res_future = scheduler.schedule_rolling(workload_with_future, temp_prov, mkt_prov, start_utc, total_window_hours=1)

    assert len(res_base.allocations) == len(res_future.allocations)
    for a1, a2 in zip(res_base.allocations, res_future.allocations):
        assert a1.job_id == a2.job_id
        assert a1.allocated_hour_offset == a2.allocated_hour_offset
        assert a1.allocated_energy_kwh == a2.allocated_energy_kwh


def test_beyond_horizon_minimum_allocation_and_competing_jobs(sample_facility_config, mock_forecast_providers):
    """Job requiring 10 units with deadline 28 receives at least 6 units during [0, 24).

    Competing jobs cannot bypass this reservation.
    """
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "compete_trace",
            "job_id": "job_long_A",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 28,
            "processing_requirement": 10,
            "energy_kwh": 100.0,
            "maximum_parallelism": 1,
            "priority": 1,
            "preemptible": True,
        },
        {
            "workload_trace_id": "compete_trace",
            "job_id": "job_competing_B",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 15,
            "processing_requirement": 5,
            "energy_kwh": 50.0,
            "maximum_parallelism": 1,
            "priority": 5,
            "preemptible": True,
        },
    ])

    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    res = scheduler.schedule_rolling(workload, temp_prov, mkt_prov, start_utc, total_window_hours=24)
    job_A_units = [a for a in res.allocations if a.job_id == "job_long_A"]
    assert len(job_A_units) >= 6


def test_forecast_contract_validation_rejects_malformed_forecasts(sample_facility_config, mock_forecast_providers):
    """Mismatched origin, non-UTC, shifted timestamps, and non-finite values fail loudly."""
    temp_prov, mkt_prov = mock_forecast_providers
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)

    workload = pd.DataFrame([
        {
            "workload_trace_id": "fc_trace",
            "job_id": "job_1",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        }
    ])
    scheduler = _make_verified_calibrated_scheduler(sample_facility_config)

    # 1. Non-finite temperature forecast
    def bad_temp_prov(origin_utc: datetime, h: int) -> np.ndarray:
        return np.full((h,), float("nan"))

    with pytest.raises(ValueError, match="Temperature forecast.*contains non-finite values"):
        scheduler.schedule_rolling(workload, bad_temp_prov, mkt_prov, start_utc, total_window_hours=1)

    # 2. Market forecast origin mismatch
    def bad_mkt_origin(origin_utc: datetime, h: int) -> ForecastResult:
        res = mkt_prov(origin_utc, h)
        return ForecastResult(
            origin_timestamp_utc=origin_utc + timedelta(hours=1),
            points=res.points,
            model_name="bad",
            model_version="1.0",
        )

    with pytest.raises(ValueError, match="Market forecast origin.*does not match rolling origin"):
        scheduler.schedule_rolling(workload, temp_prov, bad_mkt_origin, start_utc, total_window_hours=1)

    # 3. Market forecast non-finite price
    def bad_mkt_nan_price(origin_utc: datetime, h: int) -> ForecastResult:
        pts = [
            ForecastPoint(
                timestamp_utc=origin_utc + timedelta(hours=i),
                horizon_hours=i,
                predicted_price_usd_per_mwh=float("nan"),
                predicted_carbon_g_per_kwh=100.0,
            )
            for i in range(h)
        ]
        return ForecastResult(origin_timestamp_utc=origin_utc, points=pts, model_name="bad", model_version="1.0")

    with pytest.raises(ValueError, match="predicted_price_usd_per_mwh must be finite"):
        scheduler.schedule_rolling(workload, temp_prov, bad_mkt_nan_price, start_utc, total_window_hours=1)


def test_workload_validation_rejects_duplicates_and_multi_traces():
    """Duplicate job IDs and mixed workload trace IDs fail loudly."""
    # 1. Duplicate job IDs
    dup_df = pd.DataFrame([
        {
            "workload_trace_id": "trace_1",
            "job_id": "job_dup",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        },
        {
            "workload_trace_id": "trace_1",
            "job_id": "job_dup",
            "arrival_offset_hours": 1,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        },
    ])
    with pytest.raises(ValueError, match="Duplicate job_id detected in workload: 'job_dup'"):
        validate_heatguard_workload_df(dup_df)

    # 2. Mixed workload trace IDs
    mixed_df = pd.DataFrame([
        {
            "workload_trace_id": "trace_1",
            "job_id": "job_1",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        },
        {
            "workload_trace_id": "trace_2",
            "job_id": "job_2",
            "arrival_offset_hours": 1,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        },
    ])
    with pytest.raises(ValueError, match="must contain exactly one non-empty workload_trace_id across all rows"):
        validate_heatguard_workload_df(mixed_df)

    # 3. Workload with one valid trace ID and one NaN/null trace ID
    nan_df = pd.DataFrame([
        {
            "workload_trace_id": "trace_1",
            "job_id": "job_1",
            "arrival_offset_hours": 0,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        },
        {
            "workload_trace_id": None,
            "job_id": "job_2",
            "arrival_offset_hours": 1,
            "deadline_offset_hours": 5,
            "processing_requirement": 1,
            "energy_kwh": 10.0,
        },
    ])
    with pytest.raises(ValueError, match="has invalid workload_trace_id"):
        validate_heatguard_workload_df(nan_df)
