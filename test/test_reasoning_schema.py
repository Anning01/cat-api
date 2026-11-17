import os
import sqlite3
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest


def test_reasoning_upgrade_is_additive_and_repeatable(tmp_path):
    path = tmp_path / 'old-models.db'
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE ai_model_configs (id INTEGER PRIMARY KEY, thinking VARCHAR(16)); INSERT INTO ai_model_configs VALUES (1, 'enabled');")
    code = '''
import asyncio, os
from tortoise import Tortoise
from services.schema_compat import ensure_model_reasoning_schema, ensure_billing_integration_schema
async def run():
    await Tortoise.init(db_url=os.environ['DATABASE_URL'], modules={'models':['models.config']})
    await ensure_model_reasoning_schema()
    await ensure_model_reasoning_schema()
    await ensure_billing_integration_schema()
    await ensure_billing_integration_schema()
    await Tortoise.close_connections()
asyncio.run(run())
'''
    subprocess.run([sys.executable, '-c', code], check=True, env={**os.environ, 'DATABASE_URL': f'sqlite://{path}'})
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT thinking, reasoning_effort, text_api FROM ai_model_configs').fetchall() == [('enabled', None, 'chat_completions')]


@pytest.mark.asyncio
async def test_postgres_only_widens_old_thinking_column(monkeypatch):
    from services.schema_compat import ensure_model_reasoning_schema
    connection = Mock()
    connection.capabilities.dialect = 'postgres'
    connection.execute_script = AsyncMock()
    connection.execute_query_dict = AsyncMock(side_effect=[
        [{'character_maximum_length':16}], [{'character_maximum_length':64}], [{'character_maximum_length':128}], [{'character_maximum_length':None}], []])
    monkeypatch.setattr('services.schema_compat.Tortoise.get_connection', lambda _: connection)
    for _ in range(5):
        await ensure_model_reasoning_schema()
    statements = [call.args[0] for call in connection.execute_script.await_args_list]
    assert sum('ALTER COLUMN thinking TYPE VARCHAR(64)' in sql for sql in statements) == 1
    assert all('DROP' not in sql and 'DELETE' not in sql for sql in statements)


@pytest.mark.skipif(not os.environ.get('CAT_API_POSTGRES_TEST_URL'), reason='Requires an isolated local PostgreSQL test URL')
def test_real_postgres_old_reasoning_columns_upgrade_without_data_loss():
    code = r'''
import asyncio, os
from uuid import uuid4
from urllib.parse import urlsplit, unquote
import asyncpg
from tortoise import Tortoise
from services.schema_compat import ensure_model_reasoning_schema, ensure_billing_integration_schema
async def run():
    url = urlsplit(os.environ['CAT_API_POSTGRES_TEST_URL'])
    assert url.hostname in ('127.0.0.1', 'localhost', '::1')
    schema = 'reasoning_test_' + uuid4().hex
    control = await asyncpg.connect(os.environ['CAT_API_POSTGRES_TEST_URL'])
    await control.execute(f'CREATE SCHEMA "{schema}"')
    try:
        await Tortoise.init(config={'connections': {'default': {
            'engine': 'tortoise.backends.asyncpg', 'credentials': {
                'host': url.hostname, 'port': url.port or 5432, 'user': unquote(url.username),
                'password': unquote(url.password), 'database': url.path.lstrip('/'), 'schema': schema,
            }}}, 'apps': {'models': {'models': ['models.config']}}})
        db = Tortoise.get_connection('default')
        assert (await db.execute_query_dict('SELECT current_schema() AS name'))[0]['name'] == schema
        await db.execute_script("CREATE TABLE ai_model_configs (id INT PRIMARY KEY, thinking VARCHAR(16)); INSERT INTO ai_model_configs VALUES (1, 'enabled');")
        for _ in range(2):
            await ensure_model_reasoning_schema()
            await ensure_billing_integration_schema()
        assert await db.execute_query_dict('SELECT id, thinking, reasoning_effort, supports_strict_output, text_api FROM ai_model_configs') == [
            {'id': 1, 'thinking': 'enabled', 'reasoning_effort': None, 'supports_strict_output': False, 'text_api': 'chat_completions'}]
        async def width():
            return (await db.execute_query_dict("SELECT character_maximum_length AS n FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='ai_model_configs' AND column_name='thinking'"))[0]['n']
        assert await width() == 64
        await db.execute_script("ALTER TABLE ai_model_configs ALTER COLUMN thinking TYPE VARCHAR(128); UPDATE ai_model_configs SET thinking=repeat('x',100), reasoning_effort='custom-effort';")
        await ensure_model_reasoning_schema()
        assert await width() == 128
        row = (await db.execute_query_dict('SELECT thinking, reasoning_effort FROM ai_model_configs'))[0]
        assert row == {'thinking': 'x'*100, 'reasoning_effort': 'custom-effort'}
    finally:
        await Tortoise.close_connections()
        await control.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await control.close()
asyncio.run(run())
'''
    subprocess.run([sys.executable, '-c', code], check=True)
