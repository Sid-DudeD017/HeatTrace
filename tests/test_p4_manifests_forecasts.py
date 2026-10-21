"""Tests for P4 experiment manifests, historical forecasts, and schemas."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd
from datetime import datetime, timezone

from heattrace.config import load_yaml
from heattrace.forecast.historical import (
    HistoricalPersistenceForecastProvider,
    build_historical_forecast_dataset,
)
from heattrace.forecast.schema import FORECAST_COLUMNS, validate_forecast_dataframe
from heattrace.manifests import (
    build_p4_experiment_manifest,
    build_p4_forecast_manifest,
    validate_p4_experiment_manifest,
    write_atomic_json,
)


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


def test_p4_config_loads_and_has_required_keys(repo_root):
    cfg_path = repo_root / "configs/p4.yaml"
    assert cfg_path.exists()
    cfg = load_yaml(cfg_path)
    assert cfg["version"] == "1.0"
    assert cfg["random_seed"] == 20261016
    assert cfg["benchmark"]["event_window_id"] == "HW_20240702"
    assert cfg["benchmark"]["control_window_id"] == "CTRL_20240605"
    assert cfg["benchmark"]["horizon_hours"] == 120
    assert cfg["constraints"]["max_cluster_power_kw"] == 500.0
    assert cfg["constraints"]["max_concurrent_jobs"] == 16
    assert cfg["risk"]["cvar_alpha"] == 0.90


def test_p4_experiment_manifest_build_and_validation(repo_root):
    manifest = build_p4_experiment_manifest(repo_root=repo_root)
    assert manifest["manifest_version"] == "1.0"
    assert manifest["random_seed"] == 20261016
    assert manifest["forecast_actual_separation_declaration"]["is_separate"] is True
    assert manifest["carbon_data_quality_declaration"]["interpretation_label"] == "quality_limited_sensitivity_only"

    # Strict validation passes
    errs = validate_p4_experiment_manifest(manifest, repo_root=repo_root)
    assert not errs, f"Validation errors: {errs}"


def test_p4_manifest_tamper_and_path_escape(repo_root):
    manifest = build_p4_experiment_manifest(repo_root=repo_root)

    # Tamper with a hash
    bad_manifest = dict(manifest)
    bad_manifest["input_files"] = dict(manifest["input_files"])
    bad_manifest["input_files"]["p4_config"] = dict(manifest["input_files"]["p4_config"])
    bad_manifest["input_files"]["p4_config"]["sha256"] = "a" * 64

    errs = validate_p4_experiment_manifest(bad_manifest, repo_root=repo_root)
    assert any("hash mismatch" in e for e in errs)

    # Path escape
    esc_manifest = dict(manifest)
    esc_manifest["expected_output_paths"] = dict(manifest["expected_output_paths"])
    esc_manifest["expected_output_paths"]["run_manifest"] = "../../run_manifest.json"
    errs_esc = validate_p4_experiment_manifest(esc_manifest, repo_root=repo_root)
    assert any("path escape" in e for e in errs_esc)


def test_historical_persistence_forecast_no_leakage(repo_root):
    provider = HistoricalPersistenceForecastProvider(
        fallback_price_usd_per_mwh=45.0,
        fallback_carbon_g_per_kwh=220.0,
    )

    origin = datetime(2024, 7, 1, 7, 0, tzinfo=timezone.utc)

    # Create synthetic history with past, origin, and future rows
    history_rows = [
        {"timestamp_utc": origin - pd.Timedelta(hours=2), "price_usd_per_mwh": 30.0, "carbon_g_per_kwh": 180.0},
        {"timestamp_utc": origin - pd.Timedelta(hours=1), "price_usd_per_mwh": 35.0, "carbon_g_per_kwh": 190.0},
        {"timestamp_utc": origin, "price_usd_per_mwh": 999.0, "carbon_g_per_kwh": 999.0},
        {"timestamp_utc": origin + pd.Timedelta(hours=1), "price_usd_per_mwh": 1500.0, "carbon_g_per_kwh": 800.0},
    ]
    history_df = pd.DataFrame(history_rows)

    res = provider.forecast(origin, 24, history_df=history_df)
    points = res.points
    assert len(points) == 24
    # All points must use the pre-origin persistence value 35.0 and 190.0, NOT 999.0 or 1500.0
    for p in points:
        assert p.predicted_price_usd_per_mwh == 35.0
        assert p.predicted_carbon_g_per_kwh == 190.0


def test_forecast_mutating_future_actuals_does_not_change_forecast(repo_root):
    bench_p = repo_root / "data/benchmarks/benchmark_2024_event_control_v0.parquet"
    bench_df = pd.read_parquet(bench_p)

    fc_df_1 = build_historical_forecast_dataset(bench_df)

    # Mutate future actuals in bench_df
    mutated_bench = bench_df.copy()
    mutated_bench["price_usd_per_mwh"] = mutated_bench["price_usd_per_mwh"] * 10.0 + 100.0
    mutated_bench["carbon_g_per_kwh"] = mutated_bench["carbon_g_per_kwh"] * 5.0 + 50.0

    fc_df_2 = build_historical_forecast_dataset(mutated_bench)

    # Because pre-origin causal filtering strips future rows for both windows,
    # mutating future rows does not change the control forecasts at all!
    ctrl_1 = fc_df_1[fc_df_1["window_id"] == "CTRL_20240605"]
    ctrl_2 = fc_df_2[fc_df_2["window_id"] == "CTRL_20240605"]
    pd.testing.assert_frame_equal(ctrl_1.reset_index(drop=True), ctrl_2.reset_index(drop=True))


def test_forecast_fallback_on_empty_history():
    provider = HistoricalPersistenceForecastProvider(
        fallback_price_usd_per_mwh=45.0,
        fallback_carbon_g_per_kwh=220.0,
    )
    origin = datetime(2024, 6, 5, 7, 0, tzinfo=timezone.utc)
    res = provider.forecast(origin, 12, history_df=pd.DataFrame())
    for p in res.points:
        assert p.predicted_price_usd_per_mwh == 45.0
        assert p.predicted_carbon_g_per_kwh == 220.0

    f_df = getattr(res, "_forecast_df")
    assert (f_df["used_fallback"] == True).all()
    assert (f_df["forecast_method"] == "fallback_frozen_default").all()


def test_atomic_write_json(tmp_path):
    target = tmp_path / "test_manifest.json"
    data = {"hello": "world", "status": "ok"}
    write_atomic_json(target, data)
    assert target.exists()
    with target.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data
