# HeatTrace

Reproducible research prototype for evaluating workload scheduling under heatwave-related electricity price and carbon conditions.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

All primary timestamps use UTC and identify interval start. Raw downloads and secrets are intentionally excluded from Git.

## Repository layout

- `src/heattrace/` — ingestion, processing, forecasting, scheduling, and evaluation code
- `configs/` — frozen source and study configuration
- `data/` — local data only; raw/interim/processed files are ignored
- `docs/` — contracts, source audit, and methods notes
- `tests/` — unit tests and small fixtures
- `reports/` — generated QC and audit reports
- `runs/` — generated benchmark outputs
