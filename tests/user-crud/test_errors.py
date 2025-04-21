import pytest
from sqlalchemy.exc import  IntegrityError, NoResultFound

from tests.db.models.user import User
from schema import UserCreate, UserResponse, UserUpdate

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from fastrdb import FastRDB
from faker import Faker
# import orjson


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
async def test_not_found_error(db : AsyncSession , redis : Redis):
    with pytest.raises(NoResultFound):
        await crud.get(db=db , redis=redis , email=fake.email())

@pytest.mark.asyncio
async def test_create_duplicate_error(db : AsyncSession , redis : Redis):
    user = random_user()
    await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
    with pytest.raises(IntegrityError):
        await crud.create(db=db , redis=redis , obj_in=user , email=user.email)
