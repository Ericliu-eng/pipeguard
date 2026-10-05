import secrets
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from pipeguard.config import get_settings

API_KEY_HEADER = "X-API-Key"

# Declared as a security scheme rather than a plain header so the API docs show
# an Authorize button and send the key with every request tried from there.
# auto_error is off because a missing key must answer 401 with the same body as
# a wrong one, and an unconfigured server must answer 503 before either.
api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="Shared secret set by `INGEST_API_KEY` on the server.",
)


def require_ingest_key(
    x_api_key: Annotated[str | None, Security(api_key_header)] = None,
) -> None:
    """Guard the endpoint that accepts run reports from outside.

    Disabled rather than open when no key is configured: this endpoint writes
    rows on behalf of a caller, so an unset secret must fail closed.
    """
    settings = get_settings()

    if not settings.ingest_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run ingestion is not configured",
        )

    # Constant-time comparison: a plain == leaks the key a character at a time
    # to anyone who can measure the response.
    if not secrets.compare_digest(x_api_key or "", settings.ingest_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
