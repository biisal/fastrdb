from typing import Any, Generic, List, Optional,  Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import insert, select, update, delete, func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
import orjson
from redis.asyncio import Redis



ModelType = TypeVar("ModelType")
ResponseSchemaType = TypeVar("ResponseSchemaType", bound=BaseModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
ResponseListType = TypeVar("ResponseListType")

class PaginatedResponse(BaseModel, Generic[ResponseListType]):
    """
    Generic paginated response for API endpoints.
    
    Attributes:
        data: List of items in the current page
        total: Total number of items in the result set
        limit: Number of items per page
        page: Current page number
    """
    data: List[ResponseListType]
    total: int
    limit: int
    page: int


class FastRDB(Generic[ModelType, CreateSchemaType, UpdateSchemaType, ResponseSchemaType]):
    """
    Base CRUD class with generic database operations and Redis caching.
    
    This class provides common Create, Read, Update, Delete operations for SQLAlchemy models
    with integrated Redis caching to improve performance.
    
    Type Parameters:
        ModelType: SQLAlchemy model type
        CreateSchemaType: Pydantic schema for creation operations
        UpdateSchemaType: Pydantic schema for update operations
        ResponseSchemaType: Pydantic schema for response serialization
    """
    
    def __init__(self, 
                 model: Type[ModelType], 
                 response_schema: Type[ResponseSchemaType], 
                 pattern: str, 
                 list_pattern: str, 
                 exp: int,
                 invalidate_pattern_prefix: str):
        """
        Initialize CRUD operations class.
        
        Args:
            model: SQLAlchemy model class
            response_schema: Pydantic model for responses
            pattern: Redis key pattern for single item (e.g., "model:{id}")
            list_pattern: Redis key pattern for list items (e.g., "model:list:{limit}:{page}")
            exp: Redis expiration time in seconds
            invalidate_pattern_prefix: Pattern prefix for invalidating cache (e.g., "model:*")
        """
        self.model = model
        self.response_schema = response_schema
        self.pattern = pattern
        self.list_pattern = list_pattern
        self.exp = exp
        self.invalidate_pattern_prefix = invalidate_pattern_prefix

    @staticmethod
    def paginate(data: List[Any], limit: int, page: int) -> PaginatedResponse[Any]:
        """
        Generate a paginated response from a list of model instances.

        Args:
            data: The list of model instances to paginate.
            limit: The number of items per page.
            page: The current page number.

        Returns:
            A PaginatedResponse object containing the paginated data and pagination metadata.
        """
        return PaginatedResponse[Any](
            data=data,
            total=len(data),
            limit=limit,
            page=page
        )

    async def set_redis_data(self, redis: Redis, data: ResponseSchemaType, **kwargs: Any):
        """
        Store a single item in Redis cache.
        
        Args:
            redis: Redis connection object.
            data: The model data to store in Redis.
            **kwargs: Additional arguments for formatting the Redis key pattern.
                These should match the placeholders in the pattern string.
                
        Example:
            If pattern is "user:{id}", kwargs should contain {"id": 123}
        """
        data_string = data.model_dump_json()
        await redis.set(self.pattern.format(**kwargs), data_string, ex=self.exp)
        print(await redis.get(self.pattern.format(**kwargs)))

    async def set_redis_list_data(self, redis: Redis, data: List[ResponseSchemaType], **kwargs: Any):
        """
        Store a list of items in Redis cache.

        Args:
            redis: Redis connection object.
            data: List of model data to store in Redis.
            **kwargs: Additional arguments for formatting the Redis key pattern.
                These should match the placeholders in the list_pattern string.
                
        Example:
            If list_pattern is "users:list:{limit}:{page}", kwargs should contain 
            {"limit": 10, "page": 1}
        """
        data_string = orjson.dumps([item.model_dump() for item in data])
        await redis.set(self.list_pattern.format(**kwargs), data_string, ex=self.exp)

    async def get_redis_data(self, redis: Redis, return_multi: bool = False, **kwargs: Any):
        """
        Get data from Redis cache.

        Args:
            redis: Redis connection object.
            return_multi: If True, use list_pattern; otherwise, use single item pattern.
            **kwargs: Additional arguments for formatting the Redis key pattern.
                These should match the placeholders in either pattern or list_pattern.

        Returns:
            The cached data as bytes if found, otherwise None.
        """
        key = self.list_pattern.format(**kwargs) if return_multi else self.pattern.format(**kwargs)
        return await redis.get(key)

    async def invalidate_cache(self, redis: Redis, **kwargs: Any):
        """
        Invalidate cache entries matching the invalidation pattern.
        
        Uses Redis SCAN to find and delete all keys matching the pattern.

        Args:
            redis: Redis connection object.
            **kwargs: Additional arguments for formatting the invalidation pattern prefix.
                These should match the placeholders in invalidate_pattern_prefix.
        """
        pattern = self.invalidate_pattern_prefix.format(**kwargs)
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100) #type:ignore
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break

    async def create(self, db: AsyncSession, redis: Redis, obj_in: CreateSchemaType, **kwargs: Any) -> ResponseSchemaType:
        """
        Create a new record in the database and update cache.

        Args:
            db: The database session.
            redis: Redis connection object.
            obj_in: The schema with creation data.
            **kwargs: Additional arguments for Redis cache keys.

        Returns:
            The created model instance converted to response schema.
            
        Note:
            This method both creates the database record and updates the Redis cache.
            It also invalidates relevant list caches to ensure data consistency.
        """
        stmt = insert(self.model).values(obj_in.model_dump()).returning(self.model)
        result = await db.execute(stmt)
        obj = result.scalar_one()
        await db.commit()
        data = self.response_schema.model_validate(
            obj,
            from_attributes=True
        )
        await self.set_redis_data(redis=redis, data=data, **kwargs)
        await self.invalidate_cache(redis=redis, **kwargs)
        return data
    
    async def create_multi(self, db: AsyncSession, redis: Redis, instances: list[CreateSchemaType], **kwargs: Any) -> List[ResponseSchemaType]:
        """
        Create multiple records in the database in a single transaction and invalidate relevant caches.
    
        Args:
            db: The database session.
            redis: Redis connection object.
            instances: List of schemas with creation data.
            **kwargs: Additional arguments for Redis cache keys.
        
        Returns:
            List of created model instances converted to response schema.
        
        Note:
            This method creates multiple records and invalidates list caches to ensure data consistency.
            Individual item caches are not created for performance reasons, but will be populated on demand.
        """
        objs = [instance.model_dump() for instance in instances]
        query = insert(self.model).values(objs).returning(self.model)
        result = await db.execute(query)
        await db.commit()
    
        await self.invalidate_cache(redis=redis, **kwargs)
    
        created_models = result.scalars().all()
        return [self.response_schema.model_validate(model, from_attributes=True) for model in created_models]

    async def get(self, db: AsyncSession, redis: Redis, **kwargs: Any) -> ResponseSchemaType | None:
        """
        Get a single record by matching fields, with Redis caching.
        
        Args:
            db: Database session.
            redis: Redis connection object.
            **kwargs: Fields to filter by, must match model attributes.
            
        Returns:
            Found record as response schema or None if not found.
            
        Note:
            First tries to fetch from Redis cache, falls back to database lookup.
            If found in database but not in cache, updates the cache for future requests.
        """
        redis_data = await self.get_redis_data(redis=redis, **kwargs)
        if redis_data:
            return self.response_schema.model_validate_json(redis_data)
        stmt = select(self.model).filter_by(**kwargs)
        result = await db.execute(stmt)
        data = result.scalar_one_or_none()
        if data is None:
            raise NoResultFound(f"No {self.model.__name__} found matching criteria: {kwargs}")
    
        data = self.response_schema.model_validate(data, from_attributes=True)
        await self.set_redis_data(redis=redis, data=data, **kwargs)
        return data
        

    async def get_multi(self, db: AsyncSession, redis: Redis, limit: int = 10, page: int = 1, order_by : Optional[str] = None, ascending : bool = True, **kwargs: Any) -> List[ResponseSchemaType]:
        """
        Get multiple records with pagination, sorting and filtering.
        
        Args:
            db: The database session.
            redis: Redis connection object.
            limit: Items per page, defaults to 10.
            page: Current page number, defaults to 1.
            order_by: Field name to order results by. Must be a valid model attribute.
            ascending: Sort direction. True for ascending (default), False for descending.
            **kwargs: Fields to filter by, must match model attributes.
            
        Returns:
            List of model instances converted to response schema.
            
        Note:
            First tries to fetch from Redis cache, falls back to database lookup.
            If found in database but not in cache, updates the cache for future requests.
            Pagination is applied after filtering.
        """
        cache_key_params = {**kwargs, "limit": limit, "page": page}
        redis_data = await self.get_redis_data(redis=redis, return_multi=True, **cache_key_params)
        
        if redis_data:
            try:
                data_list = orjson.loads(redis_data)
                return [self.response_schema.model_validate(item) for item in data_list]
            except orjson.JSONDecodeError:
                pass
        
        stmt = select(self.model).filter_by(**kwargs).limit(limit).offset((page - 1) * limit)
        if order_by is not None and hasattr(self.model, order_by):
            order_column = getattr(self.model, order_by)
            order_column = order_column if ascending else order_column.desc()
            stmt = stmt.order_by(order_column)
        result = await db.execute(stmt)
        results = result.scalars().all()
        response_data = [self.response_schema.model_validate(model, from_attributes=True) for model in results]
        
        await self.set_redis_list_data(redis=redis, data=response_data, **cache_key_params)
        
        return response_data

    async def update(self, db: AsyncSession, redis: Redis, obj_in: UpdateSchemaType, **matches: Any) -> ResponseSchemaType:
        """
        Update a record in the database and refresh cache.

        Args:
            db: The database session.
            redis: Redis connection object.
            obj_in: The schema containing update data. Only non-None fields will be updated.
            **matches: Fields to identify the record to update, must match model attributes.

        Returns:
            The updated record converted to response schema.
            
        Note:
            This method performs the database update, updates the single-item cache,
            and invalidates any list caches to ensure data consistency.
        """
        stmt = update(self.model).filter_by(**matches).values(obj_in.model_dump(exclude_unset=True)).returning(self.model)
        result = await db.execute(stmt)
        await db.commit()
        updated_obj = result.scalar_one()
        
        # Update cache
        response_data = self.response_schema.model_validate(updated_obj, from_attributes=True)
        await self.set_redis_data(redis=redis, data=response_data, **matches)
        await self.invalidate_cache(redis=redis, **matches)
        return response_data
        
    async def count(self, db: AsyncSession, **kwargs: Any) -> int:
        """
        Count records matching the filter criteria.
        
        Args:
            db: Database session.
            **kwargs: Fields to filter by, must match model attributes.
            
        Returns:
            Count of matching records as an integer.
            
        Note:
            This method is currently implemented without Redis caching,
            although commented code shows how it could be implemented.
        """
        stmt = select(func.count(getattr(self.model, 'id'))).filter_by(**kwargs)
        result = await db.execute(stmt)
        count = result.scalar() or 0
        return count

    async def delete(self, db: AsyncSession, redis: Redis, **kwargs: Any) -> None:
        """
        Delete records matching the filter criteria.
        
        Args:
            db: Database session.
            redis: Redis connection object.
            **kwargs: Fields to filter by, must match model attributes.
            
        Raises:
            NoResultFound: If no matching records are found.
            
        Note:
            This method both deletes the database record and invalidates relevant caches
            to ensure data consistency.
        """
        query = delete(self.model).filter_by(**kwargs)
        result = await db.execute(query)
        await db.commit()
        
        if result.rowcount == 0:
            raise NoResultFound("No records found matching the delete criteria")
            
        await self.invalidate_cache(redis=redis, **kwargs)
        await redis.delete(self.pattern.format(**kwargs))
        return
