from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from pipeguard.config import get_settings


class Base(DeclarativeBase):
    pass


_POSTGRES_PREFIXES = ("postgresql+psycopg2://", "postgresql://", "postgres://")


def normalize_database_url(database_url: str) -> str:
    """Resolve any PostgreSQL URL to the psycopg3 driver.

    SQLAlchemy picks the DBAPI from the URL scheme, and a bare ``postgresql://``
    meant psycopg2 before SQLAlchemy 2.1 and means psycopg3 from 2.1 on. Hosting
    providers hand out bare URLs, so the driver would otherwise be decided by
    whichever SQLAlchemy a fresh install happens to resolve — or by hand-editing
    the scheme into an environment variable, where it is invisible to this repo.
    Decide it here instead, in version control, where it is reviewable and tested.
    """
    for prefix in _POSTGRES_PREFIXES:
        if database_url.startswith(prefix):
            return f"postgresql+psycopg://{database_url[len(prefix) :]}"
    return database_url


def connect_args_for(database_url: str) -> dict[str, object]:
    """DBAPI connect arguments shared by every engine this project creates.

    The application engine and the migration engine both go through this, so a
    connection limit cannot be set on one and forgotten on the other. That is
    exactly what happened once: the application engine gained a timeout, the
    migration engine did not, and since migrations run before the server starts,
    an unreachable database hung startup forever all over again.
    """
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    # Bounds how long an unreachable host can stall a connection attempt. libpq
    # waits forever by default, which reads as "the service never responds"
    # rather than as an error anyone can act on.
    return {"connect_timeout": get_settings().database_connect_timeout}


def _engine_kwargs(database_url: str) -> dict[str, object]:
    connect_args = connect_args_for(database_url)
    if database_url.startswith("sqlite"):
        return {"connect_args": connect_args}
    # Managed Postgres instances drop idle connections, and a dead connection is
    # only detected when it is used. Validate on checkout and retire old ones so a
    # request after an idle period does not fail with OperationalError.
    return {
        "connect_args": connect_args,
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }


settings = get_settings()
database_url = normalize_database_url(settings.database_url)
engine = create_engine(database_url, **_engine_kwargs(database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
