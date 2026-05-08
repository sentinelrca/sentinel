"""SentinelAI REST API server."""
from __future__ import annotations

from fastapi import FastAPI

from .routers.health import router as health_router
from .routers.insights import router as insights_router

app = FastAPI(title="SentinelAI API", version="0.1.0")

app.include_router(health_router)
app.include_router(insights_router, prefix="/v1")
