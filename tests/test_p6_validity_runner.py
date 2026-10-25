import copy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from heattrace.experiments.p6_validity_runner import (
    DEV_TRIPLET_ID,
    FROZEN_CALIBRATION_MANIFEST_HASH,
    FROZEN_P4_CHECKPOINT_HASH,
    FROZEN_P4_MANIFEST_HASH,
    PilotCellSpec,
    build_workload_cache,
    compute_canonical_df_sha256,
    copy_forecast_metrics_deliverable,
    enumerate_p6_pilot_matrix,
    execute_development_pilot,
    execute_p6_pilot_cell,
    load_development_benchmark_filtered,
    run_deployable_rolling_schedule,
    verify_and_validate_configs,
    verify_frozen_hashes,
)
from heattrace.policy.interfaces import ForecastPoint, ForecastResult, SchedulingConstraints
from heattrace.thermal.facility import FacilityConfig, get_preset_thermal_scenario
from heattrace.thermal.heatguard import HeatGuardScheduler
from heattrace.workload.generator import generate_deterministic_workload

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_enumeration_exact_252_and_cohort_counts():
    """Prove exactly 252 unique essential cells across four cohorts."""
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    assert len(specs) == 252

    cohort_counts = {}
    for s in specs:
        cohort_counts[s.cohort] = cohort_counts.get(s.cohort, 0) + 1

    assert cohort_counts["core_benchmark"] == 144
    assert cohort_counts["event_blind_benchmark"] == 72
    assert cohort_counts["algorithm_comparators"] == 24
    assert cohort_counts["oracle_reference"] == 12


def test_stable_run_ids_under_shuffled_enumeration():
    """Prove run IDs are deterministic and independent of enumeration order."""
    specs1 = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    import random
    rng = random.Random(42)
    shuffled_specs = list(specs1)
    rng.shuffle(shuffled_specs)

    dict1 = {s.canonical_key: s.run_id for s in specs1}
    dict2 = {s.canonical_key: s.run_id for s in shuffled_specs}
    assert dict1 == dict2


def test_no_duplicate_run_ids():
    """Prove all 252 run IDs are distinct."""
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    run_ids = [s.run_id for s in specs]
    assert len(run_ids) == len(set(run_ids)) == 252


def test_development_only_selection():
    """Prove runner strictly accepts TRIPLET_DEV_ae821c and rejects others."""
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    for s in specs:
        assert s.triplet_id == DEV_TRIPLET_ID

    for conf_id in ["TRIPLET_CONF_1_f5c700", "TRIPLET_CONF_2_2a6e22", "TRIPLET_CONF_3_628624"]:
        with pytest.raises(ValueError, match="is not the authorized development triplet"):
            enumerate_p6_pilot_matrix(conf_id)


def test_frozen_hashes_verification():
    """Verify frozen hashes pass on valid files and fail loudly on tampering."""
    res = verify_frozen_hashes(REPO_ROOT)
    assert res["p4_manifest_sha256"] == FROZEN_P4_MANIFEST_HASH
    assert res["p4_checkpoint_sha256"] == FROZEN_P4_CHECKPOINT_HASH
    assert res["calibration_manifest_sha256"] == FROZEN_CALIBRATION_MANIFEST_HASH

    with pytest.raises(ValueError, match="P4 manifest hash mismatch"):
        verify_frozen_hashes(REPO_ROOT, expected_p4_manifest="0" * 64)

    with pytest.raises(ValueError, match="P4 checkpoint hash mismatch"):
        verify_frozen_hashes(REPO_ROOT, expected_p4_checkpoint="0" * 64)

    with pytest.raises(ValueError, match="HeatGuard calibration manifest mismatch"):
        verify_frozen_hashes(REPO_ROOT, expected_calibration_manifest="0" * 64)


def test_config_validation_and_hashing():
    """Verify configs/p6_validity.yaml is loaded, validated, and hashed."""
    cfg, val_hash, th_hash = verify_and_validate_configs(
        repo_root=REPO_ROOT,
        p6_validity_yaml_path=REPO_ROOT / "configs/p6_validity.yaml",
        p6_thermal_yaml_path=REPO_ROOT / "configs/p6_thermal.yaml",
    )
    assert len(val_hash) == 64
    assert len(th_hash) == 64
    assert cfg["design_mode"] == "fallback"


def test_read_time_confirmation_boundary(tmp_path):
    """Prove read-time parquet pushdown filtering prevents confirmatory row leakage."""
    dev_df = load_development_benchmark_filtered(REPO_ROOT / "data/benchmarks/p6_event_control_pairs.parquet")
    assert len(dev_df) == 360
    assert dev_df["triplet_id"].unique().tolist() == [DEV_TRIPLET_ID]
    assert set(dev_df["window_type"].unique()) == {"heatwave", "control", "event_blind"}


def test_end_to_end_confirmatory_mutation_invariance(tmp_path):
    """Adversarial probe: drastic mutation of synthetic confirmatory rows leaves development outputs identical.

    To preserve the confirmatory seal, this test NEVER loads real confirmatory rows.
    It reads real development benchmark rows using load_development_benchmark_filtered,
    fabricates synthetic confirmatory rows conforming to the benchmark schema,
    writes clean and mutated parquet files, and proves that downstream forecast
    generation and rolling schedule executions are identical.
    """
    pairs_path = REPO_ROOT / "data/benchmarks/p6_event_control_pairs.parquet"
    real_dev_pairs = load_development_benchmark_filtered(pairs_path)

    # Fabricate synthetic confirmatory rows with identical schema
    synthetic_conf_clean = real_dev_pairs.copy().iloc[:72].copy()
    synthetic_conf_clean["triplet_id"] = "TRIPLET_CONF_SYNTHETIC"
    synthetic_conf_clean["window_type"] = "heatwave"
    synthetic_conf_clean["window_id"] = "HW_CONF_SYNTHETIC"
    synthetic_conf_clean["phase_label"] = "synthetic_confirmatory"

    # Synthetic mutated: drastically alter all weather and market outcome signals
    synthetic_conf_mutated = synthetic_conf_clean.copy()
    synthetic_conf_mutated["temperature_c"] = 999.0
    synthetic_conf_mutated["price_usd_per_mwh"] = -9999.0
    synthetic_conf_mutated["carbon_g_per_kwh"] = 8888.0
    synthetic_conf_mutated["demand_mw"] = 0.0

    # Build clean and mutated composite datasets (development + synthetic confirmatory)
    df_clean_composite = pd.concat([real_dev_pairs, synthetic_conf_clean], ignore_index=True)
    df_mutated_composite = pd.concat([real_dev_pairs, synthetic_conf_mutated], ignore_index=True)

    p1 = tmp_path / "pairs_synthetic_clean.parquet"
    p2 = tmp_path / "pairs_synthetic_mutated.parquet"
    df_clean_composite.to_parquet(p1, index=False)
    df_mutated_composite.to_parquet(p2, index=False)

    # Load both via production development-only loader
    loaded_dev1 = load_development_benchmark_filtered(p1)
    loaded_dev2 = load_development_benchmark_filtered(p2)

    # 1. Prove identical DataFrame content and digests
    assert compute_canonical_df_sha256(loaded_dev1) == compute_canonical_df_sha256(loaded_dev2)
    pd.testing.assert_frame_equal(loaded_dev1, loaded_dev2)

    # 2. Prove downstream forecast precomputation and rolling execution invariance
    from heattrace.experiments.p6_validity_runner import (
        precompute_development_forecasts,
        execute_p6_pilot_cell,
        build_workload_cache,
    )
    fc_cache1 = precompute_development_forecasts(REPO_ROOT, loaded_dev1)
    fc_cache2 = precompute_development_forecasts(REPO_ROOT, loaded_dev2)

    # Compare forecasts for heatwave window
    temp_fc1, mkt_fc1 = fc_cache1["heatwave"]
    temp_fc2, mkt_fc2 = fc_cache2["heatwave"]
    assert len(temp_fc1) == len(temp_fc2)
    for arr1, arr2 in zip(temp_fc1, temp_fc2):
        np.testing.assert_array_equal(arr1, arr2)

    # Execute a core policy cell on both
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    core_spec = [s for s in specs if s.policy_id == "full_thermal_aware" and s.context == "heatwave"][0]
    heatguard_spec = [s for s in specs if s.policy_id == "heatguard_calibrated" and s.context == "heatwave"][0]

    workload_cache, _ = build_workload_cache(REPO_ROOT)
    w_df = workload_cache[(core_spec.seed, core_spec.workload_multiplier)]
    realized_w1 = loaded_dev1[loaded_dev1["window_type"] == "heatwave"].sort_values("timestamp_utc").reset_index(drop=True)
    realized_w2 = loaded_dev2[loaded_dev2["window_type"] == "heatwave"].sort_values("timestamp_utc").reset_index(drop=True)

    sc = get_preset_thermal_scenario("medium", config_path=REPO_ROOT / "configs/p6_thermal.yaml")
    fcfg = FacilityConfig(nominal_compute_capacity_kw=500.0, thermal_scenario=sc, model_kind="power_capped")
    dummy_prov = {
        "p6_config_sha256": "0" * 64,
        "p6_thermal_config_sha256": "0" * 64,
        "development_benchmark_sha256": "0" * 64,
        f"workload_sha256_{core_spec.seed}_{core_spec.workload_multiplier}": "0" * 64,
        "forecast_metrics_source_sha256": "0" * 64,
        "p4_manifest_sha256": FROZEN_P4_MANIFEST_HASH,
        "p4_checkpoint_sha256": FROZEN_P4_CHECKPOINT_HASH,
        "calibration_manifest_sha256": FROZEN_CALIBRATION_MANIFEST_HASH,
    }

    # Core policy
    res1 = execute_p6_pilot_cell(
        spec=core_spec,
        realized_window_df=realized_w1,
        workload_df=w_df,
        temp_forecasts=temp_fc1,
        mkt_forecasts=mkt_fc1,
        fcfg=fcfg,
        provenance_hashes=dummy_prov,
        repo_root=REPO_ROOT,
    )
    res2 = execute_p6_pilot_cell(
        spec=core_spec,
        realized_window_df=realized_w2,
        workload_df=w_df,
        temp_forecasts=temp_fc2,
        mkt_forecasts=mkt_fc2,
        fcfg=fcfg,
        provenance_hashes=dummy_prov,
        repo_root=REPO_ROOT,
    )
    assert res1["cooling_adjusted_cost_usd"] == res2["cooling_adjusted_cost_usd"]
    assert res1["cooling_adjusted_carbon_kg"] == res2["cooling_adjusted_carbon_kg"]
    assert res1["completed_processing_slots"] == res2["completed_processing_slots"]
    assert res1["status"] == "SUCCESS"
    assert res2["status"] == "SUCCESS"

    # HeatGuard policy
    hg_res1 = execute_p6_pilot_cell(
        spec=heatguard_spec,
        realized_window_df=realized_w1,
        workload_df=w_df,
        temp_forecasts=temp_fc1,
        mkt_forecasts=mkt_fc1,
        fcfg=fcfg,
        provenance_hashes=dummy_prov,
        repo_root=REPO_ROOT,
    )
    hg_res2 = execute_p6_pilot_cell(
        spec=heatguard_spec,
        realized_window_df=realized_w2,
        workload_df=w_df,
        temp_forecasts=temp_fc2,
        mkt_forecasts=mkt_fc2,
        fcfg=fcfg,
        provenance_hashes=dummy_prov,
        repo_root=REPO_ROOT,
    )
    assert hg_res1["cooling_adjusted_cost_usd"] == hg_res2["cooling_adjusted_cost_usd"]
    assert hg_res1["cooling_adjusted_carbon_kg"] == hg_res2["cooling_adjusted_carbon_kg"]
    assert hg_res1["applied_margin"] == hg_res2["applied_margin"]
    assert hg_res1["status"] == "SUCCESS"
    assert hg_res2["status"] == "SUCCESS"


def test_causal_rolling_equivalence_full_thermal_aware_and_heatguard_none():
    """Prove that rolling full_thermal_aware comparator is semantically equivalent to HeatGuard none."""
    sc = get_preset_thermal_scenario("medium", config_path=REPO_ROOT / "configs/p6_thermal.yaml")
    fcfg = FacilityConfig(nominal_compute_capacity_kw=500.0, thermal_scenario=sc, model_kind="power_capped")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16, allow_preemption=True)

    start_utc = datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc)
    def temp_prov(orig, h): return np.full((h,), 25.0)
    def mkt_prov(orig, h):
        pts = [ForecastPoint(timestamp_utc=orig + timedelta(hours=i), horizon_hours=i, predicted_price_usd_per_mwh=50.0 + i, predicted_carbon_g_per_kwh=200.0 + 2*i) for i in range(h)]
        return ForecastResult(origin_timestamp_utc=orig, points=pts, model_name="m", model_version="1.0")

    w0 = generate_deterministic_workload(workload_trace_id="trace_standard_120h_v0", random_seed=20261016, job_count=30)

    # 1. HeatGuard none
    sched_none = HeatGuardScheduler(facility_config=fcfg, margin_mode="none", objective="carbon_first", repository_root=REPO_ROOT)
    res_hg_none = sched_none.schedule_rolling(w0, temp_prov, mkt_prov, start_utc, total_window_hours=120)

    # 2. Deployable rolling full_thermal_aware
    temp_fc_dict = {h: temp_prov(start_utc + timedelta(hours=h), 24) for h in range(120)}
    mkt_fc_dict = {h: mkt_prov(start_utc + timedelta(hours=h), 24) for h in range(120)}
    res_fta, _ = run_deployable_rolling_schedule(
        policy_id="full_thermal_aware",
        workload_df=w0,
        temp_forecasts=temp_fc_dict,
        mkt_forecasts=mkt_fc_dict,
        fcfg=fcfg,
        objective="carbon_first",
        start_utc=start_utc,
        constraints=constraints,
    )

    allocs_hg = [(a.job_id, a.allocated_hour_offset, round(a.execution_power_kw, 4)) for a in res_hg_none.allocations]
    allocs_fta = [(a.job_id, a.allocated_hour_offset, round(a.execution_power_kw, 4)) for a in res_fta.allocations]

    assert allocs_hg == allocs_fta
    assert res_hg_none.is_feasible == res_fta.is_feasible


def test_causal_rolling_adversarial_future_mutation_invariance():
    """Adversarial probe: mutating realized market/weather values after origin t cannot change commitments at <= t."""
    sc = get_preset_thermal_scenario("medium", config_path=REPO_ROOT / "configs/p6_thermal.yaml")
    fcfg = FacilityConfig(nominal_compute_capacity_kw=500.0, thermal_scenario=sc, model_kind="power_capped")
    constraints = SchedulingConstraints(max_cluster_power_kw=500.0, max_concurrent_jobs=16, allow_preemption=True)
    start_utc = datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc)

    # Base forecasts
    temp_fc_dict = {h: np.full((24,), 25.0) for h in range(120)}
    mkt_fc_dict = {
        h: ForecastResult(
            origin_timestamp_utc=start_utc + timedelta(hours=h),
            points=[ForecastPoint(timestamp_utc=start_utc + timedelta(hours=h+i), horizon_hours=i, predicted_price_usd_per_mwh=50.0, predicted_carbon_g_per_kwh=200.0) for i in range(24)],
            model_name="m",
            model_version="1.0",
        )
        for h in range(120)
    }

    w0 = generate_deterministic_workload(workload_trace_id="trace_standard_120h_v0", random_seed=20261016, job_count=30)
    res_base, _ = run_deployable_rolling_schedule("full_thermal_aware", w0, temp_fc_dict, mkt_fc_dict, fcfg, "carbon_first", start_utc, constraints)

    # Mutate forecasts strictly after hour 50
    temp_fc_mut = {h: np.full((24,), 25.0) if h <= 50 else np.full((24,), 45.0) for h in range(120)}
    mkt_fc_mut = {}
    for h in range(120):
        if h <= 50:
            mkt_fc_mut[h] = mkt_fc_dict[h]
        else:
            pts_mut = [
                ForecastPoint(
                    timestamp_utc=pt.timestamp_utc,
                    horizon_hours=pt.horizon_hours,
                    predicted_price_usd_per_mwh=9999.0,
                    predicted_carbon_g_per_kwh=8888.0,
                )
                for pt in mkt_fc_dict[h].points
            ]
            mkt_fc_mut[h] = ForecastResult(
                origin_timestamp_utc=mkt_fc_dict[h].origin_timestamp_utc,
                points=pts_mut,
                model_name="m_mut",
                model_version="1.0",
            )

    res_mut, _ = run_deployable_rolling_schedule("full_thermal_aware", w0, temp_fc_mut, mkt_fc_mut, fcfg, "carbon_first", start_utc, constraints)

    # Allocations up to hour 50 must be bitwise identical
    allocs_base_50 = [a for a in res_base.allocations if a.allocated_hour_offset <= 50]
    allocs_mut_50 = [a for a in res_mut.allocations if a.allocated_hour_offset <= 50]

    assert len(allocs_base_50) == len(allocs_mut_50)
    for a1, a2 in zip(allocs_base_50, allocs_mut_50):
        assert a1.job_id == a2.job_id
        assert a1.allocated_hour_offset == a2.allocated_hour_offset
        assert np.isclose(a1.execution_power_kw, a2.execution_power_kw)


def test_maximum_parallelism_preserved_through_workloads_and_scheduling():
    """Verify maximum_parallelism is preserved in scaled workloads and HeatGuard accepts it."""
    cache, digests = build_workload_cache(REPO_ROOT)
    for (s_val, m_val), w_df in cache.items():
        assert "maximum_parallelism" in w_df.columns
        max_vals = set(w_df["maximum_parallelism"].unique())
        assert max_vals.issubset({1, 2, 4})
        # Verify deterministic hash exists
        assert (s_val, m_val) in digests
        assert len(digests[(s_val, m_val)]) == 64


def test_forecast_metrics_gate_conditions(tmp_path):
    """Verify p6_forecast_metrics.csv records cond1=True and cond2=False exactly."""
    src_csv = REPO_ROOT / "data/models/p6_temperature_v2/evaluation_metrics.csv"
    dst_csv = tmp_path / "p6_forecast_metrics.csv"

    copy_forecast_metrics_deliverable(src_csv, dst_csv)
    df = pd.read_csv(dst_csv)
    val_df = df[df["split"] == "validation"]
    lstm = val_df[val_df["model"] == "TinyTemperatureLSTM"].iloc[0]
    shpd = val_df[val_df["model"] == "same_hour_previous_day"].iloc[0]

    improvement = (shpd["rmse"] - lstm["rmse"]) / shpd["rmse"]
    assert improvement >= 0.02

    ext_imp = (shpd["extreme_underprediction_mae"] - lstm["extreme_underprediction_mae"]) / shpd["extreme_underprediction_mae"]
    assert ext_imp < 0.05  # cond2 is False


def test_resume_fails_closed_on_corruption_or_hash_mismatch(tmp_path):
    """Prove resume logic rejects stale, corrupt, duplicate, or hash-mismatched files."""
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    p_parquet = out_dir / "p6_development_pilot.parquet"

    # 1. Corrupt parquet bytes
    p_parquet.write_text("corrupted bytes")
    with pytest.raises(RuntimeError, match="Resume validation failed"):
        execute_development_pilot(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", out_dir)

    # 2. Parquet missing required columns
    bad_schema_df = pd.DataFrame([{"run_id": "test", "status": "SUCCESS"}])
    bad_schema_df.to_parquet(p_parquet, index=False)
    with pytest.raises(RuntimeError, match="Missing columns"):
        execute_development_pilot(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", out_dir)

    # 3. Parquet with duplicate run_id
    valid_pilot_df = pd.read_parquet(REPO_ROOT / "data/results/p6_development_pilot.parquet")
    dup_df = pd.concat([valid_pilot_df.iloc[:1], valid_pilot_df.iloc[:1]], ignore_index=True)
    dup_df.to_parquet(p_parquet, index=False)
    with pytest.raises(RuntimeError, match="duplicate run_id"):
        execute_development_pilot(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", out_dir)

    # 4. Parquet with unknown run_id
    unk_df = valid_pilot_df.iloc[:1].copy()
    unk_df.loc[0, "run_id"] = "p6_pilot_unknown_run_id_1234567890abcdef"
    unk_df.to_parquet(p_parquet, index=False)
    with pytest.raises(RuntimeError, match="unknown run_id"):
        execute_development_pilot(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", out_dir)


@pytest.mark.parametrize(
    "tampered_col,tampered_val,err_match",
    [
        ("facility_model", "wrong_facility_model", "facility_model"),
        ("thermal_curve", "wrong_curve", "thermal_curve"),
        ("workload_multiplier", 99.0, "workload_multiplier"),
        ("workload_multiplier", 1.000001, "workload_multiplier"),
        ("workload_multiplier", "1.0", "must be numeric"),
        ("workload_multiplier", True, "must be numeric"),
        ("workload_multiplier", float("nan"), "non-finite"),
        ("workload_multiplier", float("inf"), "non-finite"),
        ("seed", 12345678, "seed"),
        ("seed", 20261017.9, "must be an integer"),
        ("seed", "20261017", "must be an integer"),
        ("seed", True, "must be an integer"),
        ("objective", "wrong_obj", "objective"),
        ("policy_id", "wrong_policy", "policy_id"),
        ("policy_version", "99.0", "policy_version"),
        ("policy_version", 1.0, "must be a string"),
        ("deployable", False, "deployable"),
        ("deployable", 1, "must be a boolean"),
        ("deployable", 0, "must be a boolean"),
        ("deployable", "True", "must be a boolean"),
        ("deployable", "False", "must be a boolean"),
        ("deployable", None, "must be a boolean"),
        ("triplet_id", None, "must be a string"),
        ("context", 123, "must be a string"),
        ("window_id", None, "must be a string"),
        ("cohort", None, "must be a string"),
        ("facility_model", 99, "must be a string"),
        ("thermal_curve", None, "must be a string"),
        ("objective", None, "must be a string"),
        ("policy_id", None, "must be a string"),
        ("margin_mode", None, "must be a string"),
        ("margin_mode", "wrong_margin", "margin_mode"),
        ("workload_trace_id", "wrong_trace_id", "workload_trace_id"),
        ("workload_trace_id", None, "must be a string"),
        ("workload_sha256", "a" * 64, "Provenance hash mismatch"),
        ("forecast_metrics_source_sha256", "b" * 64, "Provenance hash mismatch"),
        ("p6_config_sha256", "c" * 64, "Provenance hash mismatch"),
        ("p6_thermal_config_sha256", "d" * 64, "Provenance hash mismatch"),
        ("development_benchmark_sha256", "e" * 64, "Provenance hash mismatch"),
        ("p4_manifest_sha256", "f" * 64, "Provenance hash mismatch"),
        ("p4_checkpoint_sha256", "0" * 64, "Provenance hash mismatch"),
        ("calibration_manifest_sha256", "1" * 64, "Provenance hash mismatch"),
        ("calibration_manifest_sha256", "not_a_valid_64_char_hex_hash", "Malformed or non-hex"),
        ("calibration_manifest_sha256", None, "Malformed or non-hex"),
    ],
)
def test_resume_fails_closed_adversarial_tampering(tmp_path, tampered_col, tampered_val, err_match):
    """Adversarially probe resume validation against tampering of scientific keys and provenance digests."""
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    p_parquet = out_dir / "p6_development_pilot.parquet"

    # Base valid row
    valid_pilot_df = pd.read_parquet(REPO_ROOT / "data/results/p6_development_pilot.parquet")
    table = pa.Table.from_pandas(valid_pilot_df.iloc[:5])

    # Strip pandas schema metadata so parquet scalar types are preserved directly
    table = table.replace_schema_metadata(None)

    col_idx = table.schema.get_field_index(tampered_col)
    old_arr = table.column(col_idx)

    # Build properly-typed pyarrow column to ensure parquet file is valid parquet with tampered schema/data
    if isinstance(tampered_val, bool):
        vals = [tampered_val] * len(old_arr)
        new_arr = pa.array(vals, type=pa.bool_())
    elif isinstance(tampered_val, str):
        vals = [tampered_val] * len(old_arr)
        new_arr = pa.array(vals, type=pa.string())
    elif isinstance(tampered_val, int):
        vals = [tampered_val] * len(old_arr)
        new_arr = pa.array(vals, type=pa.int64())
    elif isinstance(tampered_val, float):
        vals = [tampered_val] + [float(x) for x in old_arr.to_pylist()[1:]]
        new_arr = pa.array(vals, type=pa.float64())
    elif tampered_val is None:
        vals = [None] * len(old_arr)
        new_arr = pa.array(vals, type=pa.string())
    else:
        vals = [tampered_val] * len(old_arr)
        new_arr = pa.array(vals)

    t_mod = table.set_column(col_idx, tampered_col, new_arr)
    pq.write_table(t_mod, p_parquet)

    original_bytes = p_parquet.read_bytes()

    # Attempt resume; must raise RuntimeError matching err_match and refuse overwrite
    with pytest.raises(RuntimeError, match=err_match):
        execute_development_pilot(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", out_dir)

    # Prove rejected file was NOT overwritten or repaired silently
    assert p_parquet.read_bytes() == original_bytes


def test_resume_valid_partial_and_full_reconstruction(tmp_path, monkeypatch):
    """Prove that valid partial files resume successfully and valid full files require 0 cell reruns."""
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    p_parquet = out_dir / "p6_development_pilot.parquet"

    valid_pilot_df = pd.read_parquet(REPO_ROOT / "data/results/p6_development_pilot.parquet")

    # 1. Complete valid pilot resume: 0 cells should be re-executed
    valid_pilot_df.to_parquet(p_parquet, index=False)
    initial_hash = hashlib.sha256(p_parquet.read_bytes()).hexdigest()

    df_resumed, meta = execute_development_pilot(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", out_dir)
    assert len(df_resumed) == 252
    assert meta["successful_runs"] == 252
    assert meta["pilot_parquet_sha256"] == initial_hash

    # 2. Genuine partial resume with a subset (5 valid rows)
    partial_dir = tmp_path / "partial_results"
    partial_dir.mkdir()
    partial_parquet = partial_dir / "p6_development_pilot.parquet"

    # Write 5 valid rows to temporary partial output
    subset_df = valid_pilot_df.iloc[:5].copy()
    subset_df.to_parquet(partial_parquet, index=False)

    # Directly verify validator accepts and returns exactly those 5 rows
    from heattrace.experiments.p6_validity_runner import (
        validate_existing_pilot_parquet,
        verify_frozen_hashes,
        verify_and_validate_configs,
        load_development_benchmark_filtered,
        sha256_file,
    )
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    expected_specs = {s.run_id: s for s in specs}
    workload_cache, workload_digests = build_workload_cache(REPO_ROOT)
    v_hashes = verify_frozen_hashes(REPO_ROOT)
    _, v_hash, th_hash = verify_and_validate_configs(REPO_ROOT, REPO_ROOT / "configs/p6_validity.yaml", REPO_ROOT / "configs/p6_thermal.yaml")
    pairs_dev = load_development_benchmark_filtered(REPO_ROOT / "data/benchmarks/p6_event_control_pairs.parquet")
    dev_hash = compute_canonical_df_sha256(pairs_dev)
    fc_metrics_hash = sha256_file(REPO_ROOT / "data/models/p6_temperature_v2/evaluation_metrics.csv")
    prov_hashes = {
        "p6_config_sha256": v_hash,
        "p6_thermal_config_sha256": th_hash,
        "development_benchmark_sha256": dev_hash,
        "forecast_metrics_source_sha256": fc_metrics_hash,
        **v_hashes,
    }
    for (s_val, m_val), d_val in workload_digests.items():
        prov_hashes[f"workload_sha256_{s_val}_{m_val}"] = d_val

    validated_subset = validate_existing_pilot_parquet(
        parquet_path=partial_parquet,
        expected_specs=expected_specs,
        provenance_hashes=prov_hashes,
        workload_cache=workload_cache,
    )
    assert len(validated_subset) == 5
    assert set(validated_subset.keys()) == set(subset_df["run_id"])

    # Now verify bounded execution: monkeypatch execute_p6_pilot_cell to track missing-cell invocations
    # and return deterministic synthetic rows from valid_pilot_df to avoid 247 expensive model executions
    executed_run_ids: list[str] = []
    lookup_by_rid = {r["run_id"]: r for r in valid_pilot_df.to_dict("records")}

    def mock_execute_cell(spec, **kwargs):
        executed_run_ids.append(spec.run_id)
        return lookup_by_rid[spec.run_id]

    import heattrace.experiments.p6_validity_runner as p6_runner_module
    monkeypatch.setattr(p6_runner_module, "execute_p6_pilot_cell", mock_execute_cell)

    df_full_reconstructed, meta_partial = execute_development_pilot(
        repo_root=REPO_ROOT,
        config_path=REPO_ROOT / "configs/p6_validity.yaml",
        output_dir=partial_dir,
    )

    # Prove only missing cells (252 - 5 = 247) were called
    assert len(executed_run_ids) == 247
    assert set(executed_run_ids).isdisjoint(set(subset_df["run_id"]))

    # Completed reconstructed result must have exactly 252 rows, 252 unique expected IDs, and no duplicates
    assert len(df_full_reconstructed) == 252
    assert df_full_reconstructed["run_id"].nunique() == 252
    assert set(df_full_reconstructed["run_id"]) == set(expected_specs.keys())
    assert meta_partial["successful_runs"] == 252


def test_oracle_marked_non_deployable():
    """Prove all oracle reference cells are marked deployable=false."""
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    oracle_specs = [s for s in specs if s.policy_id == "oracle_full_thermal_aware"]
    assert len(oracle_specs) == 12
    for s in oracle_specs:
        assert s.deployable is False
        assert s.cohort == "oracle_reference"


# ==============================================================================
# Phase 7 Sealed Confirmatory Dry-Run & Sealing Probes
# ==============================================================================

def test_p7_confirmatory_matrix_exact_counts_and_subtotals():
    """Verify exactly 756 unique stable cells with correct cohort subtotals."""
    from heattrace.experiments.p6_validity_runner import (
        enumerate_p7_confirmatory_matrix,
        DEV_WINDOWS,
    )

    specs = enumerate_p7_confirmatory_matrix(REPO_ROOT / "configs/p6_validity.yaml")
    assert len(specs) == 756

    # Cohort breakdown
    cohort_a = [s for s in specs if s.cohort == "core_benchmark"]
    cohort_b = [s for s in specs if s.cohort == "event_blind_benchmark"]
    cohort_c = [s for s in specs if s.cohort == "algorithm_comparators"]
    cohort_d = [s for s in specs if s.cohort == "oracle_reference"]

    assert len(cohort_a) == 432
    assert len(cohort_b) == 216
    assert len(cohort_c) == 72
    assert len(cohort_d) == 36

    # Uniqueness
    run_ids = [s.run_id for s in specs]
    assert len(set(run_ids)) == 756

    canonical_keys = [s.canonical_key for s in specs]
    assert len(set(canonical_keys)) == 756

    # Zero development triplet or windows
    for s in specs:
        assert s.triplet_id != DEV_TRIPLET_ID
        assert DEV_TRIPLET_ID not in s.canonical_key
        assert s.window_id not in DEV_WINDOWS.values()
        assert s.objective == "carbon_first"

    # Oracle deployability
    for s in cohort_d:
        assert s.deployable is False


def test_p7_confirmatory_matrix_deterministic_and_order_invariant(tmp_path):
    """Verify confirmatory enumeration is deterministic and order invariant."""
    from heattrace.experiments.p6_validity_runner import enumerate_p7_confirmatory_matrix

    specs1 = enumerate_p7_confirmatory_matrix(REPO_ROOT / "configs/p6_validity.yaml")
    specs2 = enumerate_p7_confirmatory_matrix(REPO_ROOT / "configs/p6_validity.yaml")

    assert [s.run_id for s in specs1] == [s.run_id for s in specs2]

    # Reorder keys in config
    import yaml
    with (REPO_ROOT / "configs/p6_validity.yaml").open("r") as f:
        cfg = yaml.safe_load(f)

    # Reverse confirmatory triplets in yaml
    cfg["triplets"]["confirmatory"] = list(reversed(cfg["triplets"]["confirmatory"]))
    reordered_yaml = tmp_path / "p6_validity_reordered.yaml"
    with reordered_yaml.open("w") as f:
        yaml.dump(cfg, f)

    specs_reordered = enumerate_p7_confirmatory_matrix(reordered_yaml)
    assert [s.run_id for s in specs1] == [s.run_id for s in specs_reordered]


def test_p7_confirmatory_dry_run_sealing_probe(monkeypatch):
    """Adversarial probe proving dry-run does NOT load confirmatory parquet rows or outcome data."""
    import pandas as pd
    import pyarrow.parquet as pq
    from heattrace.experiments.p6_validity_runner import run_p7_confirmatory_dry_run

    def forbidden_read_parquet(*args, **kwargs):
        raise AssertionError("Sealing violation: read_parquet was called during confirmatory dry run!")

    def forbidden_read_table(*args, **kwargs):
        raise AssertionError("Sealing violation: pq.read_table was called during confirmatory dry run!")

    monkeypatch.setattr(pd, "read_parquet", forbidden_read_parquet)
    monkeypatch.setattr(pq, "read_table", forbidden_read_table)

    manifest = run_p7_confirmatory_dry_run(
        repo_root=REPO_ROOT,
        output_manifest_path="data/manifests/p7_confirmatory_dry_run_manifest.json",
    )

    assert manifest["total_confirmatory_cells"] == 756
    assert manifest["confirmation_status"] == "sealed_not_executed"
    assert manifest["confirmatory_outcome_rows_loaded"] is False
    assert manifest["confirmatory_execution_performed"] is False


def test_p7_confirmatory_dry_run_fails_closed_on_tampering(tmp_path):
    """Verify dry-run fails closed if config, pair, or policy counts mismatch."""
    import yaml
    from heattrace.experiments.p6_validity_runner import enumerate_p7_confirmatory_matrix

    with (REPO_ROOT / "configs/p6_validity.yaml").open("r") as f:
        cfg = yaml.safe_load(f)

    # Tamper with confirmatory triplets: drop one
    cfg["triplets"]["confirmatory"] = cfg["triplets"]["confirmatory"][:2]
    bad_yaml = tmp_path / "p6_bad.yaml"
    with bad_yaml.open("w") as f:
        yaml.dump(cfg, f)

    with pytest.raises(ValueError, match="(Expected exactly 3 confirmatory triplets|Confirmatory triplets in fallback mode must contain exactly 3 items)"):
        enumerate_p7_confirmatory_matrix(bad_yaml)


def test_p7_confirmatory_matrix_rejects_fake_identities(tmp_path):
    """Adversarial probe: fake pair, heatwave, control, or blind IDs fail closed."""
    import yaml
    from heattrace.experiments.p6_validity_runner import enumerate_p7_confirmatory_matrix

    with (REPO_ROOT / "configs/p6_validity.yaml").open("r") as f:
        cfg = yaml.safe_load(f)

    # 1. Fake pair ID
    bad_cfg1 = yaml.safe_load(yaml.dump(cfg))
    bad_cfg1["triplets"]["confirmatory"][0]["pair_id"] = "TRIPLET_CONF_FAKE"
    p1 = tmp_path / "bad1.yaml"
    with p1.open("w") as f: yaml.dump(bad_cfg1, f)
    with pytest.raises(ValueError, match="pair_id mismatch"):
        enumerate_p7_confirmatory_matrix(p1)

    # 2. Fake heatwave window ID
    bad_cfg2 = yaml.safe_load(yaml.dump(cfg))
    bad_cfg2["triplets"]["confirmatory"][0]["heatwave_window_id"] = "HW_FAKE"
    p2 = tmp_path / "bad2.yaml"
    with p2.open("w") as f: yaml.dump(bad_cfg2, f)
    with pytest.raises(ValueError, match="identity mismatch"):
        enumerate_p7_confirmatory_matrix(p2)

    # 3. Fake control window ID
    bad_cfg3 = yaml.safe_load(yaml.dump(cfg))
    bad_cfg3["triplets"]["confirmatory"][0]["matched_control_window_id"] = "CTRL_FAKE"
    p3 = tmp_path / "bad3.yaml"
    with p3.open("w") as f: yaml.dump(bad_cfg3, f)
    with pytest.raises(ValueError, match="identity mismatch"):
        enumerate_p7_confirmatory_matrix(p3)

    # 4. Fake blind window ID
    bad_cfg4 = yaml.safe_load(yaml.dump(cfg))
    bad_cfg4["triplets"]["confirmatory"][0]["event_blind_window_id"] = "BLIND_FAKE"
    p4 = tmp_path / "bad4.yaml"
    with p4.open("w") as f: yaml.dump(bad_cfg4, f)
    with pytest.raises(ValueError, match="identity mismatch"):
        enumerate_p7_confirmatory_matrix(p4)


def test_p7_authoritative_loader_triplet_isolation_and_provenance(tmp_path):
    """Verify authoritative loader reads only requested triplet and enforces overlay hash."""
    from heattrace.experiments.p6_validity_runner import load_p7_triplet_benchmark_with_overlay

    pairs_path = REPO_ROOT / "data/benchmarks/p6_event_control_pairs.parquet"
    overlay_path = REPO_ROOT / "data/benchmarks/p7_phase_label_overlay.parquet"

    # Valid load of development triplet
    loaded_dev = load_p7_triplet_benchmark_with_overlay(
        pairs_path,
        overlay_path,
        "TRIPLET_DEV_ae821c",
    )
    assert len(loaded_dev) == 360
    assert set(loaded_dev["triplet_id"].unique()) == {"TRIPLET_DEV_ae821c"}
    # Canonical phases present
    hw_rows = loaded_dev[loaded_dev["window_type"] == "heatwave"]
    assert set(hw_rows["phase_label"].unique()) == {"onset", "peak", "sustained", "recovery"}

    # Rejection of mismatched overlay hash
    with pytest.raises(ValueError, match="Phase overlay hash mismatch"):
        load_p7_triplet_benchmark_with_overlay(
            pairs_path,
            overlay_path,
            "TRIPLET_DEV_ae821c",
            expected_overlay_sha256="0" * 64,
        )


def test_p7_confirmatory_dry_run_rejects_pending_or_invalid_commit():
    """Verify dry-run rejects PENDING_COMMIT or malformed commit hashes."""
    from heattrace.experiments.p6_validity_runner import run_p7_confirmatory_dry_run

    with pytest.raises(ValueError, match="Invalid implementation git_commit"):
        run_p7_confirmatory_dry_run(
            repo_root=REPO_ROOT,
            git_commit="PENDING_COMMIT",
        )

    with pytest.raises(ValueError, match="Invalid implementation git_commit"):
        run_p7_confirmatory_dry_run(
            repo_root=REPO_ROOT,
            git_commit="not_a_valid_commit",
        )
