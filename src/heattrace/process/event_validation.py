"""Quality validation for HeatTrace event catalogues and hourly phase labels."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import pandas as pd


EVENT_CATALOGUE_COLUMNS: list[str] = [
    "event_id",
    "station_id",
    "timezone",
    "local_start_date",
    "local_end_date",
    "duration_days",
    "event_start_utc",
    "event_end_utc",
    "duration_hours",
    "peak_local_date",
    "peak_temperature_c",
    "mean_max_temperature_c",
    "cumulative_exceedance_c_days",
    "threshold_p90_c",
]

HOURLY_EVENT_LABEL_COLUMNS: list[str] = [
    "timestamp_utc",
    "local_date",
    "hour_local",
    "event_id",
    "event_phase",
    "station_id",
]

VALID_EVENT_PHASES = frozenset({"onset", "peak", "sustained", "recovery"})


def validate_heatwave_events(
    df_events: pd.DataFrame,
    *,
    expected_station: str = "USW00023234",
    expected_timezone: str = "America/Los_Angeles",
    p90_threshold_c: float | None = None,
    min_consecutive_days: int = 3,
    allow_empty: bool = False,
) -> None:
    """Validate heatwave event catalogue DataFrame according to P3 contract."""
    if not isinstance(df_events, pd.DataFrame):
        raise TypeError("df_events must be a pandas DataFrame")

    # Column schema and order
    actual_cols = list(df_events.columns)
    if actual_cols != EVENT_CATALOGUE_COLUMNS:
        raise ValueError(
            f"Event catalogue columns mismatch.\nExpected: {EVENT_CATALOGUE_COLUMNS}\nActual:   {actual_cols}"
        )

    if df_events.empty:
        if allow_empty:
            return
        raise ValueError("Event catalogue cannot be empty")

    # Unique event IDs
    if df_events["event_id"].duplicated().any():
        dups = df_events[df_events["event_id"].duplicated()]["event_id"].tolist()
        raise ValueError(f"Duplicate event_id values found: {dups}")

    # Station and timezone consistency
    for idx, row in df_events.iterrows():
        eid = row["event_id"]
        if row["station_id"] != expected_station:
            raise ValueError(f"Event {eid}: station_id '{row['station_id']}' != expected '{expected_station}'")
        if row["timezone"] != expected_timezone:
            raise ValueError(f"Event {eid}: timezone '{row['timezone']}' != expected '{expected_timezone}'")

        dur_days = row["duration_days"]
        if dur_days < min_consecutive_days:
            raise ValueError(f"Event {eid}: duration_days {dur_days} < min_consecutive_days {min_consecutive_days}")

        dur_hours = row["duration_hours"]
        if dur_hours <= 0 or not isinstance(dur_hours, (int, float)):
            raise ValueError(f"Event {eid}: invalid duration_hours {dur_hours}")

        # Check timestamp awareness
        t_start = row["event_start_utc"]
        t_end = row["event_end_utc"]
        if not isinstance(t_start, (datetime, pd.Timestamp)) or t_start.tzinfo is None:
            raise ValueError(f"Event {eid}: event_start_utc must be timezone-aware UTC datetime")
        if not isinstance(t_end, (datetime, pd.Timestamp)) or t_end.tzinfo is None:
            raise ValueError(f"Event {eid}: event_end_utc must be timezone-aware UTC datetime")
        if t_start >= t_end:
            raise ValueError(f"Event {eid}: event_start_utc ({t_start}) >= event_end_utc ({t_end})")

        # Top-of-hour check
        if t_start.minute != 0 or t_start.second != 0 or t_start.microsecond != 0:
            raise ValueError(f"Event {eid}: event_start_utc ({t_start}) is not top-of-hour")
        if t_end.minute != 0 or t_end.second != 0 or t_end.microsecond != 0:
            raise ValueError(f"Event {eid}: event_end_utc ({t_end}) is not top-of-hour")

        # Expected duration hours based on start/end
        diff_hours = (t_end - t_start).total_seconds() / 3600.0
        if abs(dur_hours - diff_hours) > 1e-4:
            raise ValueError(f"Event {eid}: duration_hours {dur_hours} != calculated {diff_hours}")

        # Peak date inside interval
        d_start = str(row["local_start_date"])
        d_end = str(row["local_end_date"])
        d_peak = str(row["peak_local_date"])
        if not (d_start <= d_peak <= d_end):
            raise ValueError(f"Event {eid}: peak_local_date {d_peak} outside [{d_start}, {d_end}]")

        # Peak temperature strictly > threshold
        if p90_threshold_c is not None:
            if row["peak_temperature_c"] <= p90_threshold_c:
                raise ValueError(
                    f"Event {eid}: peak_temperature_c {row['peak_temperature_c']} <= threshold {p90_threshold_c}"
                )

    # Monotonic ordering by event_start_utc
    starts = df_events["event_start_utc"].tolist()
    if starts != sorted(starts):
        raise ValueError("Events are not strictly ordered by event_start_utc")

    # Non-overlapping event intervals
    for i in range(len(df_events) - 1):
        curr_end = df_events.iloc[i]["event_end_utc"]
        next_start = df_events.iloc[i + 1]["event_start_utc"]
        if curr_end > next_start:
            raise ValueError(
                f"Overlapping events: {df_events.iloc[i]['event_id']} (ends {curr_end}) "
                f"and {df_events.iloc[i + 1]['event_id']} (starts {next_start})"
            )


def validate_hourly_event_labels(
    df_labels: pd.DataFrame,
    df_events: pd.DataFrame | None = None,
    *,
    expected_station: str = "USW00023234",
) -> None:
    """Validate hourly event labels DataFrame according to P3 contract."""
    if not isinstance(df_labels, pd.DataFrame):
        raise TypeError("df_labels must be a pandas DataFrame")

    actual_cols = list(df_labels.columns)
    if actual_cols != HOURLY_EVENT_LABEL_COLUMNS:
        raise ValueError(
            f"Hourly event labels columns mismatch.\nExpected: {HOURLY_EVENT_LABEL_COLUMNS}\nActual:   {actual_cols}"
        )

    if df_labels.empty:
        raise ValueError("Hourly event labels cannot be empty")

    # Duplicate timestamps check (each timestamp must have exactly one event_id and phase)
    if df_labels["timestamp_utc"].duplicated().any():
        dups = df_labels[df_labels["timestamp_utc"].duplicated()]["timestamp_utc"].tolist()
        raise ValueError(f"Duplicate timestamp_utc found in hourly event labels: {dups[:5]} (total {len(dups)})")

    # Monotonic ordering
    ts_list = df_labels["timestamp_utc"].tolist()
    if ts_list != sorted(ts_list):
        raise ValueError("Hourly event labels are not sorted ascending by timestamp_utc")

    # Valid phases and timestamps
    for idx, row in df_labels.iterrows():
        ts = row["timestamp_utc"]
        if not isinstance(ts, (datetime, pd.Timestamp)) or ts.tzinfo is None:
            raise ValueError(f"Row {idx}: timestamp_utc must be a timezone-aware UTC datetime, got {ts}")
        if ts.minute != 0 or ts.second != 0 or ts.microsecond != 0:
            raise ValueError(f"Row {idx}: timestamp_utc {ts} is not top-of-hour")

        phase = row["event_phase"]
        if phase not in VALID_EVENT_PHASES:
            raise ValueError(f"Row {idx}: invalid event_phase '{phase}'. Must be in {VALID_EVENT_PHASES}")

        st = row["station_id"]
        if st != expected_station:
            raise ValueError(f"Row {idx}: station_id '{st}' != expected '{expected_station}'")

        hr = row["hour_local"]
        if not (0 <= hr <= 23):
            raise ValueError(f"Row {idx}: hour_local {hr} outside [0, 23]")

    # Consistency with event catalogue if provided
    if df_events is not None:
        known_event_ids = set(df_events["event_id"])
        label_event_ids = set(df_labels["event_id"])
        if not label_event_ids.issubset(known_event_ids):
            unknown = label_event_ids - known_event_ids
            raise ValueError(f"Hourly labels reference unknown event_ids: {unknown}")

        # For each event, ensure all phases exist: onset, peak, recovery, and (if > 1 event day) sustained
        for eid in known_event_ids:
            ev_labels = df_labels[df_labels["event_id"] == eid]
            ev_phases = set(ev_labels["event_phase"])
            if "onset" not in ev_phases:
                raise ValueError(f"Event {eid} is missing 'onset' phase rows")
            if "peak" not in ev_phases:
                raise ValueError(f"Event {eid} is missing 'peak' phase rows")
            if "recovery" not in ev_phases:
                raise ValueError(f"Event {eid} is missing 'recovery' phase rows")
