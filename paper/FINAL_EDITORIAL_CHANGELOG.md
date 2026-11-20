# HeatTrace final editorial changelog

Date: 2026-11-20

## Implemented manuscript changes

- Preserved the title and dataset-first contribution hierarchy.
- Verified the original 120-hour window rule against code and frozen indices; the validated wording is unchanged in substance.
- Verified seed-level feasibility aggregation against configuration, implementation, and frozen findings; clarified that 2.5x is an average of 2x and 3x seed maxima, not an executed workload.
- Added a numbered schema table with real identifiers and representative fields for hourly signals, station events, regional episodes, scenario windows, and run outputs.
- Added an executable reconstruction sequence for source processing, event detection, and scenario/matrix freezing. The text identifies provider, credential, Git-ignore, redistribution, and clean-checkout limitations.
- Added official bibliography entries and first-use citations for NOAA GHCNh Version 1, CAISO OASIS day-ahead LMP documentation, and EIA-930 Hourly Electric Grid Monitor documentation.
- Clarified EIA semantics: the generated-intensity workbook field is converted and independently reconciled by HeatTrace; it is a production average, not marginal or avoided emissions.
- Strengthened the novelty comparison with DCcluster-Opt, WeatherBench 2, ExtremeWeather, carbon-aware scheduling, and thermal-aware placement without making priority or superiority claims.
- Expanded interpretation of the null third event, the separating matched control, equal-service filtering, forecast-source intervention, and the invalid multi-station forecast-aware subset.
- Retained H1 supported, H2/H3 partially supported, H4 not estimable, H5 not supported, zero strict reversals, no HeatGuard superiority, and no global generalization.
- Clarified catalogue screening, detected years, eligible/excluded/provisional records, and actual evaluation coverage.

## Layout and readability

- Rebuilt Figure 1 as an aligned three-stage lifecycle with larger internal text and clear evidence-layer labels.
- Confirmed Figure 2 describes temperature, wholesale price, and demand and remains illustrative/development-only.
- Retained Figure 3 equations and synthetic-thermal disclaimer.
- Revised Figure 4's caption to identify feasibility-boundary differences, nonzero equal-service gaps, no strict ranking reversal, and three independent events.
- Shortened headings and cell wording in source, catalogue, results, and multi-station audit tables; resolved all overfull boxes.
- Added the compact schema as Table 3. The final paper contains four figures and six numbered tables, all cited in text.

## Validation

- Tectonic compilation: pass.
- Undefined citations/references: none.
- Missing graphics: none.
- Overfull boxes: none.
- Final pagination: 12 body pages plus 2 reference pages (14 total).
- Bibliography: 15 entries; official data-source citations appear as references 13--15.
- Visual inspection: pages 3, 4, 8, 11, and 12 rendered at 120 dpi; lifecycle diagram, schema, dense audit table, and protected closing sections are legible and unclipped.
- Flat `paper/submission/` bundle: rebuilt and independently compiled.

## Protected material and research integrity

- Author/affiliation/email placeholders: unchanged.
- Funding/conflict placeholders: unchanged.
- Complete Code and Data Availability statement, including HTTP 404 warning: unchanged.
- Repository access/visibility and Git remote: untouched; no access test performed.
- Scientific code, frozen configurations, historical datasets, canonical results, and archived results: untouched.
- Pre-edit backup: `paper/backups/pre_final_editorial_2026-11-20/`.

## Final checksums

- `paper/main.tex`: `09aef90fe08abe19899188265a1070847e90833a533310e080f4c6a85aa2a9aa`
- `paper/main.pdf`: `a0cd9af6ac9fa0d41e2b64c12261a4b0be64e445a419de23346c8c0de111dd08`
- `paper/references.bib`: `49f224bc1b334b2916fc7806a4871a0ac51def684d0632ddfdb0f2a467257ffd`
- `paper/submission/main.tex`: `34df407e4216f33b52d85d00a73b30ebb215263e3aa6360d668a0c2b36941127`
- `paper/submission/main.pdf`: `27cd7b12c078efb0623812b2e6e8fb1f441b4ce413e489931e9a34461fcff93b`
