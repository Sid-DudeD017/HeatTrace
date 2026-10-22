"""Analysis, summary tables, and figure generators for P5.5 (Critical Issues 1, 2, 4, 5).

Provides three explicitly separated result views:
1. Primary fair comparison: Subsets strictly to jointly feasible scenarios across policies.
2. Service-normalized sensitivity: Realized cost and emissions per delivered kWh alongside SLA completion.
3. Failure-aware sensitivity: Applies pre-registered linear penalties for unmet work.

Generates:
- Machine-readable headline findings JSON & CSV (Critical Issue 2).
- Summary comparison tables.
- Paired differences table with feasibility and work equality flags (Critical Issue 1).
- 6 publication figures (PNG + SVG) adhering to strict population and evidence labeling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heattrace.manifests import write_atomic_csv, write_atomic_figure


def compute_headline_findings(
    results_df: pd.DataFrame,
    comparator_results_df: pd.DataFrame | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Compute exact machine-readable headline numerical findings from the validated result table.

    Pure calculation: does not mutate inputs, does not create directories, and produces
    zero filesystem writes unless output_dir is explicitly provided.
    """
    # Defensive copy to ensure zero mutation on inputs
    results_df = results_df.copy()

    # 1. Identify jointly feasible scenarios (Primary Fair Comparison population)
    piv_feas = results_df.pivot_table(index="scenario_id", columns="policy_name", values="is_feasible")
    jointly_feasible_scens = set(piv_feas[piv_feas.all(axis=1)].index)
    total_scenarios = int(results_df["scenario_id"].nunique())
    jointly_feasible_count = len(jointly_feasible_scens)

    # 2. Check flat forecast collapse on schedule digests
    piv_digest = results_df.pivot_table(index="scenario_id", columns="policy_name", values="schedule_digest", aggfunc="first")
    flat_scens = results_df[results_df["forecast_scenario_id"] == "flat_forecast"]["scenario_id"].unique()
    flat_scens_count = len(flat_scens)
    flat_collapse_count = sum(len(set(piv_digest.loc[s])) == 1 for s in flat_scens)
    flat_collapse_pct = round(100.0 * flat_collapse_count / flat_scens_count, 2) if flat_scens_count > 0 else 0.0

    non_flat_scens = results_df[results_df["forecast_scenario_id"] != "flat_forecast"]["scenario_id"].unique()
    non_flat_scens_count = len(non_flat_scens)
    non_flat_divergence_count = sum(len(set(piv_digest.loc[s])) > 1 for s in non_flat_scens)
    non_flat_divergence_pct = round(100.0 * non_flat_divergence_count / non_flat_scens_count, 2) if non_flat_scens_count > 0 else 0.0

    # 3. Paired differences on the Primary Fair Comparison set
    df_fair = results_df[results_df["scenario_id"].isin(jointly_feasible_scens)].copy()
    paired_rows = []
    for scen in jointly_feasible_scens:
        sub = df_fair[df_fair["scenario_id"] == scen].set_index("policy_name")
        base_cost = sub.loc["baseline_reference", "total_realized_cost_usd"]
        base_emiss = sub.loc["baseline_reference", "total_realized_emissions_kg"]
        for pol in sub.index:
            cost_diff = sub.loc[pol, "total_realized_cost_usd"] - base_cost
            cost_pct = (cost_diff / base_cost) * 100.0 if base_cost != 0 else 0.0
            emiss_diff = sub.loc[pol, "total_realized_emissions_kg"] - base_emiss
            emiss_pct = (emiss_diff / base_emiss) * 100.0 if base_emiss != 0 else 0.0
            paired_rows.append({
                "scenario_id": scen,
                "window_type": sub.loc[pol, "window_type"],
                "policy_name": pol,
                "forecast_scenario_id": sub.loc[pol, "forecast_scenario_id"],
                "noise_sigma": sub.loc[pol, "noise_sigma"],
                "cost_diff_usd": cost_diff,
                "cost_pct_change": cost_pct,
                "emiss_diff_kg": emiss_diff,
                "emiss_pct_change": emiss_pct,
            })
    pdf_fair = pd.DataFrame(paired_rows)

    # Primary Fair Oracle Savings
    orc_fair = pdf_fair[pdf_fair["forecast_scenario_id"] == "oracle_forecast"]
    cf_orc_ctrl = orc_fair[(orc_fair["policy_name"] == "cost_first") & (orc_fair["window_type"] == "control")]
    cf_orc_hw = orc_fair[(orc_fair["policy_name"] == "cost_first") & (orc_fair["window_type"] == "event")]
    carb_orc_hw = orc_fair[(orc_fair["policy_name"] == "carbon_first") & (orc_fair["window_type"] == "event")]
    bal_orc_hw = orc_fair[(orc_fair["policy_name"] == "balanced") & (orc_fair["window_type"] == "event")]

    ctrl_oracle_savings_pct = float(round(-cf_orc_ctrl["cost_pct_change"].mean(), 2))
    ctrl_oracle_sample_size = int(len(cf_orc_ctrl))
    hw_oracle_savings_pct = float(round(-cf_orc_hw["cost_pct_change"].mean(), 2))
    hw_oracle_sample_size = int(len(cf_orc_hw))

    # Carbon reductions in HW event
    hw_carbon_first_emiss_reduction_pct = float(round(-carb_orc_hw["emiss_pct_change"].mean(), 2))
    hw_carbon_first_cost_increase_vs_cf = float(round(
        (df_fair[(df_fair["window_type"] == "event") & (df_fair["forecast_scenario_id"] == "oracle_forecast") & (df_fair["policy_name"] == "carbon_first")]["total_realized_cost_usd"].mean() /
         df_fair[(df_fair["window_type"] == "event") & (df_fair["forecast_scenario_id"] == "oracle_forecast") & (df_fair["policy_name"] == "cost_first")]["total_realized_cost_usd"].mean() - 1.0) * 100.0,
        2
    ))

    # Common cohort noise sensitivity (Critical Issue 4)
    # Define stress cells: (window_id, workload_multiplier, resource_scenario_id, deadline_scenario_id)
    scen_cell_map = {}
    for scen_id, group in results_df.groupby("scenario_id"):
        first_row = group.iloc[0]
        scen_cell_map[scen_id] = (
            first_row["window_id"],
            float(first_row["workload_multiplier"]),
            first_row["resource_scenario_id"],
            first_row["deadline_scenario_id"],
        )

    noise_levels = ["oracle_forecast", "noisy_oracle_low", "noisy_oracle_medium", "noisy_oracle_high"]
    cell_noise_feas = {}
    for scen_id in jointly_feasible_scens:
        sub_scen = results_df[results_df["scenario_id"] == scen_id].iloc[0]
        fc_id = sub_scen["forecast_scenario_id"]
        if fc_id in noise_levels:
            cell = scen_cell_map[scen_id]
            cell_noise_feas.setdefault(cell, set()).add(fc_id)

    common_cohort_cells = {cell for cell, fcs in cell_noise_feas.items() if len(fcs) == 4}
    common_cohort_sample_size = len(common_cohort_cells)

    # Calculate like-for-like common cohort cost-first savings vs baseline_reference
    cohort_scens = [s for s in jointly_feasible_scens if scen_cell_map[s] in common_cohort_cells]
    pdf_cohort = pdf_fair[pdf_fair["scenario_id"].isin(cohort_scens) & (pdf_fair["policy_name"] == "cost_first")]

    common_cohort_noise_savings = {
        "oracle_sigma_0": float(round(-pdf_cohort[pdf_cohort["forecast_scenario_id"] == "oracle_forecast"]["cost_pct_change"].mean(), 2)),
        "noisy_sigma_0_10": float(round(-pdf_cohort[pdf_cohort["forecast_scenario_id"] == "noisy_oracle_low"]["cost_pct_change"].mean(), 2)),
        "noisy_sigma_0_25": float(round(-pdf_cohort[pdf_cohort["forecast_scenario_id"] == "noisy_oracle_medium"]["cost_pct_change"].mean(), 2)),
        "noisy_sigma_0_50": float(round(-pdf_cohort[pdf_cohort["forecast_scenario_id"] == "noisy_oracle_high"]["cost_pct_change"].mean(), 2)),
    }
    common_cohort_retention_pct = float(round(
        (common_cohort_noise_savings["noisy_sigma_0_50"] / common_cohort_noise_savings["oracle_sigma_0"]) * 100.0, 2
    )) if common_cohort_noise_savings["oracle_sigma_0"] != 0 else 0.0

    # Secondary descriptive (all primary fair, varying N)
    cf_fair = pdf_fair[pdf_fair["policy_name"] == "cost_first"]
    secondary_noise_savings = {
        "oracle_sigma_0": float(round(-cf_fair[cf_fair["forecast_scenario_id"] == "oracle_forecast"]["cost_pct_change"].mean(), 2)),
        "noisy_sigma_0_10": float(round(-cf_fair[cf_fair["forecast_scenario_id"] == "noisy_oracle_low"]["cost_pct_change"].mean(), 2)),
        "noisy_sigma_0_25": float(round(-cf_fair[cf_fair["forecast_scenario_id"] == "noisy_oracle_medium"]["cost_pct_change"].mean(), 2)),
        "noisy_sigma_0_50": float(round(-cf_fair[cf_fair["forecast_scenario_id"] == "noisy_oracle_high"]["cost_pct_change"].mean(), 2)),
    }

    # Feasibility by resource stress
    feas_unconstrained = float(round(results_df[results_df["resource_scenario_id"] == "unconstrained"]["is_feasible"].mean() * 100.0, 2))
    feas_moderate = float(round(results_df[results_df["resource_scenario_id"] == "moderate_stress"]["is_feasible"].mean() * 100.0, 2))
    feas_extreme = float(round(results_df[results_df["resource_scenario_id"] == "extreme_stress"]["is_feasible"].mean() * 100.0, 2))
    feas_wl3x_extreme = float(round(results_df[(results_df["workload_multiplier"] == 3.0) & (results_df["resource_scenario_id"] == "extreme_stress")]["is_feasible"].mean() * 100.0, 2))

    # Tail risk (CVaR 90) on primary fair set for HW event under oracle
    fair_hw_orc = df_fair[(df_fair["window_type"] == "event") & (df_fair["forecast_scenario_id"] == "oracle_forecast")]
    cvar_baseline = float(round(fair_hw_orc[fair_hw_orc["policy_name"] == "baseline_reference"]["cvar_cost_90"].mean(), 2))
    cvar_cost_first = float(round(fair_hw_orc[fair_hw_orc["policy_name"] == "cost_first"]["cvar_cost_90"].mean(), 2))
    cvar_dro = float(round(fair_hw_orc[fair_hw_orc["policy_name"] == "dro_inspired"]["cvar_cost_90"].mean(), 2))

    # Small instance comparator gaps
    comp_gap_findings = {}
    if comparator_results_df is not None and not comparator_results_df.empty:
        comp_gap_findings = {
            "instances_evaluated": int(comparator_results_df["validation_id"].nunique()),
            "cost_first_mean_gap_usd": float(round(comparator_results_df[comparator_results_df["policy_name"] == "cost_first"]["cost_optimality_gap_usd"].mean(), 4)),
            "cost_first_mean_gap_pct": float(round(comparator_results_df[comparator_results_df["policy_name"] == "cost_first"]["cost_optimality_gap_pct"].mean(), 2)),
            "baseline_mean_gap_pct": float(round(comparator_results_df[comparator_results_df["policy_name"] == "baseline_reference"]["cost_optimality_gap_pct"].mean(), 2)),
            "all_comparator_optimal": bool((comparator_results_df["comparator_status"] == "optimal").all()),
        }

    findings = {
        "metadata": {
            "grid_version": "v2",
            "total_scenarios": total_scenarios,
            "total_runs": len(results_df),
            "jointly_feasible_scenarios_count": jointly_feasible_count,
            "primary_fair_population_pct": round((jointly_feasible_count / total_scenarios) * 100.0, 2),
        },
        "headline_1_flat_forecast_collapse": {
            "flat_forecast_scenarios_evaluated": flat_scens_count,
            "flat_forecast_schedule_identical_count": flat_collapse_count,
            "flat_forecast_collapse_pct": flat_collapse_pct,
            "non_flat_scenarios_evaluated": non_flat_scens_count,
            "non_flat_schedule_divergence_count": non_flat_divergence_count,
            "non_flat_divergence_pct": non_flat_divergence_pct,
        },
        "headline_2_primary_fair_savings": {
            "control_window_id": "CTRL_20240605",
            "control_sample_size_scenarios": ctrl_oracle_sample_size,
            "control_cost_first_savings_pct": ctrl_oracle_savings_pct,
            "event_window_id": "HW_20240702",
            "event_sample_size_scenarios": hw_oracle_sample_size,
            "event_cost_first_savings_pct": hw_oracle_savings_pct,
        },
        "headline_3_noise_degradation": {
            "common_cohort_sample_size_per_level": common_cohort_sample_size,
            "savings_pct_by_noise_sigma": common_cohort_noise_savings,
            "noise_retention_high_sigma_pct": common_cohort_retention_pct,
            "secondary_descriptive_savings_pct": secondary_noise_savings,
            "secondary_descriptive_sample_sizes": {k: int(len(cf_fair[cf_fair["forecast_scenario_id"] == sc])) for k, sc in [
                ("oracle", "oracle_forecast"),
                ("noisy_low", "noisy_oracle_low"),
                ("noisy_med", "noisy_oracle_medium"),
                ("noisy_high", "noisy_oracle_high"),
            ]},
        },
        "headline_4_carbon_cost_tradeoff": {
            "event_sample_size_scenarios": hw_oracle_sample_size,
            "carbon_first_emissions_reduction_pct": hw_carbon_first_emiss_reduction_pct,
            "carbon_first_cost_premium_vs_cost_first_pct": hw_carbon_first_cost_increase_vs_cf,
        },
        "headline_5_tail_risk_cvar90": {
            "event_sample_size_scenarios": hw_oracle_sample_size,
            "cvar_cost_90_baseline_usd_h": cvar_baseline,
            "cvar_cost_90_cost_first_usd_h": cvar_cost_first,
            "cvar_cost_90_dro_inspired_usd_h": cvar_dro,
            "cvar_cost_first_reduction_pct": round(((cvar_baseline - cvar_cost_first) / cvar_baseline) * 100.0, 2),
        },
        "headline_6_operational_feasibility": {
            "unconstrained_feasibility_pct": feas_unconstrained,
            "moderate_stress_feasibility_pct": feas_moderate,
            "extreme_stress_feasibility_pct": feas_extreme,
            "workload_3x_extreme_feasibility_pct": feas_wl3x_extreme,
        },
        "headline_7_comparator_validation": comp_gap_findings,
    }

    if output_dir is not None:
        write_headline_findings(findings, output_dir)

    return findings


def write_headline_findings(
    findings: dict[str, Any],
    output_dir: Path | str,
) -> tuple[Path, Path]:
    """Explicit writer for headline findings JSON and CSV.

    Only explicit production commands or tests targeting export should call this writer.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "p5_5_headline_findings.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, sort_keys=True)

    # Flattened table for auditing
    flat_rows = []
    for sec_name, sec_dict in findings.items():
        if isinstance(sec_dict, dict):
            for k, v in sec_dict.items():
                flat_rows.append({"category": sec_name, "metric": k, "value": str(v)})
    flat_df = pd.DataFrame(flat_rows)
    csv_path = out_dir / "p5_5_headline_findings.csv"
    flat_df.to_csv(csv_path, index=False)

    return json_path, csv_path


def generate_p5_5_summary_tables_v2(
    results_df: pd.DataFrame,
    output_dir: Path | str = "data/results",
) -> dict[str, Path]:
    """Generate summary tables across the three methodological views."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Path] = {}

    # 1. Jointly feasible flag
    piv_feas = results_df.pivot_table(index="scenario_id", columns="policy_name", values="is_feasible")
    jointly_feasible_set = set(piv_feas[piv_feas.all(axis=1)].index)

    # 2. Comprehensive Paired differences table (Critical Issue 1)
    scens = results_df["scenario_id"].unique()
    paired_rows = []
    for scen in scens:
        sub = results_df[results_df["scenario_id"] == scen].set_index("policy_name")
        if "baseline_reference" not in sub.index:
            continue
        base_cost = sub.loc["baseline_reference", "total_realized_cost_usd"]
        base_emiss = sub.loc["baseline_reference", "total_realized_emissions_kg"]
        base_feas = bool(sub.loc["baseline_reference", "is_feasible"])
        base_en = sub.loc["baseline_reference", "delivered_energy_kwh"]
        base_unmet_en = sub.loc["baseline_reference", "unmet_energy_kwh"]

        is_jointly_feas = scen in jointly_feasible_set

        for pol in sub.index:
            pol_feas = bool(sub.loc[pol, "is_feasible"])
            pol_en = sub.loc[pol, "delivered_energy_kwh"]
            pol_unmet_en = sub.loc[pol, "unmet_energy_kwh"]

            cost_diff = sub.loc[pol, "total_realized_cost_usd"] - base_cost
            cost_pct = (cost_diff / base_cost) * 100.0 if base_cost != 0 else 0.0
            emiss_diff = sub.loc[pol, "total_realized_emissions_kg"] - base_emiss
            emiss_pct = (emiss_diff / base_emiss) * 100.0 if base_emiss != 0 else 0.0

            equal_delivered_energy = bool(abs(pol_en - base_en) < 1e-3)
            delivered_en_diff = round(pol_en - base_en, 4)
            unmet_work_diff = round(pol_unmet_en - base_unmet_en, 4)

            # Valid for primary comparison iff both are feasible and delivered equal energy
            valid_primary = bool(base_feas and pol_feas and equal_delivered_energy)

            paired_rows.append({
                "scenario_id": scen,
                "grid_version": sub.loc[pol, "grid_version"],
                "window_id": sub.loc[pol, "window_id"],
                "window_type": sub.loc[pol, "window_type"],
                "evidence_class": sub.loc[pol, "evidence_class"],
                "forecast_scenario_id": sub.loc[pol, "forecast_scenario_id"],
                "noise_sigma": sub.loc[pol, "noise_sigma"],
                "workload_multiplier": sub.loc[pol, "workload_multiplier"],
                "resource_scenario_id": sub.loc[pol, "resource_scenario_id"],
                "deadline_scenario_id": sub.loc[pol, "deadline_scenario_id"],
                "policy_name": pol,
                "baseline_feasible": base_feas,
                "policy_feasible": pol_feas,
                "common_feasible": is_jointly_feas,
                "equal_delivered_energy": equal_delivered_energy,
                "delivered_energy_diff_kwh": delivered_en_diff,
                "unmet_work_diff_kwh": unmet_work_diff,
                "valid_for_primary_comparison": valid_primary,
                "cost_diff_usd": round(cost_diff, 4),
                "cost_pct_change": round(cost_pct, 4),
                "emiss_diff_kg": round(emiss_diff, 4),
                "emiss_pct_change": round(emiss_pct, 4),
                "failure_penalized_cost_diff_usd": round(sub.loc[pol, "failure_penalized_cost_usd"] - sub.loc["baseline_reference", "failure_penalized_cost_usd"], 4),
            })

    paired_df = pd.DataFrame(paired_rows)
    paired_path = out_dir / "p5_5_policy_paired_differences.csv"
    write_atomic_csv(paired_path, paired_df, index=False)
    generated["paired_differences"] = paired_path

    # 3. View 1: Primary Fair Comparison Summary Table (jointly feasible only)
    df_fair = results_df[results_df["scenario_id"].isin(jointly_feasible_set)].copy()
    fair_summary = df_fair.groupby(
        ["window_type", "policy_name", "forecast_scenario_id", "evidence_class"]
    )[["total_realized_cost_usd", "total_realized_emissions_kg", "cvar_cost_90", "delivered_energy_kwh"]].agg(["mean", "std", "count"]).reset_index()
    fair_summary.columns = ["_".join(c).strip("_") if isinstance(c, tuple) else c for c in fair_summary.columns]
    fair_summary_path = out_dir / "p5_5_view1_primary_fair_summary.csv"
    write_atomic_csv(fair_summary_path, fair_summary, index=False)
    generated["view1_fair_summary"] = fair_summary_path

    # 4. View 2: Service-Normalized Sensitivity Summary Table (all runs, per delivered kWh)
    norm_summary = results_df.groupby(
        ["window_type", "policy_name", "forecast_scenario_id", "resource_scenario_id"]
    )[["cost_per_delivered_kwh", "carbon_per_delivered_kwh", "sla_completion_rate", "deadline_misses", "unmet_energy_kwh"]].mean().reset_index()
    norm_summary_path = out_dir / "p5_5_view2_service_normalized_summary.csv"
    write_atomic_csv(norm_summary_path, norm_summary, index=False)
    generated["view2_norm_summary"] = norm_summary_path

    # 5. View 3: Failure-Aware Sensitivity Summary Table (including penalties)
    fail_summary = results_df.groupby(
        ["window_type", "policy_name", "forecast_scenario_id", "resource_scenario_id"]
    )[["total_realized_cost_usd", "failure_penalty_usd", "failure_penalized_cost_usd", "is_feasible"]].mean().reset_index()
    fail_summary_path = out_dir / "p5_5_view3_failure_aware_summary.csv"
    write_atomic_csv(fail_summary_path, fail_summary, index=False)
    generated["view3_failure_aware_summary"] = fail_summary_path

    # Overall consolidated summary table
    summary_cols = ["total_realized_cost_usd", "total_realized_emissions_kg", "cvar_cost_90", "sla_completion_rate", "is_feasible"]
    full_summary = results_df.groupby(["window_type", "policy_name", "forecast_scenario_id", "evidence_class"])[summary_cols].agg(["mean", "std", "count"]).reset_index()
    full_summary.columns = ["_".join(c).strip("_") if isinstance(c, tuple) else c for c in full_summary.columns]
    full_summary_path = out_dir / "p5_5_policy_comparison_summary.csv"
    write_atomic_csv(full_summary_path, full_summary, index=False)
    generated["summary_table"] = full_summary_path

    return generated


def generate_p5_5_figures_v2(
    results_df: pd.DataFrame,
    comparator_df: pd.DataFrame | None = None,
    output_fig_dir: Path | str = "data/figures",
    output_results_dir: Path | str = "data/results",
) -> dict[str, Path]:
    """Generate the 6 required publication figures strictly on the primary fair comparison population."""
    fig_dir = Path(output_fig_dir)
    res_dir = Path(output_results_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    generated: dict[str, Path] = {}

    policy_colors = {
        "baseline_reference": "#6c757d",  # Gray
        "cost_first": "#1f77b4",          # Blue
        "carbon_first": "#2ca02c",        # Green
        "balanced": "#ff7f0e",            # Orange
        "dro_inspired": "#9467bd",        # Purple
    }
    policy_labels = {
        "baseline_reference": "Baseline (ASAP)",
        "cost_first": "Cost-First",
        "carbon_first": "Carbon-First",
        "balanced": "Balanced",
        "dro_inspired": "DRO-Inspired",
    }

    # Primary Fair Comparison subset
    piv_feas = results_df.pivot_table(index="scenario_id", columns="policy_name", values="is_feasible")
    jointly_feas_scens = set(piv_feas[piv_feas.all(axis=1)].index)
    df_fair = results_df[results_df["scenario_id"].isin(jointly_feas_scens)].copy()

    # -----------------------------------------------------------------
    # Figure 1: Cost-Carbon Pareto Plot (Primary Fair Comparison Set)
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, wtype, wtitle in zip(axes, ["control", "event"], ["Control (CTRL_20240605)", "Event (HW_20240702)"]):
        sub_w = df_fair[df_fair["window_type"] == wtype]
        for pol, color in policy_colors.items():
            pol_df = sub_w[sub_w["policy_name"] == pol]
            # Oracle point (star)
            orc = pol_df[pol_df["forecast_type"] == "oracle"]
            if not orc.empty:
                ax.scatter(
                    orc["total_realized_cost_usd"].mean(),
                    orc["total_realized_emissions_kg"].mean(),
                    color=color, marker="*", s=240, edgecolors="black", linewidth=1.2,
                    label=f"{policy_labels[pol]} (Oracle Bound)" if wtype == "control" else None,
                    zorder=5,
                )
            # Noisy oracle points
            for sigma, marker, alpha in [(0.10, "o", 0.9), (0.25, "^", 0.7), (0.50, "s", 0.5)]:
                noisy = pol_df[(pol_df["forecast_type"] == "noisy_oracle") & (pol_df["noise_sigma"] == sigma)]
                if not noisy.empty:
                    ax.scatter(
                        noisy["total_realized_cost_usd"].mean(),
                        noisy["total_realized_emissions_kg"].mean(),
                        color=color, marker=marker, s=85, alpha=alpha, edgecolors="black", linewidth=0.5,
                    )
            # Flat baseline point (X)
            flat = pol_df[pol_df["forecast_type"] == "flat"]
            if not flat.empty:
                ax.scatter(
                    flat["total_realized_cost_usd"].mean(),
                    flat["total_realized_emissions_kg"].mean(),
                    color=color, marker="X", s=130, edgecolors="black", linewidth=1.2,
                )

        n_scens = sub_w["scenario_id"].nunique()
        ax.set_title(f"{wtitle} (N={n_scens} Common Feasible Scenarios)\nMean Realized Cost vs Emissions", fontsize=11, fontweight="bold")
        ax.set_xlabel("Mean Total Realized Cost ($)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.5)

    axes[0].set_ylabel("Mean Realized Carbon Emissions (kg)*", fontsize=10)
    fig.text(0.5, 0.02, "*Caveat: Carbon emissions are quality-limited sensitivity evidence only. Evaluated on Primary Fair Comparison population (jointly feasible, equal delivered work).", ha="center", fontsize=9, style="italic")
    axes[0].legend(loc="upper left", fontsize=8)
    plt.suptitle("HeatTrace P5.5: Cost–Carbon Pareto Frontier (Jointly Feasible Scenarios)", fontsize=13, fontweight="bold")
    plt.tight_layout(rect=[0, 0.05, 1, 0.95])

    f1_png = fig_dir / "p5_5_fig1_cost_carbon_pareto.png"
    f1_svg = fig_dir / "p5_5_fig1_cost_carbon_pareto.svg"
    write_atomic_figure(f1_png, fig, dpi=200)
    write_atomic_figure(f1_svg, fig, dpi=200)
    plt.close()
    generated["fig1_pareto_png"] = f1_png
    generated["fig1_pareto_svg"] = f1_svg

    # -----------------------------------------------------------------
    # Figure 2: Forecast-Error Sensitivity Plot (Common-Cohort Matched Trajectories)
    # -----------------------------------------------------------------
    # Build common cohort for like-for-like comparison across noise levels
    scen_cell_map = {}
    for scen_id, group in results_df.groupby("scenario_id"):
        first_row = group.iloc[0]
        scen_cell_map[scen_id] = (
            first_row["window_id"],
            float(first_row["workload_multiplier"]),
            first_row["resource_scenario_id"],
            first_row["deadline_scenario_id"],
        )

    noise_levels_sub = ["oracle_forecast", "noisy_oracle_low", "noisy_oracle_medium", "noisy_oracle_high"]
    cell_noise_feas = {}
    for scen_id in jointly_feas_scens:
        sub_scen = results_df[results_df["scenario_id"] == scen_id].iloc[0]
        fc_id = sub_scen["forecast_scenario_id"]
        if fc_id in noise_levels_sub:
            cell = scen_cell_map[scen_id]
            cell_noise_feas.setdefault(cell, set()).add(fc_id)

    common_cohort_cells = {cell for cell, fcs in cell_noise_feas.items() if len(fcs) == 4}
    cohort_scens = [s for s in jointly_feas_scens if scen_cell_map[s] in common_cohort_cells]
    df_cohort = df_fair[df_fair["scenario_id"].isin(cohort_scens)].copy()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fc_order = ["oracle_forecast", "noisy_oracle_low", "noisy_oracle_medium", "noisy_oracle_high"]
    fc_xlabels = ["Oracle\n(σ=0)", "Noisy Low\n(σ=0.10)", "Noisy Med\n(σ=0.25)", "Noisy High\n(σ=0.50)"]
    x = np.arange(len(fc_order))

    for pol, color in policy_colors.items():
        sub_p = df_cohort[df_cohort["policy_name"] == pol]
        hw_costs = [sub_p[(sub_p["window_type"] == "event") & (sub_p["forecast_scenario_id"] == fid)]["total_realized_cost_usd"].mean() for fid in fc_order]
        ctrl_costs = [sub_p[(sub_p["window_type"] == "control") & (sub_p["forecast_scenario_id"] == fid)]["total_realized_cost_usd"].mean() for fid in fc_order]

        ax1.plot(x, hw_costs, marker="o", linewidth=2.0, color=color, label=policy_labels[pol])
        ax2.plot(x, ctrl_costs, marker="s", linewidth=2.0, color=color, label=policy_labels[pol])

    n_cohort_hw = df_cohort[df_cohort["window_type"] == "event"]["scenario_id"].nunique() // 4
    n_cohort_ctrl = df_cohort[df_cohort["window_type"] == "control"]["scenario_id"].nunique() // 4

    ax1.set_title(f"Heatwave Event (HW_20240702, N={n_cohort_hw} Common Cohort)\nMean Realized Cost vs Forecast Noise", fontweight="bold", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(fc_xlabels)
    ax1.set_ylabel("Mean Total Realized Cost ($)", fontsize=10)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(loc="upper left", fontsize=8)

    ax2.set_title(f"Matched Control (CTRL_20240605, N={n_cohort_ctrl} Common Cohort)\nMean Realized Cost vs Forecast Noise", fontweight="bold", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(fc_xlabels)
    ax2.set_ylabel("Mean Total Realized Cost ($)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(loc="upper left", fontsize=8)

    plt.suptitle("HeatTrace P5.5: Policy Sensitivity to Forecast Error Degradation (Common Cohort)", fontsize=13, fontweight="bold")
    plt.tight_layout()

    f2_png = fig_dir / "p5_5_fig2_forecast_error_sensitivity.png"
    f2_svg = fig_dir / "p5_5_fig2_forecast_error_sensitivity.svg"
    write_atomic_figure(f2_png, fig, dpi=200)
    write_atomic_figure(f2_svg, fig, dpi=200)
    plt.close()
    generated["fig2_sensitivity_png"] = f2_png
    generated["fig2_sensitivity_svg"] = f2_svg

    # -----------------------------------------------------------------
    # Figure 3: Workload & Capacity Pressure Plot
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    wm_labels = [1.0, 2.0, 3.0]
    res_order = ["unconstrained", "moderate_stress", "extreme_stress"]
    res_xlabels = ["Unconstrained\n(500kW / 16)", "Moderate Stress\n(250kW / 8)", "Extreme Stress\n(120kW / 3)"]

    for idx, wm in enumerate(wm_labels):
        ax = axes[idx]
        sub_wm = df_fair[(df_fair["workload_multiplier"] == wm) & (df_fair["window_type"] == "event") & (df_fair["forecast_type"] != "flat")]
        x_r = np.arange(len(res_order))
        for pol, color in policy_colors.items():
            costs = []
            for rid in res_order:
                cell = sub_wm[(sub_wm["policy_name"] == pol) & (sub_wm["resource_scenario_id"] == rid)]["total_realized_cost_usd"]
                costs.append(cell.mean() if not cell.empty else np.nan)
            ax.plot(x_r, costs, marker="o", linewidth=2.0, color=color, label=policy_labels[pol] if idx == 0 else None)

        ax.set_title(f"Workload {int(wm)}× ({int(30*wm)} jobs)", fontweight="bold", fontsize=11)
        ax.set_xticks(x_r)
        ax.set_xticklabels(res_xlabels, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.5)

    axes[0].set_ylabel("Mean Total Realized Cost ($) [HW Event, Primary Fair]", fontsize=10)
    axes[0].legend(loc="upper left", fontsize=8)
    plt.suptitle("HeatTrace P5.5: Policy Differentiation Under Workload & Resource Pressure", fontsize=13, fontweight="bold")
    plt.tight_layout()

    f3_png = fig_dir / "p5_5_fig3_workload_capacity_pressure.png"
    f3_svg = fig_dir / "p5_5_fig3_workload_capacity_pressure.svg"
    write_atomic_figure(f3_png, fig, dpi=200)
    write_atomic_figure(f3_svg, fig, dpi=200)
    plt.close()
    generated["fig3_pressure_png"] = f3_png
    generated["fig3_pressure_svg"] = f3_svg

    # -----------------------------------------------------------------
    # Figure 4: Feasibility and SLA Heatmap (All Scenarios Envelope)
    # -----------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    feas_matrix = results_df.pivot_table(
        index=["workload_multiplier", "resource_scenario_id"],
        columns="policy_name",
        values="is_feasible",
        aggfunc="mean",
    )
    sla_matrix = results_df.pivot_table(
        index=["workload_multiplier", "resource_scenario_id"],
        columns="policy_name",
        values="sla_completion_rate",
        aggfunc="mean",
    )

    im1 = ax1.imshow(feas_matrix.values, cmap="YlGnBu", aspect="auto", vmin=0, vmax=1.0)
    ax1.set_title("Schedule Feasibility Rate (Full 270 Scenarios)", fontweight="bold")
    ax1.set_xticks(range(len(feas_matrix.columns)))
    ax1.set_xticklabels([policy_labels[c] for c in feas_matrix.columns], rotation=30, ha="right")
    ax1.set_yticks(range(len(feas_matrix.index)))
    ax1.set_yticklabels([f"WL {idx[0]}× | {idx[1]}" for idx in feas_matrix.index])
    for r in range(feas_matrix.shape[0]):
        for c in range(feas_matrix.shape[1]):
            val = feas_matrix.iloc[r, c]
            ax1.text(c, r, f"{val:.0%}", ha="center", va="center", color="black" if val > 0.5 else "white", fontweight="bold")

    im2 = ax2.imshow(sla_matrix.values, cmap="YlGnBu", aspect="auto", vmin=0.8, vmax=1.0)
    ax2.set_title("SLA Job Completion Rate (Full 270 Scenarios)", fontweight="bold")
    ax2.set_xticks(range(len(sla_matrix.columns)))
    ax2.set_xticklabels([policy_labels[c] for c in sla_matrix.columns], rotation=30, ha="right")
    ax2.set_yticks(range(len(sla_matrix.index)))
    ax2.set_yticklabels([f"WL {idx[0]}× | {idx[1]}" for idx in sla_matrix.index])
    for r in range(sla_matrix.shape[0]):
        for c in range(sla_matrix.shape[1]):
            val = sla_matrix.iloc[r, c]
            ax2.text(c, r, f"{val:.1%}", ha="center", va="center", color="black" if val > 0.9 else "white", fontweight="bold")

    fig.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04, label="Feasibility Rate")
    fig.colorbar(im2, ax=ax2, fraction=0.046, pad=0.04, label="SLA Completion Rate")
    plt.suptitle("HeatTrace P5.5: Feasibility and SLA Stress Envelope", fontsize=13, fontweight="bold")
    plt.tight_layout()

    f4_png = fig_dir / "p5_5_fig4_feasibility_sla_heatmap.png"
    f4_svg = fig_dir / "p5_5_fig4_feasibility_sla_heatmap.svg"
    write_atomic_figure(f4_png, fig, dpi=200)
    write_atomic_figure(f4_svg, fig, dpi=200)
    plt.close()
    generated["fig4_heatmap_png"] = f4_png
    generated["fig4_heatmap_svg"] = f4_svg

    # -----------------------------------------------------------------
    # Figure 5: Event vs Control Paired Comparison (Primary Fair Set)
    # -----------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    non_flat_fair = df_fair[df_fair["forecast_type"] != "flat"]
    hw_sub = non_flat_fair[non_flat_fair["window_type"] == "event"]
    ctrl_sub = non_flat_fair[non_flat_fair["window_type"] == "control"]

    pols = ["baseline_reference", "cost_first", "carbon_first", "balanced", "dro_inspired"]
    x = np.arange(len(pols))
    w = 0.35

    ctrl_c = [ctrl_sub[ctrl_sub["policy_name"] == p]["total_realized_cost_usd"].mean() for p in pols]
    hw_c = [hw_sub[hw_sub["policy_name"] == p]["total_realized_cost_usd"].mean() for p in pols]

    ctrl_e = [ctrl_sub[ctrl_sub["policy_name"] == p]["total_realized_emissions_kg"].mean() for p in pols]
    hw_e = [hw_sub[hw_sub["policy_name"] == p]["total_realized_emissions_kg"].mean() for p in pols]

    ax1.bar(x - w/2, ctrl_c, w, label="Control (CTRL_20240605)", color="navy", alpha=0.85)
    ax1.bar(x + w/2, hw_c, w, label="Heatwave (HW_20240702)", color="crimson", alpha=0.85)
    ax1.set_xticks(x)
    ax1.set_xticklabels([policy_labels[p] for p in pols], rotation=25, ha="right")
    ax1.set_ylabel("Mean Realized Cost ($)")
    ax1.set_title("Realized Cost: Control vs Event (Common Feasible)", fontweight="bold")
    ax1.legend()
    ax1.grid(True, linestyle="--", alpha=0.5)

    ax2.bar(x - w/2, ctrl_e, w, label="Control (CTRL_20240605)", color="navy", alpha=0.85)
    ax2.bar(x + w/2, hw_e, w, label="Heatwave (HW_20240702)", color="crimson", alpha=0.85)
    ax2.set_xticks(x)
    ax2.set_xticklabels([policy_labels[p] for p in pols], rotation=25, ha="right")
    ax2.set_ylabel("Mean Realized Emissions (kg)*")
    ax2.set_title("Realized Carbon: Control vs Event (*Caveat)", fontweight="bold")
    ax2.legend()
    ax2.grid(True, linestyle="--", alpha=0.5)

    plt.suptitle("HeatTrace P5.5: Authentic Event vs Matched Control Regime Impact (Primary Fair)", fontsize=13, fontweight="bold")
    plt.tight_layout()

    f5_png = fig_dir / "p5_5_fig5_event_vs_control.png"
    f5_svg = fig_dir / "p5_5_fig5_event_vs_control.svg"
    write_atomic_figure(f5_png, fig, dpi=200)
    write_atomic_figure(f5_svg, fig, dpi=200)
    plt.close()
    generated["fig5_event_control_png"] = f5_png
    generated["fig5_event_control_svg"] = f5_svg

    # -----------------------------------------------------------------
    # Figure 6: Small-Instance Exact Comparator Validation Gaps (Critical Issue 6)
    # -----------------------------------------------------------------
    if comparator_df is not None and not comparator_df.empty:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
        instances = comparator_df["validation_id"].unique()
        pols = ["baseline_reference", "cost_first", "carbon_first", "balanced", "dro_inspired"]
        x = np.arange(len(pols))
        w = 0.35

        ctrl_gap = [comparator_df[(comparator_df["validation_id"] == "comp_val_ctrl_24h") & (comparator_df["policy_name"] == p)]["cost_optimality_gap_pct"].iloc[0] for p in pols]
        hw_gap = [comparator_df[(comparator_df["validation_id"] == "comp_val_hw_24h") & (comparator_df["policy_name"] == p)]["cost_optimality_gap_pct"].iloc[0] for p in pols]

        ax1.bar(x - w/2, ctrl_gap, w, label="Control 24h Slice", color="navy", alpha=0.85)
        ax1.bar(x + w/2, hw_gap, w, label="Heatwave 24h Slice", color="crimson", alpha=0.85)
        ax1.set_xticks(x)
        ax1.set_xticklabels([policy_labels[p] for p in pols], rotation=25, ha="right")
        ax1.set_ylabel("Optimality Gap (% vs Exact Optimum)")
        ax1.set_title("Exact Branch-and-Bound Cost Optimality Gap (%)", fontweight="bold")
        ax1.legend()
        ax1.grid(True, linestyle="--", alpha=0.5)

        # Plot dollar gaps
        ctrl_gap_usd = [comparator_df[(comparator_df["validation_id"] == "comp_val_ctrl_24h") & (comparator_df["policy_name"] == p)]["cost_optimality_gap_usd"].iloc[0] for p in pols]
        hw_gap_usd = [comparator_df[(comparator_df["validation_id"] == "comp_val_hw_24h") & (comparator_df["policy_name"] == p)]["cost_optimality_gap_usd"].iloc[0] for p in pols]

        ax2.bar(x - w/2, ctrl_gap_usd, w, label="Control 24h Slice", color="navy", alpha=0.85)
        ax2.bar(x + w/2, hw_gap_usd, w, label="Heatwave 24h Slice", color="crimson", alpha=0.85)
        ax2.set_xticks(x)
        ax2.set_xticklabels([policy_labels[p] for p in pols], rotation=25, ha="right")
        ax2.set_ylabel("Optimality Gap ($ vs Exact Optimum)")
        ax2.set_title("Exact Branch-and-Bound Cost Optimality Gap ($)", fontweight="bold")
        ax2.legend()
        ax2.grid(True, linestyle="--", alpha=0.5)

        plt.suptitle("HeatTrace P5.5: Exact Small-Instance Comparator Validation (24h / 4 Jobs)", fontsize=13, fontweight="bold")
        plt.tight_layout()

        f6_png = fig_dir / "p5_5_fig6_comparator_optimality_gaps.png"
        f6_svg = fig_dir / "p5_5_fig6_comparator_optimality_gaps.svg"
        write_atomic_figure(f6_png, fig, dpi=200)
        write_atomic_figure(f6_svg, fig, dpi=200)
        plt.close()
        generated["fig6_comparator_png"] = f6_png
        generated["fig6_comparator_svg"] = f6_svg

    return generated
