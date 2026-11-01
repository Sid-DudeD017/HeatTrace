# 9. Reproducibility, audits, and defects

## 9.1 What P11 established

P11 reran all 756 frozen v1 cells from zero checkpoint state on the same repository/host lineage. It produced 756 successes, the same run-ID digest, equality across all 44 real non-operational columns, identical downstream tables/figures, and a 54-file archive whose verifier passes. It did not reacquire NOAA/CAISO/EIA, reproduce in a fresh locked environment, preserve the exact launch shell command, or establish third-party clean-clone execution. `docs/p11_final_results_audit.md` also corrects contradictions/nonexistent field names in the original P11 report.

## 9.2 Stage 1 and Stage 2

The only audit file present here is the Stage 2 report. It says it independently reverified Stage 1 quantitative claims, ran 84 B2 tests, verified the 54-file v1 archive, inspected all 6,480 B2 rows, and executed one controlled cell. These are conclusions from that report, not newly repeated executions in this documentation task.

Stage 2 verdict: BLOCKED. Its primary defect is unsanctioned SFO forecast/scaler/calibration transfer across 3,960 non-SFO forecast-aware cells. Other major issues are 7/66 heatwave core trios with equal service (zero at 2×/3×), 146/240 overlapping ordinary windows, blanket 2022 exclusion for one off-event EIA gap, and nine unexecuted G5 sensitivities.

## 9.3 Clean-clone audit

At current `HEAD ef506a5`, `git ls-files` returns no B2 protocol, code, docs, data, results, or Stage 2 report. All are untracked. `.gitignore` ignores `*.parquet`, including the canonical B2 result table. Therefore a clean clone of `origin/main` cannot reconstruct B2 P1–P6. Missing tracked sources include:

- `scripts/p12_b2_acquire_sources.py`, `scripts/p12_b2_detect_events.py`
- `src/heattrace/process/p12_b2_coverage.py`, `p12_b2_events.py`, `p12_b2_windows.py`
- `src/heattrace/experiments/p12_b2_runner.py`
- `src/heattrace/evaluation/p12_b2_validity.py`, `p12_b2_reporting.py`
- B2 tests, protocol, phase reports, manifests, catalogues, matrix, checkpoints, and result artifacts.

Even if source were tracked, `data/v2/models/` does not exist, so station-specific training/calibration recipes/artifacts are absent.

## 9.4 Numerically reproducible versus scientifically valid

A deterministic invalid procedure can reproduce perfectly. The one-cell Stage 2 probe matching the frozen row shows execution determinism, not protocol compliance. Likewise, 84 passing tests show tested invariants; they do not validate station transfer, causal claims, independence, or equal-service estimability.

## 9.5 Cell-count discrepancy

The reported 3,960 affected cells is correct when selecting all non-SFO rows for the four forecast-dependent policies. A confusing audit narrative can arise because the 5,940 total non-SFO rows are partitioned into 2,016 static and 144 oracle unaffected cells plus 3,960 affected cells. The policy/station breakdown is LAX 1,440, RDD 1,080, SAC 720, FAT 720. Always state the filter, not only the total.

## 9.6 Real defects versus nulls

- Protocol defect: cross-station transfer; affected comparisons invalid.
- Design weakness: overlap and severe equal-service attrition; estimability/uncertainty weakened.
- Missing experiment: G4 and nine G5 variants; non-estimable.
- Null/negative result: boundary shifts mostly zero, G2 CI crosses zero, only 1/4 G3 events exceeds P95, HeatGuard fails to win. These are scientifically legitimate outcomes, not software bugs.

## 9.7 Repair order

1. Track all code/protocol/manifests and define artifact distribution/storage.
2. Implement the frozen causal previous-day fallback or leakage-safe station-specific models.
3. Rerun the 3,960 affected cells under a versioned corrected matrix.
4. Freeze exact estimands before inspecting corrected outcomes.
5. Enforce or model ordinary-window dependence.
6. Redesign workload/capacity support so equal-service comparisons are estimable.
7. Prospectively log hourly allocation/backlog state and run G4.
8. Execute and label all G5 variants or narrow the claim.
9. Harmonize the +5.33/+4.12/+4.25 G5 estimand.

