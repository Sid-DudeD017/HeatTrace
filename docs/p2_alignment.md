# HeatTrace Phase P2: Alignment, QC, Provenance, and Onboarding

## Overview

HeatTrace Phase P2 builds the initial canonical aligned hourly dataset (`data/processed/hourly_caiso_v0.parquet`) from authentic, cached P1 sources across weather (NOAA GHCNh), wholesale power pricing (CAISO OASIS DAM LMP), and electricity generation/emissions (EIA-930).

The technical implementation adheres to frozen P1 methodology decisions and validates alignment contracts before multi-year scaling.

## Verified Scope

The v0 dataset covers exactly 48 hourly intervals representing two authentic local days in `America/Los_Angeles`:
1. **Extreme-Heat QC Local Day**: `2024-07-02` $\rightarrow$ UTC half-open interval `[2024-07-02T07:00:00Z, 2024-07-03T07:00:00Z)` (24 hours).
2. **Ordinary-Summer QC Local Day**: `2024-06-07` $\rightarrow$ UTC half-open interval `[2024-06-07T07:00:00Z, 2024-06-08T07:00:00Z)` (24 hours).

Total rows: **48**. Unique timestamps: **48**. Duplicate timestamps: **0**.

## Methodology Decisions and Source Alignment

- **Canonical Timestamp**: Timezone-aware UTC interval start (`timestamp_utc`), sorted ascending.
- **Provider Timestamp Treatment**:
  - **NOAA GHCNh**: Instantaneous/interval observations mapped into UTC hourly bins $[T, T+1\text{h})$. Arithmetic mean temperature calculated for accepted observations under the frozen quality policy.
  - **CAISO OASIS DAM LMP**: `INTERVALSTARTTIME_GMT` provides canonical UTC interval starts directly.
  - **EIA-930 API v2**: Reports in hour-ending notation (`period`). Mapped to canonical interval start via $\text{timestamp\_utc} = \text{hour\_ending\_utc} - 1\text{ hour}$.
  - **EIA-930 Workbook**: Reports in hour-ending notation (`UTC time`). Mapped to canonical interval start via $\text{UTC time} - 1\text{ hour}$.
- **Canonical Demand and Net Generation**: Sourced directly from corrected EIA API v2 (`demand_mw` and `net_generation_mw`). Workbook demand and net generation are preserved separately as audit fields (`workbook_demand_mw`, `workbook_net_generation_mw`) along with explicit absolute difference metrics.
- **Production-Based Carbon Intensity**: Sourced from official EIA workbook `CO2 Emissions Intensity for Generated Electricity`, converted to $\text{g CO}_2/\text{kWh}$ using the exact physical factor $453.59237$.
- **EIA Known Data Issues**: Retained explicitly. Flagged rows carry `carbon_data_issue = True`, `carbon_primary_analysis_eligible = False`, and `source_quality = "success_with_data_issues"`.

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

### 2. Run the Documented Dataset Loader

Any teammate can inspect and verify the dataset using the loader CLI:

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
Max Demand Diff:   0.00 MW (API demand_mw vs workbook_demand_mw)
Max Net Gen Diff:  0.00 MW (API net_generation_mw vs workbook_net_generation_mw)

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

- **Status**: **Complete** — Person A clean-environment loader verification passed. The documented loader remains available for optional independent reproduction.
- **Verification Details**: Verified in an isolated clean virtual environment outside the repository against `data/processed/hourly_caiso_v0.parquet`. All 48 rows passed schema, monotonic ordering, physics bounds, and reconciliation checks with exit code 0.
