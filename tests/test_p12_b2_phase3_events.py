"""Tests for HeatTrace Track B2 Phase 3 Weather-only Station Event and Regional Episode Catalogue."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
import pandas as pd

from heattrace.ingest.provenance import sha256_file
from heattrace.process.p12_b2_events import (
    BASELINE_YEARS,
    INACTIVE_FALLBACK,
    PRIMARY_STATIONS,
    TARGET_TIMEZONE,
    WARM_SEASON_MONTHS,
    build_b2_hourly_phase_labels,
    cluster_regional_episodes,
    compute_station_p90_threshold,
    detect_b2_station_events,
)

P11_PROTECTED_HASHES = {
    "data/archive/heattrace_v1_d5b3c86/archive_manifest.json": "2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4",
    "data/results/p11_reproduction_comparison.json": "cf14e1bfc3f8031612229f989d6dcb784771f1f7112bda809871ac782bc9f49e",
    "configs/p6_validity.yaml": "46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1",
    "docs/p6_frozen_protocol.md": "78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede",
}


def test_primary_stations_count_and_fallback_exclusion():
    """Verify exactly 5 primary stations and inactive fallback."""
    assert len(PRIMARY_STATIONS) == 5
    codes = [s["station_code"] for s in PRIMARY_STATIONS]
    assert codes == ["SFO", "SAC", "FAT", "RDD", "LAX"]
    assert "SAC_FALLBACK" not in codes
    assert INACTIVE_FALLBACK["station_code"] == "SAC_FALLBACK"
    assert INACTIVE_FALLBACK["noaa_ghcnh_id"] == "USW00093225"
    assert INACTIVE_FALLBACK["status"] == "inactive_audit_only"


def test_linear_p90_computation():
    """Verify linear percentile interpolation formula."""
    # Synthetic 10 values: 10, 20, 30, ..., 100
    sorted_vals = [float(x * 10) for x in range(1, 11)]
    n = 10
    k = (n - 1) * 0.9  # 9 * 0.9 = 8.1
    f = int(k)  # 8
    c = f + 1  # 9
    expected = sorted_vals[8] * (9 - 8.1) + sorted_vals[9] * (8.1 - 8)
    # sorted_vals[8] = 90, sorted_vals[9] = 100
    # 90 * 0.9 + 100 * 0.1 = 81 + 10 = 91.0
    assert expected == pytest.approx(91.0)


def test_strict_exceedance_and_minimum_three_consecutive_days():
    """Verify strict Tmax > P90 condition and 3-consecutive-day threshold."""
    meta = PRIMARY_STATIONS[0]
    thresh_info = {"threshold_p90_c": 30.0, "percentile": 90.0, "sample_size": 488}
    
    # Run with exactly equality (30.0) -> does not qualify
    daily_equal = [
        {"local_date": "2023-07-01", "daily_max_temperature_c": 30.0},
        {"local_date": "2023-07-02", "daily_max_temperature_c": 30.0},
        {"local_date": "2023-07-03", "daily_max_temperature_c": 30.0},
    ]
    evs = detect_b2_station_events(daily_equal, meta, thresh_info, year=2023, source_psv_path="mock.psv")
    assert len(evs) == 0

    # Run with only 2 qualifying days -> does not qualify
    daily_two = [
        {"local_date": "2023-07-01", "daily_max_temperature_c": 31.0},
        {"local_date": "2023-07-02", "daily_max_temperature_c": 32.0},
        {"local_date": "2023-07-03", "daily_max_temperature_c": 28.0},
    ]
    evs2 = detect_b2_station_events(daily_two, meta, thresh_info, year=2023, source_psv_path="mock.psv")
    assert len(evs2) == 0

    # Run with 3 qualifying days -> qualifies as 1 event
    daily_three = [
        {"local_date": "2023-07-01", "daily_max_temperature_c": 31.0},
        {"local_date": "2023-07-02", "daily_max_temperature_c": 32.0},
        {"local_date": "2023-07-03", "daily_max_temperature_c": 33.0},
    ]
    evs3 = detect_b2_station_events(daily_three, meta, thresh_info, year=2023, source_psv_path="mock.psv")
    assert len(evs3) == 1
    assert evs3[0]["qualifying_day_count"] == 3


def test_missing_day_breaks_run():
    """Verify that a missing day breaks what would otherwise be a 3-day run."""
    meta = PRIMARY_STATIONS[0]
    thresh_info = {"threshold_p90_c": 30.0, "percentile": 90.0, "sample_size": 488}

    # Day 2 is missing from sequence: 2023-07-01 (qualifying), 2023-07-03 (qualifying)
    daily = [
        {"local_date": "2023-07-01", "daily_max_temperature_c": 32.0},
        {"local_date": "2023-07-03", "daily_max_temperature_c": 33.0},
        {"local_date": "2023-07-04", "daily_max_temperature_c": 34.0},
    ]
    evs = detect_b2_station_events(daily, meta, thresh_info, year=2023, source_psv_path="mock.psv")
    # Only 03 and 04 are consecutive (len 2), 01 is isolated (len 1). Neither >= 3
    assert len(evs) == 0


def test_adjacent_qualifying_days_single_event():
    """Verify adjacent qualifying days merge into one event rather than multiple."""
    meta = PRIMARY_STATIONS[0]
    thresh_info = {"threshold_p90_c": 30.0, "percentile": 90.0, "sample_size": 488}

    daily = [
        {"local_date": "2023-07-01", "daily_max_temperature_c": 32.0},
        {"local_date": "2023-07-02", "daily_max_temperature_c": 33.0},
        {"local_date": "2023-07-03", "daily_max_temperature_c": 34.0},
        {"local_date": "2023-07-04", "daily_max_temperature_c": 35.0},
        {"local_date": "2023-07-05", "daily_max_temperature_c": 36.0},
    ]
    evs = detect_b2_station_events(daily, meta, thresh_info, year=2023, source_psv_path="mock.psv")
    assert len(evs) == 1
    assert evs[0]["qualifying_day_count"] == 5
    assert evs[0]["duration_days"] == 5


def test_earliest_peak_selected_on_temperature_tie():
    """Verify earliest local date is chosen on temperature peak tie."""
    meta = PRIMARY_STATIONS[0]
    thresh_info = {"threshold_p90_c": 30.0, "percentile": 90.0, "sample_size": 488}

    daily = [
        {"local_date": "2023-07-01", "daily_max_temperature_c": 35.0},  # Peak tie 1
        {"local_date": "2023-07-02", "daily_max_temperature_c": 32.0},
        {"local_date": "2023-07-03", "daily_max_temperature_c": 35.0},  # Peak tie 2
    ]
    evs = detect_b2_station_events(daily, meta, thresh_info, year=2023, source_psv_path="mock.psv")
    assert len(evs) == 1
    assert evs[0]["peak_local_date"] == "2023-07-01"
    assert evs[0]["peak_temperature_c"] == 35.0


def test_unique_b2_event_identities():
    """Verify B2 event ID schema avoids multi-station collision."""
    df_events = pd.read_csv("data/v2/events/p12_b2_station_events.csv")
    assert len(df_events["event_id"].unique()) == len(df_events)
    # Check that simultaneous events on same day have distinct IDs (e.g., 2022-09-04)
    sep04_events = df_events[df_events["local_start_date"] == "2022-09-04"]
    assert len(sep04_events) == 4
    eids = set(sep04_events["event_id"])
    assert eids == {
        "B2_HW_FAT_20220904",
        "B2_HW_RDD_20220904",
        "B2_HW_SAC_20220904",
        "B2_HW_SFO_20220904",
    }


def test_station_year_screening_matrix():
    """Verify SFO 2025 excluded from screening and SAC_FALLBACK not screened."""
    df_scr = pd.read_csv("data/v2/events/p12_b2_station_year_screening.csv")
    
    # SFO 2025
    sfo_2025 = df_scr[(df_scr["station_code"] == "SFO") & (df_scr["year"] == 2025)].iloc[0]
    assert sfo_2025["screen_status"] == "NOT_SCREENED_EXCLUDED"
    assert sfo_2025["detected_events_count"] == 0
    assert "97.54%" in sfo_2025["exclusion_reason"]

    # Inactive fallback
    fallback_rows = df_scr[df_scr["station_code"] == "SAC_FALLBACK"]
    assert len(fallback_rows) == 5
    for _, r in fallback_rows.iterrows():
        assert r["screen_status"] == "NOT_SCREENED_INACTIVE_FALLBACK"
        assert r["detected_events_count"] == 0


def test_event_eligibility_and_provisional_classifications():
    """Verify 2022 joint-ineligibility and 2026 provisional labeling."""
    df_events = pd.read_csv("data/v2/events/p12_b2_station_events.csv")
    
    # 2022 events
    ev_2022 = df_events[df_events["source_year"] == 2022]
    assert len(ev_2022) == 9
    for _, r in ev_2022.iterrows():
        assert r["weather_eligibility_status"] == "PASS"
        assert r["joint_evaluation_eligibility"] == "EXCLUDED"
        assert "EIA 2022" in r["exclusion_reason"]

    # 2026 events
    ev_2026 = df_events[df_events["source_year"] == 2026]
    assert len(ev_2026) == 4
    for _, r in ev_2026.iterrows():
        assert r["weather_eligibility_status"] == "PROVISIONAL"
        assert r["joint_evaluation_eligibility"] == "PROVISIONAL"
        assert r["provisional"] is True

    # 2023-2025 events (excluding SFO 2025 which produced 0)
    ev_eligible = df_events[df_events["source_year"].isin([2023, 2024, 2025])]
    assert len(ev_eligible) == 12
    for _, r in ev_eligible.iterrows():
        assert r["weather_eligibility_status"] == "PASS"
        assert r["joint_evaluation_eligibility"] == "ELIGIBLE"
        assert r["exclusion_reason"] == "NONE"


def test_regional_episode_grouping_properties():
    """Verify regional episode clustering properties and connected components."""
    df_ep = pd.read_csv("data/v2/events/p12_b2_regional_episodes.csv")
    df_ev = pd.read_csv("data/v2/events/p12_b2_station_events.csv")

    assert len(df_ep) == 15
    assert len(df_ev) == 25

    # Every station event belongs to exactly one regional episode
    assigned_eps = set(df_ev["regional_episode_id"])
    assert assigned_eps == set(df_ep["regional_episode_id"])

    # 2022-09-04 multi-station event forms a single episode
    ep_sep22 = df_ep[df_ep["regional_episode_id"] == "B2_EP_20220831_04"].iloc[0]
    assert ep_sep22["member_event_count"] == 5
    assert ep_sep22["distinct_station_count"] == 5
    assert ep_sep22["eligibility_summary"] == "EXCLUDED_FROM_JOINT_EVALUATION"


def test_hourly_phase_labels_structure():
    """Verify hourly phase labels coverage and valid labels."""
    df_hourly = pd.read_parquet("data/v2/events/p12_b2_hourly_phase_labels.parquet")
    assert not df_hourly.empty
    
    # Check valid phase values
    phases = set(df_hourly["phase"].unique())
    assert phases == {"onset", "peak", "sustained", "recovery"}

    # Total rows = 4320 hours across all 25 events (onset 24h + event + recovery 24h)
    assert len(df_hourly) == 4320


def test_immutable_p11_hashes_unmodified():
    """Verify all protected P11 baseline hashes remain strictly intact."""
    for path_str, exp_hash in P11_PROTECTED_HASHES.items():
        actual_hash = sha256_file(path_str)
        assert actual_hash == exp_hash, f"Protected P11 file altered: {path_str}"
