# HeatTrace Phase P5 Experiments & Evidence Report

## 1. Executive Summary & Gate Status

Phase P5 of HeatTrace executes the comprehensive empirical evaluation comparing the approved multi-day heatwave (`HW_20240702`) with its verified matched non-heatwave control (`CTRL_20240605`) under deterministic experimental controls.

- **Gate G5-a Status:** `VERIFIED_PASS` (0 failures, 0 violations).
- **Random Seed:** `20261016`.
- **Target Windows:** `HW_20240702` (120 hours) and `CTRL_20240605` (120 hours).
- **Workload:** `trace_standard_120h_v0` (30 jobs, 4,522.74 kWh).
- **Policies Evaluated:** `cost_first`, `carbon_first`, `balanced`, and `dro_inspired`.

---

## 2. Research Objectives & Empirical Findings

### Q1: How do heatwave and ordinary control conditions differ? (E1)
Across the 120-hour matched comparison:
- **Temperature:** Heatwave mean temperature was $20.73^\circ\text{C}$ (peak $31.10^\circ\text{C}$, 24 exceedance hours $> 25.60^\circ\text{C}$) compared to Control mean $16.68^\circ\text{C}$ (peak $22.20^\circ\text{C}$, 0 exceedance hours).
  - Paired hourly difference: $+4.05^\circ\text{C}$ (95% CI: $[+3.35^\circ\text{C}, +4.75^\circ\text{C}]$, Cohen's $d = 1.00$).
- **Grid Demand:** Heatwave mean demand was $32,420$ MW vs Control $26,453$ MW.
  - Paired hourly difference: $+5,968$ MW (95% CI: $[+5,246, +6,744]$ MW, Cohen's $d = 1.41$).
- **LMP Electricity Price:** Heatwave mean price was $\$48.96$/MWh (max $\$173.48$/MWh) vs Control $\$22.25$/MWh (min $-\$10.51$/MWh, max $\$51.27$/MWh).
  - Paired hourly difference: $+\$26.71$/MWh (95% CI: $[+\$23.01, +\$30.90]$/MWh, Cohen's $d = 1.16$).
- **Net Generation:** Paired hourly difference $+4,212$ MW (95% CI: $[+3,506, +4,972]$ MW).
- **Lagged Association Analysis (Lags -24h to +24h):**
  - In `HW_20240702`, contemporaneous temperature and price exhibit $r = 0.505$ ($p < 0.001$). Peak correlation occurs at lag $+3$ hours (temperature leads price by 3 hours, $r = 0.528$).
  - In `CTRL_20240605`, contemporaneous temperature and price correlation is negative ($r = -0.222$).

### Q2: How do scheduling policies perform under heatwave versus control conditions? (E2)
Across both windows, all 4 policies achieve 100% SLA completion with zero deadline misses and zero cluster violations:
- **Control Window (`CTRL_20240605`):**
  - Total Realized Cost: $\$103.9966$
  - Realized Emissions (Quality-Limited): $569.8798$ kg
  - Cost CVaR (90%): $\$3.1486$
- **Heatwave Window (`HW_20240702`):**
  - Total Realized Cost: $\$236.2015$ ($+127.1\%$ increase over control)
  - Realized Emissions (Quality-Limited): $831.2562$ kg ($+45.9\%$ increase over control)
  - Cost CVaR (90%): $\$7.7894$ ($+147.4\%$ tail risk increase)

*Policy Equivalence Finding:* Within each window, all 4 policies yielded identical costs and allocations due to flat causal persistence forecasts interacting with earliest-hour tie-breaking (documented in `docs/p5_policy_diagnostic.md`).

### Q3: How sensitive are results to clipping and missing-value treatment? (E3)
Evaluated across 24 combinations (3 variants $\times$ 2 windows $\times$ 4 policies):
- **Raw:** 0 modified cells. Cost = $\$103.9966$ (CTRL), $\$236.2015$ (HW).
- **Clipped (1st/99th percentiles fit strictly from pre-origin history):** 0 cells clipped (all benchmark observations fell within historical bounds). Cost and schedule outcomes were identical to raw.
- **Causal Imputed:** 0 cells imputed because benchmark data has 100% complete hourly coverage. Outcomes identical to raw.
- **Sensitivity Conclusion:** Benchmark results are completely robust to clipping and imputation because the verified 2024 benchmark data possesses 100% complete physical observations without extreme unphysical outliers.

### Q4: Does event-aware or event-stratified evaluation produce different conclusions from ordinary-window evaluation? (E4)
Evaluated under verified equal 120-hour evaluation budgets:
- **Ordinary Window (120h Control):** Realized cost = $\$103.9966$. Reflects unperturbed summer baseline.
- **Event-Stratified (60h Control + 60h Heatwave = 120h):** Realized cost = $\$167.3195$. Captures blend of baseline and acute stress.
- **Phase-Aware Event Window (120h partitioned into onset, peak, sustained, recovery):** Realized cost = $\$236.2015$. Highlights maximum acute regime cost.
- **Conclusion:** Stratified and phase-aware evaluation exposes substantial cost escalations (up to $+127\%$) that ordinary-window evaluation completely conceals.

---

## 3. Methodological Limitations & Quality Disclosures

1. **Carbon Data Quality Disclosure:** Across all 240 benchmark hours, carbon observations carry EIA Known Data Issue flags ($0/240$ primary-eligible). All carbon metrics carry the mandatory label `quality_limited_sensitivity_only` and must NOT be cited as clean causal or primary evidence.
2. **Comparator Limitation:** The full 30-job / 120-hour benchmark instance exceeds the exact small-instance branch-and-bound comparator limits ($\le 6$ jobs, $\le 24$ hours). The comparator honestly reports status `unsupported` with no fabricated optimal objective. On a controlled small fixture (4 jobs, 24 hours), the comparator proves global optimality (`optimal`, Cost = $\$16.3515$).
3. **Sample Size & Single-Event Caveat:** Evaluations are conducted on one matched 120h event/control pair. Inferential statements are exploratory and descriptive.
