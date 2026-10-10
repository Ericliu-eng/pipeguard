# API reference

Interactive documentation for the deployed service is at
[pipeguard-fn1b.onrender.com/docs](https://pipeguard-fn1b.onrender.com/docs). Free instances
sleep when idle, so the first request can take about a minute.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health, including a database probe |
| `POST` | `/runs` | Report a run executed by an external pipeline |
| `POST` | `/runs/demo` | Run the bundled synthetic pipeline |
| `GET` | `/runs` | Recent runs as a plain array (kept for backward compatibility) |
| `GET` | `/runs/page` | Filtered, paginated run history with KPI summary |
| `GET` | `/runs/{id}` | One run |
| `GET` | `/runs/{id}/checks` | That run's quality checks |
| `GET` | `/runs/{id}/analysis` | The stored incident analysis |
| `POST` | `/runs/{id}/analyze` | Create the incident analysis |

## Health

`GET /health` runs a query against the database instead of returning a constant. It
answers `200` with `"database": "ok"`, or `503` with `"status": "degraded"` when the
query fails.

A health check that cannot fail is not a health check: an earlier version returned a
constant `200` and reported this service healthy for two months while the database
behind it no longer existed.

## Reporting a run

`POST /runs` records a run that a pipeline has already executed. The pipeline sends what
only it knows — its timings, row count, errors, and the checks it evaluated on its own
data. PipeGuard then adds the row-count anomaly check, which compares the run with that
pipeline's previous healthy runs: history a single run has no way to see.

```json
{
  "pipeline_name": "market_data_lakehouse_pipeline",
  "external_run_id": "market-data-2026-09-28T12:00:00Z",
  "status": "SUCCESS",
  "started_at": "2026-09-28T12:00:00Z",
  "finished_at": "2026-09-28T12:00:04Z",
  "rows_processed": 500,
  "checks": [
    {
      "check_name": "not_null",
      "status": "PASS",
      "metric_value": 0.0,
      "threshold": 0.0,
      "message": "market_bars.ts has no nulls."
    }
  ]
}
```

```bash
curl -X POST "$PIPEGUARD_API_URL/runs" \
  -H "X-API-Key: $PIPEGUARD_API_KEY" \
  -H "Content-Type: application/json" \
  -d @report.json
```

**Contract**

- `status` is `SUCCESS` or `FAILED`; checks report `PASS`, `WARN`, or `FAIL`.
- `started_at` and `finished_at` must carry a timezone, and a run cannot finish before it
  starts. `rows_processed` must be non-negative.
- A failed run gets no anomaly check. Its zero rows mean it stopped, not that the source
  shrank, and flagging that would bury the real failure under an invented one.

**Responses**

| Status | Meaning |
| --- | --- |
| `201` | Run recorded |
| `200` | Same `external_run_id` with the same data: the stored run is returned, nothing is duplicated |
| `409` | Same `external_run_id` with *different* data: rejected rather than overwriting or masking another execution |
| `401` | Missing or wrong `X-API-Key` |
| `503` | No `INGEST_API_KEY` configured: the endpoint fails closed instead of accepting writes |
| `422` | Payload failed validation |

Retries are safe because of `external_run_id`, and concurrent retries are settled by a
unique index on `(pipeline_name, external_run_id)`. The API key is compared in constant
time.

**Execution and quality are separate.** `status` says whether the pipeline ran;
`quality_status` summarizes its checks as `PASS`, `WARN`, `FAIL`, or `NOT_EVALUATED`. A
run can succeed and still deliver bad data, and the two fields keep that visible.

## Run history

`GET /runs/page` accepts exact `pipeline_name`, `status`, and `quality_status` filters,
plus `limit` (1–200, default 50) and `offset`.

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0,
  "has_more": false,
  "summary": {
    "successful": 0,
    "failed": 0,
    "running": 0,
    "quality_incidents": 0
  }
}
```

`total` and `summary` cover every run matching the filters, not just the current page, and
come from the same query as the page itself so the two cannot disagree. Results are ordered
by newest start time, then by ID. As with any offset pagination, runs inserted while someone
is browsing can shift later pages.

## Incident analysis

`POST /runs/{id}/analyze` returns `201` with a new analysis the first time and `200` with
the stored one afterwards: a finished run and its checks no longer change, so a repeat call
would only duplicate rows. A run that is still in progress returns `409`.

Each failed check is explained in terms of what that check measures. A collapsed row count
points at upstream truncation or throttling rather than at nulls and duplicates. Advice
covers PipeGuard's own checks (`null_rate`, `duplicate_rate`, `freshness`,
`row_count_anomaly`) and the names an external pipeline typically reports (`not_null`,
`unique`, `range`, `foreign_key`); any other name falls back to generic advice.
`likely_causes` and `recommended_steps` are JSON arrays.

## Demo runs

`POST /runs/demo` runs the bundled pipeline over synthetic data, so every scenario
reproduces exactly:

| Request | Scenario |
| --- | --- |
| `POST /runs/demo` | A clean run |
| `POST /runs/demo?data_scenario=quality_failure` | The run succeeds but its data fails quality checks |
| `POST /runs/demo?simulate_failure=true` | The run itself fails |
