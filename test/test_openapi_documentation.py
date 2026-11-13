import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from tortoise import Tortoise

from api.platform import console_router
from auth.deps import AuthContext, get_auth_context
from auth.models import User
from config import settings
from main import developer_api
from models.config import GeneralConfig
from services.platform.docs_settings import DocumentationSettings, documentation_settings, with_documentation_frame
from services.platform.openapi import public_openapi
from services.schema_compat import ensure_billing_integration_schema


def walk(value):
    yield value
    if isinstance(value,dict):
        for item in value.values():yield from walk(item)
    if isinstance(value,list):
        for item in value:yield from walk(item)


def test_openapi_has_complete_public_contract_and_apifox_folders():
    document=public_openapi(developer_api)
    assert document['openapi']=='3.1.0'
    assert len(document['paths'])==24
    assert document['paths']['/api/v3/contents/generations/tasks']['post']['x-apifox-folder']=='视频/Seedance'
    assert document['paths']['/v2/video_generation']['post']['x-apifox-folder']=='视频/MiniMax'
    assert document['paths']['/api/v1/services/aigc/video-generation/video-synthesis']['post']['x-apifox-folder']=='视频/Wan3'
    assert document['paths']['/api/v3/images/generations']['post']['x-apifox-folder']=='图片/Seedream'
    assert document['paths']['/images/generations']['post']['x-apifox-folder']=='图片/OpenAI 兼容'
    assert document['paths']['/images']['post']['x-apifox-folder']=='图片/OpenRouter'
    assert document['paths']['/chat/completions']['post']['x-apifox-folder'].startswith('LLM/')
    ids=[]
    for path,methods in document['paths'].items():
        assert '/platform/keys' not in path and '/studio/' not in path
        for method,operation in methods.items():
            ids.append(operation['operationId'])
            assert operation['security']
            assert operation['tags']==[operation['x-apifox-folder']]
            assert operation['responses']['401']['content']['application/json']['schema']
            if method=='post':
                assert operation['requestBody']['content']['application/json']['examples']
            if '200' in operation['responses']:
                media=operation['responses']['200']['content']['application/json']
                assert media['schema'] and 'example' in media
    assert len(ids)==len(set(ids))
    for item in walk(document):
        if isinstance(item,dict) and '$ref' in item:
            target=document
            for part in item['$ref'].removeprefix('#/').split('/'):
                target=target[part.replace('~1','/').replace('~0','~')]
    assert 'text/event-stream' in document['paths']['/chat/completions']['post']['responses']['200']['content']
    asr=document['paths']['/api/v3/auc/bigmodel/query']['post']
    assert any(p['name']=='X-Api-Request-Id' and p['required'] for p in asr['parameters'])
    assert {'SeedASRKey':[]} in asr['security']
    assert document['paths']['/videos/{identifier}/content']['get']['responses']['307']['headers']['Location']


def test_openapi_examples_match_runtime_models():
    from fastapi.openapi.models import OpenAPI
    from schemas.platform_chat import ChatRequest
    from services.platform.images import ImageRequest
    from services.platform.videos import VideoRequest
    from services.platform.temporary_media import UploadSpec
    from schemas.platform_billing import PlatformAccountOut, PlatformReceiptOut
    document=public_openapi(developer_api)
    OpenAPI.model_validate(document)
    models={"/chat/completions":ChatRequest,"/images/generations":ImageRequest,"/images/edits":ImageRequest,
            "/images":ImageRequest,"/api/v3/images/generations":ImageRequest,"/videos":VideoRequest,"/media/uploads":UploadSpec}
    for path,model in models.items():
        examples=document['paths'][path]['post']['requestBody']['content']['application/json']['examples']
        for example in examples.values():model.model_validate(example['value'])
    for path,model in [('/account',PlatformAccountOut),('/requests',PlatformReceiptOut)]:
        model.model_validate(document['paths'][path]['get']['responses']['200']['content']['application/json']['example'])


@pytest.mark.parametrize('url', ['javascript:alert(1)','http://example.com/','https://user:secret@example.com/',
    'https://127.0.0.1/','https://localhost/','https://docs.example.com/?api_key=secret'])
def test_documentation_url_must_be_public_without_credentials(url):
    with pytest.raises(ValidationError):DocumentationSettings(url=url)


async def test_documentation_configuration_is_public_read_admin_write():
    admin=await User.create(username='docs-admin',is_super_admin=True)
    user=await User.create(username='docs-reader')
    app=FastAPI();app.include_router(console_router,prefix='/api')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/platform/documentation')).json()['data']=={'url':''}
        app.dependency_overrides[get_auth_context]=lambda:AuthContext(user=user)
        assert (await client.patch('/api/platform/documentation',json={'url':'https://rjvutktiur.apifox.cn/'})).status_code==403
        app.dependency_overrides[get_auth_context]=lambda:AuthContext(user=admin,is_super_admin=True)
        response=await client.patch('/api/platform/documentation',json={'url':'https://rjvutktiur.apifox.cn/'})
        assert response.status_code==200
        assert (await GeneralConfig.get(id=1)).api_docs_url=='https://rjvutktiur.apifox.cn/'
        app.dependency_overrides.clear()
        assert (await client.get('/api/platform/documentation')).json()['data']['url']=='https://rjvutktiur.apifox.cn/'
        exported=await client.get('/api/platform/openapi-export')
        assert exported.status_code==200 and exported.headers['content-disposition'].endswith('"cat-api-openapi.json"')
        assert len(exported.json()['paths'])==24
        assert 'docs-admin' not in exported.text


async def test_clearing_configuration_disables_environment_default(monkeypatch):
    monkeypatch.setattr(settings,'API_DOCUMENTATION_URL','https://docs.example.com/')
    assert (await documentation_settings()).url=='https://docs.example.com/'
    await GeneralConfig.create(id=1,api_docs_url='')
    assert (await documentation_settings()).url==''


def test_csp_adds_only_configured_frame_origin():
    policy="default-src 'self'; frame-src https://challenges.cloudflare.com; frame-ancestors 'none'; script-src 'self'"
    result=with_documentation_frame(policy,'https://rjvutktiur.apifox.cn')
    assert "frame-src https://challenges.cloudflare.com https://rjvutktiur.apifox.cn;" in result
    assert "frame-ancestors 'none'" in result and "script-src 'self'" in result
    assert with_documentation_frame(policy,'')==policy
    assert with_documentation_frame("default-src 'self';",'https://docs.example.com')=="default-src 'self'; frame-src 'self' https://docs.example.com;"


async def test_documentation_schema_upgrade_preserves_existing_configuration():
    await GeneralConfig.create(id=1,prompt_language='zh')
    db=Tortoise.get_connection('default')
    await db.execute_script('ALTER TABLE general_configs DROP COLUMN api_docs_url;')
    await ensure_billing_integration_schema();await ensure_billing_integration_schema()
    config=await GeneralConfig.get(id=1)
    assert config.prompt_language=='zh' and config.api_docs_url is None


async def test_html_security_headers_allow_only_documentation_frame_origin():
    from fastapi.responses import HTMLResponse
    from services.security.headers import SecurityHeadersMiddleware
    await GeneralConfig.create(id=1,api_docs_url='https://rjvutktiur.apifox.cn/')
    app=FastAPI()
    app.add_middleware(SecurityHeadersMiddleware,
        content_security_policy="default-src 'self'; frame-src https://challenges.cloudflare.com; frame-ancestors 'none'",
        docs_content_security_policy="default-src 'self'")
    @app.get('/')
    async def html():return HTMLResponse('<html><body>test</body></html>')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/')
    assert "frame-src https://challenges.cloudflare.com https://rjvutktiur.apifox.cn;" in response.headers['content-security-policy']
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['x-frame-options']=='DENY'
