"""Deterministic scenario and grid generator for HeatTrace P5.5.

Generates:
- 1x, 2x, 3x workload pressures
- Capacity/concurrency stress levels
- Deadline flexibility variations
- Forecast scenario configurations
- Full cartesian product of preregistered experiment scenarios
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.policy.interfaces import SchedulingConstraints
from heattrace.workload.generator import (
    generate_deterministic_workload,
    validate_workload_dataframe,
)


@dataclass(frozen=True)
class P55ScenarioSpec:
    """Specification of a single P5.5 experiment scenario."""
    scenario_id: str
    window_id: str
    window_type: str  # event or control
    forecast_scenario_id: str
    forecast_type: str  # flat, oracle, noisy_oracle
    evidence_class: str  # authentic_baseline, controlled_hindsight_upper_bound, controlled_simulation
    noise_sigma: float
    workload_multiplier: float
    job_count: int
    resource_scenario_id: str
    max_cluster_power_kw: float
    max_concurrent_jobs: int
    deadline_scenario_id: str
    slack_multiplier: float
    random_seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_stressed_workload(
    job_count: int,
    slack_multiplier: float,
    *,
    random_seed: int = 20261016,
    window_duration_hours: int = 120,
) -> pd.DataFrame:
    """Generate deterministic workload scaled by job_count and adjusted by deadline slack multiplier.

    Properties:
    - job identities are deterministic: job_0001 ... job_N.
    - arrival and processing requirements remain strictly valid.
    - deadlines are tightened or expanded:
        slack = dead - (arr + proc)
        new_slack = int(slack * slack_multiplier)
        new_dead = min(window_duration_hours, arr + proc + new_slack)
    - adheres to the P3-03 workload schema contract.
    """
    trace_id = f"trace_p5_5_jobs_{job_count}_slack_{slack_multiplier:.2f}"
    df_base = generate_deterministic_workload(
        workload_trace_id=trace_id,
        window_duration_hours=window_duration_hours,
        job_count=job_count,
        random_seed=random_seed,
    )

    if slack_multiplier != 1.0:
        new_deadlines = []
        for _, r in df_base.iterrows():
            arr = int(r["arrival_offset_hours"])
            dead = int(r["deadline_offset_hours"])
            proc = int(r["processing_requirement"])
            slack = dead - (arr + proc)
            new_slack = int(slack * slack_multiplier)
            new_dead = min(window_duration_hours, arr + proc + new_slack)
            # Ensure valid deadline
            if new_dead < arr + proc:
                new_dead = arr + proc
            new_deadlines.append(new_dead)
        df_base["deadline_offset_hours"] = new_deadlines

    validate_workload_dataframe(df_base, expected_window_hours=window_duration_hours)
    return df_base


def build_preregistered_p5_5_grid(
    config_path: Path | str = "configs/p5_5.yaml",
) -> list[P55ScenarioSpec]:
    """Generate the full, machine-readable, deterministic preregistered P5.5 experiment grid."""
    cfg = load_yaml(config_path)
    base_seed = int(cfg.get("random_seed", 20261016))

    windows = [
        {"window_id": cfg["benchmark"]["event_window_id"], "window_type": "event"},
        {"window_id": cfg["benchmark"]["control_window_id"], "window_type": "control"},
    ]
    forecast_scenarios = cfg["forecast_scenarios"]
    workload_mults = cfg["workload_multipliers"]
    resource_levels = cfg["resource_pressure"]
    deadline_levels = cfg["deadline_flexibility"]

    grid: list[P55ScenarioSpec] = []

    for win in windows:
        for fc in forecast_scenarios:
            for wm in workload_mults:
                job_count = int(round(30 * wm))
                for res in resource_levels:
                    for dl in deadline_levels:
                        # Derive unique deterministic scenario seed
                        seed_str = f"{win['window_id']}_{fc['id']}_{wm}_{res['id']}_{dl['id']}_{base_seed}"
                        scen_seed = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:8], 16)

                        scen_id = (
                            f"SCEN_{win['window_type'][:4].upper()}_"
                            f"{win['window_id']}_"
                            f"{fc['id']}_"
                            f"WL{int(wm)}x_"
                            f"{res['id']}_"
                            f"{dl['id']}"
                        )

                        spec = P55ScenarioSpec(
                            scenario_id=scen_id,
                            window_id=win["window_id"],
                            window_type=win["window_type"],
                            forecast_scenario_id=fc["id"],
                            forecast_type=fc["type"],
                            evidence_class=fc["evidence_class"],
                            noise_sigma=float(fc["noise_sigma"]),
                            workload_multiplier=float(wm),
                            job_count=job_count,
                            resource_scenario_id=res["id"],
                            max_cluster_power_kw=float(res["max_cluster_power_kw"]),
                            max_concurrent_jobs=int(res["max_concurrent_jobs"]),
                            deadline_scenario_id=dl["id"],
                            slack_multiplier=float(dl["slack_multiplier"]),
                            random_seed=scen_seed,
                        )
                        grid.append(spec)

    return grid


def freeze_experiment_grid(
    config_path: Path | str = "configs/p5_5.yaml",
    output_path: Path | str = "data/manifests/p5_5_experiment_grid.json",
) -> dict[str, Any]:
    """Freeze the machine-readable P5.5 experiment specification to disk."""
    grid = build_preregistered_p5_5_grid(config_path)
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    records = [s.to_dict() for s in grid]
    manifest = {
        "manifest_version": "1.0",
        "phase": "P5.5",
        "description": "Preregistered policy discriminability and stress testing experiment grid",
        "total_scenarios": len(grid),
        "config_path": str(config_path),
        "scenarios": records,
    }

    with out_file.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return manifest
