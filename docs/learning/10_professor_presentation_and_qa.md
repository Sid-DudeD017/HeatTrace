# 10. Professor presentation and question bank

## 10.1 Two-minute explanation

HeatTrace studies whether ordinary benchmark windows hide scheduling stress that appears during full heatwaves. I combine observed NOAA temperature, CAISO day-ahead wholesale prices, and an EIA CISO average carbon proxy with a simulated data center. In the model, heat raises PUE, so a fixed facility-power cap leaves less IT capacity. Synthetic jobs have arrivals, deadlines, and energy requirements, and six schedulers decide when to run them.

The original frozen study used one SFO station and three confirmatory heatwave/control/blind triplets. It ran 756 configuration cells—not 756 independent events. Static feasibility fell by 0.5× in two events and was unchanged in the third. Full thermal awareness reduced some violation hours but did not restore the tested boundary; event windows exposed separations in two events, with no ranking reversals; HeatGuard was not superior. P11 reproduced all scientific rows in the same environment.

B2 expanded to five California stations and 2022–2026. It detected 25 station events grouped into 15 regional episodes; 12 events entered a 6,480-cell matrix. The strongest result is narrow: six paired episodes all show more static cap-violation hours in heatwaves, median +8.08h. But forecast-aware non-SFO results are invalid because the runner reused SFO model/scaler/calibration, equal-service support is sparse, and G4/most robustness variants were not run. So the contribution is an honest benchmark case study and audit lesson, not a proven superior algorithm.

## 10.2 Five-minute walkthrough

1. **Problem:** computation uses IT energy plus cooling; prices/carbon vary; deadlines limit shifting.
2. **Model:** PUE is piecewise linear in temperature; facility power is IT×PUE; cap/PUE gives effective IT capacity.
3. **Observed versus simulated:** weather/price/grid proxy are historical; facility/jobs/actions are simulated.
4. **v1 design:** one SFO station, full event + matched control + event-blind window, three frozen triplets, six policies, two seeds, 1×–3×, facility/curve contexts; 756 nested cells.
5. **v1 result:** H1 supported narrowly, H2/H3 partial, H4 not estimable, H5 unsupported; P11 exact same-environment rerun.
6. **B2 design:** five stations, station P90 and three-day rule, onset/recovery, 24h-overlap regional episodes, one control and 20 ordinary windows per eligible event.
7. **Execution:** 6,480 IDs; 5,448 success, 1,032 explicit failure; only regional episodes are independent units.
8. **Results:** 6/6 static episode differences positive (+8.08h median); geography descriptive (+9.10h, CI crosses zero); G3 1/4; G4 absent; G5 low curve only.
9. **Audit:** SFO artifact transfer contaminates 3,960 cells; high-load equal service fails; ordinary windows overlap; B2 is untracked.
10. **Conclusion:** strong evidence only for modeled static cap vulnerability; algorithmic and broader claims require a corrected prospective replication.

## 10.3 Ten-minute technical outline

Spend one minute each on: research question; sources/time alignment; P90 event/episode graph; matched controls/ordinary sampling; workload/service equations; PUE/cap equations; six greedy rolling policies; v1 matrix/results; B2 matrix/results; audit/next experiment. Show Figures B2-4 and B2-6, then explicitly qualify them.

## 10.4 Challenging questions and answers

1. **What is novel?** The scoped historical-event benchmark methodology and provenance/equal-service audit, not a validated new optimizer.
2. **Why five stations?** They span northern/southern coastal and inland California climates while mapping to three CAISO hubs.
3. **Why 2022–2026?** The frozen multi-year warm-season scope; 2026 is provisional and not primary joint evidence.
4. **Why CAISO?** It supplies regional hourly day-ahead LMP proxies; they are not facility tariffs.
5. **What is PUE?** Total facility power divided by IT power; 1.4 means 40% overhead beyond IT.
6. **How are heatwaves selected?** Station P90 of 2022–2025 daily maxima; strict exceedance for at least three consecutive local days.
7. **Why station P90?** It defines locally unusual heat instead of applying one statewide absolute threshold.
8. **What is a matched control?** Same-station/year, equal-duration, weather/calendar-ranked, event-free window selected without outcomes.
9. **What is event-blind/ordinary?** Outcome-blind warm-season windows representing conventional evaluation outside known events.
10. **Why regional episodes?** Multiple stations may observe the same synoptic heatwave; grouping avoids pseudo-replication.
11. **Why are 25 events not independent?** Buffered events connect into 15 episode components, and only seven are eligible.
12. **Why does static violate the cap?** It schedules against nominal IT capacity without forecast thermal derating; realized PUE pushes facility power over cap.
13. **Why not run every job later?** Exclusive deadlines, future arrivals, finite capacity, and event-wide backlog prevent unlimited delay.
14. **TinyLSTM architecture?** 72×5 input, one 32-unit LSTM, dropout 0.1, linear 24-hour output.
15. **What is HeatGuard?** A fixed or calibrated nonnegative PUE-residual margin used to reserve capacity.
16. **Is HeatGuard DRO?** No, it is a heuristic quantile safety buffer without a formal robustness guarantee.
17. **What did H1–H5 show?** Narrow H1 support; H2/H3 partial; H4 unestimable; H5 unsupported.
18. **What did G1–G5 show?** Narrow G1 supported; G2 descriptive; G3 not established; G4 absent; G5 low-curve only.
19. **Why 1,032 failures?** 936 in-window weather gaps and 96 antecedent forecast-lookback gaps; failures are retained, not imputed.
20. **Why equal service?** A scheduler doing less work naturally uses less energy; that is not efficiency.
21. **What was wrong with SFO transfer?** The scaler/model/calibration encode SFO climate/errors but were silently applied to four other stations contrary to protocol.
22. **What survives that issue?** Static and realized oracle results for this specific defect; narrow static G1 is strongest.
23. **How reproducible is it?** v1 is strong same-environment with an archive; B2 is reproducible only in this dirty working tree, not a clean clone.
24. **Why is continuity unproven?** No state-preserving isolated-day ablation or hourly backlog/allocation traces exist.
25. **What next?** Implement previous-day/station-specific forecasts, rerun affected cells, freeze estimands, improve common support, and prospectively execute G4/G5.
26. **Does −0.5× mean 50% less capacity?** No; it is a difference on a coarse tested workload grid, not a physical capacity percentage.
27. **Are carbon values avoided emissions?** No; they are average-intensity accounting proxies.
28. **Did TinyLSTM error cause regret?** Unknown; forecast substitution was not controlled.
29. **Why can a null help?** It bounds claims and prevents a benchmark artifact from being mistaken for general improvement.
30. **Why pass tests but fail audit?** Tests checked internal contracts, not the omitted protocol constraint on station-specific models.

## 10.5 What not to claim

- “We proved HeatGuard is safer/better.”
- “We reduced carbon emissions” or “avoided emissions.”
- “756/6,480 independent experiments.”
- “The −0.5× effect is a 50% physical capacity loss.”
- “Forecast accuracy caused the outcome.”
- “Inland California is definitively worse.”
- “G3 proves heatwaves always discriminate policies.”
- “B2 is clean-clone reproducible.”
- “All 2022 data are missing.” Only one EIA hour is missing under the annual gate.
- “A successful run is feasible.” Many successful executions produce infeasible modeled schedules.

