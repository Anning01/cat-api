from datetime import datetime, timedelta, timezone
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import User, UserWallet, PlatformCallReceipt, PlatformVideoJob
from controllers.config import ai_model_config_controller
from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate, AiModelConfigPatch
from services.platform.access import create_key
from services.platform.calls import admit
from services.platform.catalog import model_catalog
from services.platform.model_aliases import ensure_model_alias, ensure_model_aliases
from services.platform.native import find_task, routing_hash
from services.platform.receipts import call_receipt


async def image(name='Doubao Seedream 5.5'):
    return await ai_model_config_controller.create(AiModelConfigCreate(name=name,task_type=2,task_types=[2],
        model='doubao-seedream-5-5-261028',base_url='https://upstream.example/api/v3',api_key='private-fixture',
        api_protocol='volcengine_ark',image_model_type='seedream_5_5',is_active=True,concurrency=10,
        pricing={'type':'image','currency':'CNY','billing_unit':'pixel_tier','prices':{'low':.13,'high_capped':.23}}))


async def test_aliases_are_readable_unique_and_stable_after_rename_and_price_changes():
    first=await image()
    second=await image('Seedream 5.5 second channel')
    assert first.public_alias=='seedream-5.5'
    assert second.public_alias==f'seedream-5.5-channel-{second.id}'
    third=await image('Seedream 5.5（优惠渠道）')
    assert third.public_alias=='seedream-5.5-discount'
    await ai_model_config_controller.patch(first.id,AiModelConfigPatch(name='Another display name',is_active=False,
        pricing={**first.pricing,'discount':.8}))
    await ensure_model_aliases();await ensure_model_aliases()
    assert (await AiModelConfig.get(id=first.id)).public_alias=='seedream-5.5'
    assert (await AiModelConfig.get(id=second.id)).public_alias==second.public_alias


async def test_catalog_mode_and_key_scope_remain_backward_compatible():
    first=await image();second=await image('Other channel')
    user=await User.create(username='alias-reader');await UserWallet.create(user=user,balance=10)
    key=await create_key(AuthContext(user=user),'limited',allowed_model_ids=[f'nv-{first.id}'])
    app=FastAPI();app.include_router(developer_router,prefix='/v1')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer '+key['key']}) as client:
        legacy=(await client.get('/v1/models')).json()['data']
        assert [r['id'] for r in legacy]==[f'nv-{first.id}']
        assert legacy[0]['alias']=='seedream-5.5'
        readable=(await client.get('/v1/models?identifier=alias')).json()['data']
        assert [r['id'] for r in readable]==['seedream-5.5']
        assert readable[0]['legacy_id']==f'nv-{first.id}'
        denied=await client.post('/v1/images/generations',json={'model':second.public_alias,'prompt':'must never reach supplier'})
        assert denied.status_code==403
    assert not await PlatformCallReceipt.all().exists()
    assert (await UserWallet.get(user=user)).balance==10


async def test_alias_and_legacy_calls_resolve_the_same_config_and_receipt_identity():
    model=await AiModelConfig.create(name='DeepSeek',model='deepseek-flash',task_type=7,is_active=True,concurrency=10,
        base_url='https://private.example/v1',api_key='private-fixture',pricing={'type':'text','input_price_per_1m':1,'output_price_per_1m':2})
    await ensure_model_alias(model)
    assert model.public_alias=='deepseek-flash'
    user=await User.create(username='alias-caller');await UserWallet.create(user=user,balance=10)
    ctx=AuthContext(user=user,allowed_model_ids=frozenset([f'nv-{model.id}']))
    for value in [model.public_alias,f'nv-{model.id}']:
        config,receipt=await admit(ctx,value,{'model':value},None)
        assert config.id==model.id
        result=await call_receipt(receipt.public_id,ctx)
        assert result.model==f'nv-{model.id}'
        assert result.model_alias=='deepseek-flash' and result.model_name=='DeepSeek'


async def test_native_query_accepts_alias_and_preserves_ownership():
    model=await AiModelConfig.create(name='Seedance mini（优惠渠道）',model='ep-private-endpoint',task_type=4,is_active=True,
        video_model_type='seedance_2_mini',api_protocol='volcengine_ark',base_url='https://private.example/api/v3',api_key='private-fixture')
    await ensure_model_alias(model)
    assert model.public_alias=='seedance-2.0-mini-discount'
    user=await User.create(username='task-owner');other=await User.create(username='other-owner')
    receipt=await PlatformCallReceipt.create(public_id='11111111-1111-4111-8111-111111111111',dedup_key='alias-task',payload_hash='fixture',
        account_user_id=user.id,user_id=user.id,model_config_id=model.id,model_name=model.name,model=model.model,pricing={},provider_id='original-task')
    await PlatformVideoJob.create(receipt=receipt,route_hash=routing_hash(model),inputs={'native_protocol':'volcengine_ark'})
    result=await find_task(AuthContext(user=user),'original-task',['volcengine_ark'],model.public_alias)
    assert result[0].id==receipt.id
    with pytest.raises(HTTPException) as error:await find_task(AuthContext(user=other),'original-task',['volcengine_ark'],model.public_alias)
    assert error.value.status_code==404


async def test_alias_upgrade_keeps_existing_model_fields():
    from tortoise import Tortoise
    from services.schema_compat import ensure_billing_integration_schema
    row=await AiModelConfig.create(name='Private vendor',model='ep-secret-endpoint',task_type=7,api_key='private-fixture',base_url='https://private.example')
    db=Tortoise.get_connection('default')
    sql=(await db.execute_query_dict("SELECT sql FROM sqlite_master WHERE name='ai_model_configs'"))[0]['sql']
    import re
    old_sql,count=re.subn(r'\s*"public_alias"[^,\n]+,?\n','\n',sql)
    assert count==1
    columns=[r['name'] for r in await db.execute_query_dict('PRAGMA table_info(ai_model_configs)') if r['name']!='public_alias']
    quoted=','.join('"'+name+'"' for name in columns)
    await db.execute_script('ALTER TABLE ai_model_configs RENAME TO alias_test_current;'+old_sql+';'+
        'INSERT INTO ai_model_configs ('+quoted+') SELECT '+quoted+' FROM alias_test_current; DROP TABLE alias_test_current;')
    await ensure_billing_integration_schema();await ensure_model_aliases();await ensure_model_aliases()
    updated=await AiModelConfig.get(id=row.id)
    assert updated.public_alias=='private-vendor'
    assert updated.api_key==row.api_key and updated.model==row.model
    assert updated.base_url==row.base_url and updated.concurrency==row.concurrency


async def test_generated_alias_does_not_steal_existing_raw_model_names():
    existing=await AiModelConfig.create(name='Legacy vendor channel',model='seedream-5.5',task_type=2,base_url='https://legacy.example',api_key='fixture-only')
    model=await image()
    assert model.public_alias==f'seedream-5.5-channel-{model.id}'
    await AiModelConfig.filter(id=model.id).update(public_alias='')
    model=await AiModelConfig.get(id=model.id)
    assert await ensure_model_alias(model)==f'seedream-5.5-channel-{model.id}'
