"""Workspace provisioning router.

POST /v1/workspaces — create a workspace and issue an API key.

Gated by X-Admin-Key header (must match SENTINEL_ADMIN_KEY env var).
The raw API key is returned exactly once; only its SHA-256 hash is stored.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import select

from sentinel_pipeline.db.postgres import WorkspaceRow, get_session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)

_KEY_PREFIX = "sk-sentinel-"


def _check_admin_key(admin_key: str | None = Security(_admin_key_header)) -> None:
    expected = os.environ.get("SENTINEL_ADMIN_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workspace provisioning is not configured (SENTINEL_ADMIN_KEY not set)",
        )
    if not admin_key or not hmac.compare_digest(admin_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key",
        )


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    tier: int = Field(default=0, ge=0, le=3)


class WorkspaceCreated(BaseModel):
    id:         str
    name:       str
    tier:       int
    api_key:    str   # shown once — store it now, it cannot be recovered
    created_at: str


@router.post("", status_code=201, response_model=WorkspaceCreated)
async def create_workspace(
    body: WorkspaceCreate,
    _: None = Depends(_check_admin_key),
) -> dict[str, Any]:
    """Provision a new workspace and return a one-time API key.

    The raw key is returned in this response only. The server stores only its
    SHA-256 hash. If the key is lost, rotate it via POST /workspaces/{id}/api-keys.
    """
    # Generate a random API key and hash it for storage
    raw_key  = _KEY_PREFIX + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    async with get_session() as session:
        # Guard against hash collision (astronomically unlikely but correct)
        existing = await session.execute(
            select(WorkspaceRow).where(WorkspaceRow.api_key_hash == key_hash)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Key hash collision — retry the request",
            )

        row = WorkspaceRow(
            id=str(uuid.uuid4()),
            name=body.name,
            api_key_hash=key_hash,
            tier=body.tier,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)

    return {
        "id":         row.id,
        "name":       row.name,
        "tier":       row.tier,
        "api_key":    raw_key,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


@router.post("/{workspace_id}/api-keys", status_code=201)
async def rotate_api_key(
    workspace_id: str,
    _: None = Depends(_check_admin_key),
) -> dict[str, Any]:
    """Issue a new API key for an existing workspace, invalidating the previous one."""
    raw_key  = _KEY_PREFIX + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    async with get_session() as session:
        result = await session.execute(
            select(WorkspaceRow).where(WorkspaceRow.id == workspace_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        row.api_key_hash = key_hash

    return {"workspace_id": workspace_id, "api_key": raw_key}
