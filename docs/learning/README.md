# HeatTrace educational walkthrough

This guide teaches the repository as it exists on 1 November 2026. It separates five kinds of evidence: observed NOAA/CAISO/EIA history; simulated workloads and facilities; executed scheduler results; conclusions independently rechecked by the Stage 2 audit; and reported claims that remain invalid, incomplete, or unverified.

## Recommended order

1. [Research foundations](01_heattrace_research_foundations.md)
2. [v1 and B2 history](02_v1_vs_b2_history.md)
3. [Repository and code walkthrough](03_repository_code_walkthrough.md)
4. [Dataset and artifact dictionary](04_datasets_csv_parquet_guide.md)
5. [Thermal, scheduling, and forecasting mathematics](05_thermal_scheduling_forecasting_math.md)
6. [Schedulers and algorithms](06_schedulers_and_algorithms.md)
7. [Hypotheses, results, and evidence](07_hypotheses_results_evidence.md)
8. [Figure catalogue](08_figures_diagrams_explained.md)
9. [Reproducibility and audit issues](09_reproducibility_and_audit_issues.md)
10. [Professor presentation and question bank](10_professor_presentation_and_qa.md)
11. [Complete learning roadmap](11_complete_learning_roadmap.md)

## Reading conventions

- **Observed** means historical measurements or market/grid records.
- **Modeled** means an assumption imposed by HeatTrace, such as PUE or a power cap.
- **Executed** means a row exists in the frozen result artifact.
- **Verified** means the Stage 2 report says it independently recalculated the value, or this walkthrough directly inspected the artifact.
- **Reported** means a project document says it, but it was not independently re-established here.
- **Protocol-invalid** means deterministic output exists but the method violated the frozen research contract.

The Stage 2 audit is an existing external report at `reproduction_audits/stage2_b2/stage2_scientific_correctness_report.md`; its conclusions are attributed rather than presented as newly discovered. No full simulation, model training, or result regeneration was performed for this guide.

