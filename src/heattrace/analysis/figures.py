"""Figure and source table generators for P5-09 / E1."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


from heattrace.manifests import write_atomic_csv, write_atomic_figure


def generate_p5_figures_and_tables(
    benchmark_df: pd.DataFrame,
    characterization_results: dict[str, pd.DataFrame],
    comparison_metrics_df: pd.DataFrame,
    output_fig_dir: Path,
    output_results_dir: Path,
) -> dict[str, Path]:
    """Generate reproducible figures and machine-readable CSV source tables."""
    output_fig_dir.mkdir(parents=True, exist_ok=True)
    output_results_dir.mkdir(parents=True, exist_ok=True)

    generated_paths: dict[str, Path] = {}

    ctrl_df = benchmark_df[benchmark_df["window_id"] == "CTRL_20240605"].sort_values("timestamp_utc").reset_index(drop=True)
    hw_df = benchmark_df[benchmark_df["window_id"] == "HW_20240702"].sort_values("timestamp_utc").reset_index(drop=True)

    # -------------------------------------------------------------
    # Figure 1: Event vs Control Signal Distributions (Boxplot)
    # -------------------------------------------------------------
    fig, axes = plt.subplots(1, 4, figsize=(16, 4))
    signals = ["temperature_c", "demand_mw", "price_usd_per_mwh", "carbon_g_per_kwh"]
    titles = ["Temperature (°C)", "Demand (MW)", "LMP Price ($/MWh)", "Carbon Intensity (g/kWh)*"]

    for ax, sig, title in zip(axes, signals, titles):
        c_vals = ctrl_df[sig].dropna()
        h_vals = hw_df[sig].dropna()
        ax.boxplot([c_vals, h_vals], tick_labels=["CTRL_20240605", "HW_20240702"])
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.5)

    plt.suptitle("HeatTrace P5-E1: Event vs Control Signal Distributions (N=120h each, *Quality-Limited)", fontsize=13)
    plt.tight_layout()
    fig1_path = output_fig_dir / "p5_fig1_signal_distributions.png"
    write_atomic_figure(fig1_path, fig, dpi=200)
    plt.close()
    generated_paths["fig1"] = fig1_path

    # Source table for Fig 1
    src1_path = output_results_dir / "p5_source_table_fig1_distributions.csv"
    write_atomic_csv(src1_path, characterization_results["window_summary_table"], index=False)
    generated_paths["src1"] = src1_path

    # -------------------------------------------------------------
    # Figure 2: Temperature and System Signals Over Time (120h)
    # -------------------------------------------------------------
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 8), sharex=True)

    hours = range(len(hw_df))
    # Temperature
    ax1.plot(hours, hw_df["temperature_c"], color="crimson", label="HW_20240702 (Event)")
    ax1.plot(hours, ctrl_df["temperature_c"], color="navy", linestyle="--", label="CTRL_20240605 (Control)")
    ax1.axhline(25.60, color="gray", linestyle=":", label="90th Pct Threshold (25.60°C)")
    ax1.set_ylabel("Temp (°C)")
    ax1.set_title("Hourly Temperature & System Signals: 120h Event vs Control", fontweight="bold")
    ax1.legend(loc="upper left")
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Price
    ax2.plot(hours, hw_df["price_usd_per_mwh"], color="crimson", label="HW Price")
    ax2.plot(hours, ctrl_df["price_usd_per_mwh"], color="navy", linestyle="--", label="CTRL Price")
    ax2.set_ylabel("Price ($/MWh)")
    ax2.legend(loc="upper left")
    ax2.grid(True, linestyle="--", alpha=0.5)

    # Demand
    ax3.plot(hours, hw_df["demand_mw"], color="crimson", label="HW Demand")
    ax3.plot(hours, ctrl_df["demand_mw"], color="navy", linestyle="--", label="CTRL Demand")
    ax3.set_ylabel("Demand (MW)")
    ax3.set_xlabel("Window Hour Offset (0 to 119)")
    ax3.legend(loc="upper left")
    ax3.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig2_path = output_fig_dir / "p5_fig2_signals_time_series.png"
    write_atomic_figure(fig2_path, fig, dpi=200)
    plt.close()
    generated_paths["fig2"] = fig2_path

    src2_path = output_results_dir / "p5_source_table_fig2_time_series.csv"
    write_atomic_csv(src2_path, benchmark_df, index=False)
    generated_paths["src2"] = src2_path

    # -------------------------------------------------------------
    # Figure 3: Event-Phase Behavior (Temperature & LMP by Phase)
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    phases = ["onset", "peak", "sustained", "recovery"]
    phase_colors = ["orange", "red", "darkred", "lightcoral"]

    hw_phases = [hw_df[hw_df["phase_label"] == p]["temperature_c"].dropna() for p in phases]
    ax1.boxplot(hw_phases, tick_labels=phases)
    ax1.set_title("HW_20240702 Temperature by Phase (°C)", fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.5)

    hw_prices = [hw_df[hw_df["phase_label"] == p]["price_usd_per_mwh"].dropna() for p in phases]
    ax2.boxplot(hw_prices, tick_labels=phases)
    ax2.set_title("HW_20240702 LMP Price by Phase ($/MWh)", fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.5)

    plt.suptitle("HeatTrace P5-E1: Event-Phase Breakdown (Onset, Peak, Sustained, Recovery)", fontsize=12)
    plt.tight_layout()
    fig3_path = output_fig_dir / "p5_fig3_phase_behavior.png"
    write_atomic_figure(fig3_path, fig, dpi=200)
    plt.close()
    generated_paths["fig3"] = fig3_path

    src3_path = output_results_dir / "p5_source_table_fig3_phase_behavior.csv"
    write_atomic_csv(src3_path, characterization_results["phase_summary_table"], index=False)
    generated_paths["src3"] = src3_path

    # -------------------------------------------------------------
    # Figure 4: Lagged Association Profiles (-24h to +24h)
    # -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    lag_df = characterization_results["lag_analysis_table"]
    hw_lag = lag_df[(lag_df["window_id"] == "HW_20240702") & (lag_df["signal_x"] == "temperature_c") & (lag_df["signal_y"] == "price_usd_per_mwh")].sort_values("lag_hours")
    ctrl_lag = lag_df[(lag_df["window_id"] == "CTRL_20240605") & (lag_df["signal_x"] == "temperature_c") & (lag_df["signal_y"] == "price_usd_per_mwh")].sort_values("lag_hours")

    ax.plot(hw_lag["lag_hours"], hw_lag["pearson_r"], marker="o", color="crimson", label="HW_20240702 Pearson r (Temp leads Price for lag > 0)")
    ax.plot(ctrl_lag["lag_hours"], ctrl_lag["pearson_r"], marker="s", color="navy", linestyle="--", label="CTRL_20240605 Pearson r")
    ax.axvline(0, color="gray", linestyle=":")
    ax.axhline(0, color="gray", linestyle="-", alpha=0.3)
    ax.set_xlabel("Lag (Hours): k > 0 means Temperature leads Price by k hours")
    ax.set_ylabel("Pearson Correlation Coefficient")
    ax.set_title("Lagged Cross-Correlation: Temperature vs Price (Lags -24h to +24h)", fontweight="bold")
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig4_path = output_fig_dir / "p5_fig4_lag_relationships.png"
    write_atomic_figure(fig4_path, fig, dpi=200)
    plt.close()
    generated_paths["fig4"] = fig4_path

    src4_path = output_results_dir / "p5_source_table_fig4_lag_relationships.csv"
    write_atomic_csv(src4_path, lag_df, index=False)
    generated_paths["src4"] = src4_path

    # -------------------------------------------------------------
    # Figure 5: Policy Performance Comparison Across Windows
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    policies = ["cost_first", "carbon_first", "balanced", "dro_inspired"]

    hw_m = comparison_metrics_df[comparison_metrics_df["window_id"] == "HW_20240702"].set_index("policy_name")
    ctrl_m = comparison_metrics_df[comparison_metrics_df["window_id"] == "CTRL_20240605"].set_index("policy_name")

    x = range(len(policies))
    width = 0.35

    ax1.bar([p - width/2 for p in x], [ctrl_m.loc[p, "total_realized_cost_usd"] for p in policies], width, label="CTRL_20240605", color="navy")
    ax1.bar([p + width/2 for p in x], [hw_m.loc[p, "total_realized_cost_usd"] for p in policies], width, label="HW_20240702", color="crimson")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(policies)
    ax1.set_ylabel("Total Realized Cost ($)")
    ax1.set_title("Realized Cost by Policy & Window", fontweight="bold")
    ax1.legend()
    ax1.grid(True, linestyle="--", alpha=0.5)

    ax2.bar([p - width/2 for p in x], [ctrl_m.loc[p, "total_realized_emissions_kg"] for p in policies], width, label="CTRL_20240605", color="navy")
    ax2.bar([p + width/2 for p in x], [hw_m.loc[p, "total_realized_emissions_kg"] for p in policies], width, label="HW_20240702", color="crimson")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(policies)
    ax2.set_ylabel("Realized Emissions (kg)*")
    ax2.set_title("Realized Emissions (*Quality-Limited)", fontweight="bold")
    ax2.legend()
    ax2.grid(True, linestyle="--", alpha=0.5)

    plt.suptitle("HeatTrace P5-E2: Policy Performance Across Event & Control Windows", fontsize=12)
    plt.tight_layout()
    fig5_path = output_fig_dir / "p5_fig5_policy_performance.png"
    write_atomic_figure(fig5_path, fig, dpi=200)
    plt.close()
    generated_paths["fig5"] = fig5_path

    src5_path = output_results_dir / "p5_source_table_fig5_policy_performance.csv"
    write_atomic_csv(src5_path, comparison_metrics_df, index=False)
    generated_paths["src5"] = src5_path

    return generated_paths
