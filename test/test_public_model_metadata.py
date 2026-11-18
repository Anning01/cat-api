"""Public catalog contract: real identifiers, explicit modalities and scoped routing."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from auth.deps import AuthContext
from auth.models import User,UserWallet
from models.config import AiModelConfig
from services.platform.access import create_key
from services.platform.calls import admit
from services.platform.catalog import model_catalog
from api.platform import developer_router


async def model(name,provider,task,**extra):
    return await AiModelConfig.create(name=name,model=provider,task_type=task,task_types=[task],is_active=True,
        api_key='private-key',base_url='https://private.example',**extra)


async def test_generic_model_list_has_standard_modalities_and_no_admin_nickname():
    text=await model('我的自定义昵称','deepseek-flash',7,public_alias='deepseek-flash')
    image=await model('优惠渠道','gpt-image-2.6',2,image_model_type='gpt_image_2_6')
    voice=await model('随便起的昵称','mimo-v2.5-tts-voicedesign',12,public_alias='mimo-v2.5-tts-voicedesign')
    asr=await model('识别','volc.seedasr.auc',9,api_protocol='volcengine_openspeech')
    enhance=await model('增强','enhance-video-generative',8,api_protocol='volcengine_mediakit')
    user=await User.create(username='generic-client')
    token=(await create_key(AuthContext(user=user),'standard'))['key']
    app=FastAPI();app.include_router(developer_router,prefix='/v1')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer '+token}) as client:
        result=(await client.get('/v1/models')).json()
        entries={row['id']:row for row in result['data']}
        assert list(entries)==['deepseek-flash','gpt-image-2.6','mimo-v2.5-tts-voicedesign','volc.seedasr.auc','enhance-video-generative']
        assert entries['deepseek-flash']['architecture']['modality']=='text->text'
        assert entries['gpt-image-2.6']['output_modalities']==['image']
        assert entries['mimo-v2.5-tts-voicedesign']['output_modalities']==['audio']
        assert entries['volc.seedasr.auc']['architecture']['modality']=='audio->text'
        assert entries['enhance-video-generative']['architecture']['modality']=='video->video'
        for row in result['data']:
            assert row['name']==row['id'] and 'alias' not in row
            assert row['object']=='model' and row['owned_by']=='cat-api'
            assert row['output_modalities']==row['architecture']['output_modalities']
            assert row['legacy_id'].startswith('nv-')
        for forbidden in ('我的自定义昵称','优惠渠道','随便起的昵称','private-key','private.example'):
            assert forbidden not in str(result)
        assert '/v1/audio/transcriptions' not in entries['volc.seedasr.auc']['endpoints']
        legacy=(await client.get('/v1/models',headers={'X-NovelVids-Capabilities':'pixel_tier_images'})).json()['data']
        assert legacy[0]['id']==f'nv-{text.id}'
        explicit=(await client.get('/v1/models?identifier=legacy')).json()['data']
        assert [r['id'] for r in explicit]==[f'nv-{m.id}' for m in (text,image,voice,asr,enhance)]


async def test_public_aliases_keep_discount_channels_and_scoped_routing():
    first=await model('常规渠道','gpt-image-2.6-sunburst',2,public_alias='gpt-image-2.6-sunburst')
    second=await model('任意后台昵称','gpt-image-2.6-sunburst',2,public_alias='gpt-image-2.6-sunburst-discount')
    user=await User.create(username='scoped-public-client');await UserWallet.create(user=user,balance=10)
    ctx=AuthContext(user=user,allowed_model_ids=frozenset([f'nv-{second.id}']))
    key=(await create_key(ctx,'scoped',allowed_model_ids=[f'nv-{second.id}']))['key']
    app=FastAPI();app.include_router(developer_router,prefix='/v1')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        listed=(await client.get('/v1/models',headers={'Authorization':'Bearer '+key})).json()['data']
        assert len(listed)==1 and listed[0]['id']=='gpt-image-2.6-sunburst-discount'
        assert listed[0]['name']==listed[0]['id'] and listed[0]['legacy_id']==f'nv-{second.id}'
        config,_=await admit(ctx,listed[0]['id'],{},None,kind='image',validate=lambda config,body:{})
        assert config.id==second.id and config.model=='gpt-image-2.6-sunburst'
        assert '任意后台昵称' not in str(listed)


async def test_private_endpoint_is_never_published_as_a_model_name():
    await model('豆包 Seed-Evolving','ep-private',7)
    await model('unknown nickname','ep-unidentified',7)
    from services.platform.model_metadata import public_models
    rows=public_models(await model_catalog())
    assert [r['id'] for r in rows]==['doubao-seed-evolving']
    assert rows[0]['input_modalities']==['text','image','video']
    assert rows[0]['output_modalities']==['text']
    assert 'ep-' not in str(rows) and 'unknown nickname' not in str(rows)
