# HeatTrace Phase P2: Alignment, QC, Provenance, and Onboarding

## Overview

HeatTrace Phase P2 builds the initial canonical aligned hourly dataset (`data/processed/hourly_caiso_v0.parquet`) from authentic, cached P1 sources across weather (NOAA GHCNh), wholesale power pricing (CAISO OASIS DAM LMP), and electricity generation/emissions (EIA-930).

The technical implementation adheres to frozen P1 methodology decisions and validates alignment contracts before multi-year scaling.

## Verified Scope

The v0 dataset covers exactly 48 hourly intervals representing two authentic local days in `America/Los_Angeles`:
1. **Extreme-Heat QC Local Day**: `2024-07-02` $\rightarrow$ UTC half-open interval `[2024-07-02T07:00:00Z, 2024-07-03T07:00:00Z)` (24 hours).
2. **Ordinary-Summer QC Local Day**: `2024-06-07` $\rightarrow$ UTC half-open interval `[2024-06-07T07:00:00Z, 2024-06-08T07:00:00Z)` (24 hours).

Total rows: **48**. Unique timestamps: **48**. Duplicate timestamps: **0**.

## Primary Artifacts Produced

- `data/processed/hourly_caiso_v0.parquet`: Canonical aligned dataset.
- `data/processed/hourly_caiso_v0_sample.csv`: Complete 48-row sample table for inspection.
- `data/manifests/aligned_coverage.csv`: Source-by-source window coverage audit for each QC day.
- `data/manifests/aligned_dataset_manifest.json`: Cryptographic manifest recording code commit, input hashes, output hashes, row counts, time ranges, missingness, and methodology parameters.

## CLI Usage Instructions

### 1. Build Aligned Dataset (Offline, Cache-Only)

Run the canonical alignment build. This command operates completely offline using cached P1 files and requires no EIA API key or internet access:

```bash
PYTHONPATH=src python -m heattrace.cli --build-aligned
```

Expected output:
```text
=================== HeatTrace P2 Aligned Dataset Builder ===================
Building canonical v0 aligned dataset from cached authentic P1 sources...
Successfully built and validated 48 aligned rows.
Parquet output:    data/processed/hourly_caiso_v0.parquet
Sample CSV output: data/processed/hourly_caiso_v0_sample.csv
Coverage CSV:      data/manifests/aligned_coverage.csv
Manifest JSON:     data/manifests/aligned_dataset_manifest.json
============================================================================
```

### 2. Run the Documented Dataset Loader (Teammate Verification)

Teammates (Person B or Person C) can verify the dataset using the loader CLI:

```bash
PYTHONPATH=src python -m heattrace.cli --load-aligned
```

Or invoke the standalone loader module:

```bash
PYTHONPATH=src python -m heattrace.process.loader
```

Expected loader output:
```text
================== HeatTrace Aligned Dataset Loader ==================
File path:         data/processed/hourly_caiso_v0.parquet
Total rows:        48
Timestamp range:   2024-06-07T07:00:00+00:00 to 2024-07-03T06:00:00+00:00
Rows per QC date:  {'2024-06-07': 24, '2024-07-02': 24}
Duplicate hours:   0
Missingness:       {'temperature_missing_count': 0, 'price_missing_count': 0, 'demand_missing_count': 0, 'net_generation_missing_count': 0, 'carbon_missing_count': 0}
EIA Issue Flags:   {'carbon_data_issue_count': 48, 'carbon_primary_analysis_eligible_count': 0}
Max Reconcil Diff: 6.583460e-07 lb/kWh (tol: 0.0001)

--- Sample First 5 Rows ---
...
======================================================================
```

## Programmatic API Usage

In Python:

```python
from heattrace.process.loader import load_aligned_dataset

# Loads and automatically validates canonical schema, monotonic order, and physics bounds
df = load_aligned_dataset("data/processed/hourly_caiso_v0.parquet")
print(f"Loaded {len(df)} rows across {df['timestamp_utc'].min()} to {df['timestamp_utc'].max()}")
```

## Gate G2-a Status

- **Status**: **Pending Independent Teammate Verification**
- **Action Required**: Person B or Person C must execute `PYTHONPATH=src python -m heattrace.cli --load-aligned` in their local environment and confirm the 48-row table passes schema and reconciliation checks.
