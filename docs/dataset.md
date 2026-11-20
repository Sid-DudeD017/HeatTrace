# HeatTrace Dataset Guide & Provenance Specification

This document provides a comprehensive technical reference for the HeatTrace datasets, detailing data layers, public versus local-only artifacts, record grains, primary keys, schemas, eligibility flags, and reuse boundaries.

---

## 1. Data Architecture: Observed, Derived, and Synthetic Layers

HeatTrace organizes research artifacts into three strictly segregated methodological layers:

```
[Layer 1: Observed Empirical Data]
  ├── NOAA GHCNh (Hourly dry-bulb air temperature, dew point, humidity)
  ├── CAISO OASIS (Day-ahead locational marginal wholesale electricity price)
  └── EIA-930 (Balancing-authority hourly demand, generation, production carbon)
         │
         ▼
[Layer 2: HeatTrace-Derived Benchmark Records]
  ├── Weather-Only Heatwave Detection (P90 daily maximum exceedances, N >= 3 days)
  ├── Station Events (25 events) & Regional Connected Episodes (15 episodes)
  ├── Matched Controls (Outcome-blind seasonal controls, T_max <= 22°C)
  └── Event-Blind Ordinary Baseline Windows (Equal-duration warm-season samples)
         │
         ▼
[Layer 3: Synthetic Benchmark Modeling & Evaluation]
  ├── Synthetic Batch Workloads (Deterministic deadline-constrained job slots)
  ├── Synthetic Thermal Sensitivity Model (Piecewise PUE coupling above 22°C)
  ├── Facility Constraints (Hard 600 kW power cap throttling effective IT capacity)
  └── Policy Optimization (Rolling-horizon schedulers evaluated under Equal-Service Gate)
```

1. **Observed Layer**: External physical and market signals collected from official public agencies. These time series provide authentic temporal structures, diurnal profiles, and cross-signal correlations.
2. **Derived Layer**: Curated benchmark scenarios, station-event catalogues, matched controls, and quality-screened evaluation windows constructed strictly from weather observations without conditioning on computational outcomes.
3. **Synthetic Layer**: Controlled facility sensitivity curves ($500\,\mathrm{kW}$ nominal IT, $600\,\mathrm{kW}$ facility cap, low and medium thermal curves) and deterministic synthetic workloads. These models do not represent telemetry from a specific physical data center; they provide a repeatable testbed to stress scheduling algorithms under realistic external conditions.

---

## 2. Public vs. Local-Only Artifact Inventory

To ensure complete transparency regarding what is publicly cloneable from GitHub versus what remains in local or ignored filesystem caches, Table 1 details the public availability of every research artifact:

| Artifact Name | Format | Record Count | Public Status | Repository Path | Notes |
|---|---|---|---|---|---|
| **Original Event Catalogue** | Parquet | 4 events | **Tracked Public** | `data/events/p3_heatwaves.parquet` | SFO events across 2022–2025 |
| **Original Control Catalogue** | CSV / Parquet | 4 controls | **Tracked Public** | `data/benchmarks/p6_event_control_index.csv` | Outcome-blind matched controls |
| **Original Triplet Index** | CSV | 4 triplets | **Tracked Public** | `data/benchmarks/p6_event_control_index.csv` | 1 development + 3 confirmatory |
| **Original Hourly Benchmark** | Parquet | 1,440 rows | **Tracked Public** | `data/benchmarks/p6_benchmark_hourly.parquet` | 120 h $\times$ 4 triplets $\times$ 3 contexts |
| **Event-Blind Pool** | CSV | 472 rows | **Tracked Public** | `data/events/p3_event_blind_pool.csv` | SFO non-extreme warm-season pool |
| **Phase Overlay Signals** | Parquet | 1,440 rows | **Tracked Public** | `data/events/p3_phase_signals.parquet` | Hourly onset, peak, recovery flags |
| **Frozen v1 Archive Payloads** | Tar / JSON / CSV | 54 payloads | **Tracked Public** | `data/archive/heattrace_v1_d5b3c86/` | Verified by `verify_archive.py` |
| **B2 Station Events** | CSV | 25 events | **Tracked Public** | `data/v2/events/p12_b2_station_events.csv` | 5 California stations, 2022–2026 |
| **B2 Regional Episodes** | CSV | 15 episodes | **Tracked Public** | `data/v2/events/p12_b2_regional_episodes.csv` | Connected components ($\pm 24\,\text{h}$) |
| **B2 Hourly Phase Labels Preview** | CSV | 100 rows | **Tracked Public** | `data/v2/events/p12_b2_hourly_phase_labels_preview.csv` | Public schema preview |
| **Full B2 Hourly Phase Labels** | CSV / Parquet | 4,320 rows | **Local-Only** | `data/v2/events/p12_b2_hourly_phase_labels.csv` | Untracked / ignored in git |
| **Full B2 Hourly Event Signals** | CSV | 4,320 rows | **Local-Only** | `data/v2/events/p12_b2_hourly_event_signals.csv` | Untracked / ignored in git |
| **B2 Matched Controls Index** | CSV | 12 controls | **Tracked Public** | `data/v2/tables/p12_b2_matched_controls.csv` | Controls for 12 matrix events |
| **B2 Ordinary Windows Index** | CSV | 240 windows | **Tracked Public** | `data/v2/tables/p12_b2_ordinary_windows.csv` | 20 windows per matrix event |
| **B2 Experiment Matrix** | CSV | 6,480 cells | **Tracked Public** | `data/v2/tables/p12_b2_matrix_cells.csv` | 12 events $\times$ 540 cells |
| **B2 Execution Results Parquet** | Parquet | 6,480 rows | **Tracked Public** | `data/v2/results/p12_b2_runs.parquet` | 43 metric columns |
| **B2 Execution Ledger** | JSONL | 6,480 lines | **Tracked Public** | `data/v2/results/p12_b2_execution.jsonl` | Terminal execution log |
| **Workload Job CSVs** | CSV | 30 files | **Tracked Public** | `data/workloads/` | Synthetic job arrival vectors |
| **Workload Parquets (Expanded)** | Parquet | Variable | **Local-Only** | `data/workloads/*.parquet` | Ignored by `.gitignore` |
| **Raw Provider Cache** | GZ / CSV / JSON | ~2.9 GiB | **Local-Only** | `data/raw/`, `data/interim/` | Ignored by `.gitignore` |
| **Compiled Manuscript PDF** | PDF | 30 pages | **Local-Only** | `paper/main.pdf` | Untracked in git |
| **Interactive Web Presentation** | React / Vite | Full repo | **Local-Only** | `.site-publish/heattrace-presentation/` | Untracked nested git repo |

---

## 3. Data Grains, Identifiers, and Schemas

### 3.1 Original v1 Single-Station Benchmark

The original single-station benchmark focuses on San Francisco International Airport (`SFO` / `USW00023234`) and wholesale pricing hub `TH_NP15_GEN-APND`.

- **Temporal Coverage**: Warm seasons (June 1 – September 30) across 2022–2025 (485 valid days).
- **Benchmark Grain**: Hourly resolution ($1.0\,\text{h}$ intervals), standardized to UTC interval-start indexing.
- **Composite Primary Key**: `(triplet_id, window_type, timestamp_utc)`
  - `triplet_id`: Unique identifier for the evaluation triplet (e.g., `TRIPLET_CONF_1_f5c700`).
  - `window_type`: Categorical evaluation context (`heatwave`, `matched_control`, `event_blind`).
  - `timestamp_utc`: ISO 8601 UTC timestamp (e.g., `2022-06-20T00:00:00Z`).
- **Original Public Hourly Dataset**: Exactly 1,440 rows:
  $$\text{4 triplets} \times \text{3 contexts} \times 120\,\text{hours} = 1,440\,\text{rows}$$
- **Important Demand Column Note**: In the v1 hourly benchmark (`p6_benchmark_hourly.parquet`), the balancing authority grid demand column is named **`demand_mw`** (measured in megawatts).

### 3.2 Track B2 California Multi-Station Extension

Track B2 expands the spatial domain to five California meteorological stations:
1. `SFO` (`USW00023234`): Northern coastal, CAISO hub `NP15`
2. `SAC` (`USW00023232`): Northern inland valley, CAISO hub `NP15`
3. `FAT` (`USW00093193`): Central inland valley, CAISO hub `ZP26`
4. `RDD` (`USW00024257`): Far-northern inland valley, CAISO hub `NP15`
5. `LAX` (`USW00023174`): Southern coastal, CAISO hub `SP15`

- **Catalogue Grain**: Event-level table (`data/v2/events/p12_b2_station_events.csv`, 25 rows) and regional episode table (`data/v2/events/p12_b2_regional_episodes.csv`, 15 rows).
  - Primary Key for station events: **`event_id`** (e.g., `B2_HW_SFO_20240702`)
  - Primary Key for regional episodes: **`regional_episode_id`** (e.g., `B2_EP_08`)
- **Hourly Extension Grain**: Hourly resolution across full evaluation windows ($120\,\text{h}$ to $312\,\text{h}$).
  - Composite Primary Key: `(event_id, timestamp_utc)`
  - **Important Demand Column Note**: In the B2 extension tables, grid demand is named **`demand_mwh`** (representing megawatt-hours per one-hour interval).
- **Simulation Matrix Grain**: Execution cell table (`data/v2/results/p12_b2_runs.parquet`, 6,480 rows).
  - Primary Key: **`run_id`** (6,480 unique deterministic SHA-256 derived strings).

---

## 4. Eligibility Flags, Exclusions, and Governance Semantics

Track B2 enforces explicit, machine-readable quality and eligibility flags across all events:

### 4.1 Weather vs. Joint-Evaluation Eligibility

- **`weather_eligibility_status`**: Indicates whether the physical meteorological observation strictly met the $P_{90}$ threshold for $\ge 3$ consecutive days without missing temperature gaps. All 25 catalogue events pass weather eligibility (`ELIGIBLE`).
- **`joint_evaluation_eligibility`**: Indicates whether an event possesses complete, synchronized data across all three required sources (weather + CAISO LMP + EIA carbon) and falls within the non-provisional historical window (2023–2025).
  - **Eligible**: Exactly 12 events across 2023–2025.
  - **Excluded**: Exactly 9 events from 2022.
  - **Provisional**: Exactly 4 events from 2026 (held pending complete full-calendar certification).

### 4.2 The 2022 Annual Joint-Source Gate Limitation

A crucial methodological nuance governs the exclusion of 2022 events:
- All nine 2022 station events are **authentic meteorological heatwaves** that fully satisfied weather screening.
- However, during initial data ingestion, a single unpopulated hourly interval was detected in the EIA-930 California grid feed on **`2022-06-13 at 17:00 UTC`**.
- Although this single missing hour occurred entirely outside the actual heatwave evaluation windows, the automated ingestion pipeline enforced a rigid annual-level joint-source completeness rule: any missing interval in a calendar year triggered complete exclusion of that entire year from joint grid evaluation.
- Consequently, all nine 2022 events were marked `EXCLUDED_ANNUAL_COVERAGE`. They remain in the catalogue as valid meteorological events, but were excluded from the joint simulation matrix.

---

## 5. Matched Controls and Ordinary Windows

To prevent confounding extreme temperature with seasonal or diurnal baselines, HeatTrace derives two distinct comparative reference structures:

### 5.1 Outcome-Blind Matched Controls

- **Selection Rule**: Each heatwave event is matched with a non-extreme window ($T_{\max} \le 22.0^\circ\mathrm{C}$) from the same warm-season pool, matched on day-of-week alignment, calendar proximity, and duration.
- **Single-Station v1**: 4 controls (120~h each). Note that 2022 confirmatory heatwaves were paired with June 2024 controls due to authentic historical data constraints (inter-annual limitation).
- **Multi-Station B2**: 12 matched controls corresponding to the 12 matrix events (`data/v2/tables/p12_b2_matched_controls.csv`).

### 5.2 Event-Blind Ordinary Windows & Overlap Limitation

- **Selection Rule**: To assess benchmark discriminability against ordinary operating conditions, B2 sampled 20 ordinary warm-season windows per matrix event (240 ordinary windows total).
- **Temporal Overlap Limitation**: An audit of window timestamps revealed that **146 of the 240 ordinary windows overlap with another selected window**, sharing up to 72 hours of identical weather and market data.
- **Statistical Consequence**: Ordinary windows are not independent samples. Statistical tests treating them as 240 independent draws commit a severe pseudo-replication fallacy.

---

## 6. Equal-Service Evaluation Gate

To ensure that reported cost or carbon differences represent genuine scheduling efficiency rather than work evasion, HeatTrace enforces a strict mathematical equal-service gate:

$$\text{Gate Passed} \iff S_{\mathrm{demanded}}(A) = S_{\mathrm{completed}}(A) = S_{\mathrm{completed}}(B)$$

- **v1 Confirmatory Matrix**: 530 of 540 pairwise deployable comparisons passed equal service (98.15%). All 10 rejections involved the non-deployable hindsight oracle under extreme $3.0\times$ load. **100% of deployable comparisons passed equal service.**
- **Track B2 Extension**: Under multi-station stress, **severe equal-service attrition occurred**. In the core-policy trio comparisons, **only 7 of 66 heatwave trios passed equal service (10.61%)**. Under $2.0\times$ and $3.0\times$ workloads, exactly **0 of 22 trios passed**. High-load cost and carbon comparisons are therefore invalid.

---

## 7. Data Formats and Public Links

Tracked public datasets can be inspected directly using standard tools:

- **Station Events Catalogue**: [`data/v2/events/p12_b2_station_events.csv`](../data/v2/events/p12_b2_station_events.csv)
- **Regional Episodes Catalogue**: [`data/v2/events/p12_b2_regional_episodes.csv`](../data/v2/events/p12_b2_regional_episodes.csv)
- **Hourly Phase Labels Preview**: [`data/v2/events/p12_b2_hourly_phase_labels_preview.csv`](../data/v2/events/p12_b2_hourly_phase_labels_preview.csv)
- **Original Triplet Index**: [`data/benchmarks/p6_event_control_index.csv`](../data/benchmarks/p6_event_control_index.csv)
- **Immutable Archive Manifest**: [`data/archive/heattrace_v1_d5b3c86/archive_manifest.json`](../data/archive/heattrace_v1_d5b3c86/archive_manifest.json)
- **Archive Self-Verifier**: [`data/archive/heattrace_v1_d5b3c86/verify_archive.py`](../data/archive/heattrace_v1_d5b3c86/verify_archive.py)
