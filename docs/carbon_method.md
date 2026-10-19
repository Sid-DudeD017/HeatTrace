# Carbon Method Decision

## Preferred Carbon Signal

The canonical production-based carbon intensity signal for CAISO (balancing authority `CISO`) is constructed directly from the official EIA-930 balancing authority workbook (`data/raw/eia/CISO.xlsx`), specifically the field:

```
CO2 Emissions Intensity for Generated Electricity
```

The canonical metric unit in HeatTrace is grams of CO₂ per kilowatt-hour ($\text{g CO}_2/\text{kWh}$). It is converted using the exact physical constant:

$$\text{carbon\_g\_per\_kwh} = \text{generated\_intensity\_lb\_per\_kwh} \times 453.59237$$

## Official Workbook vs. EIA API Reconciliation

Crucially, HeatTrace does **not** silently compute the canonical intensity signal by dividing total workbook emissions by EIA API net generation (`NG`).

1. **Workbook Positive Generation vs. API Net Generation**:
   The EIA-930 workbook intensity calculation reconciles against `Positive Generation`, not API `Net Generation`. In grids with utility storage charging, pumped storage, or station service, gross positive generation exceeds net generation (e.g. on 2024-07-02T07, workbook positive generation is 22,149 MWh whereas net generation is 22,150 MWh).
2. **Reported Generated Intensity**:
   Reported in the workbook in lbs CO₂/kWh and converted directly to g CO₂/kWh.
3. **Independently Recalculated Validation Value**:
   Recomputed to independently verify the workbook formula:
   $$\text{recalculated\_generated\_intensity\_lb\_per\_kwh} = \frac{\text{co2\_emissions\_generated\_metric\_tons} \times 2204.62262185}{\text{positive\_generation\_mwh} \times 1000}$$
   HeatTrace validates that:
   $$|\text{recalculated} - \text{reported}| \le 10^{-4}\text{ lb/kWh}$$
   Across all 48 hours of the initial aligned dataset, the maximum observed difference is $6.58 \times 10^{-7}\text{ lb/kWh}$, well within tolerance.
4. **Generated vs. Consumed Intensity**:
   - `generated_intensity_g_per_kwh` reflects electricity produced inside the CISO balancing authority.
   - `consumed_intensity_g_per_kwh` accounts for imported and exported electricity flows across interties.
   Both fields are retained for scientific audit, with generated intensity chosen as the primary production-based signal.
5. **Retrospective and Revised Nature of EIA Data**:
   The EIA-930 Hourly Electric Grid Monitor workbooks are revised periodically by balancing authorities to reconcile telemetry, interchange meters, and settlement data. Consequently, historical workbook values represent retrospective, post-audit best estimates rather than unadjusted real-time telemetry.

## EIA Known Data Issues Policy

In `data/raw/eia/CISO.xlsx`, the sheet `Known Data Issues` records data flags. Across modern balancing authorities, substantial fractions of hours carry flags (e.g. all 24 hours on both 2024-07-02 and 2024-06-07 carry `Data issue = 1`).

HeatTrace strictly enforces the following policy:
- Flagged rows must **never** be silently dropped or deleted.
- Flagged rows must **never** have their carbon intensities replaced with null.
- Flagged rows are explicitly marked:
  - `carbon_data_issue = True`
  - `carbon_primary_analysis_eligible = False`
  - `source_quality = "success_with_data_issues"`
- Flagged observations are never described as "clean".
- Downstream statistical modeling (Phase P5) must execute sensitivity analyses comparing results with and without these flagged hours.
