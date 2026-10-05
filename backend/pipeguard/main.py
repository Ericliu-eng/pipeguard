import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pipeguard import __version__, docs_page
from pipeguard.config import get_settings
from pipeguard.database import get_db
from pipeguard.routers.runs import router as runs_router
from pipeguard.schemas import HealthResponse

logger = logging.getLogger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

DESCRIPTION = """
Run monitoring for data pipelines. Pipelines report each finished run here; PipeGuard keeps
their history, compares every run's row count with that pipeline's recent healthy runs, and
explains each incident in terms of the check that failed.

**[Open the dashboard](/)** · [Source on GitHub](https://github.com/Ericliu-eng/pipeguard)

### Quick start

Reporting a run needs the `X-API-Key` header — use **Authorize** to set it here. Everything
else is read-only, apart from the demo pipeline and analysis.

```bash
curl -X POST "$PIPEGUARD_URL/runs" \\
  -H "X-API-Key: $PIPEGUARD_API_KEY" -H "Content-Type: application/json" \\
  -d '{"pipeline_name": "orders", "external_run_id": "orders-2026-10-04",
       "status": "SUCCESS", "started_at": "2026-10-04T12:00:00Z",
       "finished_at": "2026-10-04T12:00:04Z", "rows_processed": 500, "checks": []}'
```

A run has two independent states: `status` says whether it ran, `quality_status` whether its
data passed. A run can succeed and still deliver bad data.
"""

TAGS = [
    {"name": "Ingest", "description": "Report runs from your own pipelines. Needs an API key."},
    {"name": "Runs", "description": "Run history, filters, KPIs, and each run's checks."},
    {"name": "Analysis", "description": "Rule-based incident analysis for a finished run."},
    {"name": "Demo", "description": "A bundled synthetic pipeline for trying things out."},
    {"name": "System", "description": "Service health."},
]

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=DESCRIPTION,
    openapi_tags=TAGS,
    docs_url=None,  # served below, with the dashboard's styling
)
app.include_router(runs_router)


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """Serve the dashboard from the API itself.

    It is a static page that reads the public endpoints, so it needs no second
    service: one deploy to keep awake on free hosting instead of two, and no
    copy of the API's base URL to keep in sync.
    """
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/docs", include_in_schema=False)
def api_docs() -> HTMLResponse:
    """An overview of the API in the dashboard's style, then the Swagger UI."""
    return HTMLResponse(
        docs_page.render(app.openapi(), app.openapi_url, f"{settings.app_name} reference")
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Check service health",
    description=(
        "Runs a query against the database. Answers `200` when it succeeds and `503` with "
        '`"status": "degraded"` when it does not.'
    ),
    responses={503: {"model": HealthResponse, "description": "The database is unreachable"}},
)
def health(db: DbSession, response: Response) -> HealthResponse:
    """Report whether the service can actually serve requests.

    This probes the database rather than returning a constant. A health check
    that cannot fail is not a health check: this one answered "ok" for two
    months while the database behind it no longer existed, so every dashboard
    watching it stayed green through a complete outage.
    """
    try:
        db.execute(select(1))
        database = "ok"
    except SQLAlchemyError:
        logger.exception("Health check could not reach the database")
        database = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        service=settings.app_name,
        environment=settings.app_env,
        database=database,
    )
