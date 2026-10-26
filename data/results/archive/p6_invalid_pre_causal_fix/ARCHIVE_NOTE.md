# Archive Note: Invalid Pre-Causal-Fix Phase 6 Pilot Artifacts

Archived on: October 2026

These archived pilot artifacts were generated prior to critical causal boundary, fairness, and provenance repairs. They are preserved strictly for audit trail and provenance integrity and must NOT be cited or used as scientific evidence.

## Archived Artifacts & SHA-256 Hashes
- `p6_development_pilot.parquet`: `bcda381650a6be511044eb78f7f63d7440b66cbd4b768ce4041055f344014cca`
- `p6_forecast_metrics.csv`: `7006055fb9be85d0fe54e3e17ce2ed498e13b244402d60d510c57fcb0a45e558`
- `p6_pilot_review.md`: `3a30e0a276c9154db1bacb6f2bfbd34895211f78cc630f3b50cbdf79c0949352`

## Reason for Invalidation
1. **Causal Information Leakage & Unfair Rolling Comparison:** Core deployable policies (`static_unaware`, `capacity_aware`, `full_thermal_aware`) were executed once over a 120-hour forecast vector assembled from future rolling origins, rather than utilizing the same 24-hour horizon, 1-hour commitment rolling replan loop as HeatGuard.
2. **Workload Mutation:** The runner dropped `maximum_parallelism` prior to HeatGuard validation, altering the canonical workload schema.
3. **Unfiltered Confirmation Loading:** The benchmark parquet was loaded in full before filtering to `TRIPLET_DEV_ae821c`, violating read-time confirmation isolation.
4. **Weak Mutation Test:** The prior confirmatory mutation probe only exercised matrix enumeration rather than end-to-end dataset loading, forecasts, schedules, and metrics.
5. **Missing Config Validation & Provenance:** `configs/p6_validity.yaml` was not validated via `load_p6_validity_config`, and output rows lacked comprehensive configuration, input dataset, and workload hashes.
6. **Insecure Resume:** Resume logic only checked `run_id` without verifying schema or provenance hashes.
