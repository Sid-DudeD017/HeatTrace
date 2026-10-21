"""Risk-penalized DRO-inspired scheduling heuristic.

IMPORTANT LIMITATIONS & METHODOLOGICAL DISCLOSURE:
- This is a heuristic approximation inspired by distributionally robust optimization (DRO),
  NOT a formal mathematical DRO optimizer with dual conic solvers.
- It does not solve an exact supremum over a Wasserstein or moment ambiguity set.
- It provides no formal mathematical robustness certificate or worst-case guarantee.
- Uncertainty penalties are estimated from causal pre-origin historical forecast errors.
- Results are dependent on the historical error proxy and small sample sizes.
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

from heattrace.policy.common import (
    ClusterState,
    normalize_series_min_max,
    sort_workload_jobs_deterministically,
)
from heattrace.policy.feasibility import validate_schedule_feasibility
from heattrace.policy.greedy import _schedule_greedy_with_scoring
from heattrace.policy.interfaces import (
    ForecastResult,
    ScheduleResult,
    ScheduledJobAllocation,
    SchedulingConstraints,
    SchedulingPolicy,
)


class RiskPenalizedDROInspiredPolicy:
    """Heuristic policy adding a quantile-based uncertainty penalty to the balanced objective.

    Score:
      risk_adjusted_score = expected_balanced_score + lambda * uncertainty_penalty
    """

    def __init__(
        self,
        cost_weight: float = 0.5,
        carbon_weight: float = 0.5,
        cvar_alpha: float = 0.90,
        uncertainty_quantile: float = 0.90,
        dro_risk_penalty_lambda: float = 0.25,
        fallback_uncertainty_bound: float = 0.50,
    ):
        self.cost_weight = cost_weight
        self.carbon_weight = carbon_weight
        self.cvar_alpha = cvar_alpha
        self.uncertainty_quantile = uncertainty_quantile
        self.dro_risk_penalty_lambda = dro_risk_penalty_lambda
        self.fallback_uncertainty_bound = fallback_uncertainty_bound

    @property
    def policy_name(self) -> str:
        return "dro_inspired"

    @property
    def policy_version(self) -> str:
        return "1.0"

    def compute_uncertainty_penalty(
        self,
        forecast: ForecastResult,
        history_errors: list[float] | None = None,
    ) -> float:
        """Estimate uncertainty penalty strictly from causal pre-origin residuals."""
        if history_errors is not None and len(history_errors) >= 3:
            # Quantile of pre-origin residuals
            arr = np.array(history_errors)
            penalty = float(np.quantile(arr, self.uncertainty_quantile))
            return max(0.0, penalty)
        return self.fallback_uncertainty_bound

    def schedule(
        self,
        workload_df: pd.DataFrame,
        forecast: ForecastResult,
        constraints: SchedulingConstraints,
        *,
        history_errors: list[float] | None = None,
    ) -> ScheduleResult:
        # Base balanced expected objective
        uncertainty_penalty = self.compute_uncertainty_penalty(forecast, history_errors)
        risk_penalty = self.dro_risk_penalty_lambda * uncertainty_penalty

        # If lambda == 0, exactly equals balanced objective
        # The penalty can also be hour-dependent if forecast uncertainty varies by horizon:
        # Here we scale with horizon or keep transparent constant additive penalty:
        # hour_score = balanced_score + (1.0 + h / horizon) * risk_penalty
        # This penalizes distant uncertain hours more heavily when lambda > 0.
        horizon = len(forecast.points)

        return _schedule_greedy_with_scoring(
            workload_df,
            forecast,
            constraints,
            policy_name=self.policy_name,
            policy_version=self.policy_version,
            hour_score_fn=lambda h, norm_p, norm_c: (
                (self.cost_weight * norm_p + self.carbon_weight * norm_c)
                + (1.0 + float(h) / max(1, horizon)) * risk_penalty
            ),
        )
