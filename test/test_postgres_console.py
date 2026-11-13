"""Run with CAT_API_POSTGRES_TEST_URL to verify the real PostgreSQL backend.

All fixture records live in a unique temporary schema, never the application's tables.
"""
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(not os.environ.get('CAT_API_POSTGRES_TEST_URL'), reason='Requires a local PostgreSQL test URL')
def test_postgres_console_routes_and_account_isolation():
    script = r'''
import asyncio
import os
from decimal import Decimal
from uuid import uuid4
from urllib.parse import unquote, urlsplit

import asyncpg
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from auth.deps import AuthContext, get_auth_context
from auth.models import User, UserWallet
from controllers.account import account_controller
from main import app
from models.config import AiModelConfig
from schemas.billing import StatementFilters
from services.balance import consume
from services.billing.statements import billing_statements


async def main():
    url = urlsplit(os.environ['CAT_API_POSTGRES_TEST_URL'])
    schema = 'console_test_' + uuid4().hex
    control = await asyncpg.connect(os.environ['CAT_API_POSTGRES_TEST_URL'])
    await control.execute(f'CREATE SCHEMA "{schema}"')
    try:
        await Tortoise.init(config={
            'connections': {'default': {'engine': 'tortoise.backends.asyncpg', 'credentials': {
                'host': url.hostname, 'port': url.port or 5432, 'user': unquote(url.username),
                'password': unquote(url.password), 'database': url.path.lstrip('/'), 'schema': schema,
            }}},
            'apps': {'models': {'models': ['auth.models', 'models.config', 'models.usage_record']}},
            'timezone': 'Asia/Shanghai', 'use_tz': True,
        })
        await Tortoise.generate_schemas()
        admin = await User.create(username='postgres-admin', is_super_admin=True)
        user = await User.create(username='postgres-user')
        await UserWallet.create(user=admin, balance=100)
        await account_controller.top_up(user.id, Decimal('12.12'), admin.id, 'Isolated PostgreSQL test')
        await consume(user.id, Decimal('0.123456'), strict=True)
        await AiModelConfig.create(name='Isolated test model', task_type=7, task_types=[7],
            model='test-model', base_url='https://example.invalid/v1', api_key='not-a-provider-secret',
            api_protocol='openai_compatible', is_active=True,
            pricing={'type':'text', 'currency':'CNY', 'input_price_per_1m':1, 'output_price_per_1m':2})
        app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=admin, is_super_admin=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            for path in [
                '/api/users?role=user&balance_view=low', '/api/users?balance_view=negative', '/api/users/stats',
                f'/api/users/{user.id}', f'/api/users/{user.id}/transactions', f'/api/users/{user.id}/events',
                '/api/config?page=1&page_size=20', '/api/config/enums/all', '/api/config/generation/capabilities',
                '/api/platform/catalog', '/api/platform/keys', '/api/platform/usage?days=7',
                '/api/account/orders', '/api/billing/statements', '/api/billing/mine',
            ]:
                result = (await client.get(path)).json()
                assert result['code'] == 0, (path, result.get('message'))
            row = (await client.get(f'/api/users/{user.id}')).json()['data']
            assert Decimal(row['balance']) == Decimal('11.996544')
            created = (await client.post('/api/users', json={
                'username':'postgres-created', 'password':'isolated-test-password', 'nickname':'Test',
            })).json()
            assert created['code'] == 0, created.get('message')
            disabled = (await client.patch(f'/api/users/{user.id}', json={'status':0})).json()
            assert disabled['code'] == 0 and disabled['data']['status'] == 0
            ledger = await billing_statements.list(StatementFilters(account_user_id=user.id), 1, 20)
            assert ledger['summary']['total_cost'] == '0.123456'
            exported = ''.join([chunk async for chunk in billing_statements.export(StatementFilters(account_user_id=user.id))])
            assert '0.123456' in exported
            app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user)
            assert (await client.get(f'/api/users/{admin.id}/transactions')).json()['code'] == 403
            mine = (await client.get(f'/api/billing/mine?account_user_id={admin.id}')).json()['data']
            assert mine['summary']['total_cost'] == '0.123456'
        print('PostgreSQL routes, decimals, filters, audit trail, CSV and account isolation passed.')
    finally:
        app.dependency_overrides.clear()
        await Tortoise.close_connections()
        await control.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await control.close()


asyncio.run(main())
'''
    subprocess.run([sys.executable, '-c', script], check=True)
