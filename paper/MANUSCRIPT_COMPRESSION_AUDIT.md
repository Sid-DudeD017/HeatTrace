# HeatTrace Manuscript Compression Audit

## Audit baseline

- Audit date: 2026-11-19 (Asia/Kolkata).
- Original manuscript: `paper/backups/original_2026-11-19/main.tex`.
- Original compiled PDF: `paper/backups/original_2026-11-19/main.pdf`.
- Original PDF SHA-256: `001665b73ea08cfe5844d2b8c0ccbc5c589fb98a4c7a331af9cdc8acdaf43bae`.
- Original source SHA-256: `edff4a504b32dacaeefaa72ffe74d856c12389b777c48ed5c8d1c3789b95e59e`.
- Original length: 30 PDF pages, with References beginning on page 28 (27 body pages and 3 reference pages).
- Original source length: 9,018 words by `wc -w` (including LaTeX commands and table text).
- Original visual inventory: 8 figures and 6 tables.
- Inspection method: all 30 rendered pages were inspected in sequence, together with `main.tex`, bibliography, build report, evidence ledger, figure-source map, and author checklist.

The backup contains the original `main.tex`, `main.pdf`, `references.bib`, `BUILD_REPORT.md`, `EVIDENCE_TRACEABILITY.md`, `FIGURE_SOURCES.md`, and `AUTHOR_VERIFICATION_CHECKLIST.md`. The revision is therefore reversible.

## Page-level and typographic findings

1. Pages 1--4 spend roughly three pages on the abstract, introduction, a six-item contribution list, a separate non-claims section, and a roadmap. The same findings and caveats recur later.
2. Pages 4--7 contain a useful literature review, but four subsections repeat scope boundaries. The Ruparel distinction can be stated in one comparative paragraph.
3. Pages 7--8 list all H1--H5 and G1--G5 hypotheses before the methods. G1--G5 are repeated in the B2 audit; the primary research questions can be introduced compactly in the introduction.
4. The pipeline schematic on page 8 and matrix schematic on page 17 contain text too small for comfortable print reading.
5. Table 1 on page 10, Table 2 on page 12, Table 4 on page 18, Table 5 on page 22, and Table 6 on page 26 use overly wide prose columns; several are visibly clipped at the right margin.
6. Pages 10--12 repeat dataset constraints in prose, lists, and tables. The development time-series figure is illustrative rather than inferential and can be removed.
7. Pages 13--14 devote substantial space to an elementary numerical PUE example after the governing equations. Retain the equations and one parenthetical value, not a worked derivation.
8. Pages 14--16 give implementation-level LSTM and policy details that can be reduced to architecture, split, horizon, and policy role.
9. Pages 16--17 enumerate every matrix product in prose. A compact policy/design table can carry the same information.
10. Pages 18--21 restate the H1--H5 table in long hypothesis-specific subsections. The result figure, one compact table, and two analytical paragraphs are sufficient.
11. Literal Markdown markers such as `**24/36**`, `**NOT ESTIMABLE**`, and `**0 of 3 events**` are visible on pages 19--23. All must be replaced with LaTeX emphasis or plain prose.
12. The secondary policy-contrast figure on page 20 repeats the H3 result already conveyed by the primary H1/H3 figure and accompanying table.
13. Pages 21--22 use a full section and wide table for P11. The essential reproduction result fits in a concise paragraph.
14. Pages 22--26 use four pages, two figures, and a wide table for B2. Retain the narrow static-result figure and consolidate counts, defects, and G1--G5 verdicts into one compact audit table plus two paragraphs.
15. Pages 26--27 contain four separate limitations subsections. Consolidate internal, construct, external, and governance threats into one dense section without removing substantive caveats.
16. Pages 27--28 over-specify unimplemented global regions and technologies. Retain only the professor-requested design principles, all in future tense.
17. The conclusion repeats nearly every result and caveat. Reduce it to the contribution boundary and main evidentiary outcome.

## Section-by-section compression decisions

| Original material | Decision | Scientific reason |
|---|---|---|
| Abstract | Rewrite to about 180--220 words | Retain scope, v1 result, P11, and blocked B2 without methods-level detail. |
| Introduction, contribution list, non-claims, roadmap | Merge into one introduction | Preserve motivation, research questions, contribution boundary, and independent-event unit; remove duplicated disclaimers and paper roadmap. |
| Four related-work subsections | Merge into one compact section | Keep comparative synthesis of thermal-aware, carbon-aware, benchmark, and Ruparel work rather than title-by-title summaries. |
| Separate H1--H5/G1--G5 section | Remove as a standalone section | State v1 questions compactly in the introduction; present final classifications in result tables; B2 claims remain in its audit table. |
| Pipeline image | Replace with a simpler LaTeX-native vector flow | Improve legibility and avoid tiny embedded text. |
| Data-source prose and Table 1 | Merge into one compact data/benchmark table and short prose | Preserve provenance, proxy meaning, threshold, controls, blind windows, and development/confirmation split. |
| Development time-series figure | Remove | Illustrative only and not needed for the compressed scientific argument. |
| Triplet table | Fold triplet identities into the data/benchmark table | Preserve all three confirmatory triplets and cross-year-control caveat. |
| Thermal section | Retain equations; remove worked arithmetic and high-curve trivia | Equations and frozen constants convey the model; the example does not add scientific content. |
| Forecast and policy subsections | Compress into prose plus policy/design table | Preserve 72-by-5 input, 24-hour forecast, rolling horizon, six roles, HeatGuard boundary, and oracle status. |
| Parameter table and matrix schematic | Merge into policy/design table | Avoid redundant presentation while retaining all experimental axes and cohort counts. |
| Equal-service section | Retain equation and eligibility counts in experimental design | Essential construct-validity safeguard. |
| H1--H5 long subsections | Replace with one result table, primary result figure, and concise discussion | Preserve every classification, number, null, and caveat while eliminating repetition. |
| Secondary policy-contrast figure | Remove | Repeats H3 and consumes a full float. |
| P11 section and table | Compress to a paragraph in validation | Preserve 756 rerun, 44 columns, 54/54 archive, and same-environment limitation. |
| B2 architecture diagram | Remove | Small text and redundant with the audit table. |
| B2 G1 figure | Retain | Only additional experimental figure that communicates the surviving narrow B2 result. |
| B2 prose and audit table | Consolidate into one subsection and compact table | Preserve station scope, execution counts, forecast-transfer violation, equal-service attrition, overlap, G1--G5 verdicts, and BLOCKED status. |
| Four threats subsections | Merge into one section | Keep all material threats once, at their most relevant location. |
| Global future-work list | Compress to one paragraph | Retain global 2022--2026 plan, harmonization, causal forecasting, equal service, episode inference, and reproducibility; avoid invented locations or results. |
| Conclusion | Rewrite to one concise paragraph | Avoid restating the entire abstract and results table. |

## Target composition

- Body: exactly 12 pages, with References beginning on page 13.
- References: approximately 2 pages, subject to correct Springer formatting.
- Figures: 4 (pipeline, thermal model, primary v1 H1/H3 result, narrow exploratory B2 G1 result).
- Tables: 4 (data/benchmark, policy/design, H1--H5, B2 audit).
- Bibliography: retain the 12 verified entries.
- No geometry, margin, font-size, line-spacing, or bibliography-style manipulation.

## Achieved composition

- Final PDF: 14 pages total.
- Body: exactly pages 1--12.
- References: pages 13--14.
- Revised LaTeX-source word count: 4,227 by `wc -w`, down from 9,018 (53.1%).
- Final visual inventory: 4 figures and 4 tables.
- Final render inspection: all 14 pages checked; no clipped tables, overlapping captions, missing graphics, or unreadable equations remained.

## Integrity constraints for the revision

The revision will not change scientific code, datasets, frozen configurations, archived results, numerical findings, hypothesis classifications, or citations. The v1 thermal model will remain explicitly synthetic; CAISO price and EIA carbon will remain wholesale/proxy signals; P11 will remain same-environment reproduction; B2 will remain blocked; and global 2022--2026 work will remain future work.
