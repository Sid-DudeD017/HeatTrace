from pathlib import Path

import yaml

from heattrace.config import validate_repository_config
from heattrace.ingest.manifest import build_record

ROOT = Path(__file__).parents[1]


def test_source_config_loads():
    config = yaml.safe_load((ROOT / "configs/sources.yaml").read_text())
    assert config["study"]["region"] == "CAISO"
    assert config["study"]["timezone"] == "UTC"
    assert config["price"]["units"] == "USD_per_MWh"


def test_repository_contract_files_exist():
    assert (ROOT / "docs/contracts.md").exists()
    assert (ROOT / "docs/source_audit.md").exists()


def test_frozen_p0_configuration_is_valid():
    validate_repository_config(ROOT)


def test_manifest_record_contains_checksum(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("timestamp,value\n2026-01-01T00:00:00Z,1\n")
    record = build_record(
        source,
        provider="test",
        dataset="sample",
    )
    assert len(record["sha256"]) == 64
    assert record["size_bytes"] == source.stat().st_size
