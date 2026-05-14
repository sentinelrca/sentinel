"""Create a dev workspace with a known API key. Run once after migrations."""
import asyncio
import hashlib
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel",
).replace("postgres://", "postgresql+asyncpg://")

API_KEY = "sk-sentinel-dev"
KEY_HASH = hashlib.sha256(API_KEY.encode()).hexdigest()

engine = create_async_engine(DATABASE_URL)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def main():
    from sentinel_pipeline.db.postgres import WorkspaceRow

    async with Session() as session:
        result = await session.execute(
            select(WorkspaceRow).where(WorkspaceRow.api_key_hash == KEY_HASH)
        )
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Workspace already exists: {existing.id} ({existing.name})")
            print(f"API key: {API_KEY}")
            return

        ws = WorkspaceRow(
            id="ws-dev",
            name="Dev Workspace",
            api_key_hash=KEY_HASH,
            tier=0,
        )
        session.add(ws)
        await session.commit()
        print(f"Created workspace: ws-dev")
        print(f"API key: {API_KEY}")


asyncio.run(main())
