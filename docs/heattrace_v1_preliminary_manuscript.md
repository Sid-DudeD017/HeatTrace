# HeatTrace v1: Evaluating Thermal Feasibility and Capacity Awareness under Historical Grid Stress

**Status:** Preliminary Manuscript Draft (Phase 11 / Days 13–14)
**Scientific Decision:** LIMITED RESULT
**Runner Execution Commit:** `d5b3c86ac9076b118644e32dd2c8b6ab6f7cab2d`
**Analysis Implementation Commit:** `995a5b76a5cc1233213c52cdf5b8443d849e23f3`
**Archive Reference:** `data/archive/heattrace_v1_d5b3c86/`

---

## 1. Bounded Research Question

Modern computing infrastructure faces operational stress during regional grid heatwaves, where ambient temperature surges elevate cooling requirements and diminish effective IT capacity under fixed facility power envelopes. The HeatTrace v1 project investigates the empirical validity of thermal-aware workload scheduling during historical grid stress events in CAISO territory.

Specifically, the confirmatory investigation addresses:
1. Does extreme ambient heat measurably lower tested computational feasibility under fixed facility power constraints? (H1, frozen primary)
2. Does capacity-aware and thermal-aware scheduling recover tested feasibility or reduce facility limit violations? (H2, frozen secondary)
3. Do event-blind, short-window benchmarks underestimate or misrepresent heatwave operational strain? (H3, frozen secondary)
4. Can forecast uncertainty calibration improve operational safety margins over fixed engineering rules? (H5, frozen secondary)

Additionally, an exploratory hypothesis formulated post-Day-8 (H4) examined whether forecast errors causally drive scheduling regret; however, H4 remains not estimable because controlled forecast-source intervention traces were not captured in the confirmatory execution.

---

## 2. Experimental Design: Three-Event Case-Series

HeatTrace v1 evaluates scheduling behavior across a strictly frozen 756-cell confirmatory matrix. The design uses a three-event historical case-series in CAISO territory paired with meteorological data from GHCNh USW00023234:

- **CONF_1 (`TRIPLET_CONF_1_f5c700`):** Heatwave `HW_20220620` vs Control `CTRL_20240610` (Event-Blind `BLIND_9511c8fdb71a`)
- **CONF_2 (`TRIPLET_CONF_2_2a6e22`):** Heatwave `HW_20220904` vs Control `CTRL_20240615` (Event-Blind `BLIND_ec5ea1727f70`)
- **CONF_3 (`TRIPLET_CONF_3_628624`):** Heatwave `HW_20220922` vs Control `CTRL_20240620` (Event-Blind `BLIND_0a5ab2aec053`)

### Cohorts and Evaluation Controls
The matrix comprises four distinct cohorts:
1. `core_benchmark` (432 runs): Systematic contrasts across policies, workloads ({1.0x, 2.0x, 3.0x}), thermal models, and seeds.
2. `event_blind_benchmark` (216 runs): Unanchored equal-duration evaluation windows.
3. `algorithm_comparators` (72 runs): Algorithmic schedulers including HeatGuard variants.
4. `oracle_reference` (36 runs): Perfect foresight references, explicitly designated non-deployable (`deployable=False`).

### Methodological Invariants
- **Equal-Service Invariance:** Two policies are compared only if they complete identical processing slots with zero unfinished work. Drops or incomplete work cannot credit feasibility.
- **Historical Triplet as Independent Unit:** Multi-seed variations within a single cell are averaged prior to computing event-level contrasts. Seeds, grid cells, and time windows are not treated as independent statistical degrees of freedom.

---

## 3. Hypotheses and Scientific Findings (H1–H5)

Under the frozen confirmatory protocol, the project reached a definitive **LIMITED RESULT** verdict across the evaluated hypotheses:

### H1 — Static Feasibility Loss (Frozen Primary): SUPPORTED
- **Claim:** Under fixed facility power caps, static schedulers demonstrate lower tested feasible workload capacity in heatwave periods than in matched control periods.
- **Evidence:** Tested boundary differences:
  - `CONF_1`: $-0.5\times$
  - `CONF_2`: $-0.5\times$
  - `CONF_3`: $0.0\times$ (null effect)
- **Median Effect:** $-0.5\times$; 2 of 3 pairs negative.

### H2 — Capacity-Awareness Recovery (Frozen Secondary): PARTIALLY SUPPORTED
- **Claim:** Capacity-aware scheduling recovers tested feasibility loss or reduces boundary violations during heatwaves.
- **Evidence:**
  - Tested Boundary Recovery: $0.0\times$ across all pairs (no tested boundary recovery under the discrete $\{1.0\times, 2.0\times, 3.0\times\}$ evaluation grid).
  - Exact `capacity_aware` policy provided $0.0\text{ h}$ violation reduction.
  - `full_thermal_aware` achieved bounded violation hour reductions in both applicable events:
    - `CONF_1`: $1.0\text{ h}$ reduction ($1.5\text{ h} \to 0.5\text{ h}$)
    - `CONF_2`: $0.5\text{ h}$ reduction ($0.5\text{ h} \to 0.0\text{ h}$)
  - `CONF_3` exhibited no prerequisite feasibility loss and is non-applicable.
- **Verdict:** Partially supported strictly through bounded violation hour reduction under full thermal awareness; no tested boundary recovery.

### H3 — Event-Blind Understatement (Frozen Secondary): PARTIALLY SUPPORTED
- **Claim:** Complete-event evaluation produces materially different feasibility or ranking conclusions from event-blind equal-duration windows.
- **Evidence:** Complete-event evaluation demonstrates material descriptive separation from event-blind windows in `CONF_1` (24/36 non-zero metric differences) and `CONF_2` (23/36 non-zero metric differences). However, `CONF_3` yields a completely null descriptive separation (0/36 non-zero differences).
- **Ranking Reversals:** Zero strict policy ranking reversals were observed ($0/54$ eligible pairs). Ranking structures remained identical or shifted between ties.

### H4 — Forecast Mechanism Attribution (Exploratory / Post-Day-8): NOT ESTIMABLE
- **Claim:** Forecast errors directly cause scheduling regret.
- **Status:** **NOT ESTIMABLE** from the frozen confirmation. The execution environment generated end-to-end schedule outcomes but did not log intermediate hourly allocation vector traces or controlled forecast-source interventions needed to isolate mechanism attribution.

### H5 — HeatGuard Margin Advantage (Frozen Secondary): NOT SUPPORTED
- **Claim:** Calibrated dynamic PUE-residual margins outperform fixed engineering margins in reducing facility violations.
- **Evidence:** Under evaluated conditions, calibrated dynamic margin policies did not demonstrate superior performance over a fixed $0.10$ PUE margin.

---

## 4. Strongest Defensible v1 Claim

> **Strongest Defensible Claim:** In a provenance-locked three-event CAISO case series, complete heatwave windows exposed equal-service policy cost and production-based carbon-proxy separations that frozen event-blind windows missed in two events; the third event was null, strict ranking reversals were absent, and forecast-caused regret was not identified.

### Explicit Non-Claims (Prohibitions)
- **No Population-Wide / Causal Heat Claims:** Results apply to the evaluated three-event case series and cannot be generalized causally to all heatwave events.
- **No HeatGuard Superiority:** HeatGuard dynamic calibration does not show superior performance over standard fixed margins.
- **No Tested Boundary Recovery:** Neither capacity awareness nor thermal awareness expands the maximum sustainable workload multiplier beyond static baselines on the discrete $\{1.0\times, 2.0\times, 3.0\times\}$ grid.
- **No Forecast Regret Attribution:** Scheduling losses cannot be attributed causally to forecast errors in v1.

---

## 5. Methodological Limitations

1. **Discrete Grid Granularity:** Workload scaling evaluated only discrete multipliers $\{1.0\times, 2.0\times, 3.0\times\}$, limiting boundary recovery detection below $0.5\times$ resolution.
2. **Three-Event Case-Series Sample Size:** While each event spans a 120-hour window across 252 simulation cells, three historical events provide limited statistical power and do not establish population-wide generalizability.
3. **Simulated Facility Dynamics:** Facility thermal responses rely on calibrated piecewise-linear thermal/PUE assumptions and RC equivalent thermal circuits, not physical data center instrumentation.
4. **Grid Carbon Proxy:** Grid emissions factors rely on EIA-930 production-based average carbon intensity proxies, rather than CAISO day-ahead emissions or avoided marginal emissions.

---

## 6. Deferrals (Post-Day 21 / Phase 12 Scope)

The following activities are strictly deferred to future work:
- Formatting for specific conference/journal venue LaTeX templates.
- Polished prose abstract and extensive narrative related work.
- Continuous-time boundary search algorithms.
- Multimodal weather forecasting interventions (v2).
