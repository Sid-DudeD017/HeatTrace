"""Deterministic workload scaling implementation for HeatTrace Phase 3."""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

from heattrace.workload.generator import WORKLOAD_JOB_COLUMNS, validate_workload_dataframe

SUPPORTED_MULTIPLIERS: tuple[float, ...] = (1.0, 2.0, 3.0)
FROZEN_WORKLOAD_SEEDS: tuple[int, ...] = (20261016, 20261017)


def scale_workload(
    workload_df: pd.DataFrame,
    multiplier: float,
    *,
    seed: int,
    expected_window_hours: int | None = None,
) -> pd.DataFrame:
    """Scale a canonical workload deterministically by 1.0, 2.0, or 3.0.

    Requirements:
    - Accept only frozen seeds (20261016, 20261017) and multipliers (1.0, 2.0, 3.0).
    - Validate the existing workload schema using current validation utilities.
    - Require input DataFrame to contain exactly one unique seed matching the seed argument.
    - Reject missing, null, non-integer, boolean, or mixed seed values.
    - Return a new DataFrame without mutating the input.
    - 1x preserves the canonical workload content (frame-equivalent), including its workload_trace_id.
    - 2x/3x receive deterministic multiplier-and-seed-specific trace IDs:
      <source_trace_id>__x<int_multiplier>__seed<int_seed>
    - 2x/3x produce deterministic replica IDs with no collisions.
    - Preserve exact total processing and energy ratios.
    - Preserve deterministic row ordering.
    - Validate the generated result before returning it.
    - Reject booleans, NaN, infinity, unsupported multipliers, duplicate source IDs,
      inconsistent trace IDs, and malformed workloads loudly.
    """
    # 1. Type and value validations for multiplier and seed
    if isinstance(multiplier, bool):
        raise TypeError(f"multiplier cannot be a boolean, got {multiplier!r}")
    if not isinstance(multiplier, (int, float, np.number)):
        raise TypeError(f"multiplier must be numeric, got {type(multiplier).__name__}")
    if not math.isfinite(multiplier):
        raise ValueError(f"multiplier must be finite, got {multiplier}")

    mult_float = float(multiplier)
    # Match against supported multipliers with close tolerance
    matched_multiplier = None
    for sup in SUPPORTED_MULTIPLIERS:
        if math.isclose(mult_float, sup, rel_tol=1e-9, abs_tol=1e-9):
            matched_multiplier = sup
            break

    if matched_multiplier is None:
        raise ValueError(
            f"Unsupported multiplier {multiplier}. Supported multipliers are {list(SUPPORTED_MULTIPLIERS)}"
        )

    if isinstance(seed, bool):
        raise TypeError(f"seed cannot be a boolean, got {seed!r}")
    if not isinstance(seed, (int, np.integer)):
        raise TypeError(f"seed must be an integer, got {type(seed).__name__}")
    if int(seed) not in FROZEN_WORKLOAD_SEEDS:
        raise ValueError(
            f"Unsupported seed {seed}. Approved frozen seeds are {list(FROZEN_WORKLOAD_SEEDS)}"
        )
    seed_int = int(seed)

    # 2. Validate input DataFrame without mutating it
    if not isinstance(workload_df, pd.DataFrame):
        raise TypeError(f"workload_df must be a pandas DataFrame, got {type(workload_df).__name__}")
    if workload_df.empty:
        raise ValueError("workload_df cannot be empty")

    # Inconsistent trace ID check
    trace_ids = workload_df["workload_trace_id"].unique()
    if len(trace_ids) != 1:
        raise ValueError(f"workload_df contains multiple or inconsistent workload_trace_ids: {trace_ids}")
    source_trace_id = str(trace_ids[0])

    # Validate seed column in workload_df
    if "seed" not in workload_df.columns:
        raise ValueError("workload_df missing required 'seed' column")

    seed_series = workload_df["seed"]
    if seed_series.isna().any():
        raise ValueError("workload_df contains null/missing seed values")

    # Check types of seeds (no booleans, only integers)
    unique_seeds = []
    for s_val in seed_series:
        if isinstance(s_val, bool):
            raise TypeError(f"workload_df seed column contains boolean value: {s_val!r}")
        if not isinstance(s_val, (int, np.integer)):
            raise TypeError(f"workload_df seed column contains non-integer value: {s_val!r}")
        s_int = int(s_val)
        if s_int not in unique_seeds:
            unique_seeds.append(s_int)

    if len(unique_seeds) != 1:
        raise ValueError(f"workload_df contains mixed seeds: {unique_seeds}")

    df_seed = unique_seeds[0]
    if df_seed != seed_int:
        raise ValueError(
            f"workload_df unique seed ({df_seed}) does not match function seed argument ({seed_int})"
        )

    # Determine expected window hours (default to 120 or inferred/passed)
    if expected_window_hours is None:
        # Check max deadline_offset_hours in input
        max_deadline = int(workload_df["deadline_offset_hours"].max()) if not workload_df.empty else 120
        expected_window_hours = max(120, max_deadline)

    # Validate against existing canonical workload validator
    validate_workload_dataframe(workload_df, expected_window_hours=expected_window_hours, expected_seed=seed_int)

    # 3. 1x multiplier: frame-equivalent copy, non-mutating
    if matched_multiplier == 1.0:
        res = workload_df.copy(deep=True)
        validate_workload_dataframe(res, expected_window_hours=expected_window_hours, expected_seed=seed_int)
        return res

    # 4. Multipliers 2.0 and 3.0: replicate demand deterministically
    replica_count = int(matched_multiplier)
    derived_trace_id = f"{source_trace_id}__x{replica_count}__seed{seed_int}"
    replicated_dfs: list[pd.DataFrame] = []

    # Original rows become replica 0 (or original)
    df_orig = workload_df.copy(deep=True)
    df_orig["workload_trace_id"] = derived_trace_id
    replicated_dfs.append(df_orig)

    # Generate replicas 1 .. replica_count - 1
    for r in range(1, replica_count):
        df_rep = workload_df.copy(deep=True)
        df_rep["workload_trace_id"] = derived_trace_id
        # Deterministic replica job IDs: e.g. f"{orig_id}_rep{r}"
        df_rep["job_id"] = df_rep["job_id"].astype(str).map(lambda jid: f"{jid}_rep{r}")
        replicated_dfs.append(df_rep)

    # Concatenate replicas
    scaled_df = pd.concat(replicated_dfs, ignore_index=True)

    # Stable deterministic row ordering: arrival_offset_hours, -priority, deadline_offset_hours, job_id
    scaled_df["priority_num"] = scaled_df["priority"].astype(int)
    scaled_df = scaled_df.sort_values(
        by=["arrival_offset_hours", "priority_num", "deadline_offset_hours", "job_id"],
        ascending=[True, False, True, True],
    ).drop(columns=["priority_num"]).reset_index(drop=True)

    # Reorder columns to match canonical schema exactly
    scaled_df = scaled_df[WORKLOAD_JOB_COLUMNS]

    # Verify exact processing requirement and energy ratios
    orig_proc = int(workload_df["processing_requirement"].sum())
    orig_energy = float(workload_df["energy_kwh"].sum())
    scaled_proc = int(scaled_df["processing_requirement"].sum())
    scaled_energy = float(scaled_df["energy_kwh"].sum())

    expected_proc = orig_proc * replica_count
    expected_energy = orig_energy * replica_count

    if scaled_proc != expected_proc:
        raise ValueError(
            f"Scaled processing total {scaled_proc} != expected {expected_proc} ({replica_count}x {orig_proc})"
        )
    if not math.isclose(scaled_energy, expected_energy, rel_tol=1e-7, abs_tol=1e-5):
        raise ValueError(
            f"Scaled energy total {scaled_energy} != expected {expected_energy} ({replica_count}x {orig_energy})"
        )

    # Validate output schema, uniqueness of job_ids, bounds
    validate_workload_dataframe(scaled_df, expected_window_hours=expected_window_hours, expected_seed=seed_int)

    return scaled_df
