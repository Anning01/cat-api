"""Native wire contracts through local mocked suppliers; no live credentials or paid calls."""
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from api.platform import developer_router
from api.native import router as native_router
from auth.deps import AuthContext
from auth.models import PlatformCallReceipt, PlatformVideoJob, User, UserWallet
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.platform.access import create_key
from services.platform.http_contract import DEVELOPER_EXCEPTION_HANDLERS

CASES = [
    ('volcengine_ark', '/api/v3/contents/generations/tasks', '/api/v3/contents/generations/tasks/up-task', 4),
    ('minimax', '/v2/video_generation', '/v2/query/video_generation/up-task', 4),
    ('dashscope', '/api/v1/services/aigc/video-generation/video-synthesis', '/api/v1/tasks/up-task', 4),
    ('autodl', '/api/v1/comfyui/comfyui_workflow/workflow', '/api/v1/comfyui/comfyui_workflow/result/up-task', 4),
    ('volcengine_mediakit', '/api/v1/tools/enhance-video-generative', '/api/v1/tasks/up-task', 8),
    ('volcengine_openspeech', '/api/v3/auc/bigmodel/submit', '/api/v3/auc/bigmodel/query', 9),
]


@pytest.fixture
async def native_api(monkeypatch):
    user = await User.create(username='native-owner', password_hash='!')
    await UserWallet.create(user=user, balance=100)
    token = (await create_key(AuthContext(user=user), 'native'))['key']
    app = FastAPI(exception_handlers=DEVELOPER_EXCEPTION_HANDLERS)
    app.include_router(developer_router, prefix='/v1')
    app.include_router(native_router)
    state = SimpleNamespace(seen=[], submitted=None, completed=None, response_headers={}, query=False)
    original = httpx.AsyncClient
    async def dispatch(req):
        if req.url.host == 'platform.example':
            return await httpx.ASGITransport(app=app).handle_async_request(req)
        assert req.url.host == 'native.example'
        await req.aread()
        state.seen.append(req)
        payload = state.completed if state.query else state.submitted
        return httpx.Response(200, content=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'content-type':'application/json', 'x-request-id':'supplier-id',
                     'x-ratelimit-remaining-requests':'42', **state.response_headers})
    transport = httpx.MockTransport(dispatch)
    class RoutedClient(original):
        def __init__(self, **kwargs):
            super().__init__(**{'transport':transport, **kwargs})
    monkeypatch.setattr(httpx, 'AsyncClient', RoutedClient)
    async with RoutedClient(base_url='https://platform.example', headers={'Authorization':'Bearer '+token}) as client:
        yield client, state, user


@pytest.mark.parametrize('protocol,path,query_path,task_type', CASES)
async def test_native_requests_responses_and_exactly_once_billing(native_api, protocol, path, query_path, task_type):
    client, state, user = native_api
    kind = {4:'video',8:'media_processing',9:'asr'}[task_type]
    pricing = {'type':kind, 'currency':'CNY', 'billing_unit':'second', 'prices':{'720p':1}}
    if kind == 'asr':
        pricing = {'type':kind,'currency':'CNY','billing_unit':'minute','price_per_minute':1}
    if kind == 'media_processing':
        pricing = {'type':kind,'currency':'CNY','billing_unit':'minute','tiers':[{'short_side_max':1080,'fps_max':30,'price':5}]}
    model_name = 'workflow' if protocol == 'autodl' else 'volc.seedasr.auc' if kind == 'asr' else 'enhance-video-generative' if kind == 'media_processing' else 'up-model'
    model = await AiModelConfig.create(name='Native', task_type=task_type, api_protocol=protocol, model=model_name,
        base_url='https://native.example/api/v3' if protocol == 'volcengine_ark' else 'https://native.example',
        api_key='private-provider-token', is_active=True, concurrency=2, pricing=pricing)
    body = {'model':f'nv-{model.id}', 'content':[{'type':'text','text':'original @image1 prompt'},
        {'type':'image_url','image_url':{'url':'https://cdn.example/ref.png'},'role':'reference_image'}],
        'duration':4,'resolution':'720p','ratio':'16:9','seed':1234,'extra_provider_option':{'keep':False}}
    headers = {'X-Cat-Model':f'nv-{model.id}'}
    state.submitted = {'id':'up-task','extra':'unchanged'}
    state.completed = {'id':'up-task','status':'succeeded','resolution':'720p','duration':4,
        'content':{'video_url':'https://cdn.example/result.mp4'},'usage':{'completion_tokens':10},'extra':'retained'}
    if protocol == 'minimax':
        state.submitted = {'task_id':'up-task','base_resp':{'status_code':0,'status_msg':'success'},'unknown':123}
    if protocol == 'dashscope':
        body = {'model':f'nv-{model.id}','input':{'prompt':'unchanged'},'parameters':{'duration':4,'resolution':'720p','seed':1234}}
        state.submitted = {'output':{'task_id':'up-task','task_status':'PENDING'},'request_id':'up-trace'}
        state.completed = {'output':{'task_id':'up-task','task_status':'SUCCEEDED','video_url':'https://cdn.example/result.mp4'},
            'usage':{'output_video_duration':4,'input_video_duration':0,'SR':720},'request_id':'original'}
    if protocol == 'autodl':
        body = {'prompt':'unchanged','duration':4,'resolution':'720p','ref_image_0':'https://cdn.example/ref.png','custom':False}
        state.submitted = {'code':'Success','data':{'task_id':'up-task','status':'QUEUED','workflow':'original'},'msg':''}
        state.completed = {'code':'Success','data':{'task_id':'up-task','status':'SUCCESS','duration':999,
            'results':[{'type':'video','url':'https://cdn.example/result.mp4'}]},'msg':''}
        headers['Authorization'] = client.headers['Authorization'].removeprefix('Bearer ')
    if kind == 'media_processing':
        body = {'video_url':'https://cdn.example/input.mp4','resolution':'1080p','fps':30,'client_token':'original-token'}
        state.submitted = {'success':True,'task_id':'up-task','request_id':'up-trace'}
        state.completed = {'success':True,'task_id':'up-task','status':'completed',
            'result':{'video_url':'https://cdn.example/result.mp4','duration':60,'fps':30,'resolution':'1080p'},'expires_at':1234567}
    if kind == 'asr':
        body = {'user':{'uid':'original-user'},'audio':{'url':'https://cdn.example/input.mp3','format':'mp3'},
            'request':{'model_name':'bigmodel','show_utterances':True}}
        headers.update({'X-Api-Request-Id':'up-task','X-Api-Resource-Id':'volc.seedasr.auc'})
        state.response_headers = {'x-api-status-code':'20000000','x-api-message':'OK'}
        state.submitted = {}
        state.completed = {'audio_info':{'duration':60000},'result':{'text':'transcript must not be persisted',
            'utterances':[{'text':'original','start_time':0,'end_time':60000}]}}
    expected_sent = {**body, 'model':model_name} if 'model' in body else body
    response = await client.post(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.content == json.dumps(state.submitted, ensure_ascii=False).encode()
    assert response.headers['x-ratelimit-remaining-requests'] == '42'
    assert response.headers['x-request-id'] == 'supplier-id'
    assert response.headers['x-cat-request-id']
    sent = state.seen[-1]
    assert json.loads(sent.content) == expected_sent
    assert 'nv_' not in str(dict(sent.headers))
    if kind == 'asr':
        assert sent.headers['x-api-request-id'] == 'up-task'
        assert sent.headers['x-api-key'] == 'private-provider-token'
    elif protocol == 'autodl':
        assert sent.headers['authorization'] == 'private-provider-token'
    else:
        assert sent.headers['authorization'] == 'Bearer private-provider-token'
    receipt = await PlatformCallReceipt.get()
    assert receipt.provider_id == 'up-task' and receipt.state == 'processing'
    state.query = True
    for _ in range(2):
        response = await client.post(query_path, json={}, headers=headers) if kind == 'asr' else await client.get(query_path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.content == json.dumps(state.completed, ensure_ascii=False).encode()
    assert await ModelUsageRecord.all().count() == 1
    record = await ModelUsageRecord.get()
    assert record.billing_type == kind
    assert float(record.cost) == (1 if kind == 'asr' else 5 if kind == 'media_processing' else 4)
    job = await PlatformVideoJob.get()
    assert not job.output
    assert 'original @image1 prompt' not in json.dumps(job.inputs)
    assert 'transcript' not in json.dumps(job.inputs)
    other = await User.create(username='other-native-user', password_hash='!')
    other_token = (await create_key(AuthContext(user=other), 'other'))['key']
    foreign_headers = {**headers, 'Authorization':'Bearer '+other_token}
    before = len(state.seen)
    denied = await client.post(query_path,json={},headers=foreign_headers) if kind=='asr' else await client.get(query_path,headers=foreign_headers)
    assert denied.status_code == 404 and len(state.seen) == before


@pytest.mark.parametrize('status', [200,400,429,503])
async def test_native_failure_payload_headers_and_secret_boundary(native_api, status, monkeypatch):
    client,state,user = native_api
    model=await AiModelConfig.create(name='Ark',task_type=4,api_protocol='volcengine_ark',model='up-model',
        base_url='https://native.example/api/v3',api_key='provider-private',is_active=True,
        pricing={'type':'video','prices':{'720p':1}})
    from services.platform import native
    content=b'{ "error":{"code":"OriginalCode","message":"provider-private rejected"}, "extra":false }'
    async def failure(*args,**kwargs):
        return httpx.Response(status,content=content,headers={'content-type':'application/json','retry-after':'7',
            'x-ratelimit-remaining-requests':'0','connection':'x-private-hop','x-private-hop':'not-forwarded',
            'set-cookie':'supplier=cookie','x-api-key':'provider-private'})
    monkeypatch.setattr(native,'send',failure)
    response=await client.post('/v1/api/v3/contents/generations/tasks',json={'model':f'nv-{model.id}','content':[{'type':'text','text':'hi'}]})
    assert response.status_code==status and response.content==content.replace(b'provider-private',b'[redacted]')
    assert response.headers['retry-after']=='7' and response.headers['x-ratelimit-remaining-requests']=='0'
    for name in ('connection','x-private-hop','set-cookie','x-api-key'):
        assert name not in response.headers
    assert await ModelUsageRecord.all().count()==0
    assert (await PlatformCallReceipt.get()).state==('review' if status>=500 else 'rejected')


async def test_native_settlement_retries_without_losing_provider_result(native_api,monkeypatch):
    client,state,user=native_api
    await AiModelConfig.create(name='Ark',task_type=4,api_protocol='volcengine_ark',model='up-model',
        base_url='https://native.example/api/v3',api_key='provider-private',is_active=True,
        pricing={'type':'video','billing_unit':'second','prices':{'720p':1}})
    state.submitted={'id':'original-task'}
    state.completed={'id':'original-task','status':'succeeded','duration':4,'resolution':'720p',
                     'content':{'video_url':'https://cdn.example/result.mp4'},'provider_extension':'unchanged'}
    await client.post('/api/v3/contents/generations/tasks',json={'model':'up-model','content':[{'type':'text','text':'hi'}],
        'duration':4,'resolution':'720p'})
    state.query=True
    async def temporary_failure(*args):
        raise RuntimeError('temporary ledger error')
    monkeypatch.setattr('services.platform.native.settle',temporary_failure)
    response=await client.get('/api/v3/contents/generations/tasks/original-task')
    assert response.status_code==200 and response.json()==state.completed
    assert (await PlatformCallReceipt.get()).state=='measured'
    from services.platform.calls import recover_measured
    await recover_measured()
    assert (await PlatformCallReceipt.get()).state=='completed'
    assert await ModelUsageRecord.all().count()==1
    assert float((await UserWallet.get(user=user)).balance)==96


@pytest.mark.parametrize('field', ['base64','private_url','wrong_protocol'])
async def test_native_rejections_happen_before_supplier(native_api,field):
    client,state,user=native_api
    await AiModelConfig.create(name='Ark',task_type=4,api_protocol='volcengine_ark',model='up-model',
        base_url='https://native.example/api/v3',api_key='provider-private',is_active=True,
        pricing={'type':'video','billing_unit':'second','prices':{'720p':1}})
    url='data:image/png;base64,AAAA' if field=='base64' else 'https://127.0.0.1/ref.png'
    body={'model':'up-model','content':[{'type':'image_url','image_url':{'url':url}}]}
    path='/v2/video_generation' if field=='wrong_protocol' else '/api/v3/contents/generations/tasks'
    response=await client.post(path,json=body)
    assert response.status_code==422 and not state.seen
    assert not await PlatformCallReceipt.all().exists()


async def test_provider_gzip_response_is_decoded_only_once(native_api,monkeypatch):
    import gzip
    client,state,user=native_api
    await AiModelConfig.create(name='Ark',task_type=4,api_protocol='volcengine_ark',model='up-model',
        base_url='https://native.example/api/v3',api_key='provider-private',is_active=True,
        pricing={'type':'video','prices':{'720p':1}})
    state.submitted={'id':'compressed-task','unknown':'original'}
    state.response_headers={'content-encoding':'gzip'}
    # Exercise the real bounded sender with a compressed supplier transport.
    original=httpx.AsyncClient
    compressed=json.dumps(state.submitted).encode()
    def transport(request):
        return httpx.Response(200,content=gzip.compress(compressed),headers={'content-type':'application/json','content-encoding':'gzip'})
    class GzipClient(original):
        def __init__(self,**kwargs):
            super().__init__(**{**kwargs,'transport':httpx.MockTransport(transport)})
    monkeypatch.setattr('services.platform.native.httpx.AsyncClient',GzipClient)
    response=await client.post('/api/v3/contents/generations/tasks',json={'model':'up-model','content':[{'type':'text','text':'hi'}]})
    assert response.status_code==200 and response.content==compressed
    assert 'content-encoding' not in response.headers
    assert (await PlatformCallReceipt.get()).provider_id=='compressed-task'


async def test_unowned_draft_reference_is_not_sent_to_supplier(native_api):
    client,state,user=native_api
    response=await client.post('/api/v3/contents/generations/tasks',json={'model':'nv-1',
        'content':[{'type':'draft_task','draft_task':{'id':'someone-elses-draft'}}]})
    assert response.status_code==404 and not state.seen


def test_asr_split_credentials_never_leak():
    from services.platform.native import raw_response
    config=SimpleNamespace(api_key='private-app:private-access-token',api_protocol='volcengine_openspeech')
    response=httpx.Response(403,content=b'{"message":"private-access-token rejected"}',headers={'x-debug':'private-access-token'})
    forwarded=raw_response(response,SimpleNamespace(public_id=uuid4()),config)
    assert forwarded.body==b'{"message":"[redacted] rejected"}'
    assert 'x-debug' not in forwarded.headers
