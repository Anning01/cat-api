from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from tortoise import Tortoise

from api.platform import console_router, developer_router
from auth.deps import AuthContext, get_auth_context
from auth.models import PlatformApiKey, PlatformCallReceipt, User, UserWallet
from models.config import AiModelConfig
from services.platform.access import create_key, developer_identity
from services.platform.calls import admit
from services.platform.receipts import call_receipt
from services.schema_compat import ensure_billing_integration_schema


async def fixture():
    user = await User.create(username='key-owner')
    await UserWallet.create(user=user, balance=20)
    common = dict(task_type=7, is_active=True, api_protocol='openai_compatible',
                  base_url='https://example.invalid', api_key='fixture-only',
                  pricing={'type':'text', 'input_price_per_1m':1, 'output_price_per_1m':2})
    allowed = await AiModelConfig.create(**common, name='Allowed', model='allowed-provider')
    denied = await AiModelConfig.create(**common, name='Denied', model='denied-provider')
    app = FastAPI()
    app.include_router(console_router, prefix='/api')
    app.include_router(developer_router, prefix='/v1')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user)
    return user, allowed, denied, app


def request_for(raw):
    return Request({'type':'http', 'headers':[(b'authorization', ('Bearer '+raw).encode())]})


async def test_key_policy_is_saved_listed_and_filters_the_authenticated_catalog():
    user, allowed, denied, app = await fixture()
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        created = (await client.post('/api/platform/keys', json={
            'name':'Selected models', 'allowed_model_ids':[f'nv-{allowed.id}'], 'expires_at':expiry.isoformat(),
        })).json()['data']
        listed = (await client.get('/api/platform/keys')).json()['data'][0]
        assert listed['allowed_model_ids'] == [f'nv-{allowed.id}']
        assert datetime.fromisoformat(listed['expires_at'].replace('Z','+00:00')) == expiry
        assert not listed['is_expired'] and 'key' not in listed
        response = await client.get('/v1/models', headers={'Authorization':'Bearer '+created['key']})
        assert [row['id'] for row in response.json()['data']] == [f'nv-{allowed.id}']
        await PlatformApiKey.filter(id=created['id']).update(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        assert (await client.get('/v1/models', headers={'Authorization':'Bearer '+created['key']})).status_code == 401
        assert (await client.get('/api/platform/keys')).json()['data'][0]['is_expired']


async def test_model_restrictions_cover_ids_aliases_and_receipts_before_any_charge():
    user, allowed, denied, _ = await fixture()
    key = await create_key(AuthContext(user=user), 'Limited', allowed_model_ids=[f'nv-{allowed.id}'])
    ctx = await developer_identity(request_for(key['key']))
    for model in (denied.id, f'nv-{denied.id}', denied.name, denied.model):
        with pytest.raises(HTTPException) as error:
            await admit(ctx, model, {'model':str(model)}, None)
        assert error.value.status_code == 403
    assert not await PlatformCallReceipt.all().exists()
    _, receipt = await admit(AuthContext(user=user), f'nv-{denied.id}', {'model':f'nv-{denied.id}'}, None)
    with pytest.raises(HTTPException) as error:
        await call_receipt(receipt.public_id, ctx)
    assert error.value.status_code == 403
    _, permitted = await admit(ctx, allowed.model, {'model':allowed.model}, None)
    assert permitted.model_config_id == allowed.id
    assert await UserWallet.get(user=user).values_list('balance', flat=True) == 20


async def test_invalid_scope_and_expiry_are_rejected_without_creating_keys():
    user, allowed, denied, app = await fixture()
    disabled = await AiModelConfig.create(name='Disabled', model='disabled', task_type=7, is_active=False,
        base_url='https://example.invalid', api_key='fixture-only')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for fields in [
            {'allowed_model_ids':[]}, {'allowed_model_ids':['invalid']},
            {'allowed_model_ids':[f'nv-{disabled.id}']}, {'allowed_model_ids':['nv-999999']},
            {'expires_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()},
            {'expires_at':'2030-01-01T12:00:00'},
        ]:
            result = await client.post('/api/platform/keys', json={'name':'Bad key', **fields})
            assert result.status_code == 422
    assert not await PlatformApiKey.all().exists()
    legacy = await create_key(AuthContext(user=user), 'Legacy-compatible')
    assert legacy['allowed_model_ids'] is None and legacy['expires_at'] is None
    assert (await developer_identity(request_for(legacy['key']))).allowed_model_ids is None


async def test_existing_keys_migrate_without_losing_or_changing_access():
    user = await User.create(username='migration-owner')
    original = await create_key(AuthContext(user=user), 'Existing')
    db = Tortoise.get_connection('default')
    await db.execute_script('ALTER TABLE account_api_keys DROP COLUMN allowed_model_ids; ALTER TABLE account_api_keys DROP COLUMN expires_at;')
    await ensure_billing_integration_schema()
    await ensure_billing_integration_schema()
    row = await PlatformApiKey.get(id=original['id'])
    assert row.allowed_model_ids is None and row.expires_at is None
    assert (await developer_identity(request_for(original['key']))).user.id == user.id
