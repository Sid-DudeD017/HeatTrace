"""Tests for Phase 9 confirmatory validity analysis and contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from heattrace.evaluation.p6_validity import (
    CANONICAL_P8_HASHES,
    EXPECTED_ROW_COUNT,
    FLOAT_TOLERANCE,
    compute_allocation_distance,
    compute_event_level_metrics,
    compute_policy_pairwise_metrics,
    compute_relative_gap,
    compute_run_id_digest,
    compute_tested_feasible_boundary,
    evaluate_h1,
    evaluate_h2,
    evaluate_h3,
    evaluate_h4,
    evaluate_h5,
    is_row_feasible,
    run_phase_9_analysis,
    sha256_file,
    verify_p8_baseline,
)


@pytest.fixture
def p8_df():
    """Load canonical verified P8 dataset."""
    return verify_p8_baseline()


def test_canonical_p8_artifacts_byte_identical():
    """Verify all 4 P8 inputs match their frozen SHA-256 hashes exactly."""
    runs_p = Path("data/results/p6_validity_runs.parquet")
    chk_p = Path("data/results/p6_validity_checkpoint.parquet")
    man_p = Path("data/results/p6_validity_manifest.json")
    exe_p = Path("data/results/p6_validity_execution.jsonl")

    assert sha256_file(runs_p) == CANONICAL_P8_HASHES["runs"]
    assert sha256_file(chk_p) == CANONICAL_P8_HASHES["checkpoint"]
    assert sha256_file(man_p) == CANONICAL_P8_HASHES["manifest"]
    assert sha256_file(exe_p) == CANONICAL_P8_HASHES["execution"]


def test_p8_baseline_accounting(p8_df):
    """Verify P8 accounting: exactly 756 unique runs, 0 failures, correct cohorts."""
    assert len(p8_df) == EXPECTED_ROW_COUNT
    assert p8_df["run_id"].nunique() == EXPECTED_ROW_COUNT
    assert (p8_df["status"] == "SUCCESS").all()

    cohort_counts = p8_df["cohort"].value_counts().to_dict()
    assert cohort_counts["core_benchmark"] == 432
    assert cohort_counts["event_blind_benchmark"] == 216
    assert cohort_counts["algorithm_comparators"] == 72
    assert cohort_counts["oracle_reference"] == 36


def test_oracle_excluded_from_deployable(p8_df):
    """Verify oracle reference policy is strictly non-deployable."""
    oracle = p8_df[p8_df["cohort"] == "oracle_reference"]
    assert len(oracle) == 36
    assert (oracle["deployable"] == False).all()
    assert (oracle["policy_id"] == "oracle_full_thermal_aware").all()


def test_duplicate_run_ids_fail_closed(p8_df, tmp_path):
    """Verify baseline validation fails closed if run IDs contain duplicates."""
    dup_df = pd.concat([p8_df, p8_df.iloc[[0]]], ignore_index=True)
    dup_parquet = tmp_path / "dup_runs.parquet"
    dup_df.to_parquet(dup_parquet)

    with pytest.raises(ValueError, match="Expected 756"):
        verify_p8_baseline(runs_path=dup_parquet, check_hashes=False)


def test_missing_expected_ids_fail_closed(p8_df, tmp_path):
    """Verify baseline validation fails closed if rows are missing."""
    short_df = p8_df.iloc[:-1]
    short_parquet = tmp_path / "short_runs.parquet"
    short_df.to_parquet(short_parquet)

    with pytest.raises(ValueError, match="Expected 756"):
        verify_p8_baseline(runs_path=short_parquet, check_hashes=False)


def test_failure_rows_retained_in_feasibility():
    """Verify strict feasibility fails on any violation, failure, or unfinished slot."""
    row_ok = {
        "status": "SUCCESS",
        "scheduler_feasible": True,
        "thermally_feasible": True,
        "unfinished_processing_slots": 0,
        "unmet_deadlines_count": 0,
        "facility_power_violation_hours": 0,
        "total_facility_power_excess_kwh": 0,
    }
    assert is_row_feasible(row_ok) is True

    # Variations of failure
    for field, bad_val in [
        ("status", "FAILED"),
        ("scheduler_feasible", False),
        ("thermally_feasible", False),
        ("unfinished_processing_slots", 1),
        ("unmet_deadlines_count", 2),
        ("facility_power_violation_hours", 1),
        ("total_facility_power_excess_kwh", 0.5),
    ]:
        row_bad = dict(row_ok)
        row_bad[field] = bad_val
        assert is_row_feasible(row_bad) is False, f"Failed to reject bad {field}={bad_val}"


def test_seed_aggregation_before_pair_contrast(p8_df):
    """Verify that seeds are aggregated before computing event-level contrast."""
    # Check H1 evaluation
    h1 = evaluate_h1(p8_df)
    # 3 pairs
    assert len(h1["medium_primary"]["pair_effects"]) == 3
    # Check that pair effects use seed-aggregated boundary (mean of seed boundaries)
    triplet_1 = "TRIPLET_CONF_1_f5c700"
    b_hw = compute_tested_feasible_boundary(
        p8_df, triplet_1, "heatwave", "power_capped", "medium", "carbon_first", "static_unaware"
    )
    b_ctrl = compute_tested_feasible_boundary(
        p8_df, triplet_1, "control", "power_capped", "medium", "carbon_first", "static_unaware"
    )
    # HW: seed 20261016=3.0, seed 20261017=2.0 -> mean = 2.5
    # CTRL: seed 20261016=3.0, seed 20261017=3.0 -> mean = 3.0
    assert b_hw == 2.5
    assert b_ctrl == 3.0
    assert b_hw - b_ctrl == -0.5
    assert h1["medium_primary"]["pair_effects"][triplet_1] == -0.5


def test_h1_support_rule_and_outcome(p8_df):
    """Verify H1 primary support rule: at least 2 of 3 negative and negative median."""
    h1 = evaluate_h1(p8_df)
    med_res = h1["medium_primary"]
    assert med_res["pair_effects"]["TRIPLET_CONF_1_f5c700"] == -0.5
    assert med_res["pair_effects"]["TRIPLET_CONF_2_2a6e22"] == -0.5
    assert med_res["pair_effects"]["TRIPLET_CONF_3_628624"] == 0.0
    assert med_res["median_effect"] == -0.5
    assert med_res["negative_effect_count"] == 2
    assert med_res["support_criterion_met"] is True
    assert med_res["classification"] == "SUPPORTED"


def test_h2_recovery_classification(p8_df):
    """Verify H2 evaluation correctly classifies recovery as NOT_SUPPORTED on tested boundary."""
    h2 = evaluate_h2(p8_df)
    assert h2["classification"] == "NOT_SUPPORTED"
    # Neither policy expands the tested boundary beyond static (recovery <= 0.0)
    for pol in ["capacity_aware", "full_thermal_aware"]:
        for t in ["TRIPLET_CONF_1_f5c700", "TRIPLET_CONF_2_2a6e22"]:
            assert h2[pol][t]["boundary_recovery"] <= 0.0
            assert h2[pol][t]["is_boundary_recovery"] is False


def test_h3_benchmark_discriminability(p8_df):
    """Verify H3 shows heatwave exposes differences that event-blind windows obscure."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    h3 = evaluate_h3(pairwise_df)
    assert h3["classification"] == "SUPPORTED"
    assert h3["understatement_demonstrated"] is True
    assert h3["context_summary"]["event_blind"]["nonzero_cost_diff_count"] == 0
    assert h3["context_summary"]["heatwave"]["nonzero_cost_diff_count"] == 96


def test_h4_not_estimable_without_controlled_forecast_mutation(p8_df):
    """Verify H4 is strictly classified NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION."""
    h4 = evaluate_h4(p8_df)
    assert h4["classification"] == "NOT_ESTIMABLE"
    assert h4["estimability"] == "NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION"
    assert "controlled forecast-source intervention" in h4["missing_comparison"]


def test_h5_heatguard_comparator_classification(p8_df):
    """Verify H5 evaluates calibrated vs fixed margin and classifies NOT_SUPPORTED."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    h5 = evaluate_h5(p8_df, pairwise_df)
    assert h5["classification"] == "NOT_SUPPORTED"
    assert h5["heatwave_violation_hours"]["heatguard_calibrated"] == 3
    assert h5["heatwave_violation_hours"]["heatguard_fixed"] == 1


def test_equal_service_rejection_logic(p8_df):
    """Verify equal-service enforcement correctly rejects unequal work and permits equal work."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    assert len(pairwise_df) == 1080

    # Rejected pairs should be exactly 10 (all involving oracle with 12 unfinished slots in control)
    rejected = pairwise_df[pairwise_df["equal_service_eligible"] == False]
    assert len(rejected) == 10
    for _, row in rejected.iterrows():
        assert "oracle_full_thermal_aware" in (row["policy_id_a"], row["policy_id_b"])
        assert pd.isna(row["cost_gap_usd"])
        assert pd.isna(row["carbon_gap_kg"])
        assert row["cost_rank_order"] == "NULL_UNEQUAL_SERVICE"

    # Eligible pairs
    eligible = pairwise_df[pairwise_df["equal_service_eligible"] == True]
    assert len(eligible) == 1070
    assert eligible["cost_gap_usd"].notnull().all()


def test_relative_gap_zero_and_near_zero_denominators():
    """Direct probe of zero and near-zero denominators in relative gap calculation."""
    # Both zero -> 0.0
    assert compute_relative_gap(0.0, 0.0) == 0.0
    assert compute_relative_gap(1e-8, 1e-8) == 0.0

    # Near-zero denominator with difference -> None / guarded
    assert compute_relative_gap(1e-5, 1e-8) is not None
    # Regular values
    assert pytest.approx(compute_relative_gap(10.0, 5.0)) == 5.0 / 10.0
    assert pytest.approx(compute_relative_gap(5.0, 10.0)) == -5.0 / 10.0


def test_exact_ties_and_rankings():
    """Verify exact ties produce TIE and no preference bias."""
    df_tie = pd.DataFrame([{
        "triplet_id": "TRIPLET_CONF_1_f5c700",
        "context": "heatwave",
        "facility_model": "power_capped",
        "thermal_curve": "medium",
        "workload_multiplier": 1.0,
        "seed": 20261016,
        "workload_trace_id": "trace_1",
        "objective": "carbon_first",
        "run_id": "run_a",
        "policy_id": "policy_a",
        "deployable": True,
        "status": "SUCCESS",
        "scheduler_feasible": True,
        "thermally_feasible": True,
        "demanded_processing_slots": 100,
        "completed_processing_slots": 100,
        "unfinished_processing_slots": 0,
        "unmet_deadlines_count": 0,
        "facility_power_violation_hours": 0,
        "total_facility_power_excess_kwh": 0,
        "cooling_adjusted_cost_usd": 150.0,
        "cooling_adjusted_carbon_kg": 200.0,
    }, {
        "triplet_id": "TRIPLET_CONF_1_f5c700",
        "context": "heatwave",
        "facility_model": "power_capped",
        "thermal_curve": "medium",
        "workload_multiplier": 1.0,
        "seed": 20261016,
        "workload_trace_id": "trace_1",
        "objective": "carbon_first",
        "run_id": "run_b",
        "policy_id": "policy_b",
        "deployable": True,
        "status": "SUCCESS",
        "scheduler_feasible": True,
        "thermally_feasible": True,
        "demanded_processing_slots": 100,
        "completed_processing_slots": 100,
        "unfinished_processing_slots": 0,
        "unmet_deadlines_count": 0,
        "facility_power_violation_hours": 0,
        "total_facility_power_excess_kwh": 0,
        "cooling_adjusted_cost_usd": 150.0,
        "cooling_adjusted_carbon_kg": 200.0,
    }])
    p_df = compute_policy_pairwise_metrics(df_tie)
    assert len(p_df) == 1
    assert bool(p_df.iloc[0]["is_exact_cost_tie"]) is True
    assert bool(p_df.iloc[0]["is_exact_carbon_tie"]) is True
    assert p_df.iloc[0]["cost_rank_order"] == "TIE"
    assert p_df.iloc[0]["carbon_rank_order"] == "TIE"


def test_allocation_distance_math():
    """Verify allocation distance formula ||x - y||_1 / max(||x||_1, ||y||_1, eps)."""
    # Identical vectors yield zero
    v1 = [1.0, 2.0, 3.0]
    assert compute_allocation_distance(v1, v1) == 0.0

    # Orthogonal vectors with equal norm
    va = [1.0, 0.0]
    vb = [0.0, 1.0]
    assert pytest.approx(compute_allocation_distance(va, vb)) == 2.0 / 1.0

    # Differing lengths raise
    with pytest.raises(ValueError):
        compute_allocation_distance([1.0], [1.0, 2.0])


def test_deterministic_full_generation(tmp_path):
    """Verify full end-to-end analysis runs deterministically and produces expected artifacts."""
    res_dir = tmp_path / "results"
    fig_dir = tmp_path / "figures"
    doc_dir = tmp_path / "docs"

    out = run_phase_9_analysis(
        results_dir=res_dir,
        figures_dir=fig_dir,
        docs_dir=doc_dir,
    )

    # Check files exist
    assert (res_dir / "p6_event_level_metrics.csv").exists()
    assert (res_dir / "p6_policy_pairwise_metrics.csv").exists()
    assert (res_dir / "p6_analysis_manifest.json").exists()
    assert (res_dir / "p6_t1_cohort_provenance.csv").exists()
    assert (res_dir / "p6_t2_event_feasibility.csv").exists()
    assert (res_dir / "p6_t3_equal_service_gaps.csv").exists()
    assert (res_dir / "p6_t4_forecast_evidence.csv").exists()
    assert (res_dir / "p6_h1_h5_assessment.csv").exists()
    assert (fig_dir / "p6_f1_event_policy_contrasts.png").exists()
    assert (fig_dir / "p6_f4_h1_sensitivity.png").exists()
    assert (fig_dir / "p6_f2_allocation_distance_status.md").exists()
    assert (fig_dir / "p6_f3_forecast_regret_status.md").exists()
    assert (doc_dir / "p6_phase9_analysis_report.md").exists()

    # Verify primary output row counts
    assert len(out["event_metrics_df"]) == 378
    assert len(out["pairwise_df"]) == 1080
