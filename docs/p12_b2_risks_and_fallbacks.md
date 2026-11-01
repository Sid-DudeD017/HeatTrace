# P12 Track B2 risks and fallbacks

**Status:** planning risk register; no B2 experiment has been executed.

## 1. Scientific and engineering risk register

| Risk | Consequence | Detection | Mitigation/fallback | Decision impact |
|---|---|---|---|---|
| Too few independent regional episodes | station count exaggerates evidence | episode overlap graph and year counts | report station results nested in episodes; extend years later; use registered report | LIMITED, not INVALID |
| Simultaneous statewide heat counted repeatedly | pseudo-replication | 24h-buffer overlap components; strict/48h sensitivity | regional episode is independent unit | INVALID if ignored |
| Station hourly gaps or moves | biased threshold/event catalogue | station metadata snapshot and coverage report | predeclared Sacramento replacement; drop failing station before outcomes | LIMITED |
| 2026 incomplete/provisional source data | partial-season selection bias | file-level coverage through Sep 30 and source release dates | exclude 2026 primary; retain later sensitivity | LIMITED |
| CAISO historical access gaps | no aligned price data | hub/year coverage audit | use official historical downloader; prioritize NP15 stations; do not fabricate | LIMITED/INVALID per window |
| Hub is not facility tariff | overclaiming economic realism | mapping review | call it regional DAM hub signal; preserve mapping limitation | claim limitation |
| One CISO carbon proxy across all stations | cannot identify geographic carbon variation | source matrix | frame G2 as weather/price/thermal heterogeneity; no local carbon claim | claim limitation |
| EIA data-quality flags | carbon comparisons may be fragile | per-hour flags and exclusion sensitivity | retain flags; sensitivity excluding/marking affected hours | LIMITED |
| SFO TinyLSTM applied to other stations | invalid cross-station forecast/calibration | artifact station ID gate | station-specific same-architecture artifacts or causal previous-day primary | INVALID if ungated |
| Variable-duration workloads change exposure | unfair event comparisons | demanded-slot/intensity checks | constant arrival intensity, matched trace hashes, normalized metrics | INVALID if unequal |
| Long events lack same-year controls | confounded cross-year contrast | candidate audit | nearest-year fallback only with LIMITED label; ordinary distribution | LIMITED |
| Ordinary windows overlap heavily | ordinary sample pseudo-replication | overlap graph/effective sample count | non-overlap priority; cluster/blocked resampling | LIMITED |
| G4 destroys temporal continuity | uninterpretable peak-day comparison | history/state/deadline validation | defer G4 rather than truncate arbitrarily | NOT ESTIMABLE |
| Outcome leakage in selection | invalid benchmark-validity claim | schema-level ban on result columns; audit access logs | rebuild before outcomes; fail closed | INVALID |
| Full matrix exceeds seven days | no reproduction/paper time | dry-run count and pilot timing | tiered primary matrix; K=20; defer full ordinary sensitivity | LIMITED |
| Clean checkout cannot restore inputs/models | external reproduction failure | clean environment rehearsal | lock dependencies, retrieval/restore scripts, checksum manifest | no GO |
| Credential exposure | security incident/publication delay | current/history secret scan without printing values | rotate/revoke, purge only through separately approved process, sanitize bundle | stop release |
| Negative/null results | perceived weak result | preregistered decision rules | report valid negative benchmark evidence; do not tune events/policies | NEGATIVE but valid |

## 2. Station fallback ladder

### Five-station target

SFO, Sacramento, Fresno, Redding and LAX; three hubs and four climate roles.

### Three-station minimum empirical paper

SFO + Sacramento + Fresno, provided they produce multiple regional episodes in at least two years. This preserves coastal/inland contrast and adds ZP26. Redding is preferred over LAX if it adds independent episodes; LAX is preferred if SP15 coverage and southern-coastal contrast are more valuable.

### Two-station limited study

SFO + Sacramento provides a controlled climate contrast under the same NP15 signal. This isolates thermal/geographic effects better but cannot support a broad multi-region claim. Use a bounded case-series framing or GREENS registered report.

### One-station outcome

SFO-only multi-year work is temporal replication, not Track B2 multi-station external validity. Do not submit it as multi-region evidence.

## 3. Seven-day fallback triggers

| Checkpoint | Trigger | Immediate scope change |
|---|---|---|
| End Day 2 | fewer than three stations pass NOAA + hub coverage | freeze passing NP15 pair first; evaluate GREENS registered report path |
| Mid Day 3 | fewer than two independent years/episodes | stop scheduler scale-up; expand event audit or classify temporal replication non-estimable |
| End Day 4 | fewer than 10 ordinary windows per event | drop G3 for that event or use a prespecified broader-year pool with LIMITED label |
| First 10% Day-5 pilot | runtime >3x estimate or validation failures >2% | K=20, primary condition only; defer full-grid sensitivities |
| End Day 6 | G4 continuity gate fails | mark G4 NOT ESTIMABLE and omit ablation claims |
| Day 7 reproduction | any scientific mismatch | no GO; fix packaging only or report INVALID/BLOCKED |

## 4. Publication-preserving decisions

- A valid null/negative G1 or G3 result is scientifically preferable to adding favorable events.
- If geographic coverage is limited, emphasize protocol, episode-aware design and ordinary-window distributions rather than claiming statewide generality.
- If only the protocol is mature by the deadline, GREENS offers a registered-report path; do not rush unverified results.
- Keep HotCarbon 2027 as a later option. Its 2027 deadline is not announced as of this plan.

## 5. Reproduction recovery actions

Before B2 execution or public handoff:

1. Generate and commit a dependency lock with Python/platform metadata.
2. Add `scripts/prepare_p11_package.py` or equivalent to restore verified v1 archive models into runtime paths without byte changes.
3. Add raw NOAA retrieval/verification commands or freeze exact derived forecast inputs.
4. Add a clean-checkout B2 acquisition/prepare/run/analyze/compare workflow.
5. Store expected hashes in a signed release manifest.
6. Run tests and a zero-checkpoint reproduction in a new environment.
7. Have a teammate reproduce without access to the original `.env` or untracked cache.

The old reproduction report's remote-behind diagnosis is historical; local `origin/main` now points to the same `ef506a5` commit. Packaging blockers remain relevant.

## 6. Security gate

Do not expose, print or migrate credentials while preparing the package. The prior WattTime credential incident requires explicit verification that the credential was revoked/rotated, but this plan does not alter Git history. `.env`, AWS credentials, API keys and local logs must be excluded from all archives.

**Track B2 implementation plan prepared. No new scientific experiments have been executed.**
