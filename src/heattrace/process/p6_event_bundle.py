"""Phase 1 benchmark triplet bundle construction and validation (P6).

Deterministic materialization, candidate auditing, and validation for
heatwave, matched-control, and event-blind benchmark triplets.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
import zipfile
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from heattrace.ingest.noaa import get_local_day_utc_bounds


CANONICAL_BENCHMARK_SIGNALS = [
    "temperature_c",
    "price_usd_per_mwh",
    "carbon_g_per_kwh",
    "demand_mw",
]

INDEX_COLUMNS = [
    "triplet_id",
    "role",
    "event_id",
    "control_id",
    "blind_id",
    "heatwave_start_utc",
    "heatwave_end_utc",
    "control_start_utc",
    "control_end_utc",
    "blind_start_utc",
    "blind_end_utc",
    "duration_hours",
    "row_count",
    "matching_covariates",
    "matching_distances",
    "source_artifact_version",
    "selection_seed",
    "algorithm_version",
    "eligibility_status",
    "data_quality_status",
    "gate1_outcome",
]

BLIND_POOL_COLUMNS = [
    "candidate_id",
    "start_timestamp_utc",
    "end_timestamp_utc",
    "duration_hours",
    "is_eligible",
    "is_selected",
    "rejection_codes",
    "seed",
    "algorithm_version",
    "contains_heatwave_or_buffer",
    "contains_matched_control",
    "data_completeness_status",
]


class InsufficientP6BenchmarkDataError(ValueError):
    """Exception raised when available data cannot support the requested benchmark triplets."""

    def __init__(self, reasons: tuple[str, ...], blind_pool: pd.DataFrame | None = None):
        self.reasons = tuple(reasons)
        self.blind_pool = blind_pool if blind_pool is not None else pd.DataFrame(columns=BLIND_POOL_COLUMNS)
        msg = f"Insufficient data for P6 benchmark triplets ({len(self.reasons)} blockers):\n" + "\n".join(
            f"- {r}" for r in self.reasons
        )
        super().__init__(msg)


def stable_hash_id(prefix: str, content: str) -> str:
    """Generate deterministic ID using SHA-256."""
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"


def compute_event_evaluation_window(
    event_row: dict[str, Any] | pd.Series,
    *,
    target_duration_hours: int = 120,
    target_timezone: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Compute the deterministic evaluation window for a detected heatwave.

    Scientific Rules:
    - The complete detected heatwave must be contained without truncation.
    - Target window length is exactly target_duration_hours (120h).
    - If event duration_hours > target_duration_hours, the event cannot fit
      in the window without truncation and is marked is_eligible=False.
    - If event duration_hours == target_duration_hours (e.g. 120h), context allocation
      is 0 hours before and 0 hours after (no padding), spanning exactly the heatwave.
    - For events shorter than target_duration_hours (e.g. 72h):
      surplus = target_duration_hours - duration_hours (e.g. 48h).
      Allocate evenly: pad_before = surplus // 2 (24h), pad_after = surplus - pad_before (24h).
    - Half-open interval [start_utc, end_utc) is strictly respected.
    """
    eid = str(event_row.get("event_id", ""))
    dur = int(event_row.get("duration_hours", 0))

    # Event raw bounds
    s_raw = event_row.get("event_start_utc")
    e_raw = event_row.get("event_end_utc")

    # Inspect timezone awareness
    if s_raw is None or e_raw is None:
        raise ValueError(f"Event {eid} missing event_start_utc or event_end_utc")

    s_utc = pd.to_datetime(s_raw)
    e_utc = pd.to_datetime(e_raw)

    if s_utc.tzinfo is None or e_utc.tzinfo is None:
        raise ValueError(f"Event {eid} timestamps must be timezone-aware UTC, got naive")
    s_utc = s_utc.astimezone(timezone.utc)
    e_utc = e_utc.astimezone(timezone.utc)

    if dur > target_duration_hours:
        return {
            "event_id": eid,
            "is_eligible": False,
            "ineligibility_reason": f"Event duration ({dur}h) exceeds target window duration ({target_duration_hours}h) and cannot be truncated.",
            "start_timestamp_utc": s_utc,
            "end_timestamp_utc": e_utc,
            "duration_hours": dur,
            "context_before_hours": 0,
            "context_after_hours": 0,
        }

    # Allocate surrounding context
    surplus_hours = target_duration_hours - dur
    # Deterministic integer division: half before, remainder after
    before_hours = surplus_hours // 2
    after_hours = surplus_hours - before_hours

    win_start = s_utc - pd.Timedelta(hours=before_hours)
    win_end = e_utc + pd.Timedelta(hours=after_hours)

    actual_duration = int(round((win_end - win_start).total_seconds() / 3600.0))
    if actual_duration != target_duration_hours:
        raise ValueError(f"Window duration calculation error: expected {target_duration_hours}h, got {actual_duration}h")

    return {
        "event_id": eid,
        "is_eligible": True,
        "ineligibility_reason": "NONE",
        "start_timestamp_utc": win_start,
        "end_timestamp_utc": win_end,
        "duration_hours": actual_duration,
        "context_before_hours": before_hours,
        "context_after_hours": after_hours,
    }


def validate_aligned_dataframe_signals(
    aligned_df: pd.DataFrame,
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Inspect and strictly validate canonical signals in the aligned dataset.

    Rejects:
    - Missing canonical columns (temperature, price, carbon, demand)
    - Naive or non-UTC timestamps
    - Duplicate timestamps
    - Missing, NaN, or infinite signal values
    """
    if not isinstance(aligned_df, pd.DataFrame):
        raise TypeError(f"aligned_df must be a pandas DataFrame, got {type(aligned_df).__name__}")

    if aligned_df.empty:
        return {
            "is_valid": False,
            "errors": ["aligned_df is empty"],
            "valid_timestamps": set(),
        }

    errors: list[str] = []

    # 1. Required columns
    if "timestamp_utc" not in aligned_df.columns:
        errors.append("aligned_df missing required column 'timestamp_utc'")
        return {"is_valid": False, "errors": errors, "valid_timestamps": set()}

    missing_cols = [c for c in CANONICAL_BENCHMARK_SIGNALS if c not in aligned_df.columns]
    if missing_cols:
        errors.append(f"aligned_df missing required canonical signal columns: {missing_cols}")
        if require_complete:
            raise ValueError(f"aligned_df missing required canonical signal columns: {missing_cols}")
        return {"is_valid": False, "errors": errors, "valid_timestamps": set()}

    # 2. Timestamp timezone awareness (never silently localize naive timestamps)
    ts_series = aligned_df["timestamp_utc"]
    # Check first element and series dtype
    first_ts = ts_series.iloc[0]
    if isinstance(first_ts, str):
        # Check string contains timezone offset
        parsed_first = pd.to_datetime(first_ts)
        if parsed_first.tzinfo is None:
            errors.append("aligned_df timestamp_utc contains naive timestamps; timezone-aware UTC is strictly required")
            raise ValueError("aligned_df timestamp_utc contains naive timestamps; timezone-aware UTC is strictly required")
    elif hasattr(first_ts, "tzinfo") and first_ts.tzinfo is None:
        errors.append("aligned_df timestamp_utc contains naive timestamps; timezone-aware UTC is strictly required")
        raise ValueError("aligned_df timestamp_utc contains naive timestamps; timezone-aware UTC is strictly required")
    elif pd.api.types.is_datetime64_ns_dtype(ts_series) or pd.api.types.is_datetime64_dtype(ts_series):
        if not hasattr(ts_series.dt, "tz") or ts_series.dt.tz is None:
            errors.append("aligned_df timestamp_utc dtype is timezone-naive datetime64; UTC awareness required")
            raise ValueError("aligned_df timestamp_utc dtype is timezone-naive datetime64; UTC awareness required")

    converted_ts = pd.to_datetime(ts_series)
    # Ensure all timestamps are UTC
    if any(str(t.tzinfo) not in {"UTC", "datetime.timezone.utc", "ZoneInfo(key='UTC')"} for t in converted_ts if t.tzinfo is not None):
        errors.append("aligned_df timestamp_utc contains non-UTC timezone offsets")
        raise ValueError("aligned_df timestamp_utc contains non-UTC timezone offsets")

    # 3. Duplicate timestamps check
    if converted_ts.duplicated().any():
        n_dups = int(converted_ts.duplicated().sum())
        errors.append(f"aligned_df contains {n_dups} duplicate timestamps")
        if require_complete:
            raise ValueError(f"aligned_df contains {n_dups} duplicate timestamps")

    # 4. Check finite values
    valid_mask = np.ones(len(aligned_df), dtype=bool)
    for col in CANONICAL_BENCHMARK_SIGNALS:
        s_vals = pd.to_numeric(aligned_df[col], errors="coerce")
        non_finite = s_vals.isna() | np.isinf(s_vals)
        if non_finite.any():
            n_bad = int(non_finite.sum())
            errors.append(f"aligned_df signal '{col}' contains {n_bad} missing or non-finite values")
            valid_mask &= ~non_finite.to_numpy()

    valid_rows = aligned_df[valid_mask]
    valid_ts = set(pd.to_datetime(valid_rows["timestamp_utc"], utc=True))

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "valid_timestamps": valid_ts,
    }


def build_candidate_blind_windows(
    aligned_df: pd.DataFrame,
    event_catalogue_df: pd.DataFrame,
    control_catalogue_df: pd.DataFrame | None,
    *,
    window_duration_hours: int = 120,
    buffer_hours: int = 48,
    study_years: list[int] | None = None,
    study_months: list[int] | None = None,
    target_timezone: str = "America/Los_Angeles",
    seed: int = 20261016,
    version: str = "1.0",
) -> pd.DataFrame:
    """Generate deterministic candidate blind windows and audit eligibility.

    Exclusions:
    - Every detected heatwave window (onset to recovery inclusive).
    - 48-hour buffer before onset and 48-hour buffer after recovery.
    - Matched control windows.
    - Incomplete canonical signals (temperature, price, carbon, demand).
    """
    if study_years is None:
        study_years = [2022, 2023, 2024, 2025]
    if study_months is None:
        study_months = [6, 7, 8, 9]

    # Validate aligned signals and schema
    val_res = validate_aligned_dataframe_signals(aligned_df, require_complete=False)
    aligned_valid_signals_set = val_res["valid_timestamps"]

    # Pre-calculate heatwave exclusion intervals using centralized window helper
    hw_blocked_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    if event_catalogue_df is not None and not event_catalogue_df.empty:
        for _, row in event_catalogue_df.iterrows():
            win_info = compute_event_evaluation_window(
                row, target_duration_hours=window_duration_hours, target_timezone=target_timezone
            )
            s_utc = win_info["start_timestamp_utc"]
            e_utc = win_info["end_timestamp_utc"]
            # Apply 48-hour exclusion buffer on both sides
            buf_s = s_utc - pd.Timedelta(hours=buffer_hours)
            buf_e = e_utc + pd.Timedelta(hours=buffer_hours)
            hw_blocked_intervals.append((buf_s, buf_e))

    # Pre-calculate control exclusion intervals
    ctrl_blocked_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    if control_catalogue_df is not None and not control_catalogue_df.empty:
        for _, row in control_catalogue_df.iterrows():
            s_raw = row["start_timestamp_utc"]
            e_raw = row["end_timestamp_utc"]
            s_utc = pd.to_datetime(s_raw)
            e_utc = pd.to_datetime(e_raw)
            if s_utc.tzinfo is None or e_utc.tzinfo is None:
                raise ValueError("Control catalogue timestamps must be timezone-aware")
            ctrl_blocked_intervals.append((s_utc.astimezone(timezone.utc), e_utc.astimezone(timezone.utc)))

    candidates: list[dict[str, Any]] = []
    days_in_window = window_duration_hours // 24

    for yr in study_years:
        season_start = date(yr, min(study_months), 1)
        season_end = date(yr, max(study_months), 30)
        max_start = season_end - timedelta(days=days_in_window - 1)

        cur = season_start
        while cur <= max_start:
            end_incl = cur + timedelta(days=days_in_window - 1)
            s_utc_bound, _, _ = get_local_day_utc_bounds(cur.isoformat(), target_timezone=target_timezone)
            _, e_utc_bound, _ = get_local_day_utc_bounds(end_incl.isoformat(), target_timezone=target_timezone)

            win_s = pd.to_datetime(s_utc_bound, utc=True)
            win_e = pd.to_datetime(e_utc_bound, utc=True)

            cand_content = f"{cur.isoformat()}_{end_incl.isoformat()}_{window_duration_hours}_{seed}_{version}"
            cand_id = stable_hash_id("BLIND", cand_content)

            rejections: list[str] = []
            has_hw_overlap = False
            has_ctrl_overlap = False

            # 1. Overlap with any heatwave or 48h buffer
            for hw_s, hw_e in hw_blocked_intervals:
                if max(win_s, hw_s) < min(win_e, hw_e):
                    has_hw_overlap = True
                    break
            if has_hw_overlap:
                rejections.append("overlaps_heatwave_event_or_48h_buffer")

            # 2. Overlap with matched control
            for ctrl_s, ctrl_e in ctrl_blocked_intervals:
                if max(win_s, ctrl_s) < min(win_e, ctrl_e):
                    has_ctrl_overlap = True
                    break
            if has_ctrl_overlap:
                rejections.append("overlaps_matched_control")

            # 3. Data completeness check
            if not val_res["is_valid"] and any("missing required canonical signal" in err for err in val_res["errors"]):
                rejections.append("missing_canonical_schema")
            else:
                expected_hours = pd.date_range(win_s, win_e - pd.Timedelta(hours=1), freq="1h")
                missing_signals = [ts for ts in expected_hours if ts not in aligned_valid_signals_set]
                if missing_signals:
                    rejections.append(f"missing_or_non_finite_signals_count_{len(missing_signals)}")

            is_eligible = len(rejections) == 0

            candidates.append({
                "candidate_id": cand_id,
                "start_timestamp_utc": win_s.isoformat(),
                "end_timestamp_utc": win_e.isoformat(),
                "duration_hours": window_duration_hours,
                "is_eligible": is_eligible,
                "is_selected": False,
                "rejection_codes": ";".join(rejections) if rejections else "NONE",
                "seed": seed,
                "algorithm_version": version,
                "contains_heatwave_or_buffer": has_hw_overlap,
                "contains_matched_control": has_ctrl_overlap,
                "data_completeness_status": "complete" if is_eligible else "incomplete",
            })

            cur += timedelta(days=1)

    return pd.DataFrame(candidates, columns=BLIND_POOL_COLUMNS)


def validate_p6_benchmark_triplets(
    hourly_df: pd.DataFrame,
    triplet_index_df: pd.DataFrame,
    *,
    design_mode: str = "primary",  # "primary" or "fallback"
    expected_duration_hours: int = 120,
) -> dict[str, Any]:
    """Validate in-memory P6 benchmark triplets and index against Gate 1 invariants.

    Invariants strictly enforced:
    - Non-empty DataFrames.
    - Exact cardinality (1 dev + 4 conf = 5 for primary; 1 dev + 3 conf = 4 for fallback).
    - Valid roles ('development', 'confirmatory') only.
    - Non-overlapping half-open intervals [start, end) across all windows and triplets.
    - All IDs unique (no duplicate triplet, event, control, or blind IDs).
    - No window ID reused across different contexts or triplets.
    - Strict relational integrity between hourly_df and triplet_index_df:
      - Every hourly triplet_id must exist in index.
      - Every index triplet must exist in hourly data.
      - Every hourly window_id must match the indexed ID for its triplet and window_type.
      - Valid window_type enum ('heatwave', 'control', 'event_blind').
    - Exact row-count contracts:
      - 120 rows per window.
      - 360 rows per triplet.
      - 1,800 rows for primary, 1,440 rows for fallback.
    - Timestamp integrity:
      - Strictly timezone-aware UTC (reject naive or non-UTC).
      - Strictly increasing, contiguous 1-hour intervals matching index bounds exactly.
      - No duplicate (triplet_id, window_type, timestamp_utc) keys.
    - Canonical signals present, non-null, and finite.
    """
    errors: list[str] = []

    if not isinstance(hourly_df, pd.DataFrame):
        raise TypeError("hourly_df must be a pandas DataFrame")
    if not isinstance(triplet_index_df, pd.DataFrame):
        raise TypeError("triplet_index_df must be a pandas DataFrame")

    if triplet_index_df.empty:
        raise ValueError("triplet_index_df cannot be empty")
    if hourly_df.empty:
        raise ValueError("hourly_df cannot be empty")

    if design_mode not in {"primary", "fallback"}:
        raise ValueError(f"Unknown design_mode '{design_mode}'. Must be 'primary' or 'fallback'")

    # 1. Index Cardinality & Roles
    valid_roles = {"development", "confirmatory"}
    invalid_roles = set(triplet_index_df["role"].unique()) - valid_roles
    if invalid_roles:
        errors.append(f"triplet_index_df contains invalid role(s): {sorted(invalid_roles)}")

    dev_rows = triplet_index_df[triplet_index_df["role"] == "development"]
    conf_rows = triplet_index_df[triplet_index_df["role"] == "confirmatory"]

    if len(dev_rows) != 1:
        errors.append(f"Expected exactly 1 development triplet, got {len(dev_rows)}")

    expected_conf = 4 if design_mode == "primary" else 3
    if len(conf_rows) != expected_conf:
        errors.append(f"Expected exactly {expected_conf} confirmatory triplets in {design_mode} mode, got {len(conf_rows)}")

    expected_triplets = 1 + expected_conf
    if len(triplet_index_df) != expected_triplets:
        errors.append(f"Expected {expected_triplets} total index rows in {design_mode} mode, got {len(triplet_index_df)}")

    # 2. Index ID Uniqueness
    for id_col in ["triplet_id", "event_id", "control_id", "blind_id"]:
        if triplet_index_df[id_col].duplicated().any():
            dups = triplet_index_df[triplet_index_df[id_col].duplicated()][id_col].tolist()
            errors.append(f"triplet_index_df contains duplicate {id_col} values: {dups}")

    # Cross-category window ID reuse
    all_window_ids = (
        triplet_index_df["event_id"].tolist()
        + triplet_index_df["control_id"].tolist()
        + triplet_index_df["blind_id"].tolist()
    )
    if len(all_window_ids) != len(set(all_window_ids)):
        errors.append("Window ID reused across different window types or triplets in index")

    # 3. Index Interval & Duration Validation
    windows: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    indexed_windows_map: dict[str, dict[str, Any]] = {}

    for _, trow in triplet_index_df.iterrows():
        tid = trow["triplet_id"]
        dur = trow["duration_hours"]
        rc = trow["row_count"]
        if dur != expected_duration_hours:
            errors.append(f"Triplet {tid} duration_hours {dur} != expected {expected_duration_hours}")
        if rc != expected_duration_hours:
            errors.append(f"Triplet {tid} row_count {rc} != expected {expected_duration_hours}")

        for ctx_label, role_prefix in [("heatwave", "heatwave"), ("control", "control"), ("event_blind", "blind")]:
            s_col = f"{role_prefix}_start_utc"
            e_col = f"{role_prefix}_end_utc"
            id_col = "event_id" if role_prefix == "heatwave" else ("control_id" if role_prefix == "control" else "blind_id")
            wid = trow[id_col]

            s_val = trow[s_col]
            e_val = trow[e_col]

            # Check timezone awareness in index
            s_ts = pd.to_datetime(s_val)
            e_ts = pd.to_datetime(e_val)
            if s_ts.tzinfo is None or e_ts.tzinfo is None:
                errors.append(f"Window {wid} timestamp in index is naive; UTC awareness required")
            else:
                s_ts = s_ts.astimezone(timezone.utc)
                e_ts = e_ts.astimezone(timezone.utc)

            if s_ts >= e_ts:
                errors.append(f"Window {wid} invalid interval: start {s_ts} >= end {e_ts}")
            diff_h = (e_ts - s_ts).total_seconds() / 3600.0
            if int(round(diff_h)) != expected_duration_hours:
                errors.append(f"Window {wid} interval length {diff_h}h != expected {expected_duration_hours}h")

            windows.append((f"{tid}:{wid}", s_ts, e_ts))
            indexed_windows_map[f"{tid}:{ctx_label}"] = {
                "window_id": wid,
                "start_utc": s_ts,
                "end_utc": e_ts,
            }

    # Mutual non-overlap across all windows of all triplets
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            w1_name, w1_s, w1_e = windows[i]
            w2_name, w2_s, w2_e = windows[j]
            if max(w1_s, w2_s) < min(w1_e, w2_e):
                errors.append(f"Selected windows overlap: {w1_name} [{w1_s}, {w1_e}) and {w2_name} [{w2_s}, {w2_e})")

    # 4. Hourly Schema & Row Counts
    req_hourly_cols = {"timestamp_utc", "triplet_id", "window_type", "window_id", "phase_label"}
    missing_h_cols = req_hourly_cols - set(hourly_df.columns)
    if missing_h_cols:
        errors.append(f"hourly_df missing required columns: {sorted(missing_h_cols)}")

    expected_total_rows = expected_triplets * 3 * expected_duration_hours
    if len(hourly_df) != expected_total_rows:
        errors.append(f"hourly_df total rows {len(hourly_df)} != expected {expected_total_rows} ({expected_triplets} triplets * 360h)")

    # 5. Relational Checks between hourly_df and triplet_index_df
    hourly_triplet_ids = set(hourly_df["triplet_id"].unique())
    index_triplet_ids = set(triplet_index_df["triplet_id"].unique())

    # Hourly triplet absent from index
    extra_hourly_triplets = hourly_triplet_ids - index_triplet_ids
    if extra_hourly_triplets:
        errors.append(f"hourly_df contains triplet_id values absent from index: {sorted(extra_hourly_triplets)}")

    # Index triplet absent from hourly data
    missing_index_triplets = index_triplet_ids - hourly_triplet_ids
    if missing_index_triplets:
        errors.append(f"triplet_index_df contains triplet_id values absent from hourly_df: {sorted(missing_index_triplets)}")

    # Allowed window types
    valid_window_types = {"heatwave", "control", "event_blind"}
    invalid_win_types = set(hourly_df["window_type"].unique()) - valid_window_types
    if invalid_win_types:
        errors.append(f"hourly_df contains invalid window_type values: {sorted(invalid_win_types)}")

    # Global unique key: (triplet_id, window_type, timestamp_utc)
    if hourly_df.duplicated(subset=["triplet_id", "window_type", "timestamp_utc"]).any():
        errors.append("hourly_df contains duplicate keys for (triplet_id, window_type, timestamp_utc)")

    # 6. Detailed Window Verification in hourly_df
    first_ts = hourly_df["timestamp_utc"].iloc[0]
    if isinstance(first_ts, str):
        parsed = pd.to_datetime(first_ts)
        if parsed.tzinfo is None:
            errors.append("hourly_df timestamp_utc contains naive timestamps; UTC awareness required")
    elif hasattr(first_ts, "tzinfo") and first_ts.tzinfo is None:
        errors.append("hourly_df timestamp_utc contains naive timestamps; UTC awareness required")
    elif pd.api.types.is_datetime64_ns_dtype(hourly_df["timestamp_utc"]) or pd.api.types.is_datetime64_dtype(hourly_df["timestamp_utc"]):
        if not hasattr(hourly_df["timestamp_utc"].dt, "tz") or hourly_df["timestamp_utc"].dt.tz is None:
            errors.append("hourly_df timestamp_utc is timezone-naive datetime64")

    # Group by triplet_id and window_type
    for (tid, wtype), group in hourly_df.groupby(["triplet_id", "window_type"]):
        key = f"{tid}:{wtype}"
        if key not in indexed_windows_map:
            errors.append(f"hourly_df group ({tid}, {wtype}) not found in index mapping")
            continue

        target_info = indexed_windows_map[key]
        expected_wid = target_info["window_id"]
        expected_s = target_info["start_utc"]
        expected_e = target_info["end_utc"]

        # Window ID match
        actual_wids = set(group["window_id"].unique())
        if actual_wids != {expected_wid}:
            errors.append(f"hourly_df window_id for {key} is {actual_wids}, expected {expected_wid}")

        # Window row count
        if len(group) != expected_duration_hours:
            errors.append(f"hourly_df group {key} row count {len(group)} != expected {expected_duration_hours}")

        # Timestamps
        g_ts = pd.to_datetime(group["timestamp_utc"], utc=True).sort_values()
        if g_ts.iloc[0] != expected_s or (g_ts.iloc[-1] + pd.Timedelta(hours=1)) != expected_e:
            errors.append(
                f"hourly_df group {key} time range [{g_ts.iloc[0]}, {g_ts.iloc[-1] + pd.Timedelta(hours=1)}) != indexed range [{expected_s}, {expected_e})"
            )

        # Contiguity and uniqueness
        if len(g_ts) > 1:
            diffs = g_ts.diff().dropna()
            if not (diffs == pd.Timedelta(hours=1)).all():
                errors.append(f"hourly_df group {key} has non-contiguous or non-hourly timestamps")

    # 7. Canonical Signals
    for sig in CANONICAL_BENCHMARK_SIGNALS:
        if sig not in hourly_df.columns:
            errors.append(f"hourly_df missing required canonical signal column: '{sig}'")
        else:
            s_vals = pd.to_numeric(hourly_df[sig], errors="coerce")
            non_finite = s_vals.isna() | np.isinf(s_vals)
            if non_finite.any():
                n_bad = int(non_finite.sum())
                errors.append(f"hourly_df signal '{sig}' contains {n_bad} missing or non-finite values")

    if errors:
        raise ValueError(f"Triplet validation failed with {len(errors)} errors:\n" + "\n".join(f"- {e}" for e in errors))

    return {
        "valid": True,
        "design_mode": design_mode,
        "triplet_count": len(triplet_index_df),
        "development_triplets": len(dev_rows),
        "confirmatory_triplets": len(conf_rows),
        "total_hourly_rows": len(hourly_df),
        "duration_hours": expected_duration_hours,
    }


def build_p6_benchmark_triplets(
    aligned_df: pd.DataFrame,
    event_catalogue_df: pd.DataFrame,
    config: dict[str, Any],
    *,
    control_catalogue_df: pd.DataFrame | None = None,
    design_mode: str = "primary",  # "primary" or "fallback"
    random_seed: int = 20261016,
    version: str = "1.0",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pure in-memory builder for P6 benchmark triplets and candidate audit pool.

    Enforces deterministic selection without consulting downstream outcomes.
    If data sufficiency conditions are not met, raises InsufficientP6BenchmarkDataError
    with structured blockers and the audited blind pool.
    When sufficient data exists, returns:
        (hourly_df, triplet_index_df, blind_pool_df)
    """
    if design_mode not in {"primary", "fallback"}:
        raise ValueError(f"Invalid design_mode '{design_mode}'. Must be 'primary' or 'fallback'")

    target_duration_hours = int(config.get("duration_hours", 120))
    buffer_hours = int(config.get("buffer_hours", 48))
    target_timezone = config.get("target_timezone", "America/Los_Angeles")

    # 1. Audit candidate blind pool
    blind_pool_df = build_candidate_blind_windows(
        aligned_df=aligned_df,
        event_catalogue_df=event_catalogue_df,
        control_catalogue_df=control_catalogue_df,
        window_duration_hours=target_duration_hours,
        buffer_hours=buffer_hours,
        target_timezone=target_timezone,
        seed=random_seed,
        version=version,
    )

    # 2. Evaluate available heatwaves using centralized window calculator
    eligible_events: list[dict[str, Any]] = []
    if event_catalogue_df is not None and not event_catalogue_df.empty:
        for _, ev in event_catalogue_df.iterrows():
            win_info = compute_event_evaluation_window(
                ev, target_duration_hours=target_duration_hours, target_timezone=target_timezone
            )
            if win_info["is_eligible"]:
                eligible_events.append({
                    "event_id": win_info["event_id"],
                    "start_utc": win_info["start_timestamp_utc"],
                    "end_utc": win_info["end_timestamp_utc"],
                    "duration_hours": win_info["duration_hours"],
                    "raw_event": dict(ev),
                })

    # Sort events deterministically by start_utc, then event_id
    eligible_events.sort(key=lambda x: (x["start_utc"], x["event_id"]))

    # 3. Available controls
    eligible_controls: list[dict[str, Any]] = []
    if control_catalogue_df is not None and not control_catalogue_df.empty:
        for _, ctrl in control_catalogue_df.iterrows():
            is_elig = bool(ctrl.get("is_eligible", False))
            dur = int(ctrl.get("duration_hours", 0))
            if is_elig and dur == target_duration_hours:
                s_raw = ctrl["start_timestamp_utc"]
                e_raw = ctrl["end_timestamp_utc"]
                s_utc = pd.to_datetime(s_raw, utc=True)
                e_utc = pd.to_datetime(e_raw, utc=True)
                eligible_controls.append({
                    "control_id": str(ctrl["control_id"]),
                    "matched_event_id": str(ctrl.get("matched_event_id", "")),
                    "start_utc": s_utc,
                    "end_utc": e_utc,
                    "duration_hours": dur,
                    "raw_control": dict(ctrl),
                })

    # Sort controls deterministically
    eligible_controls.sort(key=lambda x: (x["start_utc"], x["control_id"]))

    # 4. Check continuous signal coverage in aligned_df
    val_res = validate_aligned_dataframe_signals(aligned_df, require_complete=False)
    aligned_valid_signals_set = val_res["valid_timestamps"]

    # Events with continuous signals
    events_with_continuous_signals: list[dict[str, Any]] = []
    for ev in eligible_events:
        ev_hours = pd.date_range(ev["start_utc"], ev["end_utc"] - pd.Timedelta(hours=1), freq="1h")
        if all(ts in aligned_valid_signals_set for ts in ev_hours):
            events_with_continuous_signals.append(ev)

    # Controls with continuous signals
    controls_with_continuous_signals: list[dict[str, Any]] = []
    for ctrl in eligible_controls:
        ctrl_hours = pd.date_range(ctrl["start_utc"], ctrl["end_utc"] - pd.Timedelta(hours=1), freq="1h")
        if all(ts in aligned_valid_signals_set for ts in ctrl_hours):
            controls_with_continuous_signals.append(ctrl)

    # Eligible blind candidates
    eligible_blinds = blind_pool_df[blind_pool_df["is_eligible"]].copy()

    # Determine required counts
    required_triplets = 5 if design_mode == "primary" else 4

    # Compile structured failure blockers
    blockers: list[str] = []
    if event_catalogue_df is None or len(event_catalogue_df) < required_triplets:
        count = len(event_catalogue_df) if event_catalogue_df is not None else 0
        blockers.append(f"Insufficient distinct heatwaves: catalogue contains {count} (minimum {required_triplets} required for {design_mode} mode)")

    if len(eligible_events) < required_triplets:
        blockers.append(
            f"Insufficient complete event windows: only {len(eligible_events)} detected heatwaves fit within the frozen {target_duration_hours}h window without truncation ({[e['event_id'] for e in eligible_events]})"
        )

    if len(events_with_continuous_signals) < required_triplets:
        blockers.append(
            f"Insufficient complete heatwave windows with canonical signals: only {len(events_with_continuous_signals)} event(s) have complete signals in aligned_df ({[e['event_id'] for e in events_with_continuous_signals]})"
        )

    if len(controls_with_continuous_signals) < required_triplets:
        blockers.append(
            f"Insufficient unique eligible controls with canonical signals: only {len(controls_with_continuous_signals)} control(s) available (minimum {required_triplets} required)"
        )

    if len(eligible_blinds) < required_triplets:
        blockers.append(
            f"Insufficient eligible blind windows with complete canonical signals: only {len(eligible_blinds)} available (minimum {required_triplets} required)"
        )

    # If blockers exist, fail loudly with structured exception
    if blockers:
        raise InsufficientP6BenchmarkDataError(tuple(blockers), blind_pool=blind_pool_df)

    # ---------------------------------------------------------------------------
    # Successful Path: Deterministic Selection & Triplet Materialization
    # ---------------------------------------------------------------------------
    # In fallback mode, human approval mandates HW_20240702 as development event,
    # and 2022 events as confirmatory events.
    if design_mode == "fallback":
        dev_candidates = [e for e in events_with_continuous_signals if e["event_id"] == "HW_20240702"]
        conf_candidates = [e for e in events_with_continuous_signals if e["event_id"] in {"HW_20220620", "HW_20220904", "HW_20220922"}]
        conf_candidates.sort(key=lambda x: (x["start_utc"], x["event_id"]))
        if dev_candidates and len(conf_candidates) >= 3:
            selected_events = [dev_candidates[0]] + conf_candidates[:3]
        else:
            selected_events = events_with_continuous_signals[:required_triplets]
    else:
        selected_events = events_with_continuous_signals[:required_triplets]

    # Select controls: match by matched_event_id or deterministic distance/date ordering
    selected_controls: list[dict[str, Any]] = []
    used_ctrl_ids: set[str] = set()

    for ev in selected_events:
        # Look for direct match first
        direct_match = [c for c in controls_with_continuous_signals if c["matched_event_id"] == ev["event_id"] and c["control_id"] not in used_ctrl_ids]
        if direct_match:
            chosen = direct_match[0]
        else:
            avail = [
                c for c in controls_with_continuous_signals
                if c["control_id"] not in used_ctrl_ids
                and not (max(ev["start_utc"], c["start_utc"]) < min(ev["end_utc"], c["end_utc"]))
            ]
            if not avail:
                raise InsufficientP6BenchmarkDataError(
                    (f"Unable to find non-overlapping unique control for event {ev['event_id']}",),
                    blind_pool=blind_pool_df,
                )
            chosen = avail[0]

        selected_controls.append(chosen)
        used_ctrl_ids.add(chosen["control_id"])

    # Select blind windows: deterministic sort using SHA-256 hash of seed + candidate_id
    occupied_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = [
        (e["start_utc"], e["end_utc"]) for e in selected_events
    ] + [(c["start_utc"], c["end_utc"]) for c in selected_controls]

    def blind_sort_key(b_row: pd.Series) -> str:
        s_val = f"{random_seed}_{b_row['candidate_id']}_{b_row['start_timestamp_utc']}"
        return hashlib.sha256(s_val.encode("utf-8")).hexdigest()

    eligible_blinds["sort_key"] = eligible_blinds.apply(blind_sort_key, axis=1)
    eligible_blinds = eligible_blinds.sort_values("sort_key").reset_index(drop=True)

    selected_blinds: list[dict[str, Any]] = []
    for _, b_row in eligible_blinds.iterrows():
        b_s = pd.to_datetime(b_row["start_timestamp_utc"], utc=True)
        b_e = pd.to_datetime(b_row["end_timestamp_utc"], utc=True)

        overlaps = False
        for occ_s, occ_e in occupied_intervals:
            if max(b_s, occ_s) < min(b_e, occ_e):
                overlaps = True
                break

        if not overlaps:
            selected_blinds.append({
                "candidate_id": str(b_row["candidate_id"]),
                "start_utc": b_s,
                "end_utc": b_e,
                "duration_hours": target_duration_hours,
            })
            occupied_intervals.append((b_s, b_e))
            if len(selected_blinds) == required_triplets:
                break

    if len(selected_blinds) < required_triplets:
        raise InsufficientP6BenchmarkDataError(
            (f"Only {len(selected_blinds)} mutually non-overlapping blind windows could be selected (need {required_triplets})",),
            blind_pool=blind_pool_df,
        )

    # Mark is_selected in blind_pool_df
    selected_blind_ids = {b["candidate_id"] for b in selected_blinds}
    blind_pool_df["is_selected"] = blind_pool_df["candidate_id"].isin(selected_blind_ids)

    # 5. Build Triplet Index and Hourly Datasets
    index_rows: list[dict[str, Any]] = []
    hourly_dfs: list[pd.DataFrame] = []

    aligned_indexed = aligned_df.copy()
    aligned_indexed["ts_utc_key"] = pd.to_datetime(aligned_indexed["timestamp_utc"], utc=True)
    aligned_map = aligned_indexed.set_index("ts_utc_key")

    for i in range(required_triplets):
        role = "development" if i == 0 else "confirmatory"
        triplet_hash = stable_hash_id("TRIPLET", f"{i}_{selected_events[i]['event_id']}_{random_seed}_{version}")
        triplet_id = f"TRIPLET_DEV_{triplet_hash[-6:]}" if role == "development" else f"TRIPLET_CONF_{i}_{triplet_hash[-6:]}"

        ev = selected_events[i]
        ctrl = selected_controls[i]
        blind = selected_blinds[i]

        ctrl_raw = ctrl.get("raw_control", {})
        m_score = ctrl_raw.get("matching_score", 0.0)
        t_dist = ctrl_raw.get("target_temperature_distance_c", 0.0)
        matching_dist_str = f"score={m_score};temp_dist_c={t_dist}"

        index_rows.append({
            "triplet_id": triplet_id,
            "role": role,
            "event_id": ev["event_id"],
            "control_id": ctrl["control_id"],
            "blind_id": blind["candidate_id"],
            "heatwave_start_utc": ev["start_utc"].isoformat(),
            "heatwave_end_utc": ev["end_utc"].isoformat(),
            "control_start_utc": ctrl["start_utc"].isoformat(),
            "control_end_utc": ctrl["end_utc"].isoformat(),
            "blind_start_utc": blind["start_utc"].isoformat(),
            "blind_end_utc": blind["end_utc"].isoformat(),
            "duration_hours": target_duration_hours,
            "row_count": target_duration_hours,
            "matching_covariates": "calendar_distance_and_noaa_temperature",
            "matching_distances": matching_dist_str,
            "source_artifact_version": version,
            "selection_seed": random_seed,
            "algorithm_version": version,
            "eligibility_status": "eligible",
            "data_quality_status": "verified_valid",
            "gate1_outcome": "PASS",
        })

        # Extract hourly rows for each member window
        for ctx_label, wid, s_utc, e_utc in [
            ("heatwave", ev["event_id"], ev["start_utc"], ev["end_utc"]),
            ("control", ctrl["control_id"], ctrl["start_utc"], ctrl["end_utc"]),
            ("event_blind", blind["candidate_id"], blind["start_utc"], blind["end_utc"]),
        ]:
            hrs = pd.date_range(s_utc, e_utc - pd.Timedelta(hours=1), freq="1h")
            w_rows = aligned_map.loc[hrs].copy()
            w_df = pd.DataFrame({
                "timestamp_utc": hrs,
                "triplet_id": triplet_id,
                "window_type": ctx_label,
                "window_id": wid,
                "phase_label": ctx_label,
                "temperature_c": pd.to_numeric(w_rows["temperature_c"]).values,
                "price_usd_per_mwh": pd.to_numeric(w_rows["price_usd_per_mwh"]).values,
                "carbon_g_per_kwh": pd.to_numeric(w_rows["carbon_g_per_kwh"]).values,
                "demand_mw": pd.to_numeric(w_rows["demand_mw"]).values,
            })
            hourly_dfs.append(w_df)

    hourly_df = pd.concat(hourly_dfs, ignore_index=True)
    triplet_index_df = pd.DataFrame(index_rows, columns=INDEX_COLUMNS)

    # Validate before returning
    validate_p6_benchmark_triplets(
        hourly_df=hourly_df,
        triplet_index_df=triplet_index_df,
        design_mode=design_mode,
        expected_duration_hours=target_duration_hours,
    )

    return hourly_df, triplet_index_df, blind_pool_df


def parse_caiso_historical_group_zips(
    directory: Path | str,
    target_node: str = "TH_NP15_GEN-APND",
    market_run_id: str = "DAM",
    lmp_type: str = "LMP",
    xml_data_item: str = "LMP_PRC",
) -> pd.DataFrame:
    """Parse historical CAISO daily group ZIP archives.

    Extracts canonical DAM LMP observations without modifying or extracting
    the source archives permanently. Validates node, market, type, finiteness,
    and returns sorted UTC-aware DataFrame.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Historical CAISO directory not found: {directory}")

    target_bytes = target_node.encode("utf-8")
    rows: list[dict[str, Any]] = []
    seen_timestamps: dict[pd.Timestamp, float] = {}

    for zpath in sorted(directory.rglob("*.zip")):
        with zipfile.ZipFile(zpath, "r") as zf:
            for name in zf.namelist():
                if "PRC_LMP_DAM_LMP" in name and name.endswith(".csv"):
                    with zf.open(name) as f:
                        header_line = f.readline().decode("utf-8").strip()
                        header = header_line.split(",")
                        idx_start = header.index("INTERVALSTARTTIME_GMT")
                        idx_node = header.index("NODE")
                        idx_market = header.index("MARKET_RUN_ID")
                        idx_type = header.index("LMP_TYPE")
                        idx_item = header.index("XML_DATA_ITEM")
                        idx_val = header.index("MW")

                        for line in f:
                            if target_bytes in line:
                                parts = line.decode("utf-8").strip().split(",")
                                if (
                                    parts[idx_node] == target_node
                                    and parts[idx_market] == market_run_id
                                    and parts[idx_type] == lmp_type
                                    and parts[idx_item] == xml_data_item
                                ):
                                    ts = pd.to_datetime(parts[idx_start], utc=True)
                                    val = float(parts[idx_val])
                                    if not np.isfinite(val):
                                        raise ValueError(f"Non-finite LMP price observed at {ts}: {val}")
                                    if ts in seen_timestamps:
                                        prev_val = seen_timestamps[ts]
                                        if abs(prev_val - val) > 1e-4:
                                            raise ValueError(
                                                f"Conflicting duplicate LMP price for {ts}: existing={prev_val} vs new={val} in {zpath.name}"
                                            )
                                        # Identical duplicate: ignore
                                        continue

                                    seen_timestamps[ts] = val
                                    rows.append({
                                        "timestamp_utc": ts,
                                        "price_usd_per_mwh": val,
                                        "node_id": target_node,
                                        "market_run_id": market_run_id,
                                        "lmp_type": lmp_type,
                                    })

    if not rows:
        return pd.DataFrame(columns=["timestamp_utc", "price_usd_per_mwh", "node_id", "market_run_id", "lmp_type"])

    df = pd.DataFrame(rows).sort_values("timestamp_utc").reset_index(drop=True)
    return df


def parse_ciso_xlsx_carbon_streaming(
    xlsx_path: Path | str,
    target_timestamps_utc: set[pd.Timestamp] | list[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """Fast bounded single-pass streaming parser for CISO.xlsx carbon intensity.

    Reads xl/worksheets/sheet1.xml in 8MB chunks using regex without loading the entire
    97MB workbook into memory. Extracts column B (serial timestamp end) and column CR
    (CO2 emissions intensity for consumed electricity, lb/kWh), converted to g/kWh via
    factor 453.59237.
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise FileNotFoundError(f"CISO.xlsx not found: {xlsx_path}")

    target_set = set(target_timestamps_utc) if target_timestamps_utc is not None else None

    from heattrace.ingest.eia import _excel_serial_to_utc
    import re

    pattern = re.compile(rb'<row r="(\d+)"[^>]*>(.*?)</row>')
    b_pattern = re.compile(rb'<c r="B\d+"[^>]*><v>([^<]+)</v></c>')
    cr_pattern = re.compile(rb'<c r="CR\d+"[^>]*><v>([^<]+)</v></c>')

    carbon_map: dict[pd.Timestamp, float] = {}

    with zipfile.ZipFile(xlsx_path, "r") as z:
        with z.open("xl/worksheets/sheet1.xml") as f:
            f.readline()  # skip xml declaration
            chunk_size = 1024 * 1024 * 8
            remainder = b""
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                data = remainder + chunk
                last_idx = data.rfind(b"</row>")
                if last_idx == -1:
                    remainder = data
                    continue
                to_process = data[:last_idx + 6]
                remainder = data[last_idx + 6:]
                for m in pattern.finditer(to_process):
                    row_xml = m.group(2)
                    b_match = b_pattern.search(row_xml)
                    if not b_match:
                        continue
                    serial_val = float(b_match.group(1).decode("ascii"))
                    dt_end = _excel_serial_to_utc(serial_val)
                    dt_start = dt_end.replace(minute=0, second=0, microsecond=0) - pd.Timedelta(hours=1)

                    if target_set is None or dt_start in target_set:
                        cr_match = cr_pattern.search(row_xml)
                        con_lb = float(cr_match.group(1).decode("ascii")) if cr_match else None
                        if con_lb is not None:
                            val_g = round(con_lb * 453.59237, 4)
                            if not np.isfinite(val_g):
                                raise ValueError(f"Non-finite carbon intensity at {dt_start}: {val_g}")
                            if dt_start in carbon_map:
                                prev_val = carbon_map[dt_start]
                                if abs(prev_val - val_g) > 1e-4:
                                    raise ValueError(
                                        f"Conflicting duplicate carbon intensity for {dt_start}: existing={prev_val} vs new={val_g}"
                                    )
                                continue
                            carbon_map[dt_start] = val_g

    records = [{"timestamp_utc": ts, "carbon_g_per_kwh": val} for ts, val in sorted(carbon_map.items())]
    return pd.DataFrame(records, columns=["timestamp_utc", "carbon_g_per_kwh"])


def materialize_p6_gate1_benchmarks(
    repo_root: Path | str = ".",
    config_dir: Path | str = "configs",
    data_dir: Path | str = "data",
    random_seed: int = 20261016,
    design_mode: str = "fallback",
    version: str = "1.0",
) -> dict[str, Any]:
    """Reproducible end-to-end pipeline to materialize all Phase 1 / Gate 1 benchmark artifacts.

    Regenerates:
    1. data/events/control_catalogue_v0.parquet & csv
    2. data/benchmarks/p6_event_blind_pool.csv
    3. data/benchmarks/p6_event_control_index.csv
    4. data/benchmarks/p6_event_control_pairs.parquet
    5. data/manifests/p6_gate1_benchmark_manifest.json

    Guarantees:
    - Pure atomic writes.
    - Idempotent and deterministic.
    - Zero data leakage.
    - Complete validation before returning.
    """
    repo_root = Path(repo_root).resolve()
    config_dir = Path(config_dir)
    if not config_dir.is_absolute():
        config_dir = (repo_root / config_dir).resolve()
    data_dir = Path(data_dir)
    if not data_dir.is_absolute():
        data_dir = (repo_root / data_dir).resolve()

    from heattrace.config import load_yaml
    from heattrace.ingest.provenance import sha256_file
    from heattrace.process.controls import build_fallback_controls, validate_control_dataframe
    from heattrace.process.alignment import aggregate_noaa_hourly_temperature
    from heattrace.ingest.caiso import parse_caiso_zip
    import tempfile
    import os

    def _rel(p: Path) -> str:
        p_res = p.resolve()
        if p_res.is_relative_to(repo_root):
            return str(p_res.relative_to(repo_root))
        if p.is_relative_to(repo_root):
            return str(p.relative_to(repo_root))
        return str(p)

    # 1. Stage A: Deterministic Identity Derivation and Candidate Ranking
    # (Uses ONLY permitted temporal, calendar, weather and configuration inputs; NO CAISO/EIA outcomes)
    ctrl_res = build_fallback_controls(data_dir=data_dir, config_dir=config_dir)
    df_controls = ctrl_res["df_controls"]
    ctrl_audit_meta = dict(ctrl_res["audit_meta"])

    hw_parquet = data_dir / "events/heatwave_events_v0.parquet"
    if not hw_parquet.exists():
        raise FileNotFoundError(f"Heatwaves catalogue not found: {hw_parquet}")
    df_events = pd.read_parquet(hw_parquet)

    # Fallback role allocation: Dev = HW_20240702; Conf = 2022 events sorted by (event_start_utc, event_id)
    if design_mode == "fallback":
        dev_events = [e for _, e in df_events.iterrows() if e["event_id"] == "HW_20240702"]
        conf_events = [e for _, e in df_events.iterrows() if e["event_id"] in {"HW_20220620", "HW_20220904", "HW_20220922"}]
        conf_events.sort(key=lambda x: (x["event_start_utc"], x["event_id"]))
        stage_a_selected_events = dev_events + conf_events[:3]
    else:
        stage_a_selected_events = [e for _, e in df_events.iterrows()][:5]

    target_duration_hours = 120
    buffer_hours = 48
    target_timezone = "America/Los_Angeles"

    # Compute evaluation windows for selected heatwaves
    stage_a_events_meta = []
    for ev in stage_a_selected_events:
        win_info = compute_event_evaluation_window(
            ev, target_duration_hours=target_duration_hours, target_timezone=target_timezone
        )
        stage_a_events_meta.append({
            "event_id": win_info["event_id"],
            "start_utc": win_info["start_timestamp_utc"],
            "end_utc": win_info["end_timestamp_utc"],
            "duration_hours": win_info["duration_hours"],
            "raw_event": dict(ev),
        })

    # Match controls for selected heatwaves
    stage_a_controls_meta = []
    for ev_meta in stage_a_events_meta:
        m_ctrl = df_controls[df_controls["matched_event_id"] == ev_meta["event_id"]].iloc[0]
        stage_a_controls_meta.append({
            "control_id": str(m_ctrl["control_id"]),
            "matched_event_id": str(m_ctrl["matched_event_id"]),
            "start_utc": pd.to_datetime(m_ctrl["start_timestamp_utc"], utc=True),
            "end_utc": pd.to_datetime(m_ctrl["end_timestamp_utc"], utc=True),
            "duration_hours": int(m_ctrl["duration_hours"]),
            "raw_control": dict(m_ctrl),
        })

    # Blocked intervals for Stage A blind candidate generation
    hw_blocked = []
    for ev_meta in stage_a_events_meta:
        hw_blocked.append((
            ev_meta["start_utc"] - pd.Timedelta(hours=buffer_hours),
            ev_meta["end_utc"] + pd.Timedelta(hours=buffer_hours),
        ))
    ctrl_blocked = [(c["start_utc"], c["end_utc"]) for c in stage_a_controls_meta]

    # Generate all candidate blind windows across eligible study season (2024)
    days_in_window = target_duration_hours // 24
    study_years = [2024]
    study_months = [6, 7, 8, 9]

    blind_candidates: list[dict[str, Any]] = []
    for yr in study_years:
        season_start = date(yr, min(study_months), 1)
        season_end = date(yr, max(study_months), 30)
        max_start = season_end - timedelta(days=days_in_window - 1)

        cur = season_start
        while cur <= max_start:
            end_incl = cur + timedelta(days=days_in_window - 1)
            s_utc_b, _, _ = get_local_day_utc_bounds(cur.isoformat(), target_timezone=target_timezone)
            _, e_utc_b, _ = get_local_day_utc_bounds(end_incl.isoformat(), target_timezone=target_timezone)
            win_s = pd.to_datetime(s_utc_b, utc=True)
            win_e = pd.to_datetime(e_utc_b, utc=True)

            cand_content = f"{cur.isoformat()}_{end_incl.isoformat()}_{target_duration_hours}_{random_seed}_{version}"
            cand_id = stable_hash_id("BLIND", cand_content)

            hw_over = any(max(win_s, hs) < min(win_e, he) for hs, he in hw_blocked)
            ctrl_over = any(max(win_s, cs) < min(win_e, ce) for cs, ce in ctrl_blocked)

            is_stage_a_elig = not (hw_over or ctrl_over)
            # Pre-rank deterministically using SHA-256 sort key
            s_val = f"{random_seed}_{cand_id}_{win_s.isoformat()}"
            sort_key = hashlib.sha256(s_val.encode("utf-8")).hexdigest()

            blind_candidates.append({
                "candidate_id": cand_id,
                "local_start_date": cur.isoformat(),
                "local_end_inclusive": end_incl.isoformat(),
                "start_utc": win_s,
                "end_utc": win_e,
                "hw_over": hw_over,
                "ctrl_over": ctrl_over,
                "is_stage_a_eligible": is_stage_a_elig,
                "sort_key": sort_key,
            })
            cur += timedelta(days=1)

    df_blind_candidates = pd.DataFrame(blind_candidates)
    df_blind_ranked = df_blind_candidates[df_blind_candidates["is_stage_a_eligible"]].sort_values("sort_key").reset_index(drop=True)

    # 2. Stage B: Verify Authentic Source Coverage in Pre-Ranked Order
    # Parse available authentic timestamps without using outcomes to influence ranking
    caiso_ts: set[pd.Timestamp] = set()
    for z in (data_dir / "raw/caiso").glob("caiso_dam_lmp_TH_NP15_GEN-APND_2024*.zip"):
        r, _ = parse_caiso_zip(z)
        for row in r:
            if row.get("lmp_type") == "LMP" and row.get("xml_data_item") == "LMP_PRC":
                caiso_ts.add(pd.to_datetime(row["timestamp_utc"], utc=True))

    demand_ts: set[pd.Timestamp] = set()
    for j in (data_dir / "raw/eia").glob("eia930_region_CISO_*.json"):
        with j.open("r", encoding="utf-8") as f:
            d_json = json.load(f)
        for r in d_json.get("response", {}).get("data", []):
            if r.get("type") == "D" and r.get("period") and r.get("value") is not None:
                he = pd.to_datetime(r["period"] + ":00:00", utc=True)
                demand_ts.add(he - pd.Timedelta(hours=1))

    # Deterministically advance down Stage A ranked candidates, rejecting windows lacking complete source coverage
    occupied_intervals = [(ev["start_utc"], ev["end_utc"]) for ev in stage_a_events_meta] + [
        (c["start_utc"], c["end_utc"]) for c in stage_a_controls_meta
    ]

    selected_stage_b_blinds: list[dict[str, Any]] = []
    blind_pool_audit_records: list[dict[str, Any]] = []

    for idx, r in df_blind_ranked.iterrows():
        rank = idx + 1
        cid = r["candidate_id"]
        s_utc = r["start_utc"]
        e_utc = r["end_utc"]

        rejections = []
        # Check overlap with previously occupied or selected intervals
        if any(max(s_utc, occ_s) < min(e_utc, occ_e) for occ_s, occ_e in occupied_intervals):
            rejections.append("overlaps_previously_selected_window")

        hrs = set(pd.date_range(s_utc, e_utc - pd.Timedelta(hours=1), freq="1h"))
        if not hrs.issubset(caiso_ts):
            rejections.append("missing_caiso_coverage")
        if not hrs.issubset(demand_ts):
            rejections.append("missing_eia_demand_coverage")

        is_selected = False
        if not rejections and len(selected_stage_b_blinds) < 4:
            selected_stage_b_blinds.append({
                "candidate_id": cid,
                "start_utc": s_utc,
                "end_utc": e_utc,
                "duration_hours": target_duration_hours,
                "stage_a_rank": rank,
            })
            occupied_intervals.append((s_utc, e_utc))
            is_selected = True

        blind_pool_audit_records.append({
            "candidate_id": cid,
            "start_timestamp_utc": s_utc.isoformat(),
            "end_timestamp_utc": e_utc.isoformat(),
            "duration_hours": target_duration_hours,
            "is_eligible": len(rejections) == 0,
            "is_selected": is_selected,
            "rejection_codes": ";".join(rejections) if rejections else "NONE",
            "seed": random_seed,
            "algorithm_version": version,
            "contains_heatwave_or_buffer": False,
            "contains_matched_control": False,
            "data_completeness_status": "complete" if len(rejections) == 0 else "incomplete",
        })

    if len(selected_stage_b_blinds) < 4:
        raise InsufficientP6BenchmarkDataError(
            (f"Only {len(selected_stage_b_blinds)} authentic blind windows satisfied coverage and non-overlap requirements",)
        )

    # Also record Stage A ineligibles in blind pool audit
    for _, r in df_blind_candidates[~df_blind_candidates["is_stage_a_eligible"]].iterrows():
        rejs = []
        if r["hw_over"]:
            rejs.append("overlaps_heatwave_event_or_48h_buffer")
        if r["ctrl_over"]:
            rejs.append("overlaps_matched_control")
        blind_pool_audit_records.append({
            "candidate_id": r["candidate_id"],
            "start_timestamp_utc": r["start_utc"].isoformat(),
            "end_timestamp_utc": r["end_utc"].isoformat(),
            "duration_hours": target_duration_hours,
            "is_eligible": False,
            "is_selected": False,
            "rejection_codes": ";".join(rejs),
            "seed": random_seed,
            "algorithm_version": version,
            "contains_heatwave_or_buffer": r["hw_over"],
            "contains_matched_control": r["ctrl_over"],
            "data_completeness_status": "incomplete",
        })

    blind_pool_df = pd.DataFrame(blind_pool_audit_records, columns=BLIND_POOL_COLUMNS).sort_values("start_timestamp_utc").reset_index(drop=True)

    # 3. Dynamically Derive Target Intervals from Frozen Identities
    target_intervals = []
    for i in range(4):
        target_intervals.append((stage_a_events_meta[i]["start_utc"], stage_a_events_meta[i]["end_utc"]))
        target_intervals.append((stage_a_controls_meta[i]["start_utc"], stage_a_controls_meta[i]["end_utc"]))
        target_intervals.append((selected_stage_b_blinds[i]["start_utc"], selected_stage_b_blinds[i]["end_utc"]))

    all_target_hours: set[pd.Timestamp] = set()
    for s_utc, e_utc in target_intervals:
        cur = s_utc
        while cur < e_utc:
            all_target_hours.add(cur)
            cur += pd.Timedelta(hours=1)

    if len(all_target_hours) != 1440:
        raise ValueError(f"Expected exactly 1,440 target hours, got {len(all_target_hours)}")

    # 4. Ingest canonical signals from authentic raw sources
    # 4a. NOAA
    temp_map: dict[pd.Timestamp, float] = {}
    for yr in [2022, 2024]:
        psv_path = data_dir / f"raw/noaa/GHCNh_USW00023234_{yr}.psv"
        if not psv_path.exists():
            raise FileNotFoundError(f"Raw NOAA PSV missing: {psv_path}")
        yr_hours = sorted([h for h in all_target_hours if h.year == yr])
        intervals = [{"timestamp_utc": h, "interval_end_utc": h + pd.Timedelta(hours=1)} for h in yr_hours]
        res_noaa = aggregate_noaa_hourly_temperature(psv_path, intervals)
        for h, d in res_noaa.items():
            t_val = d.get("temperature_c")
            if t_val is None or not np.isfinite(t_val):
                raise ValueError(f"Missing or non-finite NOAA temperature for {h}")
            temp_map[h] = float(t_val)

    # 4b. CAISO Price
    price_map: dict[pd.Timestamp, float] = {}
    # Historical 2022 zips
    hist_caiso_dir = data_dir / "raw/caiso/historical"
    df_hist_caiso = parse_caiso_historical_group_zips(hist_caiso_dir)
    for _, r in df_hist_caiso.iterrows():
        ts = r["timestamp_utc"]
        if ts in all_target_hours:
            price_map[ts] = float(r["price_usd_per_mwh"])

    # 2024 SingleZip archives
    for z in sorted((data_dir / "raw/caiso").glob("caiso_dam_lmp_TH_NP15_GEN-APND_2024*.zip")):
        r, err = parse_caiso_zip(z)
        for row in r:
            if row.get("lmp_type") == "LMP" and row.get("xml_data_item") == "LMP_PRC":
                ts = pd.to_datetime(row["timestamp_utc"], utc=True)
                if ts in all_target_hours:
                    val = float(row["price_usd_per_mwh"])
                    if ts in price_map and abs(price_map[ts] - val) > 1e-4:
                        raise ValueError(f"Conflicting duplicate 2024 CAISO price at {ts}")
                    price_map[ts] = val

    # 4c. EIA Demand
    demand_map: dict[pd.Timestamp, float] = {}
    for j in sorted((data_dir / "raw/eia").glob("eia930_region_CISO_*.json")):
        with j.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("response", {}).get("data", []):
            if r.get("type") == "D" and r.get("period"):
                he = pd.to_datetime(r["period"] + ":00:00", utc=True)
                ts = he - pd.Timedelta(hours=1)
                if ts in all_target_hours:
                    val = r.get("value")
                    if val is not None:
                        f_val = float(val)
                        if not np.isfinite(f_val):
                            raise ValueError(f"Non-finite EIA demand at {ts}: {f_val}")
                        if ts in demand_map and abs(demand_map[ts] - f_val) > 1e-4:
                            raise ValueError(f"Conflicting duplicate EIA demand for {ts}: existing={demand_map[ts]} vs new={f_val}")
                        demand_map[ts] = f_val

    # 4d. EIA Carbon
    ciso_xlsx_path = data_dir / "raw/eia/CISO.xlsx"
    df_carbon = parse_ciso_xlsx_carbon_streaming(ciso_xlsx_path, target_timestamps_utc=all_target_hours)
    carbon_map: dict[pd.Timestamp, float] = {
        r["timestamp_utc"]: float(r["carbon_g_per_kwh"]) for _, r in df_carbon.iterrows()
    }

    # Verify 100% signal coverage across all 1440 hours
    for h in all_target_hours:
        if h not in temp_map:
            raise ValueError(f"Missing temperature signal at {h}")
        if h not in price_map:
            raise ValueError(f"Missing price signal at {h}")
        if h not in demand_map:
            raise ValueError(f"Missing demand signal at {h}")
        if h not in carbon_map:
            raise ValueError(f"Missing carbon signal at {h}")

    # Build aligned DataFrame for the target windows
    aligned_rows = []
    for h in sorted(all_target_hours):
        aligned_rows.append({
            "timestamp_utc": h,
            "temperature_c": temp_map[h],
            "price_usd_per_mwh": price_map[h],
            "carbon_g_per_kwh": carbon_map[h],
            "demand_mw": demand_map[h],
        })
    aligned_df = pd.DataFrame(aligned_rows)

    # 5. Run deterministic builder
    hourly_df, triplet_index_df, blind_pool_df = build_p6_benchmark_triplets(
        aligned_df=aligned_df,
        event_catalogue_df=df_events,
        config={"duration_hours": 120, "buffer_hours": 48},
        control_catalogue_df=df_controls,
        design_mode=design_mode,
        random_seed=random_seed,
        version=version,
    )

    # 6. Transactional Staged Writes & Atomic Publication
    # All 7 Gate 1 outputs are staged in a single atomic bundle:
    # 1. control catalogue parquet
    # 2. control catalogue CSV
    # 3. control matching audit JSON
    # 4. event-control pairs parquet
    # 5. event-control index CSV
    # 6. blind pool CSV
    # 7. Gate 1 manifest JSON
    benchmarks_dir = data_dir / "benchmarks"
    events_dir = data_dir / "events"
    manifests_dir = data_dir / "manifests"
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    events_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    pairs_parquet_path = benchmarks_dir / "p6_event_control_pairs.parquet"
    index_csv_path = benchmarks_dir / "p6_event_control_index.csv"
    pool_csv_path = benchmarks_dir / "p6_event_blind_pool.csv"
    manifest_json_path = manifests_dir / "p6_gate1_benchmark_manifest.json"
    ctrl_parquet_path = events_dir / "control_catalogue_v0.parquet"
    ctrl_csv_path = events_dir / "control_catalogue_v0.csv"
    ctrl_audit_path = manifests_dir / "control_matching_audit.json"

    stage_bundle_dir = tempfile.mkdtemp(prefix="stage_g1_bundle_", dir=data_dir)
    try:
        stage_pairs = Path(stage_bundle_dir) / "p6_event_control_pairs.parquet"
        stage_index = Path(stage_bundle_dir) / "p6_event_control_index.csv"
        stage_pool = Path(stage_bundle_dir) / "p6_event_blind_pool.csv"
        stage_manifest = Path(stage_bundle_dir) / "p6_gate1_benchmark_manifest.json"
        stage_ctrl_parquet = Path(stage_bundle_dir) / "control_catalogue_v0.parquet"
        stage_ctrl_csv = Path(stage_bundle_dir) / "control_catalogue_v0.csv"
        stage_ctrl_audit = Path(stage_bundle_dir) / "control_matching_audit.json"

        hourly_df.to_parquet(stage_pairs, index=False)
        triplet_index_df.to_csv(stage_index, index=False)
        blind_pool_df.to_csv(stage_pool, index=False)
        df_controls.to_parquet(stage_ctrl_parquet, index=False)
        df_controls.to_csv(stage_ctrl_csv, index=False)

        ctrl_audit_meta["output_files"] = {
            "control_catalogue_parquet": {
                "path": _rel(ctrl_parquet_path),
                "sha256": sha256_file(stage_ctrl_parquet),
                "size_bytes": stage_ctrl_parquet.stat().st_size,
            },
            "control_catalogue_csv": {
                "path": _rel(ctrl_csv_path),
                "sha256": sha256_file(stage_ctrl_csv),
                "size_bytes": stage_ctrl_csv.stat().st_size,
            },
        }
        with stage_ctrl_audit.open("w", encoding="utf-8") as f:
            json.dump(ctrl_audit_meta, f, indent=2, sort_keys=True)

        # 7. Record manifest with full cryptographic provenance
        raw_files_meta: dict[str, Any] = {}
        for p in [
            data_dir / "raw/noaa/GHCNh_USW00023234_2022.psv",
            data_dir / "raw/noaa/GHCNh_USW00023234_2024.psv",
            ciso_xlsx_path,
        ]:
            if p.exists():
                raw_files_meta[p.name] = {
                    "path": _rel(p),
                    "sha256": sha256_file(p),
                    "size_bytes": p.stat().st_size,
                }

        for p in sorted((data_dir / "raw/caiso").glob("*.zip")):
            raw_files_meta[p.name] = {
                "path": _rel(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

        for p in sorted((data_dir / "raw/caiso/historical").rglob("*.zip")):
            raw_files_meta[p.name] = {
                "path": _rel(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

        for p in sorted((data_dir / "raw/eia").glob("eia930_region_CISO_*.json")):
            raw_files_meta[p.name] = {
                "path": _rel(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

        manifest = {
            "manifest_version": "1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "design_mode": design_mode,
            "random_seed": random_seed,
            "algorithm_version": version,
            "summary": {
                "total_benchmark_rows": len(hourly_df),
                "total_triplets": len(triplet_index_df),
                "total_blind_candidates": len(blind_pool_df),
                "selected_blind_candidates": int(blind_pool_df["is_selected"].sum()),
                "development_triplets": sum(1 for _, r in triplet_index_df.iterrows() if r["role"] == "development"),
                "confirmatory_triplets": sum(1 for _, r in triplet_index_df.iterrows() if r["role"] == "confirmatory"),
            },
            "triplets": triplet_index_df.to_dict(orient="records"),
            "raw_source_files_count": len(raw_files_meta),
            "raw_source_files": raw_files_meta,
            "output_files": {
                "pairs_parquet": {
                    "path": _rel(pairs_parquet_path),
                    "sha256": sha256_file(stage_pairs),
                    "size_bytes": stage_pairs.stat().st_size,
                },
                "index_csv": {
                    "path": _rel(index_csv_path),
                    "sha256": sha256_file(stage_index),
                    "size_bytes": stage_index.stat().st_size,
                },
                "blind_pool_csv": {
                    "path": _rel(pool_csv_path),
                    "sha256": sha256_file(stage_pool),
                    "size_bytes": stage_pool.stat().st_size,
                },
                "control_catalogue_parquet": {
                    "path": _rel(ctrl_parquet_path),
                    "sha256": sha256_file(stage_ctrl_parquet),
                    "size_bytes": stage_ctrl_parquet.stat().st_size,
                },
                "control_catalogue_csv": {
                    "path": _rel(ctrl_csv_path),
                    "sha256": sha256_file(stage_ctrl_csv),
                    "size_bytes": stage_ctrl_csv.stat().st_size,
                },
                "control_matching_audit": {
                    "path": _rel(ctrl_audit_path),
                    "sha256": sha256_file(stage_ctrl_audit),
                    "size_bytes": stage_ctrl_audit.stat().st_size,
                },
            },
            "manifest_path": _rel(manifest_json_path),
        }

        with stage_manifest.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        # Validate complete staged bundle before replacing any production file
        df_val_hourly = pd.read_parquet(stage_pairs)
        df_val_index = pd.read_csv(stage_index)
        validate_p6_benchmark_triplets(
            hourly_df=df_val_hourly,
            triplet_index_df=df_val_index,
            design_mode=design_mode,
            expected_duration_hours=target_duration_hours,
        )
        df_val_ctrl = pd.read_parquet(stage_ctrl_parquet)
        validate_control_dataframe(df_val_ctrl, require_unique_event=True)
        assert len(df_val_ctrl) == 4

        # Atomic publication: replace final production files only after complete bundle validation
        # If any file fails to replace, rollback backups to guarantee byte-for-byte invariance
        staged_replacements = [
            (stage_pairs, pairs_parquet_path),
            (stage_index, index_csv_path),
            (stage_pool, pool_csv_path),
            (stage_ctrl_parquet, ctrl_parquet_path),
            (stage_ctrl_csv, ctrl_csv_path),
            (stage_ctrl_audit, ctrl_audit_path),
            (stage_manifest, manifest_json_path),
        ]

        backups: list[tuple[Path, Path]] = []
        try:
            for s_f, d_f in staged_replacements:
                if d_f.exists():
                    backup_f = d_f.with_suffix(d_f.suffix + ".bak")
                    d_f.replace(backup_f)
                    backups.append((backup_f, d_f))
                s_f.replace(d_f)
            # Commit successful: cleanup backups
            for b_f, _ in backups:
                if b_f.exists():
                    b_f.unlink()
        except Exception as e:
            # Rollback all replaced files
            for b_f, d_f in backups:
                if b_f.exists():
                    b_f.replace(d_f)
            raise RuntimeError(f"Mid-publication failure, rollback executed successfully: {e}") from e

    finally:
        if Path(stage_bundle_dir).exists():
            import shutil
            shutil.rmtree(stage_bundle_dir, ignore_errors=True)

    return manifest


PHASE_LABEL_OVERLAY_COLUMNS = [
    "triplet_id",
    "window_type",
    "window_id",
    "timestamp_utc",
    "phase_label",
]

VALID_HEATWAVE_PHASES = {"onset", "peak", "sustained", "recovery"}
VALID_NON_EVENT_PHASES = {"control", "event_blind"}


def build_p6_phase_label_overlay(
    pairs_df: pd.DataFrame,
    event_catalogue_df: pd.DataFrame,
    *,
    target_timezone: str = "America/Los_Angeles",
) -> pd.DataFrame:
    """Build a deterministic, versioned phase-label overlay for P6 benchmark pairs.

    Keyed strictly by (triplet_id, window_id, timestamp_utc).
    Heatwave hours retain canonical phases (onset, peak, sustained, recovery) derived
    strictly from event boundary dates in events.py (without outcomes, prices, or carbon).
    Control and event-blind rows retain explicit non-event labels.
    Fails closed on missing, duplicate, conflicting, or non-covering mappings.
    """
    from heattrace.process.events import build_hourly_phase_labels

    # 1. Validate required inputs
    req_pair_cols = {"triplet_id", "window_type", "window_id", "timestamp_utc"}
    missing_cols = req_pair_cols - set(pairs_df.columns)
    if missing_cols:
        raise ValueError(f"pairs_df missing required columns for phase overlay: {sorted(missing_cols)}")

    req_event_cols = {"event_id", "local_start_date", "local_end_date", "peak_local_date"}
    missing_ev = req_event_cols - set(event_catalogue_df.columns)
    if missing_ev:
        raise ValueError(f"event_catalogue_df missing required columns: {sorted(missing_ev)}")

    # 2. Build canonical hourly phases from heatwave event boundaries
    canonical_hw_phases = build_hourly_phase_labels(
        event_catalogue_df,
        target_timezone=target_timezone,
    )
    if canonical_hw_phases.empty:
        raise ValueError("Canonical event phase generator returned empty dataframe")

    # Map (event_id, timestamp_utc) -> event_phase
    # Verify no duplicate keys in canonical source
    canonical_hw_phases["timestamp_utc"] = pd.to_datetime(canonical_hw_phases["timestamp_utc"], utc=True)
    if canonical_hw_phases.duplicated(subset=["event_id", "timestamp_utc"]).any():
        raise ValueError("Conflicting duplicate timestamps in canonical heatwave phase sources")

    phase_lookup: dict[tuple[str, pd.Timestamp], str] = {}
    for _, r in canonical_hw_phases.iterrows():
        key = (str(r["event_id"]), r["timestamp_utc"])
        phase_lookup[key] = str(r["event_phase"])

    # 3. Process pairs_df rows deterministically
    overlay_rows = []
    seen_keys: set[tuple[str, str, pd.Timestamp]] = set()

    for idx, row in pairs_df.iterrows():
        tid = str(row["triplet_id"])
        wid = str(row["window_id"])
        wtype = str(row["window_type"])
        ts = pd.to_datetime(row["timestamp_utc"], utc=True)

        rel_key = (tid, wid, ts)
        if rel_key in seen_keys:
            raise ValueError(f"Duplicate key in input pairs: {rel_key}")
        seen_keys.add(rel_key)

        if wtype == "heatwave":
            src_key = (wid, ts)
            if src_key not in phase_lookup:
                raise ValueError(
                    f"Missing canonical phase label for heatwave window '{wid}' at timestamp {ts.isoformat()}"
                )
            plabel = phase_lookup[src_key]
            if plabel not in VALID_HEATWAVE_PHASES:
                raise ValueError(f"Invalid heatwave phase label '{plabel}' for {wid} at {ts}")
        elif wtype == "control":
            plabel = "control"
        elif wtype == "event_blind":
            plabel = "event_blind"
        else:
            raise ValueError(f"Unrecognized window_type '{wtype}' for triplet '{tid}', window '{wid}'")

        overlay_rows.append({
            "triplet_id": tid,
            "window_type": wtype,
            "window_id": wid,
            "timestamp_utc": ts,
            "phase_label": plabel,
        })

    overlay_df = pd.DataFrame(overlay_rows, columns=PHASE_LABEL_OVERLAY_COLUMNS)

    # 4. Strictly validate coverage and invariants
    if len(overlay_df) != len(pairs_df):
        raise ValueError(f"Phase overlay row count {len(overlay_df)} != pairs row count {len(pairs_df)}")

    # Deterministic sort
    overlay_df = overlay_df.sort_values(by=["triplet_id", "window_id", "timestamp_utc"]).reset_index(drop=True)
    return overlay_df


def save_p6_phase_label_overlay(
    overlay_df: pd.DataFrame,
    output_path: Path | str,
) -> str:
    """Save phase label overlay parquet and return its SHA-256 hex digest."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    overlay_df.to_parquet(path, index=False)
    with path.open("rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_p6_phase_label_overlay(overlay_path: Path | str) -> pd.DataFrame:
    """Load and validate phase label overlay parquet.

    Fails closed if the schema does not match PHASE_LABEL_OVERLAY_COLUMNS exactly.
    """
    path = Path(overlay_path)
    if not path.exists():
        raise FileNotFoundError(f"Phase label overlay missing: {path}")
    df = pd.read_parquet(path)
    if list(df.columns) != PHASE_LABEL_OVERLAY_COLUMNS:
        raise ValueError(
            f"Overlay schema mismatch: got columns {list(df.columns)}, expected exactly {PHASE_LABEL_OVERLAY_COLUMNS}"
        )
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df


def apply_p6_phase_label_overlay(
    pairs_df: pd.DataFrame,
    overlay_df: pd.DataFrame,
) -> pd.DataFrame:
    """Deterministically join phase_label from overlay onto pairs dataframe by identity keys.

    Keyed strictly by (triplet_id, window_type, window_id, timestamp_utc).
    Fails closed if:
    - window_type differs between pairs and overlay
    - any rows are unmapped, duplicate, extra, or conflicting
    - heatwave rows have non-heatwave phases (onset/peak/sustained/recovery required)
    - control rows have non-control phases (must be 'control')
    - event_blind rows have non-event_blind phases (must be 'event_blind')
    """
    p_df = pairs_df.copy()
    p_df["timestamp_utc"] = pd.to_datetime(p_df["timestamp_utc"], utc=True)
    o_df = overlay_df.copy()
    o_df["timestamp_utc"] = pd.to_datetime(o_df["timestamp_utc"], utc=True)

    join_keys = ["triplet_id", "window_type", "window_id", "timestamp_utc"]

    # Verify join keys are present in both
    for k in join_keys:
        if k not in p_df.columns:
            raise ValueError(f"pairs_df missing required join key: {k}")
        if k not in o_df.columns:
            raise ValueError(f"overlay_df missing required join key: {k}")

    # Verify no duplicate keys in either
    if p_df.duplicated(subset=join_keys).any():
        raise ValueError("pairs_df contains duplicate join keys for phase overlay")
    if o_df.duplicated(subset=join_keys).any():
        raise ValueError("overlay_df contains duplicate join keys for phase overlay")

    merged = pd.merge(
        p_df.drop(columns=["phase_label"], errors="ignore"),
        o_df[join_keys + ["phase_label"]],
        on=join_keys,
        how="inner",
    )

    if len(merged) != len(p_df):
        raise ValueError(
            f"Phase label overlay join failed full coverage: merged count {len(merged)} != input pairs count {len(p_df)}"
        )

    if merged["phase_label"].isna().any():
        n_missing = int(merged["phase_label"].isna().sum())
        raise ValueError(f"Phase label overlay failed full coverage: {n_missing} rows unmapped")

    # Semantic phase validation by window_type
    hw_rows = merged[merged["window_type"] == "heatwave"]
    invalid_hw = set(hw_rows["phase_label"].unique()) - VALID_HEATWAVE_PHASES
    if invalid_hw:
        raise ValueError(f"Heatwave rows received invalid phase label(s): {invalid_hw}")

    ctrl_rows = merged[merged["window_type"] == "control"]
    invalid_ctrl = set(ctrl_rows["phase_label"].unique()) - {"control"}
    if invalid_ctrl:
        raise ValueError(f"Control rows received invalid phase label(s): {invalid_ctrl}")

    blind_rows = merged[merged["window_type"] == "event_blind"]
    invalid_blind = set(blind_rows["phase_label"].unique()) - {"event_blind"}
    if invalid_blind:
        raise ValueError(f"Event-blind rows received invalid phase label(s): {invalid_blind}")

    return merged


