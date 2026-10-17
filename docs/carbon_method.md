# Carbon method decision

The preferred carbon signal is a production-based CISO balancing-authority proxy from EIA-930 estimated CO₂ emissions and net generation. During P2, the implementation will preserve both source fields and calculate:

`carbon_g_per_kwh = estimated_co2_metric_tons * 1,000,000 / (net_generation_mwh * 1,000)`

The exact EIA field names, missing-value handling, and any unit conversion will be recorded after the first authentic sample is parsed. The signal is retrospective and may reflect revised historical submissions.
