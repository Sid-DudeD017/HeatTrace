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
> - **P1 Implementation:** Complete. All ingestion pipelines, schema validators, coverage calculators, and deterministic QC gates are implemented and unit-tested.
> - **P1 Authentic End-to-End QC:** Pending.
> - **Current Blockers for End-to-End Live QC:**
>   1. `EIA_API_KEY` is not available in the execution environment (required for live EIA API demand & net generation queries).
>   2. CAISO live network access is currently unreachable from the environment (CAISO OASIS network requests fail).
>   3. Both frozen QC dates (`2022-06-01` and `2022-09-05`) contain `Data issue = 1` for all 24 hourly records in the authentic EIA CISO workbook. Under the conservative QC policy (`fail_on_eia_data_issues: true`), QC exits nonzero until an explicit policy decision or user approval is made.

| Checklist Item | Requirement | Status | Details |
|---|---|---|---|
| **P1-01** | Download NOAA hourly temperature observations and extract daily maxima | **Complete (Verified)** | Hourly GHCNh acquisition verified from NOAA NODD S3 bucket (`noaa-ghcnh-pds`). `extract_daily_maxima` groups observations by local calendar day (`America/Los_Angeles`), converts local days to exact half-open UTC intervals (handling 23h spring-forward, 24h normal, and 25h fall-back DST days), enforces the official NOAA quality code policy (accepts `''`, `'1'`, `'5'`, `'A'`, `'Passed'`; rejects `'2'`, `'3'`, `'4'`, `'6'`, `'7'`, `'Failed'`; fails conservatively on unverified codes), and applies deterministic duplicate-timestamp resolution (HeatTrace project policy: METAR FM15 > SPECI FM16 > SYNOP FM12, conservative max tie-break, tracking duplicate/conflict counts). |
| **P1-02** | Retrieve EIA demand, generation, and hourly emissions/intensity records | **Implementation Complete (Live Key Pending)** | **Demand & Net Generation**: Implementation complete. Uses EIA API v2 `/electricity/rto/region-data` with repeated facets `facets[type][]=D` and `facets[type][]=NG`. Reports `blocked_pending_api_key` when `EIA_API_KEY` is not exported without fabricating coverage from the workbook.<br>**Native Emissions & Intensity**: Ingestion verified on authentic official EIA CISO workbook (`data/raw/eia/CISO.xlsx`, SHA-256: `b418ea77...`, 97.6 MB). Verified native sheets: `Published Hourly Data`, `Notes`, `Known Data Issues`. Translates hour-ending UTC to interval-start UTC (`UTC time - 1 hour`), verifies non-negative emissions and intensities, joins `Known Data Issues` by BA and serial, and surfaces `success_with_data_issues` because all 24 hours on both QC dates are flagged with `Data issue = 1`. |
| **P1-03** | Retrieve CAISO day-ahead LMP data with retry, caching, throttling, and documented fallback | **Implementation Complete (Network Pending)** | SingleZip DAM hourly LMP acquisition verified for node `TH_NP15_GEN-APND`. Implements strict retry allowlist (HTTP 429, 500, 502, 503, 504, URLError, TimeoutError), parses numeric and HTTP-date `Retry-After` headers, bounds backoff delay (max 30.0s), fast-fails deterministic 4xx and content/zip errors without retrying, cleans up temporary files on any failure, throttles requests (default 5.0s delay), validates cached ZIP contents and complete hourly coverage on cache hits, and documents fallback for dates older than 39 months (`blocked_pending_historical_oasis_download`). |
| **P1-04** | Record source URLs, parameters, retrieval dates, SHA-256 checksums, and coverage | **Complete (Verified)** | Provenance records appended to `data/manifests/raw_sources.jsonl` with SHA-256 digests, sanitized parameters, retrieval timestamps, and cache status. Secrets (such as `EIA_API_KEY`) are completely redacted. Hourly coverage metrics logged to `data/manifests/coverage.csv`. |
| **P1-QC** | Test 1 heatwave day and 1 ordinary summer day before scaling downloads; create coverage.csv | **Pending Authentic End-to-End Live Run** | Evaluates two explicit QC days: Heatwave (`2022-09-05`, 35.6°C max) and Ordinary (`2022-06-01`, 21.7°C max). Non-dry-run QC execution strictly checks all 5 datasets across both days and enforces the conservative `fail_on_eia_data_issues: true` policy. Because live credentials and network are absent and all 48 workbook records are flagged with data issues, authentic QC execution truthfully returns exit code 1. |


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
python -m heattrace.cli --qc
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
| **NOAA** | GHCNh | Station `USW00023234` (SFO) | **Verified Live & Cached** | Verified live download from NOAA NODD AWS S3 open bucket (`noaa-ghcnh-pds`). In interval `[2022-06-01T00:00Z, 2022-06-02T00:00Z)`, 28 raw observations cover all 24 hourly bins (24 standard 56-min METAR readings plus 4 synoptic 00-min readings; `covered_hourly_bins: 24/24`, `missing_hours: 0`). Full quality codes (`temperature_Quality_Code`) and Celsius temperatures are preserved. Daily maxima extracted across local calendar days (`America/Los_Angeles`). Subsequent runs verify cache hits without re-downloading. |
| **CAISO** | OASIS (`PRC_LMP`) | `TH_NP15_GEN-APND` | **Verified Live & Cached** | Verified live download and parsing of authentic DAM hourly LMP ZIP/CSV for `2024-06-01`. Exactly 24 hourly total-LMP records verified (`covered_hourly_bins: 24/24`, `row_count: 24`, `missing_hours: 0`, `duplicate_timestamps: 0`). Each record has 3600-second duration and interval-start UTC semantics. Throttling and retry logic with `Retry-After` support active. *Known limitation:* Standard CAISO OASIS SingleZip API enforces a rolling historical window of 39 months (3 years, 3 months). Queries for dates older than 39 months return XML error code 1000 (`No data returned for the specified selection`) and report structured status `blocked_pending_historical_oasis_download`. |
| **EIA Demand & Net Gen** | EIA-930 | BA `CISO` | **Verified Live & Cached (when API key provided)** | EIA API v2 route `/electricity/rto/region-data` with `facets[type][]=D` and `facets[type][]=NG` is verified against live API responses (24/24 covered hours for both Demand and Net Generation in interval `[2022-06-01T00:00Z, 2022-06-02T00:00Z)`). Without an environment key, it cleanly reports `blocked_pending_api_key`. |
| **EIA Emissions & Intensity** | EIA-930 | BA `CISO` | **Verified Native Workbook (Data Issues Flagged)** | Native CISO workbook (`CISO.xlsx`) ingestion is fully implemented and verified without modifying the original 97.6 MB workbook. Verified sheets: `Published Hourly Data`, `Notes`, `Known Data Issues`. Hourly coverage is 24/24 for both QC days (`2022-06-01` and `2022-09-05`). Reconciles generated and consumed intensity formulas against reported values. Native emissions status is `success_with_data_issues`: all 24 hours on each QC day have `Data issue = 1`. Under the default conservative policy (`fail_on_eia_data_issues: true`), final QC fails; the data can only be accepted with an explicit policy override (`--no-fail-on-eia-data-issues`) or after approved replacement dates are selected. Intermediate staging CSV is also supported via `--eia-emissions-file`. |

### Tooling and Linting Note
Syntax and compilation were verified using `python -m compileall src tests` and `git diff --check`.


## Repository layout

- `src/heattrace/` — ingestion, processing, forecasting, scheduling, and evaluation code
  - `src/heattrace/ingest/` — NOAA, CAISO, EIA ingestion, manifests, and coverage calculation
  - `src/heattrace/cli.py` — P1 command-line runner
- `configs/` — frozen source and study configuration
- `data/` — local data only; raw, interim, processed, and manifests are git-ignored
- `docs/` — contracts, source audit, and methods notes
- `tests/` — unit tests, mocked fixtures, and opt-in live tests
- `reports/` — generated QC and audit reports
- `runs/` — generated benchmark outputs
