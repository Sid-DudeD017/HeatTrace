# F3 Status Artifact: Forecast-Sensitive Scheduling Regret

**Status:** NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION
**Reason:** Calculating causal scheduling regret requires a controlled counterfactual forecast intervention under the identical scheduler, facility model, and workload.
**Constraint Rule:**
1. The oracle reference policy (`oracle_full_thermal_aware`) is strictly marked `deployable: false` and cannot serve as a deployable regret reference.
2. In 2 of 36 control runs, the oracle itself experienced unfinished processing slots (infeasible service), violating the equal-service baseline requirement.
3. The frozen P8 matrix contains no ablation varying forecast inputs (e.g., LSTM vs. Persistence) while holding the scheduler fixed.
**Scientific Conclusion:** True forecast regret is unestimable from the frozen confirmation matrix. Fabricating regret values without a controlled comparison basis is prohibited.
