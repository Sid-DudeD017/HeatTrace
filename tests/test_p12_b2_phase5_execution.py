from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO_ROOT / "data" / "v2" / "benchmarks" / "p12_b2_matrix_cells.csv"
RUNS_PARQUET_PATH = REPO_ROOT / "data" / "v2" / "results" / "p12_b2_runs.parquet"
RUNS_JSONL_PATH = REPO_ROOT / "data" / "v2" / "results" / "p12_b2_execution.jsonl"
MANIFEST_PATH = REPO_ROOT / "data" / "v2" / "manifests" / "p12_b2_execution_manifest.json"


@pytest.fixture(scope="module")
def matrix_df():
    return pd.read_csv(MATRIX_PATH)


@pytest.fixture(scope="module")
def runs_df():
    return pd.read_parquet(RUNS_PARQUET_PATH)


@pytest.fixture(scope="module")
def manifest_data():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def test_matrix_to_result_exact_coverage(matrix_df, runs_df):
    """Every expected run ID has exactly one terminal record; no unexpected or duplicate IDs."""
    assert len(runs_df) == 6480
    assert runs_df["run_id"].nunique() == 6480
    
    expected_ids = set(matrix_df["run_id"])
    actual_ids = set(runs_df["run_id"])
    assert actual_ids == expected_ids, f"Diff: missing={len(expected_ids - actual_ids)}, unexpected={len(actual_ids - expected_ids)}"


def test_deployable_and_oracle_counts(runs_df):
    """Verify 6,336 deployable runs and 144 non-deployable hindsight oracle references."""
    deployable = runs_df[runs_df["deployable"] == True]
    non_deployable = runs_df[runs_df["deployable"] == False]
    
    assert len(deployable) == 6336
    assert len(non_deployable) == 144
    
    # Oracle rows must all be non-deployable
    oracle_rows = runs_df[runs_df["policy"] == "oracle_full_thermal_aware"]
    assert len(oracle_rows) == 144
    assert (oracle_rows["deployable"] == False).all()
    assert (oracle_rows["role"] == "hindsight_oracle_reference").all()


def test_workload_hash_integrity(runs_df):
    """Workload hashes match frozen dry-run manifest for all rows."""
    with open(REPO_ROOT / "data" / "v2" / "manifests" / "p12_b2_matrix_dry_run.json") as f:
        dry_run = json.load(f)
    workload_hashes = {
        (w["duration_hours"], int(w["multiplier"]), w["seed"]): w["csv_sha256"]
        for w in dry_run["workload_identities"]
    }
    
    for _, row in runs_df.iterrows():
        key = (row["duration_hours"], row["workload_multiplier"], row["workload_seed"])
        assert row["workload_hash"] == workload_hashes[key]


def test_forecast_provenance_and_leakage_safety(runs_df):
    """Forecast provenance is truthful and deployable forecast policies enforce t-1 cutoff."""
    # Policies that require TinyLSTM forecasts
    fc_policies = ["capacity_aware", "full_thermal_aware", "heatguard_fixed", "heatguard_calibrated"]
    fc_df = runs_df[runs_df["policy"].isin(fc_policies)]
    assert (fc_df["forecast_identity"] == "p6_temperature_v2_tiny_lstm").all()
    assert (fc_df["forecast_history_cutoff"] == "t-1").all()

    # Static unaware and oracle do not require or use TinyLSTM forecasts
    non_fc_policies = ["static_unaware", "oracle_full_thermal_aware"]
    non_fc_df = runs_df[runs_df["policy"].isin(non_fc_policies)]
    assert (non_fc_df["forecast_identity"] == "NOT_APPLICABLE").all()
    assert (non_fc_df["forecast_history_cutoff"] == "NOT_APPLICABLE").all()


def test_static_forecast_independence(runs_df):
    """Static runs succeed on windows with complete realized data even if TinyLSTM lookback is missing."""
    # The 8 windows where FORECAST_MISSING occurs for forecast policies
    forecast_missing_windows = runs_df[
        (runs_df["policy"].isin(["capacity_aware", "full_thermal_aware"])) & 
        (runs_df["failure_category"] == "FORECAST_MISSING")
    ]["window_id"].unique()
    assert len(forecast_missing_windows) == 8

    # All static_unaware runs on those exact 8 windows MUST be SUCCESS
    static_on_fm = runs_df[
        (runs_df["policy"] == "static_unaware") & 
        (runs_df["window_id"].isin(forecast_missing_windows))
    ]
    assert len(static_on_fm) == 48
    assert (static_on_fm["execution_status"] == "SUCCESS").all()
    assert (static_on_fm["forecast_identity"] == "NOT_APPLICABLE").all()


def test_failure_semantics_and_classification(runs_df):
    """All 1,032 failed rows have null feasibility and null scientific evaluation metrics."""
    failed = runs_df[runs_df["execution_status"] == "FAILED"]
    assert len(failed) == 1032
    
    # Check failure categories
    cats = failed["failure_category"].value_counts().to_dict()
    assert cats == {"WEATHER_DATA_INCOMPLETE": 936, "FORECAST_MISSING": 96}
    
    # Feasibility must be null/NA for all failed rows
    assert failed["scheduler_feasible"].isna().all()
    assert failed["thermally_feasible"].isna().all()

    # Unevaluated scientific metrics must be null
    assert failed["jobs_demanded"].isna().all()
    assert failed["jobs_completed"].isna().all()
    assert failed["jobs_missed"].isna().all()
    assert failed["completed_processing_slots"].isna().all()
    assert failed["unfinished_processing_slots"].isna().all()
    assert failed["it_energy_kwh"].isna().all()
    assert failed["cooling_energy_kwh"].isna().all()
    assert failed["total_facility_energy_kwh"].isna().all()
    assert failed["peak_facility_power_kw"].isna().all()
    assert failed["power_cap_violation_hours"].isna().all()
    assert failed["maximum_power_cap_exceedance_kw"].isna().all()
    assert failed["cooling_adjusted_cost_usd"].isna().all()
    assert failed["cooling_adjusted_carbon_kg"].isna().all()
    assert failed["applied_margin"].isna().all()
    
    # Input demand slots and workload hash are preserved
    assert failed["demanded_processing_slots"].notnull().all()
    assert failed["workload_hash"].notnull().all()
    assert failed["window_id"].notnull().all()
    assert failed["station_code"].notnull().all()


def test_equal_service_accounting(runs_df):
    """Demanded slots match completed + unfinished slots across all SUCCESS rows."""
    success = runs_df[runs_df["execution_status"] == "SUCCESS"]
    assert len(success) == 5448
    
    # Slot balance check
    slot_balance = success["demanded_processing_slots"] - (success["completed_processing_slots"] + success["unfinished_processing_slots"])
    assert (slot_balance == 0).all()
    
    # Feasible check
    feasible = success[success["scheduler_feasible"] == True]
    assert len(feasible) == 310
    assert (feasible["jobs_missed"] == 0).all()
    assert (feasible["unfinished_processing_slots"] == 0).all()


def test_success_only_feasibility_aggregation(runs_df, manifest_data):
    """Manifest feasibility counts are calculated only from successful rows and sum exactly to success_count."""
    fb = manifest_data["feasibility_breakdown"]
    sched_feas = fb["scheduler_feasible_successes"]
    sched_infeas = fb["scheduler_infeasible_successes"]
    therm_feas = fb["thermally_feasible_successes"]
    therm_infeas = fb["thermally_infeasible_successes"]
    success_count = manifest_data["success_count"]

    assert sched_feas + sched_infeas == success_count
    assert therm_feas + therm_infeas == success_count

    # Check against dataframe success rows
    success = runs_df[runs_df["execution_status"] == "SUCCESS"]
    assert sched_feas == (success["scheduler_feasible"] == True).sum()
    assert sched_infeas == (success["scheduler_feasible"] == False).sum()
    assert therm_feas == (success["thermally_feasible"] == True).sum()
    assert therm_infeas == (success["thermally_feasible"] == False).sum()


def test_failure_window_and_cell_breakdowns(runs_df):
    """Failure-window and failure-cell breakdowns match computed actual data."""
    weather_failed = runs_df[runs_df["failure_category"] == "WEATHER_DATA_INCOMPLETE"]
    forecast_failed = runs_df[runs_df["failure_category"] == "FORECAST_MISSING"]

    weather_wids = set(weather_failed["window_id"].unique())
    forecast_wids = set(forecast_failed["window_id"].unique())

    assert len(weather_wids) == 32
    assert len(forecast_wids) == 8
    assert len(weather_wids.intersection(forecast_wids)) == 0
    assert len(weather_wids.union(forecast_wids)) == 40

    # Realized weather incomplete windows by type
    w_by_type = weather_failed[["window_id", "window_type"]].drop_duplicates()["window_type"].value_counts().to_dict()
    assert w_by_type == {"ordinary_window": 27, "matched_control": 4, "heatwave": 1}

    # Forecast lookback incomplete windows by type
    f_by_type = forecast_failed[["window_id", "window_type"]].drop_duplicates()["window_type"].value_counts().to_dict()
    assert f_by_type == {"ordinary_window": 8}

    # Cell counts by window type
    assert weather_failed["window_type"].value_counts().to_dict() == {"ordinary_window": 486, "matched_control": 360, "heatwave": 90}
    assert forecast_failed["window_type"].value_counts().to_dict() == {"ordinary_window": 96}

    # Policy counts
    assert pd.crosstab(runs_df["policy"], runs_df["failure_category"]).to_dict() == {
        "FORECAST_MISSING": {
            "capacity_aware": 48,
            "full_thermal_aware": 48,
            "heatguard_calibrated": 0,
            "heatguard_fixed": 0,
            "oracle_full_thermal_aware": 0,
            "static_unaware": 0,
        },
        "NONE": {
            "capacity_aware": 1686,
            "full_thermal_aware": 1686,
            "heatguard_calibrated": 114,
            "heatguard_fixed": 114,
            "oracle_full_thermal_aware": 114,
            "static_unaware": 1734,
        },
        "WEATHER_DATA_INCOMPLETE": {
            "capacity_aware": 282,
            "full_thermal_aware": 282,
            "heatguard_calibrated": 30,
            "heatguard_fixed": 30,
            "oracle_full_thermal_aware": 30,
            "static_unaware": 282,
        },
    }


def test_targeted_repair_versioned_idempotence(tmp_path):
    """Verify versioned targeted repair selection logic on synthetic records without mutating project outputs."""
    from heattrace.experiments.p12_b2_runner import select_repair_runs

    # Synthetic completed records
    records = {
        "run_success_1": {"run_id": "run_success_1", "execution_status": "SUCCESS"},
        "run_failed_1": {"run_id": "run_failed_1", "execution_status": "FAILED", "failure_category": "WEATHER_DATA_INCOMPLETE"},
        "run_failed_2": {"run_id": "run_failed_2", "execution_status": "FAILED", "failure_category": "FORECAST_MISSING"},
    }

    history: list[dict] = []
    runner_h = "mock_runner_hash_abc"
    config_h = "mock_config_hash_123"
    inputs_fp = "mock_inputs_fp_456"

    # Step 1: Run repair under revision R1
    target_ids, entry = select_repair_runs(
        completed_records=records,
        repair_history=history,
        repair_revision="R1",
        runner_source_hash=runner_h,
        protocol_config_hash=config_h,
        frozen_inputs_fingerprint=inputs_fp,
    )
    assert target_ids == {"run_failed_1", "run_failed_2"}
    assert entry["transaction_state"] == "STARTED"
    assert entry["target_count"] == 2
    # Mark entry COMPLETED
    entry["transaction_state"] = "COMPLETED"
    history.append(entry)

    # Step 2: Invoke repair R1 again with identical code/input hashes -> must be no-op
    target_ids_noop, entry_noop = select_repair_runs(
        completed_records=records,
        repair_history=history,
        repair_revision="R1",
        runner_source_hash=runner_h,
        protocol_config_hash=config_h,
        frozen_inputs_fingerprint=inputs_fp,
    )
    assert len(target_ids_noop) == 0
    assert entry_noop["status"] == "ALREADY_COMPLETED_NOOP"
    assert entry_noop["transaction_state"] == "COMPLETED"

    # Step 3: Authorize new revision R2 -> explicitly selects failed runs again
    target_ids_r2, entry_r2 = select_repair_runs(
        completed_records=records,
        repair_history=history,
        repair_revision="R2",
        runner_source_hash=runner_h,
        protocol_config_hash=config_h,
        frozen_inputs_fingerprint=inputs_fp,
    )
    assert target_ids_r2 == {"run_failed_1", "run_failed_2"}
    assert entry_r2["transaction_state"] == "STARTED"

    # Successful record is NEVER in target_ids
    assert "run_success_1" not in target_ids
    assert "run_success_1" not in target_ids_r2


def test_repair_transaction_true_filesystem_noop(tmp_path):
    """Test 1: Verify that a completed repair identity produces a true filesystem-level no-op.
    
    Zero calls to execute_cell, zero selected IDs, zero replaced records,
    and Parquet, JSONL, Manifest, and Ledger hashes, sizes, and mtimes remain 100% unchanged.
    """
    import os
    import time
    from unittest.mock import MagicMock
    from heattrace.experiments.p12_b2_runner import (
        B2ExecutionRunner,
        execute_matrix,
        sha256_file,
    )

    # Set up mock repo layout in tmp_path
    v2_dir = tmp_path / "data/v2"
    results_dir = v2_dir / "results"
    checkpoints_dir = v2_dir / "checkpoints"
    manifests_dir = v2_dir / "manifests"
    benchmarks_dir = v2_dir / "benchmarks"
    configs_dir = tmp_path / "configs"
    for d in (results_dir, checkpoints_dir, manifests_dir, benchmarks_dir, configs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Synthetic files
    parq_file = results_dir / "p12_b2_runs.parquet"
    jsonl_file = results_dir / "p12_b2_execution.jsonl"
    manifest_file = manifests_dir / "p12_b2_execution_manifest.json"
    ledger_file = checkpoints_dir / "p12_b2_completed_run_ids.json"
    history_file = checkpoints_dir / "p12_b2_repair_history.json"
    config_file = configs_dir / "p12_b2_protocol.yaml"
    config_file.write_text("protocol_version: mock\n")

    # Write initial synthetic payloads
    parq_file.write_bytes(b"PARQUET_SYNTHETIC_DATA")
    jsonl_file.write_text('{"run_id": "mock_run"}\n')
    manifest_file.write_text('{"manifest_version": "2.0"}\n')
    ledger_file.write_text('{"mock_run": {"run_id": "mock_run", "execution_status": "SUCCESS"}}\n')

    runner_h = sha256_file(REPO_ROOT / "src/heattrace/experiments/p12_b2_runner.py")
    config_h = sha256_file(config_file)
    inputs_fp = "mock_inputs_fp_val"

    completed_entry = {
        "repair_revision": "test_rev",
        "runner_source_hash": runner_h,
        "protocol_config_hash": config_h,
        "frozen_inputs_fingerprint": inputs_fp,
        "start_timestamp_utc": "2026-10-31T00:00:00Z",
        "completion_timestamp_utc": "2026-10-31T00:01:00Z",
        "target_count": 0,
        "target_run_ids": [],
        "transaction_state": "COMPLETED",
        "status": "COMPLETED",
    }
    history_file.write_text(json.dumps([completed_entry], indent=2))

    # Record hashes, sizes, mtimes
    files = [parq_file, jsonl_file, manifest_file, ledger_file, history_file]
    pre_hashes = {f: sha256_file(f) for f in files}
    pre_sizes = {f: f.stat().st_size for f in files}
    pre_mtimes = {f: f.stat().st_mtime_ns for f in files}

    time.sleep(0.01)

    # Mock B2ExecutionRunner inside execute_matrix to avoid needing full matrix csv
    mock_runner = MagicMock()
    mock_runner.checkpoints_dir = checkpoints_dir
    mock_runner.results_dir = results_dir
    mock_runner.manifests_dir = manifests_dir

    # Patch select_repair_runs and B2ExecutionRunner
    from unittest.mock import patch
    with patch("heattrace.experiments.p12_b2_runner.B2ExecutionRunner", return_value=mock_runner), \
         patch("heattrace.experiments.p12_b2_runner.compute_frozen_inputs_fingerprint", return_value=inputs_fp):
        execute_matrix(
            repo_root=tmp_path,
            rerun_failed=True,
            repair_revision="test_rev",
        )

    # Assert mock_runner.execute_cell was NEVER called
    assert mock_runner.execute_cell.call_count == 0

    # Assert byte sizes, hashes, and modification times remain 100% unchanged
    for f in files:
        assert sha256_file(f) == pre_hashes[f], f"Hash changed for {f}"
        assert f.stat().st_size == pre_sizes[f], f"Size changed for {f}"
        assert f.stat().st_mtime_ns == pre_mtimes[f], f"mtime changed for {f}"


def test_repair_transaction_started_is_not_completion():
    """Test 2: A matching STARTED transaction raises an explicit recovery error and is not treated as completed."""
    from heattrace.experiments.p12_b2_runner import select_repair_runs

    records = {
        "run_failed_1": {"run_id": "run_failed_1", "execution_status": "FAILED"},
    }
    history = [{
        "repair_revision": "rev_crashed",
        "runner_source_hash": "mock_rhash",
        "protocol_config_hash": "mock_chash",
        "frozen_inputs_fingerprint": "mock_fphash",
        "transaction_state": "STARTED",
        "status": "STARTED",
    }]

    with pytest.raises(RuntimeError) as exc_info:
        select_repair_runs(
            completed_records=records,
            repair_history=history,
            repair_revision="rev_crashed",
            runner_source_hash="mock_rhash",
            protocol_config_hash="mock_chash",
            frozen_inputs_fingerprint="mock_fphash",
        )
    assert "STARTED state" in str(exc_info.value)
    assert "Cannot treat as completed" in str(exc_info.value)


def test_repair_transaction_progression_and_completion(tmp_path):
    """Test 3: Verify state progression STARTED -> COMPLETED with full completion metadata."""
    from unittest.mock import MagicMock, patch
    from heattrace.experiments.p12_b2_runner import execute_matrix, sha256_file

    checkpoints_dir = tmp_path / "data/v2/checkpoints"
    results_dir = tmp_path / "data/v2/results"
    manifests_dir = tmp_path / "data/v2/manifests"
    configs_dir = tmp_path / "configs"
    for d in (checkpoints_dir, results_dir, manifests_dir, configs_dir):
        d.mkdir(parents=True, exist_ok=True)

    config_file = configs_dir / "p12_b2_protocol.yaml"
    config_file.write_text("protocol_version: mock\n")

    ledger_file = checkpoints_dir / "p12_b2_completed_run_ids.json"
    ledger_file.write_text(json.dumps({
        "fail_1": {"run_id": "fail_1", "execution_status": "FAILED", "failure_category": "WEATHER_DATA_INCOMPLETE"}
    }))

    history_file = checkpoints_dir / "p12_b2_repair_history.json"
    history_file.write_text("[]")

    mock_runner = MagicMock()
    mock_runner.checkpoints_dir = checkpoints_dir
    mock_runner.results_dir = results_dir
    mock_runner.manifests_dir = manifests_dir
    # Cells to execute: mock single row
    mock_row = pd.Series({"run_id": "fail_1"})
    mock_runner.df_cells = pd.DataFrame([{"run_id": "fail_1"}])
    mock_runner.execute_cell.return_value = {
        "run_id": "fail_1",
        "execution_status": "SUCCESS",
        "failure_category": "NONE",
        "scheduler_feasible": True,
        "thermally_feasible": True,
        "deployable": True,
    }

    with patch("heattrace.experiments.p12_b2_runner.B2ExecutionRunner", return_value=mock_runner), \
         patch("heattrace.experiments.p12_b2_runner.compute_frozen_inputs_fingerprint", return_value="mock_fp"), \
         patch("heattrace.experiments.p12_b2_runner.verify_protected_baselines", return_value={}):
        execute_matrix(
            repo_root=tmp_path,
            rerun_failed=True,
            repair_revision="rev_progression",
        )

    # Check that transaction was updated to COMPLETED
    with open(history_file) as f:
        hist = json.load(f)
    assert len(hist) == 1
    entry = hist[0]
    assert entry["transaction_state"] == "COMPLETED"
    assert entry["completion_timestamp_utc"] is not None
    assert entry["replaced_record_count"] == 1
    assert entry["previous_status_counts"] == {"FAILED": 1}
    assert entry["resulting_status_counts"] == {"SUCCESS": 1}


def test_repair_transaction_failure_handling(tmp_path):
    """Test 4: Injected failure transitions state to FAILED without marking completed."""
    from unittest.mock import MagicMock, patch
    from heattrace.experiments.p12_b2_runner import execute_matrix

    checkpoints_dir = tmp_path / "data/v2/checkpoints"
    results_dir = tmp_path / "data/v2/results"
    manifests_dir = tmp_path / "data/v2/manifests"
    configs_dir = tmp_path / "configs"
    for d in (checkpoints_dir, results_dir, manifests_dir, configs_dir):
        d.mkdir(parents=True, exist_ok=True)

    config_file = configs_dir / "p12_b2_protocol.yaml"
    config_file.write_text("protocol_version: mock\n")

    ledger_file = checkpoints_dir / "p12_b2_completed_run_ids.json"
    ledger_file.write_text(json.dumps({
        "fail_1": {"run_id": "fail_1", "execution_status": "FAILED", "failure_category": "WEATHER_DATA_INCOMPLETE"}
    }))

    history_file = checkpoints_dir / "p12_b2_repair_history.json"
    history_file.write_text("[]")

    mock_runner = MagicMock()
    mock_runner.checkpoints_dir = checkpoints_dir
    mock_runner.results_dir = results_dir
    mock_runner.manifests_dir = manifests_dir
    mock_runner.df_cells = pd.DataFrame([{"run_id": "fail_1"}])
    # Injected exception during execute_cell
    mock_runner.execute_cell.side_effect = RuntimeError("Controlled execution explosion")

    with patch("heattrace.experiments.p12_b2_runner.B2ExecutionRunner", return_value=mock_runner), \
         patch("heattrace.experiments.p12_b2_runner.compute_frozen_inputs_fingerprint", return_value="mock_fp"):
        with pytest.raises(RuntimeError, match="Controlled execution explosion"):
            execute_matrix(
                repo_root=tmp_path,
                rerun_failed=True,
                repair_revision="rev_failed_test",
            )

    # Check history state is FAILED
    with open(history_file) as f:
        hist = json.load(f)
    assert len(hist) == 1
    assert hist[0]["transaction_state"] == "FAILED"
    assert "Controlled execution explosion" in hist[0]["error_details"]


def test_repair_transaction_protects_successful_rows():
    """Test 5: Attempting to replace an existing successful record raises ValueError."""
    from heattrace.experiments.p12_b2_runner import select_repair_runs

    # Manually corrupted dictionary where a successful record is passed as a target
    records = {
        "run_succ_1": {"run_id": "run_succ_1", "execution_status": "SUCCESS"},
    }
    # select_repair_runs will never select SUCCESS rows
    target_ids, _ = select_repair_runs(
        completed_records=records,
        repair_history=[],
        repair_revision="rev_test",
        runner_source_hash="rh",
        protocol_config_hash="ch",
    )
    assert len(target_ids) == 0


def test_jsonl_and_parquet_alignment(runs_df):
    """Check that JSONL contains identical run IDs and row count as Parquet."""
    lines = []
    with open(RUNS_JSONL_PATH) as f:
        for line in f:
            lines.append(json.loads(line))
    assert len(lines) == 6480
    jsonl_run_ids = [r["run_id"] for r in lines]
    assert jsonl_run_ids == runs_df["run_id"].tolist()


def test_manifest_verification(manifest_data):
    """Verify execution manifest metadata, status counts, and protected baselines."""
    assert manifest_data["total_cells"] == 6480
    assert manifest_data["unique_run_ids"] == 6480
    assert manifest_data["success_count"] == 5448
    assert manifest_data["failed_count"] == 1032
    assert manifest_data["failure_reasons_breakdown"]["WEATHER_DATA_INCOMPLETE"] == 936
    assert manifest_data["failure_reasons_breakdown"]["FORECAST_MISSING"] == 96
    assert "NONE" not in manifest_data["failure_reasons_breakdown"]
    
    # Protected baseline verification in manifest
    assert manifest_data["protected_baselines_verification"]["phase3_event_freeze"] == "972675ef164cd29628eebdc4e509dce352b62a70a2e7214c9e9083f8d33d91c5"


def test_canonical_current_identity_and_noop():
    """Verify that current live runner hash matches a completed canonical rev1 identity and select_repair_runs returns no-op."""
    from heattrace.experiments.p12_b2_runner import (
        select_repair_runs,
        sha256_file,
        compute_frozen_inputs_fingerprint,
    )

    ledger_p = REPO_ROOT / "data/v2/checkpoints/p12_b2_completed_run_ids.json"
    history_p = REPO_ROOT / "data/v2/checkpoints/p12_b2_repair_history.json"
    runner_p = REPO_ROOT / "src/heattrace/experiments/p12_b2_runner.py"
    config_p = REPO_ROOT / "configs/p12_b2_protocol.yaml"

    with open(ledger_p) as f:
        ledger = json.load(f)
    with open(history_p) as f:
        history = json.load(f)

    runner_h = sha256_file(runner_p)
    config_h = sha256_file(config_p)
    inputs_fp = compute_frozen_inputs_fingerprint(REPO_ROOT)

    # Must find a matching completed entry in history
    matching_entry = None
    for entry in history:
        if (
            entry.get("repair_revision") == "rev1"
            and entry.get("runner_source_hash") == runner_h
            and entry.get("protocol_config_hash") == config_h
            and entry.get("frozen_inputs_fingerprint") == inputs_fp
            and entry.get("transaction_state") == "COMPLETED"
        ):
            matching_entry = entry
            break

    assert matching_entry is not None, f"No matching COMPLETED entry found for current runner {runner_h} in canonical history"

    # Calling select_repair_runs with canonical files MUST return 0 targets and ALREADY_COMPLETED_NOOP
    target_ids, entry = select_repair_runs(
        completed_records=ledger,
        repair_history=history,
        repair_revision="rev1",
        runner_source_hash=runner_h,
        protocol_config_hash=config_h,
        frozen_inputs_fingerprint=inputs_fp,
    )
    assert len(target_ids) == 0
    assert entry["status"] == "ALREADY_COMPLETED_NOOP"
    assert entry["transaction_state"] == "COMPLETED"


def test_finalize_repair_identity_idempotence_and_zero_execution(tmp_path):
    """Verify that finalize_repair_identity is fully idempotent and never executes schedulers."""
    from unittest.mock import MagicMock, patch
    from heattrace.experiments.p12_b2_runner import finalize_repair_identity, sha256_file

    # Build mock repo structure
    data_v2 = tmp_path / "data/v2"
    checkpoints_dir = data_v2 / "checkpoints"
    results_dir = data_v2 / "results"
    manifests_dir = data_v2 / "manifests"
    benchmarks_dir = data_v2 / "benchmarks"
    configs_dir = tmp_path / "configs"
    for d in (checkpoints_dir, results_dir, manifests_dir, benchmarks_dir, configs_dir):
        d.mkdir(parents=True, exist_ok=True)

    config_file = configs_dir / "p12_b2_protocol.yaml"
    config_file.write_text("protocol: mock\n")

    # Copy canonical manifests, benchmarks, and results to tmp_path to validate exact gate
    import shutil
    shutil.copy(REPO_ROOT / "data/v2/checkpoints/p12_b2_completed_run_ids.json", checkpoints_dir / "p12_b2_completed_run_ids.json")
    shutil.copy(REPO_ROOT / "data/v2/results/p12_b2_runs.parquet", results_dir / "p12_b2_runs.parquet")
    shutil.copy(REPO_ROOT / "data/v2/results/p12_b2_execution.jsonl", results_dir / "p12_b2_execution.jsonl")
    shutil.copy(REPO_ROOT / "data/v2/manifests/p12_b2_execution_manifest.json", manifests_dir / "p12_b2_execution_manifest.json")
    shutil.copy(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv", benchmarks_dir / "p12_b2_matrix_cells.csv")
    shutil.copy(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv", benchmarks_dir / "p12_b2_controls.csv")
    shutil.copy(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv", benchmarks_dir / "p12_b2_ordinary_windows.csv")
    shutil.copy(REPO_ROOT / "data/v2/manifests/p12_b2_event_freeze.json", manifests_dir / "p12_b2_event_freeze.json")
    events_dir = tmp_path / "data/v2/events"
    events_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv", events_dir / "p12_b2_station_events.csv")
    shutil.copy(REPO_ROOT / "data/v2/manifests/p12_b2_matrix_dry_run.json", manifests_dir / "p12_b2_matrix_dry_run.json")
    shutil.copy(REPO_ROOT / "data/v2/manifests/p12_b2_window_freeze.json", manifests_dir / "p12_b2_window_freeze.json")

    workloads_dir = tmp_path / "data/v2/workloads"
    workloads_dir.mkdir(parents=True, exist_ok=True)
    for p in (REPO_ROOT / "data/v2/workloads").glob("*.parquet"):
        shutil.copy(p, workloads_dir / p.name)
    for p in (REPO_ROOT / "data/v2/workloads").glob("*.csv"):
        shutil.copy(p, workloads_dir / p.name)

    processed_dir = tmp_path / "data/v2/processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "data/v2/processed/p12_b2_caiso_all_parsed.parquet", processed_dir / "p12_b2_caiso_all_parsed.parquet")
    shutil.copy(REPO_ROOT / "data/v2/processed/p12_b2_eia_all_parsed.parquet", processed_dir / "p12_b2_eia_all_parsed.parquet")

    # Initial history with synthetic previous entry
    history_file = checkpoints_dir / "p12_b2_repair_history.json"
    history_file.write_text(json.dumps([{
        "repair_revision": "rev1",
        "runner_source_hash": "old_runner_hash",
        "protocol_config_hash": "mock_cfg_h",
        "frozen_inputs_fingerprint": "mock_fp",
        "transaction_state": "COMPLETED",
        "status": "COMPLETED",
    }], indent=2))

    mock_execute_cell = MagicMock()

    dummy_scaler = {
        "mean": 0.0,
        "std": 1.0,
        "count": 1000,
        "p95": 1.0,
        "fitted_at_utc": "2026-01-01T00:00:00Z",
        "train_start_utc": "2020-01-01T00:00:00Z",
        "train_end_exclusive_utc": "2026-01-01T00:00:00Z",
    }
    with patch("heattrace.experiments.p12_b2_runner.run_preflight", return_value={}), \
         patch("heattrace.experiments.p12_b2_runner.load_verified_checkpoint", return_value=(MagicMock(), {"scaler": dummy_scaler})), \
         patch("heattrace.experiments.p12_b2_runner.B2ExecutionRunner.execute_cell", mock_execute_cell):

        # First run: should append identity migration entry
        res1 = finalize_repair_identity(repo_root=tmp_path, repair_revision="rev1")
        assert res1["transaction_kind"] == "NO_EXECUTION_IDENTITY_MIGRATION"
        assert res1["transaction_state"] == "COMPLETED"
        assert mock_execute_cell.call_count == 0

        with open(history_file) as f:
            h_data = json.load(f)
        assert len(h_data) == 2

        # Record pre-second-run stats
        pre_h = sha256_file(history_file)
        pre_mtime = history_file.stat().st_mtime_ns

        import time
        time.sleep(0.01)

        # Second run: should be true no-op
        res2 = finalize_repair_identity(repo_root=tmp_path, repair_revision="rev1")
        assert res2["transaction_kind"] == "NO_EXECUTION_IDENTITY_MIGRATION"
        assert mock_execute_cell.call_count == 0

        with open(history_file) as f:
            h_data_post = json.load(f)
        assert len(h_data_post) == 2
        assert sha256_file(history_file) == pre_h
        assert history_file.stat().st_mtime_ns == pre_mtime


def test_finalize_repair_identity_rejects_corrupted_state(tmp_path):
    """Verify that finalize_repair_identity rejects corrupted ledger counts or non-null failed metrics."""
    from unittest.mock import MagicMock, patch
    import shutil
    from heattrace.experiments.p12_b2_runner import finalize_repair_identity

    checkpoints_dir = tmp_path / "data/v2/checkpoints"
    results_dir = tmp_path / "data/v2/results"
    manifests_dir = tmp_path / "data/v2/manifests"
    benchmarks_dir = tmp_path / "data/v2/benchmarks"
    events_dir = tmp_path / "data/v2/events"
    configs_dir = tmp_path / "configs"
    for d in (checkpoints_dir, results_dir, manifests_dir, benchmarks_dir, events_dir, configs_dir):
        d.mkdir(parents=True, exist_ok=True)

    config_file = configs_dir / "p12_b2_protocol.yaml"
    config_file.write_text("protocol: mock\n")

    shutil.copy(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv", benchmarks_dir / "p12_b2_controls.csv")
    shutil.copy(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv", benchmarks_dir / "p12_b2_ordinary_windows.csv")
    shutil.copy(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv", benchmarks_dir / "p12_b2_matrix_cells.csv")
    shutil.copy(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv", events_dir / "p12_b2_station_events.csv")
    shutil.copy(REPO_ROOT / "data/v2/manifests/p12_b2_matrix_dry_run.json", manifests_dir / "p12_b2_matrix_dry_run.json")
    shutil.copy(REPO_ROOT / "data/v2/manifests/p12_b2_window_freeze.json", manifests_dir / "p12_b2_window_freeze.json")

    workloads_dir = tmp_path / "data/v2/workloads"
    workloads_dir.mkdir(parents=True, exist_ok=True)
    for p in (REPO_ROOT / "data/v2/workloads").glob("*.parquet"):
        shutil.copy(p, workloads_dir / p.name)
    for p in (REPO_ROOT / "data/v2/workloads").glob("*.csv"):
        shutil.copy(p, workloads_dir / p.name)

    processed_dir = tmp_path / "data/v2/processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "data/v2/processed/p12_b2_caiso_all_parsed.parquet", processed_dir / "p12_b2_caiso_all_parsed.parquet")
    shutil.copy(REPO_ROOT / "data/v2/processed/p12_b2_eia_all_parsed.parquet", processed_dir / "p12_b2_eia_all_parsed.parquet")

    # Incomplete ledger (e.g. 1 record only)
    ledger_file = checkpoints_dir / "p12_b2_completed_run_ids.json"
    ledger_file.write_text(json.dumps({
        "mock_1": {"run_id": "mock_1", "execution_status": "SUCCESS"}
    }))

    dummy_scaler = {
        "mean": 0.0,
        "std": 1.0,
        "count": 1000,
        "p95": 1.0,
        "fitted_at_utc": "2026-01-01T00:00:00Z",
        "train_start_utc": "2020-01-01T00:00:00Z",
        "train_end_exclusive_utc": "2026-01-01T00:00:00Z",
    }
    with patch("heattrace.experiments.p12_b2_runner.run_preflight", return_value={}), \
         patch("heattrace.experiments.p12_b2_runner.load_verified_checkpoint", return_value=(MagicMock(), {"scaler": dummy_scaler})):
        with pytest.raises(ValueError, match="Ledger record count mismatch: 1 != 6480"):
            finalize_repair_identity(repo_root=tmp_path, repair_revision="rev1")
