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
