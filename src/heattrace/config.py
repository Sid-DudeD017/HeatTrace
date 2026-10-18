"""Load and validate the frozen P0 study configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REQUIRED_CANONICAL_COLUMNS = {
    "timestamp_utc",
    "temperature_c",
    "price_usd_per_mwh",
    "carbon_g_per_kwh",
    "demand_mw",
    "source_quality",
}


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping and fail clearly for malformed top-level values."""
    value = yaml.safe_load(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a YAML mapping in {path}")
    return value


def validate_sources(config: dict[str, Any]) -> None:
    """Validate the source choices frozen by the P0 audit."""
    study = config.get("study", {})
    if study.get("region") != "CAISO":
        raise ValueError("study.region must be CAISO")
    if study.get("timezone") != "UTC":
        raise ValueError("study.timezone must be UTC")
    if config.get("price", {}).get("product") != "day_ahead_hourly_lmp":
        raise ValueError("price.product must be day_ahead_hourly_lmp")
    stations = config.get("weather", {}).get("stations", [])
    station_ids = {station.get("id") for station in stations}
    expected = {"USW00023234", "USW00023232", "USW00023174"}
    if station_ids != expected:
        raise ValueError(f"weather.stations must contain exactly {sorted(expected)}")


def validate_study(config: dict[str, Any]) -> None:
    """Validate the deterministic study window and output contract."""
    if config.get("timestamp", {}).get("timezone") != "UTC":
        raise ValueError("timestamp.timezone must be UTC")
    if config.get("timestamp", {}).get("semantics") != "interval_start":
        raise ValueError("timestamp.semantics must be interval_start")
    if config.get("random_seed") != 20261016:
        raise ValueError("random_seed must remain 20261016")
    if not REQUIRED_CANONICAL_COLUMNS.issuperset(REQUIRED_CANONICAL_COLUMNS):
        raise AssertionError("canonical column contract is invalid")


def validate_repository_config(root: str | Path) -> None:
    """Validate both frozen P0 YAML files from a repository root."""
    root = Path(root)
    sources = load_yaml(root / "configs" / "sources.yaml")
    study = load_yaml(root / "configs" / "study.yaml")
    validate_sources(sources)
    validate_study(study)
    if sources["study"]["years"] != [2022, 2023, 2024, 2025]:
        raise ValueError("study.years must be 2022-2025")
    if sources["study"]["months"] != [6, 7, 8, 9]:
        raise ValueError("study.months must be June-September")
