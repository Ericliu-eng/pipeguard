# Running and operating PipeGuard

## Run with Docker

```bash
docker compose up --build
```

- Dashboard: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`

The API container applies Alembic migrations before it starts the server, and stores a
local SQLite database in a named volume. Values from `.env` — quality thresholds, the
retention limit, `INGEST_API_KEY` — are passed into the container.

## Run without Docker

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn pipeguard.main:app --app-dir backend --reload
```

The dashboard is served by the API at `http://127.0.0.1:8000`; there is nothing else to
start.

## Configuration

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./pipeguard.db` | Any `postgresql://` URL works unedited; see below |
| `DATABASE_CONNECT_TIMEOUT` | `10` | Seconds to wait for PostgreSQL before giving up |
| `INGEST_API_KEY` | *(empty)* | Shared secret for `POST /runs`; empty disables that endpoint |
| `RUN_RETENTION_LIMIT` | `500` | Newest runs kept *per pipeline*; `0` keeps everything |
| `ROW_COUNT_DROP_THRESHOLD` | `0.30` | Drop versus recent runs that fails the anomaly check |
| `ROW_COUNT_HISTORY_SIZE` | `5` | Previous healthy runs used as the anomaly baseline |
| `NULL_RATE_THRESHOLD` | `0.05` | Demo pipeline: allowed share of null values |
| `DUPLICATE_RATE_THRESHOLD` | `0.01` | Demo pipeline: allowed share of duplicate keys |
| `FRESHNESS_HOURS_THRESHOLD` | `24` | Demo pipeline: maximum age of the newest event |
| `APP_NAME`, `APP_ENV` | `PipeGuard API`, `development` | Reported by `/health` |

**Retention is per pipeline.** Older runs are deleted together with their checks and
analyses. With one shared budget, a pipeline that runs often would evict the history of
one that runs rarely, and the rare pipeline is usually the one whose history you still
want.

**The anomaly baseline only uses healthy runs.** Runs whose own quality checks failed are
left out, so one bad load cannot drag the baseline down and hide the next.

## Database migrations

Schema changes are managed by Alembic:

```bash
alembic upgrade head
```

The first migration adopts databases created by earlier releases with `create_all`, which
is how the production database moved under Alembic. Data migrations are tested on rows in
the old format, on both SQLite and PostgreSQL, rather than on empty tables.

## Deployment

Production runs on Render as a single service — the API also serves the dashboard — and the
database is a Neon PostgreSQL instance.

- **Driver resolution.** `DATABASE_URL` can be pasted from the provider unedited. Any
  PostgreSQL scheme is normalized to psycopg 3 at startup, because SQLAlchemy 2.1 changed
  the default driver for a bare `postgresql://` — a change that once broke production on
  a fresh install.
- **Bounded startup.** Both the migration engine and the application engine give up after
  `DATABASE_CONNECT_TIMEOUT`. libpq would otherwise wait forever, and since migrations run
  before the server starts, a migration that never finishes is a server that never starts.
  An unreachable database now fails the boot with an error in the platform logs.
- **Health.** `/health` probes the database and returns `503` when it cannot reach it.

## Testing

```bash
pytest
ruff check backend migrations tests
```

The suite runs against in-memory SQLite by default. Point it at PostgreSQL to exercise the
production dialect and driver:

```powershell
docker run -d --name pipeguard-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=pipeguard_test -p 55432:5432 postgres:18
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:55432/pipeguard_test"
pytest
```

GitHub Actions runs Ruff, migrates a PostgreSQL 18 service, and runs the full suite against
both backends. Both runs matter: a SQLite-only suite never loads the PostgreSQL driver, so
it cannot catch a driver or dialect problem — which is exactly how a driver change once
reached production with every check green.

## Known limitations and next steps

- The bundled pipeline generates synthetic rows. Real pipelines integrate through
  `POST /runs`; there is no packaged client SDK yet.
- Incident analysis is rule-based; it does not call an LLM.
- Ingestion uses one shared API key, with no user accounts or rate limiting.
- `/health` can report a failure, but nothing watches it and raises an alert yet — which is
  how an earlier outage went unnoticed for two months. Alerting is the next gap to close.
- Quality thresholds are set through environment variables, not in the dashboard.
