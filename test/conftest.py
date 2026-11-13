import pytest
from tortoise import Tortoise


@pytest.fixture(autouse=True)
async def database():
    await Tortoise.init(db_url="sqlite://:memory:", modules={
        "models": ["auth.models", "models.config", "models.usage_record"],
    })
    try:
        await Tortoise.generate_schemas()
        yield
    finally:
        await Tortoise.close_connections()
