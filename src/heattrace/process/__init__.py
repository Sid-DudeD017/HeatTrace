"""HeatTrace processing and alignment package."""

from __future__ import annotations

from .alignment import build_aligned_dataset, write_aligned_outputs
from .quality import validate_aligned_dataframe
from .events import (
    build_and_export_events,
    build_hourly_phase_labels,
    compute_heatwave_percentile_threshold,
    detect_heatwave_events,
    inspect_heatwave_events,
    write_event_coverage_csv,
    write_event_manifest_json,
)
from .event_validation import (
    EVENT_CATALOGUE_COLUMNS,
    HOURLY_EVENT_LABEL_COLUMNS,
    VALID_EVENT_PHASES,
    validate_heatwave_events,
    validate_hourly_event_labels,
)

__all__ = [
    "build_aligned_dataset",
    "write_aligned_outputs",
    "validate_aligned_dataframe",
    "compute_heatwave_percentile_threshold",
    "detect_heatwave_events",
    "build_hourly_phase_labels",
    "write_event_coverage_csv",
    "write_event_manifest_json",
    "build_and_export_events",
    "inspect_heatwave_events",
    "EVENT_CATALOGUE_COLUMNS",
    "HOURLY_EVENT_LABEL_COLUMNS",
    "VALID_EVENT_PHASES",
    "validate_heatwave_events",
    "validate_hourly_event_labels",
]
