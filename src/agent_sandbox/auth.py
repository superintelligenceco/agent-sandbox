"""API key authentication."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from agent_sandbox.config import Settings

bearer_scheme = HTTPBearer(auto_error=False, description="`Authorization: Bearer <api key>`")
header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, description="`X-API-Key: <api key>`")


def key_is_valid(candidate: str, keys: tuple[str, ...]) -> bool:
    """Compare ``candidate`` against every configured key in constant time."""
    matched = False
    for key in keys:
        matched |= hmac.compare_digest(candidate.encode(), key.encode())
    return matched


def require_api_key(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    header_key: str | None = Depends(header_scheme),
) -> None:
    settings: Settings = request.app.state.settings
    if settings.insecure_no_auth:
        return
    candidate = bearer.credentials if bearer else header_key
    if not candidate or not key_is_valid(candidate, settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
