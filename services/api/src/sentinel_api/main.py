"""SentinelAI REST API server."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.health import router as health_router
from .routers.insights import router as insights_router
from .routers.flows import router as flows_router
from .routers.projects import router as projects_router
from .routers.detector_configs import router as detector_configs_router
from .routers.sources import router as sources_router
from .routers.traces import router as traces_router
from .routers.workspaces import router as workspaces_router

app = FastAPI(title="SentinelAI API", version="0.1.0")

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3001").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(insights_router,    prefix="/v1")
app.include_router(flows_router,       prefix="/v1")
app.include_router(projects_router,    prefix="/v1")
app.include_router(detector_configs_router, prefix="/v1")
app.include_router(sources_router,     prefix="/v1")
app.include_router(traces_router,      prefix="/v1")
app.include_router(workspaces_router,  prefix="/v1")
