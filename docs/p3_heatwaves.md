# HeatTrace P3: Multi-Day Heatwave Detection and Phase Labeling (Person A)

This document specifies the deterministic methodology, operational execution, and output contracts for HeatTrace Phase P3 Person A responsibilities:
- **P3-01**: Final deterministic multi-day heatwave detection and phase labeling.
- **P3-02**: Event, coverage, timestamp, and phase-assignment validation.

> [!NOTE]
> Scope boundary: This phase implements Person A's event catalogue and hourly phase labels only. Person B (matched controls P3-03/04) and Person C (data curation P3-05/06) remain assigned separately. Gate G3-a remains pending downstream integration.

---

## 1. Meteorological Threshold and Baseline

### Station and Geographic Context
- **NOAA Station**: SFO International Airport (`USW00023234`)
- **Local Reference Timezone**: `America/Los_Angeles`
- **Analysis Baseline**: Warm-season months (June, July, August, September) across 2022, 2023, 2024, and 2025.

### Quality and Deduping Policy
Observations are parsed strictly using the project's authoritative NOAA quality policy:
- Quality codes in `NOAA_ACCEPTED_QUALITY_CODES` (`""`, `"1"`, `"5"`, `"A"`, `"Passed"`) are accepted. Suspect codes are excluded.
- Hourly observations are aggregated using `extract_daily_maxima` grouped by `America/Los_Angeles` calendar days (never assuming UTC for meteorological diurnal heating cycles).
- Duplicate timestamps are resolved deterministically using aviation METAR/SPECI priority (`FM15` > `FM16` > `FM12`), tie-breaking on maximum temperature.
- Missing days remain missing; weather data are never interpolated for primary event detection.

### Empirical 90th Percentile Threshold
- **Total Valid Warm-Season Days**: $N = 485$ days across 2022–2025.
  - 2022: 122 days
  - 2023: 122 days
  - 2024: 122 days
  - 2025: 119 days (missing Aug 30–Sep 1)
- **Method**: Linear interpolation percentile ranking:
  $$k = (N - 1) \times 0.90 = (485 - 1) \times 0.90 = 435.6$$
- **Threshold Value**:
  - Exact float: $25.600000000000005^\circ\text{C}$
  - Display value: **$25.60^\circ\text{C}$** ($78.08^\circ\text{F}$)
  - Full internal precision is preserved during calculations.

---

## 2. Deterministic Heatwave Event Criteria

1. **Qualifying Day**:
   A local calendar day where:
   $$\text{daily\_max\_temperature\_c} > P_{90}\text{ threshold} \quad (25.60^\circ\text{C})$$
   (Strictly greater than; equal values do not qualify).

2. **Event Run**:
   A maximal run of $\ge 3$ consecutive qualifying days.
   - Any day with $\le P_{90}$ or missing observation terminates the run.
   - Longer runs form a single contiguous event (e.g., 5-day event).

3. **Event Identifier**:
   `HW_YYYYMMDD` formatted from the local calendar start date.

4. **Peak Day Selection**:
   The qualifying day within the event with the highest daily maximum temperature. Ties break to the earliest calendar date.

---

## 3. Detected Authentic Heatwave Events (2022–2025)

Four multi-day heatwave events meet the criteria:

| Event ID | Start Date | End Date | Duration (Days) | Duration (Hours) | Peak Date | Peak Max (°C) | Mean Max (°C) | Cum Exceed (°C·days) |
|---|---|---|---|---|---|---|---|---|
| `HW_20220620` | 2022-06-20 | 2022-06-22 | 3 | 72 | 2022-06-21 | 36.7 | 30.03 | 13.30 |
| `HW_20220904` | 2022-09-04 | 2022-09-08 | 5 | 120 | 2022-09-05 | 35.6 | 33.22 | 38.10 |
| `HW_20220922` | 2022-09-22 | 2022-09-24 | 3 | 72 | 2022-09-24 | 28.3 | 27.40 | 5.40 |
| `HW_20240702` | 2024-07-02 | 2024-07-04 | 3 | 72 | 2024-07-02 | 31.1 | 30.00 | 13.20 |

- **Total Event Days**: 14 days
- **Total Event Hours**: 336 hours

> [!NOTE]
> Event `HW_20220904` captures the historic early-September 2022 California heatwave that drove CAISO electricity demand to record highs and prompted statewide grid alerts.
>
> The P1 single-day QC check (`2024-07-02`) falls on the peak day of the 3-day event `HW_20240702`.

---

## 4. Hourly Phase Definitions and Buffer Spacing

Each heatwave event generates four chronological phases:

1. **`onset`**: The full local day ($T_\text{start} - 1\text{ day}$) immediately preceding the event (24 hours).
2. **`sustained`**: Qualifying event days preceding or following the peak day.
3. **`peak`**: The full 24 hours of the designated peak local day (`peak_local_date`).
4. **`recovery`**: The full local day ($T_\text{end} + 1\text{ day}$) immediately following the event (24 hours).

### Phase Hour Summary
Across the 4 detected events (total 22 distinct local days):
- `onset`: 96 hours (4 events $\times$ 24 hours)
- `sustained`: 240 hours (10 days $\times$ 24 hours)
- `peak`: 96 hours (4 events $\times$ 24 hours)
- `recovery`: 96 hours (4 events $\times$ 24 hours)
- **Total Labeled Hours**: 528 hours

### Phase Collision Verification
- `HW_20220620` recovery ends `2022-06-23T07:00Z`; next onset begins `2022-09-03T07:00Z` (gap: 72 days).
- `HW_20220904` recovery ends `2022-09-09T07:00Z`; next onset begins `2022-09-21T07:00Z` (gap: 12 days).
- `HW_20220922` recovery ends `2022-09-25T07:00Z`; next onset begins `2024-07-01T07:00Z` (gap: 645 days).
- **Result**: Zero buffer overlap exists across all events in the authentic 2022–2025 dataset.

---

## 5. Artifacts and CLI Commands

### Generated Artifacts
1. `data/events/heatwave_events_v0.parquet`: Canonical event catalogue table.
2. `data/events/heatwave_events_v0.csv`: Canonical event catalogue CSV.
3. `data/events/hourly_event_labels_v0.parquet`: Hourly phase assignment table.
4. `data/events/hourly_event_labels_v0_sample.csv`: Sample of hourly phase labels (first/last 20 rows).
5. `data/manifests/event_coverage.csv`: Event coverage summary table with phase hour totals.
6. `data/manifests/event_catalogue_manifest.json`: Provenance manifest recording SHA-256 hashes of inputs and outputs.

### CLI Instructions
- Build the heatwave catalogue and hourly phase labels:
  ```bash
  python -m heattrace.cli --build-events
  ```
- Inspect and summarize detected events and phase breakdown:
  ```bash
  python -m heattrace.cli --inspect-events
  ```

---

## 6. Limitations of 4-Year Baseline
The empirical 90th percentile was derived from pooled warm seasons across 2022–2025 ($N = 485$ days). In formal climatological research (e.g., WMO guidelines), percentile baselines typically rely on a 30-year climate normal (e.g., 1991–2020). Using a 4-year local baseline serves as an empirical threshold specifically calibrated for the CAISO study window. Any future historical expansion should document sensitivity against a multi-decadal normal.
