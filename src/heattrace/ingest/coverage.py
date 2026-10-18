"""Data coverage report helpers."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def compute_hourly_coverage(
    observed_timestamps: Iterable[datetime],
    *,
    requested_start: datetime,
    requested_end: datetime,
) -> dict[str, Any]:
    """Compute hourly coverage statistics strictly for an interval [requested_start, requested_end).
    
    All timestamps must have timezone-aware UTC tzinfo. Semantics are interval_start.
    Observed metrics (observed_start, observed_end, row_count, unique_timestamps, covered_hourly_bins,
    duplicate_timestamps, missing_hours) strictly describe observations within [requested_start, requested_end).
    """
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested_start and requested_end must be timezone-aware (UTC)")

    start_utc = requested_start.astimezone(timezone.utc)
    end_utc = requested_end.astimezone(timezone.utc)

    if start_utc >= end_utc:
        raise ValueError(f"requested_start ({start_utc}) must be before requested_end ({end_utc})")

    # Build expected hourly bins [H, H + 1 hour)
    expected_hours: list[datetime] = []
    curr = start_utc
    while curr < end_utc:
        expected_hours.append(curr)
        curr += timedelta(hours=1)

    expected_set = set(expected_hours)
    
    # Process observed timestamps and filter strictly to requested interval
    in_interval: list[datetime] = []
    out_of_interval_count = 0
    for ts in observed_timestamps:
        if ts.tzinfo is None:
            raise ValueError("observed timestamp must be timezone-aware")
        ts_utc = ts.astimezone(timezone.utc)
        if start_utc <= ts_utc < end_utc:
            in_interval.append(ts_utc)
        else:
            out_of_interval_count += 1

    in_interval_count = len(in_interval)
    unique_in_interval = set(in_interval)
    unique_count = len(unique_in_interval)
    duplicates = in_interval_count - unique_count

    # Check covered hourly bins: each hour H is covered if any observation falls in [H, H + 1 hour)
    covered_hours: set[datetime] = set()
    for exp_h in expected_hours:
        exp_h_end = exp_h + timedelta(hours=1)
        if any(exp_h <= ts < exp_h_end for ts in in_interval):
            covered_hours.add(exp_h)

    missing_hours = len(expected_set - covered_hours)

    obs_min = min(in_interval).isoformat() if in_interval else ""
    obs_max = max(in_interval).isoformat() if in_interval else ""

    return {
        "requested_start": start_utc.isoformat(),
        "requested_end": end_utc.isoformat(),
        "observed_start": obs_min,
        "observed_end": obs_max,
        "row_count": in_interval_count,
        "unique_timestamps": unique_count,
        "covered_hourly_bins": len(covered_hours),
        "expected_hours": len(expected_hours),
        "missing_hours": missing_hours,
        "duplicate_timestamps": duplicates,
        "out_of_interval_count": out_of_interval_count,
    }


def write_coverage_report(
    path: str | Path,
    rows: list[dict[str, Any]],
) -> None:
    """Write or overwrite coverage CSV report."""
    fieldnames = [
        "source",
        "dataset",
        "status",
        "requested_start",
        "requested_end",
        "observed_start",
        "observed_end",
        "row_count",
        "unique_timestamps",
        "covered_hourly_bins",
        "expected_hours",
        "missing_hours",
        "duplicate_timestamps",
        "notes",
        "qc_day_type",
        "qc_day_status",
        "local_date",
        "daily_max_temperature_c",
        "data_issues_matched_count",
        "data_issues_flagged_count",
        "data_issues_unflagged_count",
    ]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            filtered = {k: r.get(k, "") for k in fieldnames}
            writer.writerow(filtered)

