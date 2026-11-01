# 6. The six schedulers

| Policy | Information | Decision | Capacity | Status |
|---|---|---|---|---|
| Static unaware | market forecast, jobs; no temperature/PUE | greedy carbon/cost hours | nominal only | deployable |
| Capacity aware | above + forecast effective capacity | greedy then capacity repair | forecast derated | deployable |
| Full thermal aware | above + forecast PUE | greedy on price/carbon × PUE, then repair | forecast derated | deployable |
| HeatGuard fixed | full thermal inputs + 0.10 PUE margin | 24h rolling/1h commit | guarded forecast | deployable heuristic |
| HeatGuard calibrated | full thermal inputs + past-only residual quantile | same | calibrated guarded forecast | deployable heuristic |
| Oracle full thermal | realized PUE, price, carbon | same greedy structure with hindsight | realized | non-deployable reference |

Implementations are `StaticUnawarePolicy`, `CapacityAwarePolicy`, `FullThermalAwarePolicy`, and `OracleFullThermalAwarePolicy` in `thermal/policies.py`; `HeatGuardScheduler` is in `thermal/heatguard.py`; rolling orchestration is in the v1/B2 runners.

Using the same two-slot four-hour job from Chapter 5: static carbon-first chooses hours 1 and 2. Capacity-aware sees hour-1 capacity zero and repairs to 2 and 3. Full thermal-aware may prefer 3 over 2 if hour 2’s higher PUE makes `carbon×PUE` worse. Fixed HeatGuard may reserve even more headroom and move to 0 and 3 or fail to place a slot. Calibrated HeatGuard behaves similarly with a smaller/larger empirical margin. Oracle knows realized hour-1 outage and true market signals, providing a hindsight lower-bound/comparator, not an operational policy.

Strengths: static is simple; capacity-aware respects forecast physical limits; full thermal-aware internalizes cooling overhead; guards hedge underprediction; oracle diagnoses the value of perfect information. Weaknesses: greedy allocation is myopic, forecast variants inherit forecast/calibration errors, guard margins can be conservative, and oracle cannot be deployed. None is formal DRO.

## B2 protocol compliance audit

`B2ExecutionRunner.__init__` hard-codes `data/models/p6_temperature_v2/tiny_lstm_checkpoint.pt`, extracts its scaler, and `prepare_temperature_forecasts` applies that model to whatever station the window names. HeatGuard paths hard-code `data/models/p6_heatguard_calibration_v3`. Station identity selects raw weather but never selects a station-specific model.

Affected policies are capacity-aware, full thermal-aware, fixed HeatGuard, and calibrated HeatGuard. Stage 2 counted 3,960 affected non-SFO cells: LAX 1,440, RDD 1,080, SAC 720, FAT 720; 3,264 succeeded and 696 failed. Static does not consume temperature forecasts, and oracle consumes realized temperature, so those policies are unaffected by this particular defect. SFO is also not cross-station transfer, though its v1 training boundary should still be described honestly.

Why it matters: a scaler encodes SFO’s climate distribution, an LSTM learns SFO temporal patterns, and calibration residuals encode SFO errors. Applying them inland changes numerical meaning and safety coverage. The frozen B2 protocol explicitly prohibits silent transfer. Its fallback would copy each station’s own last 24 historical hours into the next 24 predictions—causal, simple, station-specific, and weaker in sophistication but valid under the declared contract.

Thus the B2 implementation is deterministic but forecast-aware non-SFO comparisons are protocol-invalid. It is not enough that the code reproduces the same numbers.

