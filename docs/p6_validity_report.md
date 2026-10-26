# HeatTrace Phase 10 — Concise v1 Validity Report & Claim Freeze

**Status:** COMPLETE (v1 Confirmatory Interpretation)  
**Study Phase:** Phase 10 / Day 12  
**Repository Base Commit:** `37bdffbf27666c40a24fb0591d2e2d7436508adf`  
**Implementation Git Commit:** none; the current repair is uncommitted (`uncommitted_source_changes`)  
**Authoritative Implementation Identity:** recorded analysis-source (`bea868ca4a76fa8a4a762e39591c6ad03a210f9c9f93edcffa94109bc19f4291`) and focused-test (`0ac246de29ac593f4ef0bc2f70706ca33b5041a5abdae39f76f69cc0cc0c8ed7`) SHA-256 hashes  
**Protocol Reference:** [`docs/p6_frozen_protocol.md`](file:///Users/siddharthbhakta/HeatTrace/docs/p6_frozen_protocol.md)  
**Configuration Reference:** [`configs/p6_validity.yaml`](file:///Users/siddharthbhakta/HeatTrace/configs/p6_validity.yaml)  
**Analysis Manifest:** [`data/results/p6_analysis_manifest.json`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_analysis_manifest.json)  

---

## 1. Title and v1 Status

This document provides the definitive, evidence-traceable Phase 10 / Day 12 v1 confirmatory validity report for the HeatTrace project. It synthesizes the finalized Day 10 (Phase 8) confirmatory execution baseline and Day 11 (Phase 9) statistical evaluation without modifying experimental code, re-running simulations, or re-generating data artifacts.

---

## 2. Executive Decision: LIMITED RESULT

The formal scientific decision for the HeatTrace v1 confirmatory evaluation is:

$$\mathbf{LIMITED\ RESULT}$$

### Adjudication Rationale
The result is assigned **LIMITED RESULT** (and is explicitly barred from being upgraded to **GO**) due to the following conclusive empirical findings:
1. **H1 Supported with Coarse Grid and Weak Low-Curve Sensitivity:** While the primary confirmatory hypothesis H1 satisfied its frozen support criterion (median effect $-0.5x$, negative effects in $2/3$ events under the primary medium thermal curve), low-curve sensitivity is weak ($1/3$ negative, median $0.0x$). Feasibility is evaluated only over a discrete $\{1.0x, 2.0x, 3.0x\}$ workload grid in simulated facilities.
2. **H2 Partially Supported (Mixed Evidence Across Policies and Outcomes):** Under the literal frozen disjunction ("higher tested feasible workload OR fewer violations than static scheduling"), H2 is partially supported:
   - Zero tested boundary recovery is achieved by any policy across the series.
   - The exact `capacity_aware` policy provides no boundary recovery ($0.0x$) and no violation reduction ($0.0\text{h}$) in either applicable event.
   - `full_thermal_aware` reduces violation hours in both applicable events ($1.0\text{h}$ in `CONF_1`, $0.5\text{h}$ in `CONF_2` at $3.0x$), but achieves zero tested boundary recovery and degrades the tested boundary by $-0.5x$ in `CONF_1`.
   - `CONF_3` lacked prerequisite static feasibility loss.
   - The evidence is mixed across policies and outcomes; thermal awareness does not restore tested feasibility or provide general mitigation.
3. **H3 Only Partially Supported Across Two of Three Events:** Complete heatwave windows discriminated policy cost/carbon performance that event-blind windows missed in `CONF_1` and `CONF_2` ($+24$ non-zero comparisons out of $36$), but `CONF_3` was completely null ($0/36$ separations across both heatwave and blind). Furthermore, in `CONF_1`, the matched control window also discriminated ($24/36$), demonstrating that discrimination is not unique to extreme heat. All observed ranking shifts across the 108 heatwave-versus-blind transitions were baseline-tie to heatwave-non-tie transitions; there were **zero strict ranking reversals**.
4. **H4 Forecast Mechanism Attribution Not Estimable:** The frozen confirmation matrix contains no same-scheduler counterfactual forecast intervention (varying forecast source while holding scheduler, facility model, workload, and objective identical). Hourly allocation vectors were not logged. Hindsight oracle execution is not a causal forecast intervention.
5. **H5 HeatGuard Advantage Not Supported:** Calibrated HeatGuard failed to outperform fixed-margin HeatGuard or deterministic Full Thermal Aware in $0/3$ events ($0.0\text{h}$ improvement across all triplets). Algorithmic novelty and safety margin superiority are unproven.

---

## 3. Immutable Evidence Baseline & Provenance Summary

The v1 confirmation rests on immutable, byte-verified P8 artifacts generated during Day 10. Prior to analysis, all canonical SHA-256 digests were verified bit-for-bit:

| Canonical Artifact Path | Expected & Verified SHA-256 Digest | Status |
| :--- | :--- | :---: |
| [`data/results/p6_validity_runs.parquet`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_validity_runs.parquet) | `c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f` | **MATCH** |
| [`data/results/p6_validity_checkpoint.parquet`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_validity_checkpoint.parquet) | `c45391e61a87c909fa143039464a8961d3c04c8d513669516a49d8f42fe8777f` | **MATCH** |
| [`data/results/p6_validity_manifest.json`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_validity_manifest.json) | `d0dd9f870ec2a431cc16177c5f1b7a5e6b47a7dc888b0acb491a819656006082` | **MATCH** |
| [`data/results/p6_validity_execution.jsonl`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_validity_execution.jsonl) | `de430ceea4559de2f4e67f5b122223b3496dfe854e1f5efa874909363bff0e80` | **MATCH** |

- **Canonical Run-ID Digest:** `1a8cb83e3388fbfcc16efdd916f79d847377081f02f40608e5adc112bc2a6aa1`  
  *(Computed as SHA-256 of all 756 newline-separated sorted `run_id` strings).*

---

## 4. Confirmation Accounting

Directly audited from [`data/results/p6_t1_cohort_provenance.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t1_cohort_provenance.csv) and [`data/results/p6_validity_manifest.json`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_validity_manifest.json):

- **Total Execution Rows:** $756$
- **Unique Run IDs:** $756$
- **Successful Runs:** $756$
- **Failed Runs:** $0$
- **Cohort Composition:**
  - `core_benchmark` (deployable core policies across heatwave and control): **$432$ cells**
  - `event_blind_benchmark` (deployable core policies in event-blind windows): **$216$ cells**
  - `algorithm_comparators` (calibrated and fixed margin HeatGuard): **$72$ cells**
  - `oracle_reference` (`oracle_full_thermal_aware`, deployable = false): **$36$ cells**
- **Confirmatory Triplet Allocation:** Exactly $252$ runs per confirmatory triplet:
  - `TRIPLET_CONF_1_f5c700`: $252$ rows
  - `TRIPLET_CONF_2_2a6e22`: $252$ rows
  - `TRIPLET_CONF_3_628624`: $252$ rows
- **Development Contamination:** Exactly **$0$** development triplet rows (`TRIPLET_DEV_ae821c`) entered the confirmatory suite. Confirmatory execution was clean and non-contaminated.

---

## 5. Confirmatory versus Exploratory Evidence Boundary

A strict epistemic boundary separates pre-confirmation exploratory development from frozen confirmatory evaluation:

1. **Confirmatory Scope (Locked at Day 9 / Phase 7):**
   - Hypotheses H1, H2, H3, and H5 were frozen prior to unsealing confirmatory triplets.
   - Primary metric thresholds, evaluation windows ($120\text{h}$), facility power capping ($C_{\text{eff}}[t] = \min(500, 600 / \text{PUE}[t])$), and discrete workload levels ($\{1.0x, 2.0x, 3.0x\}$) were locked in [`configs/p6_validity.yaml`](file:///Users/siddharthbhakta/HeatTrace/configs/p6_validity.yaml).
   - Only outcomes from the 756 confirmatory cells across `CONF_1`, `CONF_2`, and `CONF_3` constitute confirmatory evidence.
2. **Exploratory Scope (Day 8 Pilot & Post-Day-8 Diagnostic Questions):**
   - Question H4 regarding forecast-error causal attribution was formulated post-Day-8 after observing TinyLSTM underprediction on development data.
   - The frozen P8 confirmation was designed for benchmark validity and policy comparison; it **did not execute a counterfactual forecast substitution**.
   - Any mechanism claim attributing scheduler cost/carbon outcomes to forecast error is unestimable from confirmation data and must remain exploratory.
   - Future extensions (Days 15–21) are separately versioned exploratory studies and cannot retroactively modify v1 confirmatory findings.

---

## 6. H1–H5 Assessment

Audited directly from [`data/results/p6_h1_h5_assessment.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_h1_h5_assessment.csv):

### H1 — Static Feasibility Loss Under Extreme Heat
- **Original Frozen Status:** Primary Confirmatory Hypothesis
- **Classification:** **`SUPPORTED`**
- **Empirical Evidence:**
  - Evaluated on `static_unaware`, `carbon_first` objective, power-capped facility model, under primary medium thermal curve.
  - Event-level tested feasibility boundary contrast ($\Delta \lambda^* = \lambda^*_{\text{heatwave}} - \lambda^*_{\text{control}}$):
    - `TRIPLET_CONF_1_f5c700`: $-0.5x$ ($2.5x$ vs $3.0x$)
    - `TRIPLET_CONF_2_2a6e22`: $-0.5x$ ($2.5x$ vs $3.0x$)
    - `TRIPLET_CONF_3_628624`: $0.0x$ ($3.0x$ vs $3.0x$)
  - Median Effect: $-0.5x$
  - Sign Consistency: $2/3$ negative ($66.7\%$).
  - Frozen rule criterion ($\ge 2/3$ negative and median $< 0$) is satisfied.
  - Low-curve sensitivity: Weak ($1/3$ negative: `CONF_1` $-0.5x$, `CONF_2` $0.0x$, `CONF_3` $0.0x$; median $0.0x$).
- **Mandatory Qualifications:**
  - Applies to a coarse grid-bounded tested feasibility envelope on $\{1.0x, 2.0x, 3.0x\}$, not a continuous physical threshold.
  - Limited to the three selected CAISO historical cases, simulated facility models, and synthetic workloads.

### H2 — Capacity-Awareness Feasibility Recovery
- **Original Frozen Status:** Secondary Confirmatory Hypothesis
- **Frozen Definition:** "During heatwaves, capacity-aware scheduling has a higher tested feasible workload OR fewer violations than static scheduling."
- **Classification:** **`PARTIALLY_SUPPORTED`**
- **Empirical Evidence:**
  - **Tested Boundary Recovery:** $0.0x$ boundary recovery across all applicable events. `capacity_aware` yielded $2.5x$ vs static $2.5x$ ($0.0x$ recovery) in both `CONF_1` and `CONF_2`. `full_thermal_aware` was $-0.5x$ worse in `CONF_1` ($2.0x$ vs $2.5x$) and $0.0x$ in `CONF_2` ($2.5x$ vs $2.5x$).
  - **Violation Hours Reduction:**
    - `capacity_aware` yielded zero violation reduction in both applicable events: $0.0\text{h}$ reduction in `CONF_1` ($1.5\text{h} \to 1.5\text{h}$) and $0.0\text{h}$ reduction in `CONF_2` ($1.0\text{h} \to 1.0\text{h}$).
    - `full_thermal_aware` reduced violation hours in both applicable events: $1.0\text{h}$ reduction in `CONF_1` ($1.5\text{h} \to 0.5\text{h}$) and $0.5\text{h}$ reduction in `CONF_2` ($1.0\text{h} \to 0.5\text{h}$) at $3.0x$ workload.
  - **Prerequisite Pruning:** `TRIPLET_CONF_3_628624` lacked prerequisite static feasibility loss ($\Delta \lambda^* = 0.0x$), rendering recovery non-applicable.
- **Bounded Mixed-Result Interpretation:**
  - Under the literal disjunctive rule ("higher tested feasible workload OR fewer violations"), violation reduction by `full_thermal_aware` activates the secondary branch.
  - Because tested boundary recovery is completely absent, exact `capacity_aware` provides zero improvement, and `full_thermal_aware` exhibits a boundary degradation in `CONF_1`, the evidence is mixed across policies and metrics.
  - The hypothesis is classified as **`PARTIALLY_SUPPORTED`**. Do not claim that thermal awareness restores tested feasibility, eliminates SLA violations, or provides general mitigation.

### H3 — Event-Blind Understatement of Policy Separation
- **Original Frozen Status:** Secondary Confirmatory Hypothesis (Elevated prospectively after Day 8)
- **Classification:** **`PARTIALLY_SUPPORTED`**
- **Empirical Evidence:**
  - Evaluated across 36 seed-aggregated deployable core comparisons per triplet/context (3 policy pairs $\times$ 2 facility models $\times$ 2 curves $\times$ 3 workloads).
  - Non-zero pairwise cost/carbon separations ($| \Delta \text{cost} | > 0$):
    - `TRIPLET_CONF_1_f5c700`: Heatwave $24/36$, Event-Blind $0/36$, Matched Control $24/36$ ($\Delta_{\text{HW - Blind}} = +24$).
    - `TRIPLET_CONF_2_2a6e22`: Heatwave $24/36$, Event-Blind $0/36$, Matched Control $0/36$ ($\Delta_{\text{HW - Blind}} = +24$).
    - `TRIPLET_CONF_3_628624`: Heatwave $0/36$, Event-Blind $0/36$, Matched Control $0/36$ ($\Delta_{\text{HW - Blind}} = 0$).
  - Event effects: $[+24, +24, 0]$, median $+24$, sign consistency $2/3$ positive.
  - Ranking transitions: Across 36 heatwave-versus-blind core-policy transitions per event ($108$ total transitions across the 3 events), there were exactly $48$ baseline-tie to heatwave-non-tie transitions ($24$ in `CONF_1`, $24$ in `CONF_2`, $0$ in `CONF_3`) and $60$ unchanged ties ($12$ in `CONF_1`, $12$ in `CONF_2`, $36$ in `CONF_3`).
  - Strict ranking reversals (where policy A is preferred in blind/control but policy B is preferred in heatwave): **Exactly 0 across all 108 transitions**.
- **Mandatory Qualifications:**
  - Event-blind windows masked policy separations in two events, but the effect was null in the third event.
  - `CONF_1` does not demonstrate heatwave-unique discriminability because its matched control window also discriminated $24/36$ comparisons.
  - Conventional benchmarking did not select the "wrong" scheduler; it simply failed to detect non-zero performance separations.

### H4 — Forecast Mechanism Attribution
- **Original Status:** Post-Day-8 Exploratory Mechanism Question
- **Classification:** **`NOT_ESTIMABLE`**
- **Reason:**
  - No same-scheduler counterfactual forecast intervention exists in the confirmatory execution matrix.
  - Hourly job allocation vectors were not preserved in the confirmation schema (`allocation_count` scalar only).
  - The non-deployable hindsight oracle (`oracle_full_thermal_aware`) cannot serve as a temperature-forecast counterfactual.
  - Day 8 forecast errors represent development-only associative observations. Causal forecast-induced scheduling regret is unestimable from v1 confirmation.

### H5 — HeatGuard Algorithm Advantage
- **Original Status:** Frozen Comparator Diagnostic Question
- **Classification:** **`NOT_SUPPORTED`**
- **Empirical Evidence:**
  - Facility violation hours at $3.0x$ workload, power-capped model, medium curve:
    - `TRIPLET_CONF_1_f5c700`: calibrated $1.0\text{h}$, fixed $0.0\text{h}$, deterministic full-thermal $1.0\text{h}$.
    - `TRIPLET_CONF_2_2a6e22`: calibrated $0.5\text{h}$, fixed $0.5\text{h}$, deterministic full-thermal $0.5\text{h}$.
    - `TRIPLET_CONF_3_628624`: calibrated $0.0\text{h}$, fixed $0.0\text{h}$, deterministic full-thermal $0.0\text{h}$.
  - Calibrated HeatGuard improved over both comparators in **$0/3$ events** ($0.0\%$).
- **Mandatory Qualifications:**
  - No algorithmic superiority, safety margin advantage, or operational protection is demonstrated for HeatGuard over simpler heuristics or deterministic policies.

---

## 7. Event-Level Effect-Size and Ranking Summary

Detailed event-level metrics from [`data/results/p6_event_level_metrics.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_event_level_metrics.csv) and [`data/results/p6_t2_event_feasibility.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t2_event_feasibility.csv):

| Triplet ID | CAISO Heatwave Event | Static Feasibility Loss (H1) | Capacity-Aware Recovery (H2) | HW vs Blind Discrim (H3) | Calibrated HeatGuard vs Fixed (H5) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `TRIPLET_CONF_1_f5c700` | June 2022 (`HW_20220620`) | **$-0.5x$** ($2.5x$ vs $3.0x$) | **$0.0x$** (No recov; fta $-0.5x$, viol red $1.0\text{h}$) | **$+24$** ($24$ HW vs $0$ Blind) | **$1.0\text{h}$ vs $0.0\text{h}$** (Worse) |
| `TRIPLET_CONF_2_2a6e22` | Sept 2022 (`HW_20220904`) | **$-0.5x$** ($2.5x$ vs $3.0x$) | **$0.0x$** (No recov; fta $0.0x$, viol red $0.5\text{h}$) | **$+24$** ($24$ HW vs $0$ Blind) | **$0.5\text{h}$ vs $0.5\text{h}$** (Tied) |
| `TRIPLET_CONF_3_628624` | Late Sept 2022 (`HW_20220922`) | **$0.0x$** ($3.0x$ vs $3.0x$) | **N/A** (No prerequisite loss) | **$0$** ($0$ HW vs $0$ Blind) | **$0.0\text{h}$ vs $0.0\text{h}$** (Tied) |

### Ranking Transition Structure
Audited from [`data/results/p6_t3_equal_service_gaps.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t3_equal_service_gaps.csv):
- In `CONF_1` and `CONF_2`, deployable policy contrasts between `capacity_aware` / `static_unaware` and `full_thermal_aware` transitioned from complete equality in event-blind windows ($0.0\text{ USD}$, $0.0\text{ kg CO}_2$) to non-zero separations during heatwaves (e.g., in `CONF_1` at $3.0x$: $-\$56.92$ cost gap, $-236.79\text{ kg CO}_2$ proxy gap preferring `capacity_aware` over `full_thermal_aware`).
- Across the 36 heatwave-versus-blind core-policy transitions per event (108 transitions total across the 3 confirmatory events), **zero** pairs exhibited strict order inversion ($A \succ B$ in blind to $B \succ A$ in heatwave). All shifts were baseline ties resolving into non-tie differentials.

---

## 8. Equal-Service and Oracle Accounting

Directly audited from [`data/results/p6_analysis_manifest.json`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_analysis_manifest.json):

```text
Total Seed-Aggregated Policy Pairwise Contrasts: 540
├── Eligible Equal-Service Comparisons:          530 (100% work completed)
└── Rejected Unequal-Service Comparisons:         10 (Violated equal service)
```

### Rejection Root Cause
- All $10$ rejected comparisons occurred exclusively in the `control` context involving the non-deployable `oracle_full_thermal_aware`.
- Under seed `20261016`, the oracle completed only $291$ processing slots out of $303$ demanded ($12$ unfinished slots, incomplete service), while all deployable policies completed $303/303$ slots.
- **Enforcement Rule:** All $10$ comparisons were rejected by the equal-service filter (`equal_service_eligible = False`). No cost or carbon superiority claim may cite these oracle runs.
- **Deployable Integrity:** All 432 core deployable execution cells across heatwaves and controls completed 100% demanded service across all seeds (0 unfinished slots).

### Carbon Accounting Terminology
- Carbon metrics reflect a **production-based carbon proxy** computed from CAISO average production carbon intensity ($g\text{CO}_2/\text{kWh}$).
- They **must not** be described as avoided emissions, marginal emissions, or grid displacement effects.

---

## 9. Day 8 Development versus Frozen Confirmation

| Dimension | Day 8 Pilot (Development Only) | Day 10 Confirmation (Frozen P8 Matrix) |
| :--- | :--- | :--- |
| **Cohort & Scope** | Single development triplet (`TRIPLET_DEV_ae821c`, July 2024). | Three sealed confirmatory triplets (`CONF_1`, `CONF_2`, `CONF_3`, 2022). |
| **Feasibility Loss** | Zero boundary loss across all policies through $3.0x$ workload. | H1 static feasibility loss ($-0.5x$) confirmed in $2/3$ events. |
| **Policy Separation** | Complete-event separation observed while blind window tied. | H3 discriminability confirmed in $2/3$ events; third event was completely null. |
| **Forecast Accuracy** | TinyLSTM heatwave RMSE ($5.81^\circ\text{C}$) degraded vs baseline ($3.69^\circ\text{C}$). | Not evaluated causally; forecast mechanism attribution is unestimable. |
| **HeatGuard Safety** | Zero facility violations across all policies; no margin advantage. | Calibrated margin produced zero advantage ($0/3$ events) over fixed/deterministic. |
| **Role in Study** | Exploratory development findings that informed interpretation. | Immutable confirmatory baseline governing publication claims. |

Day 8 produced exploratory development findings that informed interpretation and validated pipeline invariants, while contributing no confirmatory hypothesis evidence.

---

## 10. Claim-Evidence Map

The following map links every scientific claim permitted in v1 to its exact quantitative derivation, governing limitations, and prohibited escalations:

| # | Major Claim | Status | Evidence Class | Source Artifact & Derivation | Limitations | Permitted Wording | Prohibited Escalation |
| :-: | :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| **C1** | Static scheduling feasibility envelope is reduced under heatwave conditions. | **Supported** | Confirmatory (Primary) | [`p6_t2_event_feasibility.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t2_event_feasibility.csv#L4-L25); rows for static_unaware in `CONF_1`, `CONF_2`, `CONF_3`. Tested boundary drops from $3.0x$ to $2.5x$ in $2/3$ events. | Coarse $\{1.0x, 2.0x, 3.0x\}$ grid; simulated facility; weak low-curve sensitivity ($1/3$). | "Static scheduling showed a 0.5x lower grid-bounded feasibility envelope in two events." | Do not claim continuous threshold, universal collapse, or strong sensitivity across thermal curves. |
| **C2** | Capacity and thermal awareness show mixed violation reduction without boundary recovery. | **Partially Supported** | Confirmatory (Secondary) | [`p6_t2_event_feasibility.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t2_event_feasibility.csv#L2-L49); boundary recovery is $0.0x$ across both events; exact `capacity_aware` provides zero violation reduction; `full_thermal_aware` reduces violation hours by $1.0\text{h}$ and $0.5\text{h}$ in applicable events; `CONF_3` lacks prerequisite loss. | Evaluated at discrete workloads; power-capped simulated model; no boundary recovery; mixed policy outcomes. | "Under the frozen disjunction, capacity and thermal awareness partially supported H2 through 0.5–1.0h violation reductions under full thermal awareness, but achieved no tested boundary recovery and exact capacity awareness showed no improvement." | Do not claim capacity awareness restores tested feasibility, guarantees safety, or solves heatwave bottlenecks. |
| **C3** | Full thermal awareness exhibits mixed violation reduction without boundary recovery. | **Secondary Mixed Observation** | Confirmatory (Secondary) | [`p6_t2_event_feasibility.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t2_event_feasibility.csv#L6-L45); violation hours at $3.0x$ drop by $1.0\text{h}$ (`CONF_1`) and $0.5\text{h}$ (`CONF_2`), but tested boundary is $-0.5x$ worse in `CONF_1`. | Does not alter discrete tested boundary; inconsistent direction across metrics. | "Full-thermal awareness reduced violation hours by 0.5–1.0h in two events but did not recover the tested boundary." | Do not claim full thermal awareness solves heatwave feasibility or restores SLA. |
| **C4** | Event-blind windows obscure policy cost and carbon-proxy separations in two events. | **Partially Supported** | Confirmatory (Secondary) | [`p6_t3_equal_service_gaps.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t3_equal_service_gaps.csv#L2-L28); $24/36$ non-zero separations in `CONF_1` and `CONF_2` heatwaves vs $0/36$ in blind windows. | Third event is null ($0/36$); control also discriminates in `CONF_1`; zero strict ranking reversals. | "Complete heatwave windows exposed equal-service separations that frozen event-blind windows missed in two events, while the third event was null." | Do not claim event-blind benchmarking selects the wrong scheduler or that heatwaves consistently discriminate. |
| **C5** | Forecast errors cannot be causally linked to scheduling performance differentials. | **Not Estimable** | Exploratory / Unestimable | [`p6_t4_forecast_evidence.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t4_forecast_evidence.csv#L18); confirmation matrix lacks same-scheduler forecast intervention; allocation vectors missing. | No counterfactual trace; associative development metrics only. | "The study cannot attribute observed differences to forecast-caused scheduling regret." | Do not claim forecast inaccuracies caused scheduler degradation or regret. |
| **C6** | HeatGuard calibrated margin provides no operational advantage over simple baselines. | **Not Supported** | Confirmatory (Comparator) | [`p6_t2_event_feasibility.csv`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_t2_event_feasibility.csv#L7-L71); calibrated violations equal or exceed fixed margin across all 3 events ($0/3$ improvement). | Tested on power-capped model, medium curve, CAISO cases. | "HeatGuard showed no advantage over fixed-margin or deterministic comparators." | Do not claim algorithmic novelty, safety guarantees, or risk mitigation for HeatGuard. |
| **C7** | Deployable policies deliver perfect equal service across all tested workloads. | **Supported** | Confirmatory (Quality) | [`p6_analysis_manifest.json`](file:///Users/siddharthbhakta/HeatTrace/data/results/p6_analysis_manifest.json#L3-L12); $530/540$ pairs equal-service eligible; all $10$ rejections restricted to hindsight oracle. | Rejections limited to non-deployable oracle under seed 20261016. | "All deployable-versus-deployable comparisons completed equal work." | Do not use rejected oracle pairs for cost or carbon claims. |

---

## 11. Strongest Frozen v1 Claim

The definitive, frozen publication claim for the HeatTrace v1 study is:

> **“In a provenance-locked three-event CAISO case series using simulated power-capped facilities and synthetic workloads, complete heatwave windows exposed equal-service cost and production-based carbon-proxy policy separations that frozen event-blind windows missed in two events, while the third event was null. Static scheduling also showed a 0.5x lower grid-bounded feasibility envelope in two events. The study found no strict ranking reversals, no HeatGuard advantage, and cannot attribute the observed differences to forecast-caused scheduling regret.”**

*Rule:* This wording is frozen. It cannot be strengthened to "consistently," "generally," or "all heatwaves."

---

## 12. Prohibited Claims

The following claims are strictly contradicted by empirical evidence or protocol boundaries and are expressly prohibited in any manuscript, presentation, or abstract:
1. **No Universal Feasibility Collapse:** Do not claim heatwaves universally collapse datacenter feasibility (event `CONF_3` showed zero feasibility loss).
2. **No Algorithmic Novelty or HeatGuard Advantage:** Do not claim HeatGuard offers superior safety, lower violations, or Pareto optimality compared to fixed margins or deterministic policies ($0/3$ event advantage).
3. **No Feasibility Restoration Under Thermal Awareness:** Do not claim capacity or thermal awareness restores lost feasibility boundaries ($0.0x$ tested boundary recovery across all applicable events).
4. **No Forecast-Caused Scheduling Regret:** Do not claim ML forecast errors causally induce scheduler failures or scheduling regret (unestimable from confirmation).
5. **No "Wrong Scheduler Selected":** Do not claim standard benchmarking selects the wrong scheduler; observed ranking changes were tie-to-non-tie transitions, not strict order inversions ($0$ reversals across 108 heatwave-versus-blind transitions).
6. **No Avoided or Marginal Emissions Claims:** Do not describe carbon differentials as marginal avoided emissions or grid decarbonization (metrics are production-based carbon proxies).
7. **No Superiority from Infeasible Oracle Runs:** Do not claim cost or carbon optimality using the non-deployable oracle in control contexts where it failed to complete equal service.
8. **No Generalization Across Datacenters:** Do not generalize beyond the simulated power-capped facility model, synthetic workloads, and three selected CAISO events.

---

## 13. Figure and Caption Audit

Existing figures and status descriptors under `data/figures/` were verified against generated data artifacts without file modification:

### Figure F1: Event-Level Policy Cost and Carbon Contrasts
- **Artifact:** [`data/figures/p6_f1_event_policy_contrasts.png`](file:///Users/siddharthbhakta/HeatTrace/data/figures/p6_f1_event_policy_contrasts.png)
- **Status:** **`ESTIMABLE`**
- **Verified Content:** Displays equal-service cost and production-based carbon-proxy outcomes across all three confirmatory events (`CONF_1`, `CONF_2`, `CONF_3`). Crucially, the null separation in `CONF_3` is fully visible alongside the separations in `CONF_1` and `CONF_2`.
- **Approved Caption:** *Figure 1: Event-level cost and production-based carbon-proxy contrasts across three CAISO confirmatory events under equal-service conditions. Policy separation appears in CONF_1 (June 2022) and CONF_2 (September 2022), whereas CONF_3 (late September 2022) is completely null.*

### Figure F2: Normalized Allocation Distance Matrix
- **Artifact:** [`data/figures/p6_f2_allocation_distance_status.md`](file:///Users/siddharthbhakta/HeatTrace/data/figures/p6_f2_allocation_distance_status.md)
- **Status:** **`NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION`**
- **Verified Content:** Explains that the frozen P8 schema logged scalar `allocation_count` but did not persist hourly job allocation vectors.
- **Approved Caption:** *Figure 2 (Not Estimable): Allocation distance metrics are unestimable from the frozen confirmation matrix because hourly schedule allocation vectors were not preserved in the confirmatory schema.*

### Figure F3: Forecast-Sensitive Scheduling Regret
- **Artifact:** [`data/figures/p6_f3_forecast_regret_status.md`](file:///Users/siddharthbhakta/HeatTrace/data/figures/p6_f3_forecast_regret_status.md)
- **Status:** **`NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION`**
- **Verified Content:** Explains that estimating causal scheduling regret requires a controlled forecast counterfactual under identical schedulers and workloads, which was not present in the frozen P8 design.
- **Approved Caption:** *Figure 3 (Not Estimable): Forecast-induced scheduling regret is unestimable from the confirmatory matrix due to the absence of a controlled same-scheduler forecast intervention.*

### Figure F4: Feasibility Sensitivity and Discriminability Consistency
- **Artifact:** [`data/figures/p6_f4_h1_sensitivity.png`](file:///Users/siddharthbhakta/HeatTrace/data/figures/p6_f4_h1_sensitivity.png)
- **Status:** **`ESTIMABLE`**
- **Verified Content:** Illustrates H1 static feasibility boundary loss across medium and low thermal curves, alongside H3 event-level policy separation consistency ($2/3$ positive, $1/3$ null) without unsupported population inference.
- **Approved Caption:** *Figure 4: Event-level static feasibility envelope sensitivity across thermal curves (medium vs. low) and pairwise policy discriminability across the three confirmatory events. Feasibility loss is sensitive to thermal curve assumptions, and discriminability replicates in two of three historical events.*

---

## 14. Comprehensive Limitations

Any publication or technical report derived from v1 must explicitly enumerate these limitations:
1. **Case Series, Not Population Inference:** The evaluation is a three-event historical case series from CAISO; it does not support population-level statistical inference regarding all heatwaves.
2. **Sample Dependence:** Two heatwaves occurred in September 2022 (`CONF_2` and `CONF_3`), meaning the events cannot be assumed to be independent and identically distributed draws.
3. **Simulated Facility Model:** Datacenter thermal responses, cooling power scaling, and capacity derating follow stylized mathematical models ($C_{\text{eff}}[t] = \min(500, 600 / \text{PUE}[t])$) rather than measured physical telemetry.
4. **Synthetic Workloads:** Job arrivals, durations, and deadlines were synthetically generated rather than sampled from production datacenter traces.
5. **Discrete Feasibility Grid:** Feasibility was evaluated on a coarse multiplier grid $\{1.0x, 2.0x, 3.0x\}$, which captures coarse envelope boundaries rather than continuous physical thresholds.
6. **Weak Low-Curve Sensitivity:** Under the low thermal sensitivity curve, H1 feasibility loss appeared in only $1/3$ events (median effect $0.0x$).
7. **CONF_3 Null Event:** One of the three confirmatory cases (`CONF_3`) yielded zero feasibility loss and zero policy discriminability across all metrics.
8. **Control Window Discrimination:** In `CONF_1`, the matched control window discriminated policies equally as well as the heatwave window ($24/36$), demonstrating that discrimination is not unique to extreme thermal stress.
9. **Tie-to-Non-Tie Transitions Only:** No strict policy ranking reversals were observed across the 108 heatwave-versus-blind core-policy transitions; extreme heat exposed performance differentials between policies that tied in blind windows, but did not invert preferences.
10. **Absence of Allocation Vectors:** Schedule traces and job allocation vectors were not logged, preventing geometric schedule distance analysis.
11. **No Counterfactual Forecast Intervention:** The confirmatory matrix did not evaluate identical schedulers across alternative forecast sources; forecast-caused regret remains unestimable.
12. **Non-Deployable Oracle Infeasibility:** The hindsight oracle is non-deployable and experienced incomplete work ($12$ unfinished slots) in control runs under seed `20261016`.
13. **Proxy Carbon Metrics:** Carbon accounting reflects average production grid intensity, not marginal grid emissions or avoided carbon.
14. **HeatGuard Negative Result:** Calibrated safety margins failed to provide any operational or violation reduction advantage over fixed margins or deterministic baselines.
15. **Strict Versioning of Extensions:** Planned exploratory extensions (Days 15–21) will be documented as separate, post-confirmatory analyses and cannot retroactively alter v1 confirmatory findings.

---

## 15. Workshop/Short-Paper Suitability

The v1 evaluation is suitable for submission to a peer-reviewed sustainable-computing workshop or short-paper track (e.g., ACM e-Energy Workshop, HotCarbon, or IGSC) **strictly if framed around benchmark methodology and mixed empirical evidence**:
- **Framing Requirements:**
  - Must be presented as a reproducible benchmark methodology for extreme-event evaluation in sustainable computing.
  - Must report positive, null, and negative results with equal prominence.
  - Must highlight that conventional event-blind benchmarking can obscure meaningful policy separations.
  - Must candidly present HeatGuard's null result as evidence that simple fixed margins or deterministic policies remain competitive.
- **Disqualifying Framings:**
  - It **must not** be pitched as an algorithmic contribution or an autonomous scheduling system paper.
  - It **must not** claim to prove that heatwaves cause scheduling failures or that ML temperature forecasts induce operational regret.

---

## 16. Day 13 Reproduction Prerequisites

Before executing the Day 13 independent reproduction pass, the following environment and verification prerequisites must be confirmed:
1. **Repository Baseline Preservation:** Record the expected tracked/untracked file baseline prior to reproduction and preserve all pre-existing untracked files. Do not delete, move, overwrite, or casually commit existing artifacts.
2. **Canonical Hash Invariance:** Recompute and verify all four canonical P8 artifact hashes (`runs.parquet`, `checkpoint.parquet`, `manifest.json`, `execution.jsonl`) before and after reproduction, confirming zero byte mutation against the frozen baseline recorded in Section 3.
3. **Execution Scope and Prohibition:** Day 13 must execute only the deterministic evaluation reproduction entry point (`src/heattrace/evaluation/p6_validity.py`), verifying bit-for-bit repeatability of tables T1–T4, figures F1–F4, and assessment classifications without re-running simulations or regenerating P8 confirmation data.
