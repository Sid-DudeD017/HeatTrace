# HeatTrace Dataset-Paper Figure Sources and Provenance

| Figure | Manuscript source | Evidence origin | SHA-256 | Scientific boundary |
|---|---|---|---|---|
| Figure 1 | LaTeX-native diagram in `paper/main.tex` | Derived from inspected ingestion, processing, catalogue, workload, thermal, and evaluation modules | Included in source hash | Conceptual lifecycle only; aligned light-blue, light-green, and light-orange vector boxes distinguish external observations, HeatTrace records, and benchmark evaluation. |
| Figure 2 | `paper/figures/fig1_signals_time_series.png` | `data/figures/p5_fig2_signals_time_series.png` | `489d4fe943fdc42e06a2dbbb3bac9c7db8175281235477b513c13a8816323f7d` | Illustrative July 2024 development event/control pair; excluded from confirmatory inference. |
| Figure 3 | `paper/figures/diag2_thermal_model.png` | Derived from `configs/p6_thermal.yaml` and `src/heattrace/thermal/model.py` | `05dc1eeb950b57ba132182f03481ebc5a6b5046ef8c5d6fed84c546e01192b02` | Synthetic temperature--PUE--capacity sensitivity, not measured facility physics. |
| Figure 4 | `paper/figures/fig2_h1_sensitivity.png` | `data/archive/heattrace_v1_d5b3c86/canonical_analysis/figures/p6_f4_h1_sensitivity.png` | `247a97f2ba3c6b050bf69454d3b5da73811538d20efb74f60f81a377a064af4d` | Primary evidence; caption now identifies boundary differences, equal-service gaps, no strict policy reversal, and $N=3$ independent events. |

## Selection changes

- The historical signal figure was restored because the dataset paper needs a concrete example of aligned event/control records.
- The narrow exploratory multi-station result figure was removed; the extension is now summarized in a catalogue/audit table so incomplete experimental conclusions do not dominate the dataset narrative.
- The matrix and extension architecture diagrams remain excluded because compact tables convey the verified information more legibly.

Legacy images remain in `paper/figures/` for provenance but are not referenced by the final manuscript or included in the flat submission bundle.
