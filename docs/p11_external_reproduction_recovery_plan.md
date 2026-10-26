# P11 External Reproduction Recovery Plan

**Audit date:** 2026-10-27  
**Repository:** `/Users/siddharthbhakta/HeatTrace`  
**Mode:** read-only Git/data/security diagnosis; no branch change, commit, push, merge, history rewrite, simulation, or experimental-input modification  
**Decision:** **BLOCKED pending a clean, content-addressed release package**

## 1. Root cause

The teammate cloned the public `origin/main`, and that ref ends at `563f6ac` (P5.5). The local checkout is also named `main`, but its HEAD is `1114e5bab3fa4db83accfaffbb36e0b7478800cb`, 18 commits ahead of `origin/main`. No remote-tracking ref contains `1114e5b`. The P6-P11 implementation, frozen inputs, P8/P9 outputs, and P11 archive therefore exist in the local commit graph but were never made reachable from the public `main` observed by the teammate.

This is not a failed P11 simulation attempt. It is a source-and-input distribution failure: the teammate had no P6/P11 code to invoke and reran **0/756** cells.

There is a second packaging defect. The tracked P11 archive contains frozen models and benchmark artifacts under `data/archive/heattrace_v1_d5b3c86/`, while the runner expects models under `data/models/`. Raw NOAA files are ignored and are not in the archive at all. A clean checkout of the local HEAD therefore still is not turnkey.

## 2. Git and branch findings

| Item | Finding |
|---|---|
| Repository root | `/Users/siddharthbhakta/HeatTrace` |
| Current branch | `main` |
| Current HEAD | `1114e5bab3fa4db83accfaffbb36e0b7478800cb` — `docs(p11): correct reproduction evidence and limitations` |
| Upstream | `origin/main` |
| Upstream HEAD | `563f6ac` — `Complete fail-closed validation for all P5.5 headline sections` |
| Ahead/behind | local `main` is 18 commits ahead, 0 behind |
| Local branches | only `main` |
| Remote-tracking branches | only `origin/main`; `origin/HEAD -> origin/main` |
| Remote | `origin https://github.com/Sid-DudeD017/HeatTrace.git` for fetch and push |
| Worktrees | one: repository root on `refs/heads/main` at `1114e5b` |
| Tags | none |
| Does `1114e5b` exist locally? | yes; it resolves to a commit |
| Local refs containing `1114e5b` | local `main` only |
| Remote refs containing `1114e5b` | none |

### P6-P11 commit chain after public `main`

The 18 unpublished commits are:

```text
92f4b57  P7 freeze and confirmatory dry-run
af3443b  P7 freeze binding and integrity checks
a5e1310  P7 provenance fixes
8fe9b56  P7 documentation correction
1ec25f7  P8 frozen 756-cell runner
48da438  P8 finalized-output repair
c240f48  P8 semantic validation
ba58555  P8 execution metadata/log checks
553dc86  P9 analysis and artifacts
6c193cb  P9 event-level analysis correction
250bbec  P9 generated artifacts update
5ff0d23  P9 H3/H2 corrections
37bdffb  P9 provenance update
d5b3c86  P10 audited H1-H5 checkpoint and P11 execution baseline
995a5b7  P11 archive, comparison record, report, and manuscript
85c2a60  P11 portable archive payload and provenance repair
287cc95  P11 external-source metadata repair
1114e5b  P11 reproduction-evidence/limitations correction
```

`995a5b7` is the initial P11 implementation commit. `1114e5b` is the local revision containing the complete corrected P11 state. The recorded 756-cell reproduction executed against `d5b3c86`; the analysis implementation is recorded as `995a5b7`.

### Working tree state

There are no tracked modifications, but the checkout is not clean:

- Untracked: local model directories under `data/models/`, reproduction copies under `data/reproductions/`, result/archive working copies, several local documents, `.site-publish/`, and two stray files named `tsc` and `vitest`.
- Ignored: `.env`, virtualenv/cache files, raw/processed/forecast/workload data, legacy benchmark/event files, canonical P8 run/checkpoint parquets, execution outputs, and Python caches.
- The important distinction is that the **P6-P11 source is committed locally**, but several files in the runner's expected runtime layout are untracked or ignored. Equivalent frozen copies of the model and P8/P9 artifacts are tracked inside the P11 archive.

This explains why GitHub `main` ends at P5.5: the local branch was advanced by 18 commits without advancing any remote ref. Nothing in the inspected refs indicates a second unpublished branch or tag.

## 3. Missing reproduction requirements

“Tracked” below means tracked at local revision `1114e5b`, not visible at public `origin/main`.

### Source, protocol, and runner

| Relative path | State at `1114e5b` | Approx. size | Essential? | Distribution |
|---|---|---:|---|---|
| `src/heattrace/thermal/heatguard.py` | tracked | 33 KB | yes | clean source snapshot |
| `src/heattrace/thermal/{facility,metrics,model,policies,scheduler,validation}.py` | tracked | about 115 KB total | yes | clean source snapshot |
| `src/heattrace/forecast/{calibration,dataset,evaluate_temperature,tiny_lstm,train_temperature}.py` | tracked | about 100 KB total | yes | clean source snapshot |
| `src/heattrace/experiments/p6_validity_runner.py` | tracked | 139 KB | yes; 756-cell runner | clean source snapshot |
| `src/heattrace/evaluation/p6_validity.py` | tracked | 79 KB | yes; tables/figures and hypothesis comparison | clean source snapshot |
| `src/heattrace/cli.py` | tracked | about 76 KB | yes; exposes `--run-p6-confirmation` | clean source snapshot |
| `configs/p6_validity.yaml` | tracked | 5.4 KB | yes | source snapshot plus SHA-256 manifest |
| `configs/p6_thermal.yaml` | tracked | 1.2 KB | yes | source snapshot plus SHA-256 manifest |
| `docs/p6_frozen_protocol.md` | tracked | 20 KB | yes | source snapshot plus SHA-256 manifest |
| `data/archive/heattrace_v1_d5b3c86/verify_archive.py` | tracked | 7.6 KB | yes for archive validation | source snapshot |
| `scripts/prepare_p11_package.py` | **missing** | — | yes before external handoff | create and test; copies verified archive payloads into runtime paths without changing bytes |
| `scripts/compare_p11_scientific_outputs.py` | **missing** | — | yes before external handoff | create and test; compare run IDs/scientific columns and derived artifacts |

### Event, control, blind, overlay, and provenance datasets

| Relative path | State | Size | Essential? | Distribution |
|---|---|---:|---|---|
| `data/events/heatwave_events_v0.parquet` | tracked | 15.8 KB | provenance/rebuild; not directly read by final runner | source/release asset |
| `data/events/control_catalogue_v0.parquet` | tracked | 11.5 KB | provenance/rebuild; not directly read by final runner | source/release asset |
| `data/benchmarks/p6_event_blind_pool.csv` | tracked | 78.6 KB | provenance/rebuild; not directly read by final runner | source/release asset |
| `data/benchmarks/p6_event_control_pairs.parquet` | tracked | 53.9 KB | **yes; direct simulation input containing the three heatwave/control/blind triplets** | release asset with hash |
| `data/benchmarks/p6_event_control_index.csv` | tracked | 1.8 KB | yes; frozen identity/provenance | release asset with hash |
| `data/benchmarks/p7_phase_label_overlay.parquet` | tracked | 15.8 KB | yes; direct simulation input | release asset with hash |
| `data/manifests/p7_confirmatory_dry_run_manifest.json` | tracked | 2.2 KB | yes; runner gate | release asset with hash |

The actual 756-cell runner reads the combined `p6_event_control_pairs.parquet`, not the three catalogue files independently. The catalogue files and blind pool are still needed to audit how the combined benchmark was formed.

### Frozen model and HeatGuard artifacts

The runtime copies under `data/models/` exist only locally and are untracked. Byte-identical archive copies below are tracked.

| Tracked archive path | Runtime destination | Size | Essential? | Distribution |
|---|---|---:|---|---|
| `data/archive/heattrace_v1_d5b3c86/frozen_models/p6_temperature_v2/artifact_manifest.json` | `data/models/p6_temperature_v2/artifact_manifest.json` | 6.2 KB | yes | release asset; verify before copy |
| `.../p6_temperature_v2/tiny_lstm_checkpoint.pt` | `data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt` | 27.1 KB | yes | release asset; hash before `torch.load` |
| `.../p6_temperature_v2/scaler.json` | `data/models/p6_temperature_v2/scaler.json` | 236 B | yes | release asset |
| `.../p6_temperature_v2/split_manifest.json` | `data/models/p6_temperature_v2/split_manifest.json` | 2.8 KB | audit | release asset |
| `.../p6_temperature_v2/evaluation_metrics.csv` | `data/models/p6_temperature_v2/evaluation_metrics.csv` | 2.2 KB | yes; forecast gate | release asset |
| `.../p6_temperature_v2/training_history.json` | `data/models/p6_temperature_v2/training_history.json` | 4.7 KB | audit only | release asset |
| `.../p6_heatguard_calibration_v3/calibration.json` | `data/models/p6_heatguard_calibration_v3/calibration.json` | 761 B | yes | release asset |
| `.../p6_heatguard_calibration_v3/manifest.json` | `data/models/p6_heatguard_calibration_v3/manifest.json` | 2.8 KB | yes | release asset |
| `.../p6_heatguard_calibration_v3/origins.json` | `data/models/p6_heatguard_calibration_v3/origins.json` | 8.2 KB | yes for artifact integrity | release asset |
| `.../p6_heatguard_calibration_v3/forecast_temperatures.npy` | corresponding runtime path | 25.6 KB | yes for artifact integrity | release asset |
| `.../p6_heatguard_calibration_v3/realized_temperatures.npy` | corresponding runtime path | 25.6 KB | yes for artifact integrity | release asset |
| `.../p6_heatguard_calibration_v3/residuals.npy` | corresponding runtime path | 51.0 KB | yes for artifact integrity | release asset |

### Historical data required during scoring

| Relative path | State | Size | SHA-256 | Essential? | Distribution |
|---|---|---:|---|---|---|
| `data/raw/noaa/GHCNh_USW00023234_2022.psv` | ignored, local only | 10.7 MB | `7b2c0793e99761763ffc3930114a64837b4680301e2a415f2a7940ac0d0a066e` | **yes** | separate data asset or reproducible download with hash |
| `data/raw/noaa/GHCNh_USW00023234_2024.psv` | ignored, local only | 12.0 MB | `5f4b0c8513e5793698886836795aa8b8a7dac5793ef4e4cb6a9368e7c4e7c1f3` | **yes** | separate data asset or reproducible download with hash |
| `data/raw/noaa/GHCNh_USW00023234_2023.psv` | ignored, local only | 11.2 MB | recorded in archive manifest | no for the 756-cell matrix; training/rebuild only | optional raw-data bundle |
| `data/raw/noaa/GHCNh_USW00023234_2025.psv` | ignored, local only | 11.6 MB | recorded in archive manifest | no for the 756-cell matrix; rebuild/provenance only | optional raw-data bundle |

Contrary to the current archive note, the confirmatory runner calls `load_noaa_hourly_series` while precomputing inference forecasts. The 2022 heatwaves and 2024 control/blind windows therefore require the 2022 and 2024 raw NOAA files even when the TinyLSTM checkpoint is not retrained. This must be corrected in the package documentation or removed by freezing the exact derived temperature inputs and changing the runner to consume them.

CAISO price and EIA carbon history used by the 756 cells is already embodied in the frozen combined benchmark parquet. Raw CAISO/EIA sources are required to rebuild that benchmark from scratch, not to rerun the frozen simulation.

### Original and expected output artifacts

All items below are tracked under `data/archive/heattrace_v1_d5b3c86/`; working copies under `data/results/` or `data/reproductions/` are ignored/untracked.

| Archive file | Size | Role | Distribution |
|---|---:|---|---|
| `canonical_p8/p6_validity_runs.parquet` | 63.6 KB | original 756-row baseline | release asset |
| `canonical_p8/p6_validity_checkpoint.parquet` | 63.6 KB | canonical checkpoint | release asset |
| `canonical_p8/p6_validity_manifest.json` | 2.3 KB | canonical run/hashes | release asset |
| `canonical_p8/p6_validity_execution.jsonl` | 259.8 KB | canonical execution log | release asset |
| `reproduction_p8/p6_validity_runs.parquet` | 63.1 KB | P11 reproduction baseline | release asset |
| `reproduction_p8/p6_validity_checkpoint.parquet` | 63.1 KB | P11 reproduction checkpoint | release asset |
| `reproduction_p8/p6_validity_manifest.json` | 2.3 KB | P11 reproduction manifest | release asset after path sanitization |
| `reproduction_p8/p6_validity_execution.jsonl` | 259.8 KB | P11 reproduction log | release asset |
| `canonical_analysis/p6_event_level_metrics.csv` | 74.7 KB | expected table | release asset |
| `canonical_analysis/p6_policy_pairwise_metrics.csv` | 299.6 KB | expected table | release asset |
| `canonical_analysis/p6_t1_cohort_provenance.csv` | 1.3 KB | expected table | release asset |
| `canonical_analysis/p6_t2_event_feasibility.csv` | 6.6 KB | expected table | release asset |
| `canonical_analysis/p6_t3_equal_service_gaps.csv` | 6.6 KB | expected table | release asset |
| `canonical_analysis/p6_t4_forecast_evidence.csv` | 2.6 KB | expected table | release asset |
| `canonical_analysis/p6_h1_h5_assessment.csv` | 2.6 KB | expected table | release asset |
| `canonical_analysis/figures/p6_f1_event_policy_contrasts.png` | 343 KB | expected figure | release asset |
| `canonical_analysis/figures/p6_f2_allocation_distance_status.md` | 748 B | expected status figure | release asset |
| `canonical_analysis/figures/p6_f3_forecast_regret_status.md` | 922 B | expected status figure | release asset |
| `canonical_analysis/figures/p6_f4_h1_sensitivity.png` | 202 KB | expected figure | release asset |
| `data/results/p11_reproduction_comparison.json` | 3.3 KB | expected scientific comparison summary | source snapshot |

The complete tracked P11 archive is about 3.0 MB and its self-verifier currently passes all 54 inventory entries.

### Frozen hashes that must gate execution

| Item | SHA-256 |
|---|---|
| `configs/p6_validity.yaml` | `46f132487b66c35e31f91ffa4f0e30db4825b0641ed10253283038e4be62e2f1` |
| `configs/p6_thermal.yaml` | `250f1b07daa6a19bcc9fe7415c7034b5ade240d69095cf3b539b7ee6ba001551` |
| `docs/p6_frozen_protocol.md` | `78cf42a1d0c6849628280b43db7b60dfa6bc3b227565bd84d0215e9e7cb25ede` |
| combined benchmark parquet | `60cea3627d9f81d3b2020e17930a6418b6aa0bfe3b292256e3949f76947dd109` |
| benchmark index CSV | `a57a777325c21cdbd343f8ec718734ad45d6cfbcfa293a80b29b324249a14b72` |
| phase overlay parquet | `7157a2e64efafa148aa276efc20c12893ad1e938ecf767c76a5ccd5e7c49da23` |
| TinyLSTM artifact manifest | `ae265bddc65c3eb06a978a06a6baa0f779b222925b4fa41d76d161d373160a79` |
| TinyLSTM checkpoint | `69e18ae35c7912387895702b9e0aabd084c42d1aad31ac0327ef70e3c92132ed` |
| HeatGuard calibration manifest | `bdf291a1db7c7c232f19e8aa22c59db6772ccd095caf5f1853b67e402e12096c` |
| expected run-ID digest | `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1` |

## 4. Secret-exposure and privacy risks

No credential value was printed during this audit.

### Findings

- `.env` exists locally, is ignored, and contains an API credential variable. It must never be copied, archived, committed, or included in support logs.
- The tracked source uses environment-variable names for EIA authentication. The high-confidence scan match in `src/heattrace/ingest/eia.py` is credential-handling code, not an embedded credential.
- No literal `WATTTIME` marker, private-key header, or common high-confidence GitHub/AWS/Bearer token pattern was found in the current tracked tree, the proposed P11 archive, reachable local history, or scanned unreachable blobs.
- This negative scan does **not** prove that previously public WattTime credentials are absent from GitHub history, forks, caches, pull-request refs, release assets, or reflogs not present in this checkout. The previously exposed WattTime credential must be considered compromised and revoked/rotated before any sharing.
- Absolute local paths occur in these tracked P11 artifacts and should be sanitized or explicitly classified as non-secret metadata before release:
  - `docs/p11_final_results_audit.md`
  - `data/archive/heattrace_v1_d5b3c86/canonical_analysis/docs/p6_validity_report.md`
  - `data/archive/heattrace_v1_d5b3c86/canonical_p8/p6_validity_manifest.json`
  - `data/archive/heattrace_v1_d5b3c86/reproduction_p8/p6_validity_manifest.json`
  - `data/archive/heattrace_v1_d5b3c86/reproduction_analysis/p6_analysis_manifest.json`
- Do not edit the canonical archive in place to remove those paths: that would invalidate its recorded hashes. If path privacy requires redaction, produce a separately named sanitized release copy with a new manifest, preserve the original canonical hashes in the audit record, and prove that scientific payloads are unchanged.
- The `.pt` checkpoint is a serialized object. Only load the hash-verified release copy from a trusted source; do not accept a replacement checkpoint from an untrusted party.

### Required pre-release security gate

1. Revoke/rotate the historical WattTime credentials and verify that no old token remains valid.
2. Build the candidate package in a new temporary directory from an explicit allowlist; never from `cp -R` of the working tree.
3. Exclude `.git`, `.env*`, raw authentication responses, shell history, logs with headers/query strings, `.venv`, caches, and all unrelated ignored/untracked files.
4. Run a maintained secret scanner (for example, Gitleaks and/or TruffleHog) against the candidate directory and, separately, every Git ref that would be published. Preserve only the redacted scanner report.
5. Inspect JSON/YAML/CSV/log outputs for `Authorization`, cookies, query-string keys, usernames, emails, home-directory paths, and cloud credentials.
6. Do not publish the current full Git history merely because the working tree scan is clean. If history cannot be conclusively audited, publish a new content-only source snapshot/repository with provenance pointing back to `1114e5b`.

## 5. Safe independent-sharing plan

### A. Frozen source revision

Use the tree content of `1114e5bab3fa4db83accfaffbb36e0b7478800cb` as the source snapshot. Do not silently substitute `d5b3c86` or public `563f6ac`.

Because the old public history previously contained credentials, the safest release is a new clean repository or signed source archive built from an allowlist, with:

- `SOURCE_REVISION.txt` recording `1114e5b...`;
- a SHA-256 manifest for every package file;
- no `.git` history from the old public repository;
- a fresh package commit/tag or release checksum/signature;
- the package-preparation and comparison scripts added and reviewed;
- an explicit statement that the original P11 execution baseline was `d5b3c86...`.

If a sanitized archive copy is necessary, give it a distinct release identifier and manifest. Never overwrite the canonical P11 evidence or describe a rehashed copy as byte-identical to the original archive.

The runner currently binds a new run's `execution_commit` to the checkout HEAD. In a clean snapshot repository, pass the new clean-package HEAD and record `1114e5b...` separately as `source_tree_origin`. Do not pretend the fresh package commit has the old SHA.

### B. Processed datasets and manifests

Ship a separate `heattrace-p11-data-v1` asset containing:

- the combined event/control/blind benchmark, index, phase overlay, and P7 dry-run manifest;
- NOAA 2022 and 2024 PSV files or a provider-approved deterministic download recipe plus their exact hashes;
- one top-level `SHA256SUMS` or JSON manifest with byte size, source URL/provider, retrieval date, transformation status, and license/terms reference;
- no raw API responses that contain credentials or request headers.

NOAA data is generally open/public-domain when NOAA-produced, but source attribution and dataset-specific notices still apply ([NOAA/NCEI open-data policy](https://www.ncei.noaa.gov/sites/default/files/2023-12/NCEI%20PD-10-2-02%20-%20Open%20Data%20Policy%20Signed.pdf)). EIA permits API-derived use subject to attribution and non-misrepresentation ([EIA API terms](https://www.eia.gov/opendata/terms-of-service.php)). CAISO allows use of much public website material with credit and notices intact, but its API/data terms retain proprietary language; confirm the exact OASIS redistribution basis and preserve CAISO attribution before publishing transformed market data ([CAISO terms](https://www.caiso.com/privacy-terms-of-use)). If that review is inconclusive, distribute a downloader/transform recipe and hashes rather than republishing CAISO raw files.

### C. Frozen configuration and model checkpoints

Ship the three frozen specifications and the complete TinyLSTM/HeatGuard artifact directories. The package preparation script must:

1. verify `archive_manifest.json` and every nested model hash;
2. copy, never regenerate, model bytes into `data/models/...`;
3. verify destination hashes again;
4. refuse overwrite unless the destination is absent or already byte-identical.

### D. Dependency/environment setup

The repository has no lock file. `pyproject.toml` declares only pandas, pyarrow, and PyYAML; `torch` is optional and NumPy, SciPy, and Matplotlib are used but not fully declared. The audited host used:

```text
Python 3.13.3, macOS 15.6.1 arm64
pandas 3.0.3; pyarrow 24.0.0; PyYAML 6.0.3; numpy 2.4.6
scipy 1.17.1; matplotlib 3.11.2; torch 2.13.0; pytest 9.1.1
```

Before the 756-cell rerun:

- declare NumPy, SciPy, and Matplotlib in appropriate project extras;
- keep PyTorch in a documented simulation/ML extra;
- generate a cross-platform lock/constraints set with hashes and record Python/platform compatibility;
- test at least Windows x86-64, macOS arm64, and Linux x86-64 in CI;
- set deterministic seeds and CPU execution, and record package versions plus BLAS/PyTorch build metadata.

Provisional setup commands (replace with the checked-in locked install once created):

**Windows PowerShell**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev,ml]" numpy scipy matplotlib
```

**macOS/Linux**

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,ml]' numpy scipy matplotlib
```

These are bootstrap commands, not a dependency freeze. A genuine reproduction claim requires the release lock/constraints file.

### E. Cross-platform preparation and preflight

After `scripts/prepare_p11_package.py` exists, use the same logical commands on all platforms:

```text
python scripts/prepare_p11_package.py --archive data/archive/heattrace_v1_d5b3c86 --data-asset <path-to-data-asset> --verify-only
python scripts/prepare_p11_package.py --archive data/archive/heattrace_v1_d5b3c86 --data-asset <path-to-data-asset> --materialize
python data/archive/heattrace_v1_d5b3c86/verify_archive.py
python scripts/p11_preflight.py --require-empty-output data/reproductions/external_p11
```

Use `.venv\Scripts\python.exe` on Windows and `.venv/bin/python` on macOS/Linux in place of `python`.

### F. Exact 756-cell command

Once preflight passes, run from the repository root into an empty, dedicated output tree. If the sanitized package HEAD is `<PACKAGE_HEAD_40_HEX>`:

```text
python -m heattrace.cli --run-p6-confirmation --execution-commit <PACKAGE_HEAD_40_HEX> --data-dir data/reproductions/external_p11
```

The current CLI interprets `--data-dir` only for the output directory in this command; frozen inputs still resolve under repository `data/`. The preflight script must check this explicitly. Do not copy canonical P8 outputs into the new output directory, or the runner will report `ALREADY_COMPLETED` instead of rerunning 756 cells.

### G. Exact table/figure regeneration command

The existing module entry point assumes canonical output hashes and paths, so use the explicit function call for a reproduction (or add a proper CLI wrapper before release):

```text
python -c "from heattrace.evaluation.p6_validity import run_phase_9_analysis; run_phase_9_analysis(runs_path='data/reproductions/external_p11/results/p6_validity_runs.parquet', manifest_path='data/reproductions/external_p11/results/p6_validity_manifest.json', execution_path='data/reproductions/external_p11/results/p6_validity_execution.jsonl', checkpoint_path='data/reproductions/external_p11/results/p6_validity_checkpoint.parquet', results_dir='data/reproductions/external_p11/analysis/results', figures_dir='data/reproductions/external_p11/analysis/figures', docs_dir='data/reproductions/external_p11/analysis/docs', check_baseline_hashes=False)"
```

Before release, replace this fragile one-liner with `scripts/regenerate_p11_analysis.py` using the same arguments. The analysis currently reads `data/results/p6_forecast_metrics.csv` through a hard-coded path; preflight must verify that tracked frozen file or the analysis function should accept it as an explicit argument.

### H. Comparison against original P11 outputs

Create `scripts/compare_p11_scientific_outputs.py` and run:

```text
python scripts/compare_p11_scientific_outputs.py --candidate data/reproductions/external_p11 --reference data/archive/heattrace_v1_d5b3c86 --report data/reproductions/external_p11/comparison.json
```

The comparison must:

1. verify 756 rows, 756 unique run IDs, and the exact run-ID digest;
2. align rows by `run_id`, never by parquet order;
3. compare all 44 recorded non-operational/scientific columns exactly;
4. allow differences only in `execution_commit`, `runtime_seconds`, and execution-log timestamps/paths;
5. verify cohort counts `432/216/72/36`;
6. require all rows `SUCCESS`, all 36 oracle rows `deployable == false`, and zero development triplet/window IDs;
7. compare the seven CSV tables and four deterministic figure/status artifacts byte-for-byte to `canonical_analysis` hashes;
8. reproduce H1-H5 verdicts exactly;
9. exit nonzero for every mismatch and write a machine-readable report.

### I. Simulation reproduction versus raw-data rebuilding

These are separate claims:

- **Simulation reproduction:** start from frozen processed benchmark rows, the frozen NOAA inference history, frozen model/checkpoint/calibration artifacts, configs, and source; rerun the 756 cells and analysis. No live API credentials are needed.
- **Raw-data reconstruction:** reacquire NOAA, CAISO, and EIA sources; reproduce alignment, event detection, matching, carbon/price processing, model training, and calibration; then recover the frozen hashes. This requires provider-specific download instructions, dates/versions, attribution/terms, potentially API keys supplied privately by the reproducer, and much more storage. It must not be implied by a successful frozen simulation rerun.

## 6. Test-failure diagnosis and environment fixes

The teammate's `214 passed, 41 failed, 3 errors, 3 skipped` result is consistent with testing public P5.5 source against an incomplete checkout. It cannot validate P11 because those tests and modules are absent there.

For this audit, a clean `git archive` of local `1114e5b` was tested with the existing environment and pytest plugin autoload disabled. Result: **462 passed, 115 failed, 31 errors, 6 skipped in 426.59 seconds**. The failures are dominated by missing production-layout data, not by one cross-platform numerical discrepancy.

### Tests coupled to ignored or unmaterialized production data

| Test module | External/ignored assumptions |
|---|---|
| `tests/test_p2_alignment.py` | `data/raw/eia/CISO.xlsx` and production processed data |
| `tests/test_p3_controls_benchmark.py` | copies full `data/raw`, `data/events`, `data/benchmarks`, and `data/workloads` trees |
| `tests/test_p3_events.py` | raw NOAA/EIA plus `data/processed/hourly_caiso_v0.parquet` and production event files |
| `tests/test_p4_manifests_forecasts.py` | legacy ignored benchmark parquet and production manifests |
| `tests/test_p4_metrics_runner.py` | benchmark, workloads, events, processed, and forecast trees |
| `tests/test_p5_experiments.py` | ignored benchmark, processed history, workload, forecasts, results, and sampling manifests |
| `tests/test_p5_5_experiments.py` | ignored legacy benchmark parquet and production baseline hashes |
| `tests/test_p6_event_bundle.py` | raw CAISO/EIA, event catalogues, and materialized benchmark trees |
| `tests/test_p6_heatguard.py` | untracked runtime `data/models` and ignored raw NOAA |
| `tests/test_p6_validity_analysis.py` | ignored canonical `data/results/p6_validity_*` files instead of archive fixtures |
| `tests/test_p6_validity_runner.py` | untracked runtime models and ignored canonical results/checkpoints/logs |

### Required test design fixes

- Add small, synthetic, immutable fixtures under `tests/fixtures/` for unit tests. Fixtures should cover schemas, time boundaries, provenance failures, and one or two tiny scheduling cells without reading repository production data.
- Mark provider/raw-data tests `integration` or `external_data`; require an explicit dataset root and validate its manifest before running.
- For optional production data, skip with an explicit reason and acquisition URL/manifest identifier. Do not let an integration test become an unhandled `FileNotFoundError`.
- For scientific reproduction, missing files, wrong hashes, wrong schema, or a nonempty output directory must be hard failures. Never generate synthetic substitutes or silently fall back to locally available data.
- Make fixture roots explicit through pytest fixtures/environment configuration rather than `Path("data/...")` relative to the current working directory.
- Point P6 baseline tests to the tracked archive or copy its files into `tmp_path`; do not assume ignored working copies exist.
- Add CI jobs for `unit`, `integration-with-release-data`, and `p11-reproduction-preflight` so their requirements and expected skips are visible.

### Undeclared/import-path issues

- Declare direct dependencies: NumPy, SciPy (`src/heattrace/analysis/characterization.py`), and Matplotlib (figure modules).
- Document/install PyTorch for the simulation and checkpoint loader; the existing `ml` extra is insufficient for a complete analysis environment unless combined with plotting/scientific extras.
- Retain `src`-layout installation (`pip install -e .`) as the supported path. `pytest.ini` currently injects `src`; that can hide packaging/import defects, so also test the installed wheel in CI without `pythonpath = ["src"]`.
- Disable or constrain unrelated third-party pytest plugin autoload in the documented test command. In this sandbox, `pytest-rerunfailures` attempted to bind a local socket before collection; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoided that unrelated failure.

Recommended test commands after fixture separation:

```text
python -m pytest -m unit
python -m pytest -m integration --external-data-root <verified-data-root>
python -m pytest tests/test_p6_validity_runner.py tests/test_p6_validity_analysis.py
```

## 7. Artifact comparison and exact verification criteria

A genuine independent reproduction is accepted only if all of the following hold:

1. The clean package manifest and all input hashes verify before execution.
2. The environment lock verifies and the environment report records OS, architecture, Python, package versions, and CPU/BLAS/PyTorch details.
3. The output directory was empty; the manifest says `cells_executed_in_this_session == 756` and `execution_resumed_from_checkpoint == false`.
4. There are exactly 756 rows and 756 unique run IDs; digest is `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1`.
5. Cohorts are exactly: core 432, event-blind 216, algorithm comparators 72, oracle 36.
6. All rows are `SUCCESS`; all oracle rows are non-deployable; no development ID appears.
7. All nine frozen hashes and all workload hashes in every row match the release manifest.
8. After run-ID alignment, all 44 scientific/non-operational columns equal the canonical P11 reference exactly. Only execution commit, runtime, log timestamps, and package-specific paths may differ.
9. Seven analysis CSVs and four figure/status artifacts match the canonical hashes byte-for-byte.
10. Verdicts are exactly H1 `SUPPORTED`, H2 `PARTIALLY_SUPPORTED`, H3 `PARTIALLY_SUPPORTED`, H4 `NOT_ESTIMABLE`, and H5 `NOT_SUPPORTED`.
11. Unit tests pass. Integration tests either pass with the documented dataset or skip explicitly; no missing-data error is reported as a product defect.
12. The raw-data reconstruction claim remains false unless NOAA/CAISO/EIA reacquisition and the complete upstream transformation pipeline are independently run and hash-verified.

## 8. What must be given to the teammate

Minimum handoff:

1. A security-scanned, content-only source snapshot derived from local `1114e5b`, with source provenance and a new clean package revision.
2. The tracked 54-file P11 archive and its verifier/manifest.
3. A separate verified data asset containing NOAA 2022 and 2024 history (or an exact downloader) and the runtime benchmark inputs.
4. A package-preparation script that materializes frozen models into `data/models` and refuses hash mismatches/overwrites.
5. A lock/constraints set and platform-specific environment instructions.
6. A preflight script, the exact 756-cell command, and an empty output location.
7. A table/figure regeneration wrapper and the scientific comparison script.
8. The verification checklist above, provider attribution/terms, and an explicit statement that this is simulation reproduction, not raw NOAA/CAISO/EIA reconstruction.

## 9. Shortest safe path

1. Rotate/revoke the exposed WattTime credential.
2. Build and secret-scan an allowlisted, content-only source release from `1114e5b`; do not publish the old history.
3. Add only the packaging/preflight/comparison wrappers and dependency lock, review them, and create a new clean package revision without changing frozen experimental bytes.
4. Publish the verified 3 MB P11 archive plus the separately licensed/hash-manifested NOAA 2022/2024 data asset.
5. Have the teammate create a fresh environment from the lock, materialize inputs, run preflight, execute all 756 cells from an empty output directory, regenerate analysis, and run the fail-closed comparison.
6. Accept reproduction only against the exact criteria in Section 7.

This route avoids pushing unverified history, avoids sharing credentials, preserves frozen scientific inputs, and produces a defensible third-party simulation reproduction.
