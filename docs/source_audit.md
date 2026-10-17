# Source audit

Status: initial decisions recorded; accessibility smoke tests pending.

The study starts with NOAA weather, CAISO day-ahead LMP, and EIA CISO demand/generation/emissions records. Coverage, retrieval date, request parameters, and SHA-256 checksums will be recorded in `data/manifests/raw_sources.jsonl`.

Important limitation: the price node and balancing-authority carbon signal form a representative single-region benchmark, not a spatially precise data-center model.
