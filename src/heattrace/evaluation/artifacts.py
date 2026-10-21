"""Atomic artifact writing and publication for P4 benchmark outputs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any
import pandas as pd

from heattrace.ingest.provenance import sha256_file
from heattrace.manifests import write_atomic_json


def publish_p4_run_artifacts_atomically(
    target_run_dir: Path,
    staged_run_dir: Path,
) -> None:
    """Atomically publish artifacts from staged directory to target run directory.

    If anything fails, rolls back cleanly and leaves no partial state.
    """
    target_run_dir = target_run_dir.resolve()
    staged_run_dir = staged_run_dir.resolve()

    backup_dir = target_run_dir.with_name(f"{target_run_dir.name}_backup_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")

    had_target = target_run_dir.exists()
    if had_target:
        # Move target to backup
        target_run_dir.rename(backup_dir)

    try:
        # Move staged to target
        staged_run_dir.rename(target_run_dir)
        # If success, remove backup
        if had_target and backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        # Rollback
        if target_run_dir.exists():
            shutil.rmtree(target_run_dir)
        if had_target and backup_dir.exists():
            backup_dir.rename(target_run_dir)
        raise


def build_p4_run_manifest(
    run_dir: Path,
    *,
    manifest_version: str = "1.0",
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Index all generated files in the run directory with SHA-256 and size."""
    run_dir = run_dir.resolve()
    if generated_at_utc is None:
        generated_at_utc = datetime.now(timezone.utc).isoformat()

    output_files: dict[str, Any] = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name != "run_manifest.json" and not p.name.endswith(".tmp"):
            rel_p = p.relative_to(run_dir).as_posix()
            output_files[rel_p] = {
                "path": rel_p,
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

    return {
        "manifest_version": manifest_version,
        "run_directory": run_dir.as_posix(),
        "generated_at_utc": generated_at_utc,
        "total_files": len(output_files),
        "output_files": output_files,
    }
