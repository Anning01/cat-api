import asyncio
from copy import deepcopy

from httpx import ASGITransport, AsyncClient

from auth.deps import AuthContext, get_auth_context
from auth.models import User
from main import app
from models.config import AiModelConfig


async def test_model_settings_loads_all_three_dependencies_without_changing_models():
    user = await User.create(username='settings-admin',is_super_admin=True)
    pricing = {'type':'video','currency':'CNY','prices':{'480p':23},'billing_unit':'token'}
    config = await AiModelConfig.create(name='Retained model',task_type=4,task_types=[4],model='seedance-mini',
        video_model_type='seedance_2_mini',api_protocol='volcengine_ark',base_url='https://example.test/api/v3',api_key='fixture-private',pricing=deepcopy(pricing))
    app.dependency_overrides[get_auth_context] = lambda:AuthContext(user=user,is_super_admin=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            paths=['/api/config?page=1&page_size=100','/api/config/enums/all','/api/config/generation/capabilities']
            listing,enums,capabilities = [response.json() for response in await asyncio.gather(*(client.get(path) for path in paths))]
            assert [listing['code'],enums['code'],capabilities['code']] == [0,0,0]
            assert listing['data']['items'][0]['id']==config.id
            assert enums['data']['ai_task_type'] and enums['data']['image_model_type'] and enums['data']['video_model_type']
            assert capabilities['data']['image'] and capabilities['data']['video']
            assert capabilities['data']['media_processing']['resolutions']
            assert capabilities['data']['audio_recognition']['pricing']['type']=='asr'
            assert 'fixture-private' not in str([enums,capabilities])
            result=await client.patch(f'/api/config/{config.id}',json={'pricing':pricing})
            assert result.json()['code']==0
            app.dependency_overrides[get_auth_context] = lambda:AuthContext(user=user,is_super_admin=False)
            for path in paths:
                assert (await client.get(path)).json()['code']==403
            await config.refresh_from_db()
            assert config.api_key=='fixture-private' and config.pricing==pricing
            assert await AiModelConfig.all().count()==1
    finally:
        app.dependency_overrides.clear()


async def test_model_settings_save_and_clear_provider_defined_reasoning_values():
    user = await User.create(username='reasoning-admin', is_super_admin=True)
    model = await AiModelConfig.create(name='推理', task_type=7, model='upstream',
        base_url='https://vendor.invalid', api_key='fixture')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user, is_super_admin=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.patch(f'/api/config/{model.id}', json={'thinking':'provider-thinking','reasoning_effort':'provider-effort','text_api':'responses'})
            assert response.json()['code'] == 0
            await model.refresh_from_db()
            assert model.thinking == 'provider-thinking' and model.reasoning_effort == 'provider-effort'
            assert model.text_api == 'responses'
            response = await client.patch(f'/api/config/{model.id}', json={'thinking':None, 'reasoning_effort':None})
            assert response.json()['code'] == 0
            await model.refresh_from_db()
            assert model.thinking is None and model.reasoning_effort is None
    finally:
        app.dependency_overrides.clear()


async def test_public_catalog_reports_strict_output_for_studio_selection():
    from services.platform.catalog import model_catalog
    model = await AiModelConfig.create(name='Strict model', task_type=7, model='strict', supports_strict_output=True, text_api='responses',
        base_url='https://vendor.invalid', api_key='fixture', is_active=True)
    catalog = await model_catalog()
    entry = next(row for row in catalog if row['id'] == f'nv-{model.id}')
    assert entry['strict_output'] is True
    assert entry['text_api'] == 'responses'
