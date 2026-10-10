# Data model

## `pipeline_runs`

One record per pipeline execution. Stores timing, execution status, aggregate quality status,
processed row count, and normalized error details. Externally reported runs also carry an
`external_run_id`; `(pipeline_name, external_run_id)` is unique so reporter retries are idempotent.
An internal request fingerprint rejects reuse of that identifier with different report data.

## `quality_checks`

One record per check evaluated for a run. Stores the measured value, configured threshold, status,
and a human-readable message. Demo runs write `null_rate`, `duplicate_rate`, `freshness`, and
`row_count_anomaly`. Externally reported runs store the checks the pipeline sent, plus a
`row_count_anomaly` computed here from that pipeline's history.

## `incident_analyses`

At most one analysis per run — the schema allows several, but `POST /runs/{id}/analyze`
returns the stored one instead of adding another — with severity, a summary, and model
provenance. `likely_causes` and
`recommended_steps` are JSON arrays, with advice specific to each check that failed.

Relationships:

```text
pipeline_runs 1 ---- * quality_checks
pipeline_runs 1 ---- * incident_analyses
```
