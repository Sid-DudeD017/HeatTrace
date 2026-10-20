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
    load_heatwave_config,
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
from .controls import (
    CONTROL_CATALOGUE_COLUMNS,
    build_and_export_controls,
    match_deterministic_control,
    validate_control_dataframe,
)
from .benchmark import (
    BENCHMARK_COLUMNS,
    build_and_export_p3_benchmark,
    inspect_benchmark_dataset,
    validate_benchmark_dataframe,
)
from .audit import run_p3_audit, print_p3_audit_report

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
    "load_heatwave_config",
    "EVENT_CATALOGUE_COLUMNS",
    "HOURLY_EVENT_LABEL_COLUMNS",
    "VALID_EVENT_PHASES",
    "validate_heatwave_events",
    "validate_hourly_event_labels",
    "CONTROL_CATALOGUE_COLUMNS",
    "match_deterministic_control",
    "validate_control_dataframe",
    "build_and_export_controls",
    "BENCHMARK_COLUMNS",
    "build_and_export_p3_benchmark",
    "inspect_benchmark_dataset",
    "validate_benchmark_dataframe",
    "run_p3_audit",
    "print_p3_audit_report",
]
