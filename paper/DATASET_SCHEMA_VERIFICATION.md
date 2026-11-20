# HeatTrace dataset-schema verification

Verification date: 2026-11-20. Checks were read-only and used pandas/PyArrow against the existing artifacts. “Unique” below means the relevant observed key had zero duplicates and zero null key values; it is not a universal guarantee for future releases.

## Artifact-level audit

| Artifact | Grain and observed size | Key check | Columns and nullability checked | Links, flags, and deviations |
|---|---|---|---|---|
| `data/benchmarks/p6_event_control_pairs.parquet` | One original hourly row per triplet/window/timestamp; 1,440 rows, 9 columns | Composite `(triplet_id, window_type, timestamp_utc)` is unique; no null key values | `timestamp_utc`, `triplet_id`, `window_type`, `window_id`, `phase_label`, `temperature_c`, `price_usd_per_mwh`, `carbon_g_per_kwh`, `demand_mw`; no null values observed | Public original bundle. Uses `demand_mw`, not the extension's `demand_mwh`; `window_id` alone is descriptive, not the checked hourly key. |
| `data/v2/events/p12_b2_hourly_event_signals.csv` | One extension event-hour; 4,320 rows, 37 columns | Composite `(event_id, timestamp_utc)` is unique; no null key values | Includes `station_code`, `regional_episode_id`, `phase`, temperature fields, `price_usd_per_mwh`, `carbon_g_per_kwh`, `demand_mwh`, `data_issue_flag`, `has_data_issue`, and source-specific missing flags. Two `temperature_c` values are null; 2,208 grid/carbon values are null and explicitly flagged | `event_id` and `regional_episode_id` resolve to the event and episode catalogues. Full local export is not in the public tree; the public tree includes a preview. The previous manuscript table did not distinguish this schema from the original bundle. |
| `data/v2/events/p12_b2_station_events.csv` | One station heatwave event; 25 rows, 31 columns | `event_id` is unique and non-null | Checked station/source IDs, local and UTC bounds, threshold/sample fields, duration/temperature summaries, onset/recovery/full-window bounds, `regional_episode_id`, `weather_eligibility_status`, `joint_evaluation_eligibility`, `provisional`, `exclusion_reason`, and `source_file_references`; no null values observed | Every episode reference resolves. Weather eligibility and joint evaluation eligibility are separate fields. |
| `data/v2/events/p12_b2_regional_episodes.csv` | One connected regional episode; 15 rows, 13 columns | `regional_episode_id` is unique and non-null | Checked component/event bounds, `member_event_count`, `distinct_station_count`, `station_codes`, `event_ids`, `represented_years`, `primary_independent_unit`, and `eligibility_summary`; no null values observed | Every event's episode reference resolves. `event_ids` is a membership list, not a relational primary key. |
| `data/v2/benchmarks/p12_b2_controls.csv` | One matched control; 12 rows, 24 columns | `control_id` is unique and non-null | Checked event/episode references, UTC bounds, duration, candidate rank, matching score, coverage and eligibility fields; no null values observed | Every `matched_event_id` resolves to the event catalogue. |
| `data/v2/benchmarks/p12_b2_ordinary_windows.csv` | One selected ordinary window; 240 rows, 24 columns | `ordinary_window_id` is unique and non-null | Checked event/episode references, UTC bounds, duration, selection rank/stratum, coverage, overlap, and limitation fields; no null values observed | Every matched event/episode reference resolves. Window overlap is a documented dependence issue, not a duplicate-key defect. |
| `data/v2/benchmarks/p12_b2_matrix_cells.csv` | One planned simulation cell; 6,480 rows, 17 columns | `run_id` is unique and non-null | Checked `window_id`, `window_type`, `event_id`, `regional_episode_id`, policy/facility/curve/load/seed/objective fields and workload/configuration hashes; no null values observed | All event, episode, and window references resolve. This is a matrix/configuration artifact, not the execution-output schema. |
| `data/v2/results/p12_b2_execution.jsonl` | One execution record per matrix cell; 6,480 records | `run_id` is unique and non-null; all matrix run IDs are represented | Checked `execution_status`, `failure_category`, `completed_processing_slots`, service counts, feasibility fields, facility energy/power, cost/carbon, runtime, and hashes. The 1,032 failed records legitimately have null outcome/feasibility fields; `applied_margin` is null where inapplicable | Every execution `run_id` resolves to the matrix. The manuscript now uses actual output fields rather than only repeating matrix factors. |

## Referential-integrity results

Observed missing references were zero for:

- extension hourly event to station event;
- extension hourly episode to regional episode;
- station event to regional episode;
- matched control to station event;
- ordinary window to station event;
- matrix cell to event, episode, and known window;
- execution result to matrix cell.

## Manuscript corrections arising from the audit

1. Split the original public hourly bundle from the locally generated extension hourly export.
2. State the checked composite keys explicitly; do not imply that `station_code`, `event_id`, or `window_id` alone uniquely identifies an hourly row.
3. Use exact demand fields: `demand_mw` in the original Parquet bundle and `demand_mwh` in the extension hourly export.
4. Preserve the distinct event-level `weather_eligibility_status` and `joint_evaluation_eligibility` fields.
5. Describe `run_id` as unique in both the 6,480-row matrix and execution stream, while separating configuration fields from outcome fields.
6. State that failed execution records retain identity/status but may have null scientific outcomes.

No source file, dataset, identifier, or frozen result was changed during verification.
