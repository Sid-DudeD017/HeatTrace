# 7. Hypotheses, results, and evidence

## 7.1 v1 H1–H5

| Hypothesis | Experiment and exact result | Verdict | Challenge |
|---|---|---|---|
| H1 static feasibility | Static, capped/medium, heatwave vs control. Effects −0.5×, −0.5×, 0.0×; median −0.5×; 2/3 negative | Supported under frozen rule | coarse tested grid, three events, not proportional physical capacity loss |
| H2 awareness recovery | No tested-boundary recovery; capacity-aware 0h reduction; full thermal reduces violation hours 1.0h and 0.5h in two applicable events | Partially supported under disjunctive rule | mitigation did not restore feasibility and sometimes worsened boundary |
| H3 blind understatement | heatwave nonzero gaps 24/36, 24/36, 0/36; blind 0/36 all; control 24/36 for CONF1; zero strict reversals | Partially supported | reveals separation, not a different winning policy; one control also separates |
| H4 forecast mechanism | no same-policy forecast substitution or hourly allocation traces | Not estimable | accuracy is not forecast-caused regret |
| H5 HeatGuard | calibrated beats both fixed/full-thermal in 0/3 events | Not supported | no superior safety/algorithm claim |

Source calculation is `evaluation/p6_validity.py`; evidence is the canonical analysis CSVs and `docs/p6_validity_report.md`. P11 reproduced the evidence but did not add new findings.

## 7.2 B2 G1–G5

| Hypothesis | Actual P6 result | Stage 2 status |
|---|---|---|
| G1 temporal replication | Full boundary mean −0.083×, median 0; narrow static difference positive in 6/6 paired episodes, median +8.083h across 2023–2025 | Narrow static claim survives; broad claim limited |
| G2 geography | inland 15.9h vs coastal 6.8h; contrast +9.10h; cluster bootstrap CI [−3.08,+25.47] | descriptive only; interval crosses zero; episode 08 belongs to both classes |
| G3 discriminability | 4 estimable events; only LAX 2024 exceeds ordinary P95; 3 within; 21 catalogue events non-estimable/absent | not established; 3/4 estimable events rely on invalid transfer and ordinary windows overlap |
| G4 continuity | no valid full-event versus isolated 120h ablation preserving arrivals/deadlines/backlog | not estimable |
| G5 robustness | only low curve executed; all six paired episodes positive | limited; nine sensitivities absent; conflicting summary statistics need correction |

Stage 2 independently recalculated 25 station events, 15 episodes, 12 eligible events, seven eligible episodes, 6,480 unique IDs, 5,448 successes, and 1,032 failures. Six—not seven—episodes have valid controls for the narrow G1 paired statistic.

## 7.3 The G5 discrepancy

P6 text reports +5.33h; the analysis function computes the median of episode mean differences and Stage 2 reports +4.12h, while the median of episode medians is +4.25h. These are different estimands, and the repository does not consistently label them. Do not quote one as definitive until code, table, and prose use the same aggregation.

## 7.4 Claim triage

| Research claim | Intended evidence | Actual finding | Strength | Caveat |
|---|---|---|---|---|
| Static capped facilities are more vulnerable in heatwaves | paired episode violation differences | 6/6 positive, median +8.08h | strongest within model | retrospective, synthetic facility/workload |
| Broad feasibility boundary shifts | lower feasible multiplier | mean −0.08×, 5/6 zero | unsupported/limited | coarse grid |
| Inland stress exceeds coastal | cluster contrast | +9.10h, CI crosses zero | descriptive | only six unique episodes |
| Heatwaves beat ordinary benchmark P95 | common-support equal-service distribution | 1/4 estimable exceeds | not established | transfer + overlap + attrition |
| Full-event continuity matters | prospective state-preserving ablation | never run | not estimable | aggregate rows insufficient |
| HeatGuard/TinyLSTM improve statewide outcomes | valid station models and equal service | protocol violated | invalid for non-SFO | static/oracle unaffected by transfer |
| Cost/carbon savings | identical completed service | no valid high-load heatwave trios | not estimable broadly | doing less work looks cheaper |

## 7.5 What the project demonstrates

| Category | Answer | Why |
|---|---|---|
| New algorithm | No/partial prototype | HeatGuard is a heuristic and showed no superiority |
| New dataset | Partial | curated multi-source benchmark artifacts, not a new primary observational source |
| New benchmark methodology | Yes, scoped | event/control/ordinary design, thermal feasibility, equal-service/provenance gates |
| Validated algorithmic improvement | No | H5 null; B2 forecast policies invalid outside SFO |
| Multi-year empirical case study | Yes within simulation | historical inputs across stations/years drive modeled experiments |
| Causal finding | No | observational event selection plus simulation; no forecast intervention |
| Broad generalizable claim | No | small/selected episode set and model assumptions |

“Proved” should be avoided. Say “the simulation evidence supports” and name the scope.

