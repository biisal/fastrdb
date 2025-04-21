import pytest

from tests.db.models.user import User
from schema import UserCreate, UserResponse, UserUpdate

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from fastrdb import FastRDB
from faker import Faker
import orjson


fake = Faker()

redis_pattern = "user:email:{email}"
redis_list_pattern = "user:list:{limit}:{page}"
redis_invalidate_pattern = ""
redis_exp = 60


crud = FastRDB[User , UserCreate , UserUpdate , UserResponse](
    model=User ,
    response_schema=UserResponse,
    pattern=redis_pattern, 
    list_pattern=redis_list_pattern, 
    exp=3600, 
    invalidate_pattern_prefix=redis_invalidate_pattern)


def random_user() -> UserCreate:
    return UserCreate(name=fake.name(),email=fake.email(),bio=fake.text(),is_active=True)

@pytest.mark.asyncio
async def test_create(db : AsyncSession , redis : Redis):
    user = random_user()
    created_user = await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    assert created_user.name == user.name
    assert created_user.email == user.email
    assert created_user.bio == user.bio
    assert created_user.is_active == user.is_active
    key = redis_pattern.format(email=user.email)
    redis_data = await redis.get(key)
    assert redis_data != None
    redis_data = orjson.loads(redis_data)
    assert redis_data["name"] == user.name
    assert redis_data["email"] == user.email
    assert redis_data["bio"] == user.bio
    assert redis_data["is_active"] == user.is_active

@pytest.mark.asyncio
async def test_create_multi(db : AsyncSession , redis : Redis):
    users = [random_user() for _ in range(10)]
    created_users = await crud.create_multi(db=db ,redis=redis , instances=users)
    assert len(created_users) == 10
    assert created_users[0].name == users[0].name

@pytest.mark.asyncio
async def test_get(db : AsyncSession , redis : Redis):
    user = random_user()
    created_user = await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    get_user = await crud.get(db=db , redis=redis , email=user.email)
    assert get_user != None
    assert created_user.name == get_user.name
    assert created_user.email == get_user.email
    assert created_user.bio == get_user.bio
    assert created_user.is_active == get_user.is_active

    key = redis_pattern.format(email=user.email)
    redis_data = await redis.get(key)
    assert redis_data != None
    redis_data = orjson.loads(redis_data)
    assert redis_data["name"] == user.name
    assert redis_data["email"] == user.email
    assert redis_data["bio"] == user.bio
    assert redis_data["is_active"] == user.is_active

@pytest.mark.asyncio
async def test_get_multi(db: AsyncSession , redis: Redis):
    for _ in range(10):
        user = random_user()
        await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    users = await crud.get_multi(db=db , redis=redis , limit=5 , page=1)
    assert len(users) == 5

    key = redis_list_pattern.format(limit=5 , page=1)
    redis_data = await redis.get(key)
    assert redis_data != None
    redis_data = orjson.loads(redis_data)
    assert len(redis_data) == 5

@pytest.mark.asyncio
async def test_update(db: AsyncSession , redis: Redis):
    user = random_user()
    created_user = await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    user.bio = fake.text()
    updated_user = await crud.update(db=db , redis=redis , obj_in=UserUpdate(bio=user.bio) , email=user.email)
    new_updated_user = await crud.get(db=db , redis=redis , email=user.email)
    assert updated_user != None
    assert new_updated_user != None
    assert new_updated_user.name == created_user.name
    assert new_updated_user.email == created_user.email
    assert new_updated_user.bio == updated_user.bio
    assert new_updated_user.bio != created_user.bio
    assert new_updated_user.is_active == created_user.is_active


@pytest.mark.asyncio
async def test_delete(db: AsyncSession , redis: Redis):
    user = random_user()
    await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    deleted_respondse = await crud.delete(db=db , redis=redis , email=user.email)
    assert deleted_respondse == None
    
    key = redis_pattern.format(email=user.email)
    redis_data = await redis.get(key)
    assert redis_data == None

@pytest.mark.asyncio
async def test_count(db: AsyncSession , redis: Redis):
    for _ in range(10):
        user = random_user()
        await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    count = await crud.count(db=db)
    assert count == 10

@pytest.mark.asyncio
async def test_pagination(db: AsyncSession , redis: Redis):
    users = [await crud.create(db=db , redis=redis , obj_in=user , email=user.email) for user in [random_user() for _ in range(20)]]
    paginated = crud.paginate(data=users, limit=10 , page=1)
    assert paginated != None
    assert paginated.limit == 10
    assert paginated.page == 1
    assert len(paginated.data) == 20

