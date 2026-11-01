# P12 Track B2 workshop submission roadmap

**Primary target:** GREENS 2027  
**Verified submission deadline:** 2026-11-13, Anywhere on Earth  
**Potential later target:** HotCarbon 2027; deadline not announced as of 2026-10-29.  
**Status:** planning only; no Track B2 results exist.

## 1. Submission framing

Working framing:

> A multi-year, multi-station historical heatwave evaluation of sustainable cloud schedulers.

The contribution should be presented as:

1. outcome-blind construction of complete heatwave, matched-control and representative ordinary-window benchmarks;
2. episode-aware treatment of simultaneous multi-station heatwaves;
3. external-validity testing across California climate regions, years and CAISO hub signals;
4. transparent thermal feasibility and equal-service policy evaluation;
5. reproducible reporting of positive, null and negative cases.

It is not a new algorithm paper, a real data-center failure study, or a claim of avoided emissions.

## 2. GREENS paper paths

GREENS 2027 currently lists four contribution types. Two are realistic:

### Emerging research paper (up to 8 pages)

Use only if the GO gate passes by the internal evidence freeze. Essential evidence:

- at least three eligible stations spanning coastal/inland and at least two hubs;
- multiple independent regional episodes across at least two years;
- complete G1-G3 primary analysis with 20 ordinary windows per event where feasible;
- bounded G5 sensitivity;
- zero-checkpoint reproduction and artifact manifest;
- explicit threats, nulls and non-claims.

### Registered report (6 pages + 2 pages references)

Preferred fallback if data coverage, episode count or reproduction is incomplete. Submit the frozen B2 design without implying results. This is especially defensible because B2 is confirmatory/quantitative and outcome selection is a core validity concern.

Position paper or extended abstract should be used only if neither empirical nor registered-report quality is reached.

## 3. Essential versus deferred experiments

| Priority | Experiment | GREENS necessity | Deferral rule |
|---:|---|---|---|
| 1 | Multi-station/year source coverage and station metadata | essential | none |
| 2 | Station events + regional episode grouping | essential | none |
| 3 | Complete event vs matched control under primary power-capped/medium condition | essential | none |
| 4 | 20 representative ordinary windows/event and G3 distribution | essential for benchmark-validity claim | minimum 10 gives LIMITED |
| 5 | Static/capacity/full-thermal policies and equal-service checks | essential | none |
| 6 | HeatGuard/oracle on event/control | useful continuity with v1, not the main novelty | may be secondary if artifacts unavailable |
| 7 | Low/energy-only and bounded cap/threshold sensitivity | essential threat check, but bounded | full factorial may defer |
| 8 | G4 isolated hot-day continuity ablation | optional/conditional | defer if continuity gate fails |
| 9 | K=30 ordinary windows and full v1 grid on all windows | optional second week | defer first |
| 10 | New forecast architecture or HeatGuard redesign | out of scope | separate project |

## 4. Calendar from 2026-10-29

| Date | Milestone |
|---|---|
| Oct 29 | Plan/protocol draft; repository and security audit |
| Oct 30 | Freeze protocol/config and station eligibility rules |
| Oct 31-Nov 1 | Source acquisition/coverage and event/episode catalogue |
| Nov 2 | Controls, ordinary windows and dry-run matrix freeze |
| Nov 3 | Primary execution with checkpoints |
| Nov 4 | Analysis and bounded sensitivities |
| Nov 5 | Zero-checkpoint reproduction and artifact freeze |
| Nov 6 | Internal GO/LIMITED/NEGATIVE/INVALID decision; choose paper type |
| Nov 7-9 | Draft methods/results/threats and figures |
| Nov 10 | Teammate reproduction/review and claim audit |
| Nov 11 | IEEE format, references, artifact instructions |
| Nov 12 | Final proof, source/result hash check, submission rehearsal |
| Nov 13 AoE | Submission deadline; submission itself requires human authorization |

## 5. Paper evidence package

Required tables/figures:

1. Station, climate class, hub mapping and coverage table.
2. Station-event timeline grouped by regional episode and year.
3. Complete-event vs ordinary-window discriminability distributions.
4. Feasibility/violation effects by episode with station observations nested.
5. Geographic heterogeneity plot with explicit low sample warnings.
6. Robustness table for threshold, curve, cap and episode grouping.
7. Reproduction/provenance table with run counts, hashes and failures.

Required threats:

- airport representativeness;
- regional hub versus facility tariff;
- shared CISO carbon signal;
- simulated PUE/capacity and synthetic jobs;
- correlated statewide episodes;
- incomplete/provisional 2026 data;
- variable-duration exposure;
- forecast-domain shift and calibration;
- ordinary-window dependence;
- production-average rather than marginal carbon.

## 6. Novelty assessment

Potentially stronger scientific contributions:

- regional-episode-aware multi-station heatwave benchmarking;
- distributional comparison against many outcome-blind ordinary windows;
- replication of feasibility/discriminability across climate regimes and years;
- full-event continuity analysis if valid.

Mostly engineering extensions:

- parameterizing station/node IDs;
- acquiring additional years;
- scaling the runner and storage;
- producing more manifests without a stronger analysis design.

HeatGuard and TinyLSTM reuse provide continuity, not new algorithmic novelty.

## 7. Readiness decision

- **GO emerging paper:** all essential evidence and reproduction gates pass; results may be positive, mixed or negative.
- **GO registered report:** protocol and feasibility audit are strong but execution/reproduction is incomplete or sample size is uncertain.
- **LIMITED abstract/position:** fewer than three stations or only descriptive episode evidence, but methodology is useful.
- **NO SUBMISSION:** invalid selection, pseudo-replication, unreproducible outputs, security issue, or claims exceed evidence.

## 8. Non-claims

Do not claim actual data-center failures, HeatGuard superiority, forecast-caused regret, 756 independent events, independent electricity markets per station, verified avoided emissions, statewide generality from correlated stations, or completed B2 results before execution.

## 9. Venue verification

- GREENS 2027 official call, contribution types and page limits: <https://greensworkshop.github.io/>
- ICSE/GREENS official date listing (November 13, 2026, AoE): <https://conf.researchr.org/home/icse-2027/greens-2027>
- HotCarbon official program page (2027 details currently to be announced): <https://hotcarbon.org/program>

Recheck all venue dates and formatting rules immediately before submission; this planning snapshot is dated 2026-10-29.

**Track B2 implementation plan prepared. No new scientific experiments have been executed.**
