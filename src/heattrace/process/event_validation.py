"""Quality validation for HeatTrace event catalogues and hourly phase labels."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
import pandas as pd


EVENT_CATALOGUE_COLUMNS: list[str] = [
    "event_id",
    "station_id",
    "timezone",
    "threshold_percentile",
    "threshold_temperature_c",
    "percentile_method",
    "local_start_date",
    "local_end_date",
    "event_start_utc",
    "event_end_utc",
    "qualifying_day_count",
    "duration_days",
    "duration_hours",
    "peak_local_date",
    "peak_temperature_c",
    "mean_max_temperature_c",
    "cumulative_exceedance_c_days",
    "missing_days_inside_event",
    "valid_observation_count",
    "duplicate_observation_count",
    "conflict_observation_count",
    "source_quality",
    "source_file_references",
]

HOURLY_EVENT_LABEL_COLUMNS: list[str] = [
    "timestamp_utc",
    "local_timestamp",
    "local_date",
    "hour_local",
    "event_id",
    "event_phase",
    "station_id",
    "daily_max_temperature_c",
    "threshold_temperature_c",
    "exceeds_threshold",
    "temperature_missing",
    "source_quality",
]

VALID_EVENT_PHASES = frozenset({"onset", "peak", "sustained", "recovery"})
EVENT_ID_PATTERN = re.compile(r"^HW_(\d{8})$")


def validate_heatwave_events(
    df_events: pd.DataFrame,
    *,
    expected_station: str = "USW00023234",
    expected_timezone: str = "America/Los_Angeles",
    expected_threshold_c: float | None = None,
    expected_percentile: float | None = None,
    expected_percentile_method: str | None = None,
    min_consecutive_days: int = 3,
    daily_records_by_date: dict[str, dict[str, Any]] | None = None,
    allow_empty: bool = False,
) -> None:
    """Validate heatwave event catalogue DataFrame according to P3 contract."""
    if not isinstance(df_events, pd.DataFrame):
        raise TypeError("df_events must be a pandas DataFrame")

    actual_cols = list(df_events.columns)
    if actual_cols != EVENT_CATALOGUE_COLUMNS:
        raise ValueError(
            f"Event catalogue columns mismatch.\nExpected: {EVENT_CATALOGUE_COLUMNS}\nActual:   {actual_cols}"
        )

    if df_events.empty:
        if allow_empty:
            return
        raise ValueError("Event catalogue cannot be empty")

    if df_events["event_id"].duplicated().any():
        dups = df_events[df_events["event_id"].duplicated()]["event_id"].tolist()
        raise ValueError(f"Duplicate event_id values found: {dups}")

    tz = ZoneInfo(expected_timezone)

    for idx, row in df_events.iterrows():
        eid = str(row["event_id"])
        m = EVENT_ID_PATTERN.match(eid)
        if not m:
            raise ValueError(f"Event {eid}: invalid event_id format (must match HW_YYYYMMDD)")

        id_date_str = m.group(1)
        expected_start_from_id = f"{id_date_str[:4]}-{id_date_str[4:6]}-{id_date_str[6:8]}"
        if str(row["local_start_date"]) != expected_start_from_id:
            raise ValueError(
                f"Event {eid}: event_id date '{expected_start_from_id}' does not match local_start_date '{row['local_start_date']}'"
            )

        if row["station_id"] != expected_station:
            raise ValueError(f"Event {eid}: station_id '{row['station_id']}' != expected '{expected_station}'")
        if row["timezone"] != expected_timezone:
            raise ValueError(f"Event {eid}: timezone '{row['timezone']}' != expected '{expected_timezone}'")

        if expected_percentile is not None and abs(float(row["threshold_percentile"]) - expected_percentile) > 1e-6:
            raise ValueError(f"Event {eid}: threshold_percentile {row['threshold_percentile']} != expected {expected_percentile}")
        if expected_percentile_method is not None and row["percentile_method"] != expected_percentile_method:
            raise ValueError(f"Event {eid}: percentile_method '{row['percentile_method']}' != expected '{expected_percentile_method}'")
        if expected_threshold_c is not None and abs(float(row["threshold_temperature_c"]) - expected_threshold_c) > 1e-4:
            raise ValueError(f"Event {eid}: threshold_temperature_c {row['threshold_temperature_c']} != expected {expected_threshold_c}")

        thresh_c = float(row["threshold_temperature_c"])

        d_start = date.fromisoformat(str(row["local_start_date"]))
        d_end = date.fromisoformat(str(row["local_end_date"]))
        if d_start > d_end:
            raise ValueError(f"Event {eid}: local_start_date ({d_start}) > local_end_date ({d_end})")

        calendar_days = (d_end - d_start).days + 1
        dur_days = int(row["duration_days"])
        if dur_days != calendar_days:
            raise ValueError(f"Event {eid}: duration_days {dur_days} inconsistent with calendar dates ({calendar_days})")

        qual_count = int(row["qualifying_day_count"])
        if qual_count != dur_days:
            raise ValueError(f"Event {eid}: qualifying_day_count {qual_count} != duration_days {dur_days}")

        if dur_days < min_consecutive_days:
            raise ValueError(f"Event {eid}: duration_days {dur_days} < min_consecutive_days {min_consecutive_days}")

        missing_inside = int(row["missing_days_inside_event"])
        if missing_inside != 0:
            raise ValueError(f"Event {eid}: missing_days_inside_event {missing_inside} != 0 (runs must be contiguous)")

        t_start = row["event_start_utc"]
        t_end = row["event_end_utc"]
        if not isinstance(t_start, (datetime, pd.Timestamp)) or t_start.tzinfo is None:
            raise ValueError(f"Event {eid}: event_start_utc must be timezone-aware UTC datetime")
        if str(t_start.tzinfo) not in ("UTC", "datetime.timezone.utc", "ZoneInfo(key='UTC')") and t_start.utcoffset() != timedelta(0):
            raise ValueError(f"Event {eid}: event_start_utc timezone must be UTC, got {t_start.tzinfo}")

        if not isinstance(t_end, (datetime, pd.Timestamp)) or t_end.tzinfo is None:
            raise ValueError(f"Event {eid}: event_end_utc must be timezone-aware UTC datetime")
        if str(t_end.tzinfo) not in ("UTC", "datetime.timezone.utc", "ZoneInfo(key='UTC')") and t_end.utcoffset() != timedelta(0):
            raise ValueError(f"Event {eid}: event_end_utc timezone must be UTC, got {t_end.tzinfo}")

        if t_start >= t_end:
            raise ValueError(f"Event {eid}: event_start_utc ({t_start}) >= event_end_utc ({t_end})")

        if t_start.minute != 0 or t_start.second != 0 or t_start.microsecond != 0:
            raise ValueError(f"Event {eid}: event_start_utc ({t_start}) is not top-of-hour")
        if t_end.minute != 0 or t_end.second != 0 or t_end.microsecond != 0:
            raise ValueError(f"Event {eid}: event_end_utc ({t_end}) is not top-of-hour")

        # Verify local midnight to UTC bounds match exactly
        exp_start_loc = datetime(d_start.year, d_start.month, d_start.day, 0, 0, tzinfo=tz)
        next_after_end = d_end + timedelta(days=1)
        exp_end_loc = datetime(next_after_end.year, next_after_end.month, next_after_end.day, 0, 0, tzinfo=tz)
        exp_start_utc = exp_start_loc.astimezone(timezone.utc)
        exp_end_utc = exp_end_loc.astimezone(timezone.utc)

        if t_start != exp_start_utc:
            raise ValueError(f"Event {eid}: event_start_utc {t_start} != expected {exp_start_utc} from {d_start}")
        if t_end != exp_end_utc:
            raise ValueError(f"Event {eid}: event_end_utc {t_end} != expected {exp_end_utc} from {d_end}")

        dur_hours = int(row["duration_hours"])
        diff_hours = int(round((t_end - t_start).total_seconds() / 3600.0))
        if dur_hours != diff_hours:
            raise ValueError(f"Event {eid}: duration_hours {dur_hours} != calculated {diff_hours}")

        d_peak_str = str(row["peak_local_date"])
        d_peak = date.fromisoformat(d_peak_str)
        if not (d_start <= d_peak <= d_end):
            raise ValueError(f"Event {eid}: peak_local_date {d_peak_str} outside [{d_start}, {d_end}]")

        peak_temp = float(row["peak_temperature_c"])
        if peak_temp <= thresh_c:
            raise ValueError(f"Event {eid}: peak_temperature_c {peak_temp} <= threshold {thresh_c}")

        # If daily records are provided, perform ground-truth validation
        if daily_records_by_date is not None:
            curr_date = d_start
            event_daily_maxima: list[float] = []
            while curr_date <= d_end:
                cur_str = curr_date.isoformat()
                if cur_str not in daily_records_by_date:
                    raise ValueError(f"Event {eid}: local date {cur_str} missing from daily records")
                d_rec = daily_records_by_date[cur_str]
                t_max = d_rec.get("daily_max_temperature_c")
                if t_max is None:
                    raise ValueError(f"Event {eid}: daily max temperature is None on {cur_str}")
                if t_max <= thresh_c:
                    raise ValueError(f"Event {eid}: date {cur_str} has daily_max {t_max} <= threshold {thresh_c}")
                event_daily_maxima.append(t_max)
                curr_date += timedelta(days=1)

            # Check peak
            expected_peak_max = max(event_daily_maxima)
            if abs(peak_temp - expected_peak_max) > 1e-4:
                raise ValueError(f"Event {eid}: peak_temperature_c {peak_temp} != daily max {expected_peak_max}")

            # Earliest tie-break for peak
            for cur_d, t in zip([d_start + timedelta(days=i) for i in range(dur_days)], event_daily_maxima):
                if abs(t - expected_peak_max) < 1e-4:
                    if cur_d.isoformat() != d_peak_str:
                        raise ValueError(
                            f"Event {eid}: peak_local_date {d_peak_str} != earliest date with max temp ({cur_d.isoformat()})"
                        )
                    break

            expected_mean_max = float(sum(event_daily_maxima) / len(event_daily_maxima))
            if abs(float(row["mean_max_temperature_c"]) - expected_mean_max) > 1e-4:
                raise ValueError(f"Event {eid}: mean_max_temperature_c mismatch")

            expected_cum_exceed = float(sum(t - thresh_c for t in event_daily_maxima))
            if abs(float(row["cumulative_exceedance_c_days"]) - expected_cum_exceed) > 1e-4:
                raise ValueError(f"Event {eid}: cumulative_exceedance_c_days mismatch")

    # Monotonic ordering
    starts = df_events["event_start_utc"].tolist()
    if starts != sorted(starts):
        raise ValueError("Events are not strictly ordered by event_start_utc")

    # Non-overlapping intervals
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
    expected_timezone: str = "America/Los_Angeles",
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

    if df_labels["timestamp_utc"].duplicated().any():
        dups = df_labels[df_labels["timestamp_utc"].duplicated()]["timestamp_utc"].tolist()
        raise ValueError(f"Duplicate timestamp_utc found in hourly event labels: {dups[:5]} (total {len(dups)})")

    ts_list = df_labels["timestamp_utc"].tolist()
    if ts_list != sorted(ts_list):
        raise ValueError("Hourly event labels are not sorted ascending by timestamp_utc")

    tz = ZoneInfo(expected_timezone)

    for idx, row in df_labels.iterrows():
        ts_utc = row["timestamp_utc"]
        if not isinstance(ts_utc, (datetime, pd.Timestamp)) or ts_utc.tzinfo is None:
            raise ValueError(f"Row {idx}: timestamp_utc must be a timezone-aware UTC datetime, got {ts_utc}")
        if str(ts_utc.tzinfo) not in ("UTC", "datetime.timezone.utc", "ZoneInfo(key='UTC')") and ts_utc.utcoffset() != timedelta(0):
            raise ValueError(f"Row {idx}: timestamp_utc timezone must be UTC, got {ts_utc.tzinfo}")

        if ts_utc.minute != 0 or ts_utc.second != 0 or ts_utc.microsecond != 0:
            raise ValueError(f"Row {idx}: timestamp_utc {ts_utc} is not top-of-hour")

        # Verify local_timestamp, local_date, and hour_local
        ts_loc = ts_utc.astimezone(tz)
        exp_loc_ts = ts_loc.strftime("%Y-%m-%dT%H:%M:%S")
        exp_loc_date = ts_loc.strftime("%Y-%m-%d")
        exp_hour = ts_loc.hour

        if str(row["local_timestamp"]) != exp_loc_ts:
            raise ValueError(f"Row {idx}: local_timestamp '{row['local_timestamp']}' != expected '{exp_loc_ts}'")
        if str(row["local_date"]) != exp_loc_date:
            raise ValueError(f"Row {idx}: local_date '{row['local_date']}' != expected '{exp_loc_date}'")
        if int(row["hour_local"]) != exp_hour:
            raise ValueError(f"Row {idx}: hour_local {row['hour_local']} != expected {exp_hour}")

        phase = str(row["event_phase"])
        if phase not in VALID_EVENT_PHASES:
            raise ValueError(f"Row {idx}: invalid event_phase '{phase}'. Must be in {VALID_EVENT_PHASES}")

        st = str(row["station_id"])
        if st != expected_station:
            raise ValueError(f"Row {idx}: station_id '{st}' != expected '{expected_station}'")

    if df_events is not None:
        known_event_ids = set(df_events["event_id"])
        label_event_ids = set(df_labels["event_id"])
        if not label_event_ids.issubset(known_event_ids):
            unknown = label_event_ids - known_event_ids
            raise ValueError(f"Hourly labels reference unknown event_ids: {unknown}")

        for _, ev in df_events.iterrows():
            eid = ev["event_id"]
            ev_labels = df_labels[df_labels["event_id"] == eid]
            ev_phases = set(ev_labels["event_phase"])

            for req_phase in ("onset", "peak", "recovery"):
                if req_phase not in ev_phases:
                    raise ValueError(f"Event {eid} is missing '{req_phase}' phase rows")

            if int(ev["duration_days"]) > 1 and "sustained" not in ev_phases:
                raise ValueError(f"Event {eid} has duration_days > 1 but is missing 'sustained' phase")

            # Check exact phase counts
            dur_days = int(ev["duration_days"])
            exp_onset_hours = 24
            exp_recovery_hours = 24
            exp_peak_hours = 24
            exp_sustained_hours = (dur_days - 1) * 24

            actual_onset = len(ev_labels[ev_labels["event_phase"] == "onset"])
            actual_recovery = len(ev_labels[ev_labels["event_phase"] == "recovery"])
            actual_peak = len(ev_labels[ev_labels["event_phase"] == "peak"])
            actual_sustained = len(ev_labels[ev_labels["event_phase"] == "sustained"])

            if actual_onset != exp_onset_hours:
                raise ValueError(f"Event {eid}: onset hours {actual_onset} != {exp_onset_hours}")
            if actual_recovery != exp_recovery_hours:
                raise ValueError(f"Event {eid}: recovery hours {actual_recovery} != {exp_recovery_hours}")
            if actual_peak != exp_peak_hours:
                raise ValueError(f"Event {eid}: peak hours {actual_peak} != {exp_peak_hours}")
            if actual_sustained != exp_sustained_hours:
                raise ValueError(f"Event {eid}: sustained hours {actual_sustained} != {exp_sustained_hours}")
