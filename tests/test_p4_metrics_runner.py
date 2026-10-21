"""Tests for P4 metrics calculation, common runner, and atomic publication."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from heattrace.evaluation.artifacts import (
    build_p4_run_manifest,
    publish_p4_run_artifacts_atomically,
)
from heattrace.evaluation.metrics import (
    compute_cvar,
    compute_schedule_metrics,
)
from heattrace.evaluation.runner import run_p4_benchmark
from heattrace.policy.interfaces import (
    ScheduleResult,
    ScheduledJobAllocation,
)
from heattrace.process.p4_audit import run_g4_audit


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


def test_cvar_hand_calculation():
    # Test hand-calculated CVaR
    # Losses = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    # alpha = 0.90
    # 90th percentile is 91.0 (with linear interpolation) or 90
    # Values >= 90 are [90, 100] -> mean = 95.0
    losses = np.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], dtype=float)
    cvar_val = compute_cvar(losses, alpha=0.90)
    # The tail values >= quantile
    q = np.quantile(losses, 0.90)
    expected_cvar = np.mean(losses[losses >= q])
    assert cvar_val == pytest.approx(expected_cvar, abs=1e-4)


def test_atomic_publication_and_rollback(tmp_path):
    target_dir = tmp_path / "runs/p4_v0"
    target_dir.mkdir(parents=True)
    (target_dir / "old_file.txt").write_text("old_content")

    stage_dir = tmp_path / "staging_dir"
    stage_dir.mkdir(parents=True)
    (stage_dir / "new_file.txt").write_text("new_content")

    publish_p4_run_artifacts_atomically(target_dir, stage_dir)

    assert target_dir.exists()
    assert (target_dir / "new_file.txt").exists()
    assert not (target_dir / "old_file.txt").exists()
    assert not stage_dir.exists()


def test_end_to_end_p4_runner_and_g4_audit(repo_root, tmp_path):
    # Run the benchmark into a test output dir
    test_run_dir = tmp_path / "test_p4_run"
    test_data_dir = tmp_path / "data"
    test_manifest_dir = test_data_dir / "manifests"
    test_manifest_dir.mkdir(parents=True)

    # Copy required inputs to tmp data
    import shutil
    shutil.copytree(repo_root / "data/benchmarks", test_data_dir / "benchmarks")
    shutil.copytree(repo_root / "data/workloads", test_data_dir / "workloads")
    shutil.copytree(repo_root / "data/events", test_data_dir / "events")
    shutil.copytree(repo_root / "data/processed", test_data_dir / "processed")
    shutil.copy(repo_root / "data/manifests/benchmark_manifest.json", test_manifest_dir)
    shutil.copy(repo_root / "data/manifests/p3_comprehensive_audit.json", test_manifest_dir)

    # Run benchmark
    res = run_p4_benchmark(
        repo_root=repo_root,
        output_run_dir=test_run_dir,
    )
    assert res["status"] == "success"
    assert res["metrics_count"] == 8

    # Audit
    audit_res = run_g4_audit(
        repo_root=repo_root,
        runs_dir=test_run_dir,
    )
    assert audit_res["status"] == "VERIFIED_PASS"
    assert audit_res["failure_count"] == 0
