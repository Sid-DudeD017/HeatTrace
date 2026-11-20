# HeatTrace Dataset-Paper Reframing Audit

Audit date: 2026-11-20 (Asia/Kolkata).

## Starting manuscript

- Source: `paper/main.tex`; compiled artifact: `paper/main.pdf`.
- Starting length: 14 pages total, with 12 manuscript pages and References on pages 13--14.
- Starting emphasis: benchmark experiments and policy comparisons dominate the section hierarchy; dataset construction is concentrated in one section and one table.
- Reader-facing development identifiers occur repeatedly (`v1`, `P11`, `Track B2`, `B2`). These should be replaced with scientific descriptions while exact artifact names remain in evidence records.

## Verified constructed datasets and artifacts

### Original single-station California benchmark

- Public measurements: NOAA GHCNh hourly weather at SFO (`USW00023234`), CAISO OASIS day-ahead NP15 locational marginal price, and EIA-930 CISO demand, generation, emissions, and production-average carbon-intensity fields.
- Derived HeatTrace artifacts: aligned hourly tables; weather-only heatwave labels; control catalogue; event-blind window pool; four event/control/blind triplets; phase overlays; frozen manifests; experiment results; and archive/reproduction comparison records.
- Coverage used for event detection: June--September 2022--2025, 485 valid SFO warm-season days.
- Catalogue: four detected SFO events; one July 2024 development triplet and three 2022 confirmatory triplets.
- Each primary evaluation record represents one hourly interval with aligned weather, price, carbon proxy, and grid context plus derived window/phase labels. Every frozen event, matched-control, and selected event-blind window contains 120 hourly rows.
- The publicly sourced observations were collected by NOAA, CAISO, and EIA; HeatTrace did not newly measure them.

### Exploratory five-station California extension

- Stations: SFO, SAC, FAT, RDD, and LAX, representing northern/southern coastal and inland California regimes. A predeclared Sacramento fallback exists but was not activated for event screening.
- Coverage: June--September 2022--2026 weather acquisition; 2026 is provisional.
- Catalogue: 25 station events grouped into 15 primary 24-hour-buffer regional episodes.
- Event eligibility: 12 eligible station events, 9 excluded 2022 events, and 4 provisional 2026 events. Episode status is 7 eligible, 5 excluded, and 3 provisional.
- Machine-readable event rows include station and source IDs, climate class, local/UTC boundaries, station-specific threshold and sample size, duration, peak/mean temperature, cumulative exceedance, phase-window bounds, regional episode, eligibility, exclusion reason, and source references.
- Hourly derived records include event/episode IDs, UTC and local time, phase flags, temperature/QC fields, hub price, CISO carbon fields, demand/generation, missingness, and issue flags.
- Benchmark artifacts include matched controls, 20 ordinary-window candidates per matrix event, overlap identifiers, coverage status, a 6,480-cell matrix, missingness audits, and claim-triage tables.

## Verified quality and provenance controls

- Event selection is weather-only; price, carbon, scheduling results, and policy outcomes are excluded from eligibility decisions.
- Timestamps use UTC interval starts; weather-day rules use `America/Los_Angeles`.
- Source manifests record URLs or identifiers, query scope, retrieval/processing timestamps, hashes, sizes, and coverage counts.
- NOAA duplicate/conflict and daily-maximum coverage checks are explicit. The multi-station screen requires at least 98% valid daily maxima; SFO 2025 was excluded at 119/122 days (97.54%).
- Missing weather breaks event runs; no event-detection imputation is used.
- Regional episodes are connected components after 24-hour interval expansion, which reduces double-counting but can create transitive composite episodes.
- Multi-station matrix execution attempted 6,480 cells: 5,448 succeeded and 1,032 failed (936 weather-incomplete, 96 forecast-missing).

## Consistency reconciliations

### Fixed 120-hour windows

`compute_event_evaluation_window` requires the complete detected event to fit within 120 hours. If an event is shorter, the surplus is divided before and after the event; a 72-hour event receives 24 hours on each side. A 120-hour event receives no padding. The existing manuscript's blanket description as one onset day plus event plus one recovery day is therefore inaccurate for events longer than 72 hours and will be replaced. The multi-station catalogue separately retains variable full windows from onset through recovery.

### Reported 0.5x boundary shifts

The executed workload grid is exactly `{1.0x, 2.0x, 3.0x}`. `compute_tested_feasible_boundary` first finds the maximum feasible tested multiplier for each of two workload seeds and then reports their arithmetic mean. A reported 2.5x boundary therefore means that one seed's maximum feasible tested level was 2x and the other's was 3x; it is not an executed 2.5x workload or a continuous threshold estimate. The manuscript will state this explicitly.

## Experimental evidence retained as benchmark validation

- Six policy roles, temperature-dependent PUE/effective capacity, synthetic deadline-constrained workloads, forecasting, the frozen 756-cell experiment, and equal-service filtering.
- H1--H5 classifications and all positive, negative, null, and non-estimable findings.
- Same-environment rerun: 756/756 cells, exact agreement on 44 scientific columns, 54/54 archive payload verification; not raw-source reconstruction or independent clean-checkout reproduction.
- Exploratory extension audit: 3,960 forecast-dependent run IDs affected by prohibited SFO-model transfer, 7/66 equal-service trios, 0/22 at both 2x and 3x, and 146/240 overlapping selected ordinary windows.

## Editorial changes required

1. Make the dataset pipeline, catalogue, schemas, provenance, and quality controls the primary contribution.
2. Separate public source measurements, HeatTrace-derived artifacts, and synthetic/modeled benchmark inputs.
3. Move scheduling methodology/results into benchmark evaluation and utility sections.
4. Replace internal development identifiers in scientific prose with descriptive terms; retain exact filenames and experiment IDs only in evidence records.
5. Rename the exploratory section to `California Multi-Station Dataset Extension and Quality Assessment` and keep one compact audit table.
6. Add a dedicated future global 2022--2026 methodology section in proposal tense.
7. Add Code and Data Availability. The configured remote is `https://github.com/Sid-DudeD017/HeatTrace.git`; an unauthenticated check of `https://github.com/Sid-DudeD017/HeatTrace` returned HTTP 404 on 2026-11-20, so public access cannot be claimed. The manuscript must display the URL together with an author-verification warning.

## Repository inspection boundary

The repository contains tracked source, configurations, benchmark tables, result archives, models, figures, and several derived data products. Raw NOAA, CAISO, EIA, and multi-station processed inputs are excluded by `.gitignore` or may carry provider-specific redistribution constraints. The README documents environment setup and many phase-specific commands, but a fully independent source-to-result reconstruction has not been demonstrated. This distinction must appear in the availability statement.
