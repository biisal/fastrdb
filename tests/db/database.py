from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

# Dummy database config
DB_DRIVER = "sqlite+aiosqlite"
DB_NAME = "example.db"
DATABASE_URL = f"{DB_DRIVER}:///{DB_NAME}"  # sqlite+aiosqlite:///example.db

# Base class for models
class Base(MappedAsDataclass, DeclarativeBase):
    pass

# Async engine and session factory
async_engine = create_async_engine(DATABASE_URL, echo=False)
local_session = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False
)
