# HeatTrace v0 Data Contract

## Canonical hourly table

The aligned dataset uses one row per UTC interval start with interval-start semantics, sorted ascending by `timestamp_utc`. The initial technical evaluation table covers 48 hours (exactly 24 rows for extreme-heat QC day `2024-07-02` and 24 rows for ordinary-summer QC day `2024-06-07` in `America/Los_Angeles`).

### Canonical Schema and Column Specification

Deterministic column ordering in `data/processed/hourly_caiso_v0.parquet` and `data/processed/hourly_caiso_v0_sample.csv`:

| Column | Type | Unit / Meaning | Nullable | Source / Policy |
|---|---|---|---|---|
| `timestamp_utc` | `datetime64[ns, UTC]` | Timezone-aware UTC interval start | No | Canonical timeline |
| `qc_day_type` | `string` | QC window category (`heatwave` or `ordinary`) | No | Evaluation category |
| `local_date` | `string` | Local calendar date (`YYYY-MM-DD`) in `America/Los_Angeles` | No | QC reference date |
| `temperature_c` | `float64` | Hourly arithmetic mean temperature (°C) | Yes | NOAA GHCNh SFO (`USW00023234`) |
| `temperature_obs_count` | `int64` | Count of accepted NOAA observations in interval | No | NOAA GHCNh audit |
| `temperature_min_c` | `float64` | Minimum accepted observation in interval (°C) | Yes | NOAA GHCNh audit |
| `temperature_max_c` | `float64` | Maximum accepted observation in interval (°C) | Yes | NOAA GHCNh audit |
| `temperature_missing` | `bool` | Explicit missingness indicator for temperature | No | True if 0 valid observations |
| `price_usd_per_mwh` | `float64` | CAISO DAM total LMP (USD/MWh) | Yes | CAISO OASIS `TH_NP15_GEN-APND` |
| `price_missing` | `bool` | Explicit missingness indicator for price | No | True if price is missing/null |
| `demand_mw` | `float64` | Balancing authority demand (MW-equivalent average) | Yes | EIA-930 CISO (from workbook MWh) |
| `demand_missing` | `bool` | Explicit missingness indicator for demand | No | True if demand is null |
| `net_generation_mw` | `float64` | Net generation (MW-equivalent average) | Yes | EIA-930 CISO (from workbook MWh) |
| `net_generation_missing` | `bool` | Explicit missingness indicator for net generation | No | True if net generation is null |
| `carbon_g_per_kwh` | `float64` | Production-based generated carbon intensity (g CO₂/kWh) | Yes | EIA-930 canonical generated proxy |
| `carbon_missing` | `bool` | Explicit missingness indicator for carbon | No | True if carbon intensity is null |
| `carbon_data_issue` | `bool` | EIA Known Data Issues flag (`True` if flagged) | No | Preserved from EIA-930 workbook |
| `carbon_primary_analysis_eligible` | `bool` | Primary analysis eligibility (`False` if issue flagged) | No | P5 sensitivity requirement |
| `source_quality` | `string` | Combined record quality status | No | `success` or `success_with_data_issues` |
| `co2_emissions_generated_metric_tons` | `float64` | Native generated CO₂ emissions (metric tons) | Yes | EIA-930 CISO workbook |
| `co2_emissions_consumed_metric_tons` | `float64` | Native consumed CO₂ emissions (metric tons) | Yes | EIA-930 CISO workbook |
| `generated_intensity_lb_per_kwh` | `float64` | Native reported generated intensity (lb CO₂/kWh) | Yes | EIA-930 CISO workbook |
| `consumed_intensity_lb_per_kwh` | `float64` | Native reported consumed intensity (lb CO₂/kWh) | Yes | EIA-930 CISO workbook |
| `generated_intensity_g_per_kwh` | `float64` | Generated intensity converted to g CO₂/kWh | Yes | $1\text{ lb/kWh} = 453.59237\text{ g/kWh}$ |
| `consumed_intensity_g_per_kwh` | `float64` | Consumed intensity converted to g CO₂/kWh | Yes | $1\text{ lb/kWh} = 453.59237\text{ g/kWh}$ |
| `positive_generation_mwh` | `float64` | Sum of positive generation (MWh) | Yes | EIA-930 reconciliation denominator |
| `consumed_electricity_mwh` | `float64` | Electricity consumed (MWh) | Yes | EIA-930 consumed denominator |
| `eia_api_net_generation_mw` | `float64` | Net generation from EIA API v2 (MW) | Yes | EIA API v2 region-data comparison |
| `recalculated_generated_intensity_lb_per_kwh` | `float64` | Independently recalculated generated intensity (lb/kWh) | Yes | Recalculated from emissions & generation |
| `recalculated_generated_intensity_g_per_kwh` | `float64` | Independently recalculated generated intensity (g/kWh) | Yes | Recalculated converted to g/kWh |
| `generated_intensity_reconciliation_difference` | `float64` | Difference between recalculated and reported intensity | Yes | Tolerance limit: $\le 10^{-4}\text{ lb/kWh}$ |
| `eia_data_issue_flag` | `string` | Original EIA issue indicator string from workbook | No | Audit string |
| `source_station_id` | `string` | Weather station identifier (`USW00023234`) | No | Provenance |
| `source_caiso_node` | `string` | CAISO pricing node (`TH_NP15_GEN-APND`) | No | Provenance |
| `source_balancing_authority` | `string` | Balancing authority (`CISO`) | No | Provenance |

## Provider Alignment Rules

1. **NOAA GHCNh**:
   - Observations are reported at UTC times.
   - Quality policy: observations are filtered by `check_noaa_temperature_quality`. Accepted codes (`""`, `"1"`, `"5"`, `"A"`, `"Passed"`) are included; rejected or suspect codes are excluded.
   - Within-hour aggregation: observations falling in $[T, T+1\text{h})$ are averaged arithmetic mean into `temperature_c`. Count, min, and max are recorded.
   - Missingness: hours with zero valid observations set `temperature_missing = True` with null values. Observations are never interpolated across missing intervals.

2. **CAISO OASIS DAM LMP**:
   - Hourly interval starts match `INTERVALSTARTTIME_GMT`.
   - Duration is verified to be exactly 3600 seconds.
   - Negative prices are valid wholesale market signals and must never be converted to null or clipped to zero.

3. **EIA-930**:
   - API v2 hourly periods (`period`) use the EIA-930 hour-ending convention (e.g., period `2024-07-02T08` corresponds to the interval ending at 08:00 UTC).
   - Interval-start mapping: canonical interval-start is computed as $\text{timestamp\_utc} = \text{hour\_ending\_utc} - 1\text{ hour}$ (e.g., `2024-07-02T08` $\rightarrow$ `2024-07-02T07:00:00Z`).
   - Query semantics: for requested canonical interval $[T_\text{start}, T_\text{end})$, EIA API query bounds are $\text{start} = T_\text{start} + 1\text{h}$ through $\text{end} = T_\text{end}$ inclusive.
   - Canonical demand and net generation: `demand_mw` and `net_generation_mw` are sourced from the corrected EIA API v2 query. Workbook values are retained as `workbook_demand_mw` and `workbook_net_generation_mw` alongside explicit difference audit fields.
   - Workbook `UTC time` is hour-ending; interval start is mapped as $\text{UTC time} - 1\text{ hour}$, consistent with official EIA documentation.
   - Known Data Issues: rows flagged with `Data issue = 1` are retained with `carbon_data_issue = True`, `carbon_primary_analysis_eligible = False`, and `source_quality = "success_with_data_issues"`. They must never be discarded or silently treated as clean.

## Frozen Processing Settings

- Primary timestamp convention: UTC interval start (`timestamp_utc`).
- Local QC timezone: `America/Los_Angeles`.
- Study window: June–September, 2022–2025.
- Random seed: `20261016`.
- Missing observations remain flagged; unusual prices are not interpolated automatically.
- P1 single-day QC is distinct from the final P3 multi-day heatwave definition.
