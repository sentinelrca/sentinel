"""API key authentication. Injects workspace into request via FastAPI Depends."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from sentinel_pipeline.db.postgres import WorkspaceRow, get_session

_bearer = HTTPBearer()


async def get_workspace(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> WorkspaceRow:
    api_key = credentials.credentials
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    async with get_session() as session:
        result = await session.execute(
            select(WorkspaceRow).where(WorkspaceRow.api_key_hash == key_hash)
        )
        ws = result.scalar_one_or_none()
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return ws
