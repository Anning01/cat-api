"""VoiceDesign contract tests use local WAV fixtures; no real supplier calls or payments."""
import base64
from decimal import Decimal
import io
import json
import wave

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from auth.models import PlatformCallReceipt, User, UserWallet
from controllers.config import ai_model_config_controller
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from schemas.config import AiModelConfigCreate, AiModelConfigPatch
from services.platform.access import create_key
from services.platform.calls import settle
from services.platform.voice_design import MODEL, voice_cost, wav_usage
from test.test_sdk_contract import sdk_api


def wav_data(frames=20001, rate=8000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b'\x00\x00' * frames)
    return base64.b64encode(output.getvalue()).decode()


def completion(audio=None):
    return {'id':'voice-fixture','object':'chat.completion','created':1,'model':MODEL,
        'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':None,
            'audio':{'data':wav_data() if audio is None else audio}}}],
        'usage':{'prompt_tokens':12345,'completion_tokens':98765,'total_tokens':111110}}


async def channel():
    return await AiModelConfig.create(task_type=12,task_types=[12],name='MiMo VoiceDesign',public_alias='mimo-voice-design',
        model=MODEL,api_protocol='openai_compatible',base_url='https://vendor.example/v1',api_key='upstream-fixture',
        is_active=True,pricing={'type':'voice_design','billing_unit':'second','price_per_second':0.012,'discount':0.8})


def request(model):
    return {'model':model,'messages':[{'role':'user','content':'沉稳的年轻男声'},
        {'role':'assistant','content':'你好，这是试听台词。'}],'audio':{'format':'wav'},'stream':False}


async def post(sdk, model, *, key='voice-once', payload=None):
    return await sdk._client.post('https://platform.example/v1/chat/completions',json=payload or request(model),
        headers={'Authorization':f'Bearer {sdk.api_key}','Idempotency-Key':key})


async def test_voice_catalog_forward_duration_receipt_and_idempotency(sdk_api):
    sdk,state,_ = sdk_api
    config=await channel()
    state.failure=200,json.dumps(completion()).encode(),{'content-type':'application/json','x-request-id':'supplier-id'}
    listed=(await sdk.models.list()).data
    item=next(m.model_dump() for m in listed if m.id==config.public_alias)
    assert item['kinds']==['voice_design'] and item['task_types']==[12]
    assert item['pricing']=={'type':'voice_design','billing_unit':'second','currency':'CNY','price_per_second':0.012,'discount':0.8}
    assert 'upstream-fixture' not in json.dumps(item)
    wallet=await UserWallet.get()
    original=wallet.balance
    reply=await post(sdk,config.public_alias)
    assert reply.status_code==200 and reply.json()==completion()
    assert reply.headers['x-request-id']=='supplier-id'
    receipt_id=reply.headers['x-cat-request-id']
    sent=json.loads(state.seen[-1].content)
    assert sent['model']==MODEL and sent['audio']=={'format':'wav'} and sent['stream'] is False
    assert sent['messages']==request(config.public_alias)['messages']
    r=await PlatformCallReceipt.get(public_id=receipt_id)
    assert r.usage=={'seconds':2.500125,'frames':20001,'sample_rate':8000}
    assert r.state=='completed'
    record=await ModelUsageRecord.get(id=r.usage_record_id)
    assert record.task_type==12 and record.billing_type=='voice_design' and record.cost==Decimal('0.024001')
    await wallet.refresh_from_db()
    assert wallet.balance==original-record.cost
    receipt=await sdk._client.get(f'https://platform.example/v1/requests/{receipt_id}',headers={'Authorization':f'Bearer {sdk.api_key}'})
    assert receipt.json()['usage']['seconds']==2.500125
    assert receipt.json()['settlement']=={'status':'settled','amount':'0.024001','currency':'CNY'}
    assert receipt.json()['pricing']['price_per_second']==0.012
    assert (await post(sdk,config.public_alias)).status_code==409
    assert len(state.seen)==1
    await settle(r.id)
    assert await ModelUsageRecord.all().count()==1
    user=await User.create(username='other-voice-user')
    other=(await create_key(AuthContext(user=user),'other'))['key']
    cross=await sdk._client.get(f'https://platform.example/v1/requests/{receipt_id}',headers={'Authorization':f'Bearer {other}'})
    assert cross.status_code==404
    await AiModelConfig.filter(id=config.id).update(is_active=False)
    assert config.public_alias not in [m.id for m in (await sdk.models.list()).data]
    assert (await post(sdk,f'nv-{config.id}',key='disabled')).status_code==404


@pytest.mark.parametrize('audio', ['invalid base64',base64.b64encode(b'not wav').decode(),wav_data()[:-12]])
async def test_unmeasurable_audio_preserves_result_for_client_without_charging(sdk_api,audio):
    sdk,state,_=sdk_api
    config=await channel()
    result=completion(audio)
    state.failure=200,json.dumps(result).encode(),{'content-type':'application/json'}
    reply=await post(sdk,f'nv-{config.id}')
    assert reply.status_code==200 and reply.json()==result
    r=await PlatformCallReceipt.get()
    assert r.state=='review' and r.usage is None
    assert await ModelUsageRecord.all().count()==0
    assert (await UserWallet.get()).balance==20


@pytest.mark.parametrize('change', [{'stream':True},{'audio':{'format':'mp3'}},{'audio':{'format':'wav','voice':'forbidden'}},
    {'messages':[{'role':'user','content':'missing preview'}]},{'n':2},{'modalities':['text']}])
async def test_invalid_voice_request_never_reaches_supplier(sdk_api,change):
    sdk,state,_=sdk_api
    config=await channel()
    reply=await post(sdk,f'nv-{config.id}',payload={**request(f'nv-{config.id}'),**change})
    assert reply.status_code==422 and not state.seen
    assert await PlatformCallReceipt.all().count()==0


@pytest.mark.parametrize('price', [None,True,-1,float('inf'),'0.01'])
async def test_config_rejects_invalid_voice_price(price):
    with pytest.raises(HTTPException):
        await ai_model_config_controller.create(AiModelConfigCreate(task_type=12,task_types=[12],name='invalid',
            model=MODEL,api_protocol='openai_compatible',base_url='https://vendor.example/v1',api_key='fixture',is_active=True,
            pricing={'type':'voice_design','billing_unit':'second','price_per_second':price}))


async def test_admin_can_configure_price_and_next_catalog_read_changes(sdk_api):
    sdk,_,_=sdk_api
    config=await channel()
    await ai_model_config_controller.patch(config.id,AiModelConfigPatch(pricing={'type':'voice_design','billing_unit':'second','price_per_second':0.02}))
    item=next(m.model_dump() for m in (await sdk.models.list()).data if m.id==config.public_alias)
    assert item['pricing']['price_per_second']==0.02
    assert voice_cost(wav_usage(completion()),item['pricing'])==Decimal('0.050003')


async def test_measured_voice_recovery_uses_original_price_and_never_discards_audio(sdk_api,monkeypatch):
    from services.platform import calls
    sdk,state,_=sdk_api
    config=await channel()
    state.failure=200,json.dumps(completion()).encode(),{'content-type':'application/json'}
    original_settle=calls.settle
    async def unavailable(receipt_id):
        raise RuntimeError('temporary settlement failure')
    monkeypatch.setattr(calls,'settle',unavailable)
    reply=await post(sdk,f'nv-{config.id}')
    assert reply.status_code==200 and reply.json()==completion()
    receipt=await PlatformCallReceipt.get()
    assert receipt.state=='measured' and await ModelUsageRecord.all().count()==0
    await AiModelConfig.filter(id=config.id).update(pricing={'type':'voice_design','billing_unit':'second','price_per_second':99})
    await original_settle(receipt.id)
    await original_settle(receipt.id)
    records=await ModelUsageRecord.all()
    assert len(records)==1 and records[0].cost==Decimal('0.024001')


@pytest.mark.parametrize('status,state_name', [(400,'rejected'),(503,'review')])
async def test_voice_supplier_failure_has_receipt_and_no_automatic_retry(sdk_api,status,state_name):
    sdk,state,_=sdk_api
    config=await channel()
    state.failure=status,b'{"error":{"message":"supplier failed"}}',{'content-type':'application/json'}
    reply=await post(sdk,f'nv-{config.id}')
    assert reply.status_code==status and reply.headers['x-cat-request-id']
    receipt=await PlatformCallReceipt.get()
    assert receipt.state==state_name and len(state.seen)==1
    assert await ModelUsageRecord.all().count()==0


async def test_voice_key_model_restriction_prevents_supplier_call(sdk_api):
    sdk,state,models=sdk_api
    config=await channel()
    wallet=await UserWallet.get()
    user=await User.get(id=wallet.user_id)
    limited=(await create_key(AuthContext(user=user),'limited',allowed_model_ids=[f'nv-{models[0].id}']))['key']
    reply=await sdk._client.post('https://platform.example/v1/chat/completions',json=request(f'nv-{config.id}'),
        headers={'Authorization':f'Bearer {limited}'})
    assert reply.status_code==403 and not state.seen
    assert await PlatformCallReceipt.all().count()==0
