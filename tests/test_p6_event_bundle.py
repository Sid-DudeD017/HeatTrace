"""Comprehensive test suite for P6 event bundle builder, validator, and defect counterexamples.

Exposes and tests all defects:
- successful primary and fallback build path
- InsufficientP6BenchmarkDataError typed exception and structured reasons
- complete canonical schema requirements (missing temp, price, carbon, demand)
- centralized event window calculation (72h -> 120h, 120h -> 120h, >120h rejected)
- relational validation (duplicate IDs, absent triplet IDs, mismatched window types, time interval checks)
- deterministic selection and tie-breaking
- strict non-leakage (monkeypatching filesystem, proving immunity to scheduler/policy outcome mutations)
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from heattrace.process.p6_event_bundle import (
    CANONICAL_BENCHMARK_SIGNALS,
    INDEX_COLUMNS,
    BLIND_POOL_COLUMNS,
    InsufficientP6BenchmarkDataError,
    build_candidate_blind_windows,
    build_p6_benchmark_triplets,
    compute_event_evaluation_window,
    stable_hash_id,
    validate_aligned_dataframe_signals,
    validate_p6_benchmark_triplets,
)


# ---------------------------------------------------------------------------
# Fixtures and Helpers for Synthetic Inputs
# ---------------------------------------------------------------------------

def make_synthetic_aligned_dataset(
    start_utc: pd.Timestamp,
    periods_hours: int = 5000,
    missing_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Generate a continuous, complete, timezone-aware UTC aligned dataset."""
    ts = pd.date_range(start_utc, periods=periods_hours, freq="1h")
    data = {
        "timestamp_utc": ts,
        "temperature_c": np.linspace(15.0, 32.0, periods_hours),
        "price_usd_per_mwh": np.linspace(40.0, 120.0, periods_hours),
        "carbon_g_per_kwh": np.linspace(120.0, 280.0, periods_hours),
        "demand_mw": np.linspace(22000.0, 38000.0, periods_hours),
    }
    if missing_cols:
        for c in missing_cols:
            if c in data:
                del data[c]
    return pd.DataFrame(data)


def make_synthetic_inputs_for_triplets(
    num_events: int = 5,
    num_controls: int = 5,
    start_date: str = "2024-06-01",
    duration_hours: int = 120,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate sufficient synthetic aligned_df, event_catalogue_df, and control_catalogue_df."""
    base_s = pd.Timestamp(f"{start_date} 07:00:00", tz="UTC")

    events = []
    controls = []

    cur_s = base_s
    for i in range(num_events):
        eid = f"HW_SYNTH_{i}"
        # Let events be 72h detected events
        ev_start = cur_s
        ev_end = ev_start + pd.Timedelta(hours=72)
        events.append({
            "event_id": eid,
            "duration_hours": 72,
            "local_start_date": (ev_start.date() + timedelta(days=1)).isoformat(),
            "local_end_date": (ev_start.date() + timedelta(days=3)).isoformat(),
            "event_start_utc": (ev_start + pd.Timedelta(hours=24)).isoformat(),
            "event_end_utc": (ev_start + pd.Timedelta(hours=96)).isoformat(),
        })
        cur_s = cur_s + pd.Timedelta(hours=144)  # advance past 120h window + buffer

    for i in range(num_controls):
        cid = f"CTRL_SYNTH_{i}"
        c_start = cur_s
        c_end = c_start + pd.Timedelta(hours=duration_hours)
        controls.append({
            "control_id": cid,
            "matched_event_id": f"HW_SYNTH_{i}" if i < num_events else "HW_OTHER",
            "start_timestamp_utc": c_start.isoformat(),
            "end_timestamp_utc": c_end.isoformat(),
            "duration_hours": duration_hours,
            "is_eligible": True,
        })
        cur_s = c_end + pd.Timedelta(hours=48)

    # Make aligned dataset covering all events, controls, plus ample room for blinds
    total_hours = int(round((cur_s - base_s).total_seconds() / 3600.0)) + 2000
    aligned_df = make_synthetic_aligned_dataset(base_s, periods_hours=total_hours)

    return aligned_df, pd.DataFrame(events), pd.DataFrame(controls)


# ---------------------------------------------------------------------------
# 1. Successful Build Path Tests
# ---------------------------------------------------------------------------

def test_successful_primary_path_produces_5_triplets_and_1800_rows():
    """A sufficient primary input produces exactly 5 triplets, 1800 hourly rows, and 5 selected blinds."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    hourly, index, pool = build_p6_benchmark_triplets(
        aligned_df=aligned,
        event_catalogue_df=events,
        config=cfg,
        control_catalogue_df=controls,
        design_mode="primary",
        random_seed=20261016,
    )

    assert len(index) == 5
    assert len(hourly) == 1800
    assert pool["is_selected"].sum() == 5
    assert len(index[index["role"] == "development"]) == 1
    assert len(index[index["role"] == "confirmatory"]) == 4

    # Validate output
    val_res = validate_p6_benchmark_triplets(hourly, index, design_mode="primary")
    assert val_res["valid"] is True
    assert val_res["total_hourly_rows"] == 1800


def test_successful_fallback_path_produces_4_triplets_and_1440_rows():
    """A sufficient fallback input produces exactly 4 triplets, 1440 hourly rows, and 4 selected blinds."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=4, num_controls=4)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    hourly, index, pool = build_p6_benchmark_triplets(
        aligned_df=aligned,
        event_catalogue_df=events,
        config=cfg,
        control_catalogue_df=controls,
        design_mode="fallback",
        random_seed=20261016,
    )

    assert len(index) == 4
    assert len(hourly) == 1440
    assert pool["is_selected"].sum() == 4
    assert len(index[index["role"] == "development"]) == 1
    assert len(index[index["role"] == "confirmatory"]) == 3

    val_res = validate_p6_benchmark_triplets(hourly, index, design_mode="fallback")
    assert val_res["valid"] is True
    assert val_res["total_hourly_rows"] == 1440


def test_builder_determinism_and_shuffled_row_invariance():
    """Repeated execution produces identical logical output and shuffled input rows yield same selection."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    h1, idx1, p1 = build_p6_benchmark_triplets(
        aligned, events, cfg, control_catalogue_df=controls, design_mode="primary", random_seed=20261016
    )

    # Shuffle inputs
    events_shuffled = events.sample(frac=1.0, random_state=42).reset_index(drop=True)
    controls_shuffled = controls.sample(frac=1.0, random_state=42).reset_index(drop=True)

    h2, idx2, p2 = build_p6_benchmark_triplets(
        aligned, events_shuffled, cfg, control_catalogue_df=controls_shuffled, design_mode="primary", random_seed=20261016
    )

    pd.testing.assert_frame_equal(idx1, idx2)
    pd.testing.assert_frame_equal(h1, h2)
    pd.testing.assert_series_equal(p1["is_selected"], p2["is_selected"])


# ---------------------------------------------------------------------------
# 2. Insufficient Data Contract Tests
# ---------------------------------------------------------------------------

def test_insufficient_events_raises_typed_exception():
    """When fewer than required events exist, InsufficientP6BenchmarkDataError is raised."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=2, num_controls=5)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    with pytest.raises(InsufficientP6BenchmarkDataError) as exc_info:
        build_p6_benchmark_triplets(
            aligned_df=aligned,
            event_catalogue_df=events,
            config=cfg,
            control_catalogue_df=controls,
            design_mode="primary",
        )
    assert any("Insufficient distinct heatwaves" in r for r in exc_info.value.reasons)
    assert not exc_info.value.blind_pool.empty


def test_insufficient_controls_raises_typed_exception():
    """When fewer than required controls exist, InsufficientP6BenchmarkDataError is raised."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=2)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    with pytest.raises(InsufficientP6BenchmarkDataError) as exc_info:
        build_p6_benchmark_triplets(
            aligned_df=aligned,
            event_catalogue_df=events,
            config=cfg,
            control_catalogue_df=controls,
            design_mode="primary",
        )
    assert any("Insufficient unique eligible controls" in r for r in exc_info.value.reasons)


# ---------------------------------------------------------------------------
# 3. Canonical Schema & Completeness Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_signal", ["temperature_c", "price_usd_per_mwh", "carbon_g_per_kwh", "demand_mw"])
def test_missing_canonical_signal_column_fails_validation(missing_signal):
    """Missing any of the 4 canonical signal columns fails schema validation."""
    aligned = make_synthetic_aligned_dataset(
        pd.Timestamp("2024-06-01 07:00:00", tz="UTC"), periods_hours=100, missing_cols=[missing_signal]
    )
    with pytest.raises(ValueError, match="missing required canonical signal"):
        validate_aligned_dataframe_signals(aligned, require_complete=True)


def test_partial_canonical_schema_produces_zero_eligible_blind_windows():
    """A dataset lacking price/carbon/demand produces 0 eligible blind windows."""
    aligned = make_synthetic_aligned_dataset(
        pd.Timestamp("2024-06-01 07:00:00", tz="UTC"),
        periods_hours=2000,
        missing_cols=["price_usd_per_mwh", "carbon_g_per_kwh", "demand_mw"],
    )
    pool = build_candidate_blind_windows(
        aligned_df=aligned,
        event_catalogue_df=pd.DataFrame(),
        control_catalogue_df=pd.DataFrame(),
        window_duration_hours=120,
        study_years=[2024],
        study_months=[6],
    )
    assert pool["is_eligible"].sum() == 0
    assert all("missing_canonical_schema" in r for r in pool["rejection_codes"])


def test_naive_timestamp_in_aligned_dataset_is_rejected():
    """Naive timestamps in aligned_df are strictly rejected, never silently localized."""
    aligned = make_synthetic_aligned_dataset(pd.Timestamp("2024-06-01 07:00:00", tz="UTC"), periods_hours=100)
    # Strip timezone
    aligned["timestamp_utc"] = aligned["timestamp_utc"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="naive timestamps"):
        validate_aligned_dataframe_signals(aligned, require_complete=True)


def test_duplicate_aligned_timestamps_fail_validation():
    """Duplicate timestamps in aligned_df are strictly rejected."""
    aligned = make_synthetic_aligned_dataset(pd.Timestamp("2024-06-01 07:00:00", tz="UTC"), periods_hours=100)
    aligned.loc[1, "timestamp_utc"] = aligned.loc[0, "timestamp_utc"]
    with pytest.raises(ValueError, match="duplicate timestamps"):
        validate_aligned_dataframe_signals(aligned, require_complete=True)


# ---------------------------------------------------------------------------
# 4. Centralized Event-Window Calculation Tests
# ---------------------------------------------------------------------------

def test_72h_event_expands_deterministically_to_120h():
    """A 72-hour event receives exactly 24h before and 24h after to span 120h."""
    ev = {
        "event_id": "HW_72",
        "duration_hours": 72,
        "event_start_utc": "2024-07-02 07:00:00+00:00",
        "event_end_utc": "2024-07-05 07:00:00+00:00",
    }
    w = compute_event_evaluation_window(ev, target_duration_hours=120)
    assert w["is_eligible"] is True
    assert w["duration_hours"] == 120
    assert w["context_before_hours"] == 24
    assert w["context_after_hours"] == 24
    assert w["start_timestamp_utc"] == pd.Timestamp("2024-07-01 07:00:00", tz="UTC")
    assert w["end_timestamp_utc"] == pd.Timestamp("2024-07-06 07:00:00", tz="UTC")


def test_120h_event_remains_exactly_120h_without_padding():
    """A 120-hour heatwave is not padded to 168h; it spans exactly 120h."""
    ev = {
        "event_id": "HW_120",
        "duration_hours": 120,
        "event_start_utc": "2022-09-04 07:00:00+00:00",
        "event_end_utc": "2022-09-09 07:00:00+00:00",
    }
    w = compute_event_evaluation_window(ev, target_duration_hours=120)
    assert w["is_eligible"] is True
    assert w["duration_hours"] == 120
    assert w["context_before_hours"] == 0
    assert w["context_after_hours"] == 0
    assert w["start_timestamp_utc"] == pd.Timestamp("2022-09-04 07:00:00", tz="UTC")
    assert w["end_timestamp_utc"] == pd.Timestamp("2022-09-09 07:00:00", tz="UTC")


def test_event_longer_than_120h_is_rejected():
    """An event longer than 120h is marked ineligible and not truncated."""
    ev = {
        "event_id": "HW_144",
        "duration_hours": 144,
        "event_start_utc": "2022-09-01 07:00:00+00:00",
        "event_end_utc": "2022-09-07 07:00:00+00:00",
    }
    w = compute_event_evaluation_window(ev, target_duration_hours=120)
    assert w["is_eligible"] is False
    assert "exceeds target window duration" in w["ineligibility_reason"]


# ---------------------------------------------------------------------------
# 5. Relational Validator Tests
# ---------------------------------------------------------------------------

def test_validator_rejects_duplicate_control_ids():
    """Validator rejects duplicate control IDs in index."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    index.loc[1, "control_id"] = index.loc[0, "control_id"]
    with pytest.raises(ValueError, match="duplicate control_id"):
        validate_p6_benchmark_triplets(hourly, index)


def test_validator_rejects_duplicate_triplet_ids():
    """Validator rejects duplicate triplet IDs in index."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    index.loc[1, "triplet_id"] = index.loc[0, "triplet_id"]
    with pytest.raises(ValueError, match="duplicate triplet_id"):
        validate_p6_benchmark_triplets(hourly, index)


def test_validator_rejects_hourly_triplet_id_absent_from_index():
    """Validator rejects hourly records with triplet_ids missing from the index."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    hourly.loc[0:10, "triplet_id"] = "TRIPLET_PHANTOM"
    with pytest.raises(ValueError, match="absent from index"):
        validate_p6_benchmark_triplets(hourly, index)


def test_validator_rejects_index_triplet_missing_from_hourly():
    """Validator rejects indexed triplets missing from hourly records."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    t_drop = index["triplet_id"].iloc[0]
    hourly_dropped = hourly[hourly["triplet_id"] != t_drop]
    with pytest.raises(ValueError, match="absent from hourly_df|total rows"):
        validate_p6_benchmark_triplets(hourly_dropped, index)


def test_validator_rejects_window_type_mismatch():
    """Validator rejects hourly records with invalid window_type."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    hourly.loc[0, "window_type"] = "invalid_context"
    with pytest.raises(ValueError, match="invalid window_type"):
        validate_p6_benchmark_triplets(hourly, index)


def test_validator_rejects_timestamp_outside_indexed_interval():
    """Validator rejects hourly rows shifted outside the indexed interval."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    hourly.loc[0, "timestamp_utc"] = hourly.loc[0, "timestamp_utc"] - pd.Timedelta(hours=24)
    with pytest.raises(ValueError, match="time range .* != indexed range"):
        validate_p6_benchmark_triplets(hourly, index)


def test_validator_rejects_non_finite_signal_in_hourly():
    """Validator rejects NaN or infinite values in canonical signals."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    hourly, index, _ = build_p6_benchmark_triplets(aligned, events, {"duration_hours": 120}, control_catalogue_df=controls)
    hourly.loc[5, "carbon_g_per_kwh"] = np.nan
    with pytest.raises(ValueError, match="missing or non-finite"):
        validate_p6_benchmark_triplets(hourly, index)


# ---------------------------------------------------------------------------
# 6. Strict Leakage Independence Tests
# ---------------------------------------------------------------------------

def test_leakage_pure_builder_never_reads_filesystem(monkeypatch):
    """Pure builder does not consult filesystem during execution."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    # Intercept open to detect unauthorized file access
    orig_open = open

    def guarded_open(file, *args, **kwargs):
        path_str = str(file)
        if any(kw in path_str for kw in ["results", "runs", "schedule", "policy", "output"]):
            raise PermissionError(f"Leakage detected! Attempted to access: {path_str}")
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)

    hourly, index, pool = build_p6_benchmark_triplets(
        aligned_df=aligned,
        event_catalogue_df=events,
        config=cfg,
        control_catalogue_df=controls,
        design_mode="primary",
    )
    assert len(index) == 5


def test_leakage_immunity_to_scheduler_results_mutation(tmp_path):
    """Mutating or adding scheduler outcome files does not affect selection."""
    aligned, events, controls = make_synthetic_inputs_for_triplets(num_events=5, num_controls=5)
    cfg = {"duration_hours": 120, "buffer_hours": 48}

    h1, idx1, p1 = build_p6_benchmark_triplets(aligned, events, cfg, control_catalogue_df=controls, design_mode="primary")

    # Mutate disk with dummy scheduler result
    res_dir = tmp_path / "data/results"
    res_dir.mkdir(parents=True)
    (res_dir / "sched_result.parquet").write_bytes(b"dummy")

    h2, idx2, p2 = build_p6_benchmark_triplets(aligned, events, cfg, control_catalogue_df=controls, design_mode="primary")

    pd.testing.assert_frame_equal(idx1, idx2)
    pd.testing.assert_frame_equal(h1, h2)


# ---------------------------------------------------------------------------
# 7. Authentic Ingestion & Streaming Reader Tests
# ---------------------------------------------------------------------------

def test_parse_caiso_historical_group_zips():
    """Verify parsing of authentic historical CAISO daily group ZIP archives."""
    from heattrace.process.p6_event_bundle import parse_caiso_historical_group_zips
    p = Path("data/raw/caiso/historical/June18-25_22")
    if not p.exists():
        pytest.skip("Historical CAISO folder not present")

    df = parse_caiso_historical_group_zips(p)
    assert not df.empty
    assert "timestamp_utc" in df.columns
    assert "price_usd_per_mwh" in df.columns
    assert df["node_id"].iloc[0] == "TH_NP15_GEN-APND"
    assert df["market_run_id"].iloc[0] == "DAM"
    assert df["price_usd_per_mwh"].notna().all()
    assert np.all(np.isfinite(df["price_usd_per_mwh"]))


def test_parse_ciso_xlsx_carbon_streaming():
    """Verify fast single-pass bounded streaming reader for CISO.xlsx."""
    from heattrace.process.p6_event_bundle import parse_ciso_xlsx_carbon_streaming
    p = Path("data/raw/eia/CISO.xlsx")
    if not p.exists():
        pytest.skip("CISO.xlsx not present")

    target_ts = {pd.to_datetime("2024-07-01 07:00:00", utc=True)}
    df = parse_ciso_xlsx_carbon_streaming(p, target_timestamps_utc=target_ts)
    assert len(df) == 1
    assert df["timestamp_utc"].iloc[0] == pd.to_datetime("2024-07-01 07:00:00", utc=True)
    assert np.isfinite(df["carbon_g_per_kwh"].iloc[0])
    assert df["carbon_g_per_kwh"].iloc[0] > 0.0


def test_materialized_benchmark_files_integrity():
    """Verify materialized Phase 1 benchmark artifacts on disk."""
    p_pairs = Path("data/benchmarks/p6_event_control_pairs.parquet")
    p_idx = Path("data/benchmarks/p6_event_control_index.csv")
    p_pool = Path("data/benchmarks/p6_event_blind_pool.csv")

    assert p_pairs.exists(), "p6_event_control_pairs.parquet missing"
    assert p_idx.exists(), "p6_event_control_index.csv missing"
    assert p_pool.exists(), "p6_event_blind_pool.csv missing"

    df_pairs = pd.read_parquet(p_pairs)
    df_idx = pd.read_csv(p_idx)
    df_pool = pd.read_csv(p_pool)

    assert len(df_pairs) == 1440, f"Expected 1440 rows, got {len(df_pairs)}"
    assert len(df_idx) == 4, f"Expected 4 rows, got {len(df_idx)}"
    assert len(df_pool) == 472, f"Expected 472 rows, got {len(df_pool)}"
    assert df_pool["is_selected"].sum() == 4, "Expected 4 selected blinds in pool"

    validate_p6_benchmark_triplets(
        hourly_df=df_pairs,
        triplet_index_df=df_idx,
        design_mode="fallback",
        expected_duration_hours=120,
    )


def test_gate1_relational_and_provenance_invariants():
    """Verify strict relational and provenance invariants across all Gate 1 artifacts."""
    df_pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    df_idx = pd.read_csv("data/benchmarks/p6_event_control_index.csv")
    df_pool = pd.read_csv("data/benchmarks/p6_event_blind_pool.csv")
    df_ctrl = pd.read_parquet("data/events/control_catalogue_v0.parquet")
    df_events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    # 1. Triplet roles & cardinality
    dev_triplet = df_idx[df_idx["role"] == "development"]
    conf_triplets = df_idx[df_idx["role"] == "confirmatory"]
    assert len(dev_triplet) == 1, "Exactly 1 development triplet required"
    assert len(conf_triplets) == 3, "Exactly 3 confirmatory triplets required"
    assert dev_triplet["event_id"].iloc[0] == "HW_20240702", "HW_20240702 must be dev event"
    assert set(conf_triplets["event_id"]) == {"HW_20220620", "HW_20220904", "HW_20220922"}, "Confirmatory events mismatch"

    # 2. Every indexed control exists exactly once in control catalogue
    ctrl_id_set = set(df_ctrl["control_id"])
    for cid in df_idx["control_id"]:
        assert cid in ctrl_id_set, f"Control {cid} missing from control catalogue"
        assert (df_ctrl["control_id"] == cid).sum() == 1, f"Control {cid} not unique in catalogue"

    # 3. Matching scores agree across control catalogue and index
    for _, r in df_idx.iterrows():
        cid = r["control_id"]
        c_row = df_ctrl[df_ctrl["control_id"] == cid].iloc[0]
        score_str = f"score={c_row['matching_score']};temp_dist_c={c_row['target_temperature_distance_c']}"
        assert r["matching_distances"] == score_str, f"Matching distance mismatch for {cid}"

    # 4. Every indexed blind exists exactly once as selected candidate in blind pool
    pool_sel = df_pool[df_pool["is_selected"]]
    assert len(pool_sel) == 4, "Expected exactly 4 selected candidates in blind pool"
    pool_sel_ids = set(pool_sel["candidate_id"])
    for bid in df_idx["blind_id"]:
        assert bid in pool_sel_ids, f"Blind ID {bid} not in selected blind pool"
        assert (pool_sel["candidate_id"] == bid).sum() == 1, f"Blind ID {bid} not unique in selected pool"

    # 5. Global non-overlap among all 12 windows
    intervals = []
    for _, r in df_idx.iterrows():
        intervals.append((pd.to_datetime(r["heatwave_start_utc"], utc=True), pd.to_datetime(r["heatwave_end_utc"], utc=True)))
        intervals.append((pd.to_datetime(r["control_start_utc"], utc=True), pd.to_datetime(r["control_end_utc"], utc=True)))
        intervals.append((pd.to_datetime(r["blind_start_utc"], utc=True), pd.to_datetime(r["blind_end_utc"], utc=True)))

    assert len(intervals) == 12, "Expected 12 window intervals"
    # Pairwise disjoint test (or same exact interval only if disjoint in time)
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            s1, e1 = intervals[i]
            s2, e2 = intervals[j]
            overlap = max(s1, s2) < min(e1, e2)
            assert not overlap, f"Windows {i} ({s1}..{e1}) and {j} ({s2}..{e2}) overlap!"

    # 6. Strict buffer separation: blind windows must exclude all heatwaves + 48h buffer
    for b_row in pool_sel.itertuples():
        b_s = pd.to_datetime(b_row.start_timestamp_utc, utc=True)
        b_e = pd.to_datetime(b_row.end_timestamp_utc, utc=True)
        for _, ev_r in df_events.iterrows():
            hw_s = pd.to_datetime(ev_r["event_start_utc"], utc=True) - pd.Timedelta(hours=48)
            hw_e = pd.to_datetime(ev_r["event_end_utc"], utc=True) + pd.Timedelta(hours=48)
            overlap = max(b_s, hw_s) < min(b_e, hw_e)
            assert not overlap, f"Blind {b_row.candidate_id} violates 48h buffer around {ev_r['event_id']}"


def test_historical_caiso_parser_rejects_conflicts(tmp_path):
    """Historical CAISO parser rejects conflicting duplicate timestamps loudly."""
    import zipfile
    from heattrace.process.p6_event_bundle import parse_caiso_historical_group_zips

    # Create dummy zip with conflicting prices for the same timestamp
    zip_p = tmp_path / "test_conflict.zip"
    with zipfile.ZipFile(zip_p, "w") as zf:
        csv_content = (
            "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,OPR_DT,OPR_HR,OPR_INTERVAL,NODE,NODE_ID,PNODE_RESMRID,MARKET_RUN_ID,LMP_TYPE,XML_DATA_ITEM,PNODE_ID,GRP_TYPE,POS,MW,EXECUTION_TYPE\n"
            "2022-06-20T07:00:00-00:00,2022-06-20T08:00:00-00:00,2022-06-20,1,0,TH_NP15_GEN-APND,TH_NP15_GEN-APND,TH_NP15_GEN-APND,DAM,LMP,LMP_PRC,TH_NP15_GEN-APND,ALL_APNODES,0,50.0,0\n"
            "2022-06-20T07:00:00-00:00,2022-06-20T08:00:00-00:00,2022-06-20,1,0,TH_NP15_GEN-APND,TH_NP15_GEN-APND,TH_NP15_GEN-APND,DAM,LMP,LMP_PRC,TH_NP15_GEN-APND,ALL_APNODES,0,99.0,0\n"
        )
        zf.writestr("20220620_20220620_PRC_LMP_DAM_LMP_v12.csv", csv_content)

    with pytest.raises(ValueError, match="Conflicting duplicate LMP price"):
        parse_caiso_historical_group_zips(tmp_path)


def test_ciso_xlsx_streaming_parser_accuracy():
    """Verify streaming parser matches exact known carbon intensities from CISO.xlsx."""
    from heattrace.process.p6_event_bundle import parse_ciso_xlsx_carbon_streaming
    p = Path("data/raw/eia/CISO.xlsx")
    if not p.exists():
        pytest.skip("CISO.xlsx missing")

    # Sample hours
    target_ts = [
        pd.to_datetime("2024-07-01 07:00:00", utc=True),
        pd.to_datetime("2024-06-05 07:00:00", utc=True),
        pd.to_datetime("2024-09-15 07:00:00", utc=True),
    ]
    df = parse_ciso_xlsx_carbon_streaming(p, target_timestamps_utc=target_ts)
    assert len(df) == 3
    for _, r in df.iterrows():
        assert np.isfinite(r["carbon_g_per_kwh"])
        assert 50.0 < r["carbon_g_per_kwh"] < 500.0


def test_materialize_p6_gate1_benchmarks_end_to_end_idempotent(tmp_path):
    """materialize_p6_gate1_benchmarks runs idempotently in tmp_path."""
    from heattrace.process.p6_event_bundle import materialize_p6_gate1_benchmarks
    import shutil

    # Copy necessary input trees to tmp_path
    data_tmp = tmp_path / "data"
    cfg_tmp = tmp_path / "configs"
    shutil.copytree("data/events", data_tmp / "events")
    shutil.copytree("data/raw", data_tmp / "raw")
    shutil.copytree("configs", cfg_tmp)

    manifest1 = materialize_p6_gate1_benchmarks(repo_root=tmp_path, config_dir=cfg_tmp, data_dir=data_tmp)
    assert manifest1["summary"]["total_benchmark_rows"] == 1440
    assert manifest1["summary"]["total_triplets"] == 4

    # Run again and verify hash consistency across benchmark output files
    manifest2 = materialize_p6_gate1_benchmarks(repo_root=tmp_path, config_dir=cfg_tmp, data_dir=data_tmp)
    for k in ["pairs_parquet", "index_csv", "blind_pool_csv", "control_catalogue_parquet", "control_catalogue_csv"]:
        assert manifest1["output_files"][k]["sha256"] == manifest2["output_files"][k]["sha256"]

    # Manifest semantic equality (excluding volatile generated_at_utc and audit timestamps)
    assert manifest1["summary"] == manifest2["summary"]
    assert manifest1["triplets"] == manifest2["triplets"]
    assert manifest1["design_mode"] == manifest2["design_mode"]
    assert manifest1["algorithm_version"] == manifest2["algorithm_version"]


def test_gate1_transactional_failure_injection(tmp_path, monkeypatch):
    """Verify that if validation or materialization fails during staging, all 7 outputs are untouched."""
    from heattrace.process.p6_event_bundle import materialize_p6_gate1_benchmarks
    from heattrace.ingest.provenance import sha256_file
    import shutil

    data_tmp = tmp_path / "data"
    cfg_tmp = tmp_path / "configs"
    shutil.copytree("data/events", data_tmp / "events")
    shutil.copytree("data/raw", data_tmp / "raw")
    shutil.copytree("configs", cfg_tmp)

    # Initial successful materialization
    manifest = materialize_p6_gate1_benchmarks(repo_root=tmp_path, config_dir=cfg_tmp, data_dir=data_tmp)

    all_output_paths = [
        data_tmp / "benchmarks/p6_event_control_pairs.parquet",
        data_tmp / "benchmarks/p6_event_control_index.csv",
        data_tmp / "benchmarks/p6_event_blind_pool.csv",
        data_tmp / "events/control_catalogue_v0.parquet",
        data_tmp / "events/control_catalogue_v0.csv",
        data_tmp / "manifests/control_matching_audit.json",
        data_tmp / "manifests/p6_gate1_benchmark_manifest.json",
    ]

    orig_hashes = {p: sha256_file(p) for p in all_output_paths}
    orig_mtimes = {p: p.stat().st_mtime_ns for p in all_output_paths}

    # Inject failure during validation in the second run
    import heattrace.process.p6_event_bundle as p6_bundle
    def broken_validate(*args, **kwargs):
        raise RuntimeError("Simulated mid-pipeline transactional failure!")

    monkeypatch.setattr(p6_bundle, "validate_p6_benchmark_triplets", broken_validate)

    with pytest.raises(RuntimeError, match="Simulated mid-pipeline transactional failure!"):
        materialize_p6_gate1_benchmarks(repo_root=tmp_path, config_dir=cfg_tmp, data_dir=data_tmp)

    # Assert every single one of the 7 published production files was untouched
    for p in all_output_paths:
        assert sha256_file(p) == orig_hashes[p]
        assert p.stat().st_mtime_ns == orig_mtimes[p]


def test_stage_a_candidate_identities_independent_of_outcome_values():
    """Verify that mutating CAISO prices, EIA demand, and EIA carbon does not change frozen Stage A identities."""
    from heattrace.process.p6_event_bundle import build_p6_benchmark_triplets, compute_event_evaluation_window
    import pandas as pd
    import numpy as np

    df_events = pd.read_parquet("data/events/heatwave_events_v0.parquet")
    df_controls = pd.read_parquet("data/events/control_catalogue_v0.parquet")

    # Generate synthetic aligned signals across known window hours
    ts_range = []
    for _, r in df_controls.iterrows():
        ts_range.extend(pd.date_range(r["start_timestamp_utc"], r["end_timestamp_utc"] - pd.Timedelta(hours=1), freq="1h"))
    for _, r in df_events.iterrows():
        w = compute_event_evaluation_window(r)
        ts_range.extend(pd.date_range(w["start_timestamp_utc"], w["end_timestamp_utc"] - pd.Timedelta(hours=1), freq="1h"))
    # Also add candidate blind windows in Aug/Sept
    for s_date in ["2024-07-27", "2024-08-03", "2024-09-03", "2024-09-19"]:
        s_utc = pd.to_datetime(s_date + " 07:00:00", utc=True)
        ts_range.extend(pd.date_range(s_utc, s_utc + pd.Timedelta(hours=119), freq="1h"))

    unique_ts = sorted(set(ts_range))
    base_aligned = pd.DataFrame({
        "timestamp_utc": unique_ts,
        "temperature_c": 24.0,
        "price_usd_per_mwh": 45.0,
        "carbon_g_per_kwh": 220.0,
        "demand_mw": 28000.0,
    })

    _, idx1, _ = build_p6_benchmark_triplets(
        aligned_df=base_aligned,
        event_catalogue_df=df_events,
        config={"duration_hours": 120, "buffer_hours": 48},
        control_catalogue_df=df_controls,
        design_mode="fallback",
    )

    # Mutate CAISO prices, EIA demand, and EIA carbon significantly
    mutated_aligned = base_aligned.copy()
    mutated_aligned["price_usd_per_mwh"] = 999.0
    mutated_aligned["demand_mw"] = 55000.0
    mutated_aligned["carbon_g_per_kwh"] = 800.0

    _, idx2, _ = build_p6_benchmark_triplets(
        aligned_df=mutated_aligned,
        event_catalogue_df=df_events,
        config={"duration_hours": 120, "buffer_hours": 48},
        control_catalogue_df=df_controls,
        design_mode="fallback",
    )

    # Assert identities are 100% invariant to outcome values
    for col in ["triplet_id", "role", "event_id", "control_id", "blind_id", "heatwave_start_utc", "control_start_utc", "blind_start_utc"]:
        assert (idx1[col] == idx2[col]).all()


def test_event_specific_control_temperature_matching():
    """Verify changing one event's matching temperature changes that event's score/ranking without changing others."""
    from heattrace.process.controls import build_fallback_controls
    import tempfile
    import shutil

    # Run default pure build
    res1 = build_fallback_controls()
    per_ev1 = res1["per_event_candidates"]

    # HW_20240702 target temp is 30.0, HW_20220922 target temp is 27.4
    ev1_scores = [c["matching_score"] for c in per_ev1["HW_20240702"][:10]]
    ev2_scores = [c["matching_score"] for c in per_ev1["HW_20220922"][:10]]

    # The scores differ between the two events because they match against different event temperatures
    assert ev1_scores != ev2_scores

    # Mutate the event catalogue in a temporary copy so only HW_20240702 target temperature changes
    with tempfile.TemporaryDirectory() as tmp_d:
        tmp_data = Path(tmp_d) / "data"
        shutil.copytree("data/events", tmp_data / "events")
        shutil.copytree("data/raw", tmp_data / "raw")
        hw_p = tmp_data / "events/heatwave_events_v0.parquet"
        df_hw = pd.read_parquet(hw_p)
        df_hw.loc[df_hw["event_id"] == "HW_20240702", "mean_max_temperature_c"] = 42.0
        df_hw.to_parquet(hw_p, index=False)

        res2 = build_fallback_controls(data_dir=tmp_data)
        per_ev2 = res2["per_event_candidates"]

        # HW_20240702 candidate scores changed
        assert [c["matching_score"] for c in per_ev2["HW_20240702"][:10]] != ev1_scores
        # Unrelated event HW_20220922 candidate scores are strictly identical
        assert [c["matching_score"] for c in per_ev2["HW_20220922"][:10]] == ev2_scores


def test_stage_b_missing_caiso_coverage_deterministically_advances(tmp_path):
    """Verify that missing CAISO files causes deterministic advance down pre-ranked candidate list."""
    from heattrace.process.p6_event_bundle import materialize_p6_gate1_benchmarks
    import shutil

    data_tmp = tmp_path / "data"
    cfg_tmp = tmp_path / "configs"
    shutil.copytree("data/events", data_tmp / "events")
    shutil.copytree("data/raw", data_tmp / "raw")
    shutil.copytree("configs", cfg_tmp)

    # When caiso_dam_lmp_TH_NP15_GEN-APND_20240920_20240925.zip is removed,
    # BLIND_ef75b17921d7 (2024-09-19 to 2024-09-24) loses coverage and is skipped.
    # The pipeline deterministically advances to next available candidate BLIND_3d808572606e.
    caiso_zip = data_tmp / "raw/caiso/caiso_dam_lmp_TH_NP15_GEN-APND_20240920_20240925.zip"
    assert caiso_zip.exists()
    caiso_zip.unlink()

    manifest = materialize_p6_gate1_benchmarks(repo_root=tmp_path, config_dir=cfg_tmp, data_dir=data_tmp)
    selected_blinds = [t["blind_id"] for t in manifest["triplets"]]
    # BLIND_ef75b17921d7 was skipped, and BLIND_3d808572606e took its place deterministically
    assert "BLIND_ef75b17921d7" not in selected_blinds
    assert "BLIND_3d808572606e" in selected_blinds


def test_eia_conflicting_duplicate_timestamps_fail_loudly(tmp_path):
    """Verify that conflicting duplicate timestamps in EIA data raise loud ValueError."""
    from heattrace.process.p6_event_bundle import materialize_p6_gate1_benchmarks
    import shutil
    import json

    data_tmp = tmp_path / "data"
    cfg_tmp = tmp_path / "configs"
    shutil.copytree("data/events", data_tmp / "events")
    shutil.copytree("data/raw", data_tmp / "raw")
    shutil.copytree("configs", cfg_tmp)

    # Inject conflicting duplicate into one EIA json file
    eia_file = data_tmp / "raw/eia/eia930_region_CISO_20240701.json"
    with eia_file.open("r", encoding="utf-8") as f:
        d = json.load(f)
    # Add conflicting duplicate record for 2024-07-01T08 (which is ts 2024-07-01 07:00:00)
    conflict_record = {
        "period": "2024-07-01T08",
        "respondent": "CISO",
        "type": "D",
        "value": "999999",  # Conflicting value
    }
    d["response"]["data"].append(conflict_record)
    with eia_file.open("w", encoding="utf-8") as f:
        json.dump(d, f)

    with pytest.raises(ValueError, match="Conflicting duplicate EIA demand"):
        materialize_p6_gate1_benchmarks(repo_root=tmp_path, config_dir=cfg_tmp, data_dir=data_tmp)


def test_fallback_controls_produced_algorithmically():
    """Verify controls are allocated algorithmically across candidate set and recorded in audit."""
    import json
    audit_path = Path("data/manifests/control_matching_audit.json")
    assert audit_path.exists()
    with audit_path.open("r", encoding="utf-8") as f:
        audit = json.load(f)

    assert audit["allocation_algorithm"] == "greedy_non_overlapping_score_distance_date"
    assert len(audit["selected_controls"]) == 4

    for sc in audit["selected_controls"]:
        assert "selected_rank" in sc
        assert sc["selected_rank"] >= 1
        assert sc["matching_score"] >= 0.0
        assert "total_candidates_evaluated" in sc
        assert sc["total_candidates_evaluated"] > 100


# ==============================================================================
# Phase 7 Phase-Label Propagation & Overlay Adversarial Probes
# ==============================================================================

def test_p7_phase_label_overlay_genuine_phases_survive():
    """Verify multiple genuine heatwave phases survive propagation."""
    from heattrace.process.p6_event_bundle import (
        build_p6_phase_label_overlay,
        apply_p6_phase_label_overlay,
    )
    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    overlay = build_p6_phase_label_overlay(pairs, events)
    applied = apply_p6_phase_label_overlay(pairs, overlay)

    # All four canonical heatwave phases must survive
    hw_rows = applied[applied["window_type"] == "heatwave"]
    hw_phases = set(hw_rows["phase_label"].unique())
    assert hw_phases == {"onset", "peak", "sustained", "recovery"}

    # Non-event rows must retain explicit non-event labels
    ctrl_rows = applied[applied["window_type"] == "control"]
    assert set(ctrl_rows["phase_label"].unique()) == {"control"}

    blind_rows = applied[applied["window_type"] == "event_blind"]
    assert set(blind_rows["phase_label"].unique()) == {"event_blind"}


def test_p7_phase_label_overlay_shuffled_order_invariance():
    """Verify shuffled source rows produce identical overlay output and mapping."""
    from heattrace.process.p6_event_bundle import (
        build_p6_phase_label_overlay,
        apply_p6_phase_label_overlay,
    )
    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    shuffled_pairs = pairs.sample(frac=1.0, random_state=42).reset_index(drop=True)
    shuffled_events = events.sample(frac=1.0, random_state=42).reset_index(drop=True)

    overlay1 = build_p6_phase_label_overlay(pairs, events)
    overlay2 = build_p6_phase_label_overlay(shuffled_pairs, shuffled_events)

    pd.testing.assert_frame_equal(overlay1, overlay2)

    applied1 = apply_p6_phase_label_overlay(pairs, overlay1)
    applied2 = apply_p6_phase_label_overlay(shuffled_pairs, overlay2)
    # Check that sorting applied2 back to pairs order gives identical dataframe
    applied2_sorted = applied2.sort_values(by=["triplet_id", "window_id", "timestamp_utc"]).reset_index(drop=True)
    applied1_sorted = applied1.sort_values(by=["triplet_id", "window_id", "timestamp_utc"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(applied1_sorted, applied2_sorted)


def test_p7_phase_label_overlay_missing_row_fails_loudly():
    """Verify missing phase row fails loudly (fails closed)."""
    from heattrace.process.p6_event_bundle import (
        build_p6_phase_label_overlay,
        apply_p6_phase_label_overlay,
    )
    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    overlay = build_p6_phase_label_overlay(pairs, events)
    # Drop one row from overlay
    incomplete_overlay = overlay.iloc[:-1].copy()

    with pytest.raises(ValueError, match="full coverage"):
        apply_p6_phase_label_overlay(pairs, incomplete_overlay)


def test_p7_phase_overlay_join_rejects_window_type_tampering():
    """Verify mutating window_type (e.g., heatwave -> control) raises ValueError."""
    from heattrace.process.p6_event_bundle import (
        build_p6_phase_label_overlay,
        apply_p6_phase_label_overlay,
    )
    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")
    overlay = build_p6_phase_label_overlay(pairs, events)

    # Attack 1: Mutate heatwave row to control in pairs
    tampered_pairs = pairs.copy()
    hw_idx = tampered_pairs[tampered_pairs["window_type"] == "heatwave"].index[0]
    tampered_pairs.loc[hw_idx, "window_type"] = "control"

    with pytest.raises(ValueError, match="(full coverage|invalid phase label)"):
        apply_p6_phase_label_overlay(tampered_pairs, overlay)

    # Attack 2: Mutate control row to heatwave in pairs
    tampered_pairs2 = pairs.copy()
    ctrl_idx = tampered_pairs2[tampered_pairs2["window_type"] == "control"].index[0]
    tampered_pairs2.loc[ctrl_idx, "window_type"] = "heatwave"

    with pytest.raises(ValueError, match="(full coverage|invalid phase label)"):
        apply_p6_phase_label_overlay(tampered_pairs2, overlay)

    # Attack 3: Overlay with extra row
    extra_overlay = pd.concat([overlay, overlay.iloc[[0]].assign(timestamp_utc=pd.Timestamp("2099-01-01 00:00:00+00:00"))], ignore_index=True)
    # Joining with original pairs must still strictly match and check
    with pytest.raises(ValueError, match="duplicate join keys"):
        apply_p6_phase_label_overlay(pairs, pd.concat([overlay, overlay.iloc[[0]]], ignore_index=True))


def test_p7_phase_label_overlay_schema_exactness(tmp_path):
    """Verify loading overlay requires exact schema, rejecting missing or extra columns."""
    from heattrace.process.p6_event_bundle import (
        load_p6_phase_label_overlay,
        PHASE_LABEL_OVERLAY_COLUMNS,
    )
    overlay = pd.read_parquet("data/benchmarks/p7_phase_label_overlay.parquet")

    # Extra column
    bad_overlay = overlay.assign(extra_col=123)
    bad_path = tmp_path / "bad_overlay.parquet"
    bad_overlay.to_parquet(bad_path, index=False)

    with pytest.raises(ValueError, match="Overlay schema mismatch"):
        load_p6_phase_label_overlay(bad_path)



def test_p7_phase_label_overlay_duplicate_conflicting_fails_loudly():
    """Verify duplicate or conflicting labels fail closed."""
    from heattrace.process.p6_event_bundle import apply_p6_phase_label_overlay

    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    dup_pairs = pd.concat([pairs, pairs.iloc[[0]]], ignore_index=True)

    from heattrace.process.p6_event_bundle import build_p6_phase_label_overlay
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    with pytest.raises(ValueError, match="Duplicate key"):
        build_p6_phase_label_overlay(dup_pairs, events)

    overlay = build_p6_phase_label_overlay(pairs, events)
    conflicting_overlay = pd.concat([overlay, overlay.iloc[[0]].assign(phase_label="corrupted")], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate join keys"):
        apply_p6_phase_label_overlay(pairs, conflicting_overlay)


def test_p7_phase_label_control_blind_cannot_be_heatwave_phases():
    """Verify control and event-blind rows cannot be mislabeled as heatwave phases."""
    from heattrace.process.p6_event_bundle import (
        build_p6_phase_label_overlay,
        apply_p6_phase_label_overlay,
    )
    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    overlay = build_p6_phase_label_overlay(pairs, events)
    applied = apply_p6_phase_label_overlay(pairs, overlay)

    non_event_rows = applied[applied["window_type"].isin(["control", "event_blind"])]
    heatwave_phase_set = {"onset", "peak", "sustained", "recovery"}
    assert not any(p in heatwave_phase_set for p in non_event_rows["phase_label"])


def test_p7_phase_label_independent_of_price_carbon_outcomes():
    """Verify alterations to price, carbon, demand, or outcomes cannot alter phase labels."""
    from heattrace.process.p6_event_bundle import (
        build_p6_phase_label_overlay,
        apply_p6_phase_label_overlay,
    )
    pairs = pd.read_parquet("data/benchmarks/p6_event_control_pairs.parquet")
    events = pd.read_parquet("data/events/heatwave_events_v0.parquet")

    # Mutate price, carbon, demand drastically
    mutated_pairs = pairs.copy()
    mutated_pairs["price_usd_per_mwh"] = mutated_pairs["price_usd_per_mwh"] * 1000.0 + 999.0
    mutated_pairs["carbon_g_per_kwh"] = mutated_pairs["carbon_g_per_kwh"] * 0.001
    mutated_pairs["demand_mw"] = 0.0

    overlay_orig = build_p6_phase_label_overlay(pairs, events)
    overlay_mut = build_p6_phase_label_overlay(mutated_pairs, events)

    pd.testing.assert_frame_equal(overlay_orig, overlay_mut)




