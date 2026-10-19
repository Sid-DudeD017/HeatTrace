# HeatTrace

Reproducible research prototype for evaluating workload scheduling under heatwave-related electricity price and carbon conditions.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

All primary timestamps use UTC and identify interval start. Raw downloads and secrets are intentionally excluded from Git.

## Phase P1: Data-Acquisition Smoke Tests

Phase P1 implements reproducible data-acquisition smoke tests for NOAA GHCNh, CAISO OASIS, and EIA-930 before historical bulk downloading.

### P1 Checklist & Implementation Status

> **Overall Phase P1 Status:**
> - **P1 Implementation & Pipeline QC:** Complete. All ingestion pipelines, schema validators, coverage calculators, and deterministic QC gates are fully implemented, verified, and passing under authentic multi-source execution.
> - **Methodology & QC Dates:** Percentile-defined extreme-heat day (`2024-07-02`, authentic max `31.1°C` vs 2024 June–September P98 threshold `30.0°C`) and ordinary summer day (`2024-06-07`, authentic max `21.7°C` vs 2024 summer median `20.6°C`, range `[20.0, 24.0]`).
> - **Historical Superseded Candidates:** The original 2022 QC dates (`2022-09-05` Labor Day heatwave peak at `35.6°C`, 2022 P98 `34.19°C`; and `2022-06-01` ordinary day at `21.7°C`) were superseded because CAISO's free OASIS SingleZip API operates on a rolling 39-month window, placing 2022 dates beyond direct API access. The 2022 analysis remains valid and documented in project history.
> - **EIA Data-Quality Policy:** EIA-930 flags `Data issue = 1` across modern balancing authority workbooks (covering 93% of all modern hours in `CISO.xlsx`). For P1 ingestion and pipeline QC, status `success_with_data_issues` is accepted under an explicitly documented configuration policy (`fail_on_eia_data_issues: false`). In coverage reporting, all 24/24 issue counts are truthfully recorded. Downstream research (P2/P5) retains these flags for sensitivity analysis and exclusion testing.

| Checklist Item | Requirement | Status | Details |
|---|---|---|---|
| **P1-01** | Download NOAA hourly temperature observations and extract daily maxima | **Complete (Verified)** | Hourly GHCNh acquisition verified from NOAA NODD S3 bucket (`noaa-ghcnh-pds`) for primary station `USW00023234` (SFO). `extract_daily_maxima` groups observations by local calendar day (`America/Los_Angeles`), converts local days to exact half-open UTC intervals, enforces official NOAA quality code policy, and applies deterministic duplicate-timestamp resolution (METAR FM15 > SPECI FM16 > SYNOP FM12, conservative max tie-break). Daily maxima verified: `31.1°C` on extreme-heat day `2024-07-02` (qualifying above 2024 summer P98 of `30.0°C`) and `21.7°C` on ordinary day `2024-06-07` (near 2024 summer median of `20.6°C`). |
| **P1-02** | Retrieve EIA demand, generation, and hourly emissions/intensity records | **Complete (Verified)** | **Demand & Net Generation**: Retrieved and validated live via EIA API v2 `/electricity/rto/region-data` using repeated facets `facets[type][]=D` and `facets[type][]=NG`. Exactly 24/24 hourly bins covered for both series on both QC days.<br>**Native Emissions & Intensity**: Verified on authentic official EIA CISO workbook (`data/raw/eia/CISO.xlsx`, SHA-256: `b418ea77...`, 97.6 MB). Verified sheets: `Published Hourly Data`, `Notes`, `Known Data Issues`. Translates hour-ending UTC to interval-start UTC (`UTC time - 1 hour`), verifies non-negative emissions and intensities, validates formula reconciliation, and tracks Known Data Issues flags (all 24 hours on each QC day flagged with `Data issue = 1`, accepted for pipeline QC under explicit policy). |
| **P1-03** | Retrieve CAISO day-ahead LMP data with retry, caching, throttling, and documented fallback | **Complete (Verified)** | SingleZip DAM hourly LMP acquisition verified live for node `TH_NP15_GEN-APND`. Exactly 24/24 hourly bins verified for both `2024-07-02` and `2024-06-07` with zero missing hours and zero duplicates. Implements retry allowlist, `Retry-After` header parsing, throttling (5.0s), ZIP integrity verification, and cache validation. |
| **P1-04** | Record source URLs, parameters, retrieval dates, SHA-256 checksums, and coverage | **Complete (Verified)** | Provenance records appended to `data/manifests/raw_sources.jsonl` with SHA-256 digests, sanitized parameters, retrieval timestamps, and cache status. Secrets (`EIA_API_KEY`) are completely redacted. Hourly coverage metrics logged to `data/manifests/coverage.csv`. |
| **P1-QC** | Test 1 heatwave day and 1 ordinary summer day before scaling downloads; create coverage.csv | **Complete (Verified Exit 0)** | Evaluates extreme-heat day (`2024-07-02`) and ordinary summer day (`2024-06-07`). Authentic non-dry-run QC execution verifies all 8 required hourly datasets across both days (16 rows total), confirming 24/24 covered bins, zero missing hours, zero duplicates, and verified QC day classifications, exiting 0 under the documented ingestion-QC policy. |


### Running Smoke Tests & Quality Control

#### 1. Dry Run (Sanitized request parameters, no network calls)
```bash
python -m heattrace.cli --dry-run
# Or for a specific source:
python -m heattrace.cli --source noaa --dry-run
# Dry run for P1-QC 2-day evaluation:
python -m heattrace.cli --dry-run --qc
```

#### 2. Live and Cached Smoke Tests
To run authentic sample downloads:
```bash
# Test all sources
python -m heattrace.cli

# Test an individual source
python -m heattrace.cli --source noaa
python -m heattrace.cli --source caiso
python -m heattrace.cli --source eia

# Test EIA API live (when EIA_API_KEY is exported)
python -m heattrace.cli --source eia --eia-api

# Ingest authentic EIA CISO Excel workbook:
python -m heattrace.cli --source eia --eia-emissions-workbook=data/raw/eia/CISO.xlsx

# Test EIA emissions with a manually prepared staging CSV:
python -m heattrace.cli --source eia --eia-emissions-file=data/raw/eia/ciso_emissions_staging.csv

# Run P1-QC two-day validation across all sources:
set -a; [ -f .env ] && source .env; set +a
PYTHONPATH=src python -m heattrace.cli --qc --eia-api --eia-emissions-workbook=data/raw/eia/CISO.xlsx
```

#### 3. EIA CISO Workbook Details
The authentic official EIA CISO workbook is located at:
`data/raw/eia/CISO.xlsx`
- File size: 97,607,203 bytes
- SHA-256: `b418ea77f536048e11fe0c5786de7544dfa7c774a90083e7f2c0d9facc74ce50`
- Sheets: `Published Hourly Data`, `Notes`, `Known Data Issues`
- Time range: July 1, 2015 through October 18, 2026
- Semantics: `UTC time` is hour-ending. Interval start is $\text{UTC time} - 1\text{ hour}$.
- Units: Demand and generation in MWh; CO₂ emissions in metric tons; CO₂ intensity in lbs/kWh.
- Conversions: 1 lb/kWh = 453.59237 g/kWh.

**Cache and Provenance Semantics:**
- When a file is first acquired, raw files are saved unchanged in `data/raw/<provider>/`, and a provenance record with `cache_hit: false` is written to `data/manifests/raw_sources.jsonl`.
- Subsequent runs validate the cached file's integrity (checking headers, stations, years, or zip contents). If valid, a cache hit is recognized without recording false network retrievals or changing `retrieved_at`. If corrupt, the file is safely reacquired.
- Coverage metrics are saved to `data/manifests/coverage.csv`.

#### 4. Offline Unit Tests and Opt-In Live Tests
Offline unit tests mock all external network calls and validate parsing, schema checks, interval boundaries, error paths, and secret redaction:
```bash
pytest
```
To run the opt-in live network tests:
```bash
HEATTRACE_LIVE_TESTS=1 pytest -k "test_live"
```

### Source Verification Status & Known Limitations

| Provider | Dataset | Target / Node | Verification Status | Observed Result / Limitations |
|---|---|---|---|---|
| **NOAA** | GHCNh | Station `USW00023234` (SFO) | **Verified Live & Cached** | Verified live download from NOAA NODD AWS S3 open bucket (`noaa-ghcnh-pds`). In 2024, complete summer observations cover all 122 days. Extreme-heat day `2024-07-02` verified at `31.1°C` daily maximum (2024 summer P98: `30.0°C`). Ordinary day `2024-06-07` verified at `21.7°C` (2024 summer median: `20.6°C`). Full quality codes and Celsius temperatures preserved. Subsequent runs verify cache hits without re-downloading. |
| **CAISO** | OASIS (`PRC_LMP`) | `TH_NP15_GEN-APND` | **Verified Live & Cached** | Verified live download and parsing of authentic DAM hourly LMP ZIP/CSV for `2024-07-02` and `2024-06-07`. Exactly 24 hourly total-LMP records verified per day (`covered_hourly_bins: 24/24`, `missing_hours: 0`, `duplicate_timestamps: 0`). Each record has 3600-second duration and interval-start UTC semantics. Throttling (5.0s) and retry logic active. *Known limitation:* Standard CAISO OASIS SingleZip API enforces a rolling historical window of 39 months; older dates return XML error code 1000 and report `blocked_pending_historical_oasis_download`. |
| **EIA Demand & Net Gen** | EIA-930 | BA `CISO` | **Verified Live & Cached** | EIA API v2 route `/electricity/rto/region-data` with `facets[type][]=D` and `facets[type][]=NG` is verified against live API responses (24/24 covered hours for both Demand and Net Generation on both `2024-07-02` and `2024-06-07`). Without an environment key, it cleanly reports `blocked_pending_api_key`. |
| **EIA Emissions & Intensity** | EIA-930 | BA `CISO` | **Verified Native Workbook (Ingestion-QC Policy)** | Native CISO workbook (`CISO.xlsx`) ingestion is fully implemented and verified without modifying the original 97.6 MB workbook. Verified sheets: `Published Hourly Data`, `Notes`, `Known Data Issues`. Hourly coverage is 24/24 for both QC days. Reconciles generated and consumed intensity formulas against reported values. Native emissions status is `success_with_data_issues`: all 24 hours on each QC day have `Data issue = 1`. Under the explicit ingestion-QC policy (`fail_on_eia_data_issues: false`), pipeline QC passes; downstream scientific analysis (P2/P5) must retain flags and perform exclusion/sensitivity analysis. |

### Tooling and Linting Note
Syntax and compilation were verified using `python -m compileall src tests` and `git diff --check`.


## Phase P2: Alignment, QC, Provenance, and Onboarding

Phase P2 builds and validates the first canonical aligned dataset (`data/processed/hourly_caiso_v0.parquet`) from the two authentic P1 QC windows (`2024-07-02` extreme heat and `2024-06-07` ordinary summer in `America/Los_Angeles`).

### P2 Checklist & Implementation Status

> **Overall Phase P2 Status:**
> - **P2-01 (Alignment & Merge):** **Complete (Verified)**. Canonical 48-row UTC hourly index constructed with interval-start semantics, unique sorted timestamps, and exact 24 rows per local date. EIA API v2 periods correctly treated as hour-ending and mapped to interval start ($\text{period} - 1\text{h}$).
> - **P2-02 (Canonical Carbon Signal):** **Complete (Verified)**. Canonical demand and net generation sourced from corrected EIA API v2; canonical carbon intensity uses official workbook `CO2 Emissions Intensity for Generated Electricity`, converted via $1\text{ lb/kWh} = 453.59237\text{ g/kWh}$. Retains reported and recalculated values; reconciliation diff passes tolerance ($6.58 \times 10^{-7} \le 10^{-4}\text{ lb/kWh}$).
> - **P2-03 (QC & Validation):** **Complete (Verified)**. Deterministic schema, timestamp alignment, monotonic ordering, non-negativity, missingness, EIA issue flags, and source audit differences verified.
> - **P2-04 (Onboarding & Documentation):** **Complete (Verified)**. Documentation in `docs/p2_alignment.md`, `docs/contracts.md`, and `docs/carbon_method.md`.
> - **P2-TEST (Unit & Integration Tests):** **Complete (Verified)**. Comprehensive tests in `tests/test_p2_alignment.py` and `tests/test_p1_ingest.py` passing with zero test mutation of production data.
> - **Gate G2-a:** **Complete — Person A clean-environment loader verification passed. The documented loader remains available for optional independent reproduction.**

### Running P2 Alignment and Verification

#### 1. Build Aligned Dataset (Offline, Cache-Only)
```bash
PYTHONPATH=src python -m heattrace.cli --build-aligned
```
This command loads authentic cached P1 files, normalizes units, validates the canonical contract, and produces:
- `data/processed/hourly_caiso_v0.parquet`
- `data/processed/hourly_caiso_v0_sample.csv`
- `data/manifests/aligned_coverage.csv`
- `data/manifests/aligned_dataset_manifest.json`

#### 2. Run Aligned Dataset Loader
To load, validate, and inspect the table:
```bash
PYTHONPATH=src python -m heattrace.cli --load-aligned
```
Or use the loader module directly:
```bash
PYTHONPATH=src python -m heattrace.process.loader
```

## Repository layout

- `src/heattrace/` — ingestion, processing, forecasting, scheduling, and evaluation code
  - `src/heattrace/ingest/` — NOAA, CAISO, EIA ingestion, manifests, and coverage calculation
  - `src/heattrace/process/` — canonical alignment, unit normalization, schema validation, and loader
  - `src/heattrace/cli.py` — P1 and P2 command-line interface
- `configs/` — frozen source and study configuration
- `data/` — local data only; raw, interim, processed, and manifests are git-ignored
- `docs/` — contracts, source audit, carbon methodology, and alignment documentation
- `tests/` — unit tests, mocked fixtures, and opt-in live tests
- `reports/` — generated QC and audit reports
- `runs/` — generated benchmark outputs
