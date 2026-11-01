"""Tests for Track B2 Phase 6 Analysis and Validity Evaluations."""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from heattrace.evaluation.p12_b2_validity import (
    CANONICAL_PHASE5_HASHES,
    DEPLOYABLE_POLICIES,
    CORE_DEPLOYABLE_POLICIES,
    verify_phase5_inputs,
    build_missingness_audit,
    build_equal_service_audit,
    calculate_tested_feasibility_boundary,
    evaluate_g1_temporal_replication,
    evaluate_g2_geographic_heterogeneity,
    evaluate_g3_benchmark_discriminability,
    evaluate_g4_continuity_gate,
    evaluate_g5_bounded_robustness,
    sha256_file,
)


@pytest.fixture(scope="module")
def runs_df():
    return pd.read_parquet("data/v2/results/p12_b2_runs.parquet")


@pytest.fixture(scope="module")
def events_df():
    return pd.read_csv("data/v2/events/p12_b2_station_events.csv")


@pytest.fixture(scope="module")
def episodes_df():
    return pd.read_csv("data/v2/events/p12_b2_regional_episodes.csv")


@pytest.fixture(scope="module")
def controls_df():
    return pd.read_csv("data/v2/benchmarks/p12_b2_controls.csv")


@pytest.fixture(scope="module")
def ow_df():
    return pd.read_csv("data/v2/benchmarks/p12_b2_ordinary_windows.csv")


@pytest.fixture(scope="module")
def overlap_df():
    return pd.read_csv("data/v2/benchmarks/p12_b2_window_overlap_graph.csv")


def test_phase5_input_hashes():
    """Verify authoritative Phase 5 input hashes."""
    verify_phase5_inputs()


def test_hierarchical_nesting(events_df, episodes_df):
    """Verify exact hierarchical nesting: station event -> exactly one regional episode."""
    assert "regional_episode_id" in events_df.columns
    assert "regional_episode_id" in episodes_df.columns
    assert events_df["regional_episode_id"].notna().all()
    assert set(events_df["regional_episode_id"]).issubset(set(episodes_df["regional_episode_id"]))


def test_failed_row_exclusion_and_missingness_audit(runs_df, events_df, episodes_df, controls_df, ow_df):
    """Verify failed executions are excluded from effects but preserved in missingness audit."""
    audit = build_missingness_audit(runs_df, events_df, episodes_df, controls_df, ow_df)
    total_row = audit[audit["scope"] == "total_matrix"].iloc[0]
    assert total_row["total_cells"] == 6480
    assert total_row["successful_cells"] == 5448
    assert total_row["failed_cells"] == 1032
    assert total_row["weather_incomplete_cells"] == 936
    assert total_row["forecast_missing_cells"] == 96


def test_equal_service_audit(runs_df):
    """Verify equal service filtering for cost and carbon comparisons."""
    audit = build_equal_service_audit(runs_df)
    assert len(audit) > 0
    stat_row = audit[
        (audit["comparison_type"] == "heatwave_vs_matched_control")
        & (audit["policy"] == "static_unaware")
    ].iloc[0]
    assert stat_row["total_pairs"] == 192
    assert stat_row["equal_service_pairs"] == 192
    assert stat_row["unequal_service_excluded"] == 0

    hw_trio = audit[audit["comparison_type"] == "within_window_core_trio_heatwave"].iloc[0]
    assert hw_trio["total_pairs"] == 66
    assert hw_trio["equal_service_pairs"] == 7
    assert hw_trio["unequal_service_excluded"] == 59


def test_g1_tested_feasibility_boundary_calculation(runs_df, events_df):
    """Verify G1 tested boundary is dynamically derived from row data without hardcoding."""
    ev_b, ep_b = calculate_tested_feasibility_boundary(runs_df, events_df)
    assert len(ev_b) == 25  # All 25 catalogue events evaluated
    assert len(ep_b) == 15  # All 15 regional episodes evaluated

    # Check that failed/missing rows are NOT converted to boundary 0.0x
    failed_ev = ev_b[ev_b["event_id"] == "B2_HW_LAX_20250828"].iloc[0]
    assert failed_ev["status"] == "NON_ESTIMABLE"
    assert np.isnan(failed_ev["heatwave_boundary"])
    assert np.isnan(failed_ev["control_boundary"])

    # Check estimable events
    sfo_ev = ev_b[ev_b["event_id"] == "B2_HW_SFO_20240702"].iloc[0]
    assert sfo_ev["status"] == "ESTIMABLE"
    assert sfo_ev["heatwave_boundary"] == 0.5  # Seed 20261016 feasible at 1.0x, seed 20261017 0.0x -> mean 0.5x
    assert sfo_ev["control_boundary"] == 0.5
    assert sfo_ev["delta_boundary"] == 0.0

    lax_2025 = ev_b[ev_b["event_id"] == "B2_HW_LAX_20250821"].iloc[0]
    assert lax_2025["status"] == "ESTIMABLE"
    assert lax_2025["heatwave_boundary"] == 0.0
    assert lax_2025["control_boundary"] == 0.5  # Seed 20261016 feasible at 1.0x in control
    assert lax_2025["delta_boundary"] == -0.5

    # Check episode level aggregation
    ep_est = ep_b[ep_b["status"] == "ESTIMABLE"]
    assert len(ep_est) == 6
    assert (ep_est["mean_delta_boundary"] <= 0.0).all()


def test_g1_temporal_replication_components(runs_df, events_df):
    """Verify G1 component breakdown: narrow static claim SUPPORTED, full claim LIMITED."""
    ev_agg, ep_agg, assessment = evaluate_g1_temporal_replication(runs_df, events_df)
    assert assessment["hypothesis"] == "G1"
    assert assessment["classification"] == "LIMITED"
    assert assessment["narrow_claim_classification"] == "SUPPORTED"
    assert assessment["independent_episodes_count"] == 6
    assert assessment["positive_episodes_count"] == 6
    assert assessment["years_with_positive_effect"] == 3
    assert assessment["overall_episode_median_violation_hours_diff"] > 0
    assert "tested_feasibility_boundary_summary" in assessment
    assert assessment["tested_feasibility_boundary_summary"]["estimable_episodes"] == 6


def test_g2_geographic_heterogeneity(runs_df, events_df, episodes_df):
    """Verify G2 geographic heterogeneity and episode clustering handling."""
    ev_agg, _, _ = evaluate_g1_temporal_replication(runs_df, events_df)
    summary_df, assessment = evaluate_g2_geographic_heterogeneity(ev_agg, episodes_df)
    assert assessment["hypothesis"] == "G2"
    assert assessment["classification"] == "DESCRIPTIVE_ONLY"
    assert assessment["total_unique_episodes"] == 6
    assert assessment["coastal_episodes_count"] == 4
    assert assessment["inland_episodes_count"] == 3
    assert assessment["shared_carbon_proxy_unidentifiable"] is True


def test_g3_common_support_discriminability(runs_df, events_df, ow_df, overlap_df):
    """Verify G3 common workload support, equal service filtering, and strict inequality."""
    ev_df, ep_df, assessment = evaluate_g3_benchmark_discriminability(runs_df, events_df, ow_df, overlap_df)
    assert assessment["hypothesis"] == "G3"
    assert assessment["equal_service_trios_retained"] == 456
    assert assessment["unequal_service_trios_excluded"] == 888

    # Estimable events under common support: exactly 4
    estimable = ev_df[ev_df["classification"] != "NON_ESTIMABLE"]
    assert len(estimable) == 4
    assert set(estimable["event_id"]) == {
        "B2_HW_LAX_20230908",
        "B2_HW_LAX_20240905",
        "B2_HW_LAX_20250821",
        "B2_HW_SFO_20240702",
    }
    assert (estimable["valid_ordinary_k"] >= 10).all()

    # Verify strict inequality
    for _, r in estimable.iterrows():
        assert r["exceeds_p95"] == (r["heatwave_separation"] > r["ordinary_p95"])

    # Verify programmatic denominator identity: 25 = 4 estimable + 8 non-estimable matrix + 13 absent from matrix
    denoms = assessment["event_denominators"]
    assert denoms["total_catalogue_events"] == 25
    assert denoms["estimable_matrix_events"] == 4
    assert denoms["non_estimable_matrix_events"] == 8
    assert denoms["catalogue_events_absent_from_matrix"] == 13
    assert (
        denoms["total_catalogue_events"]
        == denoms["estimable_matrix_events"]
        + denoms["non_estimable_matrix_events"]
        + denoms["catalogue_events_absent_from_matrix"]
    )

    # Detailed non-estimable breakdown: 1 execution failed, 7 no valid heatwave equal service
    det = denoms["detailed_breakdown"]
    assert det["absent_from_matrix"] == 13
    assert det["present_execution_failed"] == 1
    assert det["present_no_equal_service_support"] == 7
    assert det["present_common_support_k_under_10"] == 0

    # Regional episode summary
    assert len(ep_df) == 15
    assert (ep_df["classification"] == "HEATWAVE_EXCEEDS_P95").sum() == 1
    assert (ep_df["classification"] == "WITHIN_ORDINARY_DISTRIBUTION").sum() == 3
    assert (ep_df["classification"] == "NON_ESTIMABLE").sum() == 11


def test_g4_continuity_gate():
    """Verify G4 continuity gate fails closed without internal allocation traces."""
    res = evaluate_g4_continuity_gate()
    assert res["hypothesis"] == "G4"
    assert res["classification"] == "NON_ESTIMABLE"
    assert res["gate_passed"] is False


def test_g5_bounded_robustness(runs_df, events_df):
    """Verify G5 differentiates 1 executed variant from 9 non-estimable variants."""
    v_df, assessment = evaluate_g5_bounded_robustness(runs_df, events_df)
    assert assessment["hypothesis"] == "G5"
    assert assessment["classification"] == "PARTIALLY_ROBUST — LOW THERMAL CURVE ONLY"
    assert assessment["executed_preregistered_variants_count"] == 1
    assert assessment["missing_preregistered_variants_count"] == 9
    assert "energy_only_facility" not in v_df["variant_id"].values
    assert len(v_df) == 10
    exec_df = v_df[v_df["status_in_phase5"] == "EXECUTED"]
    assert len(exec_df) == 1
    assert exec_df["variant_id"].iloc[0] == "low_thermal_curve"
    non_est = v_df[v_df["status_in_phase5"] == "NOT_EXECUTED"]
    assert len(non_est) == 9
    assert (non_est["classification"] == "NON_ESTIMABLE").all()


def test_oracle_exclusion_from_deployable():
    """Verify oracle is excluded from deployable rankings."""
    assert "oracle_full_thermal_aware" not in DEPLOYABLE_POLICIES
    assert "oracle_full_thermal_aware" not in CORE_DEPLOYABLE_POLICIES


def test_phase6_artifacts_exist_and_hashes():
    """Verify all required Phase 6 output artifacts exist."""
    required_files = [
        "data/v2/results/p12_b2_event_metrics.csv",
        "data/v2/results/p12_b2_episode_metrics.csv",
        "data/v2/results/p12_b2_ordinary_distributions.csv",
        "data/v2/results/p12_b2_g1_g5_assessment.csv",
        "data/v2/results/p12_b2_missingness_audit.csv",
        "data/v2/results/p12_b2_equal_service_audit.csv",
        "data/v2/manifests/p12_b2_phase6_analysis_spec.json",
        "data/v2/manifests/p12_b2_phase6_manifest.json",
        "docs/p12_b2_phase6_completion.md",
        "data/v2/figures/fig4_g1_temporal_replication.png",
        "data/v2/figures/fig5_g2_geographic_heterogeneity.png",
        "data/v2/figures/fig6_g3_heatwave_vs_ordinary_p95.png",
        "data/v2/figures/fig7_g3_ordinary_k_and_overlap.png",
        "data/v2/tables/table1_missingness_flow.csv",
        "data/v2/tables/table11_final_g1_g5_decision.csv",
    ]
    for rf in required_files:
        p = Path(rf)
        assert p.exists(), f"Missing required artifact {rf}"
        assert p.stat().st_size > 0, f"Empty artifact {rf}"
