# 11. Complete learning roadmap

| Step | Read and inspect | Prerequisite / difficulty | Exercise |
|---|---|---|---|
| 1. Questions/claims | `p6_frozen_protocol.md`, `p12_b2_protocol.yaml`, Chapters 1–2 | experimental design / easy | explain observed vs simulated in 60 seconds |
| 2. Evidence boundaries | `p6_validity_report.md`, Stage 2 report | validity / medium | classify five claims as supported/invalid/unestimable |
| 3. Provenance | protocol/event/window/execution manifests | hashing/freezes / medium | trace one hash from matrix to run row |
| 4. Ingestion | `ingest/noaa.py`, `caiso.py`, `eia.py`, B2 coverage | time series/units / medium | explain hour-start versus hour-ending |
| 5. Events | `p12_b2_events.py` functions | percentiles/graphs / medium | hand-detect an event and episode |
| 6. Windows | `B2Phase4Pipeline` matching/sampling | matching / medium | decode one control score and overlap component |
| 7. Workloads | `workload/generator.py`, `scaling.py` | scheduling basics / easy | verify demanded=completed+unfinished for one row |
| 8. Thermal model | `thermal/model.py`, `facility.py` | algebra / easy | compute PUE/capacity at 32°C |
| 9. Forecasting | `forecast/dataset.py`, `tiny_lstm.py`, `calibration.py` | ML/time leakage / hard | map each 24h previous-day target to history index |
| 10. Policies | `policy/greedy.py`, `thermal/scheduler.py`, `policies.py`, `heatguard.py` | greedy scheduling / hard | solve the four-hour example for six policies |
| 11. Runner | `p6_validity_runner.py`, `p12_b2_runner.py` | orchestration / hard | decode one run ID and follow each input lookup |
| 12. Matrix/results | B2 matrix/run Parquets, v1 canonical run table | pandas / medium | reproduce group counts read-only |
| 13. Analysis | `evaluation/p6_validity.py`, `p12_b2_validity.py` | statistics / hard | derive G1 +8.08h aggregation |
| 14. Figures | reporting/figure code and Chapter 8 | visualization / medium | give a 30-second caveated explanation of each B2 plot |
| 15. Presentation | Chapter 10 | synthesis / medium | answer the 30 questions without notes |

## First three files to master

1. `configs/p12_b2_protocol.yaml` — intended research contract.
2. `src/heattrace/thermal/model.py` — the physical abstraction all results depend on.
3. `src/heattrace/experiments/p12_b2_runner.py` — the actual operation, including where it diverges from the contract.

Then read `p12_b2_validity.py` and the Stage 2 audit together. The fastest route to real understanding is to compare intended protocol, implemented runner, and derived claim—not to memorize result tables in isolation.

## Final self-test

You understand HeatTrace when you can: derive PUE/capacity/cost/carbon units; distinguish a terminal SUCCESS from feasibility; explain why equal service matters; factor 756 and 6,480 without calling cells independent; locate the SFO transfer; state H1–H5 and G1–G5 with exact caveats; and present the strongest surviving claim without overstating causality or algorithmic novelty.

