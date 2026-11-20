# HeatTrace final-correction changelog

Date: 2026-11-20 (Asia/Kolkata).

## Manuscript changes

- Replaced the obsolete HTTP 404 warning with a verified public repository URL and an artifact-specific availability statement.
- Distinguished public code/derived artifacts from the manuscript tree, the locally generated full extension hourly export, and excluded NOAA/CAISO/EIA raw and processed inputs.
- Clarified that all nine 2022 events are weather-eligible catalogue records and that their joint-evaluation exclusion is caused by a conservative annual gate. The single missing EIA interval is outside every affected full event window; no event was restored.
- Replaced the nonportable long inline reconstruction command with two checked CLI entry points and an accurate description of the internal phase-four function, environment dependencies, provider-input requirements, and clean-checkout limitation.
- Rebuilt the schema table from observed CSV/JSONL/Parquet schemas. It now states checked composite and unique keys, exact fields, row counts, missingness, and artifact-specific semantics.
- Reduced repetition in results prose while preserving all H1--H5 decisions, exact table values, negative findings, and case-study boundaries.
- Added restrained color to the LaTeX-native lifecycle diagram to distinguish measurement, derived-data, and evaluation layers.
- Corrected official CAISO and EIA documentation titles and removed unverified ExtremeWeather page metadata. No citation key or in-text citation was left unresolved.

## Verification artifacts

- Added `FINAL_CORRECTION_AUDIT.md`.
- Added `DATASET_SCHEMA_VERIFICATION.md`.
- Updated `BUILD_REPORT.md`, `EVIDENCE_TRACEABILITY.md`, and `FIGURE_SOURCES.md`.
- Recompiled and visually inspected the 14-page PDF.
- Rebuilt the flat `paper/submission/` bundle from the final source and generated output.

## Preservation

- Protected identity, affiliation, email, funding, and declaration placeholders remain unchanged.
- Scientific source code, datasets, configurations, and frozen results were not modified.
- No data acquisition, model training, scientific experiment, commit, or push occurred.
- Recovery copy: `paper/backups/pre_final_correction_2026-11-20/`.

## Final checksums

SHA-256:

| File | SHA-256 |
|---|---|
| `paper/main.tex` | `a10052bfef2d0da4e25a70bb6b06b50ebbf2e6aca6f3f1b897d1375c03b65381` |
| `paper/main.pdf` | `305dac25030afd53019d7b4e1317141be8490fa6ac1ec048a39d87b09e792dc4` |
| `paper/references.bib` | `23bcd6804b8d883d765a492d30f37d607c8075230e80649cd855c669fcb452fc` |
| `paper/submission/main.tex` | `5ff787181e4ee9c3df60332778206dd4382f935d1bd1551020bf99f05ae9782e` |
| `paper/submission/main.pdf` | `bce677bbaa0ef23f4eef7715b17d981adba00619ad818856a502d8615e120e07` |
| `paper/submission/references.bib` | `23bcd6804b8d883d765a492d30f37d607c8075230e80649cd855c669fcb452fc` |
| `paper/FINAL_CORRECTION_AUDIT.md` | `150c28df45f5b28bbbdc73a42b6601dff43919c685fed6624d5b1f3e0b809f21` |
| `paper/DATASET_SCHEMA_VERIFICATION.md` | `8a510e1247335e4c3c74b1d6d1376ab6580a6dd67116001013242d76aeeebad7` |

The root and flat-submission TeX sources differ only in the three expected graphics paths. Both compile successfully to 14 pages with 12 body pages and 2 reference pages.
