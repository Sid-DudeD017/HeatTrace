# Carbon method decision

The preferred carbon signal is a production-based CISO balancing-authority proxy from EIA-930 estimated CO₂ emissions and net generation. During P2, the implementation will preserve both source fields and calculate:

`carbon_g_per_kwh = estimated_co2_metric_tons * 1,000,000 / (net_generation_mwh * 1,000)`

### EIA-930 Emissions Data Source Investigation & Authentic Workbook Verification

Official investigation of EIA Form EIA-930 and the Hourly Electric Grid Monitor establishes:
1. **API v2 Scope**: The official EIA API v2 routes (`/electricity/rto/region-data`, `/electricity/rto/fuel-type-data`, `/electricity/rto/interchange-data`, `/electricity/rto/region-sub-ba-data`) expose physical grid metrics (demand `D`, demand forecast `DF`, net generation `NG`, total interchange `TI`, and generation by energy source), but do **not** publish hourly estimated CO₂ emissions directly.
2. **Official Access Mechanism via Hourly Electric Grid Monitor**: Official EIA-930 documentation indicates that hourly CO₂ emissions data are published as part of balancing-authority workbooks downloadable from the EIA Hourly Electric Grid Monitor:
   - Navigation path: [EIA Hourly Electric Grid Monitor](https://www.eia.gov/electricity/gridmonitor/) -> **Download Data** -> **Balancing Authority/Regional Files** -> select balancing authority `CISO`.
   - Verified Workbook: An authentic official CISO workbook is available at `data/raw/eia/CISO.xlsx` (97,607,203 bytes, SHA-256 `b418ea77f536048e11fe0c5786de7544dfa7c774a90083e7f2c0d9facc74ce50`).
   - Worksheets:
     - `Published Hourly Data`: Historical hourly time series covering July 1, 2015 through October 18, 2026.
     - `Notes`: Official column definitions, metadata, and unit descriptions.
     - `Known Data Issues`: Data issue flags joined on BA and hour-ending UTC time.
   - Reporting convention: `UTC time` and `Local time` are hour-ending. The canonical interval-start UTC is $\text{UTC time} - 1\text{ hour}$.
   - Native units:
     - Demand and net generation: MWh.
     - CO₂ emissions (`CO2 Emissions Generated`, `CO2 Emissions Consumed`): metric tons.
     - CO₂ intensity (`CO2 Emissions Intensity for Generated Electricity`, `CO2 Emissions Intensity for Consumed Electricity`): lbs CO₂/kWh.
   - Intensity conversions & reconciliation:
     - $1\text{ lb/kWh} = 453.59237\text{ g/kWh}$.
     - Generated intensity reconciles via $(\text{CO2 Emissions Generated} \times 2204.62262185) / (\text{Positive Generation} \times 1000)$.
     - Consumed intensity reconciles via $(\text{CO2 Emissions Consumed} \times 2204.62262185) / (\text{Consumed Electricity} \times 1000)$.
3. **Staging CSV Fallback Contract**:
   - In addition to native Excel workbook ingestion (`--eia-emissions-workbook`), an explicit intermediate HeatTrace staging CSV contract remains supported via `--eia-emissions-file`:
     - Mandatory columns: `balancing_authority`, `timestamp`, `co2_value`, `co2_unit`.
     - Optional columns: `timezone` (required if timestamp is naive), `fold` (required for ambiguous local timestamps during fall-back DST transitions).
     - Allowed units: `metric_tons`, `mt`, `metric_tonnes`, `short_tons`, `st`.
4. **P1 Phase Status**: Native EIA CISO workbook parsing and coverage validation are fully implemented and verified against `data/raw/eia/CISO.xlsx` alongside live EIA API v2 demand and net-generation retrieval. For P1-QC, the candidate dates are the 2024 percentile-defined extreme-heat day (`2024-07-02`) and ordinary summer day (`2024-06-07`). The native emissions status is `success_with_data_issues`: all 24 hours on each QC day carry `Data issue = 1` in `CISO.xlsx` (an empirical condition spanning 93% of modern hours in the workbook). Under the explicit ingestion-only QC policy (`fail_on_eia_data_issues: false`), pipeline QC passes. Downstream scientific analysis (P2/P5) must retain these issue flags and perform sensitivity analysis. The original 2022 candidates (`2022-09-05` and `2022-06-01`) remain documented in project history as superseded candidates replaced due to CAISO's 39-month free API window.

The exact EIA field names and conversions are now verified from authentic data. The signal is retrospective and may reflect revised historical submissions.
