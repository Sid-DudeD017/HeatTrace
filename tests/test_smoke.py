from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_source_config_loads():
    config = yaml.safe_load((ROOT / "configs/sources.yaml").read_text())
    assert config["study"]["region"] == "CAISO"
    assert config["study"]["timezone"] == "UTC"
    assert config["price"]["units"] == "USD_per_MWh"


def test_repository_contract_files_exist():
    assert (ROOT / "docs/contracts.md").exists()
    assert (ROOT / "docs/source_audit.md").exists()
