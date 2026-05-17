from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel",
)

# Replace postgres:// with postgresql+asyncpg:// for SQLAlchemy async
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class Base(DeclarativeBase):
    pass


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id         = Column(String, primary_key=True)
    name       = Column(String, nullable=False)
    api_key_hash = Column(String, nullable=False, unique=True)
    tier       = Column(Integer, nullable=False, default=0)  # maps to Tier enum
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SourceRow(Base):
    __tablename__ = "sources"

    # config_json standard keys (all connectors must honour these):
    #   kind (str): connector type, e.g. "langfuse" or "langsmith"
    #   store_content (bool, default False): when False, connectors omit prompt/response
    #     content (inputs, outputs, messages) from span attributes; only structural fields
    #     (token counts, latency, span kind, status) are retained.
    #     Set True only when the workspace operator has explicitly opted in.
    #   [future M5] mask_pii (bool, default False): when True and store_content is True,
    #     apply PII redaction before storing content in span attributes.

    id             = Column(String, primary_key=True)
    workspace_id   = Column(String, nullable=False)
    kind           = Column(String, nullable=False)   # "langfuse" | "langsmith" | ...
    config_json    = Column(JSON,   nullable=False)   # encrypted at rest in production
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


class RuleConfigRow(Base):
    __tablename__ = "rule_configs"

    id           = Column(String, primary_key=True)
    workspace_id = Column(String, nullable=False)
    rule_id      = Column(String, nullable=False)
    action       = Column(String, nullable=False)   # 'DISABLED' | 'OVERRIDE_SEVERITY'
    severity     = Column(String, nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now())


class InsightRow(Base):
    __tablename__ = "insights"

    id                 = Column(String, primary_key=True)
    workspace_id       = Column(String, nullable=False, index=True)
    trace_id           = Column(String, nullable=False, index=True)
    rule_id            = Column(String, nullable=False)
    severity           = Column(String, nullable=False)
    title              = Column(String, nullable=False)
    detail             = Column(Text,   nullable=False)
    recommendation     = Column(Text,   nullable=False)
    affected_span_ids  = Column(JSON,   nullable=False, default=list)
    evidence           = Column(JSON,   nullable=False, default=dict)
    status             = Column(String, nullable=False, default="open")
    created_at         = Column(DateTime(timezone=True), server_default=func.now(), index=True)
