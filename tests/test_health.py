from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pipeguard.database import Base, get_db
from pipeguard.main import app
from sqlalchemy.exc import OperationalError


class _UnreachableSession:
    """Stands in for a session whose database has gone away."""

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def close(self) -> None:
        pass


def test_root_serves_the_dashboard(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<script src="/static/app.js"' in response.text


def test_api_docs_use_the_dashboard_styling(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert '<link rel="stylesheet" href="/static/docs.css">' in response.text
    assert 'href="/">Dashboard</a>' in response.text


def test_ingest_key_is_declared_for_the_docs(client: TestClient) -> None:
    # Declared as a security scheme, the docs page offers an Authorize button.
    schema = client.get("/openapi.json").json()

    scheme = schema["components"]["securitySchemes"]["APIKeyHeader"]
    assert scheme == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Shared secret set by `INGEST_API_KEY` on the server.",
    }
    assert schema["paths"]["/runs"]["post"]["security"] == [{"APIKeyHeader": []}]


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/app.js", "javascript"),
        ("/static/styles.css", "text/css"),
        ("/static/docs.css", "text/css"),
        ("/static/favicon.svg", "image/svg+xml"),
    ],
)
def test_dashboard_assets_are_served(client: TestClient, path: str, content_type: str) -> None:
    # The page is useless if an asset it references is missing from the package.
    response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def test_health_reports_ok_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"


def test_health_reports_degraded_when_the_database_is_unreachable(
    client: TestClient,
) -> None:
    def unreachable_db() -> Generator[_UnreachableSession, None, None]:
        yield _UnreachableSession()

    app.dependency_overrides[get_db] = unreachable_db

    response = client.get("/health")

    # The endpoint used to return a constant "ok", so a dashboard watching it
    # stayed green while the database behind it no longer existed. It has to be
    # able to fail, and to fail with a status code a monitor can act on.
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "unavailable"


def test_startup_does_not_mutate_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_create_all(**kwargs: Any) -> None:
        raise AssertionError("schema changes belong to Alembic, not application startup")

    monkeypatch.setattr(Base.metadata, "create_all", unexpected_create_all)

    # TestClient used to run create_all against the globally configured database,
    # even though request sessions were correctly overridden to use the test DB.
    with TestClient(app) as test_client:
        assert test_client.get("/health").status_code in (200, 503)
