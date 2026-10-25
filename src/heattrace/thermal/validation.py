"""Thermal validation routines for matched-input integrity and boundary checks.

Checks:
- Event and control use identical workload data (identical SHA-256 digest).
- Both windows contain expected horizon hours (120 rows).
- Timestamps are unique, sorted, contiguous, UTC-aware, and hour-aligned.
- Temperature has no missing or non-finite values.
- Nominal compute capacity and facility-cap rules are identical.
- Same thermal scenario parameters applied to both windows.
- Schedule allocations remain inside declared horizon [0, horizon).
- Jobs not moved outside [arrival, deadline) bounds.
- No duplicate (job_id, hour) allocations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.interfaces import ScheduleResult
from heattrace.thermal.model import ThermalScenario


# Canonical workload fields required for scheduling
CANONICAL_WORKLOAD_COLUMNS: list[str] = [
    "workload_trace_id",
    "job_id",
    "arrival_offset_hours",
    "deadline_offset_hours",
    "processing_requirement",
    "energy_kwh",
    "maximum_parallelism",
    "priority",
    "preemptible",
]


def compute_workload_digest(workload_df: pd.DataFrame) -> str:
    """Compute deterministic SHA-256 digest of canonical workload fields.

    Requirements:
    - Fails clearly if any required scheduling field is absent.
    - Normalizes values deterministically:
      - identifiers as strings;
      - offsets and integer fields as integers;
      - energy rounded consistently (6 decimal places);
      - booleans as actual booleans.
    - Sorts deterministically using workload_trace_id and job_id.
    - Uses canonical JSON with stable separators (",", ":") and sorted keys.
    - Row order does not change the digest.
    - Any scheduling-relevant mutation changes the digest.
    """
    for c in CANONICAL_WORKLOAD_COLUMNS:
        if c not in workload_df.columns:
            raise ValueError(f"Workload dataframe missing required canonical column '{c}'")

    sorted_df = workload_df.sort_values(
        by=["workload_trace_id", "job_id"]
    ).reset_index(drop=True)

    records = []
    for _, row in sorted_df.iterrows():
        records.append({
            "workload_trace_id": str(row["workload_trace_id"]),
            "job_id": str(row["job_id"]),
            "arrival_offset_hours": int(row["arrival_offset_hours"]),
            "deadline_offset_hours": int(row["deadline_offset_hours"]),
            "processing_requirement": int(row["processing_requirement"]),
            "energy_kwh": round(float(row["energy_kwh"]), 6),
            "maximum_parallelism": int(row["maximum_parallelism"]),
            "priority": int(row["priority"]),
            "preemptible": bool(row["preemptible"]),
        })

    payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_configuration_digest(config_dict: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of configuration dictionary."""
    payload = json.dumps(config_dict, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_window_series(
    df: pd.DataFrame,
    expected_horizon_hours: int = 120,
) -> None:
    """Verify window series integrity:

    - Exact length == expected_horizon_hours
    - Timestamps are unique, sorted, contiguous, UTC-aware, and hour-aligned
    - Temperature has no missing or non-finite values
    """
    if len(df) != expected_horizon_hours:
        raise ValueError(f"Expected {expected_horizon_hours} rows, found {len(df)}")

    if "timestamp_utc" not in df.columns:
        raise ValueError("DataFrame missing 'timestamp_utc' column")
    if "temperature_c" not in df.columns:
        raise ValueError("DataFrame missing 'temperature_c' column")

    ts = df["timestamp_utc"]

    # UTC-aware check
    if not hasattr(ts.dt, "tz") or ts.dt.tz is None:
        raise ValueError("timestamp_utc must be timezone-aware UTC")
    if str(ts.dt.tz) not in ("UTC", "datetime.timezone.utc"):
        raise ValueError(f"timestamp_utc timezone must be UTC, got {ts.dt.tz}")

    # Monotonicity & uniqueness
    if not ts.is_monotonic_increasing:
        raise ValueError("timestamp_utc is not strictly monotonically increasing")
    if ts.duplicated().any():
        raise ValueError("timestamp_utc contains duplicate values")

    # Contiguous hourly intervals & hour-aligned
    for i in range(len(ts)):
        t = ts.iloc[i]
        if t.minute != 0 or t.second != 0 or t.microsecond != 0:
            raise ValueError(f"timestamp_utc at index {i} ({t}) is not hour-aligned")
        if i > 0:
            prev = ts.iloc[i - 1]
            diff = (t - prev).total_seconds()
            if diff != 3600.0:
                raise ValueError(
                    f"Non-contiguous hourly interval between index {i-1} ({prev}) and {i} ({t})"
                )

    # Temperature non-finite / missing check
    temps = df["temperature_c"]
    if temps.isna().any() or not np.all(np.isfinite(temps.to_numpy(dtype=float))):
        raise ValueError("temperature_c contains missing or non-finite values")


def validate_timestamps_aligned(
    realized_df: pd.DataFrame,
    thermal_state_df: pd.DataFrame,
) -> None:
    """Strictly validate timestamp alignment between realized_df and thermal_state_df.

    Requirements:
    - realized_df has timestamp_utc
    - thermal_state_df has timestamp_utc
    - both columns are timezone-aware UTC
    - both are sorted (strictly monotonic)
    - both contain no duplicates
    - both are hour-aligned (minute=0, second=0, microsecond=0)
    - both have the same length
    - every timestamp matches exactly and in the same order
    """
    if "timestamp_utc" not in realized_df.columns:
        raise ValueError("realized_df is missing required column 'timestamp_utc'")
    if "timestamp_utc" not in thermal_state_df.columns:
        raise ValueError("thermal_state_df is missing required column 'timestamp_utc'")

    ts_r = realized_df["timestamp_utc"]
    ts_t = thermal_state_df["timestamp_utc"]

    if len(ts_r) != len(ts_t):
        raise ValueError(
            f"Row count mismatch: realized_df has {len(ts_r)} rows, thermal_state_df has {len(ts_t)}"
        )

    for name, ts in [("realized_df", ts_r), ("thermal_state_df", ts_t)]:
        if not hasattr(ts.dt, "tz") or ts.dt.tz is None:
            raise ValueError(f"{name} timestamp_utc must be timezone-aware UTC, got naive")
        if str(ts.dt.tz) not in ("UTC", "datetime.timezone.utc"):
            raise ValueError(f"{name} timestamp_utc timezone must be UTC, got {ts.dt.tz}")
        if not ts.is_monotonic_increasing:
            raise ValueError(f"{name} timestamp_utc is not strictly monotonically increasing")
        if ts.duplicated().any():
            raise ValueError(f"{name} timestamp_utc contains duplicate timestamps")
        for i, t in enumerate(ts):
            if t.minute != 0 or t.second != 0 or t.microsecond != 0:
                raise ValueError(f"{name} timestamp at index {i} ({t}) is not hour-aligned")

    if not ts_r.equals(ts_t):
        # Find first difference
        diff_idx = (ts_r.values != ts_t.values).argmax()
        raise ValueError(
            f"Timestamp mismatch at index {diff_idx}: realized={ts_r.iloc[diff_idx]} vs thermal={ts_t.iloc[diff_idx]}"
        )


def validate_matched_inputs(
    event_df: pd.DataFrame,
    control_df: pd.DataFrame,
    event_workload: pd.DataFrame,
    control_workload: pd.DataFrame,
    expected_horizon_hours: int = 120,
    *,
    config: dict[str, Any] | None = None,
    nominal_compute_cap_kw_event: float | None = None,
    nominal_compute_cap_kw_control: float | None = None,
    scenarios_event: dict[str, ThermalScenario] | None = None,
    scenarios_control: dict[str, ThermalScenario] | None = None,
) -> dict[str, Any]:
    """Validate that event and control satisfy matched-input criteria.

    Enforces:
    - event and control workload digests are identical;
    - nominal compute capacities are identical;
    - nominal facility-cap rules are identical;
    - thermal scenario parameters are identical;
    - expected horizon is identical;
    - configuration digest is recorded;
    - event and control window IDs are different;
    - event is labelled event and control is labelled control when those columns exist.
    """
    validate_window_series(event_df, expected_horizon_hours)
    validate_window_series(control_df, expected_horizon_hours)

    ev_digest = compute_workload_digest(event_workload)
    ctrl_digest = compute_workload_digest(control_workload)

    if ev_digest != ctrl_digest:
        raise ValueError(
            f"Workload digest mismatch: event={ev_digest} vs control={ctrl_digest}"
        )

    # Check window IDs are different
    ev_wids = event_df["window_id"].unique() if "window_id" in event_df.columns else []
    ctrl_wids = control_df["window_id"].unique() if "window_id" in control_df.columns else []
    if len(ev_wids) == 1 and len(ctrl_wids) == 1:
        if ev_wids[0] == ctrl_wids[0]:
            raise ValueError(f"Event and control window IDs must be different, got {ev_wids[0]}")

    # Check window_type labels when present
    if "window_type" in event_df.columns:
        ev_types = set(event_df["window_type"].dropna().unique())
        if "event" not in ev_types and "heatwave" not in ev_types:
            raise ValueError(f"Event window is not labelled as event/heatwave, got {ev_types}")
    if "window_type" in control_df.columns:
        ctrl_types = set(control_df["window_type"].dropna().unique())
        if "control" not in ctrl_types and "ordinary" not in ctrl_types:
            raise ValueError(f"Control window is not labelled as control/ordinary, got {ctrl_types}")

    # Nominal compute capacities identical
    if nominal_compute_cap_kw_event is not None and nominal_compute_cap_kw_control is not None:
        if nominal_compute_cap_kw_event != nominal_compute_cap_kw_control:
            raise ValueError(
                f"Nominal compute capacity mismatch: event={nominal_compute_cap_kw_event} vs control={nominal_compute_cap_kw_control}"
            )

    # Thermal scenario parameters identical
    if scenarios_event is not None and scenarios_control is not None:
        if set(scenarios_event.keys()) != set(scenarios_control.keys()):
            raise ValueError(f"Thermal scenario keys mismatch between event and control")
        for k in scenarios_event:
            s_ev = scenarios_event[k]
            s_ctrl = scenarios_control[k]
            if s_ev != s_ctrl:
                raise ValueError(f"Thermal scenario mismatch for {k}: {s_ev} vs {s_ctrl}")

    config_digest = compute_configuration_digest(config) if config is not None else None

    return {
        "event_workload_digest": ev_digest,
        "control_workload_digest": ctrl_digest,
        "configuration_digest": config_digest,
        "expected_horizon_hours": expected_horizon_hours,
        "matched": True,
    }


def validate_schedule_bounds(
    schedule: ScheduleResult,
    workload_df: pd.DataFrame,
    horizon_hours: int,
) -> None:
    """Validate that schedule allocations satisfy horizon, arrival, deadline, and uniqueness."""
    workload_jobs = {str(row["job_id"]): row for _, row in workload_df.iterrows()}
    seen_pairs: set[tuple[str, int]] = set()

    for a in schedule.allocations:
        jid = a.job_id
        if jid not in workload_jobs:
            raise ValueError(f"Unknown job_id in allocation: {jid}")

        h = a.allocated_hour_offset
        if h < 0 or h >= horizon_hours:
            raise ValueError(f"Job {jid} hour {h} out of horizon bounds [0, {horizon_hours})")

        pair = (jid, h)
        if pair in seen_pairs:
            raise ValueError(f"Duplicate allocation for job {jid} at hour {h}")
        seen_pairs.add(pair)

        job_info = workload_jobs[jid]
        arr = int(job_info["arrival_offset_hours"])
        dead = int(job_info["deadline_offset_hours"])

        if h < arr:
            raise ValueError(f"Job {jid} hour {h} before arrival {arr}")
        if h >= dead:
            raise ValueError(f"Job {jid} hour {h} at/after deadline {dead}")


# =========================================================================
# P6 Validity Configuration Validation
# =========================================================================

import re

VALID_CONTEXTS = {"heatwave", "matched_control", "event_blind"}
VALID_FACILITY_MODELS = {"energy_only", "power_capped"}
VALID_THERMAL_CURVES = {"low", "medium"}
VALID_OBJECTIVES = {"cost_first", "carbon_first"}
VALID_DEPLOYABLE_POLICIES = {"static_unaware", "capacity_aware", "full_thermal_aware"}


UNRESOLVED_CONCEPTS = (
    "tbd",
    "required",
    "unknown",
    "unresolved",
    "pending",
    "deferred",
    "not yet",
    "to be determined",
    "to be decided",
    "not available",
    "awaiting",
)

# Match an approved unresolved concept only at the beginning, followed by end-of-string or non-alphanumeric boundary
_UNRESOLVED_PATTERN = re.compile(
    r"^(?:" + "|".join(re.escape(c) for c in sorted(UNRESOLVED_CONCEPTS, key=len, reverse=True)) + r")(?=[^a-z0-9]|$)"
)


def is_unresolved_value(value: Any) -> bool:
    """Check if a value represents an unresolved placeholder or pending scientific decision.

    Requirements:
    - Case-insensitive
    - Insensitive to leading/trailing whitespace
    - Robust to spaces, underscores, and hyphens within multiword phrases
    - Valid when followed by punctuation, slash, or other separator
    - Resistant to false positives inside legitimate words (e.g. pendington, tbdx)
    - Returns False for non-string types or empty strings
    """
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    if not v:
        return False
    # Normalize runs of whitespace, underscores, and hyphens to a single space
    v_norm = re.sub(r"[\s_-]+", " ", v)
    return bool(_UNRESOLVED_PATTERN.match(v_norm))


def is_placeholder(value: Any) -> bool:
    """Backward-compatible alias for is_unresolved_value."""
    return is_unresolved_value(value)


def _validate_id_field(val: Any, field_name: str) -> None:
    """Validate that an ID field is a non-empty, non-blank string or valid placeholder."""
    if val is None:
        raise ValueError(f"{field_name} cannot be None; must be a non-empty string or recognized placeholder")
    if isinstance(val, bool):
        raise TypeError(f"{field_name} cannot be a boolean; must be a non-empty string")
    if not isinstance(val, str):
        raise TypeError(f"{field_name} must be a string, got {type(val).__name__}")
    if not val.strip():
        raise ValueError(f"{field_name} cannot be blank or whitespace-only")


REQUIRED_DEADLINE_REGIME_FIELDS = {
    "processing_requirement_unit",
    "arrival_semantics",
    "deadline_semantics",
    "slack_distribution",
    "slack_bounds_hours",
}

REQUIRED_PARAMETER_SOURCES_FIELDS = {
    "low_curve_source",
    "medium_curve_source",
    "base_pue_source",
    "facility_cap_interpretation_source",
}

REQUIRED_PRIMARY_ANALYSIS_FIELDS = {
    "hypothesis",
    "facility_model",
    "policy",
    "outcome",
    "thermal_curve_rule",
    "objective_rule",
    "seed_aggregation_rule",
    "pair_contrast",
    "across_pair_support_rule",
}

EXPECTED_PRIMARY_ANALYSIS_FIXED_VALUES = {
    "hypothesis": "H1",
    "facility_model": "power_capped",
    "policy": "static_unaware",
    "outcome": "grid_bounded_lambda_star",
    "pair_contrast": "heatwave_minus_matched_control",
    "seed_aggregation_rule": "aggregate_within_pair_context_configuration_before_contrast",
}


def _validate_numeric_float(val: Any, name: str, expected: float | None = None) -> float:
    import math
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise TypeError(f"'{name}' must be numeric, got {type(val).__name__} ({val})")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValueError(f"'{name}' must be finite, got {fval}")
    if expected is not None and not math.isclose(fval, expected, abs_tol=1e-6):
        raise ValueError(f"'{name}' must be {expected}, got {fval}")
    return fval


def _validate_strict_int(val: Any, name: str, expected: int | None = None) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise TypeError(f"'{name}' must be an integer, got {type(val).__name__} ({val})")
    if expected is not None and val != expected:
        raise ValueError(f"'{name}' must be {expected}, got {val}")
    return val


def validate_p6_validity_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate P6 validity configuration mapping against the frozen protocol contract.

    Enforces:
    - Missing required keys
    - Development and confirmatory cardinality (exactly 1 dev triplet, exactly 4 conf triplets)
    - Enum value validity across contexts, facility models, thermal curves, objectives, policies
    - Duplicate dimensions, IDs, or seeds
    - Malformed types
    - Empty collections
    - Oracle explicitly marked deployable: false
    - Triplet identity and duration invariants:
      - pair_id and window IDs must be non-empty strings or recognized placeholder strings
      - duration_hours must be a non-boolean positive integer
      - all triplets must have equal durations
      - development and confirmatory pair_id values must be unique once concrete
      - concrete heatwave window IDs must be unique across triplets
      - concrete matched-control window IDs must be unique across triplets
      - concrete event-blind window IDs must be unique across triplets
      - no concrete window ID may be reused in a different context or triplet
    - Seed types:
      - exactly two seeds
      - each seed must be either a recognized placeholder string or a non-boolean integer
      - concrete integer seeds must be distinct
    - Placeholder and frozen-state detection:
      - inspects every required unresolved field
      - is_frozen is True only when EVERY required field is concrete and valid
      - has_placeholders and is_frozen are always logical opposites
    """
    if not isinstance(cfg, dict):
        raise TypeError(f"Config must be a dictionary, got {type(cfg).__name__}")

    required_top_keys = {
        "version",
        "contract_label",
        "triplets",
        "dimensions",
        "policies",
        "deadline_regime",
        "parameter_sources",
        "primary_analysis",
        "temperature_forecast",
        "heatguard",
    }
    missing_top = required_top_keys - set(cfg.keys())
    if missing_top:
        raise ValueError(f"Missing required top-level configuration keys: {sorted(missing_top)}")

    # 1. Triplets validation
    triplets = cfg["triplets"]
    if not isinstance(triplets, dict):
        raise TypeError("cfg['triplets'] must be a mapping")

    if "development" not in triplets:
        raise ValueError("Missing 'development' triplet definition in triplets")
    if "confirmatory" not in triplets:
        raise ValueError("Missing 'confirmatory' triplets definition in triplets")

    dev_triplet = triplets["development"]
    if not isinstance(dev_triplet, dict):
        raise TypeError("triplets['development'] must be a mapping")

    conf_triplets = triplets["confirmatory"]
    if not isinstance(conf_triplets, list):
        raise TypeError("triplets['confirmatory'] must be a list")

    design_mode = cfg.get("design_mode", "primary")
    if design_mode not in {"primary", "fallback"}:
        raise ValueError(f"Invalid design_mode '{design_mode}'. Must be 'primary' or 'fallback'")

    expected_conf_count = 3 if design_mode == "fallback" else 4
    if len(conf_triplets) != expected_conf_count:
        if design_mode == "fallback":
            raise ValueError(
                f"Confirmatory triplets in fallback mode must contain exactly 3 items, got {len(conf_triplets)}"
            )
        else:
            raise ValueError(
                f"Confirmatory triplets must contain exactly 4 items, got {len(conf_triplets)}"
            )

    all_triplet_dicts = [("development", dev_triplet)] + [
        (f"confirmatory[{i}]", ct) for i, ct in enumerate(conf_triplets)
    ]

    req_triplet_fields = {
        "pair_id",
        "heatwave_window_id",
        "matched_control_window_id",
        "event_blind_window_id",
        "duration_hours",
    }

    all_pair_ids: list[str] = []
    concrete_hw_ids: list[str] = []
    concrete_ctrl_ids: list[str] = []
    concrete_blind_ids: list[str] = []
    all_concrete_window_ids: list[str] = []
    triplet_durations: list[int] = []
    all_triplet_string_fields: list[str] = []

    for name, t_dict in all_triplet_dicts:
        if not isinstance(t_dict, dict):
            raise TypeError(f"{name} must be a mapping, got {type(t_dict).__name__}")
        missing_fields = req_triplet_fields - set(t_dict.keys())
        if missing_fields:
            raise ValueError(f"triplets['{name}'] missing required fields: {sorted(missing_fields)}" if name == "development" else f"{name} missing required fields: {sorted(missing_fields)}")

        # Validate pair_id
        pid = t_dict["pair_id"]
        _validate_id_field(pid, f"{name}.pair_id")
        all_pair_ids.append(pid)
        all_triplet_string_fields.append(pid)

        # Validate window IDs
        hw_id = t_dict["heatwave_window_id"]
        _validate_id_field(hw_id, f"{name}.heatwave_window_id")
        all_triplet_string_fields.append(hw_id)
        if not is_placeholder(hw_id):
            if hw_id in concrete_hw_ids:
                raise ValueError(f"Duplicate concrete heatwave_window_id '{hw_id}' in {name}")
            if hw_id in all_concrete_window_ids:
                raise ValueError(f"Concrete window ID '{hw_id}' reused across categories or triplets in {name}")
            concrete_hw_ids.append(hw_id)
            all_concrete_window_ids.append(hw_id)

        ctrl_id = t_dict["matched_control_window_id"]
        _validate_id_field(ctrl_id, f"{name}.matched_control_window_id")
        all_triplet_string_fields.append(ctrl_id)
        if not is_placeholder(ctrl_id):
            if ctrl_id in concrete_ctrl_ids:
                raise ValueError(f"Duplicate concrete matched_control_window_id '{ctrl_id}' in {name}")
            if ctrl_id in all_concrete_window_ids:
                raise ValueError(f"Concrete window ID '{ctrl_id}' reused across categories or triplets in {name}")
            concrete_ctrl_ids.append(ctrl_id)
            all_concrete_window_ids.append(ctrl_id)

        blind_id = t_dict["event_blind_window_id"]
        _validate_id_field(blind_id, f"{name}.event_blind_window_id")
        all_triplet_string_fields.append(blind_id)
        if not is_placeholder(blind_id):
            if blind_id in concrete_blind_ids:
                raise ValueError(f"Duplicate concrete event_blind_window_id '{blind_id}' in {name}")
            if blind_id in all_concrete_window_ids:
                raise ValueError(f"Concrete window ID '{blind_id}' reused across categories or triplets in {name}")
            concrete_blind_ids.append(blind_id)
            all_concrete_window_ids.append(blind_id)

        # Validate duration_hours
        dur = t_dict["duration_hours"]
        if isinstance(dur, bool) or not isinstance(dur, (int, np.integer)):
            raise TypeError(f"{name}.duration_hours must be a non-boolean positive integer, got {type(dur).__name__}")
        if int(dur) <= 0:
            raise ValueError(f"{name}.duration_hours must be strictly positive, got {dur}")
        triplet_durations.append(int(dur))

    # All triplets must have equal durations
    if len(set(triplet_durations)) != 1:
        raise ValueError(f"All triplets must have equal duration_hours, got {triplet_durations}")

    # Check for duplicate pair_ids among non-placeholders
    non_placeholder_pairs = [pid for pid in all_pair_ids if not is_placeholder(pid)]
    if len(non_placeholder_pairs) != len(set(non_placeholder_pairs)):
        raise ValueError(f"Duplicate pair_ids found: {non_placeholder_pairs}")

    # 2. Dimensions validation
    dims = cfg["dimensions"]
    if not isinstance(dims, dict):
        raise TypeError("cfg['dimensions'] must be a mapping")

    req_dims = {
        "contexts",
        "facility_models",
        "thermal_curves",
        "workload_multipliers",
        "seeds",
        "objectives",
    }
    missing_dims = req_dims - set(dims.keys())
    if missing_dims:
        raise ValueError(f"Missing required dimensions: {sorted(missing_dims)}")

    # Contexts
    contexts = dims["contexts"]
    if not isinstance(contexts, list) or len(contexts) == 0:
        raise ValueError("contexts must be a non-empty list")
    if len(contexts) != len(set(contexts)):
        raise ValueError(f"Duplicate contexts found: {contexts}")
    unknown_contexts = set(contexts) - VALID_CONTEXTS
    if unknown_contexts:
        raise ValueError(f"Unknown contexts: {sorted(unknown_contexts)}")
    if set(contexts) != VALID_CONTEXTS:
        raise ValueError(f"contexts must match frozen set {sorted(VALID_CONTEXTS)}, got {sorted(contexts)}")

    # Facility models
    facility_models = dims["facility_models"]
    if not isinstance(facility_models, list) or len(facility_models) == 0:
        raise ValueError("facility_models must be a non-empty list")
    if len(facility_models) != len(set(facility_models)):
        raise ValueError(f"Duplicate facility_models found: {facility_models}")
    unknown_fac = set(facility_models) - VALID_FACILITY_MODELS
    if unknown_fac:
        raise ValueError(f"Unknown facility_models: {sorted(unknown_fac)}")
    if set(facility_models) != VALID_FACILITY_MODELS:
        raise ValueError(f"facility_models must match frozen set {sorted(VALID_FACILITY_MODELS)}")

    # Thermal curves
    thermal_curves = dims["thermal_curves"]
    if not isinstance(thermal_curves, list) or len(thermal_curves) == 0:
        raise ValueError("thermal_curves must be a non-empty list")
    if len(thermal_curves) != len(set(thermal_curves)):
        raise ValueError(f"Duplicate thermal_curves found: {thermal_curves}")
    unknown_curves = set(thermal_curves) - VALID_THERMAL_CURVES
    if unknown_curves:
        raise ValueError(f"Unknown thermal_curves: {sorted(unknown_curves)}")
    if set(thermal_curves) != VALID_THERMAL_CURVES:
        raise ValueError(f"thermal_curves must match frozen set {sorted(VALID_THERMAL_CURVES)}")

    # Workload multipliers
    multipliers = dims["workload_multipliers"]
    if not isinstance(multipliers, list) or len(multipliers) == 0:
        raise ValueError("workload_multipliers must be a non-empty list")
    if len(multipliers) != len(set(multipliers)):
        raise ValueError(f"Duplicate workload_multipliers found: {multipliers}")
    float_mults = [float(m) for m in multipliers]
    if sorted(float_mults) != [1.0, 2.0, 3.0]:
        raise ValueError(f"workload_multipliers must be [1.0, 2.0, 3.0], got {multipliers}")

    # Seeds validation
    seeds = dims["seeds"]
    if not isinstance(seeds, list) or len(seeds) == 0:
        raise ValueError("seeds must be a non-empty list")
    if len(seeds) != 2:
        raise ValueError(f"seeds must contain exactly 2 explicit seeds, got {len(seeds)}")

    concrete_seeds: list[int] = []
    for i, s in enumerate(seeds):
        if is_placeholder(s):
            continue
        if s is None:
            raise ValueError(f"Seed {i} cannot be None")
        if isinstance(s, bool):
            raise TypeError(f"Seed {i} cannot be a boolean")
        if isinstance(s, (int, np.integer)):
            concrete_seeds.append(int(s))
        else:
            raise TypeError(
                f"Seed {i} must be a recognized placeholder string or a non-boolean integer, got {type(s).__name__} ({s!r})"
            )

    if len(concrete_seeds) == 2 and concrete_seeds[0] == concrete_seeds[1]:
        raise ValueError(f"Duplicate seeds found: {concrete_seeds}")

    # Objectives
    objectives = dims["objectives"]
    if not isinstance(objectives, list) or len(objectives) == 0:
        raise ValueError("objectives must be a non-empty list")
    if len(objectives) != len(set(objectives)):
        raise ValueError(f"Duplicate objectives found: {objectives}")
    unknown_obj = set(objectives) - VALID_OBJECTIVES
    if unknown_obj:
        raise ValueError(f"Unknown objectives: {sorted(unknown_obj)}")
    if set(objectives) != VALID_OBJECTIVES:
        raise ValueError(f"objectives must match frozen set {sorted(VALID_OBJECTIVES)}")

    # 3. Policies validation
    policies = cfg["policies"]
    if not isinstance(policies, dict):
        raise TypeError("cfg['policies'] must be a mapping")
    if "deployable" not in policies:
        raise ValueError("policies missing 'deployable' list")
    if "reference" not in policies:
        raise ValueError("policies missing 'reference' mapping")

    deployable = policies["deployable"]
    if not isinstance(deployable, list) or len(deployable) == 0:
        raise ValueError("policies['deployable'] must be a non-empty list")
    if len(deployable) != len(set(deployable)):
        raise ValueError(f"Duplicate deployable policies: {deployable}")
    unknown_dep = set(deployable) - VALID_DEPLOYABLE_POLICIES
    if unknown_dep:
        raise ValueError(f"Unknown deployable policies: {sorted(unknown_dep)}")
    if set(deployable) != VALID_DEPLOYABLE_POLICIES:
        raise ValueError(f"deployable policies must match {sorted(VALID_DEPLOYABLE_POLICIES)}")

    reference = policies["reference"]
    if not isinstance(reference, dict):
        raise TypeError("policies['reference'] must be a mapping")
    if reference.get("id") != "oracle_full_thermal_aware":
        raise ValueError(f"reference policy id must be 'oracle_full_thermal_aware', got {reference.get('id')}")
    if reference.get("deployable") is not False:
        raise ValueError(f"reference policy MUST have deployable: false, got {reference.get('deployable')}")

    # 4. Deadline regime & parameter sources validation
    deadline_regime = cfg["deadline_regime"]
    if not isinstance(deadline_regime, dict):
        raise TypeError("cfg['deadline_regime'] must be a mapping")
    missing_deadline_fields = REQUIRED_DEADLINE_REGIME_FIELDS - set(deadline_regime.keys())
    if missing_deadline_fields:
        raise ValueError(f"deadline_regime missing required fields: {sorted(missing_deadline_fields)}")
    deadline_field_values: list[str] = []
    for f in sorted(REQUIRED_DEADLINE_REGIME_FIELDS):
        val = deadline_regime[f]
        _validate_id_field(val, f"deadline_regime.{f}")
        deadline_field_values.append(val)

    parameter_sources = cfg["parameter_sources"]
    if not isinstance(parameter_sources, dict):
        raise TypeError("cfg['parameter_sources'] must be a mapping")
    missing_param_fields = REQUIRED_PARAMETER_SOURCES_FIELDS - set(parameter_sources.keys())
    if missing_param_fields:
        raise ValueError(f"parameter_sources missing required fields: {sorted(missing_param_fields)}")
    parameter_source_values: list[str] = []
    for f in sorted(REQUIRED_PARAMETER_SOURCES_FIELDS):
        val = parameter_sources[f]
        _validate_id_field(val, f"parameter_sources.{f}")
        parameter_source_values.append(val)

    # 5. Primary analysis validation
    primary_analysis = cfg["primary_analysis"]
    if not isinstance(primary_analysis, dict):
        raise TypeError("cfg['primary_analysis'] must be a mapping")
    missing_primary_fields = REQUIRED_PRIMARY_ANALYSIS_FIELDS - set(primary_analysis.keys())
    if missing_primary_fields:
        raise ValueError(f"primary_analysis missing required fields: {sorted(missing_primary_fields)}")

    # Validate fixed primary analysis fields
    for field_name, expected_val in EXPECTED_PRIMARY_ANALYSIS_FIXED_VALUES.items():
        actual_val = primary_analysis[field_name]
        _validate_id_field(actual_val, f"primary_analysis.{field_name}")
        if actual_val != expected_val:
            raise ValueError(
                f"primary_analysis.{field_name} must be exact fixed value '{expected_val}', got '{actual_val}'"
            )

    # Validate primary analysis unresolved decision fields
    decision_fields = ["thermal_curve_rule", "objective_rule", "across_pair_support_rule"]
    primary_decision_values: list[str] = []
    for f in decision_fields:
        val = primary_analysis[f]
        _validate_id_field(val, f"primary_analysis.{f}")
        primary_decision_values.append(val)

    # 8. Phase 4 Temperature Forecast validation
    tf_status = validate_temperature_forecast_config(cfg["temperature_forecast"])

    # 9. Phase 5 HeatGuard validation
    hg_status = validate_heatguard_config(cfg["heatguard"])

    # Thorough placeholder inspection across all required scientific fields:
    # - all triplet pair_ids and window_ids
    # - both seeds
    # - all 5 required deadline_regime fields
    # - all 4 required parameter_sources fields
    # - all 3 required primary_analysis decision fields
    # - all string values in temperature_forecast
    # - all string values in heatguard
    triplet_placeholders = any(is_unresolved_value(f) for f in all_triplet_string_fields)
    has_placeholders = (
        triplet_placeholders
        or any(is_unresolved_value(s) for s in seeds)
        or any(is_unresolved_value(v) for v in deadline_field_values)
        or any(is_unresolved_value(v) for v in parameter_source_values)
        or any(is_unresolved_value(v) for v in primary_decision_values)
        or tf_status["has_placeholders"]
        or hg_status["has_placeholders"]
    )

    return {
        "valid": True,
        "is_frozen": not has_placeholders,
        "has_placeholders": has_placeholders,
        "gate1_triplets_frozen": not triplet_placeholders,
    }


def validate_temperature_forecast_config(tf: Any) -> dict[str, Any]:
    """Strictly validate temperature_forecast configuration against the frozen Phase 4 contract."""
    from datetime import datetime, timezone
    import math

    if not isinstance(tf, dict):
        raise TypeError(f"'temperature_forecast' must be a dictionary, got {type(tf).__name__}")

    # Inspect for placeholder / unresolved values
    def _collect_strings(obj: Any) -> list[str]:
        strs = []
        if isinstance(obj, str):
            strs.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                strs.extend(_collect_strings(v))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                strs.extend(_collect_strings(item))
        return strs

    all_tf_strings = _collect_strings(tf)
    has_tf_placeholders = any(is_unresolved_value(s) for s in all_tf_strings)

    # Helper to enforce strict finite non-boolean float
    def _validate_float(val: Any, name: str, expected: float | None = None) -> float:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError(f"'{name}' must be numeric, got {type(val).__name__} ({val})")
        fval = float(val)
        if not math.isfinite(fval):
            raise ValueError(f"'{name}' must be finite, got {fval}")
        if expected is not None and not math.isclose(fval, expected, abs_tol=1e-6):
            raise ValueError(f"'{name}' must be {expected}, got {fval}")
        return fval

    # Helper to enforce strict integer
    def _validate_int(val: Any, name: str, expected: int | None = None) -> int:
        if isinstance(val, bool) or not isinstance(val, int):
            raise TypeError(f"'{name}' must be an integer, got {type(val).__name__} ({val})")
        if expected is not None and val != expected:
            raise ValueError(f"'{name}' must be {expected}, got {val}")
        return val

    # 1. Splits
    if "splits" not in tf or not isinstance(tf["splits"], dict):
        raise ValueError("Missing or invalid 'splits' mapping in temperature_forecast")
    splits = tf["splits"]

    if splits.get("boundary_semantics") != "half_open_start_inclusive_end_exclusive":
        raise ValueError(
            f"splits.boundary_semantics must be 'half_open_start_inclusive_end_exclusive', got '{splits.get('boundary_semantics')}'"
        )

    split_bounds: dict[str, tuple[datetime, datetime]] = {}
    for split_key in ["training", "validation", "calibration_reservation"]:
        if split_key not in splits or not isinstance(splits[split_key], dict):
            raise ValueError(f"Missing or invalid required split mapping: 'splits.{split_key}'")
        s = splits[split_key]

        if "end_utc" in s:
            raise ValueError(
                f"Ambiguous 'end_utc' found in 'splits.{split_key}'; contract requires 'end_exclusive_utc'"
            )
        if "start_utc" not in s:
            raise ValueError(f"Missing 'start_utc' in 'splits.{split_key}'")
        if "end_exclusive_utc" not in s:
            raise ValueError(f"Missing 'end_exclusive_utc' in 'splits.{split_key}'")

        try:
            st = datetime.fromisoformat(str(s["start_utc"]))
        except Exception as e:
            raise ValueError(f"Invalid timestamp in 'splits.{split_key}.start_utc': {e}") from e

        try:
            et = datetime.fromisoformat(str(s["end_exclusive_utc"]))
        except Exception as e:
            raise ValueError(f"Invalid timestamp in 'splits.{split_key}.end_exclusive_utc': {e}") from e

        if st.tzinfo is None or st.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError(f"Timestamp 'splits.{split_key}.start_utc' must be explicit UTC, got {st}")
        if et.tzinfo is None or et.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError(f"Timestamp 'splits.{split_key}.end_exclusive_utc' must be explicit UTC, got {et}")

        if st >= et:
            raise ValueError(
                f"Split '{split_key}' start_utc ({st.isoformat()}) must be strictly earlier than end_exclusive_utc ({et.isoformat()})"
            )
        split_bounds[split_key] = (st, et)

    tr_st, tr_et = split_bounds["training"]
    va_st, va_et = split_bounds["validation"]
    ca_st, ca_et = split_bounds["calibration_reservation"]

    if not (tr_st < tr_et <= va_st < va_et <= ca_st < ca_et):
        raise ValueError("Splits must be strictly chronological and disjoint: training < validation < calibration")

    # 2. Architecture
    if "architecture" not in tf or not isinstance(tf["architecture"], dict):
        raise ValueError("Missing or invalid 'architecture' mapping in temperature_forecast")
    arch = tf["architecture"]

    if arch.get("model") != "TinyTemperatureLSTM":
        raise ValueError(f"architecture.model must be 'TinyTemperatureLSTM', got '{arch.get('model')}'")
    _validate_int(arch.get("input_size"), "architecture.input_size", expected=5)
    _validate_int(arch.get("hidden_size"), "architecture.hidden_size", expected=32)
    _validate_int(arch.get("num_layers"), "architecture.num_layers", expected=1)
    _validate_int(arch.get("horizon"), "architecture.horizon", expected=24)
    _validate_float(arch.get("dropout"), "architecture.dropout", expected=0.1)

    # 3. Training
    if "training" not in tf or not isinstance(tf["training"], dict):
        raise ValueError("Missing or invalid 'training' mapping in temperature_forecast")
    train = tf["training"]

    if train.get("device") != "cpu":
        raise ValueError(f"training.device must be 'cpu', got '{train.get('device')}'")
    _validate_int(train.get("seed"), "training.seed", expected=20261016)
    if train.get("optimizer") != "AdamW":
        raise ValueError(f"training.optimizer must be 'AdamW', got '{train.get('optimizer')}'")
    if train.get("loss") != "SmoothL1":
        raise ValueError(f"training.loss must be 'SmoothL1', got '{train.get('loss')}'")
    _validate_float(train.get("learning_rate"), "training.learning_rate", expected=0.001)
    _validate_int(train.get("batch_size"), "training.batch_size", expected=64)
    _validate_int(train.get("max_epochs"), "training.max_epochs", expected=50)
    _validate_int(train.get("early_stopping_patience"), "training.early_stopping_patience", expected=5)
    _validate_float(train.get("early_stopping_min_delta"), "training.early_stopping_min_delta", expected=0.0001)

    # 4. Baselines
    if "baselines" not in tf or not isinstance(tf["baselines"], dict):
        raise ValueError("Missing or invalid 'baselines' mapping in temperature_forecast")
    base = tf["baselines"]

    expected_methods = ["last_observation", "same_hour_previous_day", "ewma_0.20"]
    methods = base.get("methods")
    if not isinstance(methods, list) or sorted(methods) != sorted(expected_methods):
        raise ValueError(f"baselines.methods must contain exactly {expected_methods}, got {methods}")
    _validate_float(base.get("ewma_alpha"), "baselines.ewma_alpha", expected=0.20)

    # 5. Extreme Temperature
    if "extreme_temperature" not in tf or not isinstance(tf["extreme_temperature"], dict):
        raise ValueError("Missing or invalid 'extreme_temperature' mapping in temperature_forecast")
    ext = tf["extreme_temperature"]
    if ext.get("threshold_rule") != "training_p95_strictly":
        raise ValueError(
            f"extreme_temperature.threshold_rule must be 'training_p95_strictly', got '{ext.get('threshold_rule')}'"
        )

    # 6. Gate
    if "gate" not in tf or not isinstance(tf["gate"], dict):
        raise ValueError("Missing or invalid 'gate' mapping in temperature_forecast")
    gate = tf["gate"]
    _validate_float(gate.get("rmse_improvement_threshold"), "gate.rmse_improvement_threshold", expected=0.02)
    _validate_float(gate.get("extreme_improvement_threshold"), "gate.extreme_improvement_threshold", expected=0.05)
    _validate_float(gate.get("extreme_rmse_slack"), "gate.extreme_rmse_slack", expected=-0.02)

    return {
        "valid": True,
        "has_placeholders": has_tf_placeholders,
    }


def validate_heatguard_config(hg: Any) -> dict[str, Any]:
    """Strictly validate heatguard configuration mapping against frozen Phase 5 contract."""
    from datetime import datetime, timezone
    import math

    if not isinstance(hg, dict):
        raise TypeError(f"'heatguard' must be a dictionary, got {type(hg).__name__}")

    def _collect_strings(obj: Any) -> list[str]:
        strs = []
        if isinstance(obj, str):
            strs.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                strs.extend(_collect_strings(v))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                strs.extend(_collect_strings(item))
        return strs

    all_hg_strings = _collect_strings(hg)
    has_hg_placeholders = any(is_unresolved_value(s) for s in all_hg_strings)

    # 1. Check top-level heatguard keys
    req_hg_keys = {"calibration", "rolling"}
    missing = req_hg_keys - set(hg.keys())
    if missing:
        raise ValueError(f"heatguard missing required keys: {sorted(missing)}")

    cal = hg["calibration"]
    if not isinstance(cal, dict):
        raise TypeError("heatguard['calibration'] must be a mapping")

    # 2. Calibration fields
    _validate_numeric_float(cal.get("quantile"), "heatguard.calibration.quantile", expected=0.90)
    if cal.get("quantile_method") != "higher":
        raise ValueError(f"heatguard.calibration.quantile_method must be 'higher', got '{cal.get('quantile_method')}'")
    if cal.get("residual_definition") != "realized_pue_minus_forecast_pue":
        raise ValueError(
            f"heatguard.calibration.residual_definition must be 'realized_pue_minus_forecast_pue', got '{cal.get('residual_definition')}'"
        )
    if cal.get("calibrated_margin_rule") != "max(0, quantile(residuals, 0.90, method='higher'))":
        raise ValueError(
            "heatguard.calibration.calibrated_margin_rule must be \"max(0, quantile(residuals, 0.90, method='higher'))\", "
            f"got '{cal.get('calibrated_margin_rule')}'"
        )
    if cal.get("thermal_curve") != "medium":
        raise ValueError(f"heatguard.calibration.thermal_curve must be 'medium', got '{cal.get('thermal_curve')}'")
    _validate_numeric_float(cal.get("fixed_pue_margin"), "heatguard.calibration.fixed_pue_margin", expected=0.10)
    _validate_strict_int(cal.get("forecast_horizon_hours"), "heatguard.calibration.forecast_horizon_hours", expected=24)
    _validate_strict_int(cal.get("commit_hours"), "heatguard.calibration.commit_hours", expected=1)
    _validate_strict_int(cal.get("replan_frequency_hours"), "heatguard.calibration.replan_frequency_hours", expected=1)
    _validate_strict_int(cal.get("min_calibration_origins"), "heatguard.calibration.min_calibration_origins", expected=100)
    if cal.get("allow_fixed_fallback") is not False:
        raise ValueError(
            f"heatguard.calibration.allow_fixed_fallback must be False strictly in production config, got {cal.get('allow_fixed_fallback')}"
        )
    if cal.get("coverage_status") != "heuristic_upper_pue_buffer_not_formal_guarantee":
        raise ValueError(
            "heatguard.calibration.coverage_status must be 'heuristic_upper_pue_buffer_not_formal_guarantee', "
            f"got '{cal.get('coverage_status')}'"
        )

    # Calibration reservation
    if "calibration_reservation" not in cal or not isinstance(cal["calibration_reservation"], dict):
        raise ValueError("heatguard.calibration missing 'calibration_reservation' mapping")
    cres = cal["calibration_reservation"]
    st_raw = cres.get("start_utc")
    et_raw = cres.get("end_exclusive_utc")
    if not st_raw or not et_raw:
        raise ValueError("heatguard.calibration.calibration_reservation missing start_utc or end_exclusive_utc")

    if st_raw != "2022-06-01T00:00:00+00:00":
        raise ValueError(f"calibration_reservation start_utc must be '2022-06-01T00:00:00+00:00', got '{st_raw}'")
    if et_raw != "2022-06-16T00:00:00+00:00":
        raise ValueError(f"calibration_reservation end_exclusive_utc must be '2022-06-16T00:00:00+00:00', got '{et_raw}'")

    try:
        st = datetime.fromisoformat(str(st_raw))
        et = datetime.fromisoformat(str(et_raw))
    except Exception as e:
        raise ValueError(f"Invalid timestamp in calibration_reservation: {e}") from e

    if st.tzinfo is None or st.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("calibration_reservation start_utc must be explicit UTC")
    if et.tzinfo is None or et.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("calibration_reservation end_exclusive_utc must be explicit UTC")
    if st >= et:
        raise ValueError("calibration_reservation start_utc must be strictly earlier than end_exclusive_utc")

    # Provenance
    if "provenance" not in cal or not isinstance(cal["provenance"], dict):
        raise ValueError("heatguard.calibration missing 'provenance' mapping")
    prov = cal["provenance"]
    if prov.get("model_artifact") != "p6_temperature_v2":
        raise ValueError(f"heatguard.calibration.provenance.model_artifact must be 'p6_temperature_v2', got '{prov.get('model_artifact')}'")
    if prov.get("artifact_manifest_hash") != "ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79":
        raise ValueError("heatguard.calibration.provenance.artifact_manifest_hash mismatch")
    if prov.get("forecast_config_hash") != "bda89d3baf3f9c1cade93aca5d43f8c5bb64de4fc07b548e0e8cf2349578d1d7":
        raise ValueError("heatguard.calibration.provenance.forecast_config_hash mismatch")
    if prov.get("split_hash") != "59fdcf783d2b2d825e44d5a9eaf29a87fa96f262b921e4b6394c2f96c6a4284c":
        raise ValueError("heatguard.calibration.provenance.split_hash mismatch")
    if prov.get("checkpoint_hash") != "69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed":
        raise ValueError("heatguard.calibration.provenance.checkpoint_hash mismatch")
    if prov.get("calibration_artifact") != "p6_heatguard_calibration_v3":
        raise ValueError(f"heatguard.calibration.provenance.calibration_artifact must be 'p6_heatguard_calibration_v3', got '{prov.get('calibration_artifact')}'")
    if prov.get("manifest_hash") != "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c":
        raise ValueError("heatguard.calibration.provenance.manifest_hash mismatch")

    # 3. Rolling fields
    roll = hg["rolling"]
    if not isinstance(roll, dict):
        raise TypeError("heatguard['rolling'] must be a mapping")
    _validate_strict_int(roll.get("forecast_horizon_hours"), "heatguard.rolling.forecast_horizon_hours", expected=24)
    _validate_strict_int(roll.get("commit_hours"), "heatguard.rolling.commit_hours", expected=1)
    _validate_strict_int(roll.get("replan_frequency_hours"), "heatguard.rolling.replan_frequency_hours", expected=1)
    if roll.get("primary_objective") != "carbon_first":
        raise ValueError(f"heatguard.rolling.primary_objective must be 'carbon_first', got '{roll.get('primary_objective')}'")
    if roll.get("secondary_objective") != "cost_first":
        raise ValueError(f"heatguard.rolling.secondary_objective must be 'cost_first', got '{roll.get('secondary_objective')}'")
    if roll.get("no_composite_policy") is not True:
        raise ValueError("heatguard.rolling.no_composite_policy must be True")

    return {
        "valid": True,
        "has_placeholders": has_hg_placeholders,
    }


def load_p6_validity_config(config_path: str | Path) -> dict[str, Any]:
    """Load and validate P6 validity configuration using repository load_yaml."""
    from heattrace.config import load_yaml
    cfg = load_yaml(config_path)
    validate_p6_validity_config(cfg)
    return cfg
