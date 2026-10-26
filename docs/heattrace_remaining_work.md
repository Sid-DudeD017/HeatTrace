# HeatTrace remaining work after P11

## A. Essential v1 release/reproducibility blockers

1. Correct two P11 record errors: "756 cells were not rerun" (`docs/p11_v1_reproduction_report.md:161`) and CONF2 H3 `23/36` (`:100`) versus corrected `24/36` (`docs/p6_validity_report.md:134-140`).
2. Pin the exact environment. Current requirements are lower bounds only (`pyproject.toml:1-24`).
3. Provide a clean-checkout reproduction script/README: restore archived models/calibration to runtime paths, retrieve/verify raw NOAA, run 756 cells to a new directory, regenerate analyses, compare scientific fields, and verify the archive.
4. Resolve artifact tracking policy. Current root P8 logs/manifests, model directories, reproduction directory, and validity report are untracked/ignored; durable evidence lives in the committed archive.
5. Run and record the full offline test suite in the pinned clean environment, not only P11's 5+24 focused tests (`docs/p11_v1_reproduction_report.md:134-138`).
6. Create a v1 tag/release and immutable public archive only after the above. No tag currently exists.
7. Finish the manuscript bibliography/related work and venue formatting. Current manuscript is explicitly preliminary (`docs/heattrace_v1_preliminary_manuscript.md:1-111`).

## B. Scientific limitations that do not invalidate v1

- N=3 bounded case series; two events are from September 2022 and are not IID.
- All matched controls are June 2024, which can mix heatwave effects with year/season/regime effects.
- Simulated PUE/capacity and synthetic jobs; no data-center telemetry.
- Coarse 1x/2x/3x feasibility grid and weak low-curve sensitivity.
- Production-average carbon proxy with EIA quality flags, not marginal/avoided emissions.
- One null event; CONF1 control discriminates as much as heatwave; no strict reversals.
- No confirmatory allocation vectors, forecast arms, or phase metrics.
- Greedy oracle can leave work incomplete and must not support superiority claims.

These are catalogued at `docs/p6_validity_report.md:294-311`.

## C. Planned Days 15–21 extension (not executed)

Git history ends at P11 and contains no P12–P18 implementation. The dashboard labels the following as separately versioned exploratory work (`docs/heattrace-14-day-review.html:88,137-143,395`):

| Day | Planned work | Required boundary |
|---|---|---|
| 15 | Freeze v2; preserve v1; restore phase pipeline. | No v1 mutation. |
| 16 | Materialize about 20–30 eligible ordinary windows per heatwave without scheduler outcomes. | Outcome-blind selection; correlated robustness samples, not new events. |
| 17 | Heatwave-versus-ordinary discriminability. | Report per-event distributions; do not claim superiority if ordinary windows behave similarly. |
| 18 | Same scheduler with TinyLSTM, previous-day, and realized-temperature oracle arms; retain hourly traces. | Oracle non-deployable; all other inputs fixed. |
| 19 | Forecast -> PUE/capacity -> allocation -> outcome analysis. | Equal service and causal arm isolation. |
| 20 | Phase-aware descriptive analysis; optional full-event vs isolated-day ablation. | Preserve equal exposure, causal lookback, arrivals/deadlines and cross-boundary state or defer. |
| 21 | Reproduce/audit v2 and update only exploratory claims. | Preserve nulls and keep additional events separate from v1. |

Additional historical events (candidate 2020/2021/2024) are a separate replication track, not replacements for null v1 cases (`docs/heattrace-14-day-review.html:367-373`).

## D. Optional future research

- Continuous feasibility-boundary search after preregistration.
- Real facility telemetry and calibrated PUE/thermal dynamics.
- Same-year or regime-balanced controls and multiple CAISO nodes/regions.
- Production workload traces with resource heterogeneity.
- Marginal-emissions signals with appropriate causal interpretation.
- Formal DRO/Benders/battery/renewable implementation only as a new project, never mislabeled as existing HeatTrace.
- Independent implementation and external reproduction on Linux/containerized environments.

## Priority before the professor meeting

No new experiment is required. Bring the four figures, the triplet index, T1–T4, and the P11 comparison. Be ready to state the two P11 documentation discrepancies, the clean-checkout limitation, and the precise non-claims. If time permits, correct the P11 report and add a one-page reproduction command sequence, but do not alter scientific artifacts or rerun/tune anything.
