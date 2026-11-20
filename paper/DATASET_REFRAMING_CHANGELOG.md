# Dataset-Paper Reframing Changelog

Date: 2026-11-20.

## Manuscript changes

- Retitled the paper to *HeatTrace: A Historical Heatwave Dataset and Evaluation Benchmark for Sustainable Cloud Scheduling*.
- Rewrote the abstract and introduction so dataset construction is primary, scheduling evaluation is secondary, and auditing/reproducibility is tertiary.
- Reorganized the manuscript around sources and harmonization, event catalogue/scenarios, dataset characterization and schemas, benchmark framework, benchmark utility, multi-station dataset quality, and future global scope.
- Added explicit separation between external NOAA/CAISO/EIA measurements, HeatTrace-derived artifacts, and synthetic/model inputs.
- Added verified catalogue statistics: four original SFO events; four triplets with three confirmatory units; 25 multi-station events; 15 regional episodes; 12 eligible, 9 excluded, and 4 provisional station events; 7 eligible, 5 excluded, and 3 provisional episodes.
- Added record-grain and join semantics for hourly, event, episode, scenario, and run records.
- Restored the illustrative event/control signal figure and removed the exploratory extension result figure.
- Reframed H1--H5 as benchmark-utility evidence without changing classifications or numerical outcomes.
- Renamed and reframed the multi-station work as dataset development and scientific quality assessment; retained the 3,960-run forecast defect, service attrition, overlap, and narrow static result.
- Added a dedicated future global 2022--2026 benchmark methodology section in proposal tense.
- Added a clickable Code and Data Availability URL and an explicit author-verification warning after unauthenticated access returned HTTP 404.

## Consistency corrections

- Corrected the primary 120-hour-window description: complete events are contained, with surplus time split before/after shorter events; the rule is not universally onset day + 72-hour event + recovery day.
- Explained that reported 2.5x feasibility boundaries are means of two seed-specific maxima chosen from the executed 1x, 2x, and 3x grid; no 2.5x workload was executed.
- Distinguished station events, regional episodes, windows, triplets, matrix cells, and independent inferential units.

## Terminology

Removed reader-facing internal development labels (`v1`, `B2`, `Track B2`, `P6`, `P11`, `P12`) from the title, abstract, prose, headings, tables, and captions. Exact identifiers remain in evidence ledgers and repository filenames.

## Build outcome

- 14 pages total.
- Exactly 12 substantive manuscript pages.
- References on pages 13--14.
- 4 figures, 5 tables, and 12 bibliography entries.
- No LaTeX errors, undefined citations/references, missing graphics, or overfull boxes.
