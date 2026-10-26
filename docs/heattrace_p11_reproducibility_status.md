# HeatTrace P11 / Days 13–14 reproducibility status

## Verdict

P11 is substantively complete as a same-machine deterministic reproduction and archive exercise. It reran 756 cells in a clean output directory, compared every scientific field with the canonical P8 results, regenerated P9 analyses, and built a self-verifying 54-file archive. It did not establish turnkey full reproduction from a bare checkout on an arbitrary machine.

## Requirement audit

| Requirement | Verified? | Evidence | Remaining concern |
|---|---|---|---|
| Canonical P8 records intact | Yes | Root hashes equal those at `docs/p11_v1_reproduction_report.md:28-32`; archived copies in `canonical_p8/`. | Root outputs are mostly ignored/untracked, so archive is the durable copy. |
| 756 cells actually reproduced | Yes | Lines 49-66; distinct reproduced parquet hash `2a41634a…`; `data/results/p11_reproduction_comparison.json`. | Line 161 incorrectly says they were not rerun. |
| Unique IDs/cohorts | Yes | 756 IDs; 432 core, 216 blind, 72 comparator, 36 oracle (`docs/p11_v1_reproduction_report.md:47-59`). | None for recorded execution. |
| Scientific equality | Yes | Zero differences in completed/unfinished work, violations, cost, carbon, PUE, peak power and feasibility (`:70-88`). | Runtime/commit/timestamps intentionally differ. |
| Analysis regeneration | Yes | Scientific CSVs and deterministic figures match byte-for-byte (`:92-116`). | Reports/manifests contain operational provenance differences. |
| Adversarial checks | Yes, recorded | Missing/duplicate IDs, dev leakage, oracle deployability, dropped/incomplete work, frozen hash and failure-row probes (`:120-130`). | This audit did not rerun mutating tests because the user required read-only investigation. |
| Focused tests | Yes, recorded | 5 runner tests and 24 analysis tests passed (`:134-138`). | Full suite was not reported for P11. |
| Archive completeness/integrity | Yes for inventory | 54/54 verified by `verify_archive.py`; manifest has per-file SHA-256. | External NOAA raw files are referenced by hash, not included. |
| Models/calibration archived | Yes | Temperature V2 and HeatGuard V3 complete files listed at `:142-151`. | Runner expects them at untracked `data/models/...`, not archive paths. |
| Environment pinned | No | P11 records Python 3.13.3; `pyproject.toml` uses only minimum versions. | No lockfile/container/platform-independent environment. |
| Raw/processed manifests | Partial | Frozen benchmark/config/model/result hashes are archived. | Raw NOAA bytes, CAISO/EIA acquisition inputs, and full P1/P2 raw manifests are not in the 54-file archive. |
| Clean-checkout command | No | Only archive self-verification command is documented (`:150-151`). | No end-to-end restore/copy/download + execute + analyze recipe. |
| Figure/table regeneration | Yes | P11 matched 11 outputs (`:104-116`). | `docs/p6_validity_report.md` is archived but current root copy is untracked. |
| Manuscript | Preliminary only | `docs/heattrace_v1_preliminary_manuscript.md:1-111`. | Not submission-ready; limited related work and no venue format. |
| Release/tag | No | HEAD has no tags; archive directory is committed. | No signed/tagged v1 release or remote publication. |
| Working tree currently clean | No | Current `git status` contains pre-existing untracked models, reproductions, logs and reports. | P11's clean-tracked statement was historical. |

## What P11 actually ran

The evidence supports a full scheduler-cell reproduction, not merely metadata validation:

1. Canonical P8: 756-row SHA `c45391e6…`.
2. Reproduction: 756-row SHA `2a41634…`.
3. Run-ID digest is identical: `1a8cb83e…`.
4. Scientific fields are exactly identical; operational fields differ (`data/results/p11_reproduction_comparison.json`).
5. Reproduced analysis tables and figures match canonical bytes (`docs/p11_v1_reproduction_report.md:92-116`).

The contradictory line at `docs/p11_v1_reproduction_report.md:161` should be read as a documentation defect, probably copied from the earlier Day-13 plan that prescribed analysis-only regeneration (`docs/p6_validity_report.md:329-334`).

## Can another person reproduce from a clean checkout?

They can verify the committed archive immediately with:

```bash
python3 data/archive/heattrace_v1_d5b3c86/verify_archive.py
```

They can inspect canonical/reproduced outputs and hashes. They cannot reliably rerun the entire confirmation from only a clean checkout because:

- `precompute_confirmatory_forecasts` reads `data/raw/noaa` and `data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt` (`src/heattrace/experiments/p6_validity_runner.py:1931-1964`). Raw NOAA and `data/models/` are ignored.
- The archive stores model copies under `data/archive/.../frozen_models/`, but no documented restoration command maps them to runtime paths.
- The archive manifest records NOAA hashes under `external_source_inputs`, not the raw bytes.
- Dependencies are ranges, not exact resolved versions (`pyproject.toml:1-24`).
- P11 does not document the exact CLI or Python invocation used for the 756-cell reproduction.

Thus: **artifact verification is clean-checkout reproducible; full computational reproduction is only demonstrated in the original local environment.**

## Minimum release corrections

Before calling v1 externally reproducible:

1. Correct the P11 "not rerun" sentence and 23/36 H3 value.
2. Add a lockfile or container definition with exact Python/package versions.
3. Add a script that restores archived model/calibration files to runtime paths or parameterize the runner paths.
4. Document legal/raw source retrieval plus checksum verification for NOAA; clarify whether CAISO/EIA raw data are needed for confirmation or only rebuilding benchmarks.
5. Provide one clean-checkout command sequence for archive verification, optional full execution, analysis regeneration, and equality comparison.
6. Run/report the complete offline test suite in that clean environment.
7. Create a versioned release/tag only after those documentation fixes.
