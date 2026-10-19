"""Minimal loader module for HeatTrace aligned dataset verification."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from heattrace.process.quality import CANONICAL_COLUMNS, validate_aligned_dataframe


def load_aligned_dataset(
    parquet_path: str | Path = "data/processed/hourly_caiso_v0.parquet",
    *,
    validate: bool = True,
) -> pd.DataFrame:
    """Load the aligned Parquet dataset and optionally validate its schema and contents."""
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"Aligned dataset Parquet file not found: {path}")

    df = pd.read_parquet(path)

    if validate:
        validate_aligned_dataframe(df)

    return df


def inspect_aligned_dataset(
    parquet_path: str | Path = "data/processed/hourly_caiso_v0.parquet",
    *,
    sample_rows: int = 5,
) -> dict[str, Any]:
    """Inspect the aligned dataset and print a concise, human-readable summary for teammate verification."""
    df = load_aligned_dataset(parquet_path, validate=True)
    summary = validate_aligned_dataframe(df)

    print("\n================== HeatTrace Aligned Dataset Loader ==================")
    print(f"File path:         {parquet_path}")
    print(f"Total rows:        {summary['row_count']}")
    print(f"Timestamp range:   {summary['timestamp_start']} to {summary['timestamp_end']}")
    print(f"Rows per QC date:  {summary['date_counts']}")
    print(f"Duplicate hours:   {summary['duplicate_timestamps']}")
    print(f"Missingness:       {summary['missingness']}")
    print(f"EIA Issue Flags:   {summary['eia_issues']}")
    print(f"Max Reconcil Diff: {summary['max_reconciliation_diff_lb_per_kwh']:.6e} lb/kWh (tol: {summary['reconciliation_tolerance_lb_per_kwh']})")
    print(f"Max Demand Diff:   {summary['max_demand_difference_mw']:.2f} MW (API demand_mw vs workbook_demand_mw)")
    print(f"Max Net Gen Diff:  {summary['max_net_generation_difference_mw']:.2f} MW (API net_generation_mw vs workbook_net_generation_mw)")

    print(f"\n--- Sample First {sample_rows} Rows ---")
    display_cols = [
        "timestamp_utc",
        "local_date",
        "temperature_c",
        "price_usd_per_mwh",
        "demand_mw",
        "net_generation_mw",
        "workbook_demand_mw",
        "workbook_net_generation_mw",
        "carbon_g_per_kwh",
        "carbon_data_issue",
        "source_quality",
    ]
    print(df[display_cols].head(sample_rows).to_string(index=False))
    print("======================================================================\n")

    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="HeatTrace aligned dataset loader and verifier.")
    parser.add_argument(
        "--path",
        default="data/processed/hourly_caiso_v0.parquet",
        help="Path to hourly_caiso_v0.parquet (default: data/processed/hourly_caiso_v0.parquet)",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5,
        help="Number of sample rows to display (default: 5)",
    )
    args = parser.parse_args(argv)
    inspect_aligned_dataset(args.path, sample_rows=args.sample_rows)


if __name__ == "__main__":
    main()
