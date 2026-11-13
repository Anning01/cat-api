import pytest
from tortoise import Tortoise
from cryptography.fernet import Fernet
from config import settings


@pytest.fixture(autouse=True)
async def database(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, 'API_KEY_ENCRYPTION_KEY', key)
    monkeypatch.setenv('API_KEY_ENCRYPTION_KEY', key)
    await Tortoise.init(db_url="sqlite://:memory:", modules={
        "models": ["auth.models", "models.config", "models.usage_record"],
    }, timezone=settings.TIMEZONE)
    try:
        await Tortoise.generate_schemas()
        yield
    finally:
        await Tortoise.close_connections()
