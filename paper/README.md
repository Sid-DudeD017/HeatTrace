# HeatTrace Manuscript Directory

This directory contains the dataset-led, author-reviewable Springer Nature LaTeX manuscript, compiled PDF, evidence records, reversible backups, and a flat compile-ready submission bundle.

## Key files

```text
paper/
├── main.tex                         # Revised Springer Nature manuscript
├── main.pdf                         # 14 pages: 12 body + 2 references
├── references.bib                   # 15-entry bibliography
├── FINAL_EDITORIAL_AUDIT.md         # Pre-edit scientific/editorial audit
├── FINAL_EDITORIAL_CHANGELOG.md     # Implemented corrections and validation
├── DATASET_PAPER_REFRAMING_AUDIT.md # Evidence and consistency audit before rewriting
├── DATASET_REFRAMING_CHANGELOG.md    # Dataset-paper changes and terminology updates
├── MANUSCRIPT_COMPRESSION_AUDIT.md  # Original-page audit and editing decisions
├── BUILD_REPORT.md                  # Build, pagination, warning, and integrity checks
├── EVIDENCE_TRACEABILITY.md         # Claim-to-artifact mapping
├── FIGURE_SOURCES.md                # Four retained figures and provenance
├── AUTHOR_VERIFICATION_CHECKLIST.md # Metadata and policy items requiring authors
├── backups/original_2026-11-19/     # Reversible 30-page original
├── backups/pre_dataset_reframing_2026-11-20/ # Previous 12-page framing
├── figures/                         # Retained and legacy provenance figures
└── submission/                      # Flat compile-ready journal upload bundle
```

## Build

```bash
cd paper
tectonic main.tex
```

The final audited build uses Springer Nature `sn-jnl.cls` and `sn-mathphys-num.bst`. It has exactly 12 substantive body pages; References begin on page 13 and end on page 14. The manuscript contains four figures, six tables, and 15 bibliography entries.

The source still includes author-facing placeholders for names, affiliations, correspondence, funding, and competing interests. The protected repository-access statement remains unchanged; repository access was not re-tested during the final editorial pass.
