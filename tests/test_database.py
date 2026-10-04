import pytest
from pipeguard.database import _engine_kwargs, normalize_database_url


def test_sqlite_url_allows_cross_thread_access() -> None:
    assert _engine_kwargs("sqlite:///./pipeguard.db") == {
        "connect_args": {"check_same_thread": False}
    }


def test_postgres_url_validates_pooled_connections() -> None:
    kwargs = _engine_kwargs("postgresql+psycopg://user:pass@host:5432/pipeguard")

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 300
    # Bounded so an unreachable host errors instead of stalling forever.
    assert kwargs["connect_args"]["connect_timeout"] == 10


@pytest.mark.parametrize(
    "scheme",
    ["postgresql", "postgres", "postgresql+psycopg2"],
)
def test_postgres_urls_resolve_to_psycopg3(scheme: str) -> None:
    # Whatever scheme the host hands out, the driver must not be left to
    # SQLAlchemy's default: that default changed in 2.1 and took production down
    # with ModuleNotFoundError: No module named 'psycopg'.
    url = f"{scheme}://user:pass@host/db?sslmode=require"

    assert normalize_database_url(url) == ("postgresql+psycopg://user:pass@host/db?sslmode=require")


def test_normalizing_is_idempotent() -> None:
    url = "postgresql+psycopg://user:pass@host/db"

    assert normalize_database_url(url) == url


def test_sqlite_urls_are_left_alone() -> None:
    url = "sqlite+pysqlite:///:memory:"

    assert normalize_database_url(url) == url
