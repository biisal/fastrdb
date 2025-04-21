## Create A Database Connection

```python
# db.py
from typing import AsyncGenerator
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
async_engine = create_async_engine(DATABASE_URL, echo=True)
local_session = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False
)

async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with local_session() as session:
        try:
            await session.commit()
            yield session
        finally:
            await session.close()
```

## Create A SqlAlchemy Model

```python hl_lines="4"
# models.py
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean
from db import Base

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

## Create required Pydantic schemas/models

```python
# schemas.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    bio: Optional[str] = None
    is_active: bool = True

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    bio: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    bio: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 
```


## Now Initialize FastRDB

```python hl_lines="2"
# crud.py
from fastrdb import FastRDB
from models import User
from schemas import UserCreate, UserUpdate, UserResponse

user_crud = FastRDB[User, UserCreate, UserUpdate, UserResponse](
    User, 
    UserResponse,   
    pattern="user:email:{email}",
    list_pattern="user:page:{page}:limit:{limit}",
    invalidate_pattern_prefix="todo:*",
    exp=6000
)

```
### Args Explanations:
- Generic type arguments [...]
    - ModelType: SQLAlchemy model (e.g., Item) representing the DB table
    - CreateSchemaType: Pydantic schema for creation operations
    - UpdateSchemaType: Pydantic schema for update operations
    - ResponseSchemaType: Pydantic schema for response serialization

- Constructor arguments (...):
    - **Model** : SQLAlchemy model class
    - **ResponseSchema** : Pydantic model for response serialization
    - **pattern** : Used for caching a single object (like one user)
        ```Python
        pattern="user:email:{email}"
        ```
        What it means:
        - This pattern creates a unique Redis key for each individual item.
        - The placeholder ({email} will be replaced by actual values at runtime.
        Example key:
            ```python
            user:email:john@example.com
            ```
    - **list_pattern** :  Used for caching a list of objects (like paginated results)
        ```Python
        list_pattern = "user:page:{page}:limit:{limit}"
        ```
        What it means:
        - This creates a Redis key for a specific page of a list.
        - Example key:
            ```python
            user:page:1:limit:10
            ```

    - **invalidate_pattern_prefix**	:Used to invalidate multiple related keys at once
        ```Python
        invalidate_pattern_prefix="user:*"
        ```
        What it means:

        - This sets up a prefix for cache keys that should be cleared when data is updated or deleted.
        - Example key:
            ```python
            user:*
            ```
    
    - **exp**: Redis expiration time

## Now Create Async Redis Client

```python hl_lines="2"
# redis_client.py
from redis.asyncio import Redis
from typing import AsyncGenerator

redis_host = "localhost"           
redis_port = 6379          
redis_db = 0
redis_decode_responses = True 

redis_client = Redis(
    host=redis_host,
    port=redis_port,
    db=redis_db,
    decode_responses=redis_decode_responses
)

async def get_redis() -> AsyncGenerator[Redis, None]:
    try:
        yield redis_client
    finally:
        await redis_client.close()
```

### Now we are ready to use the FastRDB class

- In this example, we'll create a FastAPI app to manage items.(But you can use it anywhere)
```python hl_lines="16"
# main.py
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from redis_client import get_redis
from crud import user_crud
from models import User
from schemas import UserCreate, UserUpdate, UserResponse
from db import async_get_db

app = FastAPI()

@app.post("/users/", response_model=UserResponse)
async def create_user(user: UserCreate, redis: Redis = Depends(get_redis), db: AsyncSession = Depends(async_get_db)) -> UserResponse:
    return await user_crud.create(db=db, redis=redis, obj_in=user , email=user.email)
```

- If you want to use without FastAPI:

```python hl_lines="10"
# main.py
from redis_client import get_redis
from crud import user_crud
from models import User
from schemas import UserCreate, UserUpdate, UserResponse
from db import async_get_db

async def create_user(user: UserCreate) -> UserResponse:
    async with get_redis() as redis, async_get_db() as db:
        return await user_crud.create(db=db, redis=redis, obj_in=user , email=user.email)

```
## All Methods

### `create`
- Creates a new record in the database and caches it in Redis.
    - args : `db: AsyncSession, redis: Redis, obj_in: CreateSchema, **kwargs: Any`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `redis: Redis`: An async Redis client.
        - `obj_in: CreateSchema`: An instance of the create schema.
        - `**kwargs: Any`: Keyword arguments for matching redis pattern. Like you have set `pattern="user:email:{email}"` then you will pass `email="john@example.com"` here.
    - Returns : `ResponseSchemaType`
    - Example :
        ```python
        db = AsyncSession(...)  # Your SQLAlchemy async session
        redis = Redis(...)      # Your Redis client
        user = UserCreate(name="John Doe", email="john@example.com" , bio="Hello World")
        await user_crud.create(db=db, redis=redis, obj_in=user , email=user.email)
        ```
### `get`
- Retrieves a single record from the database and caches it in Redis.
    - args : `db: AsyncSession, redis: Redis, **kwargs: Any`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `redis: Redis`: An async Redis client.
        - `**kwargs: Any`: Keyword arguments used for matching the Redis key pattern and filtering the record from the database.
            - If your Redis key pattern is set as pattern="user:email:{email}", you must pass email="john@example.com" in kwargs.
            - These keyword arguments will be used both to format the Redis key and to filter the database query.
            - You can include additional filters, but it is mandatory to provide all fields required by the Redis key pattern.
    - Returns : `ResponseSchemaType` 
    - Raises : `NoResultFound` from SQLAlchemy
    - Example :
        ```python
        from sqlalchemy.orm.exc import NoResultFound
        db = AsyncSession(...)  # Your SQLAlchemy async session
        redis = Redis(...)      # Your Redis client
        try:
            user = await user_crud.get(db=db, redis=redis, email="john@example.com")
        except NoResultFound:
            # Handle the case where no user is found
            ...
        ```

### `update`
- Updates a record in the database and caches the updated record in Redis.
    - args : `db: AsyncSession, redis: Redis, obj_in: UpdateSchema, **kwargs: Any`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `redis: Redis`: An async Redis client.
        - `obj_in: UpdateSchema`: An instance of the update schema.
        - `**kwargs: Any`: Keyword arguments  for filtering the record to update.
            - If your Redis key pattern is set as pattern="user:email:{email}", you must pass email="john@example.com" in kwargs.
            - These keyword arguments will be used both to format the Redis key and to filter the database query.
            - You can include additional filters, but it is mandatory to provide all fields required by the Redis key pattern.
    - Returns : `ResponseSchemaType` 
    - Example :
        ```python
        db = AsyncSession(...)  # Your SQLAlchemy async session
        redis = Redis(...)      # Your Redis client
        user = UserUpdate(name="John Doe")
        await user_crud.update(db=db, redis=redis, obj_in=user , email="john@example.com")
        ```

### `get_multi`
- Retrieves multiple records from the database and caches them in Redis.
    - args : `db: AsyncSession, redis: Redis, limit : int = 10 , page : int = 1 , order_by : Optional[str] = None , ascending : bool = True , **kwargs: Any`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `redis: Redis`: An async Redis client.
        - `limit : int = 10`: Number of records per page.
        - `page : int = 1`: Current page number.
        - `order_by : Optional[str] = None`: Field to order by.
            - `order_by` must be a valid model attribute.
            - If you have a SqlAlchemy model field `id` then you can use `order_by="id"`. It will fetch records from database sorted by `id` in ascending(default) order.
        - `ascending : bool = True`: Sort direction. True for ascending (default), False for descending.
        - `**kwargs: Any`: Keyword arguments for filtering the records.
            - If your Redis key list_pattern is set as list_pattern="user:page:{page}:limit:{limit}" , you must pass page=1 and limit=10 in kwargs.However in this case the page and limit already has default value so you are not passing as keyword arg but you have to use it like this. 
    - Returns : `List[ResponseSchemaType]`
    - Example :
        ```python
        db = AsyncSession(...)  # Your SQLAlchemy async session
        redis = Redis(...)      # Your Redis client
        users = await user_crud.get_multi(db=db, redis=redis, limit=10, page=1 , order_by="id")


        # Another Example
        # verse_crud = FastRDB[Verse, VerseCreate, VerseUpdate, VerseResponse](
        # Verse, 
        # VerseResponse,   
        # pattern="verse:chapter_id:{chapter_id}:verse_id:{verse_id}",
        # list_pattern="verse:chapter_id:{chapter_id}:page:{page}:limit:{limit}",
        # invalidate_pattern_prefix="verse:chapter_id:{chapter_id}:*",
        # exp=6000)
            
        verses = await verse_crud.get_multi(
        db=db,
        redis=redis,
        limit=20,
        page=1,
        order_by="verse_id",
        chapter_id=3) # it will fetch records from database sorted by `verse_id` in ascending order and filtered by `chapter_id`
            # and list_pattern="verse:chapter:{chapter_id}:page:{page}:limit:{limit}"9

        ```

### `create_multi`
- Creates multiple records in the database.
    - args : `db: AsyncSession, redis: Redis, instances: List[CreateSchema]`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `redis: Redis`: An async Redis client.
        - `instances: List[CreateSchema]`: A list of instances of the create schema.
        - `**kwargs : Any`: Keyword arguments for matching redis pattern.
    - Returns : `List[ResponseSchemaType]`
    - Example :
    ```python
    db = AsyncSession(...)  # Your SQLAlchemy async session
    redis = Redis(...)      # Your Redis client
    users = [
        UserCreate(name="John Doe", email="john@example.com" , bio="Hello World"),
        UserCreate(name="Jane Doe", email="jane@example.com" , bio="Hello World")]
    await user_crud.create_multi(db=db, redis=redis, instances=users)
    ```

### `delete`
- Deletes a record from the database and invalidates the cache.
    - args : `db: AsyncSession, redis: Redis, **kwargs: Any`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `redis: Redis`: An async Redis client.
        - `**kwargs: Any`: Keyword arguments used for matching the Redis key pattern and filtering the record from the database.
            - If your Redis key `pattern` is set as pattern="user:email:{email}", you must pass email="john@example.com" in kwargs.
            - make sure arg maches your `invalidate_pattern_prefix` like invalidate_pattern_prefix="user:email:{email}" then you must pass email="john@example.com"
            - These keyword arguments will be used both to format the Redis key and to filter the database query.
            - You can include additional filters, but it is mandatory to provide all fields required by the Redis key pattern.
    - Returns : None
    - Example :
        ```python
        db = AsyncSession(...)  # Your SQLAlchemy async session
        redis = Redis(...)      # Your Redis client
        await user_crud.delete(db=db, redis=redis, email="john@example.com")
        ```

### `count`
- Counts the number of records in the database.
    - args : `db: AsyncSession, redis: Redis, **kwargs: Any`
    - Explanation:
        - `db: AsyncSession`: An async SQLAlchemy session.
        - `**kwargs: Any`: Keyword arguments used for filtering the records from the database.
    - Returns: count of data
    - Example :
    ```python
    db = AsyncSession(...)  # Your SQLAlchemy async session
    await user_crud.count(db=db, email="john@example.com")
    ```

### `paginate`
- Returns a paginated response for a given list of data.
    - args : `data : List[Any] , limit : int , page : int`
        - data: List[Any] – A list of items (usually model instances) to paginate.
        - limit: int – The maximum number of items per page.
        - page : int – The current page number.
    - Returns: `List[Any]`
        - PaginatedResponse[Any] – A Pydantic model containing:
        - data: Sublist of items for the requested page.
        - total: Total number of items across all pages.
        - limit: Number of items per page (as provided).
        - page: Current page number (as provided).
    - Example :
    ```python
    users = await user_crud.get_multi(db=db, redis=redis, limit=10, page=1 , order_by="id")
    return verse_crud.paginate(data=users, limit=limit, page=page)
    ```

---
# Conclusion
You've now set up a FastRDB instance and can start using it for your database operations.

### Thanks for following along!
- If this helped you, consider giving the project a ⭐️, sharing it, or contributing to future improvements.
Happy Coding!
- Github: [biisal/fastrdb](https://github.com/biisal/fastrdb)
- Contact : [+917029881540](https://wa.me/+917029881540)
