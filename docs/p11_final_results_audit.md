# HeatTrace P11 Final Results Audit

**Audit date:** 2026-10-26
**Scope:** Phase 11 only (Days 13–14)
**Audit mode:** Read-only investigation; no simulations, tests, models, configurations, or existing experiment artifacts were changed
**Verdict:** **COMPLETE WITH LIMITATIONS**

## 1. Executive summary

P11 did perform a second, zero-resume execution of all 756 frozen confirmatory cells. This is supported by a distinct 793-line execution log that starts with `initial_completed: 0`, contains 756 unique `CELL_COMPLETED` events, and ends with `total_cells: 756` after 264.19 seconds. All 756 rows report `SUCCESS`; the reproduced run-ID digest matches the canonical digest; and an independent row comparison during this audit found all 44 non-operational columns byte/value-equivalent after run-ID alignment. Only `runtime_seconds` and `execution_commit` differ.

P11 also regenerated seven CSV result tables and four figure/status artifacts from the reproduced output. Their hashes match the canonical analysis artifacts. It created a versioned v1 archive with 54 inventoried payload files, a self-contained verifier, a reproduction comparison record, a reproduction report, and a preliminary manuscript. The archive verifier passed both in the working tree and after extraction from `git archive HEAD`.

P11 did **not** rebuild datasets from original NOAA, CAISO, or EIA sources; did **not** execute the study in a clean checkout or fresh dependency environment; did **not** retain an exact shell-command transcript; and did **not** establish third-party independent reproduction. The repository has no dependency lock file. The existing P11 report also contains a direct contradiction: it describes a clean 756-cell execution but later states that the 756 cells were not rerun. It additionally lists three per-run scientific fields that are not columns in either run parquet. Those are documentation defects, not failures of the actual second execution.

**Scientific conclusion:** P11 strengthened research reproducibility and artifact quality, but did not generate new scientific evidence.

## 2. P11 objectives versus verified completion

The Phase 11 plan required a clean-output 756-run reproduction, regenerated H1–H5 tables and figures, targeted tests, an immutable/versioned archive, exact Git provenance, and a preliminary manuscript that separates confirmatory and exploratory evidence ([plan](heattrace-14-day-review.html#L233)).

| Planned objective | Verified status | Evidence and limitation |
|---|---|---|
| Reproduce exactly 756 run IDs | **Completed** | The reproduction manifest reports 756 cells, 756 unique IDs, 756 successes, zero failures, no checkpoint resume, and 756 cells executed in-session ([manifest](../data/reproductions/heattrace_v1_d5b3c86/p6_validity_manifest.json#L3-L22)). The execution log starts from zero ([log](../data/reproductions/heattrace_v1_d5b3c86/p6_validity_execution.jsonl#L5)) and finishes at 756 ([log](../data/reproductions/heattrace_v1_d5b3c86/p6_validity_execution.jsonl#L793)). |
| Match the canonical run-ID set | **Completed** | Both manifests contain digest `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1`; this audit also aligned both parquets and verified equal 756-ID sets. |
| Regenerate H1–H5 tables and figures | **Completed** | Seven CSV outputs, two PNG figures, and two Markdown status figures are present in both canonical and reproduction archive trees; all eleven hashes match ([P11 report](p11_v1_reproduction_report.md#L92-L116)). The exact analysis command was not preserved. |
| Run targeted provenance/leakage/equal-service/analysis tests | **Completed, evidence limited to summary** | The tracked report records 5 runner tests passed with 72 deselected and 24 analysis tests passed ([P11 report](p11_v1_reproduction_report.md#L134-L138)). There is no raw pytest log, JUnit file, or immutable command transcript. Failed count is zero by the recorded summaries; skipped count is not independently recorded. |
| Archive v1 artifacts with hashes | **Completed** | The archive manifest inventories 54 payloads ([archive manifest](../data/archive/heattrace_v1_d5b3c86/archive_manifest.json#L46-L47)); its SHA-256 is `2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4`. All 54 hashes and sizes pass the self-verifier. |
| Make archive read-only/versioned | **Partially completed** | All archive payloads, manifest, and verifier are Git-tracked. Files remain ordinary writable `0644` files; immutability is by Git/hash detection, not filesystem enforcement or signed release/tag. |
| Identify exact implementation and evidence commits | **Completed with naming nuance** | Reproduction executed against `d5b3c86...`, the P10 checkpoint. P11 implementation/archive commits are `995a5b7...`, `85c2a60...`, and `287cc95...`. The final archive manifest records runner and analysis commits ([archive manifest](../data/archive/heattrace_v1_d5b3c86/archive_manifest.json#L3-L6)). |
| Prepare preliminary manuscript with nulls and limitations | **Completed** | The manuscript retains `LIMITED RESULT`, identifies H4 as post-Day-8 exploratory and not estimable, preserves the null third event, and lists explicit non-claims ([manuscript](heattrace_v1_preliminary_manuscript.md#L46-L92)). |
| Defer final polishing | **Completed** | Venue formatting, final abstract, and extended related work were not added; the manuscript explicitly lists deferrals ([manuscript](heattrace_v1_preliminary_manuscript.md#L105-L111)). |

No planned P11 experiment was skipped. Clean-environment reproduction and raw-data reconstruction were not promised as explicit Phase 11 deliverables, but remain material reproducibility limitations.

## 3. Commits and files attributable to P11

### Commits

| Commit | Role | Verified changes |
|---|---|---|
| `d5b3c86ac9076b118644e32dd2c8b6ab6f7cab2d` | Execution baseline, not a P11 commit | P10 checkpoint used by the P11 rerun. It changed P10 analysis/report/test files and the plan. |
| `995a5b76a5cc1233213c52cdf5b8443d849e23f3` | Initial P11 implementation | Added archive manifest/verifier, comparison JSON, reproduction report, preliminary manuscript; added an optional `check_baseline_hashes` parameter to the analysis entry point. |
| `85c2a605b12d266060eb56f84d95d673784f33d4` | P11 portability/provenance repair | Added all 54 archive payloads, expanded verifier, and corrected report/manuscript/comparison metadata. |
| `287cc958aa1a5267ef00cd17014069e07fa09eb0` | Final P11 metadata repair | Corrected four external NOAA source byte counts in the archive manifest. |

### Created or modified paths

The complete commit-level inventory is 59 archive/report/code paths. The material groups are:

- Added `docs/p11_v1_reproduction_report.md` and `docs/heattrace_v1_preliminary_manuscript.md`.
- Added `data/results/p11_reproduction_comparison.json`.
- Added `data/archive/heattrace_v1_d5b3c86/archive_manifest.json` and `verify_archive.py`.
- Added 54 archived payloads under `canonical_p8/`, `reproduction_p8/`, `canonical_analysis/`, `reproduction_analysis/`, `frozen_benchmarks/`, `frozen_models/`, and `frozen_specifications/`.
- Modified `src/heattrace/evaluation/p6_validity.py` to allow reproduction analysis to bypass the *canonical-byte-hash* requirement while retaining semantic verification. The default remains `check_baseline_hashes=True`; no production caller in the tracked source disables it.
- The final repair modified only `archive_manifest.json`.

The working `data/reproductions/` directory remains untracked, but its P11 reproduction artifacts are preserved as tracked copies under `data/archive/heattrace_v1_d5b3c86/reproduction_p8/` and `reproduction_analysis/`.

## 4. What P11 actually executed

| Verification activity | Actually executed? | Command/evidence | Result | Limitations |
|---|---|---|---|---|
| 1. Source-code verification | **Yes, bounded** | Execution records commit `d5b3c86...`; analysis records `995a5b7...`; archive records both. | Git provenance is bound to the rerun and analysis. | No signed tag/release and no exact source-tree hash beyond Git commits. |
| 2. Dependency verification | **Partial** | Report records Python 3.13.3/macOS arm64 ([report](p11_v1_reproduction_report.md#L10-L16)); frozen model/config hashes were checked. | Frozen scientific dependencies matched. | No `uv.lock`, `poetry.lock`, or requirements lock; no saved `pip freeze`; third-party package versions are not reproducible from the repository. |
| 3. Existing-artifact hash verification | **Yes** | Canonical P8 and frozen hashes are recorded in the report ([report](p11_v1_reproduction_report.md#L28-L43)) and archive inventory. | Canonical P8 bytes stayed unchanged. | Root canonical P8/model outputs are untracked; tracked archive copies preserve them. |
| 4. Unit/integration tests | **Reported yes** | `pytest tests/test_p6_validity_runner.py -k "enumeration or contamination or digest or frozen"` and `pytest tests/test_p6_validity_analysis.py`. | 5 + 24 = **29 passed**; 72 deselected; 0 failures reported. | No raw test log; skipped count and exact environment are unverified. |
| 5. Regenerate result tables from reproduced simulation output | **Yes** | Reproduction analysis manifest points to the reproduction parquets and lists output hashes ([manifest](../data/reproductions/analysis/results/p6_analysis_manifest.json#L41-L75)). | Seven CSV tables regenerated; all seven match canonical hashes. | Exact shell/Python invocation not retained. |
| 6. Regenerate research plots | **Yes** | Reproduction analysis contains two PNGs plus two Markdown status artifacts; hashes match canonical outputs. | 2 graphical plots and 2 status figures regenerated identically. | No graphical pixel-level test beyond exact byte hashes; exact invocation absent. |
| 7. Re-execute individual simulations | **Yes** | Each execution-log `CELL_COMPLETED` record names a run ID and status. | 756 cell executions recorded. | Log is application-generated, not an external scheduler/audit log. |
| 8. Re-execute all 756 confirmatory simulations | **Yes** | Log lines 1–793; line 5 has `initial_completed: 0`; line 793 records 756 completed and 264.19 seconds. | **756/756 successes, 0 failures, 756 unique IDs.** | Same host and repository, not an independent environment. Exact launch command absent. |
| 9. Rebuild dataset from original NOAA/CAISO/EIA inputs | **No** | No P11 dataset-build log or rebuilt raw/intermediate dataset exists. NOAA raw files are only external provenance entries ([archive manifest](../data/archive/heattrace_v1_d5b3c86/archive_manifest.json#L319-L346)). | Not performed. | Dataset reproducibility remains unestablished. CAISO/EIA raw reconstruction is not archived as a P11 procedure. |
| 10. Clean-checkout reproduction in a fresh environment | **No** | P11 has no clean-checkout simulation log. During this audit, archive verification passed after `git archive HEAD` extraction, but no simulation was run there. | Archive portability verified; experiment portability not verified. | Canonical models/results are not tracked at their normal runtime paths, and dependencies are not locked. |
| 11. Frozen configuration and Git provenance verification | **Yes** | Frozen hashes and commits are recorded in the reproduction and archive manifests. | Expected frozen hashes match; no P11 changes to frozen specs or canonical outcomes were found. | Provenance is repository-local rather than signed/externally attested. |

### Exact command evidence caveat

The repository does not contain a full command transcript. The only exact P11 commands preserved in tracked prose are the two pytest commands above, `git diff --check`, and the archive verifier command `python3 data/archive/heattrace_v1_d5b3c86/verify_archive.py` ([report](p11_v1_reproduction_report.md#L134-L151)). The simulation report names `execute_frozen_confirmation`, but does not preserve its exact CLI or Python invocation. Therefore the *execution* is verified from its log, while the exact launch command is **unverified**.

## 5. Exact numerical P11 results

### Confirmatory rerun

- Simulation cells rerun: **756**.
- Unique run IDs: **756**.
- Successful reruns: **756**.
- Failed reruns: **0**.
- Resume count at start: **0 completed**.
- Wall-clock time: **264.19 s**.
- Cohorts: **432** core benchmark, **216** event-blind benchmark, **72** algorithm comparators, **36** oracle reference.
- Oracle rows incorrectly marked deployable: **0/36**.
- Development leakage rows: **0**.
- Run-ID digest: `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1` (canonical match).

### Tests

- Tests reported passed: **29** total (5 runner + 24 analysis).
- Tests reported failed: **0**.
- Tests deselected: **72**.
- Tests skipped: **not independently recorded**.

### Row and artifact comparison

- Independently reproduced result rows: **756**.
- Run-ID set discrepancies: **0**.
- Non-operational run-table column discrepancies after run-ID alignment: **0 across 44 columns**.
- Operational columns differing: `runtime_seconds` in 751 rows and `execution_commit` in 756 rows.
- Canonical run/checkpoint SHA-256: `c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f`.
- Reproduction run/checkpoint SHA-256: `2a41634a318193f8fcde624bd0dd0e023a9da19d1e4fd682cb32895fba9033fa`.
- Canonical manifest SHA-256: `d0dd9f870ec2a431cc16177c5f1b7a5e6b47a7dc888b0acb491a819656006082`.
- Reproduction manifest SHA-256: `29e60aee534bb3f91ab9aecf4704bea85a2d80ba5043996c8fc94579effc8b32`.
- Canonical execution-log SHA-256: `de430ceea4559de2f4e67f5b122223b3496dfe854e1f5efa874909363bff0e80`.
- Reproduction execution-log SHA-256: `d1df535a3ee1a0be2404afd03dfb35803af06528b239225d4f6932ca204e7935`.
- Regenerated CSV tables: **7/7 byte-identical**.
- Regenerated figure/status artifacts: **4/4 byte-identical** (2 PNG, 2 Markdown status artifacts).
- Scientific conclusion changes: **0**.
- Archive payloads: **54/54 verified**.
- Archive manifest SHA-256: `2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4`.

### Hypothesis outcomes retained

- H1: **SUPPORTED**; event effects `-0.5x`, `-0.5x`, `0.0x`.
- H2: **PARTIALLY SUPPORTED**; no tested-boundary recovery, bounded full-thermal violation reductions.
- H3: **PARTIALLY SUPPORTED**; 24/36 and 23/36 non-zero event separations in CONF_1/CONF_2, 0/36 in CONF_3, 0/54 strict reversals.
- H4: **NOT ESTIMABLE**; no controlled forecast-source intervention/allocation traces.
- H5: **NOT SUPPORTED**; calibrated dynamic margin did not beat fixed margin.

## 6. Before versus after P11

| Dimension | Before P11 | After P11 | What changed? |
|---|---|---|---|
| Experimental reproducibility | One canonical 756-cell P8 execution | A second 756-cell execution on the same host/source lineage | Same scientific rows were reproduced; environment independence remains untested. |
| Dataset reproducibility | Frozen derived inputs and source provenance | Same; raw NOAA file hashes/sizes documented | No NOAA/CAISO/EIA rebuild was performed. |
| Figures and tables | Canonical P9/P10 outputs | Seven tables and four figure/status artifacts regenerated from rerun outputs | All eleven deterministic artifact hashes match. |
| Artifact integrity | Canonical outputs and scattered frozen inputs | Versioned archive with 54-file content inventory and verifier | Archive is portable and tamper-detecting, but not physically read-only or signed. |
| Test coverage | Existing runner/analysis tests | Focused 29-test pass reported | No new broad test campaign; raw test logs were not retained. |
| Documentation | Day 11 audit and concise v1 report | Reproduction report plus preliminary manuscript | Reproduction/reporting improved; P11 report contains two material documentation defects. |
| Git provenance | P8/P9/P10 commits and manifests | Runner commit, analysis commit, archive repair commits, final manifest hash | Exact evidence snapshot is now Git-tracked. |
| Publication readiness | LIMITED RESULT with claim/evidence map | Preliminary manuscript and reproducibility package | Better workshop/short-paper support; raw-data and independent-environment reproducibility remain limitations. |

Compared with the Day 11 adversarial audit, P11 added a second execution, deterministic downstream regeneration, an archive-level hash inventory, a portable verifier, and a preliminary manuscript. It did not add data, events, interventions, or scientific degrees of freedom.

## 7. Did P11 produce new scientific findings?

- New scientific experiment: **No.** It repeated the frozen experiment without changing parameters.
- Additional policy-performance differences: **No.** Reproduced differences exactly match the prior results.
- Feasibility findings changed: **No.** H1 remains supported with two `-0.5x` events and one null event.
- Carbon/cost findings changed: **No.** All eligible derived comparisons match.
- LSTM forecast-regret mechanism resolved: **No.** H4 remains not estimable.
- HeatGuard improved: **No.** H5 remains not supported.
- New independent heatwave events: **No.** The same three confirmatory triplets were rerun.
- Onset/peak/recovery analysis restored: **No.** P11 did not add new phase-level traces or analysis.
- Original hypothesis verdict changed: **No.** All H1–H5 classifications are unchanged.

**P11 strengthened research reproducibility and artifact quality, but did not generate new scientific evidence.**

## 8. Correctness findings

### Important

1. **The P11 report contradicts the actual execution evidence.** It states that a clean execution ran all 756 cells ([lines 47–66](p11_v1_reproduction_report.md#L47-L66)) but later says “756 cells were not rerun” ([line 161](p11_v1_reproduction_report.md#L161)). The application-generated execution log supports the former. The latter should be corrected to avoid invalidating the narrative record.

2. **The P11 report claims comparison of nonexistent per-run columns.** It lists `mean_pue`, `max_pue`, and `peak_facility_power_kw` as fields checked across all 756 rows ([lines 72–84](p11_v1_reproduction_report.md#L72-L84)); neither canonical nor reproduction parquet contains those columns. The actual parquets have `realized_facility_energy_kwh`, `maximum_facility_power_excess_kw`, and the other recorded fields. This audit verified equality across all 44 real non-operational columns, so the reproduction conclusion survives, but the field list is inaccurate.

3. **Clean-checkout experiment reproduction is not established.** A `git archive HEAD` extraction can verify the archived 54 files, but the repository does not track canonical model artifacts at their normal `data/models/...` runtime paths, and it has no dependency lock. No 756-cell run was performed in that extracted tree.

4. **The exact command and environment transcript is incomplete.** The simulation launch and analysis-regeneration commands are absent, and no raw test log or dependency snapshot is archived. This prevents command-for-command independent repetition.

### Minor

5. **Archived JSON and report links retain absolute local paths.** Several archived manifests and the canonical report contain `/Users/siddharthbhakta/HeatTrace/...` or absolute `file://` references. The verifier itself uses relative inventory paths and passes portably, so these stale display/provenance strings do not break integrity verification, but they reduce usability on another machine.

6. **“Immutable/read-only” is logical, not enforced.** Archive files are normal writable files. Git and SHA-256 detect changes; they do not prevent them. A signed tag/release or write-protected external archive would provide stronger assurance.

### Checks that passed

- No stale or mismatched archive inventory hash was found.
- No missing inventoried archive payload was found.
- No frozen specification changed during P11.
- No canonical P8 outcome bytes were overwritten.
- Reproduction output contains no missing or duplicate run IDs and no silent failures.
- All reproduced table and figure/status hashes match their canonical equivalents.
- Archive verification passes from the working tree and from a fresh `git archive HEAD` extraction.

## 9. Verdict and reproducibility ratings

**Final P11 verdict: COMPLETE WITH LIMITATIONS.**

The core Phase 11 work is real: all 756 simulations were rerun from zero, the scientific rows and downstream outputs reproduce, and a complete tracked hash inventory exists. “Complete and independently reproducible” would be too strong because the rerun used the same machine/repository lineage, raw datasets were not rebuilt, dependency versions are not locked, and no clean-checkout simulation was performed.

| Area | Rating | Basis |
|---|---|---|
| Experiment reproducibility | **Strong, same-environment** | 756/756 second execution; exact run-ID set and 44 non-operational columns match. |
| Dataset reproducibility | **Not demonstrated** | External raw NOAA metadata is recorded, but NOAA/CAISO/EIA rebuild was not run. |
| Result-table reproducibility | **Strong** | Seven regenerated CSVs are byte-identical. |
| Figure reproducibility | **Strong for produced artifacts** | Two PNGs and two status artifacts are byte-identical. |
| Artifact integrity | **Strong** | 54/54 archive payloads pass size/hash verification; manifest is tracked. |
| Clean-checkout readiness | **Partial** | Archive verification works from `git archive`; full simulation reproduction was not attempted and runtime dependencies/paths are incomplete. |

## 10. Remaining P11 work and Day 15 readiness

### BLOCKER — before executing v2 outcomes

- **None found in the frozen v1 evidence itself.** The v1 archive is internally consistent and the rerun is scientifically equivalent.

### IMPORTANT — before paper submission

- Correct the contradictory “756 cells were not rerun” statement and the nonexistent field list in `docs/p11_v1_reproduction_report.md`.
- Add a machine-readable command/environment record: exact simulation and analysis commands, Python/package versions, and test output.
- Add a dependency lock and document how archive-contained models/benchmarks are mapped into runtime paths in a clean checkout.
- Perform and record one clean-checkout rerun in an isolated environment if claiming independent or turnkey reproducibility.
- Document or execute raw NOAA/CAISO/EIA dataset reconstruction if claiming dataset-level reproducibility.

### OPTIONAL

- Replace absolute local links/paths in archived reports/manifests with relative references.
- Publish a signed tag/release or external write-protected checksum record.
- Preserve raw pytest/JUnit logs in future phase archives.

### Day 15 decision

It is safe to freeze the current v1 archive and begin Day 15 protocol work in a separate branch, using commit `287cc958aa1a5267ef00cd17014069e07fa09eb0` and archive-manifest SHA-256 `2038706b9a0b24b1f874c58eb9b788635de61c8796e0200969229a99463927a4` as the immutable baseline. Do not claim clean-environment or dataset reconstruction reproducibility, and do not inspect new v2 outcomes until the separate v2 protocol is frozen.

## 11. Auditor verification commands

These commands were executed during this audit; they are not retroactively attributed to P11:

```text
git status --short
git log --oneline --decorate -n 25
git show --stat --summary <P11 commits>
python3 data/archive/heattrace_v1_d5b3c86/verify_archive.py
git archive HEAD | tar -x -C <temporary-directory>
python3 <temporary-directory>/data/archive/heattrace_v1_d5b3c86/verify_archive.py
.venv/bin/python <read-only parquet/log comparison probes>
shasum -a 256 data/archive/heattrace_v1_d5b3c86/archive_manifest.json
```

No expensive simulation or test suite was run during this audit.
