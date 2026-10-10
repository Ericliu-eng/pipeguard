import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pipeguard.config import Settings, get_settings
from pipeguard.database import Base, get_db, normalize_database_url
from pipeguard.main import app
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Tests run against SQLite by default so the suite stays fast and needs nothing
# installed. Set TEST_DATABASE_URL to point them at a real PostgreSQL instead;
# CI does both, because a SQLite-only suite never loads the PostgreSQL driver and
# so cannot catch a driver or dialect problem that breaks production.
DEFAULT_TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"


def create_test_engine() -> Engine:
    url = normalize_database_url(os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
    if url.startswith("sqlite"):
        # One shared in-memory database for the whole engine; a fresh connection
        # would otherwise get its own empty database.
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url)


@pytest.fixture(autouse=True)
def default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings read .env, and the docs tell developers to set INGEST_API_KEY
    # there. Without this, a local .env changed what the tests asserted.
    settings = get_settings()
    for name, field in Settings.model_fields.items():
        monkeypatch.setattr(settings, name, field.default)


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    test_engine = create_test_engine()
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Generator[Session, None, None]:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> Generator[TestClient, None, None]:
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
