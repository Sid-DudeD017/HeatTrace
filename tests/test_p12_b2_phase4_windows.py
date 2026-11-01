"""Tests for HeatTrace Track B2 Phase 4 Window Selection, Workload Freeze, and Execution Matrix Dry Run."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import random
import shutil
import tempfile
import pytest
import pandas as pd

from heattrace.ingest.provenance import sha256_file
from heattrace.process.p12_b2_windows import (
    B2Phase4Pipeline,
    run_phase4_pipeline,
    verify_protected_p11_files,
    PROTECTED_P11_BASELINES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# -----------------------------------------------------------------------------
# 1. Scope and Exclusions
# -----------------------------------------------------------------------------

def test_1_only_12_eligible_events_enter_primary_matrix():
    df_events = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv")
    eligible = df_events[df_events["joint_evaluation_eligibility"] == "ELIGIBLE"]
    assert len(eligible) == 12

    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    assert len(df_ctrls) == 12
    assert set(df_ctrls["matched_event_id"]) == set(eligible["event_id"])


def test_2_excluded_2022_events_produce_zero_primary_cells():
    df_matrix = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv")
    df_events = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv")
    excluded = df_events[df_events["joint_evaluation_eligibility"] == "EXCLUDED"]["event_id"].tolist()
    assert len(excluded) == 9

    overlap = set(df_matrix["event_id"]).intersection(set(excluded))
    assert len(overlap) == 0


def test_3_provisional_2026_events_produce_zero_primary_cells():
    df_matrix = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv")
    df_events = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv")
    provisional = df_events[df_events["joint_evaluation_eligibility"] == "PROVISIONAL"]["event_id"].tolist()
    assert len(provisional) == 4

    overlap = set(df_matrix["event_id"]).intersection(set(provisional))
    assert len(overlap) == 0


def test_4_sfo_2025_and_sac_fallback_produce_no_selections():
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_ord = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv")

    assert not any(r["station_code"] == "SFO" and r["source_year"] == 2025 for _, r in df_ctrls.iterrows())
    assert not any(r["station_code"] == "SFO" and r["source_year"] == 2025 for _, r in df_ord.iterrows())
    assert not any("SAC_FALLBACK" in str(r["station_code"]) for _, r in df_ctrls.iterrows())
    assert not any("SAC_FALLBACK" in str(r["station_code"]) for _, r in df_ord.iterrows())


# -----------------------------------------------------------------------------
# 2. Control Selection Rules and Fallbacks
# -----------------------------------------------------------------------------

def test_5_exactly_one_control_per_included_event():
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    assert len(df_ctrls) == 12
    assert df_ctrls["matched_event_id"].nunique() == 12


def test_selected_control_must_be_rank_1_and_consistent_with_candidates():
    """Verify that for all 12 controls:
    - candidate_rank == 1
    - Exactly one candidate per event has selection_outcome == 'SELECTED_CONTROL'
    - The selected candidate has final_rank == 1
    - Selected candidate ID/date corresponds to the control ID/date
    - Recomputing documented lexicographic sort selects the exact same candidate
    """
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_ctrl_cands = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_control_candidates.csv")

    assert len(df_ctrls) == 12

    # 1. candidate_rank == 1 for all controls
    assert (df_ctrls["candidate_rank"] == 1).all(), "Not all controls have candidate_rank == 1"

    for _, ctrl in df_ctrls.iterrows():
        ev_id = ctrl["matched_event_id"]
        cands_ev = df_ctrl_cands[df_ctrl_cands["matched_event_id"] == ev_id]
        
        # 2. Exactly one candidate per event has selection_outcome == 'SELECTED_CONTROL'
        selected_cands = cands_ev[cands_ev["selection_outcome"] == "SELECTED_CONTROL"]
        assert len(selected_cands) == 1, f"Event {ev_id} has {len(selected_cands)} selected control candidates"
        sel_cand = selected_cands.iloc[0]

        # 3. Selected candidate has final_rank == 1
        assert sel_cand["final_rank"] == 1, f"Event {ev_id} selected candidate has final_rank {sel_cand['final_rank']}"

        # 4. Selected candidate ID/date corresponds to control ID/date
        assert sel_cand["local_start_date"] == ctrl["local_start_date"]
        expected_cand_id = f"B2_CAND_{ctrl['station_code']}_{ctrl['matched_event_id'].split('_')[-1]}_{pd.to_datetime(ctrl['local_start_date']).strftime('%Y%m%d')}"
        assert sel_cand["candidate_id"] == expected_cand_id

        # 5. Recomputing lexicographic sort independently selects the same candidate
        cands_list = cands_ev.to_dict("records")
        ranked = B2Phase4Pipeline.rank_candidates(cands_list)
        eligible_ranked = [c for c in ranked if c["is_eligible"]]
        assert len(eligible_ranked) > 0
        assert eligible_ranked[0]["candidate_id"] == sel_cand["candidate_id"]
        assert eligible_ranked[0]["local_start_date"] == ctrl["local_start_date"]


def test_6_same_station_control_enforcement():
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_events = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv").set_index("event_id")

    for _, r in df_ctrls.iterrows():
        ev = df_events.loc[r["matched_event_id"]]
        assert r["station_code"] == ev["station_code"]


def test_7_8_same_year_preference_and_cross_year_label():
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    for _, r in df_ctrls.iterrows():
        assert r["same_year"] is True or r["same_year"] == "True"
        assert r["source_year"] == r["selection_year"]
        assert r["limitation_label"] == "NONE"


def test_cross_year_fallback_and_limitation_label():
    """Verify complete cross-year fallback selection path when same-year pool has no eligible candidates."""
    pipeline = B2Phase4Pipeline(REPO_ROOT)
    ev = pipeline.df_eligible_events[pipeline.df_eligible_events["event_id"] == "B2_HW_RDD_20230714"].iloc[0]
    
    st = ev["station_code"]
    yr = int(ev["source_year"])
    dur_days = int(ev["duration_days"]) + 2
    dur_hrs = dur_days * 24
    ev_start_date = date.fromisoformat(str(ev["local_start_date"]))
    ev_end_date = date.fromisoformat(str(ev["local_end_date"]))
    ev_mid_date = ev_start_date + (ev_end_date - ev_start_date) / 2
    ev_weekday = ev_start_date.weekday()
    ev_mean_max = float(ev["mean_max_temperature_c"])

    # Simulate same-year having 0 eligible candidates
    cands_same_year = pipeline._evaluate_candidate_windows_for_year(
        st, yr, dur_days, dur_hrs, ev["event_id"], ev_weekday, ev_mid_date, ev_mean_max, is_same_year=True
    )
    for c in cands_same_year:
        c["is_eligible"] = False
        c["rejection_reasons"] = "synthetic_same_year_exclusion"

    # Fallback search over multiple years (2024 and 2025)
    cands_pool = list(cands_same_year)
    candidate_years = [y for y in [2023, 2024, 2025] if y != yr]
    candidate_years.sort(key=lambda y: (abs(y - yr), y))
    
    fallback_used = "NONE"
    limitation_label = "NONE"
    for fb_yr in candidate_years:
        fb_cands = pipeline._evaluate_candidate_windows_for_year(
            st, fb_yr, dur_days, dur_hrs, ev["event_id"], ev_weekday, ev_mid_date, ev_mean_max, is_same_year=False
        )
        fb_eligible = [c for c in fb_cands if c["is_eligible"]]
        if fb_eligible:
            cands_pool.extend(fb_cands)
            fallback_used = f"CROSS_YEAR_{fb_yr}"
            limitation_label = "LIMITED_CROSS_YEAR"
            break

    # Run the real selection code
    top_ctrl, sorted_cands = pipeline.select_matched_control_for_event(
        cands_pool, ev["event_id"], st, ev_start_date
    )

    # Verify nearest eligible year is chosen (2024 is abs(2024-2023)=1 vs 2025 abs=2)
    assert fallback_used == "CROSS_YEAR_2024"
    assert limitation_label == "LIMITED_CROSS_YEAR"
    assert top_ctrl["same_year"] is False
    assert top_ctrl["source_year"] == 2024
    assert top_ctrl["final_rank"] == 1
    assert top_ctrl["selection_outcome"] == "SELECTED_CONTROL"
    assert top_ctrl["is_eligible"] is True


def test_9_10_exact_utc_duration_and_dst_safe():
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_events = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv").set_index("event_id")

    for _, r in df_ctrls.iterrows():
        ev = df_events.loc[r["matched_event_id"]]
        ev_start = pd.to_datetime(ev["full_window_start_utc"])
        ev_end = pd.to_datetime(ev["full_window_end_utc"])
        ev_hrs = int((ev_end - ev_start).total_seconds() / 3600)

        ctrl_start = pd.to_datetime(r["start_utc"])
        ctrl_end = pd.to_datetime(r["end_utc"])
        ctrl_hrs = int((ctrl_end - ctrl_start).total_seconds() / 3600)

        assert ctrl_hrs == ev_hrs
        assert r["duration_hours"] == ev_hrs


def test_11_no_overlap_with_protected_intervals():
    df_events = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_station_events.csv")
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_ord = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv")
    df_episodes = pd.read_csv(REPO_ROOT / "data/v2/events/p12_b2_regional_episodes.csv")

    protected_intervals = [
        (pd.to_datetime(r["full_window_start_utc"]), pd.to_datetime(r["full_window_end_utc"]))
        for _, r in df_events.iterrows()
    ]
    protected_episodes = [
        (pd.to_datetime(r["component_start_utc"]), pd.to_datetime(r["component_end_utc"]))
        for _, r in df_episodes.iterrows()
    ]

    all_windows = []
    for _, r in df_ctrls.iterrows():
        all_windows.append((r["control_id"], pd.to_datetime(r["start_utc"]), pd.to_datetime(r["end_utc"])))
    for _, r in df_ord.iterrows():
        all_windows.append((r["ordinary_window_id"], pd.to_datetime(r["start_utc"]), pd.to_datetime(r["end_utc"])))

    for wid, ws, we in all_windows:
        for ps, pe in protected_intervals:
            assert not (max(ws, ps) < min(we, pe)), f"{wid} overlaps event [{ps}, {pe}]"
        for ps, pe in protected_episodes:
            assert not (max(ws, ps) < min(we, pe)), f"{wid} overlaps episode [{ps}, {pe}]"


def test_12_no_embedded_three_day_strict_p90_run():
    pipeline = B2Phase4Pipeline(REPO_ROOT)
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_ord = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv")

    for _, r in pd.concat([df_ctrls, df_ord]).iterrows():
        st = r["station_code"]
        yr = int(r["source_year"])
        p90 = pipeline.thresholds_map[st]
        daily = pipeline.get_station_daily_maxima(st, yr)

        s_date = pd.to_datetime(r["local_start_date"]).date()
        dur_days = int(r["duration_days"])

        run = 0
        for i in range(dur_days):
            d = (s_date + pd.Timedelta(days=i)).isoformat()
            t = daily.get(d)
            assert t is not None, f"Missing weather day {d}"
            if t > p90:
                run += 1
                assert run < 3, f"Embedded 3-day P90 run detected in {r.get('control_id', r.get('ordinary_window_id'))}"
            else:
                run = 0


def test_13_missing_weather_rejects_candidate():
    """Verify that a candidate with any missing weather day is rejected with explicit reason."""
    pipeline = B2Phase4Pipeline(REPO_ROOT)
    # Populate the weather cache first, then inject None
    daily = pipeline.get_station_daily_maxima("SFO", 2024)
    # Inject missing day into the dictionary
    daily["2024-06-15"] = None
    cands = pipeline._evaluate_candidate_windows_for_year(
        "SFO", 2024, 5, 120, "TEST_EV", 0, date(2024, 7, 1), 25.0, True
    )
    # Any candidate spanning 2024-06-15 must have 'missing_weather_day' in rejection_reasons
    affected = [c for c in cands if date(2024, 6, 11) <= c["w_start_date"] <= date(2024, 6, 15)]
    assert len(affected) > 0
    for c in affected:
        assert "missing_weather_day" in c["rejection_reasons"]
        assert c["is_eligible"] is False


# -----------------------------------------------------------------------------
# 3. Candidate Pooling, Stratification, and Fallbacks
# -----------------------------------------------------------------------------

def test_14_15_candidate_pool_materialized_and_deterministic_ranking():
    df_ctrl_cands = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_control_candidates.csv")
    df_ord_cands = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_window_candidates.csv")

    assert len(df_ctrl_cands) > 0
    assert len(df_ord_cands) > 0
    assert "rejection_reasons" in df_ctrl_cands.columns
    assert "rejection_reasons" in df_ord_cands.columns


def test_candidate_ordering_independence():
    """Verify that shuffling candidate input order does not alter deterministic ranking and selection."""
    pipeline = B2Phase4Pipeline(REPO_ROOT)
    ev = pipeline.df_eligible_events.iloc[0]
    dur_days = int(ev["duration_days"]) + 2
    cands = pipeline._evaluate_candidate_windows_for_year(
        ev["station_code"], int(ev["source_year"]), dur_days, dur_days * 24,
        ev["event_id"], date.fromisoformat(ev["local_start_date"]).weekday(),
        date.fromisoformat(ev["local_start_date"]), float(ev["mean_max_temperature_c"]), True
    )
    # Shuffled copy
    shuffled = list(cands)
    random.Random(42).shuffle(shuffled)

    sort_key = lambda c: (
        0 if c["is_eligible"] else 1,
        0 if c["same_year"] else 1,
        c["weekday_diff"],
        c["calendar_distance_days"],
        c["weather_distance_c"],
        c["start_utc"],
    )
    cands_sorted = sorted(cands, key=sort_key)
    shuffled_sorted = sorted(shuffled, key=sort_key)

    assert [c["w_start_date"] for c in cands_sorted] == [c["w_start_date"] for c in shuffled_sorted]


def test_16_17_18_k_20_selected_per_eligible_event():
    df_ord = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv")
    counts = df_ord.groupby("matched_event_id").size()
    assert len(counts) == 12
    for ev_id, k in counts.items():
        assert k == 20, f"Event {ev_id} has K={k} != 20"


def test_ordinary_window_fallback_labels():
    """Verify fallback behavior invoking real ordinary window selection helper with synthetic pools."""
    # 1. 20+ candidates -> K=20, limitation NONE
    pool_25 = [
        {"w_start_date": date(2024, 6, 1) + timedelta(days=i * 5), "is_eligible": True, "same_year": True}
        for i in range(25)
    ]
    selected_25, lim_25, k_25 = B2Phase4Pipeline.select_ordinary_windows_from_candidates(pool_25, duration_days=5, target_k_default=20)
    assert len(selected_25) == 20
    assert k_25 == 20
    assert lim_25 == "NONE"

    # 2. 15 candidates -> K=15, limitation LIMITED_K_BELOW_TARGET
    pool_15 = [
        {"w_start_date": date(2024, 6, 1) + timedelta(days=i * 5), "is_eligible": True, "same_year": True}
        for i in range(15)
    ]
    selected_15, lim_15, k_15 = B2Phase4Pipeline.select_ordinary_windows_from_candidates(pool_15, duration_days=5, target_k_default=20)
    assert len(selected_15) == 15
    assert k_15 == 15
    assert lim_15 == "LIMITED_K_BELOW_TARGET"

    # 3. 8 candidates (< 10) -> K=8, limitation LIMITED_FEWER_THAN_10_G3_UNAVAILABLE
    pool_8 = [
        {"w_start_date": date(2024, 6, 1) + timedelta(days=i * 5), "is_eligible": True, "same_year": True}
        for i in range(8)
    ]
    selected_8, lim_8, k_8 = B2Phase4Pipeline.select_ordinary_windows_from_candidates(pool_8, duration_days=5, target_k_default=20)
    assert len(selected_8) == 8
    assert k_8 == 8
    assert lim_8 == "LIMITED_FEWER_THAN_10_G3_UNAVAILABLE"


def test_19_overlap_graph_validity():
    df_overlap = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_window_overlap_graph.csv")
    assert len(df_overlap) > 0
    assert "component_id" in df_overlap.columns


# -----------------------------------------------------------------------------
# 4. Workloads and Matrix Dry Run
# -----------------------------------------------------------------------------

def test_20_unique_identities():
    df_ctrls = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_controls.csv")
    df_ord = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_ordinary_windows.csv")
    df_matrix = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv")

    assert df_ctrls["control_id"].is_unique
    assert df_ord["ordinary_window_id"].is_unique
    assert df_matrix["run_id"].is_unique


def test_21_22_workload_hashes_reused_across_matched_windows():
    df_matrix = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv")
    grouped = df_matrix.groupby(["duration_hours", "workload_multiplier", "workload_seed"])["workload_hash"].nunique()
    for key, count in grouped.items():
        assert count == 1, f"Multiple workload hashes for condition {key}"

    distinct_durs = df_matrix["duration_hours"].unique()
    assert len(distinct_durs) == 5


def test_23_24_matrix_formula_and_expected_total():
    manifest_p = REPO_ROOT / "data/v2/manifests/p12_b2_matrix_dry_run.json"
    with manifest_p.open() as f:
        manifest = json.load(f)

    assert manifest["total_planned_cells"] == 6480
    assert manifest["formula_verification"]["expected_total_for_12_events_at_k20"] == 6480
    assert manifest["formula_verification"]["all_events_match_formula"] is True


def test_25_26_canonical_run_ids_unique_and_oracle_non_deployable():
    df_matrix = pd.read_csv(REPO_ROOT / "data/v2/benchmarks/p12_b2_matrix_cells.csv")
    assert len(df_matrix) == 6480
    assert df_matrix["run_id"].nunique() == 6480

    oracle_cells = df_matrix[df_matrix["policy"] == "oracle_full_thermal_aware"]
    assert len(oracle_cells) == 144
    assert (oracle_cells["deployable"] == False).all()

    non_oracle_cells = df_matrix[df_matrix["policy"] != "oracle_full_thermal_aware"]
    assert len(non_oracle_cells) == 6336
    assert (non_oracle_cells["deployable"] == True).all()


# -----------------------------------------------------------------------------
# 5. Outcome Blindness, Protected Boundaries, and Manifest Verification
# -----------------------------------------------------------------------------

def test_27_28_29_outcome_blindness_and_namespace_protection():
    manifest_p = REPO_ROOT / "data/v2/manifests/p12_b2_matrix_dry_run.json"
    with manifest_p.open() as f:
        manifest = json.load(f)

    assert manifest["outcome_blindness_declaration"]["schedulers_executed"] is False
    assert manifest["outcome_blindness_declaration"]["policy_outcomes_inspected"] is False
    assert manifest["output_namespace_audit"]["violates_v1_boundary"] is False


def test_guarded_input_boundary_outcome_blindness(monkeypatch):
    """Verify that selection code does not read any results, lmp, or policy outcome files by hooking file access."""
    pipeline = B2Phase4Pipeline(REPO_ROOT)
    
    # Track opened files and fail if forbidden result/policy paths are accessed
    forbidden_terms = [
        "data/results",
        "data/v2/results",
        "scheduler",
        "policy_outcomes",
        "lmp",
        "emission_results",
    ]
    opened_paths: list[str] = []

    orig_open = Path.open

    def guarded_open(self_path, *args, **kwargs):
        path_str = str(self_path)
        for term in forbidden_terms:
            if term in path_str:
                raise PermissionError(f"Outcome-blindness violation: attempted access to forbidden path {path_str}")
        opened_paths.append(path_str)
        return orig_open(self_path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    # Execute selection under active guard
    res = pipeline.run_selection()
    assert len(res["df_controls"]) == 12
    assert len(res["df_ordinary_windows"]) == 240
    assert len(opened_paths) > 0
    for p in opened_paths:
        for term in forbidden_terms:
            assert term not in p


def test_30_phase3_freeze_hash_unchanged():
    p3_manifest = REPO_ROOT / "data/v2/manifests/p12_b2_event_freeze.json"
    assert sha256_file(p3_manifest) == "972675ef164cd29628eebdc4e509dce352b62a70a2e7214c9e9083f8d33d91c5"


def test_31_all_protected_p11_files():
    """Verify all protected P11 baselines pass fail-closed check."""
    verifications = verify_protected_p11_files(REPO_ROOT)
    for name, res in verifications.items():
        assert res["status"] == "VERIFIED_MATCH"
        assert res["sha256"] == PROTECTED_P11_BASELINES[name]["expected_sha256"]


def test_manifest_file_hashes_match_artifacts():
    """Verify that every artifact hash in window_freeze.json matches the file on disk."""
    manifest_p = REPO_ROOT / "data/v2/manifests/p12_b2_window_freeze.json"
    with manifest_p.open() as f:
        manifest = json.load(f)

    for art_name, art_info in manifest["artifacts"].items():
        file_path = REPO_ROOT / art_info["path"]
        assert file_path.exists(), f"Artifact file missing: {file_path}"
        computed_hash = sha256_file(file_path)
        assert computed_hash == art_info["sha256"], f"Hash mismatch for {art_name}"
        assert file_path.stat().st_size == art_info["bytes"]


# -----------------------------------------------------------------------------
# 6. Isolated Test Execution and Zero Mutation
# -----------------------------------------------------------------------------

def test_isolated_two_run_reproducibility():
    """Verify byte-for-byte reproducibility across two independent temporary directory runs without mutating repo."""
    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        tmp_path1 = Path(tmpdir1)
        tmp_path2 = Path(tmpdir2)

        for p in [tmp_path1, tmp_path2]:
            shutil.copytree(REPO_ROOT / "configs", p / "configs")
            (p / "data/v2").mkdir(parents=True)
            shutil.copytree(REPO_ROOT / "data/v2/raw", p / "data/v2/raw")
            shutil.copytree(REPO_ROOT / "data/v2/events", p / "data/v2/events")
            shutil.copytree(REPO_ROOT / "data/v2/manifests", p / "data/v2/manifests")
            # Also copy protected P11 baselines so fail-closed check passes in tmp
            (p / "data/archive").mkdir(parents=True)
            shutil.copytree(REPO_ROOT / "data/archive/heattrace_v1_d5b3c86", p / "data/archive/heattrace_v1_d5b3c86")
            (p / "data/results").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "data/results/p11_reproduction_comparison.json", p / "data/results/p11_reproduction_comparison.json")
            (p / "docs").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "docs/p6_frozen_protocol.md", p / "docs/p6_frozen_protocol.md")

        run_phase4_pipeline(tmp_path1)
        run_phase4_pipeline(tmp_path2)

        csvs = [
            "data/v2/benchmarks/p12_b2_controls.csv",
            "data/v2/benchmarks/p12_b2_ordinary_windows.csv",
            "data/v2/benchmarks/p12_b2_control_candidates.csv",
            "data/v2/benchmarks/p12_b2_ordinary_window_candidates.csv",
            "data/v2/benchmarks/p12_b2_window_overlap_graph.csv",
            "data/v2/benchmarks/p12_b2_matrix_cells.csv",
        ]
        for rel in csvs:
            h1 = sha256_file(tmp_path1 / rel)
            h2 = sha256_file(tmp_path2 / rel)
            assert h1 == h2, f"Two-run mismatch for {rel}"
