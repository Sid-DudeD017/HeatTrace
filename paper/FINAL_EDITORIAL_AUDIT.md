# HeatTrace final editorial audit

Audit date: 2026-11-20

## Repository state and scope controls

- The pre-edit working tree contained user-owned untracked material, including the entire `paper/` tree, `.site-publish/`, and three derived CSV files under `data/v2/events/`. None is to be deleted or overwritten outside the manuscript outputs requested by the brief.
- The current manuscript, bibliography, PDF, supporting documents, and submission bundle were copied to `paper/backups/pre_final_editorial_2026-11-20/` before editing.
- Scientific source code, frozen configurations, historical data, and experimental results are read-only for this pass.
- Author/affiliation/email placeholders, funding/conflict placeholders, and the complete Code and Data Availability statement (including the HTTP 404 warning) are protected verbatim.

## Scientific verification

- Fixed-window construction is consistent with `src/heattrace/process/p6_event_bundle.py`: the complete event must fit within 120 hours; surplus hours are divided before and after the event; 72-hour events receive 24 hours on each side; 120-hour events receive no padding; events longer than 120 hours are invalid rather than truncated. The frozen index records 120 rows for every original event, control, and blind window. The multi-station extension instead preserves variable onset-to-recovery windows.
- Feasibility-boundary aggregation is consistent with `configs/p6_validity.yaml`, `src/heattrace/evaluation/p6_validity.py`, and frozen results: only 1x, 2x, and 3x are executed; each seed contributes its maximum feasible executed multiplier; the reported boundary is the arithmetic mean across seeds. A value of 2.5x is therefore an aggregate of seed-specific maxima 2x and 3x, not an executed workload.
- The reported H1 changes of -0.5x, -0.5x, and 0x are retained. The experimental conclusions remain bounded to three independent confirmatory events.
- Catalogue counts agree with machine-readable artifacts: 25 station events and 15 regional episodes; 12 eligible station events, nine excluded 2022 events, and four provisional 2026 events; seven eligible, five excluded, and three provisional episodes.

## Missing citations

- The first substantive source description lacks direct citations to NOAA GHCNh, CAISO OASIS day-ahead LMP documentation, and EIA Form EIA-930/Hourly Electric Grid Monitor documentation.
- Official dataset/documentation entries will be added without invented DOIs. The EIA wording must distinguish directly published generated-intensity fields from HeatTrace's unit conversion and validation; CAISO LMP must remain a wholesale signal; airport observations must remain climate proxies.

## Dataset documentation gaps

- Existing prose describes record grains but does not show the real join keys and representative column names compactly.
- A schema table is needed for hourly observations, station events, regional episodes, controls/ordinary windows, and run-level outputs.
- The paper does not yet provide a practical reconstruction sequence using commands that exist in the repository.
- Reconstruction limitations need to state that raw/processed source material is locally present or ignored rather than proven redistributable, external retrieval and provider constraints remain, and clean-checkout source-to-result reproduction has not been demonstrated.

## Novelty and discussion gaps

- The related-work section names DCcluster-Opt, WeatherBench 2, and ExtremeWeather, but it should compare their research objects directly with HeatTrace's complete station-event catalogue, outcome-blind controls, quality flags, provenance manifests, and scheduling protocol.
- Interpretation should explain, without causal invention, why complete events can expose modeled feasibility changes; why the third event and one matched control prevent heatwave-exclusive claims; why forecast-source intervention and equal completed service are necessary; and why the exploratory multi-station results are not validated.

## Writing and layout issues

- Several adjacent passages repeat dataset/benchmark/provenance terminology and can be tightened.
- Figure 1 needs larger, more consistent internal text and clearer visual hierarchy.
- Figure 4's caption needs explicit statements about no strict ranking reversal and `N=3` event-level independence.
- Tables 1, 2, and 5 use long headings and dense cells. Headings and cell wording can be shortened without removing values.
- A visual PDF inspection is required after compilation to check page balance, figure legibility, table overflow, bibliography pagination, and protected text.

## Planned changes

1. Add official NOAA, CAISO, and EIA entries and cite them at first substantive use.
2. Add one compact real-field schema table and a concise reconstruction/reuse subsection.
3. Tighten novelty positioning and scientific interpretation while preserving every reported result.
4. Improve Figure 1 typesetting, Figure 4 caption, and dense table wording.
5. Compile with the existing Springer class and numbered bibliography; check citations, cross-references, warnings, and page counts.
6. Update the PDF, supporting evidence documents, submission bundle, and final changelog.
