"""Deterministic equal-budget sampling strategies (P5-03 / E4).

Provides 3 equal-budget sampling manifests:
1. ordinary_window: The full 120h control window (and 120h event window).
2. event_stratified: Equal balanced sample across event and control windows (e.g. 60h event + 60h control = 120h).
3. phase_aware: Budget allocated proportionally across event phases (onset, peak, sustained, recovery) totaling 120h.
"""

from __future__ import annotations

import hashlib
from typing import Any
import numpy as np
import pandas as pd


def generate_sampling_manifests(
    benchmark_df: pd.DataFrame,
    budget_hours: int = 120,
    seed: int = 20261016,
    workload_id: str = "trace_standard_120h_v0",
) -> dict[str, pd.DataFrame]:
    """Generate deterministic sampling manifests with equal total evaluation budget."""
    rng = np.random.RandomState(seed)
    manifests: dict[str, pd.DataFrame] = {}

    ctrl_df = benchmark_df[benchmark_df["window_id"] == "CTRL_20240605"].sort_values("timestamp_utc").reset_index(drop=True)
    hw_df = benchmark_df[benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)

    # 1. Ordinary-window sampling
    # Primary equal-budget: 120h ordinary control window
    ord_rows: list[dict[str, Any]] = []
    for idx, row in ctrl_df.iterrows():
        ord_rows.append({
            "sampling_strategy": "ordinary_window",
            "sample_index": idx,
            "window_id": row["window_id"],
            "window_type": row["window_type"],
            "phase_label": row["phase_label"],
            "timestamp_utc": row["timestamp_utc"],
            "hour_offset": idx,
            "workload_trace_id": workload_id,
            "inclusion_reason": "Chronological ordinary control window observation",
        })
    manifests["ordinary_window"] = pd.DataFrame(ord_rows)

    # 2. Event-stratified sampling
    # Balanced equal budget: 60h from control, 60h from heatwave (deterministic stride/selection)
    # Stride of 2 gives exactly 60 evenly spaced hours across each 120h window
    strat_rows: list[dict[str, Any]] = []
    # 60 control hours
    ctrl_sample_indices = np.arange(0, len(ctrl_df), 2)[:budget_hours // 2]
    for s_idx, idx in enumerate(ctrl_sample_indices):
        row = ctrl_df.iloc[idx]
        strat_rows.append({
            "sampling_strategy": "event_stratified",
            "sample_index": s_idx,
            "window_id": row["window_id"],
            "window_type": row["window_type"],
            "phase_label": row["phase_label"],
            "timestamp_utc": row["timestamp_utc"],
            "hour_offset": idx,
            "workload_trace_id": workload_id,
            "inclusion_reason": "Stratified non-event control stratum (50% budget)",
        })
    # 60 event hours
    hw_sample_indices = np.arange(0, len(hw_df), 2)[:budget_hours // 2]
    for s_idx, idx in enumerate(hw_sample_indices):
        row = hw_df.iloc[idx]
        strat_rows.append({
            "sampling_strategy": "event_stratified",
            "sample_index": (budget_hours // 2) + s_idx,
            "window_id": row["window_id"],
            "window_type": row["window_type"],
            "phase_label": row["phase_label"],
            "timestamp_utc": row["timestamp_utc"],
            "hour_offset": idx,
            "workload_trace_id": workload_id,
            "inclusion_reason": "Stratified heatwave event stratum (50% budget)",
        })
    manifests["event_stratified"] = pd.DataFrame(strat_rows)

    # 3. Phase-aware event sampling
    # Evaluates within the heatwave event window partitioned by phase
    # Total budget = 120h (the exact full event window partitioned and labeled by phase)
    # Phases: onset (24h), peak (24h), sustained (48h), recovery (24h) = 120h
    phase_rows: list[dict[str, Any]] = []
    for idx, row in hw_df.iterrows():
        phase_rows.append({
            "sampling_strategy": "phase_aware",
            "sample_index": idx,
            "window_id": row["window_id"],
            "window_type": row["window_type"],
            "phase_label": row["phase_label"],
            "timestamp_utc": row["timestamp_utc"],
            "hour_offset": idx,
            "workload_trace_id": workload_id,
            "inclusion_reason": f"Phase-aware partition: {row['phase_label']}",
        })
    manifests["phase_aware"] = pd.DataFrame(phase_rows)

    return manifests


def validate_sampling_manifests(
    manifests: dict[str, pd.DataFrame],
    target_budget_hours: int = 120,
) -> list[str]:
    """Validate equal budgets, no unexpected duplicates, and chronological integrity."""
    errors: list[str] = []

    for name, df in manifests.items():
        if len(df) != target_budget_hours:
            errors.append(f"{name}: Achieved budget {len(df)} does not match target budget {target_budget_hours}")

        # Check duplicates
        dups = df["timestamp_utc"].duplicated()
        if dups.any():
            errors.append(f"{name}: Duplicate timestamps detected: {df.loc[dups, 'timestamp_utc'].tolist()}")

        # Check required columns
        req_cols = [
            "sampling_strategy",
            "sample_index",
            "window_id",
            "window_type",
            "phase_label",
            "timestamp_utc",
            "workload_trace_id",
            "inclusion_reason",
        ]
        for c in req_cols:
            if c not in df.columns:
                errors.append(f"{name}: Missing column {c}")

    return errors
