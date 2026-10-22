"""Evaluation strategy comparison (P5-11 / E4).

Compares:
- ordinary_window
- event_stratified
- phase_aware

Under verified equal 120-hour evaluation budgets.
"""

from __future__ import annotations

from typing import Any
import pandas as pd


def compare_evaluation_strategies(
    sampling_metrics_df: pd.DataFrame,
    manifests: dict[str, pd.DataFrame],
    target_budget_hours: int = 120,
) -> dict[str, Any]:
    """Analyze and compare policy rankings and metrics across equal-budget sampling strategies."""
    # Verify budgets
    strategy_summaries: list[dict[str, Any]] = []

    for strat_name, manifest in manifests.items():
        achieved_budget = len(manifest)
        shortfall = max(0, target_budget_hours - achieved_budget)

        # Composition by window and phase
        w_comp = manifest["window_id"].value_counts().to_dict()
        p_comp = manifest["phase_label"].value_counts().to_dict()

        strat_summaries = sampling_metrics_df[sampling_metrics_df["sampling_strategy"] == strat_name].copy()
        
        # Rank policies by realized cost
        strat_summaries = strat_summaries.sort_values("total_realized_cost_usd")
        ranked_policies = strat_summaries["policy_name"].tolist()

        strategy_summaries.append({
            "sampling_strategy": strat_name,
            "target_budget_hours": target_budget_hours,
            "achieved_budget_hours": achieved_budget,
            "budget_shortfall": shortfall,
            "window_composition": w_comp,
            "phase_composition": p_comp,
            "policy_cost_ranking": ranked_policies,
            "ranking_identical_across_policies": (strat_summaries["total_realized_cost_usd"].nunique() == 1),
            "sample_size_limitation": "Single 120h evaluation budget per strategy; ranking differences are descriptive.",
        })

    summary_df = pd.DataFrame(strategy_summaries)

    return {
        "strategy_comparison_summary": summary_df,
        "sampling_metrics": sampling_metrics_df,
    }
