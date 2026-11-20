# HeatTrace final-correction build report

## Build

- Build date: 2026-11-20 (Asia/Kolkata).
- Title: *HeatTrace: A Historical Heatwave Dataset and Evaluation Benchmark for Sustainable Cloud Scheduling*.
- Compiler: Tectonic 0.17.0.
- Class/style: Springer Nature `sn-jnl.cls` with `sn-mathphys-num.bst`.
- Command: `cd paper && tectonic --keep-logs main.tex`.
- Result: successful, exit status 0.

## Pagination and inventory

| Metric | Final value | Status |
|---|---:|---|
| Total pages | 14 | Pass |
| Body pages before References | 12 | Pass |
| First References page | 13 | Pass |
| Reference pages | 2 | Pass |
| Figures | 4 | Pass |
| Tables | 6 | Pass |
| Bibliography entries | 15 | Pass |

Page 12 contains future scope, conclusion, Code and Data Availability, and declarations. References occupy pages 13--14.

## Final corrections verified

- Anonymous public access to `https://github.com/Sid-DudeD017/HeatTrace` was verified by HTTP 200 responses for the repository page, raw README, repository API, and recursive tree API. The public API reports `visibility: public` and `private: false`.
- The availability statement now lists only artifacts observed in the public tree and distinguishes the locally generated full extension hourly export, manuscript tree, and excluded provider inputs.
- The nine 2022 events are accurately described as weather-eligible catalogue records excluded by a conservative annual joint-source gate. The missing `2022-06-13 17:00 UTC` EIA interval is outside their full event windows.
- Reconstruction commands were checked through `--help`, module signatures, and Python syntax compilation without performing acquisition or scientific reruns. The phase-four freeze is correctly identified as an internal function rather than a CLI.
- The schema table now distinguishes original and extension hourly artifacts, checked composite and simple keys, exact demand-field names, and matrix versus execution fields.
- H1--H5 values and classifications are unchanged; repeated result counts were removed from prose while retained in Table 5 and Figure 4.
- Figure 1 uses LaTeX-native vector boxes with distinct source/derived/evaluation colors. No scientific result plot was replaced.
- CAISO and EIA dataset-documentation titles were corrected to official page titles. Unsupported ExtremeWeather page metadata was removed; verified DOI, journal, conference, article, and page metadata were retained elsewhere.

## Compilation and visual validation

- No LaTeX errors, undefined citations, undefined references, missing graphics, or overfull boxes remain.
- Remaining log messages are underfull/page-balancing notices caused by narrow table columns and the Springer layout.
- Pages 3, 6, 7, 8, 12, 13, and 14 were rendered at 120 dpi and visually inspected. Figure 1 is aligned and legible; the schema table remains inside the text block; reconstruction commands wrap safely; availability text is clickable and unclipped; references occupy two readable pages.

## Preservation and repository integrity

- Author, affiliation, email, funding, and conflict-of-interest placeholders are unchanged from the pre-correction backup.
- No scientific Python source, dataset, frozen configuration, historical result, Git remote, or repository visibility setting was modified.
- No experiment, acquisition workflow, commit, or push was performed.
- The pre-correction manuscript and submission bundle are preserved at `paper/backups/pre_final_correction_2026-11-20/`.

Final checksums are recorded in `paper/FINAL_CORRECTION_CHANGELOG.md` after submission-bundle validation.
