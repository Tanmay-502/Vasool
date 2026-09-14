"""Small demo-friendly API key guard for state-changing operations.

Production deployments should still put this behind a proper identity provider or
service-to-service auth. This guard prevents unauthenticated public mutation while
keeping GET surfaces open for the dashboard.
"""

from fastapi import Header, HTTPException, status

from app.config import settings


def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.VASOOL_API_KEY.strip()
    if not expected:
        if settings.ENV.lower() in {"development", "test"}:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server API authentication is not configured",
        )

    supplied = x_api_key
    if not supplied and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = token.strip()

    if supplied != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid Vasool API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
