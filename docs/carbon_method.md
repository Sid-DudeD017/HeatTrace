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
4. **P1 Phase Status**: Native EIA CISO workbook parsing and coverage validation are fully implemented and verified against `data/raw/eia/CISO.xlsx`. The current native emissions and carbon status is `success_with_data_issues` because all 48 hourly records across the two frozen QC days (`2022-06-01` and `2022-09-05`) have `Data issue = 1` in the authentic workbook. Ingestion of EIA API demand and net-generation live QC remains pending an available `EIA_API_KEY`. Consequently, final authentic end-to-end P1-QC remains pending. Under the default conservative policy (`fail_on_eia_data_issues: true`), final QC fails; running with `--no-fail-on-eia-data-issues` is an explicit research-policy override, not evidence that the underlying data issues disappeared.

The exact EIA field names and conversions are now verified from authentic data. The signal is retrospective and may reflect revised historical submissions.
