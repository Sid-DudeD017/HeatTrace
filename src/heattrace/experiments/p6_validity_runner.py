"""Phase 6 validity experiment runner and execution engine.

Strictly runs development-only pilot (TRIPLET_DEV_ae821c) across 252 unique pilot cells:
- Cohort A: Core heatwave/control benchmark (144 cells)
- Cohort B: Event-blind benchmark (72 cells)
- Cohort C: Algorithm additions: fixed-margin + HeatGuard (24 cells)
- Cohort D: Oracle reference policy (12 cells)
Total: 252 cells.

All deployable policies execute under the identical 24-hour horizon, 1-hour commitment
rolling replan causal boundary. Confirmatory triplets are strictly filtered at read-time
using pyarrow parquet filters before entering runner memory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from heattrace.forecast.dataset import (
    ScalerMetadata,
    load_noaa_hourly_series,
)
from heattrace.forecast.historical import HistoricalPersistenceForecastProvider
from heattrace.forecast.train_temperature import load_verified_checkpoint, predict_unscaled
from heattrace.ingest.provenance import sha256_file
from heattrace.policy.interfaces import (
    ForecastPoint,
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
)
from heattrace.thermal.facility import (
    FacilityConfig,
    build_forecast_facility_state,
    build_realized_facility_state,
    get_preset_thermal_scenario,
)
from heattrace.thermal.heatguard import (
    HeatGuardMarginMode,
    HeatGuardScheduler,
)
from heattrace.thermal.metrics import score_thermal_schedule
from heattrace.thermal.policies import (
    CapacityAwarePolicy,
    FullThermalAwarePolicy,
    OracleFullThermalAwarePolicy,
    StaticUnawarePolicy,
)
from heattrace.thermal.validation import load_p6_validity_config, validate_p6_validity_config
from heattrace.workload.generator import generate_deterministic_workload
from heattrace.workload.scaling import scale_workload

FROZEN_P4_MANIFEST_HASH = "ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79"
FROZEN_P4_CHECKPOINT_HASH = "69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed"
FROZEN_CALIBRATION_MANIFEST_HASH = "bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c"

DEV_TRIPLET_ID = "TRIPLET_DEV_ae821c"
DEV_WINDOWS = {
    "heatwave": "HW_20240702",
    "control": "CTRL_20240605",
    "event_blind": "BLIND_ef75b17921d7",
}

EXPECTED_PILOT_SCHEMA_COLUMNS = [
    "run_id",
    "triplet_id",
    "context",
    "window_id",
    "cohort",
    "facility_model",
    "thermal_curve",
    "workload_multiplier",
    "seed",
    "workload_trace_id",
    "objective",
    "policy_id",
    "policy_version",
    "deployable",
    "margin_mode",
    "applied_margin",
    "status",
    "error_class",
    "error_message",
    "runtime_seconds",
    "demanded_processing_slots",
    "demanded_energy_kwh",
    "completed_processing_slots",
    "completed_energy_kwh",
    "unfinished_processing_slots",
    "unmet_deadlines_count",
    "allocation_count",
    "facility_power_violation_hours",
    "total_facility_power_excess_kwh",
    "maximum_facility_power_excess_kw",
    "realized_facility_energy_kwh",
    "cooling_adjusted_cost_usd",
    "cooling_adjusted_carbon_kg",
    "scheduler_feasible",
    "thermally_feasible",
    "p6_config_sha256",
    "p6_thermal_config_sha256",
    "development_benchmark_sha256",
    "workload_sha256",
    "forecast_metrics_source_sha256",
    "p4_manifest_sha256",
    "p4_checkpoint_sha256",
    "calibration_manifest_sha256",
]


def _is_valid_sha256(val: Any) -> bool:
    """Validate that val is a 64-character lowercase hexadecimal SHA-256 string."""
    if not isinstance(val, str) or len(val) != 64:
        return False
    return all(c in "0123456789abcdef" for c in val.lower())


def _validate_exact_string_key(col_name: str, val: Any, expected: str, run_id: str) -> None:
    """Validate that a categorical/string scientific key is strictly a non-null string equal to expected."""
    if isinstance(val, bool) or not isinstance(val, str):
        raise ValueError(
            f"Scientific key type violation for {run_id}: '{col_name}' must be a string, got {type(val).__name__} ({val!r})"
        )
    if val != expected:
        raise ValueError(
            f"Scientific key mismatch for {run_id}: '{col_name}' '{val}' != '{expected}'"
        )


def _validate_exact_workload_multiplier(val: Any, expected: float, run_id: str) -> None:
    """Validate workload_multiplier is a finite numeric value strictly equal to expected."""
    if isinstance(val, bool) or not isinstance(val, (int, float, np.integer, np.floating)):
        raise ValueError(
            f"Scientific key type violation for {run_id}: 'workload_multiplier' must be numeric, got {type(val).__name__} ({val!r})"
        )
    val_float = float(val)
    if math.isnan(val_float) or math.isinf(val_float):
        raise ValueError(
            f"Scientific key non-finite violation for {run_id}: 'workload_multiplier' is {val!r}"
        )
    if val_float != float(expected):
        raise ValueError(
            f"Scientific key mismatch for {run_id}: 'workload_multiplier' {val_float} != {expected}"
        )


def _validate_exact_seed(val: Any, expected: int, run_id: str) -> None:
    """Validate seed is strictly an integer/numpy integer strictly equal to expected."""
    if isinstance(val, bool) or not isinstance(val, (int, np.integer)):
        raise ValueError(
            f"Scientific key type violation for {run_id}: 'seed' must be an integer, got {type(val).__name__} ({val!r})"
        )
    if int(val) != int(expected):
        raise ValueError(
            f"Scientific key mismatch for {run_id}: 'seed' {int(val)} != {expected}"
        )


def _validate_exact_deployable(val: Any, expected: bool, run_id: str) -> None:
    """Validate deployable is strictly a Python bool or NumPy bool_ strictly equal to expected."""
    if not isinstance(val, (bool, np.bool_)):
        raise ValueError(
            f"Scientific key type violation for {run_id}: 'deployable' must be a boolean, got {type(val).__name__} ({val!r})"
        )
    if bool(val) != bool(expected):
        raise ValueError(
            f"Scientific key mismatch for {run_id}: 'deployable' {bool(val)} != {expected}"
        )


def validate_existing_pilot_parquet(
    parquet_path: Path,
    expected_specs: dict[str, PilotCellSpec],
    provenance_hashes: dict[str, str],
    workload_cache: dict[tuple[int, float], pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    """Fail-closed validation of existing pilot parquet file for safe resume.

    Validates:
      1. Schema integrity: exactly the 43 expected columns.
      2. No duplicate run_id values.
      3. For every row, run_id belongs to the expected enumerated pilot specs.
      4. Complete scientific key identity matches the enumerated spec with strict type checks:
         triplet_id, context, window_id, cohort, facility_model, thermal_curve,
         workload_multiplier, seed, objective, policy_id, policy_version,
         deployable, and margin_mode.
      5. workload_trace_id matches the cached workload for that (seed, workload_multiplier).
      6. All 8 provenance hashes are valid 64-char hex strings and match freshly computed values.
      7. Status is either SUCCESS or FAILED.

    Returns:
      A dictionary mapping run_id -> row_dict for successful runs that can be safely reused.
    """
    df = pd.read_parquet(parquet_path)

    # 1. Require complete expected schema
    actual_cols = list(df.columns)
    if actual_cols != EXPECTED_PILOT_SCHEMA_COLUMNS:
        missing = set(EXPECTED_PILOT_SCHEMA_COLUMNS) - set(actual_cols)
        extra = set(actual_cols) - set(EXPECTED_PILOT_SCHEMA_COLUMNS)
        raise ValueError(
            f"Pilot parquet schema mismatch. Missing columns: {sorted(missing)}; Extra columns: {sorted(extra)}"
        )

    # 2. Check run_id uniqueness
    if df["run_id"].duplicated().any():
        dups = df["run_id"][df["run_id"].duplicated()].unique().tolist()
        raise ValueError(f"Existing parquet contains duplicate run_id values: {dups}")

    successful_rows: dict[str, dict[str, Any]] = {}

    for _, r in df.iterrows():
        r_dict = r.to_dict()
        rid = r_dict.get("run_id")
        if not isinstance(rid, str) or not rid:
            raise ValueError(f"Existing parquet contains null or non-string run_id: {rid}")

        if rid not in expected_specs:
            raise ValueError(f"Existing parquet contains unknown run_id: '{rid}'")

        spec = expected_specs[rid]

        # 4. Compare row with its enumerated PilotCellSpec across complete scientific identity using strict types
        expected_margin_mode = spec.margin_mode or "none"
        _validate_exact_string_key("triplet_id", r_dict.get("triplet_id"), spec.triplet_id, rid)
        _validate_exact_string_key("context", r_dict.get("context"), spec.context, rid)
        _validate_exact_string_key("window_id", r_dict.get("window_id"), spec.window_id, rid)
        _validate_exact_string_key("cohort", r_dict.get("cohort"), spec.cohort, rid)
        _validate_exact_string_key("facility_model", r_dict.get("facility_model"), spec.facility_model, rid)
        _validate_exact_string_key("thermal_curve", r_dict.get("thermal_curve"), spec.thermal_curve, rid)
        _validate_exact_workload_multiplier(r_dict.get("workload_multiplier"), spec.workload_multiplier, rid)
        _validate_exact_seed(r_dict.get("seed"), spec.seed, rid)
        _validate_exact_string_key("objective", r_dict.get("objective"), spec.objective, rid)
        _validate_exact_string_key("policy_id", r_dict.get("policy_id"), spec.policy_id, rid)
        _validate_exact_string_key("policy_version", r_dict.get("policy_version"), str(spec.policy_version), rid)
        _validate_exact_deployable(r_dict.get("deployable"), spec.deployable, rid)
        _validate_exact_string_key("margin_mode", r_dict.get("margin_mode"), expected_margin_mode, rid)

        # 5. Validate workload_trace_id against cached workload
        expected_wl = workload_cache.get((spec.seed, spec.workload_multiplier))
        if expected_wl is None:
            raise ValueError(f"Workload cache missing entry for seed={spec.seed}, multiplier={spec.workload_multiplier}")
        expected_trace_id = str(expected_wl["workload_trace_id"].iloc[0])
        _validate_exact_string_key("workload_trace_id", r_dict.get("workload_trace_id"), expected_trace_id, rid)

        # 6. Validate all 8 provenance fields against freshly computed expected values
        expected_wl_hash = provenance_hashes[f"workload_sha256_{spec.seed}_{spec.workload_multiplier}"]
        provenance_checks = [
            ("p6_config_sha256", provenance_hashes["p6_config_sha256"]),
            ("p6_thermal_config_sha256", provenance_hashes["p6_thermal_config_sha256"]),
            ("development_benchmark_sha256", provenance_hashes["development_benchmark_sha256"]),
            ("workload_sha256", expected_wl_hash),
            ("forecast_metrics_source_sha256", provenance_hashes["forecast_metrics_source_sha256"]),
            ("p4_manifest_sha256", provenance_hashes["p4_manifest_sha256"]),
            ("p4_checkpoint_sha256", provenance_hashes["p4_checkpoint_sha256"]),
            ("calibration_manifest_sha256", provenance_hashes["calibration_manifest_sha256"]),
        ]

        for prov_col, expected_val in provenance_checks:
            actual_val = r_dict.get(prov_col)
            if not _is_valid_sha256(actual_val):
                raise ValueError(
                    f"Malformed or non-hex SHA-256 for column '{prov_col}' in row {rid}: '{actual_val}'"
                )
            if actual_val != expected_val:
                raise ValueError(
                    f"Provenance hash mismatch for column '{prov_col}' in row {rid}: '{actual_val}' != '{expected_val}'"
                )

        status = r_dict.get("status")
        if status not in ("SUCCESS", "FAILED"):
            raise ValueError(f"Invalid status '{status}' in row {rid}")

        if status == "SUCCESS":
            successful_rows[rid] = r_dict

    return successful_rows


def compute_canonical_df_sha256(df: pd.DataFrame) -> str:
    """Compute deterministic SHA-256 digest of a DataFrame independent of row index."""
    df_sorted = df.reindex(sorted(df.columns), axis=1)
    csv_bytes = df_sorted.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(csv_bytes).hexdigest()


@dataclass(frozen=True)
class PilotCellSpec:
    triplet_id: str
    context: str
    window_id: str
    cohort: str
    facility_model: str
    thermal_curve: str
    workload_multiplier: float
    seed: int
    objective: str
    policy_id: str
    policy_version: str
    deployable: bool
    margin_mode: str | None
    fixed_margin: float | None

    @property
    def canonical_key(self) -> str:
        return (
            f"{self.triplet_id}__"
            f"{self.context}__"
            f"{self.window_id}__"
            f"{self.cohort}__"
            f"{self.facility_model}__"
            f"{self.thermal_curve}__"
            f"wl_{self.workload_multiplier:.1f}x__"
            f"seed_{self.seed}__"
            f"{self.objective}__"
            f"{self.policy_id}__"
            f"v{self.policy_version}__"
            f"deployable_{str(self.deployable).lower()}"
        )

    @property
    def run_id(self) -> str:
        h = hashlib.sha256(self.canonical_key.encode("utf-8")).hexdigest()[:16]
        return f"p6_pilot_{self.cohort}_{self.context}_{self.policy_id}_{h}"


def enumerate_p6_pilot_matrix(triplet_id: str = DEV_TRIPLET_ID) -> list[PilotCellSpec]:
    """Deterministically enumerate the exact 252 development pilot cells.

    Rejects any non-development triplet before enumeration.
    """
    if triplet_id != DEV_TRIPLET_ID:
        raise ValueError(
            f"Pilot execution rejected: '{triplet_id}' is not the authorized development triplet ('{DEV_TRIPLET_ID}')."
        )

    specs: list[PilotCellSpec] = []

    facility_models = ["energy_only", "power_capped"]
    thermal_curves = ["low", "medium"]
    workload_multipliers = [1.0, 2.0, 3.0]
    seeds = [20261016, 20261017]
    primary_objective = "carbon_first"

    # Cohort A: Core heatwave/control benchmark (144 cells)
    core_contexts = [("heatwave", DEV_WINDOWS["heatwave"]), ("control", DEV_WINDOWS["control"])]
    core_policies = [
        ("static_unaware", "1.0", True),
        ("capacity_aware", "1.0", True),
        ("full_thermal_aware", "1.0", True),
    ]

    for ctx, win_id in core_contexts:
        for fm in facility_models:
            for tc in thermal_curves:
                for mult in workload_multipliers:
                    for seed in seeds:
                        for pol_id, pol_v, dep in core_policies:
                            specs.append(
                                PilotCellSpec(
                                    triplet_id=triplet_id,
                                    context=ctx,
                                    window_id=win_id,
                                    cohort="core_benchmark",
                                    facility_model=fm,
                                    thermal_curve=tc,
                                    workload_multiplier=mult,
                                    seed=seed,
                                    objective=primary_objective,
                                    policy_id=pol_id,
                                    policy_version=pol_v,
                                    deployable=dep,
                                    margin_mode=None,
                                    fixed_margin=None,
                                )
                            )

    # Cohort B: Event-blind benchmark (72 cells)
    blind_context = ("event_blind", DEV_WINDOWS["event_blind"])
    for fm in facility_models:
        for tc in thermal_curves:
            for mult in workload_multipliers:
                for seed in seeds:
                    for pol_id, pol_v, dep in core_policies:
                        specs.append(
                            PilotCellSpec(
                                triplet_id=triplet_id,
                                context=blind_context[0],
                                window_id=blind_context[1],
                                cohort="event_blind_benchmark",
                                facility_model=fm,
                                thermal_curve=tc,
                                workload_multiplier=mult,
                                seed=seed,
                                objective=primary_objective,
                                policy_id=pol_id,
                                policy_version=pol_v,
                                deployable=dep,
                                margin_mode=None,
                                fixed_margin=None,
                            )
                        )

    # Cohort C: Algorithm additions: fixed-margin + HeatGuard (24 cells)
    algo_policies = [
        ("heatguard_calibrated", "1.0", True, "calibrated", None),
        ("heatguard_fixed", "1.0", True, "fixed", 0.10),
    ]
    for ctx, win_id in core_contexts:
        for mult in workload_multipliers:
            for seed in seeds:
                for pol_id, pol_v, dep, mm, fm_val in algo_policies:
                    specs.append(
                        PilotCellSpec(
                            triplet_id=triplet_id,
                            context=ctx,
                            window_id=win_id,
                            cohort="algorithm_comparators",
                            facility_model="power_capped",
                            thermal_curve="medium",
                            workload_multiplier=mult,
                            seed=seed,
                            objective=primary_objective,
                            policy_id=pol_id,
                            policy_version=pol_v,
                            deployable=dep,
                            margin_mode=mm,
                            fixed_margin=fm_val,
                        )
                    )

    # Cohort D: Oracle reference (12 cells)
    for ctx, win_id in core_contexts:
        for mult in workload_multipliers:
            for seed in seeds:
                specs.append(
                    PilotCellSpec(
                        triplet_id=triplet_id,
                        context=ctx,
                        window_id=win_id,
                        cohort="oracle_reference",
                        facility_model="power_capped",
                        thermal_curve="medium",
                        workload_multiplier=mult,
                        seed=seed,
                        objective=primary_objective,
                        policy_id="oracle_full_thermal_aware",
                        policy_version="1.0",
                        deployable=False,
                        margin_mode=None,
                        fixed_margin=None,
                    )
                )

    return specs


@dataclass(frozen=True)
class ConfirmatoryCellSpec:
    triplet_id: str
    context: str
    window_id: str
    cohort: str
    facility_model: str
    thermal_curve: str
    workload_multiplier: float
    seed: int
    objective: str
    policy_id: str
    policy_version: str
    deployable: bool
    margin_mode: str | None
    fixed_margin: float | None

    @property
    def canonical_key(self) -> str:
        return (
            f"{self.triplet_id}__"
            f"{self.context}__"
            f"{self.window_id}__"
            f"{self.cohort}__"
            f"{self.facility_model}__"
            f"{self.thermal_curve}__"
            f"wl_{self.workload_multiplier:.1f}x__"
            f"seed_{self.seed}__"
            f"{self.objective}__"
            f"{self.policy_id}__"
            f"v{self.policy_version}__"
            f"deployable_{str(self.deployable).lower()}"
        )

    @property
    def run_id(self) -> str:
        h = hashlib.sha256(self.canonical_key.encode("utf-8")).hexdigest()[:16]
        return f"p7_conf_{self.cohort}_{self.context}_{self.policy_id}_{h}"


def enumerate_p7_confirmatory_matrix(
    p6_validity_yaml_path: Path | str = "configs/p6_validity.yaml",
) -> list[ConfirmatoryCellSpec]:
    """Deterministically enumerate the exact 756 confirmatory evaluation cells from validated config.

    Guarantees:
    - Derives identities from validated frozen configuration only.
    - Exactly 756 unique stable run IDs.
    - Zero cells belonging to development triplet or development windows.
    - Exactly 432 event/control core cells (Cohort A).
    - Exactly 216 event-blind core cells (Cohort B).
    - Exactly 72 algorithm comparator cells (Cohort C).
    - Exactly 36 non-deployable oracle reference cells (Cohort D).
    - Strictly carbon_first objective.
    - Zero execution and zero reading of confirmatory parquet rows or outcome data.
    """
    path = Path(p6_validity_yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file missing: {path}")

    cfg = load_p6_validity_config(path)
    val_status = validate_p6_validity_config(cfg)
    if not val_status.get("valid") or not val_status.get("is_frozen") or val_status.get("has_placeholders"):
        raise ValueError(f"p6_validity.yaml failed validation: {val_status}")

    triplets_cfg = cfg.get("triplets", {})
    conf_triplets = triplets_cfg.get("confirmatory", [])
    if len(conf_triplets) != 3:
        raise ValueError(f"Expected exactly 3 confirmatory triplets in config, found {len(conf_triplets)}")

    dims = cfg.get("dimensions", {})
    facility_models = dims.get("facility_models", ["energy_only", "power_capped"])
    thermal_curves = dims.get("thermal_curves", ["low", "medium"])
    workload_multipliers = dims.get("workload_multipliers", [1.0, 2.0, 3.0])
    seeds = dims.get("seeds", [20261016, 20261017])
    primary_objective = "carbon_first"

    # Strict dimensional checks
    if set(facility_models) != {"energy_only", "power_capped"}:
        raise ValueError(f"Invalid facility models for confirmatory matrix: {facility_models}")
    if set(thermal_curves) != {"low", "medium"}:
        raise ValueError(f"Invalid thermal curves for confirmatory matrix: {thermal_curves}")
    if sorted(workload_multipliers) != [1.0, 2.0, 3.0]:
        raise ValueError(f"Invalid workload multipliers for confirmatory matrix: {workload_multipliers}")
    if sorted(seeds) != [20261016, 20261017]:
        raise ValueError(f"Invalid seeds for confirmatory matrix: {seeds}")

    core_policies = [
        ("static_unaware", "1.0", True),
        ("capacity_aware", "1.0", True),
        ("full_thermal_aware", "1.0", True),
    ]

    specs: list[ConfirmatoryCellSpec] = []

    # Sort triplets by pair_id to guarantee order-invariance to YAML key/list reordering
    sorted_conf_triplets = sorted(conf_triplets, key=lambda t: str(t["pair_id"]))

    for t in sorted_conf_triplets:
        pair_id = str(t["pair_id"])
        hw_id = str(t["heatwave_window_id"])
        ctrl_id = str(t["matched_control_window_id"])
        blind_id = str(t["event_blind_window_id"])

        if pair_id == DEV_TRIPLET_ID or hw_id == DEV_WINDOWS["heatwave"] or ctrl_id == DEV_WINDOWS["control"] or blind_id == DEV_WINDOWS["event_blind"]:
            raise ValueError(f"Development identity leaked into confirmatory triplet specification: {t}")

        # Cohort A: Event/control core cells (3 pairs * 2 contexts * 2 facilities * 2 curves * 3 workloads * 2 seeds * 1 obj * 3 policies = 432)
        pair_contexts = [("heatwave", hw_id), ("control", ctrl_id)]
        for ctx, wid in pair_contexts:
            for fm in ["energy_only", "power_capped"]:
                for tc in ["low", "medium"]:
                    for mult in [1.0, 2.0, 3.0]:
                        for seed in [20261016, 20261017]:
                            for pol_id, pol_v, dep in core_policies:
                                specs.append(
                                    ConfirmatoryCellSpec(
                                        triplet_id=pair_id,
                                        context=ctx,
                                        window_id=wid,
                                        cohort="core_benchmark",
                                        facility_model=fm,
                                        thermal_curve=tc,
                                        workload_multiplier=mult,
                                        seed=seed,
                                        objective=primary_objective,
                                        policy_id=pol_id,
                                        policy_version=pol_v,
                                        deployable=dep,
                                        margin_mode=None,
                                        fixed_margin=None,
                                    )
                                )

        # Cohort B: Event-blind core cells (3 blind * 2 facilities * 2 curves * 3 workloads * 2 seeds * 1 obj * 3 policies = 216)
        for fm in ["energy_only", "power_capped"]:
            for tc in ["low", "medium"]:
                for mult in [1.0, 2.0, 3.0]:
                    for seed in [20261016, 20261017]:
                        for pol_id, pol_v, dep in core_policies:
                            specs.append(
                                ConfirmatoryCellSpec(
                                    triplet_id=pair_id,
                                    context="event_blind",
                                    window_id=blind_id,
                                    cohort="event_blind_benchmark",
                                    facility_model=fm,
                                    thermal_curve=tc,
                                    workload_multiplier=mult,
                                    seed=seed,
                                    objective=primary_objective,
                                    policy_id=pol_id,
                                    policy_version=pol_v,
                                    deployable=dep,
                                    margin_mode=None,
                                    fixed_margin=None,
                                )
                            )

        # Cohort C: Algorithm comparators (3 pairs * 2 contexts * 3 workloads * 2 seeds * 2 policies = 72)
        algo_policies = [
            ("heatguard_calibrated", "1.0", True, "calibrated", None),
            ("heatguard_fixed", "1.0", True, "fixed", 0.10),
        ]
        for ctx, wid in pair_contexts:
            for mult in [1.0, 2.0, 3.0]:
                for seed in [20261016, 20261017]:
                    for pol_id, pol_v, dep, mm, fm_val in algo_policies:
                        specs.append(
                            ConfirmatoryCellSpec(
                                triplet_id=pair_id,
                                context=ctx,
                                window_id=wid,
                                cohort="algorithm_comparators",
                                facility_model="power_capped",
                                thermal_curve="medium",
                                workload_multiplier=mult,
                                seed=seed,
                                objective=primary_objective,
                                policy_id=pol_id,
                                policy_version=pol_v,
                                deployable=dep,
                                margin_mode=mm,
                                fixed_margin=fm_val,
                            )
                        )

        # Cohort D: Oracle reference (3 pairs * 2 contexts * 3 workloads * 2 seeds * 1 oracle = 36)
        for ctx, wid in pair_contexts:
            for mult in [1.0, 2.0, 3.0]:
                for seed in [20261016, 20261017]:
                    specs.append(
                        ConfirmatoryCellSpec(
                            triplet_id=pair_id,
                            context=ctx,
                            window_id=wid,
                            cohort="oracle_reference",
                            facility_model="power_capped",
                            thermal_curve="medium",
                            workload_multiplier=mult,
                            seed=seed,
                            objective=primary_objective,
                            policy_id="oracle_full_thermal_aware",
                            policy_version="1.0",
                            deployable=False,
                            margin_mode=None,
                            fixed_margin=None,
                        )
                    )

    # Fail closed verification of exact counts and uniqueness
    if len(specs) != 756:
        raise ValueError(f"Confirmatory matrix enumeration count {len(specs)} != 756")

    run_ids = [s.run_id for s in specs]
    if len(set(run_ids)) != 756:
        raise ValueError(f"Duplicate run IDs detected in confirmatory matrix ({len(set(run_ids))} unique of 756)")

    canonical_keys = [s.canonical_key for s in specs]
    if len(set(canonical_keys)) != 756:
        raise ValueError(f"Duplicate canonical scientific keys detected in confirmatory matrix ({len(set(canonical_keys))} unique of 756)")

    # Assert no dev triplets or windows
    for s in specs:
        if s.triplet_id == DEV_TRIPLET_ID or DEV_TRIPLET_ID in s.canonical_key:
            raise ValueError(f"Development triplet leaked into confirmatory cell: {s.run_id}")
        if s.window_id in DEV_WINDOWS.values():
            raise ValueError(f"Development window leaked into confirmatory cell: {s.run_id}")
        if s.objective != "carbon_first":
            raise ValueError(f"Non-carbon_first objective '{s.objective}' in confirmatory cell: {s.run_id}")
        if s.cohort == "oracle_reference" and s.deployable is not False:
            raise ValueError(f"Oracle cell marked deployable: {s.run_id}")

    return specs


def run_p7_confirmatory_dry_run(
    repo_root: Path | str = ".",
    output_manifest_path: Path | str = "data/manifests/p7_confirmatory_dry_run_manifest.json",
    git_commit: str = "PENDING_COMMIT",
) -> dict[str, Any]:
    """Execute sealed, non-executing confirmatory dry run and generate provenance manifest.

    Guarantees:
    - Strictly non-executing (no scheduling simulation is run).
    - Confirmatory parquet rows and outcome tables are never read.
    - Verified against disk hashes of configs, protocol, and frozen models.
    - Verifies exact 756 count and cohort breakdown.
    - Writes data/manifests/p7_confirmatory_dry_run_manifest.json with zero outcome data.
    """
    root = Path(repo_root)
    validity_cfg_path = root / "configs" / "p6_validity.yaml"
    thermal_cfg_path = root / "configs" / "p6_thermal.yaml"
    protocol_path = root / "docs" / "p6_frozen_protocol.md"

    # 1. Verify frozen artifact hashes
    verified_hashes = verify_frozen_hashes(root)

    # 2. Verify configs
    cfg, validity_hash, thermal_hash = verify_and_validate_configs(
        root, validity_cfg_path, thermal_cfg_path
    )

    # 3. Protocol hash
    if not protocol_path.exists():
        raise FileNotFoundError(f"Missing protocol file: {protocol_path}")
    protocol_hash = sha256_file(protocol_path)

    # 4. Enumerate confirmatory matrix
    specs = enumerate_p7_confirmatory_matrix(validity_cfg_path)

    # Subtotals
    cohort_counts = {
        "core_benchmark": sum(1 for s in specs if s.cohort == "core_benchmark"),
        "event_blind_benchmark": sum(1 for s in specs if s.cohort == "event_blind_benchmark"),
        "algorithm_comparators": sum(1 for s in specs if s.cohort == "algorithm_comparators"),
        "oracle_reference": sum(1 for s in specs if s.cohort == "oracle_reference"),
    }
    if cohort_counts != {
        "core_benchmark": 432,
        "event_blind_benchmark": 216,
        "algorithm_comparators": 72,
        "oracle_reference": 36,
    }:
        raise ValueError(f"Cohort subtotal mismatch: {cohort_counts}")

    # Sorted run-ID digest
    sorted_run_ids = sorted(s.run_id for s in specs)
    run_id_digest = hashlib.sha256("\n".join(sorted_run_ids).encode("utf-8")).hexdigest()

    manifest_data = {
        "manifest_version": "1.0",
        "study_phase": "Phase 7 (Day 9 Provenance Repair and Confirmatory Freeze)",
        "confirmation_status": "sealed_not_executed",
        "confirmatory_outcome_rows_loaded": False,
        "confirmatory_execution_performed": False,
        "total_confirmatory_cells": len(specs),
        "cohort_counts": cohort_counts,
        "run_id_digest": run_id_digest,
        "primary_confirmatory_objective": "carbon_first",
        "frozen_pair_identities": [
            {
                "pair_id": t["pair_id"],
                "heatwave_window_id": t["heatwave_window_id"],
                "matched_control_window_id": t["matched_control_window_id"],
                "event_blind_window_id": t["event_blind_window_id"],
            }
            for t in sorted(cfg["triplets"]["confirmatory"], key=lambda x: x["pair_id"])
        ],
        "frozen_hashes": {
            "p6_validity_yaml_sha256": validity_hash,
            "p6_thermal_yaml_sha256": thermal_hash,
            "p6_frozen_protocol_sha256": protocol_hash,
            **verified_hashes,
        },
        "enumerator_version": "1.0",
        "git_commit": git_commit,
    }

    out_p = root / output_manifest_path
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    return manifest_data



def load_development_benchmark_filtered(pairs_path: Path) -> pd.DataFrame:
    """Load development benchmark rows using read-time parquet pushdown filtering.

    Strict boundary: Non-development rows are never read into pandas DataFrame memory.
    """
    if not pairs_path.exists():
        raise FileNotFoundError(f"Benchmark pairs file missing: {pairs_path}")

    # Read-time filtering using pyarrow
    table = pq.read_table(
        str(pairs_path),
        filters=[("triplet_id", "=", DEV_TRIPLET_ID)],
    )
    df = table.to_pandas()

    if df.empty:
        raise ValueError(f"No rows returned for {DEV_TRIPLET_ID} from {pairs_path}")

    # Validate that NO confirmatory triplet leaked into memory
    triplets = df["triplet_id"].unique()
    if len(triplets) != 1 or triplets[0] != DEV_TRIPLET_ID:
        raise ValueError(f"Data boundary breach: Expected strictly [{DEV_TRIPLET_ID}], found {triplets}")

    # Validate window types and expected window IDs
    for ctx, exp_id in DEV_WINDOWS.items():
        sub = df[df["window_type"] == ctx].sort_values("timestamp_utc").reset_index(drop=True)
        if len(sub) != 120:
            raise ValueError(f"Context '{ctx}' has {len(sub)} rows, expected 120")
        actual_id = str(sub["window_id"].iloc[0])
        if actual_id != exp_id:
            raise ValueError(f"Context '{ctx}' window_id mismatch: got '{actual_id}', expected '{exp_id}'")

        # Validate contiguous hourly UTC timestamps
        ts_series = pd.to_datetime(sub["timestamp_utc"], utc=True)
        for i in range(1, len(ts_series)):
            delta = (ts_series.iloc[i] - ts_series.iloc[i - 1]).total_seconds()
            if delta != 3600:
                raise ValueError(f"Non-contiguous hourly interval at row {i} in context '{ctx}': {delta}s")

    return df


def verify_and_validate_configs(
    repo_root: Path,
    p6_validity_yaml_path: Path,
    p6_thermal_yaml_path: Path,
) -> tuple[dict[str, Any], str, str]:
    """Validate configs/p6_validity.yaml and compute canonical configuration hashes."""
    if not p6_validity_yaml_path.exists():
        raise FileNotFoundError(f"Missing validity config: {p6_validity_yaml_path}")
    if not p6_thermal_yaml_path.exists():
        raise FileNotFoundError(f"Missing thermal config: {p6_thermal_yaml_path}")

    cfg = load_p6_validity_config(p6_validity_yaml_path)
    val_status = validate_p6_validity_config(cfg)
    if not val_status.get("valid") or not val_status.get("is_frozen") or val_status.get("has_placeholders"):
        raise ValueError(f"p6_validity.yaml failed frozen validation: {val_status}")

    # Verify key configuration dimensions agree with the runner
    triplets = cfg.get("triplets", {})
    dev_triplet = triplets.get("development", {})
    if dev_triplet.get("pair_id") != DEV_TRIPLET_ID:
        raise ValueError(f"Development pair_id mismatch in config: {dev_triplet.get('pair_id')} != {DEV_TRIPLET_ID}")

    conf_triplets = triplets.get("confirmatory", [])
    if len(conf_triplets) != 3:
        raise ValueError(f"Expected 3 confirmatory triplets in config, found {len(conf_triplets)}")

    hg_cfg = cfg.get("heatguard", {})
    rolling_cfg = hg_cfg.get("rolling", {})
    if rolling_cfg.get("forecast_horizon_hours") != 24 or rolling_cfg.get("commit_hours") != 1:
        raise ValueError("HeatGuard rolling configuration mismatch: horizon must be 24, commit must be 1")

    p6_validity_hash = sha256_file(p6_validity_yaml_path)
    p6_thermal_hash = sha256_file(p6_thermal_yaml_path)

    return cfg, p6_validity_hash, p6_thermal_hash


def verify_frozen_hashes(
    repo_root: Path,
    expected_p4_manifest: str = FROZEN_P4_MANIFEST_HASH,
    expected_p4_checkpoint: str = FROZEN_P4_CHECKPOINT_HASH,
    expected_calibration_manifest: str = FROZEN_CALIBRATION_MANIFEST_HASH,
) -> dict[str, str]:
    """Verify all three frozen SHA-256 hashes strictly against disk."""
    p4_manifest_path = repo_root / "data/models/p6_temperature_v2/artifact_manifest.json"
    p4_checkpoint_path = repo_root / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"
    cal_manifest_path = repo_root / "data/models/p6_heatguard_calibration_v3/manifest.json"

    for p, name in [
        (p4_manifest_path, "P4 temperature artifact manifest"),
        (p4_checkpoint_path, "P4 temperature checkpoint"),
        (cal_manifest_path, "P6 HeatGuard calibration manifest"),
    ]:
        if not p.exists():
            raise FileNotFoundError(f"Required frozen file missing: {p} ({name})")

    h_p4_m = sha256_file(p4_manifest_path)
    if h_p4_m != expected_p4_manifest:
        raise ValueError(f"P4 manifest hash mismatch: got {h_p4_m}, expected {expected_p4_manifest}")

    h_p4_c = sha256_file(p4_checkpoint_path)
    if h_p4_c != expected_p4_checkpoint:
        raise ValueError(f"P4 checkpoint hash mismatch: got {h_p4_c}, expected {expected_p4_checkpoint}")

    h_cal_m = sha256_file(cal_manifest_path)
    if h_cal_m != expected_calibration_manifest:
        raise ValueError(f"HeatGuard calibration manifest mismatch: got {h_cal_m}, expected {expected_calibration_manifest}")

    return {
        "p4_manifest_sha256": h_p4_m,
        "p4_checkpoint_sha256": h_p4_c,
        "calibration_manifest_sha256": h_cal_m,
    }


def copy_forecast_metrics_deliverable(
    source_metrics_csv: Path,
    target_metrics_csv: Path,
) -> tuple[Path, str]:
    """Produce data/results/p6_forecast_metrics.csv preserving validation and development rows."""
    if not source_metrics_csv.exists():
        raise FileNotFoundError(f"Source evaluation metrics missing: {source_metrics_csv}")

    df = pd.read_csv(source_metrics_csv)
    valid_splits = {"validation", "development"}
    actual_splits = set(df["split"].unique())
    if not actual_splits.issubset(valid_splits):
        raise ValueError(f"Found non-authorized splits in forecast metrics: {actual_splits - valid_splits}")

    val_df = df[df["split"] == "validation"]
    lstm_val = val_df[val_df["model"] == "TinyTemperatureLSTM"]
    shpd_val = val_df[val_df["model"] == "same_hour_previous_day"]
    if lstm_val.empty or shpd_val.empty:
        raise ValueError("Missing LSTM or same_hour_previous_day in validation split")

    lstm_rmse = float(lstm_val["rmse"].iloc[0])
    shpd_rmse = float(shpd_val["rmse"].iloc[0])
    improvement = (shpd_rmse - lstm_rmse) / shpd_rmse
    cond1 = improvement >= 0.02

    lstm_ext = float(lstm_val["extreme_underprediction_mae"].iloc[0])
    shpd_ext = float(shpd_val["extreme_underprediction_mae"].iloc[0])
    ext_improvement = (shpd_ext - lstm_ext) / shpd_ext
    cond2 = (ext_improvement >= 0.05) and (improvement >= -0.02)

    target_metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target_metrics_csv.with_suffix(".tmp")
    df.to_csv(temp_target, index=False)
    temp_target.replace(target_metrics_csv)

    file_hash = sha256_file(target_metrics_csv)
    return target_metrics_csv, file_hash


def build_workload_cache(repo_root: Path) -> tuple[dict[tuple[int, float], pd.DataFrame], dict[tuple[int, float], str]]:
    """Generate and cache workloads preserving maximum_parallelism and compute deterministic digests."""
    cache: dict[tuple[int, float], pd.DataFrame] = {}
    digests: dict[tuple[int, float], str] = {}

    canonical_w0_path = repo_root / "data/workloads/workload_trace_v0.parquet"
    if canonical_w0_path.exists():
        w0 = pd.read_parquet(canonical_w0_path)
    else:
        w0 = generate_deterministic_workload(
            workload_trace_id="trace_standard_120h_v0",
            random_seed=20261016,
            job_count=30,
        )

    w1 = generate_deterministic_workload(
        workload_trace_id="trace_standard_120h_v1",
        random_seed=20261017,
        job_count=30,
    )

    for seed, base_w in [(20261016, w0), (20261017, w1)]:
        for mult in [1.0, 2.0, 3.0]:
            scaled = scale_workload(base_w, mult, seed=seed)
            # Verify maximum_parallelism is preserved
            if "maximum_parallelism" not in scaled.columns:
                raise ValueError("Workload scaling unexpectedly omitted maximum_parallelism")
            cache[(seed, mult)] = scaled
            digests[(seed, mult)] = compute_canonical_df_sha256(scaled)

    return cache, digests


def precompute_development_forecasts(
    repo_root: Path,
    pairs_dev: pd.DataFrame,
) -> dict[str, tuple[dict[int, np.ndarray], dict[int, ForecastResult]]]:
    """Precompute rolling temperature and market forecasts for each development window.

    Enforces:
    - Temperature features at origin t strictly end at t-1 and draw from [t-72, t-1].
    - Market forecasts at origin t strictly use history < t and frozen fallback behavior.
    """
    raw_noaa_dir = repo_root / "data/raw/noaa"
    model_ckpt = repo_root / "data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt"
    model, ckpt_data = load_verified_checkpoint(model_ckpt)
    scaler_dict = ckpt_data["scaler"]
    scaler = ScalerMetadata(
        mean=scaler_dict["mean"],
        std=scaler_dict["std"],
        count=scaler_dict["count"],
        p95=scaler_dict["p95"],
        fitted_at_utc=scaler_dict["fitted_at_utc"],
        train_start_utc=scaler_dict["train_start_utc"],
        train_end_exclusive_utc=scaler_dict["train_end_exclusive_utc"],
    )

    mkt_provider = HistoricalPersistenceForecastProvider()
    forecast_cache: dict[str, tuple[dict[int, np.ndarray], dict[int, ForecastResult]]] = {}

    for ctx in ["heatwave", "control", "event_blind"]:
        w_df = pairs_dev[pairs_dev["window_type"] == ctx].sort_values("timestamp_utc").reset_index(drop=True)
        w_id = str(w_df["window_id"].iloc[0])
        start_utc = pd.to_datetime(w_df["timestamp_utc"].iloc[0], utc=True).to_pydatetime()
        end_utc = pd.to_datetime(w_df["timestamp_utc"].iloc[-1], utc=True).to_pydatetime() + timedelta(hours=1)

        hist_start_utc = start_utc - timedelta(hours=72)
        end_with_target = end_utc + timedelta(hours=24)

        noaa_series = load_noaa_hourly_series(raw_noaa_dir, hist_start_utc, end_with_target)

        # Build feature tensors for all 120 rolling origins strictly from causal history [t-72, t-1]
        features_list = []
        for h_offset in range(120):
            orig_ts = start_utc + timedelta(hours=h_offset)
            lb_df = noaa_series.loc[orig_ts - timedelta(hours=72) : orig_ts - timedelta(hours=1)]
            if len(lb_df) != 72:
                raise ValueError(f"Origin {orig_ts} has incomplete lookback: {len(lb_df)} rows")
            temps = lb_df["temperature_c"].to_numpy(dtype=np.float32)
            if np.isnan(temps).any():
                raise ValueError(f"Origin {orig_ts} contains NaN temperature in lookback")

            std_temps = (temps - scaler.mean) / scaler.std
            ts_hours = np.array([ts.hour for ts in lb_df.index], dtype=np.float32)
            ts_doy = np.array([ts.timetuple().tm_yday for ts in lb_df.index], dtype=np.float32)
            sin_hr = np.sin(2 * np.pi * ts_hours / 24.0, dtype=np.float32)
            cos_hr = np.cos(2 * np.pi * ts_hours / 24.0, dtype=np.float32)
            sin_dy = np.sin(2 * np.pi * ts_doy / 365.25, dtype=np.float32)
            cos_dy = np.cos(2 * np.pi * ts_doy / 365.25, dtype=np.float32)

            feat = np.stack([std_temps, sin_hr, cos_hr, sin_dy, cos_dy], axis=-1)
            features_list.append(feat)

        X_all = np.stack(features_list, axis=0)
        preds_24 = predict_unscaled(model, X_all, scaler)

        temp_by_offset: dict[int, np.ndarray] = {}
        mkt_by_offset: dict[int, ForecastResult] = {}

        for h_offset in range(120):
            orig_ts = start_utc + timedelta(hours=h_offset)
            temp_by_offset[h_offset] = preds_24[h_offset]

            mkt_res = mkt_provider.forecast(
                origin_timestamp_utc=orig_ts,
                horizon_hours=24,
                history_df=w_df,
                window_type=ctx,
                window_id=w_id,
            )
            mkt_by_offset[h_offset] = mkt_res

        forecast_cache[ctx] = (temp_by_offset, mkt_by_offset)

    return forecast_cache


def run_deployable_rolling_schedule(
    policy_id: str,
    workload_df: pd.DataFrame,
    temp_forecasts: dict[int, np.ndarray],
    mkt_forecasts: dict[int, ForecastResult],
    fcfg: FacilityConfig,
    objective: str,
    start_utc: datetime,
    constraints: SchedulingConstraints,
) -> tuple[ScheduleResult, float | None]:
    """Execute a deployable policy under the common rolling information boundary.

    Shared rolling specification:
    - 24-hour forecast horizon;
    - 1-hour commitment;
    - only released, unfinished work;
    - beyond-horizon reservation;
    - no future realized data.
    """
    trace_id = str(workload_df["workload_trace_id"].iloc[0])
    demanded_proc = int(workload_df["processing_requirement"].sum())

    jobs_state: dict[str, dict[str, Any]] = {}
    for _, row in workload_df.iterrows():
        jid = str(row["job_id"])
        req = int(row["processing_requirement"])
        arr = int(row["arrival_offset_hours"])
        dead = int(row["deadline_offset_hours"])
        energy = float(row["energy_kwh"])
        jobs_state[jid] = {
            "remaining_req": req,
            "arrival": arr,
            "deadline": dead,
            "unit_power_kw": energy / req,
            "unit_energy_kwh": energy / req,
            "workload_row": row.to_dict(),
        }

    committed_allocations: list[ScheduledJobAllocation] = []
    overall_unmet_deadlines: set[str] = set()

    for origin_h in range(120):
        origin_utc = start_utc + timedelta(hours=origin_h)
        temp_fc_24 = temp_forecasts[origin_h]
        mkt_fc_24 = mkt_forecasts[origin_h]

        # 1. In-window eligible jobs check
        window_eligible_jobs: list[dict[str, Any]] = []
        job_required_in_window: dict[str, int] = {}
        step_unmet: list[str] = []

        for jid, info in jobs_state.items():
            if info["remaining_req"] <= 0:
                continue
            arr = info["arrival"]
            dead = info["deadline"]
            rem = info["remaining_req"]

            if arr > origin_h:
                continue
            if dead <= origin_h:
                if jid not in step_unmet:
                    step_unmet.append(jid)
                continue

            window_arr_offset = max(0, arr - origin_h)
            if dead <= origin_h + 24:
                window_deadline_offset = dead - origin_h
                window_effective_req = rem
                job_required_in_window[jid] = rem
            else:
                window_deadline_offset = 24
                future_slots = dead - (origin_h + 24)
                req_in_window = max(0, rem - future_slots)
                window_effective_req = req_in_window
                job_required_in_window[jid] = req_in_window

            if window_effective_req == 0:
                continue

            if window_deadline_offset <= window_arr_offset or window_effective_req > (window_deadline_offset - window_arr_offset):
                if jid not in step_unmet:
                    step_unmet.append(jid)

            window_eligible_jobs.append({
                "workload_trace_id": trace_id,
                "job_id": jid,
                "arrival_offset_hours": window_arr_offset,
                "deadline_offset_hours": window_deadline_offset,
                "processing_requirement": window_effective_req,
                "energy_kwh": window_effective_req * info["unit_energy_kwh"],
                "maximum_parallelism": info["workload_row"].get("maximum_parallelism", 1),
                "priority": info["workload_row"].get("priority", 0),
                "preemptible": info["workload_row"].get("preemptible", True),
            })

        # 2. Build 24-hour forecast facility state for this origin
        fc_df = pd.DataFrame({
            "timestamp_utc": [origin_utc + timedelta(hours=h) for h in range(24)],
            "forecast_temperature_c": temp_fc_24,
        })
        forecast_facility_state = build_forecast_facility_state(fc_df, fcfg)

        if window_eligible_jobs:
            replan_df = pd.DataFrame(window_eligible_jobs)

            if policy_id == "static_unaware":
                policy = StaticUnawarePolicy(objective=objective)
                window_result = policy.schedule(replan_df, mkt_fc_24, constraints)
            elif policy_id == "capacity_aware":
                policy = CapacityAwarePolicy(forecast_facility_state, objective=objective)
                window_result = policy.schedule(replan_df, mkt_fc_24, constraints)
            elif policy_id == "full_thermal_aware":
                policy = FullThermalAwarePolicy(forecast_facility_state, objective=objective)
                window_result = policy.schedule(replan_df, mkt_fc_24, constraints)
            else:
                raise ValueError(f"Unknown deployable policy_id in rolling harness: {policy_id}")

            # Verify in-window allocations meet required-in-window units
            in_window_alloc_counts: dict[str, int] = {j["job_id"]: 0 for j in window_eligible_jobs}
            for alloc in window_result.allocations:
                in_window_alloc_counts[alloc.job_id] += 1

            for jid, required_units in job_required_in_window.items():
                actual_units = in_window_alloc_counts.get(jid, 0)
                if actual_units < required_units:
                    if jid not in step_unmet:
                        step_unmet.append(jid)

            if not window_result.is_feasible:
                for uj in window_result.unmet_deadlines:
                    if uj not in step_unmet:
                        step_unmet.append(uj)

            # Commit offset 0 only
            for alloc in window_result.allocations:
                if alloc.allocated_hour_offset == 0:
                    jid = alloc.job_id
                    if jobs_state[jid]["remaining_req"] > 0:
                        global_alloc = ScheduledJobAllocation(
                            job_id=jid,
                            allocated_hour_offset=origin_h,
                            execution_power_kw=alloc.execution_power_kw,
                            allocated_energy_kwh=alloc.allocated_energy_kwh,
                        )
                        committed_allocations.append(global_alloc)
                        jobs_state[jid]["remaining_req"] -= 1

        for jid in step_unmet:
            overall_unmet_deadlines.add(jid)

    # Final check across all jobs
    for jid, info in jobs_state.items():
        if info["remaining_req"] > 0:
            overall_unmet_deadlines.add(jid)

    is_overall_feasible = (len(overall_unmet_deadlines) == 0) and (len(committed_allocations) == demanded_proc)

    sched_res = ScheduleResult(
        policy_name=policy_id,
        policy_version="1.0",
        workload_trace_id=trace_id,
        window_duration_hours=120,
        allocations=committed_allocations,
        total_cost_usd=0.0,
        total_carbon_emissions_kg=0.0,
        is_feasible=is_overall_feasible,
        unmet_deadlines=sorted(list(overall_unmet_deadlines)),
    )
    return sched_res, 0.0


def execute_p6_pilot_cell(
    spec: PilotCellSpec,
    realized_window_df: pd.DataFrame,
    workload_df: pd.DataFrame,
    temp_forecasts: dict[int, np.ndarray],
    mkt_forecasts: dict[int, ForecastResult],
    fcfg: FacilityConfig,
    provenance_hashes: dict[str, str],
    repo_root: Path,
) -> dict[str, Any]:
    """Execute a single pilot cell deterministically and record complete metrics and provenance."""
    t0 = time.perf_counter()
    status = "SUCCESS"
    error_class = None
    error_msg = None

    nominal_compute_cap_kw = float(fcfg.nominal_compute_capacity_kw)
    constraints = SchedulingConstraints(
        max_cluster_power_kw=nominal_compute_cap_kw,
        max_concurrent_jobs=16,
        allow_preemption=True,
    )

    realized_temp_df = realized_window_df[["timestamp_utc", "temperature_c"]].copy()
    realized_state = build_realized_facility_state(realized_temp_df, fcfg)

    trace_id = str(workload_df["workload_trace_id"].iloc[0])
    demanded_proc = int(workload_df["processing_requirement"].sum())
    demanded_energy = float(workload_df["energy_kwh"].sum())

    sched_res: ScheduleResult | None = None
    applied_margin: float | None = None

    start_ts = pd.to_datetime(realized_window_df["timestamp_utc"].iloc[0], utc=True).to_pydatetime()

    try:
        if spec.cohort in ("core_benchmark", "event_blind_benchmark"):
            sched_res, applied_margin = run_deployable_rolling_schedule(
                policy_id=spec.policy_id,
                workload_df=workload_df,
                temp_forecasts=temp_forecasts,
                mkt_forecasts=mkt_forecasts,
                fcfg=fcfg,
                objective=spec.objective,
                start_utc=start_ts,
                constraints=constraints,
            )

        elif spec.cohort == "algorithm_comparators":
            # Calibrated or fixed HeatGuard
            def temp_prov(origin_utc: datetime, horizon: int) -> np.ndarray:
                offset = int((origin_utc - start_ts).total_seconds() // 3600)
                return temp_forecasts[offset][:horizon]

            def mkt_prov(origin_utc: datetime, horizon: int) -> ForecastResult:
                offset = int((origin_utc - start_ts).total_seconds() // 3600)
                return mkt_forecasts[offset]

            if spec.policy_id == "heatguard_calibrated":
                scheduler = HeatGuardScheduler(
                    facility_config=fcfg,
                    margin_mode=HeatGuardMarginMode.calibrated,
                    calibration_artifact_dir=repo_root / "data/models/p6_heatguard_calibration_v3",
                    expected_manifest_sha256=FROZEN_CALIBRATION_MANIFEST_HASH,
                    objective=spec.objective,
                    repository_root=repo_root,
                )
            elif spec.policy_id == "heatguard_fixed":
                scheduler = HeatGuardScheduler(
                    facility_config=fcfg,
                    margin_mode=HeatGuardMarginMode.fixed,
                    fixed_pue_margin=spec.fixed_margin or 0.10,
                    objective=spec.objective,
                    repository_root=repo_root,
                )
            else:
                raise ValueError(f"Unknown algorithm policy: {spec.policy_id}")

            rolling_res = scheduler.schedule_rolling(
                workload_df=workload_df,
                temperature_forecast_provider=temp_prov,
                market_forecast_provider=mkt_prov,
                window_start_utc=start_ts,
                total_window_hours=120,
                nominal_constraints=constraints,
            )
            applied_margin = rolling_res.applied_margin
            sched_res = ScheduleResult(
                policy_name=rolling_res.policy_name,
                policy_version=rolling_res.policy_version,
                workload_trace_id=rolling_res.workload_trace_id,
                window_duration_hours=rolling_res.total_horizon_hours,
                allocations=rolling_res.allocations,
                total_cost_usd=0.0,
                total_carbon_emissions_kg=0.0,
                is_feasible=rolling_res.is_feasible,
                unmet_deadlines=rolling_res.unmet_deadlines,
            )

        elif spec.cohort == "oracle_reference":
            # Non-deployable reference policy with hindsight
            pol = OracleFullThermalAwarePolicy(
                realized_facility_state=realized_state,
                realized_market_state=realized_window_df,
                objective=spec.objective,
            )
            pts = [
                ForecastPoint(
                    timestamp_utc=start_ts + timedelta(hours=h),
                    horizon_hours=h,
                    predicted_price_usd_per_mwh=float(realized_window_df["price_usd_per_mwh"].iloc[h]),
                    predicted_carbon_g_per_kwh=float(realized_window_df["carbon_g_per_kwh"].iloc[h]),
                )
                for h in range(120)
            ]
            fc_real = ForecastResult(
                origin_timestamp_utc=start_ts,
                points=pts,
                model_name="realized_market",
                model_version="1.0",
            )
            sched_res = pol.schedule(workload_df, fc_real, constraints)

        else:
            raise ValueError(f"Unknown cohort: {spec.cohort}")

        score_df, score_summary = score_thermal_schedule(
            schedule=sched_res,
            workload_df=workload_df,
            realized_df=realized_window_df,
            thermal_state_df=realized_state,
        )

        completed_proc = len(sched_res.allocations)
        completed_energy = float(score_summary["total_compute_energy_kwh"])
        unfinished_proc = demanded_proc - completed_proc
        alloc_count = len(sched_res.allocations)
        violation_hours = int(score_summary["facility_power_violation_hours"])
        total_excess_kwh = float(score_summary["total_facility_power_excess_kwh"])
        max_excess_kw = float(score_summary["maximum_facility_power_excess_kw"])
        realized_fac_energy = float(score_summary["total_facility_energy_kwh"])
        cost_usd = float(score_summary["cooling_adjusted_cost_usd"])
        carbon_kg = float(score_summary["cooling_adjusted_carbon_kg"])
        sched_feasible = bool(sched_res.is_feasible)
        thermal_feasible = bool(score_summary["thermally_feasible"])
        unmet_deadlines_count = len(sched_res.unmet_deadlines)

    except Exception as exc:
        status = "FAILED"
        error_class = type(exc).__name__
        error_msg = str(exc)[:200]
        completed_proc = None
        completed_energy = None
        unfinished_proc = None
        alloc_count = None
        violation_hours = None
        total_excess_kwh = None
        max_excess_kw = None
        realized_fac_energy = None
        cost_usd = None
        carbon_kg = None
        sched_feasible = False
        thermal_feasible = False
        unmet_deadlines_count = None

    runtime_s = float(time.perf_counter() - t0)

    return {
        "run_id": spec.run_id,
        "triplet_id": spec.triplet_id,
        "context": spec.context,
        "window_id": spec.window_id,
        "cohort": spec.cohort,
        "facility_model": spec.facility_model,
        "thermal_curve": spec.thermal_curve,
        "workload_multiplier": float(spec.workload_multiplier),
        "seed": int(spec.seed),
        "workload_trace_id": trace_id,
        "objective": spec.objective,
        "policy_id": spec.policy_id,
        "policy_version": spec.policy_version,
        "deployable": bool(spec.deployable),
        "margin_mode": spec.margin_mode or "none",
        "applied_margin": applied_margin,
        "status": status,
        "error_class": error_class,
        "error_message": error_msg,
        "runtime_seconds": round(runtime_s, 4),
        "demanded_processing_slots": demanded_proc,
        "demanded_energy_kwh": round(demanded_energy, 4),
        "completed_processing_slots": completed_proc,
        "completed_energy_kwh": round(completed_energy, 4) if completed_energy is not None else None,
        "unfinished_processing_slots": unfinished_proc,
        "unmet_deadlines_count": unmet_deadlines_count,
        "allocation_count": alloc_count,
        "facility_power_violation_hours": violation_hours,
        "total_facility_power_excess_kwh": round(total_excess_kwh, 4) if total_excess_kwh is not None else None,
        "maximum_facility_power_excess_kw": round(max_excess_kw, 4) if max_excess_kw is not None else None,
        "realized_facility_energy_kwh": round(realized_fac_energy, 4) if realized_fac_energy is not None else None,
        "cooling_adjusted_cost_usd": round(cost_usd, 4) if cost_usd is not None else None,
        "cooling_adjusted_carbon_kg": round(carbon_kg, 4) if carbon_kg is not None else None,
        "scheduler_feasible": sched_feasible,
        "thermally_feasible": thermal_feasible,
        "p6_config_sha256": provenance_hashes["p6_config_sha256"],
        "p6_thermal_config_sha256": provenance_hashes["p6_thermal_config_sha256"],
        "development_benchmark_sha256": provenance_hashes["development_benchmark_sha256"],
        "workload_sha256": provenance_hashes[f"workload_sha256_{spec.seed}_{spec.workload_multiplier}"],
        "forecast_metrics_source_sha256": provenance_hashes["forecast_metrics_source_sha256"],
        "p4_manifest_sha256": provenance_hashes["p4_manifest_sha256"],
        "p4_checkpoint_sha256": provenance_hashes["p4_checkpoint_sha256"],
        "calibration_manifest_sha256": provenance_hashes["calibration_manifest_sha256"],
    }


def execute_development_pilot(
    repo_root: Path,
    config_path: Path,
    output_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute the full 252-cell development pilot with atomic write and resume safety."""
    # 1. Verify frozen artifact hashes
    verified_hashes = verify_frozen_hashes(repo_root)

    # 2. Validate validity configuration and thermal configuration
    thermal_cfg_path = repo_root / "configs/p6_thermal.yaml"
    _, p6_validity_hash, p6_thermal_hash = verify_and_validate_configs(
        repo_root=repo_root,
        p6_validity_yaml_path=config_path,
        p6_thermal_yaml_path=thermal_cfg_path,
    )

    # 3. Read development benchmark rows strictly through read-time pushdown filtering
    pairs_path = repo_root / "data/benchmarks/p6_event_control_pairs.parquet"
    pairs_dev = load_development_benchmark_filtered(pairs_path)
    dev_benchmark_hash = compute_canonical_df_sha256(pairs_dev)

    # 4. Build workload cache and workload digests
    workload_cache, workload_digests = build_workload_cache(repo_root)

    # 5. Check forecast metrics source hash
    src_fc_metrics = repo_root / "data/models/p6_temperature_v2/evaluation_metrics.csv"
    fc_metrics_source_hash = sha256_file(src_fc_metrics)

    provenance_hashes = {
        "p6_config_sha256": p6_validity_hash,
        "p6_thermal_config_sha256": p6_thermal_hash,
        "development_benchmark_sha256": dev_benchmark_hash,
        "forecast_metrics_source_sha256": fc_metrics_source_hash,
        **verified_hashes,
    }
    for (s_val, m_val), d_val in workload_digests.items():
        provenance_hashes[f"workload_sha256_{s_val}_{m_val}"] = d_val

    # 6. Enumerate exact 252 pilot cells
    specs = enumerate_p6_pilot_matrix(DEV_TRIPLET_ID)
    if len(specs) != 252:
        raise ValueError(f"Enumerated {len(specs)} cells; expected exactly 252.")

    expected_run_ids = {s.run_id: s for s in specs}

    # 7. Precompute development forecasts
    forecast_cache = precompute_development_forecasts(
        repo_root=repo_root,
        pairs_dev=pairs_dev,
    )

    # 8. Strict fail-closed resume validation
    output_parquet = output_dir / "p6_development_pilot.parquet"
    existing_rows: dict[str, dict[str, Any]] = {}

    if output_parquet.exists():
        try:
            existing_rows = validate_existing_pilot_parquet(
                parquet_path=output_parquet,
                expected_specs=expected_run_ids,
                provenance_hashes=provenance_hashes,
                workload_cache=workload_cache,
            )
        except Exception as resume_err:
            raise RuntimeError(f"Resume validation failed: {resume_err}. Refusing to overwrite corrupt output.") from resume_err

    results_rows: list[dict[str, Any]] = []
    total_start = time.perf_counter()

    for spec in specs:
        if spec.run_id in existing_rows:
            results_rows.append(existing_rows[spec.run_id])
            continue

        w_df = pairs_dev[pairs_dev["window_type"] == spec.context].sort_values("timestamp_utc").reset_index(drop=True)
        workload = workload_cache[(spec.seed, spec.workload_multiplier)]
        temp_fc, mkt_fc = forecast_cache[spec.context]

        sc = get_preset_thermal_scenario(spec.thermal_curve, config_path=repo_root / "configs/p6_thermal.yaml")
        fcfg = FacilityConfig(
            nominal_compute_capacity_kw=500.0,
            thermal_scenario=sc,
            model_kind=spec.facility_model,
        )

        row = execute_p6_pilot_cell(
            spec=spec,
            realized_window_df=w_df,
            workload_df=workload,
            temp_forecasts=temp_fc,
            mkt_forecasts=mkt_fc,
            fcfg=fcfg,
            provenance_hashes=provenance_hashes,
            repo_root=repo_root,
        )
        results_rows.append(row)

    total_wall_time_s = time.perf_counter() - total_start

    pilot_df = pd.DataFrame(results_rows)
    pilot_df = pilot_df.sort_values("run_id").reset_index(drop=True)

    # Atomic output write
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_parquet = output_parquet.with_suffix(".tmp.parquet")
    pilot_df.to_parquet(temp_parquet, index=False)
    temp_parquet.replace(output_parquet)

    # Copy forecast metrics deliverable
    dst_fc_metrics = output_dir / "p6_forecast_metrics.csv"
    _, fc_metrics_hash = copy_forecast_metrics_deliverable(src_fc_metrics, dst_fc_metrics)

    pilot_hash = sha256_file(output_parquet)

    meta = {
        "total_cells": len(pilot_df),
        "unique_run_ids": pilot_df["run_id"].nunique(),
        "successful_runs": int((pilot_df["status"] == "SUCCESS").sum()),
        "failed_runs": int((pilot_df["status"] != "SUCCESS").sum()),
        "total_wall_time_seconds": round(total_wall_time_s, 2),
        "pilot_parquet_sha256": pilot_hash,
        "forecast_metrics_sha256": fc_metrics_hash,
        "cohort_counts": pilot_df["cohort"].value_counts().to_dict(),
        "verified_hashes": verified_hashes,
        "provenance_hashes": provenance_hashes,
    }

    return pilot_df, meta
