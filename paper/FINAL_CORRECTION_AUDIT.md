# HeatTrace final-correction audit

Audit date: 2026-11-20 (Asia/Kolkata). This audit was completed before the final correction pass. It is read-only with respect to scientific code, data, frozen configurations, and archived results.

## Baseline and preservation

- Git branch: `main`.
- Configured remote: `https://github.com/Sid-DudeD017/HeatTrace.git`.
- Baseline PDF: 14 pages (12 manuscript pages followed by 2 reference pages).
- The working tree already contained untracked research and manuscript artifacts. They were preserved.
- Recoverable backup: `paper/backups/pre_final_correction_2026-11-20/`.
- Protected author, affiliation, email, funding, and conflict-of-interest placeholders must remain unchanged.

## Confirmed issues and required corrections

### Public access and availability

Anonymous HTTP checks returned 200 for the repository page, raw `README.md`, the public repository API, and the recursive tree API. The API reports `visibility: public`, `private: false`, and default branch `main`. The old HTTP 404 warning and author-verification placeholder are therefore obsolete.

The public tree contains source code, configurations, tests, documentation, the original benchmark bundle, multi-station event/episode/scenario/matrix artifacts, manifests, workload traces, results, tables, and audit material. It does not contain `paper/`, raw provider inputs, processed provider inputs, or the locally generated full `data/v2/events/p12_b2_hourly_event_signals.csv`. The public tree does contain the original hourly Parquet bundle and an extension hourly preview. Availability wording must distinguish these public artifacts from local generated files and must not claim a clean-checkout source-to-result reconstruction.

The public README explains the project, dependencies, general quick start, and original workflow. Detailed extension phases are documented in repository documentation, but the README is not a complete source-to-result recipe for the multi-station extension.

### 2022 joint-evaluation exclusion

The event catalogue contains nine 2022 station events. All nine pass `weather_eligibility_status`; all remain in the 25-event catalogue; all are marked `EXCLUDED` only for joint evaluation. The EIA coverage table records one missing CISO interval at `2022-06-13 17:00 UTC` (2,927 valid of 2,928 expected warm-season intervals). That timestamp is outside every affected event's full onset-to-recovery window.

The implementation applies a year-level 2022 joint-source exclusion before scenario selection while retaining weather-only eligibility separately. The manuscript must therefore describe this as a conservative pipeline/source-selection limitation, not meteorological invalidity or proof of missing data inside the event windows. An event-window coverage gate is a future alternative; no event is restored in this correction.

### Reconstruction instructions

- `scripts/p12_b2_acquire_sources.py` exists; `--repo-root .` is accepted from the repository root. The command validates/processes provider inputs and can require local source files, network access, credentials, and historically available endpoints.
- `scripts/p12_b2_detect_events.py` exists and its defaults resolve the repository's expected event, manifest, and NOAA directories. Its syntax was checked with `--help`; the scientific workflow was not rerun.
- `run_phase4_pipeline(repo_root=".")` exists in `src/heattrace/process/p12_b2_windows.py`, but it is a Python function, not a command-line entry point. The long inline `python -c` command in the manuscript is nonportable and should be omitted in favor of an accurate prose description.
- Python syntax checks passed for both scripts and the phase-four module. The declared environment requires Python 3.11 or later and core dependencies including pandas, PyArrow, and PyYAML.

### Schema table

The existing table conflates two hourly artifact schemas, labels a composite key as though it were a simple identifier, and describes matrix/configuration fields as run-output fields. It must distinguish:

- the public original hourly bundle keyed by `(triplet_id, window_type, timestamp_utc)` and using `demand_mw`;
- the locally generated extension hourly export keyed by `(event_id, timestamp_utc)` and using `demand_mwh` plus phase/quality fields;
- unique event, episode, scenario, and run identifiers;
- execution outcome fields such as `execution_status`, `failure_category`, `completed_processing_slots`, and `total_facility_energy_kwh`.

All stated key and foreign-key relationships were checked. Full details are recorded in `DATASET_SCHEMA_VERIFICATION.md`.

### Results prose and visuals

The H1--H5 numeric evidence is already complete in the result table and figure. The prose repeats counts and should be shortened to scientific interpretation, null findings, and caveats. Figure 1 is structurally accurate and readable but should give the three evidence layers stronger visual distinction without introducing a new stage.

### References

Publisher/proceedings metadata were checked for all scholarly references, with focused verification of Ruparel, DCcluster-Opt, Moore et al., WeatherBench 2, and ExtremeWeather. Official product/documentation pages were checked for NOAA GHCNh, CAISO prices, and EIA-930. Dataset titles should follow the exact official page/product titles. Official URLs and publisher details should be added where verified; unsupported metadata should not be invented.

## Scientific quantities preserved

The audit found no stronger artifact contradicting the protected findings: four original SFO events; three confirmatory triplets; 756 successful original cells; H1 changes of `-0.5x, -0.5x, 0x`; H3 separations `24/36, 24/36, 0/36`; no strict reversal; 44-column same-environment agreement; 54/54 archive payload verification; 25 extension events; 15 episodes; 6,480 extension cells; 5,448 successes; 1,032 failures; 3,960 protocol-affected run IDs; severe equal-service attrition; and ordinary-window overlap.
