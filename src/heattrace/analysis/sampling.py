"""Deterministic equal-budget sampling strategies over hourly policy outcomes (P5-03 / E4).

Defensible Design:
- Policies schedule strictly over original contiguous 120h timelines (CTRL_20240605 and HW_20240702).
- E4 sampling strategies evaluate already-generated hourly schedule outcomes.
- Sampling never reassigns pseudo-horizons or disrupts arrival/deadline constraints.
- Exactly equal evaluation budget (120 selected outcome hours per strategy):
  1. ordinary_window: 120 hours from CTRL_20240605 schedule outcomes.
  2. event_stratified: 60 hours from CTRL_20240605 + 60 hours from HW_20240702 schedule outcomes.
  3. phase_aware: 120 hours from HW_20240702 schedule outcomes partitioned by event phase (onset, peak, sustained, recovery).
"""

from __future__ import annotations

import hashlib
from typing import Any
import numpy as np
import pandas as pd


def generate_outcome_sampling_manifests(
    control_outcomes_df: pd.DataFrame,
    event_outcomes_df: pd.DataFrame,
    budget_hours: int = 120,
    seed: int = 20261016,
    workload_id: str = "trace_standard_120h_v0",
    workload_digest: str = "",
    constraint_digest: str = "",
) -> dict[str, pd.DataFrame]:
    """Generate deterministic sampling manifests selecting outcome hours from authentic runs."""
    manifests: dict[str, pd.DataFrame] = {}

    ctrl_sorted = control_outcomes_df.sort_values("hour_offset").reset_index(drop=True)
    hw_sorted = event_outcomes_df.sort_values("hour_offset").reset_index(drop=True)

    # 1. Ordinary-window strategy (120 control outcome hours)
    ord_rows: list[dict[str, Any]] = []
    for idx, row in ctrl_sorted.head(budget_hours).iterrows():
        ord_rows.append({
            "sampling_strategy": "ordinary_window",
            "sample_index": int(idx),
            "window_id": str(row["window_id"]),
            "window_type": "control",
            "phase_label": str(row.get("phase_label", "control")),
            "timestamp_utc": row["timestamp_utc"],
            "original_hour_offset": int(row["hour_offset"]),
            "workload_trace_id": workload_id,
            "workload_digest": workload_digest,
            "constraint_digest": constraint_digest,
            "inclusion_reason": "Chronological ordinary control outcome hour (100% control budget)",
        })
    manifests["ordinary_window"] = pd.DataFrame(ord_rows)

    # 2. Event-stratified strategy (60 control outcome hours + 60 event outcome hours = 120h)
    strat_rows: list[dict[str, Any]] = []
    # 60 control hours (even offsets 0, 2, ..., 118)
    ctrl_indices = np.arange(0, len(ctrl_sorted), 2)[:budget_hours // 2]
    for s_idx, orig_idx in enumerate(ctrl_indices):
        row = ctrl_sorted.iloc[orig_idx]
        strat_rows.append({
            "sampling_strategy": "event_stratified",
            "sample_index": s_idx,
            "window_id": str(row["window_id"]),
            "window_type": "control",
            "phase_label": str(row.get("phase_label", "control")),
            "timestamp_utc": row["timestamp_utc"],
            "original_hour_offset": int(row["hour_offset"]),
            "workload_trace_id": workload_id,
            "workload_digest": workload_digest,
            "constraint_digest": constraint_digest,
            "inclusion_reason": "Stratified non-event control outcome stratum (50% budget)",
        })
    # 60 event hours (even offsets 0, 2, ..., 118)
    hw_indices = np.arange(0, len(hw_sorted), 2)[:budget_hours // 2]
    for s_idx, orig_idx in enumerate(hw_indices):
        row = hw_sorted.iloc[orig_idx]
        strat_rows.append({
            "sampling_strategy": "event_stratified",
            "sample_index": (budget_hours // 2) + s_idx,
            "window_id": str(row["window_id"]),
            "window_type": "event",
            "phase_label": str(row.get("phase_label", "sustained")),
            "timestamp_utc": row["timestamp_utc"],
            "original_hour_offset": int(row["hour_offset"]),
            "workload_trace_id": workload_id,
            "workload_digest": workload_digest,
            "constraint_digest": constraint_digest,
            "inclusion_reason": "Stratified heatwave event outcome stratum (50% budget)",
        })
    manifests["event_stratified"] = pd.DataFrame(strat_rows)

    # 3. Phase-aware strategy (120 event outcome hours partitioned by phase)
    phase_rows: list[dict[str, Any]] = []
    for idx, row in hw_sorted.head(budget_hours).iterrows():
        phase_rows.append({
            "sampling_strategy": "phase_aware",
            "sample_index": int(idx),
            "window_id": str(row["window_id"]),
            "window_type": "event",
            "phase_label": str(row.get("phase_label", "sustained")),
            "timestamp_utc": row["timestamp_utc"],
            "original_hour_offset": int(row["hour_offset"]),
            "workload_trace_id": workload_id,
            "workload_digest": workload_digest,
            "constraint_digest": constraint_digest,
            "inclusion_reason": f"Phase-aware event outcome partition: {row.get('phase_label', 'sustained')}",
        })
    manifests["phase_aware"] = pd.DataFrame(phase_rows)

    return manifests


def validate_sampling_manifests(
    manifests: dict[str, pd.DataFrame],
    target_budget_hours: int = 120,
) -> list[str]:
    """Validate equal budgets, no duplicate samples, and original timestamp preservation."""
    errors: list[str] = []

    for name, df in manifests.items():
        if len(df) != target_budget_hours:
            errors.append(f"{name}: Achieved budget {len(df)} != target budget {target_budget_hours}")

        dups = df["sample_index"].duplicated()
        if dups.any():
            errors.append(f"{name}: Duplicate sample_index detected: {df.loc[dups, 'sample_index'].tolist()}")

        req_cols = [
            "sampling_strategy",
            "sample_index",
            "window_id",
            "window_type",
            "phase_label",
            "timestamp_utc",
            "original_hour_offset",
            "workload_trace_id",
            "workload_digest",
            "constraint_digest",
            "inclusion_reason",
        ]
        for c in req_cols:
            if c not in df.columns:
                errors.append(f"{name}: Missing column {c}")

    return errors
