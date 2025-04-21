import pytest_asyncio
from typing import AsyncGenerator

from redis.asyncio import Redis
from db.database import async_engine, local_session , Base
from sqlalchemy.ext.asyncio.session import AsyncSession

from db.redis_client import redis_client

@pytest_asyncio.fixture(scope="function") #type: ignore
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with local_session() as session:
        try:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            yield session
        finally:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        await session.close()  


@pytest_asyncio.fixture(scope="function")
async def redis() -> AsyncGenerator[Redis, None]:
    try:
        yield redis_client
    finally:
        await redis_client.flushall() # type: ignore
        await redis_client.aclose()
