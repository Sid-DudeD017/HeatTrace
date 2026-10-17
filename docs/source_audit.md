# Source audit

Status: P0 source audit complete on 17 October 2026. Acquisition smoke tests remain in P1.

## Frozen source choices

### NOAA weather

- Dataset: [Global Historical Climatology Network hourly (GHCNh)](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly).
- Stations: `USW00023234` (San Francisco International), `USW00023232` (Sacramento Executive), and `USW00023174` (Los Angeles International).
- Variable: hourly air temperature, converted to degrees Celsius.
- Access: NOAA bulk station/year files in PSV or Parquet; the current GHCNh documentation describes the station list, file layout, variables, and quality flags.
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
- Fields: demand, net generation, generation by source, interchange, and estimated CO₂ emissions where available.
- Preferred carbon field: estimated CO₂ intensity in gCO₂/kWh derived from EIA emissions and generation, with the exact derivation recorded in `docs/carbon_method.md` during P2.
- Note: EIA states that historical submissions are available from January 2019, which covers the 2022–2025 study period. The emissions estimate depends on the accuracy of BA-reported generation and interchange.

## Accessibility and risk decisions

- NOAA: public bulk access is suitable; station-level coverage must be checked for every study year.
- CAISO: request throttling, caching, and a one-day smoke test are required. If the selected node/product is inaccessible, freeze a documented equivalent before analysis.
- EIA: public API/download access is suitable; historical revisions mean this is not automatically a point-in-time record of what an operator knew.
- Coverage, retrieval date, request parameters, and SHA-256 checksums will be recorded in `data/manifests/raw_sources.jsonl`.

Important limitation: the price node and balancing-authority carbon signal form a representative single-region benchmark, not a spatially precise data-center model.
