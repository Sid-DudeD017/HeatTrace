# Google Antigravity Build Prompt — HeatTrace Interactive Research Presentation

Copy everything below the horizontal rule into Google Antigravity.

---

## ROLE

You are a senior scientific-visualization architect, React/TypeScript frontend lead, accessibility specialist, and research-presentation designer.

Build a complete, polished, offline-capable interactive presentation website for a professor meeting about **HeatTrace v1 through P11 (Days 13–14)**. This is a scientific research-progress presentation, not a startup landing page, SaaS dashboard, product advertisement, or generic student portfolio.

The main presentation should take **8–10 minutes**, while expandable evidence panels and a separate technical appendix should support deeper questions.

## NON-NEGOTIABLE EVIDENCE BOUNDARY

1. Read the full source package first:
   - `docs/heattrace_website_presentation_source.md`
2. Verify critical claims against the repository artifacts listed below before encoding them.
3. Completed findings must always be labeled as **HeatTrace v1 through P11**.
4. The proposed **HeatTrace v2 Days 15–21** work must be visually and semantically separated from v1.
5. Every v2 experiment must visibly carry all three labels:
   - `PLANNED`
   - `NOT EXECUTED`
   - `NO RESULTS YET`
6. Do not invent results, charts, assets, percentages, projected carbon reductions, success probabilities, expected discoveries, or future claims.
7. Do not call production-average carbon-intensity differences “carbon savings,” “avoided emissions,” or marginal emissions.
8. Do not claim HeatGuard outperforms any baseline.
9. Do not imply forecast errors caused scheduling regret; that mechanism is not estimable from v1.
10. Do not claim strict ranking reversals; there were zero.
11. Do not claim phase-specific scheduling findings; phase labels exist, but phase-level scheduling outcomes were not retained.
12. Do not claim a clean-checkout or third-party-independent reproduction.
13. Do not describe HeatTrace as a faithful implementation of Ruparel’s formal DRO/battery framework.
14. Treat all computed facility quantities—PUE, cooling energy, effective capacity, and violations—as **simulated/model-derived**.

## SOURCE REPOSITORY AND OUTPUT ISOLATION

The HeatTrace repository is research evidence and must remain frozen. Do not install frontend dependencies into it and do not modify its code, data, figures, configurations, models, or results.

Create the website as a sibling project, not inside the research repository:

```text
../HeatTrace-Presentation/
```

If that directory already exists, stop and ask before overwriting it. Copy only the verified static values and approved figure assets needed by the presentation. Do not symlink to the source repository and do not load Parquet/large CSV research datasets in the browser.

## FILES TO INSPECT

Required content and evidence:

```text
docs/heattrace_website_presentation_source.md
docs/p6_validity_report.md
docs/p6_frozen_protocol.md
docs/p11_v1_reproduction_report.md
docs/p11_final_results_audit.md
docs/p7_freeze_readiness.md
docs/p6_thermal_method.md
docs/p4_scheduling_metrics.md
docs/carbon_method.md
data/results/p6_h1_h5_assessment.csv
data/results/p6_t2_event_feasibility.csv
data/results/p6_t3_equal_service_gaps.csv
data/results/p6_event_level_metrics.csv
data/results/p6_forecast_metrics.csv
data/results/p11_reproduction_comparison.json
data/benchmarks/p6_event_control_index.csv
data/events/heatwave_events_v0.parquet
data/benchmarks/p7_phase_label_overlay.parquet
```

Approved primary figures:

```text
data/figures/p6_f1_event_policy_contrasts.png
data/figures/p6_f4_h1_sensitivity.png
```

Approved optional development figures, only when visibly labeled `DEVELOPMENT / EXPLORATORY`:

```text
data/figures/p5_fig1_signal_distributions.png
data/figures/p5_fig2_signals_time_series.png
data/figures/p5_fig3_phase_behavior.png
data/figures/p5_fig4_lag_relationships.png
data/figures/p5_fig5_policy_performance.png
data/figures/p5_5_fig1_cost_carbon_pareto.svg
data/figures/p5_5_fig2_forecast_error_sensitivity.svg
data/figures/p5_5_fig3_workload_capacity_pressure.svg
data/figures/p5_5_fig4_feasibility_sla_heatmap.svg
data/figures/p5_5_fig5_event_vs_control.svg
data/figures/p5_5_fig6_comparator_optimality_gaps.svg
```

Do not present the Markdown status files `p6_f2_allocation_distance_status.md` or `p6_f3_forecast_regret_status.md` as charts. Convert their content into honest “not estimable” limitation cards.

## VERIFIED RECORD CORRECTIONS

- Use **24/36**, not the stale 23/36 value, for CONF_2 heatwave policy discriminability. The authoritative current sources are `data/results/p6_h1_h5_assessment.csv`, `data/results/p6_t3_equal_service_gaps.csv`, and the corrected P10 report.
- P11 did rerun all 756 cells from zero checkpoint state. The current report, execution log, and comparison JSON agree on this.
- Phrase P11 as a **same-environment reproduction** in the same repository/machine lineage.

## TECHNOLOGY AND PROJECT STRUCTURE

Use:

- React 18+
- TypeScript with strict mode
- Vite
- Tailwind CSS
- Recharts for verified numeric charts
- Lucide React for restrained interface icons
- KaTeX or a lightweight equivalent for equations
- Vitest + React Testing Library for unit/component tests
- Playwright for one compact presentation-flow smoke test if practical

The built site must run without external APIs and work offline after dependencies are installed. Do not use remote fonts, analytics, telemetry, external image CDNs, runtime data fetching, authentication, a database, or server-side functionality.

Use a structure close to:

```text
HeatTrace-Presentation/
├── public/
│   └── assets/
│       ├── p6_f1_event_policy_contrasts.png
│       └── p6_f4_h1_sensitivity.png
├── src/
│   ├── components/
│   │   ├── presentation/
│   │   ├── charts/
│   │   ├── architecture/
│   │   ├── thermal/
│   │   ├── roadmap/
│   │   └── evidence/
│   ├── data/
│   │   ├── events.ts
│   │   ├── results.ts
│   │   ├── forecasts.ts
│   │   ├── hypotheses.ts
│   │   ├── reproducibility.ts
│   │   ├── architecture.ts
│   │   ├── roadmap.ts
│   │   └── sources.ts
│   ├── hooks/
│   ├── lib/
│   ├── screens/
│   ├── styles/
│   ├── App.tsx
│   └── main.tsx
├── tests/
├── README.md
├── package.json
├── tsconfig.json
└── vite.config.ts
```

Static chart data must be typed and checked into `src/data/`. Every datum should have a source ID that resolves to a visible evidence citation.

## VISUAL DIRECTION

Create a polished research-laboratory aesthetic:

- Background: deep navy/near-black, not pure black.
- Primary heat accent: restrained amber/orange.
- Control/cool accent: cyan/blue.
- Neutral text: warm white and cool gray.
- Status colors: green for supported/passed, amber for partial/limited, red-orange for unsupported, slate for not estimable, violet only for future/planned work.
- Typography: locally available/system stack; technical but highly legible. Avoid remote font loading.
- Use a large projector-safe type scale and strong contrast.
- Favor scientific charts, precise annotations, clear whitespace and thin gridlines.
- Use gradients only as subtle atmospheric accents, not as the core visual language.
- Avoid glassmorphism, fake terminal effects, fake monitoring dashboards, neon overload, 3D globes, decorative particles and motion-heavy backgrounds.

Visual separation rules:

- All v1 screens carry a small persistent label: `HEATTRACE v1 · COMPLETED THROUGH P11`.
- Development-only content carries `DEVELOPMENT / EXPLORATORY`.
- Confirmatory content carries `FROZEN CONFIRMATION`.
- The final v2 screen changes the accent system to violet + dashed outlines and carries a persistent banner: `PROPOSED EXTENSION · NO EXPERIMENTS EXECUTED`.
- Never put v2 cards inside a v1 results chart or reuse v1 result colors as if v2 had outcomes.

## PRESENTATION SHELL AND NAVIGATION

Build ten main full-screen presentation sections. The tenth and final main section is the v2 roadmap. The technical appendix and Q&A are separate modes and do not extend the main progress count.

Required behavior:

- ArrowRight, ArrowDown and Space: next screen.
- ArrowLeft and ArrowUp: previous screen.
- Home: first screen.
- End: final v2 roadmap screen.
- `F`: enter/exit fullscreen using the Fullscreen API.
- `A`: open/close technical appendix.
- `Q`: open/close Professor Q&A.
- Escape: close modal/drawer/appendix first, then exit fullscreen if no overlay is open.
- Do not hijack arrow/space keys while focus is inside a slider, button menu, select, dialog or scrollable disclosure panel.
- Provide visible previous/next controls, a 1–10 progress indicator, a compact section menu, current screen title and fullscreen button.
- Update the URL hash for direct links such as `#results` and `#roadmap`; restore the correct screen on reload.
- Respect `prefers-reduced-motion` and provide near-instant transitions in reduced-motion mode.
- Keep focus management and ARIA labels correct.

Use restrained 180–280 ms opacity/translate transitions. No autoplay and no timed slide advancement.

## MAIN PRESENTATION SCREENS

### Screen 1 — Opening

Title: **HeatTrace**

Subtitle: **Evaluating Thermal Feasibility and Capacity Awareness under Historical Grid Stress**

Central question:

> Can complete historical heatwave evaluations reveal cloud-scheduling limitations that ordinary or event-blind windows miss?

Scope strip:

- Historical NOAA/CAISO/EIA signals
- Simulated facility thermals
- Synthetic deadline-constrained workloads
- Three-event frozen confirmatory case series
- HeatTrace v1 through P11

Include a subtle visual chain showing `Heat → PUE → Capacity → Scheduling`, explicitly labeled “modeled mechanism.”

### Screen 2 — Motivation and Ruparel Boundary

Explain in plain language:

- Flexible cloud workloads can shift across hours.
- Electricity prices and production carbon intensity vary by hour.
- Ambient heat can raise modeled cooling overhead and reduce IT capacity under a fixed facility cap.
- Complete-event benchmarking may reveal differences hidden by ordinary or arbitrary windows.

Show a two-column comparison with these boundaries:

| Feature | Ruparel reference | HeatTrace v1 |
|---|---|---|
| Objective | Geo-distributed multi-objective robust scheduling | Historical heatwave benchmark validity and modeled thermal feasibility |
| Forecasting | Regional price, carbon and renewable forecasts | SFO temperature; direct 24h TinyLSTM |
| Uncertainty | Moment/Wasserstein sets, DR chance constraints, CVaR | Empirical PUE residual margin; no formal guarantee |
| Optimization | Formal DRO and Benders decomposition | Greedy/repair heuristics and rolling replanning |
| Energy system | Battery and renewable components | No battery or renewable dispatch |
| Geography | Multiple regions/data centers | One CAISO-region case study |

Reference citation:

```text
Hardik Ruparel, “Carbon-aware scheduling and distributionally robust optimization for cloud systems: forecasting, battery storage, and adaptive ambiguity refinement,” Journal of Cloud Computing 15, article 84 (2026), DOI 10.1186/s13677-026-00904-7.
```

Use an explicit callout: **“Inspired by the problem setting; not a reproduction of the Ruparel optimizer.”**

### Screen 3 — Historical Data and Heatwave Events

Introduce four evidence sources:

- NOAA GHCNh, SFO station `USW00023234`.
- CAISO OASIS NP15 day-ahead total LMP, node `TH_NP15_GEN-APND`.
- EIA-930 CISO production-based carbon intensity.
- Synthetic cloud workload trace.

Show the weather-only rule:

```text
June–September daily maxima, 2022–2025
P90 = 25.60°C
Qualifying day: Tmax > 25.60°C
Heatwave: at least 3 consecutive qualifying days
```

Create an accessible event selector with four event cards. Selecting an event updates a detail panel. Use these exact values:

```ts
export const heatwaveEvents = [
  {
    id: "HW_20220620",
    role: "CONFIRMATORY",
    localStart: "2022-06-20",
    localEnd: "2022-06-22",
    rawStartUtc: "2022-06-20T07:00:00Z",
    rawEndUtc: "2022-06-23T07:00:00Z",
    durationHours: 72,
    peakDate: "2022-06-21",
    peakC: 36.7,
    meanDailyMaxC: 30.0333,
    cumulativeExceedanceCDays: 13.3
  },
  {
    id: "HW_20220904",
    role: "CONFIRMATORY",
    localStart: "2022-09-04",
    localEnd: "2022-09-08",
    rawStartUtc: "2022-09-04T07:00:00Z",
    rawEndUtc: "2022-09-09T07:00:00Z",
    durationHours: 120,
    peakDate: "2022-09-05",
    peakC: 35.6,
    meanDailyMaxC: 33.22,
    cumulativeExceedanceCDays: 38.1
  },
  {
    id: "HW_20220922",
    role: "CONFIRMATORY",
    localStart: "2022-09-22",
    localEnd: "2022-09-24",
    rawStartUtc: "2022-09-22T07:00:00Z",
    rawEndUtc: "2022-09-25T07:00:00Z",
    durationHours: 72,
    peakDate: "2022-09-24",
    peakC: 28.3,
    meanDailyMaxC: 27.4,
    cumulativeExceedanceCDays: 5.4
  },
  {
    id: "HW_20240702",
    role: "DEVELOPMENT",
    localStart: "2024-07-02",
    localEnd: "2024-07-04",
    rawStartUtc: "2024-07-02T07:00:00Z",
    rawEndUtc: "2024-07-05T07:00:00Z",
    durationHours: 72,
    peakDate: "2024-07-02",
    peakC: 31.1,
    meanDailyMaxC: 30.0,
    cumulativeExceedanceCDays: 13.2
  }
] as const;
```

Make the distinction between raw detected events and normalized 120-hour evaluation windows explicit.

### Screen 4 — Clickable End-to-End Architecture

Create a responsive SVG or DOM-based architecture diagram; do not use a static decorative image. Modules:

1. NOAA / CAISO / EIA ingestion
2. UTC alignment, QC and provenance
3. Weather-only event detection
4. Controls and event-blind window generation
5. TinyLSTM temperature forecasting
6. PUE and effective-capacity model
7. Synthetic workloads
8. Rolling schedulers
9. Realized scoring and equal-service analysis
10. P11 reproduction and archive

Selecting a module opens a side panel containing:

- purpose
- inputs
- outputs
- actual algorithm
- equation, where relevant
- evidence/source paths
- assumptions/limitations

Populate content from `docs/heattrace_website_presentation_source.md` Part B. Do not create fictitious services, queues, databases or ML systems.

### Screen 5 — Thermal Model Explorer

Build a genuinely functional calculator with:

- Temperature slider: sensible range 10–45°C; step 0.1.
- Requested IT allocation slider: 0–500 kW; step 1.
- Mode selector: energy-only / power-capped.
- Curve selector: low / medium. High may appear only in the appendix and must be labeled excluded from confirmation.
- Preset button: “Verified 32°C example” sets medium curve, power-capped, 32°C and 450 kW.

Frozen parameters:

```ts
const basePue = 1.20;
const thresholdC = 22.0;
const nominalItCapacityKw = 500.0;
const facilityCapKw = 600.0;
const curves = {
  low: { slopePerC: 0.010, maxPue: 1.45 },
  medium: { slopePerC: 0.020, maxPue: 1.70 }
};
```

Compute live:

```text
excessTemperature = max(temperatureC - 22, 0)
PUE = min(1.20 + slope × excessTemperature, maxPUE)
effectiveCapacityPowerCapped = min(500, 600 / PUE)
effectiveCapacityEnergyOnly = 500
facilityPower = requestedIT × PUE
coolingOverhead = requestedIT × (PUE - 1)
facilityExcess = max(facilityPower - 600, 0)
violatesCap = powerCapped && facilityExcess > 0.000001
```

Show the formula and substituted arithmetic. At the 32°C preset, display:

- PUE 1.40
- effective capacity 428.57 kW
- 450 kW requested IT
- facility power 630 kW
- modeled cooling overhead 180 kW for the one-hour example
- 30 kW facility-cap excess

Every output card must say `SIMULATED / MODEL-DERIVED`. The energy-only mode still uses PUE for facility energy but does not derate the nominal IT capacity.

### Screen 6 — Forecasting and Scheduling

Explain the TinyLSTM as a compact architecture strip:

```text
72 hourly observations × 5 features
→ one unidirectional LSTM layer, 32 hidden units
→ dropout 0.1
→ linear 32→24
→ direct 24-hour temperature forecast
```

Features: standardized temperature, sine/cosine hour of day, sine/cosine day of year.

Show a grouped RMSE comparison using these exact values:

```ts
export const forecastRmse = [
  { context: "Validation", lstm: 2.0739, previousDay: 2.3297, status: "DEVELOPMENT / VALIDATION" },
  { context: "Development heatwave", lstm: 5.8075, previousDay: 3.6948, status: "DEVELOPMENT" },
  { context: "Development control", lstm: 1.8744, previousDay: 2.5746, status: "DEVELOPMENT" },
  { context: "Development blind", lstm: 3.0177, previousDay: 1.8762, status: "DEVELOPMENT" }
] as const;
```

Add the validation nuance: TinyLSTM improved overall validation RMSE by 10.98%, but its extreme-underprediction MAE was 3.4291°C versus 3.2155°C for previous-day persistence. The gate passed through the overall-RMSE condition, not the extreme-underprediction condition.

Provide an interactive policy comparison table with rows:

- `static_unaware`
- `capacity_aware`
- `full_thermal_aware`
- `heatguard_calibrated`
- `heatguard_fixed`
- `oracle_full_thermal_aware`

Columns:

- temperature information
- capacity constraint
- objective
- margin
- rolling/deployable status
- measured v1 conclusion

Mark the oracle as `NON-DEPLOYABLE`. State that deployable thermal scheduling uses a 24-hour plan, commits one hour, and replans every hour.

Optional educational scheduling walkthrough: show a tiny illustrative job moving from an overloaded 32°C hour to a cooler feasible hour. Label it **ILLUSTRATIVE — NOT A RECONSTRUCTION OF A CONFIRMATORY SCHEDULE**.

### Screen 7 — Frozen Experimental Design

Show the three confirmatory triplets with precise 120-hour intervals. Use `data/benchmarks/p6_event_control_index.csv` as the source. Include a tabbed or segmented selector for CONF_1, CONF_2 and CONF_3.

Show frozen matrix arithmetic:

```ts
export const matrixCounts = [
  { cohort: "Core heatwave/control", count: 432 },
  { cohort: "Event-blind", count: 216 },
  { cohort: "Algorithm comparators", count: 72 },
  { cohort: "Oracle reference", count: 36 }
] as const;
```

Total: **756**.

Also show:

- facilities: energy-only and power-capped
- thermal curves: low and medium
- workloads: 1×, 2×, 3×
- seeds: `20261016`, `20261017`
- primary objective: carbon-first
- core policies: static, capacity-aware, full thermal

Use a prominent note:

> The independent confirmatory unit is the historical event/triplet (N=3). The 756 cells are repeated configurations, not 756 independent heatwaves.

### Screen 8 — Actual Scientific Results

This is the visual centerpiece. It must be the most legible and carefully annotated screen. Use three coordinated chart tabs or panels.

#### Chart A: Grid-bounded static feasibility

Use:

```ts
export const feasibilityEffects = [
  { event: "CONF_1", deltaLambda: -0.5 },
  { event: "CONF_2", deltaLambda: -0.5 },
  { event: "CONF_3", deltaLambda: 0.0 }
] as const;
```

Label the measure `heatwave − matched control tested boundary`. State the 1×/2×/3× workload grid and primary power-capped/medium/carbon-first condition. Do not imply a continuous physical threshold.

#### Chart B: Policy discriminability

Use grouped bars out of 36:

```ts
export const discriminability = [
  { event: "CONF_1", heatwave: 24, blind: 0, control: 24, denominator: 36 },
  { event: "CONF_2", heatwave: 24, blind: 0, control: 0, denominator: 36 },
  { event: "CONF_3", heatwave: 0, blind: 0, control: 0, denominator: 36 }
] as const;
```

State:

- 48 tie-to-non-tie transitions.
- 0 strict reversals across the 108 heatwave-versus-blind core-policy transitions.
- CONF_1 control discriminated as much as its heatwave; separation is not uniquely heatwave-specific.

#### Chart C: Equal-service cost and production-carbon-proxy gaps

Provide event and workload selectors. Keep the orientation visible at all times:

```text
gap = capacity_aware − full_thermal_aware
```

Use:

```ts
export const policyGaps = [
  { event: "CONF_1", load: 1, costUsd: -20.9615, carbonKg: -80.2420 },
  { event: "CONF_1", load: 2, costUsd: -41.92305, carbonKg: -160.4840 },
  { event: "CONF_1", load: 3, costUsd: -56.92145, carbonKg: -236.78865 },
  { event: "CONF_2", load: 1, costUsd: -188.38115, carbonKg: -20.63945 },
  { event: "CONF_2", load: 2, costUsd: -376.76220, carbonKg: -41.27890 },
  { event: "CONF_2", load: 3, costUsd: -371.13615, carbonKg: -66.67780 },
  { event: "CONF_3", load: 1, costUsd: 0.0, carbonKg: 0.0 },
  { event: "CONF_3", load: 2, costUsd: 0.0, carbonKg: 0.0 },
  { event: "CONF_3", load: 3, costUsd: 0.0, carbonKg: 0.0 }
] as const;
```

For negative values, use text such as “capacity-aware reported the lower value in this oriented comparison.” Never relabel these values as “HeatTrace savings.” Keep USD and kg CO2 on separate axes/panels; never add them into one composite score.

Include buttons to open the existing P6 figures in an accessible lightbox:

- `p6_f1_event_policy_contrasts.png`
- `p6_f4_h1_sensitivity.png`

Each chart must include:

- evidence status: `FROZEN CONFIRMATION · REPRODUCED IN P11`
- units
- exact source path
- a short limitation annotation
- an accessible table fallback

### Screen 9 — Negative Results, Hypotheses and Reproducibility

Use a compact H1–H5 matrix:

```ts
export const hypotheses = [
  {
    id: "H1",
    title: "Static feasibility",
    verdict: "SUPPORTED",
    evidence: "−0.5×, −0.5×, 0.0×; median −0.5×",
    limit: "N=3, coarse grid, simulated facility; low-curve sensitivity weak"
  },
  {
    id: "H2",
    title: "Capacity-awareness recovery",
    verdict: "PARTIALLY SUPPORTED",
    evidence: "Exact capacity-aware: 0.0× recovery and 0.0 h reduction. Full thermal: 1.0 h and 0.5 h violation reductions, but no boundary recovery.",
    limit: "Support comes only from the frozen OR rule’s violation branch"
  },
  {
    id: "H3",
    title: "Event-blind understatement",
    verdict: "PARTIALLY SUPPORTED",
    evidence: "24/36 vs 0/36 in CONF_1 and CONF_2; CONF_3 0/36; no strict reversals",
    limit: "CONF_1 control also discriminated 24/36"
  },
  {
    id: "H4",
    title: "Forecast mechanism attribution",
    verdict: "NOT ESTIMABLE",
    evidence: "No same-scheduler forecast intervention or hourly allocation vectors",
    limit: "Do not claim forecast-caused regret"
  },
  {
    id: "H5",
    title: "HeatGuard comparator",
    verdict: "NOT SUPPORTED",
    evidence: "Calibrated margin improved over both comparators in 0/3 events",
    limit: "Conditional on the frozen facility, margin and three events"
  }
] as const;
```

Add a negative-results strip:

- CONF_3 was null.
- Zero strict ranking reversals.
- No forecast-caused regret established.
- No consistent HeatGuard advantage.
- No phase-specific scheduler finding.
- Production carbon proxy is not marginal avoided emissions.

Show the P11 reproduction block:

```ts
export const reproduction = {
  rerunCells: 756,
  successes: 756,
  failures: 0,
  scientificDifferences: 0,
  comparedScientificColumns: 44,
  matchingResultTables: 7,
  matchingFigureOrStatusArtifacts: 4,
  archiveFilesVerified: 54,
  archiveFilesTotal: 54,
  environment: "Same machine/repository lineage",
  cleanCheckoutSimulation: false,
  rawSourceRebuild: false
} as const;
```

Make the distinction between deterministic same-environment reproduction and independent third-party reproduction visually obvious.

### Screen 10 — FINAL MAIN SCREEN: HeatTrace v2 Proposed Research Extension (Days 15–21)

This must be the final screen reached by normal presentation navigation and by the End key.

Title:

**HeatTrace v2: Proposed Research Extension (Days 15–21)**

Persistent status banner:

```text
PLANNED · NOT EXECUTED · NO RESULTS YET
```

Introductory boundary statement:

> The following experiments are proposals for professor feedback. They are separate from the completed HeatTrace v1 evidence and cannot change the verified P11 results shown earlier.

#### Three research-direction pillars

Create three selectable pillar cards above the timeline:

1. **Benchmark validity through representative ordinary-window sampling**
2. **Forecast-caused scheduling effects through controlled forecast substitution**
3. **Phase-aware and complete-event evaluation**

Selecting a pillar highlights the relevant days without hiding the others.

#### Chronological Days 15–21 roadmap

Render a left-to-right timeline on wide screens and a vertical timeline on smaller screens. Every day card must display `PLANNED`, `NOT EXECUTED`, and `NO RESULTS YET`. Clicking or pressing Enter/Space expands a full detail panel. Only one detail panel needs to be open at a time, but support opening multiple if implementation remains accessible and readable.

Each expanded detail must show exactly these six fields:

1. Research question
2. Current limitation motivating it
3. Proposed experimental method
4. Measurements to collect
5. What a positive result would establish
6. What a negative result would mean

Use the following content.

##### Day 15 — Freeze v2 and restore traceable phase semantics

- **Research question:** Can a separate v2 protocol preserve the immutable v1 baseline while producing the hourly evidence needed for phase and mechanism analysis?
- **Current limitation:** v1 has valid phase labels, but confirmatory output retains only cell-level outcomes and scalar allocation counts; dependencies and future v2 analysis are not yet frozen.
- **Proposed method:** Create a separately versioned v2 protocol and output namespace; bind it to the v1 archive; verify weather-only onset/peak/sustained/recovery labels through UTC conversion and 120-hour padding; specify hourly allocation, backlog, forecast-PUE, effective-capacity and outcome trace schemas before any new result is inspected.
- **Measurements:** Hashes and manifests; v1 byte-invariance; phase-label coverage/key integrity; hourly trace completeness; leakage and schema tests; zero overwritten v1 files.
- **Positive result would establish:** The extension is preregistered, isolated from v1 and technically capable of supporting the planned analyses.
- **Negative result would mean:** Do not execute v2 outcomes; repair provenance, phase propagation or trace completeness first. It would not alter any v1 conclusion.

##### Day 16 — Representative ordinary-window sampling

- **Research question:** Are the three selected matched controls and blind windows representative of ordinary historical conditions, or are v1 policy-separation conclusions sensitive to window choice?
- **Current limitation:** Each v1 event has only one matched control and one blind window; CONF_1’s control discriminated as much as the heatwave, and all confirmatory controls come from June 2024.
- **Proposed method:** Materialize the complete eligible pool before scheduling; retain approximately 20–30 distinct 120-hour ordinary windows per heatwave where available, or every valid window if fewer; apply frozen weather/calendar/data-quality rules; exclude heatwave/buffer overlap and missing-source windows; select without reading scheduler outcomes.
- **Measurements:** Candidate and retained counts; matching covariates/distances; years/seasons represented; coverage and quality flags; overlap exclusions; deterministic sampling IDs/seeds; pool completeness.
- **Positive result would establish:** A defensible, outcome-blind ordinary-window reference distribution for each event.
- **Negative result would mean:** Available history cannot support a representative comparison under the frozen rules; use all valid candidates, report the limitation, and do not search for a friendlier control pool.

##### Day 17 — Heatwave versus ordinary-window benchmark validity

- **Research question:** Do complete heatwaves produce stronger or qualitatively different policy discriminability than the frozen distribution of ordinary windows?
- **Current limitation:** v1 shows heatwave-versus-blind separation in two events, but one control discriminated equally and the third event was null.
- **Proposed method:** Run the unchanged core policies, workloads, thermal models and equal-service filters on the Day 16 frozen windows; compare each complete heatwave with its ordinary-window distribution; report events separately and treat ordinary windows as correlated robustness observations, not independent heatwave samples.
- **Measurements:** Equal-service cost/carbon-proxy gaps; feasibility boundaries; violation hours; detection rate of non-zero gaps; ties; strict reversals; heatwave percentile/rank within its ordinary-window distribution; per-event distributions.
- **Positive result would establish:** Under the frozen design, complete heatwave evaluation is more discriminating than representative ordinary-window benchmarking for specific events.
- **Negative result would mean:** Ordinary windows discriminate as often or more strongly; weaken or reject claims that heatwave event selection has superior benchmark value.

##### Day 18 — Controlled temperature-forecast substitution

- **Research question:** Does changing only the temperature forecast source change scheduling decisions under an otherwise identical thermal-aware scheduler?
- **Current limitation:** v1 has forecast-accuracy measurements but no controlled same-scheduler forecast arm and no hourly allocations, so forecast-caused regret is not estimable.
- **Proposed method:** Use the identical frozen full-thermal-aware scheduler with exactly three temperature inputs: frozen TinyLSTM, same-hour-previous-day persistence and a realized-temperature oracle marked non-deployable. Hold workload, price/carbon forecasts, facility parameters, objective, 24-hour horizon, one-hour commitment and all other inputs fixed. Do not retrain or tune models.
- **Measurements:** Hourly forecast temperature; forecast error by horizon; predicted PUE; predicted effective capacity; committed allocations; backlog; realized outcomes; arm-equality and future-leakage tests.
- **Positive result would establish:** Temperature information alone can change predicted capacity and scheduling decisions under the tested scheduler.
- **Negative result would mean:** Forecast sources differ in accuracy but do not materially change allocations under the tested conditions; forecast-mechanism support would remain absent.

##### Day 19 — Forecast-to-outcome mechanism analysis

- **Research question:** When forecast arms change decisions, do those changes produce equal-service differences in realized cost, production-carbon proxy, deadlines or facility violations?
- **Current limitation:** v1 cannot trace forecast → PUE/capacity → allocation → outcome and cannot calculate allocation distance.
- **Proposed method:** Analyze only the frozen Day 18 outputs; compare deployable arms separately from the non-deployable realized-temperature oracle; enforce identical completed work; calculate allocation distance from saved hourly vectors and connect forecast error to predicted-capacity and realized-outcome changes.
- **Measurements:** MAE/RMSE and extreme underprediction; normalized allocation distance; capacity-bound hours; backlog/deferred work; completed service; realized cost; production-carbon proxy; deadlines; facility violations; oracle gaps.
- **Positive result would establish:** A bounded forecast-caused scheduling mechanism under a controlled information intervention.
- **Negative result would mean:** Accuracy differences do not create material allocation or realized-outcome differences; H4 remains unsupported under tested conditions.

##### Day 20 — Phase-aware and complete-event evaluation

- **Research question:** Do onset, peak, sustained heat and recovery exhibit different scheduling risks, and does a complete multi-day event reveal accumulated effects missed by isolated-day evaluation?
- **Current limitation:** v1 stores phase labels but not phase-level scheduling traces; isolated-day comparisons could be unfair if they reset deadlines, workload exposure or cross-boundary state.
- **Proposed method:** Use only frozen weather-derived phases; summarize forecast error, modeled PUE/capacity, backlog, violations and equal-service outcomes by phase while treating phases as repeated segments within events. Only run the preregistered full-event versus isolated-peak/random-day ablation if equal hours, causal lookback, workload exposure, arrivals/deadlines and cross-boundary job state can be preserved.
- **Measurements:** Phase-level forecast error; PUE/effective capacity; backlog; deferred work; deadline and facility violations; service-normalized cost/carbon proxy; policy divergence; cumulative full-event outcomes; sequence-state integrity.
- **Positive result would establish:** Specific weather-defined phases or multi-day continuity carry descriptive scheduling information beyond an equal-exposure isolated-day view.
- **Negative result would mean:** Phase labels and event continuity do not materially distinguish scheduler behavior; phase analysis should remain supporting evidence, and an invalid isolated-day ablation must be deferred rather than forced.

##### Day 21 — Reproduce and adversarially audit v2

- **Research question:** Are the v2 extensions reproducible, provenance-complete and robust to adversarial claim checks without changing v1 evidence?
- **Current limitation:** New exploratory experiments can introduce selection bias, leakage, unequal service, hidden failures or accidental v1 mutation.
- **Proposed method:** Reproduce v2 in a clean versioned output directory; verify window provenance, stable IDs, explicit failure retention, forecast-arm isolation, hourly traces, weather-only phases, equal-service filters, tables/figures and hashes; adjudicate each research question as supported, limited, negative, not estimable or invalid.
- **Measurements:** Exact run-ID sets; success/failure counts; scientific-field differences; hash matches; selection/leakage probes; service exclusions; v1 archive invariance; regenerated-table/figure matches.
- **Positive result would establish:** The v2 evidence is mechanically reproducible and its claims remain within the frozen design.
- **Negative result would mean:** Mark affected experiments invalid or incomplete, preserve all nulls/failures, and do not update the verified v1 results.

#### Parallel independent-event replication track

Show a visually parallel branch beside or below Days 15–21, not as another completed day:

**Title:** Additional independent historical heatwave replication

**Status:** `PLANNED · NOT EXECUTED · NO RESULTS YET`

**Purpose:** Test whether the bounded v1 observations appear in additional, independently selected historical heatwaves without replacing the null v1 event.

**Eligibility boundary:** Candidates may include additional historical years such as 2020, 2021 or further 2024 periods only if NOAA temperature, CAISO price, EIA-930 carbon/demand data and complete causal forecast histories are available and pass the frozen data-quality contract.

**Selection rule:** Detect events from NOAA weather alone using a preregistered threshold/duration rule before inspecting prices, carbon signals, workloads or scheduler outcomes. Do not select events because they produce large policy gaps.

**Method:** Build a separate replication manifest and event/control/blind triplets; retain every eligible event; run the frozen scheduler comparison without retuning v1 parameters; report each event individually and keep the replication set separate from v1 confirmation and v2 mechanism experiments.

**Measurements:** Source coverage; event properties; matching diagnostics; feasibility effects; equal-service gaps; ties/reversals; null-event frequency; sensitivity to facility curves.

**Positive result would establish:** The bounded pattern is observed in additional independently selected cases, improving external case-series support.

**Negative result would mean:** The v1 pattern is event-specific or unstable; narrow the claim and preserve the additional null/contradictory cases.

#### Professor feedback panel

Place this at the bottom/end of the final screen and make it visually inviting but not editable or persistent. Present exactly these three questions:

1. **Should we prioritize benchmarking validity or forecast-related scheduling mechanisms?**
2. **Would adding more independent heatwaves improve the research more than adding realistic production workloads?**
3. **Is phase-aware event analysis a sufficiently interesting contribution, or should it remain supporting evidence?**

Each question can be clicked to reveal a concise “decision implications” note:

- Benchmark-validity priority → Days 16–17 first.
- Forecast-mechanism priority → Days 18–19 first, after Day 15 integrity work.
- Independent events versus workloads → case generalization versus workload realism.
- Phase-aware contribution → proceed as a core v2 question only if hourly trace integrity is available; otherwise keep it supporting evidence.

Do not store votes or imply a decision has been made. Add a small note: **“Discussion can change the proposed v2 protocol, but it does not change the verified v1 results.”**

## TECHNICAL APPENDIX MODE

Create a separate appendix drawer or route that is not part of the 1–10 main progress count. Organize it into tabs:

1. Equations and units
2. Data provenance and timestamp semantics
3. Exact triplet intervals
4. Workload and deadline rules
5. Policy definitions
6. Equal-service accounting
7. P11 reproduction limits
8. HeatTrace v2 methodology

The v2 methodology appendix should contain:

- ordinary-window eligibility and pseudo-replication warning
- controlled forecast-arm invariants
- required hourly trace schema
- phase definitions and repeated-segment interpretation
- isolated-day fairness requirements
- independent-event selection rule
- preregistration and stop/invalidation rules

Keep main slides concise; put methodological detail here rather than overloading the final roadmap screen.

## PROFESSOR Q&A MODE

Create a separate `Q` overlay with concise, evidence-grounded answers to likely questions:

- Is HeatTrace a Ruparel reproduction? No.
- Why SFO? It is the actual frozen NOAA station used in v1.
- Are violations observed failures? No, they are simulated facility-model violations.
- Why is N only three? Four detected events existed; one was development and three were sealed confirmation.
- Why do 756 runs not mean N=756? They are within-event configurations and seeds.
- Did HeatGuard win? No.
- Did the LSTM cause regret? Not estimable.
- Is carbon avoided emissions? No, it is an average production-based proxy.
- Was v1 independently reproduced? It was reproduced on the same machine/repository lineage, not by a third party or clean-checkout full simulation.
- Were phases analyzed? Labels were preserved, but phase-specific scheduler outcomes were not retained.

## EVIDENCE CITATION UX

Every chart, result card, equation and major methodological statement must have a compact source button. Activating it opens an evidence popover/drawer with:

- repository-relative source path
- evidence class: implementation / development / frozen confirmation / P11 reproduction / planned
- concise limitation

Do not use fake line numbers. Use actual paths. Provide a global Sources panel grouped by screen.

## ACCESSIBILITY AND RESPONSIVENESS

- WCAG AA contrast minimum.
- Semantic headings and landmarks.
- Fully keyboard-operable buttons, tabs, accordions, sliders, chart selectors, architecture modules and lightbox.
- Visible focus rings.
- Tooltips available via focus as well as hover.
- Accessible tables for every chart.
- Do not communicate status by color alone.
- Minimum projector-safe text size; avoid dense 12px labels.
- Support 1366×768, 1440×900, 1920×1080 and common laptop/mobile widths.
- On small screens, switch from full slide framing to readable vertical sections while preserving section navigation.
- Ensure expanded roadmap details are scrollable without advancing slides.

## DATA AND CLAIM-SAFETY TYPES

Use explicit TypeScript evidence metadata:

```ts
export type EvidenceClass =
  | "IMPLEMENTATION"
  | "DEVELOPMENT"
  | "FROZEN_CONFIRMATION"
  | "P11_REPRODUCTION"
  | "PLANNED";

export type FutureStatus = {
  planned: true;
  executed: false;
  resultsAvailable: false;
};

export type SourceRef = {
  id: string;
  path: string;
  evidenceClass: EvidenceClass;
  limitation?: string;
};
```

All v2 roadmap entries must use a `FutureStatus` object fixed to:

```ts
{ planned: true, executed: false, resultsAvailable: false }
```

Do not create numeric outcome fields for future experiments. This makes fabricated future results structurally harder to introduce.

## TESTS AND ACCEPTANCE CRITERIA

Implement and run tests for:

### Content integrity

- CONF_2 discriminability is 24/36.
- Feasibility effects are exactly −0.5, −0.5 and 0.0.
- Matrix counts sum to 756.
- P11 displays 756 successes, 0 failures and 0 scientific discrepancies.
- H1–H5 verdicts match the frozen table.
- “carbon savings,” “avoided emissions,” “HeatGuard outperforms,” and “756 independent” do not appear in rendered copy.
- Every v2 experiment displays PLANNED, NOT EXECUTED and NO RESULTS YET.
- No v2 experiment data structure contains outcome values.

### Interaction

- Keyboard next/previous/Home/End works.
- End navigates to the v2 roadmap.
- Fullscreen control calls the Fullscreen API and handles unsupported browsers gracefully.
- URL hashes restore sections.
- Architecture nodes open correct detail panels.
- Thermal calculations match the 32°C preset within rounding tolerance.
- Event selector updates all displayed event values.
- Result event/workload selectors show correct oriented gaps.
- Chart table fallbacks contain the same values as the visual charts.
- Roadmap accordions work by mouse and keyboard.
- Pillar selection highlights the correct roadmap days without hiding status labels.
- Appendix and Q&A open/close and restore focus.

### Build quality

- `npm run typecheck` passes.
- `npm test` passes.
- `npm run build` passes.
- No runtime console errors in the production build.
- No network requests are required at runtime.
- No source repository paths are accessed at runtime.
- All copied assets have descriptive alt text.

## README REQUIREMENTS

Write a README containing:

- project purpose and evidence boundary
- exact local install/run/build/test commands
- copied asset list and original repository-relative sources
- typed data-source map
- status/claim vocabulary
- keyboard shortcuts
- offline behavior
- how to update data safely without touching the frozen HeatTrace repository
- explicit note that v2 is proposed and has no results

## FINAL DELIVERY

Deliver the completed sibling project, not just mockups. Before finishing:

1. Confirm the HeatTrace research repository has not been modified.
2. Run typecheck, tests and production build.
3. Report the created project path.
4. Report build/test results.
5. List copied figure assets and their original source paths.
6. Summarize any deviations or verification limits.

The final experience should feel like a rigorous, modern scientific briefing: visually confident, interactive where interaction improves explanation, transparent about negative results, and structurally incapable of presenting the proposed v2 roadmap as completed research.
