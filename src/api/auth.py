"""API key authentication dependency."""
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from config import API_KEY

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_header_scheme)) -> None:
    """FastAPI dependency — raises 403 when API_KEY is set and the request key is wrong."""
    if not API_KEY:
        return  # auth disabled in dev mode
    if key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key. Provide it via X-API-Key header.",
        )
