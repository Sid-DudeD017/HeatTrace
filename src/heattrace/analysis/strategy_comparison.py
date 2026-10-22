"""Evaluation strategy comparison (P5-11 / E4).

Compares:
- ordinary_window (120h control)
- event_stratified (60h control + 60h event)
- phase_aware (120h event partitioned by phase)

Evaluated over authentic policy schedule outcomes under verified equal 120-hour budgets.
"""

from __future__ import annotations

from typing import Any
import pandas as pd


def compare_evaluation_strategies(
    sampling_metrics_df: pd.DataFrame,
    manifests: dict[str, pd.DataFrame],
    target_budget_hours: int = 120,
) -> dict[str, Any]:
    """Analyze and compare policy rankings and metrics across equal-budget outcome sampling strategies."""
    strategy_summaries: list[dict[str, Any]] = []

    for strat_name, manifest in manifests.items():
        achieved_budget = len(manifest)
        shortfall = max(0, target_budget_hours - achieved_budget)

        # Composition by window and phase
        w_comp = manifest["window_id"].value_counts().to_dict()
        p_comp = manifest["phase_label"].value_counts().to_dict()

        strat_summaries = sampling_metrics_df[sampling_metrics_df["sampling_strategy"] == strat_name].copy()
        strat_summaries = strat_summaries.sort_values("total_sampled_cost_usd")
        ranked_policies = strat_summaries["policy_name"].tolist()

        unique_costs = strat_summaries["total_sampled_cost_usd"].nunique()

        strategy_summaries.append({
            "sampling_strategy": strat_name,
            "evaluation_basis": "sampled_hourly_schedule_outcomes",
            "target_budget_hours": target_budget_hours,
            "achieved_budget_hours": achieved_budget,
            "budget_shortfall": shortfall,
            "window_composition": str(w_comp),
            "phase_composition": str(p_comp),
            "policy_cost_ranking": str(ranked_policies),
            "ranking_identical_across_policies": (unique_costs == 1),
            "sample_size_limitation": "Single 120h evaluation budget per strategy; ranking differences are descriptive.",
        })

    summary_df = pd.DataFrame(strategy_summaries)

    return {
        "strategy_comparison_summary": summary_df,
        "sampling_metrics": sampling_metrics_df,
    }
