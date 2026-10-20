"""Deterministic mock workload generator and job trace schemas for HeatTrace P3-03."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import random
from typing import Any
import pandas as pd

from heattrace.config import load_yaml
from heattrace.ingest.provenance import sha256_file


WORKLOAD_JOB_COLUMNS: list[str] = [
    "workload_trace_id",
    "job_id",
    "arrival_offset_hours",
    "deadline_offset_hours",
    "processing_requirement",
    "energy_kwh",
    "maximum_parallelism",
    "priority",
    "preemptible",
    "seed",
    "generator_version",
]

DEFAULT_GENERATOR_VERSION = "1.0"


def generate_deterministic_workload(
    *,
    workload_trace_id: str = "trace_standard_120h_v0",
    window_duration_hours: int = 120,
    job_count: int = 50,
    random_seed: int = 20261016,
    generator_version: str = DEFAULT_GENERATOR_VERSION,
) -> pd.DataFrame:
    """Generate a deterministic synthetic workload trace using relative hour offsets.
    
    Properties:
    - Relative offsets: arrival_offset_hours in [0, window_duration_hours - 4)
    - Deadlines: deadline_offset_hours > arrival_offset_hours, <= window_duration_hours
    - Processing requirement: hours required (integer in [1, 8])
    - Feasible: processing_requirement <= (deadline_offset_hours - arrival_offset_hours)
    - Energy requirement: energy_kwh = processing_requirement * power_draw_kw (e.g. 10 kW to 100 kW)
    - Max parallelism: integer in [1, 4]
    - Priority: integer in [1, 5] (1=standard, 5=critical)
    - Preemptible: boolean
    - Zero absolute event/control timestamps: completely reusable across event or control windows.
    - Deterministic: identical output given the same random_seed.
    """
    if window_duration_hours <= 0:
        raise ValueError(f"window_duration_hours must be > 0, got {window_duration_hours}")
    if job_count <= 0:
        raise ValueError(f"job_count must be > 0, got {job_count}")

    rng = random.Random(random_seed)
    jobs: list[dict[str, Any]] = []

    for idx in range(1, job_count + 1):
        job_id = f"job_{idx:04d}"

        # Arrival offset: 0 to window_duration_hours - 6
        max_arr = max(0, window_duration_hours - 6)
        arr_offset = rng.randint(0, max_arr)

        # Processing requirement: 1 to 6 hours
        proc_req = rng.randint(1, 6)

        # Slack: at least proc_req hours, plus optional slack between 1 and 24 hours
        max_slack = min(24, window_duration_hours - (arr_offset + proc_req))
        slack = rng.randint(1, max(1, max_slack))
        dead_offset = min(window_duration_hours, arr_offset + proc_req + slack)

        # Ensure deadline > arrival and >= arrival + proc_req
        if dead_offset < arr_offset + proc_req:
            dead_offset = arr_offset + proc_req

        # Parallelism: 1, 2, or 4
        max_parallelism = rng.choice([1, 2, 4])

        # Power draw per processing hour: 15.0 to 75.0 kW
        power_kw = round(rng.uniform(15.0, 75.0), 2)
        energy_kwh = round(proc_req * power_kw, 2)

        priority = rng.randint(1, 5)
        preemptible = rng.choice([True, False])

        jobs.append({
            "workload_trace_id": workload_trace_id,
            "job_id": job_id,
            "arrival_offset_hours": arr_offset,
            "deadline_offset_hours": dead_offset,
            "processing_requirement": proc_req,
            "energy_kwh": energy_kwh,
            "maximum_parallelism": max_parallelism,
            "priority": priority,
            "preemptible": preemptible,
            "seed": random_seed,
            "generator_version": generator_version,
        })

    # Deterministic sorting: arrival_offset_hours, priority (descending), deadline_offset_hours, job_id
    jobs.sort(key=lambda j: (j["arrival_offset_hours"], -j["priority"], j["deadline_offset_hours"], j["job_id"]))

    df = pd.DataFrame(jobs, columns=WORKLOAD_JOB_COLUMNS)
    validate_workload_dataframe(df, expected_window_hours=window_duration_hours)
    return df


def validate_workload_dataframe(
    df: pd.DataFrame,
    *,
    expected_window_hours: int = 120,
    expected_seed: int | None = None,
) -> None:
    """Validate a workload DataFrame according to the P3-03 contract."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    actual_cols = list(df.columns)
    if actual_cols != WORKLOAD_JOB_COLUMNS:
        raise ValueError(
            f"Workload columns mismatch.\nExpected: {WORKLOAD_JOB_COLUMNS}\nActual:   {actual_cols}"
        )

    if df.empty:
        raise ValueError("Workload DataFrame cannot be empty")

    if df["job_id"].duplicated().any():
        dups = df[df["job_id"].duplicated()]["job_id"].tolist()
        raise ValueError(f"Duplicate job_id found in workload: {dups}")

    for idx, row in df.iterrows():
        jid = row["job_id"]
        arr = row["arrival_offset_hours"]
        dead = row["deadline_offset_hours"]
        proc = row["processing_requirement"]
        energy = row["energy_kwh"]
        par = row["maximum_parallelism"]
        prio = row["priority"]

        if arr < 0:
            raise ValueError(f"Job {jid}: arrival_offset_hours {arr} < 0")
        if dead > expected_window_hours:
            raise ValueError(f"Job {jid}: deadline_offset_hours {dead} > window {expected_window_hours}")
        if dead <= arr:
            raise ValueError(f"Job {jid}: deadline_offset_hours {dead} <= arrival {arr}")
        if proc <= 0:
            raise ValueError(f"Job {jid}: processing_requirement {proc} <= 0")
        if proc > (dead - arr):
            raise ValueError(f"Job {jid}: processing_requirement {proc} exceeds window ({dead - arr})")
        if energy <= 0.0:
            raise ValueError(f"Job {jid}: energy_kwh {energy} <= 0")
        if par <= 0:
            raise ValueError(f"Job {jid}: maximum_parallelism {par} <= 0")
        if not (1 <= prio <= 5):
            raise ValueError(f"Job {jid}: priority {prio} outside [1, 5]")

        if expected_seed is not None and row["seed"] != expected_seed:
            raise ValueError(f"Job {jid}: seed {row['seed']} != expected {expected_seed}")


def build_and_export_workloads(
    data_dir: Path | str = "data",
    config_dir: Path | str = "configs",
    job_count: int = 50,
) -> dict[str, Any]:
    """Build, export, and manifest the deterministic workload trace."""
    data_dir = Path(data_dir)
    config_dir = Path(config_dir)

    study_cfg = load_yaml(config_dir / "study.yaml")
    seed = study_cfg.get("random_seed", 20261016)

    df_workload = generate_deterministic_workload(
        workload_trace_id="trace_standard_120h_v0",
        window_duration_hours=120,
        job_count=job_count,
        random_seed=seed,
    )

    workload_dir = data_dir / "workloads"
    workload_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = workload_dir / "workload_trace_v0.parquet"
    csv_path = workload_dir / "workload_trace_v0.csv"
    manifest_path = workload_dir / "workload_manifest.json"

    df_workload.to_parquet(parquet_path, index=False)
    df_workload.to_csv(csv_path, index=False)

    manifest = {
        "manifest_version": "1.0",
        "workload_trace_id": "trace_standard_120h_v0",
        "job_count": len(df_workload),
        "random_seed": seed,
        "window_duration_hours": 120,
        "total_processing_hours": int(df_workload["processing_requirement"].sum()),
        "total_energy_kwh": float(round(df_workload["energy_kwh"].sum(), 2)),
        "generator_version": DEFAULT_GENERATOR_VERSION,
        "output_files": {
            "workload_trace_parquet": {
                "path": str(parquet_path),
                "sha256": sha256_file(parquet_path),
                "size_bytes": parquet_path.stat().st_size,
            },
            "workload_trace_csv": {
                "path": str(csv_path),
                "sha256": sha256_file(csv_path),
                "size_bytes": csv_path.stat().st_size,
            },
        },
    }

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    return {
        "df": df_workload,
        "parquet_path": parquet_path,
        "csv_path": csv_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def inspect_workload_trace(parquet_path: Path | str) -> None:
    """Print human-readable summary of the generated workload trace."""
    p = Path(parquet_path)
    if not p.is_file():
        raise FileNotFoundError(f"Workload trace not found: {p}")

    df = pd.read_parquet(p)
    print("\n======================= HeatTrace P3 Workload Trace =======================")
    print(f"File:                   {p}")
    print(f"Trace ID:               {df['workload_trace_id'].iloc[0]}")
    print(f"Job Count:              {len(df)}")
    print(f"Random Seed:            {df['seed'].iloc[0]}")
    print(f"Total Processing Req:   {df['processing_requirement'].sum()} hours")
    print(f"Total Energy Req:       {df['energy_kwh'].sum():.2f} kWh")
    print(f"Mean Arrival Offset:    {df['arrival_offset_hours'].mean():.1f} hours")
    print(f"Mean Deadline Offset:   {df['deadline_offset_hours'].mean():.1f} hours")
    print("---------------------------------------------------------------------------")
    print("Sample Jobs (First 5):")
    for _, r in df.head(5).iterrows():
        print(
            f"  {r['job_id']:<10} | Arr: {r['arrival_offset_hours']:>2}h | Dead: {r['deadline_offset_hours']:>3}h | "
            f"Proc: {r['processing_requirement']}h | Energy: {r['energy_kwh']:>6.1f} kWh | "
            f"Prio: {r['priority']} | Preempt: {str(r['preemptible']):<5}"
        )
    print("===========================================================================\n")
