"""Deterministic scenario and grid generator for HeatTrace P5.5 (Grid Version 2).

Key improvements in v2:
- Strict seed separation:
  * forecast_seed depends ONLY on (base_seed, window_id, forecast_scenario_id).
  * workload_seed depends ONLY on (base_seed, job_count).
  * capacity and deadline parameters do NOT perturb forecast or workload seeds.
- Corrected evidence classification:
  * authentic_historical_baseline: ONLY flat_forecast + 1x workload + unconstrained capacity + baseline deadline.
  * controlled_simulation_flat_forecast: flat_forecast with any stressed condition (workload != 1x, capacity != unconstrained, or deadline != baseline).
  * controlled_hindsight_upper_bound: oracle_forecast.
  * controlled_simulation_noisy_oracle: noisy_oracle forecasts.
- Canonical scenario IDs: SCEN_v2_{window}_{fc}_{wl}_{res}_{dl}.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.experiments.p5_5_scenarios import compute_forecast_seed
from heattrace.workload.generator import (
    generate_deterministic_workload,
    validate_workload_dataframe,
)


@dataclass(frozen=True)
class P55ScenarioSpecV2:
    """Specification of a single P5.5 experiment scenario (Grid v2)."""
    scenario_id: str
    grid_version: str
    window_id: str
    window_type: str  # event or control
    forecast_scenario_id: str
    forecast_type: str  # flat, oracle, noisy_oracle
    evidence_class: str
    noise_sigma: float
    workload_multiplier: float
    job_count: int
    resource_scenario_id: str
    max_cluster_power_kw: float
    max_concurrent_jobs: int
    deadline_scenario_id: str
    slack_multiplier: float
    forecast_seed: int
    workload_seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def determine_evidence_class(
    forecast_type: str,
    workload_multiplier: float,
    resource_scenario_id: str,
    deadline_scenario_id: str,
) -> str:
    """Strictly classify the evidence category based on experimental conditions."""
    if forecast_type == "oracle":
        return "controlled_hindsight_upper_bound"
    elif forecast_type == "noisy_oracle":
        return "controlled_simulation_noisy_oracle"
    elif forecast_type == "flat":
        # Only the exact P5 baseline combination is authentic historical baseline
        if (
            workload_multiplier == 1.0
            and resource_scenario_id == "unconstrained"
            and deadline_scenario_id == "baseline"
        ):
            return "authentic_historical_baseline"
        else:
            return "controlled_simulation_flat_forecast"
    else:
        raise ValueError(f"Unknown forecast_type: {forecast_type}")


def generate_stressed_workload_v2(
    job_count: int,
    slack_multiplier: float,
    *,
    base_seed: int = 20261016,
    window_duration_hours: int = 120,
) -> pd.DataFrame:
    """Generate deterministic workload scaled by job_count and adjusted by deadline slack multiplier.

    Workload seed depends strictly on base_seed and job_count.
    """
    wl_seed_str = f"workload_{base_seed}_{job_count}"
    wl_seed = int(hashlib.sha256(wl_seed_str.encode("utf-8")).hexdigest()[:8], 16)

    trace_id = f"trace_p5_5_v2_jobs_{job_count}_slack_{slack_multiplier:.2f}"
    df_base = generate_deterministic_workload(
        workload_trace_id=trace_id,
        window_duration_hours=window_duration_hours,
        job_count=job_count,
        random_seed=wl_seed,
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
            if new_dead < arr + proc:
                new_dead = arr + proc
            new_deadlines.append(new_dead)
        df_base["deadline_offset_hours"] = new_deadlines

    validate_workload_dataframe(df_base, expected_window_hours=window_duration_hours)
    return df_base


def build_preregistered_p5_5_grid_v2(
    config_path: Path | str = "configs/p5_5.yaml",
) -> list[P55ScenarioSpecV2]:
    """Generate the full, machine-readable, deterministic preregistered P5.5 grid v2."""
    cfg = load_yaml(config_path)
    base_seed = int(cfg.get("random_seed", 20261016))
    grid_ver = str(cfg.get("grid_version", "v2"))

    windows = [
        {"window_id": cfg["benchmark"]["event_window_id"], "window_type": "event"},
        {"window_id": cfg["benchmark"]["control_window_id"], "window_type": "control"},
    ]
    forecast_scenarios = cfg["forecast_scenarios"]
    workload_mults = cfg["workload_multipliers"]
    resource_levels = cfg["resource_pressure"]
    deadline_levels = cfg["deadline_flexibility"]

    grid: list[P55ScenarioSpecV2] = []

    for win in windows:
        for fc in forecast_scenarios:
            fc_seed = compute_forecast_seed(base_seed, win["window_id"], fc["id"])

            for wm in workload_mults:
                job_count = int(round(30 * wm))
                wl_seed_str = f"workload_{base_seed}_{job_count}"
                wl_seed = int(hashlib.sha256(wl_seed_str.encode("utf-8")).hexdigest()[:8], 16)

                for res in resource_levels:
                    for dl in deadline_levels:
                        evidence_cls = determine_evidence_class(
                            fc["type"],
                            wm,
                            res["id"],
                            dl["id"],
                        )

                        scen_id = (
                            f"SCEN_v2_{win['window_type'][:4].upper()}_"
                            f"{win['window_id']}_"
                            f"{fc['id']}_"
                            f"WL{int(wm)}x_"
                            f"{res['id']}_"
                            f"{dl['id']}"
                        )

                        spec = P55ScenarioSpecV2(
                            scenario_id=scen_id,
                            grid_version=grid_ver,
                            window_id=win["window_id"],
                            window_type=win["window_type"],
                            forecast_scenario_id=fc["id"],
                            forecast_type=fc["type"],
                            evidence_class=evidence_cls,
                            noise_sigma=float(fc["noise_sigma"]),
                            workload_multiplier=float(wm),
                            job_count=job_count,
                            resource_scenario_id=res["id"],
                            max_cluster_power_kw=float(res["max_cluster_power_kw"]),
                            max_concurrent_jobs=int(res["max_concurrent_jobs"]),
                            deadline_scenario_id=dl["id"],
                            slack_multiplier=float(dl["slack_multiplier"]),
                            forecast_seed=fc_seed,
                            workload_seed=wl_seed,
                        )
                        grid.append(spec)

    return grid


def freeze_experiment_grid_v2(
    config_path: Path | str = "configs/p5_5.yaml",
    output_path: Path | str = "data/manifests/p5_5_experiment_grid.json",
) -> dict[str, Any]:
    """Freeze the machine-readable P5.5 experiment specification to disk."""
    grid = build_preregistered_p5_5_grid_v2(config_path)
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    records = [s.to_dict() for s in grid]
    manifest = {
        "manifest_version": "2.0",
        "grid_version": "v2",
        "phase": "P5.5",
        "description": "Preregistered policy discriminability and stress testing experiment grid v2 with isolated seeds and corrected evidence taxonomy",
        "total_scenarios": len(grid),
        "config_path": str(config_path),
        "scenarios": records,
    }

    with out_file.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return manifest
