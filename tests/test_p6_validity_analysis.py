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
    classify_ranking_transition,
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
    generate_h1_h5_assessment_table,
    generate_t3_equal_service_gaps,
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


def test_seed_aggregation_before_policy_contrasts(p8_df):
    """Verify that seeds are aggregated before computing policy contrasts in p6_policy_pairwise_metrics."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    assert len(pairwise_df) == 540
    assert (pairwise_df["seed_count"] == 2).all()
    assert "source_run_ids_a" in pairwise_df.columns
    assert "source_run_ids_b" in pairwise_df.columns
    assert "triplet_id" in pairwise_df.columns


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


def test_h2_recovery_classification_and_prerequisites(p8_df):
    """Verify H2 evaluation handles prerequisite static loss and reports exact recovery numbers."""
    h2 = evaluate_h2(p8_df)
    assert h2["classification"] == "NOT_SUPPORTED"

    # CONF_3 has no prerequisite static loss -> NOT_APPLICABLE
    assert h2["capacity_aware"]["TRIPLET_CONF_3_628624"]["status"] == "NOT_APPLICABLE_NO_PREREQUISITE_LOSS"
    assert h2["full_thermal_aware"]["TRIPLET_CONF_3_628624"]["status"] == "NOT_APPLICABLE_NO_PREREQUISITE_LOSS"

    # CONF_1 and CONF_2 have prerequisite loss
    assert h2["capacity_aware"]["TRIPLET_CONF_1_f5c700"]["boundary_recovery"] == 0.0
    assert h2["full_thermal_aware"]["TRIPLET_CONF_1_f5c700"]["boundary_recovery"] == -0.5
    assert h2["capacity_aware"]["TRIPLET_CONF_2_2a6e22"]["boundary_recovery"] == 0.0
    assert h2["full_thermal_aware"]["TRIPLET_CONF_2_2a6e22"]["boundary_recovery"] == 0.0

    # Violation reduction
    assert h2["full_thermal_aware"]["TRIPLET_CONF_2_2a6e22"]["violation_hours_reduction"] == 0.5
    assert h2["full_thermal_aware"]["TRIPLET_CONF_1_f5c700"]["violation_hours_reduction"] == 1.0


def test_ranking_transition_classification_logic():
    """Verify ranking transition semantics (ties vs strict reversals)."""
    # Strict reversal: A-pref to B-pref
    assert classify_ranking_transition("policy_a_preferred", "policy_b_preferred") == "STRICT_REVERSAL"
    assert classify_ranking_transition("policy_b_preferred", "policy_a_preferred") == "STRICT_REVERSAL"

    # Tie to non-tie
    assert classify_ranking_transition("TIE", "policy_a_preferred") == "BASELINE_TIE_TO_HEATWAVE_NON_TIE"
    assert classify_ranking_transition("TIE", "policy_b_preferred") == "BASELINE_TIE_TO_HEATWAVE_NON_TIE"

    # Non-tie to tie
    assert classify_ranking_transition("policy_a_preferred", "TIE") == "BASELINE_NON_TIE_TO_HEATWAVE_TIE"

    # Unchanged
    assert classify_ranking_transition("TIE", "TIE") == "SAME"
    assert classify_ranking_transition("policy_a_preferred", "policy_a_preferred") == "SAME"

    # Guarded
    assert classify_ranking_transition(None, "policy_a_preferred") == "NOT_ESTIMABLE"
    assert classify_ranking_transition("NOT_ESTIMABLE", "TIE") == "NOT_ESTIMABLE"


def test_h3_full_scope_denominators_and_transition_counts(p8_df):
    """Verify H3 full scope has denominator 36 per triplet, correct event effects, and zero strict reversals."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    h3 = evaluate_h3(pairwise_df)

    assert h3["classification"] == "PARTIALLY_SUPPORTED"
    assert h3["total_triplets"] == 3

    # Check denominator 36 across all triplets
    for t in ["TRIPLET_CONF_1_f5c700", "TRIPLET_CONF_2_2a6e22", "TRIPLET_CONF_3_628624"]:
        res = h3["event_results"][t]
        assert res["total_evaluated_pairs_per_context"] == 36
        # Numerator never exceeds denominator
        assert res["heatwave_nonzero_cost_comparisons"] <= 36
        assert res["control_nonzero_cost_comparisons"] <= 36
        assert res["blind_nonzero_cost_comparisons"] <= 36

    # CONF_1: 24/36 HW, 24/36 CTRL, 0/36 BLIND
    c1 = h3["event_results"]["TRIPLET_CONF_1_f5c700"]
    assert c1["heatwave_nonzero_cost_comparisons"] == 24
    assert c1["control_nonzero_cost_comparisons"] == 24
    assert c1["blind_nonzero_cost_comparisons"] == 0
    assert c1["event_effect_nonzero_cost_delta"] == 24
    assert c1["blind_tie_to_nontie_count"] == 24
    assert c1["blind_strict_reversals_count"] == 0

    # CONF_2: 24/36 HW, 0/36 CTRL, 0/36 BLIND
    c2 = h3["event_results"]["TRIPLET_CONF_2_2a6e22"]
    assert c2["heatwave_nonzero_cost_comparisons"] == 24
    assert c2["control_nonzero_cost_comparisons"] == 0
    assert c2["blind_nonzero_cost_comparisons"] == 0
    assert c2["event_effect_nonzero_cost_delta"] == 24
    assert c2["blind_tie_to_nontie_count"] == 24
    assert c2["blind_strict_reversals_count"] == 0

    # CONF_3: 0/36 HW, 0/36 CTRL, 0/36 BLIND
    c3 = h3["event_results"]["TRIPLET_CONF_3_628624"]
    assert c3["heatwave_nonzero_cost_comparisons"] == 0
    assert c3["control_nonzero_cost_comparisons"] == 0
    assert c3["blind_nonzero_cost_comparisons"] == 0
    assert c3["event_effect_nonzero_cost_delta"] == 0
    assert c3["blind_tie_to_nontie_count"] == 0
    assert c3["blind_strict_reversals_count"] == 0

    # Event effects list and median
    assert h3["event_effects"] == [24, 24, 0]
    assert h3["median_event_effect"] == 24.0
    assert h3["sign_consistency"] == "2/3 positive"


def test_t3_primary_condition_rows_and_transitions(p8_df):
    """Verify primary T3 table has exactly 27 rows (9 per triplet) with explicit transition fields."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    t3_df = generate_t3_equal_service_gaps(pairwise_df)

    assert len(t3_df) == 27
    for t in ["TRIPLET_CONF_1_f5c700", "TRIPLET_CONF_2_2a6e22", "TRIPLET_CONF_3_628624"]:
        assert len(t3_df[t3_df["triplet_id"] == t]) == 9

    # Check explicit fields
    for col in [
        "transition_vs_control",
        "transition_vs_blind",
        "strict_reversal_vs_control",
        "strict_reversal_vs_blind",
        "tie_to_nontie_vs_control",
        "tie_to_nontie_vs_blind",
    ]:
        assert col in t3_df.columns

    # Strict reversals vs blind are 0 across all 27 rows
    assert t3_df["strict_reversal_vs_blind"].sum() == 0
    # Tie to nontie vs blind: 12 total (6 in CONF_1, 6 in CONF_2)
    assert t3_df["tie_to_nontie_vs_blind"].sum() == 12


def test_h4_not_estimable_without_controlled_forecast_mutation(p8_df):
    """Verify H4 is strictly classified NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION."""
    h4 = evaluate_h4(p8_df)
    assert h4["classification"] == "NOT_ESTIMABLE"
    assert h4["estimability"] == "NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION"
    assert "controlled forecast-source intervention" in h4["missing_comparison"]


def test_h5_comparator_event_level_and_zero_margin_equivalence(p8_df):
    """Verify H5 evaluates against both comparators per event and documents zero-margin equivalence."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    h5 = evaluate_h5(p8_df, pairwise_df)

    assert h5["classification"] == "NOT_SUPPORTED"
    assert "full_thermal_aware verified equivalent to zero-margin HeatGuard" in h5["no_margin_comparator_equivalence"]
    assert len(h5["event_comparisons"]) == 3

    assert h5["event_comparisons"]["TRIPLET_CONF_1_f5c700"]["improves_over_fixed_margin"] is False
    assert h5["event_comparisons"]["TRIPLET_CONF_2_2a6e22"]["improves_over_fixed_margin"] is False
    assert h5["event_comparisons"]["TRIPLET_CONF_3_628624"]["improves_over_fixed_margin"] is False


def test_equal_service_rejection_after_aggregation(p8_df):
    """Verify equal-service enforcement correctly rejects aggregated comparisons if any seed failed."""
    pairwise_df = compute_policy_pairwise_metrics(p8_df)
    assert len(pairwise_df) == 540

    rejected = pairwise_df[pairwise_df["equal_service_eligible"] == False]
    assert len(rejected) == 10
    for _, row in rejected.iterrows():
        assert "oracle_full_thermal_aware" in (row["policy_id_a"], row["policy_id_b"])
        assert pd.isna(row["cost_gap_usd"])
        assert pd.isna(row["carbon_gap_kg"])
        assert row["cost_rank_order"] == "NULL_UNEQUAL_SERVICE"

    eligible = pairwise_df[pairwise_df["equal_service_eligible"] == True]
    assert len(eligible) == 530
    assert eligible["cost_gap_usd"].notnull().all()


def test_relative_gap_zero_and_near_zero_denominators():
    """Direct probe of zero and near-zero denominators in relative gap calculation."""
    assert compute_relative_gap(0.0, 0.0) == 0.0
    assert compute_relative_gap(1e-8, 1e-8) == 0.0
    assert compute_relative_gap(1e-5, 1e-8) is not None
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
        "run_id": "run_a1",
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
        "seed": 20261017,
        "workload_trace_id": "trace_1",
        "objective": "carbon_first",
        "run_id": "run_a2",
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
        "run_id": "run_b1",
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
    }, {
        "triplet_id": "TRIPLET_CONF_1_f5c700",
        "context": "heatwave",
        "facility_model": "power_capped",
        "thermal_curve": "medium",
        "workload_multiplier": 1.0,
        "seed": 20261017,
        "workload_trace_id": "trace_1",
        "objective": "carbon_first",
        "run_id": "run_b2",
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
    v1 = [1.0, 2.0, 3.0]
    assert compute_allocation_distance(v1, v1) == 0.0

    va = [1.0, 0.0]
    vb = [0.0, 1.0]
    assert pytest.approx(compute_allocation_distance(va, vb)) == 2.0 / 1.0

    with pytest.raises(ValueError):
        compute_allocation_distance([1.0], [1.0, 2.0])


def test_synthetic_mutation_changes_evaluator_classification(p8_df):
    """Regression test proving classification changes dynamically when synthetic data changes."""
    mutated_df = p8_df.copy()
    mask = (
        (mutated_df["triplet_id"] == "TRIPLET_CONF_3_628624")
        & (mutated_df["context"] == "heatwave")
        & (mutated_df["policy_id"] == "full_thermal_aware")
    )
    mutated_df.loc[mask, "cooling_adjusted_cost_usd"] += 50.0

    pw_mut = compute_policy_pairwise_metrics(mutated_df)
    h3_mut = evaluate_h3(pw_mut)
    assert h3_mut["classification"] == "SUPPORTED"
    assert h3_mut["discriminating_triplet_count"] == 3

    t_mut = generate_h1_h5_assessment_table(mutated_df, pw_mut)
    h3_row = t_mut[t_mut["hypothesis"].str.startswith("H3")].iloc[0]
    assert h3_row["classification"] == "SUPPORTED"
    assert "3/3 positive" in h3_row["sign_consistency"]


def test_h2_markdown_report_matches_evaluator_data(tmp_path):
    """Verify H2 markdown report accurately displays full-thermal CONF-1 boundary change of -0.5x."""
    res_dir = tmp_path / "results"
    fig_dir = tmp_path / "figures"
    doc_dir = tmp_path / "docs"

    run_phase_9_analysis(
        results_dir=res_dir,
        figures_dir=fig_dir,
        docs_dir=doc_dir,
    )

    report_text = (doc_dir / "p6_phase9_analysis_report.md").read_text(encoding="utf-8")
    assert "boundary change=-0.5x" in report_text
    assert "0.0x recovery in CONF_1 and CONF_2" not in report_text
    assert "/12" not in report_text
    assert "/36" in report_text


def test_deterministic_full_generation(tmp_path):
    """Verify full end-to-end analysis runs deterministically and produces identical hashes across clean dirs."""
    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"

    out1 = run_phase_9_analysis(
        results_dir=dir1 / "results",
        figures_dir=dir1 / "figures",
        docs_dir=dir1 / "docs",
    )
    out2 = run_phase_9_analysis(
        results_dir=dir2 / "results",
        figures_dir=dir2 / "figures",
        docs_dir=dir2 / "docs",
    )

    assert len(out1["event_metrics_df"]) == 378
    assert len(out1["pairwise_df"]) == 540
    assert len(out1["tables"]["T3"]) == 27

    for filename in [
        "p6_event_level_metrics.csv",
        "p6_policy_pairwise_metrics.csv",
        "p6_t1_cohort_provenance.csv",
        "p6_t2_event_feasibility.csv",
        "p6_t3_equal_service_gaps.csv",
        "p6_t4_forecast_evidence.csv",
        "p6_h1_h5_assessment.csv",
    ]:
        h1 = sha256_file(dir1 / "results" / filename)
        h2 = sha256_file(dir2 / "results" / filename)
        assert h1 == h2, f"Nondeterministic CSV output for {filename}"

    for filename in ["p6_f2_allocation_distance_status.md", "p6_f3_forecast_regret_status.md"]:
        h1 = sha256_file(dir1 / "figures" / filename)
        h2 = sha256_file(dir2 / "figures" / filename)
        assert h1 == h2, f"Nondeterministic status artifact for {filename}"

    h1_rep = sha256_file(dir1 / "docs" / "p6_phase9_analysis_report.md")
    h2_rep = sha256_file(dir2 / "docs" / "p6_phase9_analysis_report.md")
    assert h1_rep == h2_rep, "Nondeterministic report markdown output"
