"""Analysis and professor-ready figure generators for P5.5.

Produces:
1. Summary policy-comparison table (CSV).
2. Cost-Carbon Pareto plot (PNG + SVG).
3. Forecast-error sensitivity plot (PNG + SVG).
4. Workload/capacity-pressure plot (PNG + SVG).
5. Feasibility or SLA heatmap (PNG + SVG).
6. Event-versus-control comparison figure (PNG + SVG).

All plots strictly distinguish:
- Authentic evidence (P5 flat baseline)
- Controlled simulation (noisy oracle)
- Controlled hindsight upper bound (oracle)
- Quality-limited carbon caveat
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from heattrace.manifests import write_atomic_csv, write_atomic_figure


def generate_p5_5_summary_tables(
    results_df: pd.DataFrame,
    output_dir: Path | str = "data/results",
) -> dict[str, Path]:
    """Generate summary policy-comparison tables and paired difference tables."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Path] = {}

    # 1. Summary comparison table grouped by policy and forecast scenario
    summary_cols = [
        "total_realized_cost_usd",
        "total_realized_emissions_kg",
        "cvar_cost_90",
        "sla_completion_rate",
        "is_feasible",
    ]
    summary_table = results_df.groupby(
        ["window_type", "policy_name", "forecast_scenario_id", "evidence_class"]
    )[summary_cols].agg(["mean", "std", "count"]).reset_index()

    # Flatten multi-level columns
    summary_table.columns = [
        "_".join(c).strip("_") if isinstance(c, tuple) else c
        for c in summary_table.columns
    ]

    p5_5_summary_path = out_dir / "p5_5_policy_comparison_summary.csv"
    write_atomic_csv(p5_5_summary_path, summary_table, index=False)
    generated["summary_table"] = p5_5_summary_path

    # 2. Paired differences against baseline_reference
    scens = results_df["scenario_id"].unique()
    paired_rows = []
    for scen in scens:
        sub = results_df[results_df["scenario_id"] == scen].set_index("policy_name")
        if "baseline_reference" not in sub.index:
            continue
        base_cost = sub.loc["baseline_reference", "total_realized_cost_usd"]
        base_emiss = sub.loc["baseline_reference", "total_realized_emissions_kg"]
        for pol in sub.index:
            cost_diff = sub.loc[pol, "total_realized_cost_usd"] - base_cost
            cost_pct = (cost_diff / base_cost) * 100.0 if base_cost != 0 else 0.0
            emiss_diff = sub.loc[pol, "total_realized_emissions_kg"] - base_emiss
            emiss_pct = (emiss_diff / base_emiss) * 100.0 if base_emiss != 0 else 0.0
            paired_rows.append({
                "scenario_id": scen,
                "window_id": sub.loc[pol, "window_id"],
                "window_type": sub.loc[pol, "window_type"],
                "policy_name": pol,
                "forecast_scenario_id": sub.loc[pol, "forecast_scenario_id"],
                "forecast_type": sub.loc[pol, "forecast_type"],
                "evidence_class": sub.loc[pol, "evidence_class"],
                "noise_sigma": sub.loc[pol, "noise_sigma"],
                "workload_multiplier": sub.loc[pol, "workload_multiplier"],
                "resource_scenario_id": sub.loc[pol, "resource_scenario_id"],
                "deadline_scenario_id": sub.loc[pol, "deadline_scenario_id"],
                "is_feasible": sub.loc[pol, "is_feasible"],
                "cost_diff_usd": round(cost_diff, 4),
                "cost_pct_change": round(cost_pct, 4),
                "emiss_diff_kg": round(emiss_diff, 4),
                "emiss_pct_change": round(emiss_pct, 4),
            })

    paired_df = pd.DataFrame(paired_rows)
    paired_path = out_dir / "p5_5_policy_paired_differences.csv"
    write_atomic_csv(paired_path, paired_df, index=False)
    generated["paired_differences"] = paired_path

    return generated


def generate_p5_5_figures(
    results_df: pd.DataFrame,
    output_fig_dir: Path | str = "data/figures",
    output_results_dir: Path | str = "data/results",
) -> dict[str, Path]:
    """Generate the 5 required professor-ready publication figures in PNG and SVG formats."""
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

    # -----------------------------------------------------------------
    # Figure 1: Cost-Carbon Pareto Plot (Trade-Off Under Forecast Scenarios)
    # -----------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, wtype, wtitle in zip(axes, ["control", "event"], ["Control (CTRL_20240605)", "Event (HW_20240702)"]):
        sub_w = results_df[results_df["window_type"] == wtype]
        for pol, color in policy_colors.items():
            pol_df = sub_w[sub_w["policy_name"] == pol]
            # Plot oracle point (star)
            orc = pol_df[pol_df["forecast_type"] == "oracle"]
            if not orc.empty:
                ax.scatter(
                    orc["total_realized_cost_usd"].mean(),
                    orc["total_realized_emissions_kg"].mean(),
                    color=color, marker="*", s=220, edgecolors="black", linewidth=1.2,
                    label=f"{policy_labels[pol]} (Oracle Bound)" if wtype == "control" else None,
                    zorder=5,
                )
            # Plot noisy oracle points (circles with size indicating noise sigma)
            for sigma, marker, alpha in [(0.10, "o", 0.9), (0.25, "^", 0.7), (0.50, "s", 0.5)]:
                noisy = pol_df[(pol_df["forecast_type"] == "noisy_oracle") & (pol_df["noise_sigma"] == sigma)]
                if not noisy.empty:
                    ax.scatter(
                        noisy["total_realized_cost_usd"].mean(),
                        noisy["total_realized_emissions_kg"].mean(),
                        color=color, marker=marker, s=80, alpha=alpha, edgecolors="black", linewidth=0.5,
                    )
            # Plot flat baseline point (X)
            flat = pol_df[pol_df["forecast_type"] == "flat"]
            if not flat.empty:
                ax.scatter(
                    flat["total_realized_cost_usd"].mean(),
                    flat["total_realized_emissions_kg"].mean(),
                    color=color, marker="X", s=130, edgecolors="black", linewidth=1.0,
                )

        ax.set_title(f"{wtitle}\nMean Realized Cost vs Emissions Across Scenarios", fontsize=11, fontweight="bold")
        ax.set_xlabel("Mean Total Realized Cost ($)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.5)

    axes[0].set_ylabel("Mean Realized Carbon Emissions (kg)*", fontsize=10)
    fig.text(0.5, 0.02, "*Caveat: Carbon emissions are quality-limited sensitivity evidence only. Star=Hindsight Oracle, Circles/Triangles/Squares=Noisy Oracle (σ=0.10, 0.25, 0.50), X=Flat Baseline.", ha="center", fontsize=9, style="italic")
    axes[0].legend(loc="upper left", fontsize=8)
    plt.suptitle("HeatTrace P5.5: Cost–Carbon Pareto Frontier Across Policies & Forecast Regimes", fontsize=13, fontweight="bold")
    plt.tight_layout(rect=[0, 0.05, 1, 0.95])

    f1_png = fig_dir / "p5_5_fig1_cost_carbon_pareto.png"
    f1_svg = fig_dir / "p5_5_fig1_cost_carbon_pareto.svg"
    write_atomic_figure(f1_png, fig, dpi=200)
    write_atomic_figure(f1_svg, fig, dpi=200)
    plt.close()
    generated["fig1_pareto_png"] = f1_png
    generated["fig1_pareto_svg"] = f1_svg

    # -----------------------------------------------------------------
    # Figure 2: Forecast-Error Sensitivity Plot
    # -----------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fc_order = ["oracle_forecast", "noisy_oracle_low", "noisy_oracle_medium", "noisy_oracle_high", "flat_forecast"]
    fc_xlabels = ["Oracle\n(σ=0)", "Noisy Low\n(σ=0.10)", "Noisy Med\n(σ=0.25)", "Noisy High\n(σ=0.50)", "Flat Baseline\n(Authentic)"]
    x = np.arange(len(fc_order))

    for pol, color in policy_colors.items():
        sub_p = results_df[results_df["policy_name"] == pol]
        # Event window
        hw_costs = [sub_p[(sub_p["window_type"] == "event") & (sub_p["forecast_scenario_id"] == fid)]["total_realized_cost_usd"].mean() for fid in fc_order]
        ctrl_costs = [sub_p[(sub_p["window_type"] == "control") & (sub_p["forecast_scenario_id"] == fid)]["total_realized_cost_usd"].mean() for fid in fc_order]

        ax1.plot(x, hw_costs, marker="o", linewidth=1.8, color=color, label=policy_labels[pol])
        ax2.plot(x, ctrl_costs, marker="s", linewidth=1.8, color=color, label=policy_labels[pol])

    ax1.set_title("Heatwave Event (HW_20240702): Cost vs Forecast Error", fontweight="bold", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(fc_xlabels)
    ax1.set_ylabel("Mean Total Realized Cost ($)", fontsize=10)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(loc="upper left", fontsize=8)

    ax2.set_title("Matched Control (CTRL_20240605): Cost vs Forecast Error", fontweight="bold", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(fc_xlabels)
    ax2.set_ylabel("Mean Total Realized Cost ($)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(loc="upper left", fontsize=8)

    plt.suptitle("HeatTrace P5.5: Policy Sensitivity to Forecast Error Degradation", fontsize=13, fontweight="bold")
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
        sub_wm = results_df[(results_df["workload_multiplier"] == wm) & (results_df["window_type"] == "event") & (results_df["forecast_type"] != "flat")]
        x_r = np.arange(len(res_order))
        for pol, color in policy_colors.items():
            costs = [sub_wm[(sub_wm["policy_name"] == pol) & (sub_wm["resource_scenario_id"] == rid)]["total_realized_cost_usd"].mean() for rid in res_order]
            ax.plot(x_r, costs, marker="o", linewidth=2.0, color=color, label=policy_labels[pol] if idx == 0 else None)

        ax.set_title(f"Workload {int(wm)}× ({int(30*wm)} jobs)", fontweight="bold", fontsize=11)
        ax.set_xticks(x_r)
        ax.set_xticklabels(res_xlabels, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.5)

    axes[0].set_ylabel("Mean Total Realized Cost ($) [HW Event]", fontsize=10)
    axes[0].legend(loc="upper left", fontsize=8)
    plt.suptitle("HeatTrace P5.5: Policy Differentiation Under Increasing Workload and Resource Pressure", fontsize=13, fontweight="bold")
    plt.tight_layout()

    f3_png = fig_dir / "p5_5_fig3_workload_capacity_pressure.png"
    f3_svg = fig_dir / "p5_5_fig3_workload_capacity_pressure.svg"
    write_atomic_figure(f3_png, fig, dpi=200)
    write_atomic_figure(f3_svg, fig, dpi=200)
    plt.close()
    generated["fig3_pressure_png"] = f3_png
    generated["fig3_pressure_svg"] = f3_svg

    # -----------------------------------------------------------------
    # Figure 4: Feasibility and SLA Heatmap
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
    ax1.set_title("Schedule Feasibility Rate (All Scenarios)", fontweight="bold")
    ax1.set_xticks(range(len(feas_matrix.columns)))
    ax1.set_xticklabels([policy_labels[c] for c in feas_matrix.columns], rotation=30, ha="right")
    ax1.set_yticks(range(len(feas_matrix.index)))
    ax1.set_yticklabels([f"WL {idx[0]}× | {idx[1]}" for idx in feas_matrix.index])
    for r in range(feas_matrix.shape[0]):
        for c in range(feas_matrix.shape[1]):
            val = feas_matrix.iloc[r, c]
            ax1.text(c, r, f"{val:.0%}", ha="center", va="center", color="black" if val > 0.5 else "white", fontweight="bold")

    im2 = ax2.imshow(sla_matrix.values, cmap="YlGnBu", aspect="auto", vmin=0.8, vmax=1.0)
    ax2.set_title("SLA Job Completion Rate", fontweight="bold")
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
    # Figure 5: Event vs Control Paired Comparison
    # -----------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    non_flat = results_df[results_df["forecast_type"] != "flat"]
    hw_sub = non_flat[non_flat["window_type"] == "event"]
    ctrl_sub = non_flat[non_flat["window_type"] == "control"]

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
    ax1.set_title("Realized Cost: Control vs Event", fontweight="bold")
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

    plt.suptitle("HeatTrace P5.5: Authentic Event vs Matched Control Regime Impact", fontsize=13, fontweight="bold")
    plt.tight_layout()

    f5_png = fig_dir / "p5_5_fig5_event_vs_control.png"
    f5_svg = fig_dir / "p5_5_fig5_event_vs_control.svg"
    write_atomic_figure(f5_png, fig, dpi=200)
    write_atomic_figure(f5_svg, fig, dpi=200)
    plt.close()
    generated["fig5_event_control_png"] = f5_png
    generated["fig5_event_control_svg"] = f5_svg

    return generated
