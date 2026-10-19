# Source audit

Status: P0 source audit complete on 17 October 2026. Acquisition smoke tests remain in P1.

## Frozen source choices

### NOAA weather

- Dataset: [Global Historical Climatology Network hourly (GHCNh)](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly). Official documentation: [NOAA GHCNh Documentation (PDF)](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf).
- Stations: `USW00023234` (San Francisco International), `USW00023232` (Sacramento Executive), and `USW00023174` (Los Angeles International).
- Variable: hourly air temperature (`temperature`), converted to degrees Celsius.
- Quality Code Policy:
  - GHCNh preserves component source QC flags across ~110 contributing global streams. Per `ghcnh_DOCUMENTATION.pdf`, quality codes are stream-dependent.
  - Accepted passing codes: `""` (unflagged / passed automated checks), `"1"` (passed manual/automated QC), `"5"` (passed/acceptable in USAF / global surface streams e.g. sources 313, 314, 343), `"A"` (passed/accepted in specialized streams), `"Passed"` / `"passed"`.
  - Rejected failed codes: `"2"` (suspect / failed temporal or spatial consistency), `"3"`, `"4"`, `"6"`, `"7"`, `"Failed"`, `"failed"`.
  - Unknown codes: any flag outside these verified sets is rejected with a validation error to prevent silently accepting unverified observations.
- Access: NOAA bulk station/year files in PSV via NODD AWS S3 open bucket (`noaa-ghcnh-pds`); file layout, variables, quality flags, and report types follow the official NCEI specification.
- Rationale: three fixed stations provide a simple northern coastal, northern inland, and southern coastal representation of the CAISO footprint.


### CAISO price

- Dataset: [CAISO OASIS](https://www.caiso.com/documents/oasisapispecification.pdf).
- Product: day-ahead hourly LMP at `TH_NP15_GEN-APND`.
- Unit: USD/MWh.
- Access: OASIS download interface/API; test one day before expanding requests.
- Note: the OASIS specification identifies hourly DAM LMP results for PNodes/APNodes and their energy, congestion, and loss components. The node is a representative benchmark signal, not a spatially precise data-center price.

### EIA demand and carbon

- Dataset: [EIA Form EIA-930 / Hourly Electric Grid Monitor](https://www.eia.gov/electricity/930-content/about.html).
- Geography: balancing authority `CISO`.
- Fields: demand (`D`), net generation (`NG`), generation by source, interchange (`TI`), and estimated CO₂ emissions and intensity.
- Preferred carbon field: estimated CO₂ intensity in gCO₂/kWh derived from EIA emissions and generation, with the exact derivation recorded in `docs/carbon_method.md`.
- Data availability across interfaces:
  - Demand and Net Generation: available via EIA API v2 endpoint `/electricity/rto/region-data/data` with repeated facet parameters `facets[type][]=D` and `facets[type][]=NG`.
  - Estimated CO₂ emissions and intensity: verified and ingested natively from official EIA CISO workbook (`data/raw/eia/CISO.xlsx`, SHA-256 `b418ea77...`, 97.6 MB) downloaded from the Hourly Electric Grid Monitor.
  - Workbook structure:
    - `Published Hourly Data`: hourly time series covering July 1, 2015 to October 18, 2026.
    - `Notes`: official column definitions, documentation, and unit specifications (MWh, metric tons, lbs/kWh).
    - `Known Data Issues`: hourly anomalous issue flags joined on BA + UTC time.
  - Timestamp semantics: Both API v2 `period` and Workbook `UTC time` / `Local time` follow the EIA-930 hour-ending reporting convention. Canonical interval-start UTC is mapped as $\text{timestamp\_utc} = \text{hour\_ending\_utc} - 1\text{ hour}$. For a requested half-open interval $[T_\text{start}, T_\text{end})$, the required EIA API query bounds are $\text{start} = T_\text{start} + 1\text{h}$ through $\text{end} = T_\text{end}$ inclusive.
- Note: EIA states that historical submissions are available from January 2019, which covers the 2022–2025 study period. Ingestion of both API v2 physical grid data and native Excel workbook carbon data is implemented and verified for 2024 percentile-defined extreme-heat (`2024-07-02`) and ordinary (`2024-06-07`) QC days. Native emissions status is `success_with_data_issues` due to Known Data Issues flags present across modern EIA balancing authority submissions, accepted for pipeline QC under an explicit ingestion-only policy. The former 2022 candidates remain documented as superseded candidates replaced due to CAISO's 39-month free API window.

## Accessibility and risk decisions

- NOAA: public bulk access is suitable; station-level coverage must be checked for every study year.
- CAISO: request throttling, caching, and a one-day smoke test are required. If the selected node/product is inaccessible, freeze a documented equivalent before analysis.
- EIA: public API/download access is suitable; historical revisions mean this is not automatically a point-in-time record of what an operator knew.
- Coverage, retrieval date, request parameters, and SHA-256 checksums will be recorded in `data/manifests/raw_sources.jsonl`.

Important limitation: the price node and balancing-authority carbon signal form a representative single-region benchmark, not a spatially precise data-center model.
