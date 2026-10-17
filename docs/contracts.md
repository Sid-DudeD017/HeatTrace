# HeatTrace v0 Data Contract

## Canonical hourly table

The aligned dataset uses one row per UTC interval start and must include:

| Column | Type | Unit / meaning |
|---|---|---|
| `timestamp_utc` | timezone-aware datetime | UTC interval start |
| `temperature_c` | float | degrees Celsius |
| `price_usd_per_mwh` | float | day-ahead electricity price |
| `carbon_g_per_kwh` | float | production-based carbon proxy |
| `demand_mw` | float, nullable | balancing-authority demand |
| `source_quality` | string | source/QC status |

Provider timestamps and original interval conventions must be retained separately in staging data.
