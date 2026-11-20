# HeatTrace Documentation Hub

Welcome to the HeatTrace technical and scientific documentation directory. This index groups the repository's 57+ research documents by role, methodology, and lifecycle stage to facilitate navigation for researchers, peer reviewers, and evaluators.

---

## 1. Start Here (Core Documentation)

For a fast orientation to the project, start with these top-level guides:

- **[Repository Overview](../README.md)**: Main professor-facing entry point detailing research scope, datasets, H1–H5 findings, B2 extension audit, and execution boundaries.
- **[Dataset & Provenance Guide](dataset.md)**: Comprehensive schema definitions, record grains, primary keys, quality flags, eligibility rules, and public availability inventory.
- **[Research Claims & Evidence Map](heattrace_research_claims_and_evidence.md)**: Exhaustive claim-to-evidence matrix mapping every scientific assertion to machine-readable tables.
- **[Professor Presentation Brief](heattrace_professor_presentation_brief.md)**: High-level executive briefing, slide-by-slide narrative, and strategic review guide.
- **[Website & Presentation Source](heattrace_website_presentation_source.md)**: Content specifications and structure for the interactive web presentation.

---

## 2. Dataset and Provenance Specifications

Detailed engineering reports on data acquisition, time standardization, and environmental signal alignment:

- **[P2 Signal Alignment](p2_alignment.md)**: UTC interval-start standardization, station-local time interpretation, and cross-source synchronization.
- **[P3 Heatwave Detection](p3_heatwaves.md)**: Formulation and execution of the weather-only $P_{90}$ consecutive-day heatwave detection protocol.
- **[P4 Scheduling Metrics](p4_scheduling_metrics.md)**: Mathematical definitions of feasibility, power violations, equal-service constraints, and objective functions.
- **[P6 Thermal Methodology](p6_thermal_method.md)**: Formulation of the piecewise dry-bulb temperature $\to$ PUE $\to$ effective compute capacity coupling.
- **[Carbon Accounting Methodology](carbon_method.md)**: Analysis of EIA-930 production-average grid emissions and why marginal emissions differ.
- **[Contracts Specification](contracts.md)**: Interface contracts between data ingestion, forecasting, thermal modeling, and scheduling.
- **[Source Data Audit](source_audit.md)**: Initial audit of NOAA, CAISO, and EIA data availability and API access parameters.

---

## 3. Original Confirmatory Benchmark (v1 / Phase P6–P11)

The frozen, provenance-locked 3-event confirmatory study evaluating hypotheses H1 through H5:

- **[P6 Frozen Protocol](p6_frozen_protocol.md)**: The authoritative preregistered protocol governing the 756-cell confirmatory matrix.
- **[P6 Validity Report](p6_validity_report.md)**: Primary analysis report evaluating H1 through H5, boundary shifts, and policy separations.
- **[P6 Phase 9 Analysis Report](p6_phase9_analysis_report.md)**: Statistical aggregation across the confirmatory triplets and comparator cohorts.
- **[P6 Gate 1 Review](p6_gate1_review.md)** & **[P6 Pilot Review](p6_pilot_review.md)**: Preflight data validation and pilot simulation checks.
- **[P7 Freeze Readiness](p7_freeze_readiness.md)**: Verification of configuration immutability prior to final execution.
- **[P11 Final Results Audit](p11_final_results_audit.md)**: Definitive audit verifying the clean 756-cell re-execution, 44 scientific columns, and archive integrity.
- **[P11 v1 Reproduction Report](p11_v1_reproduction_report.md)**: Detailed report on the same-environment reproduction verification.
- **[P11 Reproducibility Status](heattrace_p11_reproducibility_status.md)**: Summary of reproducibility achievements and environmental limitations.
- **[v1 Preliminary Manuscript](heattrace_v1_preliminary_manuscript.md)**: Early manuscript draft documenting initial v1 findings.

---

## 4. Multi-Station California Extension (Track B2 / Phase P12)

Exploratory dataset expansion to five California climate zones (SFO, SAC, FAT, RDD, LAX) across 2022–2026:

- **[B2 Multi-Year Multi-Station Plan](p12_b2_multiyear_multistation_plan.md)**: Architectural proposal for the California multi-station expansion.
- **[B2 Frozen Protocol Draft](p12_b2_frozen_protocol_draft.md)**: Protocol draft governing the 6,480-cell matrix (note: marked `1.0-draft`).
- **[B2 Data Source Matrix](p12_b2_data_source_matrix.md)** & **[B2 CAISO Historical Access](p12_b2_caiso_historical_access.md)**: Station-hub mappings and OASIS acquisition scripts.
- **[B2 Experiment Matrix](p12_b2_experiment_matrix.md)**: Specification of the 12 matrix events and 540 cells per event.
- **[B2 Phase 2 Completion Report](p12_b2_phase2_completion.md)**: Acquisition and quality-control results for the five weather stations.
- **[B2 Phase 3 Completion Report](p12_b2_phase3_completion.md)**: Detection of 25 station events and 15 regional episodes.
- **[B2 Phase 4 Completion Report](p12_b2_phase4_completion.md)**: Matched control and ordinary window selection.
- **[B2 Phase 5 Completion Report](p12_b2_phase5_completion.md)**: Execution results for the 6,480 matrix cells (5,448 successes, 1,032 failures).
- **[B2 Phase 6 Completion Report](p12_b2_phase6_completion.md)**: Preliminary analysis of claims G1 through G5.
- **[B2 Risks and Fallbacks](p12_b2_risks_and_fallbacks.md)**: Risk register for missing data and model availability.
- **[B2 Workshop Submission Roadmap](p12_b2_workshop_submission_roadmap.md)**: Initial roadmap for workshop dissemination.

---

## 5. Scientific Audits, Defects, and Limitations

Crucial adversarial audits that diagnose methodological defects, protocol violations, and non-estimable claims:

- **[Stage 2 B2 Scientific Correctness Audit Report](../reproduction_audits/stage2_b2/stage2_scientific_correctness_report.md)**: The authoritative independent audit classifying Track B2 as **BLOCKED**, diagnosing unauthorized cross-station forecast transfer across 3,960 cells (61.1%), severe equal-service attrition (10.61% pass rate), and ordinary-window overlap.
- **[P5 Policy Diagnostic](p5_policy_diagnostic.md)**: Diagnostic investigation of initial policy anomalies under power-capping.
- **[P5.5 Findings Report](p5_5_findings_report.md)** & **[P5.5 Professor Briefing](p5_5_professor_briefing.md)**: Mid-project progress reviews.

---

## 6. Educational Learning Roadmap

A self-contained, 11-part pedagogical walkthrough designed for students, research assistants, and onboarding engineers:

- **[Learning Roadmap Overview](learning/README.md)**
- **[01. Research Foundations](learning/01_heattrace_research_foundations.md)**: Core motivation, extreme weather, and sustainable computing concepts.
- **[02. v1 vs. B2 Project History](learning/02_v1_vs_b2_history.md)**: Evolution from single-station v1 to multi-station B2.
- **[03. Repository Code Walkthrough](learning/03_repository_code_walkthrough.md)**: Architecture of `src/heattrace/` modules and execution runners.
- **[04. Datasets, CSV & Parquet Guide](learning/04_datasets_csv_parquet_guide.md)**: Deep dive into schema definitions and data files.
- **[05. Thermal, Scheduling & Forecasting Math](learning/05_thermal_scheduling_forecasting_math.md)**: Mathematical formulations of PUE, power caps, and LSTM forecasting.
- **[06. Schedulers & Algorithms](learning/06_schedulers_and_algorithms.md)**: Comparison of static, capacity-aware, full-thermal, and HeatGuard heuristics.
- **[07. Hypotheses, Results & Evidence](learning/07_hypotheses_results_evidence.md)**: Step-by-step breakdown of H1–H5 and G1–G5 findings.
- **[08. Figures & Diagrams Explained](learning/08_figures_diagrams_explained.md)**: Detailed explanations of all visual artifacts.
- **[09. Reproducibility & Audit Issues](learning/09_reproducibility_and_audit_issues.md)**: Lessons from the P11 reproduction and B2 adversarial audit.
- **[10. Presentation & Q&A Preparation](learning/10_professor_presentation_and_qa.md)**: Frequently asked questions and defensive presentation notes.
- **[11. Complete Learning Roadmap](learning/11_complete_learning_roadmap.md)**: Comprehensive study curriculum and review milestones.

---

## 7. Historical Planning and Superseded Records

*Note: These documents represent historical planning notes and phase roadmaps. They reflect earlier development milestones and must not be interpreted as the current repository state or final scientific consensus.*

- **[P11 External Reproduction Recovery Plan](p11_external_reproduction_recovery_plan.md)**: Contains historical Git status snapshots from Day 13; superseded by the [P11 Final Results Audit](p11_final_results_audit.md).
- **[14-Day Research Plan](heattrace-heatguard-14-day-plan.md)**: Original sprint plan outlining Phase 1 through Phase 14 milestones.
- **[P5 Experiments Plan](p5_experiments.md)**: Intermediate experiment execution schedule.
- **[Remaining Work Ledger](heattrace_remaining_work.md)**: Historical tracking of open items prior to Phase P11 freeze.
- **[Professor Quick Revision](heattrace_professor_quick_revision.md)**: Early revision summary.
- **[Website Prompt & Requirements](heattrace_antigravity_website_prompt.md)**: Original design prompt for the interactive presentation explorer.
- **[Complete Project Handoff](heattrace_complete_project_handoff.md)** & **[Complete Learning Guide](heattrace_complete_learning_guide.md)**: Early synthesis summaries.
