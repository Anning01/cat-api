import json

import httpx
import pytest
from openai import AsyncOpenAI, APIStatusError

from auth.models import BalanceTransaction, PlatformCallReceipt
from test.test_sdk_contract import sdk_api


def response(status='completed', usage=True):
    return {'id': 'resp-fixture', 'object': 'response', 'created_at': 1, 'model': 'vendor-model',
            'status': status, 'output': [{'id': 'msg-1', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                'content': [{'type': 'output_text', 'text': '{"answer":42}', 'annotations': []}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12,
                'input_tokens_details': {'cached_tokens': 3}, 'output_tokens_details': {'reasoning_tokens': 1}} if usage else None,
            'vendor_extension': {'kept': True}}


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_responses_preserves_wire_and_settles_once(sdk_api, monkeypatch, streaming):
    sdk, state, models = sdk_api
    models[0].thinking = 'disabled'
    models[0].reasoning_effort = 'high'
    await models[0].save()
    seen = []
    result = response()
    wire = ': heartbeat\n\nevent: response.completed\ndata: ' + json.dumps({'type': 'response.completed', 'response': result}) + '\n\n'
    def dispatch(request):
        seen.append(json.loads(request.content))
        assert request.url.path == '/v1/responses'
        return httpx.Response(200, text=wire, headers={'content-type': 'text/event-stream'}) if streaming else httpx.Response(200, json=result)
    monkeypatch.setattr('services.platform.chat.provider_client', lambda config: AsyncOpenAI(
        api_key='upstream', base_url='https://vendor.example/v1', max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(dispatch))))
    schema = {'type': 'json_schema', 'name': 'answer', 'strict': True, 'schema': {'type': 'object'}}
    request = {'model': 'official-chat', 'input': 'Return JSON', 'stream': streaming,
        'text': {'format': schema}, 'reasoning': {'effort': 'low'}, 'provider_option': {'value': 123}}
    raw = await sdk._client.post('https://platform.example/v1/responses', json=request, headers={**sdk.auth_headers, 'Idempotency-Key': 'responses-once'})
    assert raw.status_code == 200, raw.text
    assert raw.text == wire if streaming else raw.json() == result
    assert seen == [request]
    receipt = await PlatformCallReceipt.get(provider_id='resp-fixture')
    assert receipt.state == 'completed'
    assert receipt.usage['input_tokens'] == 10 and receipt.usage['output_tokens'] == 2
    assert receipt.usage['cache_read_tokens'] == 3
    assert await BalanceTransaction.filter(usage_record_id=receipt.usage_record_id,type='consume').count()==1
    repeated = await sdk._client.post('https://platform.example/v1/responses', json=request, headers={**sdk.auth_headers, 'Idempotency-Key': 'responses-once'})
    assert repeated.status_code == 409 and len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal,usage,expected', [
    ('response.completed', True, 'completed'), ('response.incomplete', True, 'completed'),
    ('response.failed', True, 'review'), ('response.completed', False, 'review'), (None, True, 'review')])
async def test_responses_stream_terminal_and_missing_usage(sdk_api, monkeypatch, terminal, usage, expected):
    sdk, _, _ = sdk_api
    result = response(usage=usage)
    events = [{'type': 'response.created', 'response': {**result, 'usage': None}}]
    if terminal:
        events.append({'type': terminal, 'response': result})
    wire = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)
    monkeypatch.setattr('services.platform.chat.provider_client', lambda config: AsyncOpenAI(
        api_key='upstream', base_url='https://vendor.example/v1', max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            text=wire, headers={'content-type': 'text/event-stream'})))))
    raw = await sdk._client.post('https://platform.example/v1/responses', json={'model': 'official-chat', 'input': 'test', 'stream': True}, headers=sdk.auth_headers)
    assert raw.status_code == 200 and raw.text == wire
    receipt = await PlatformCallReceipt.all().get()
    assert receipt.state == expected


@pytest.mark.asyncio
async def test_responses_rejection_is_not_retried(sdk_api, monkeypatch):
    sdk, state, models = sdk_api
    state.failure = (400, b'{"error":{"message":"unsupported format"}}', {'content-type': 'application/json'})
    with pytest.raises(APIStatusError) as error:
        await sdk.responses.create(model='official-chat', input='test')
    assert error.value.status_code == 400 and len(state.seen) == 1
    assert (await PlatformCallReceipt.all().get()).state == 'rejected'
    models[0].max_tokens = 10
    await models[0].save()
    with pytest.raises(APIStatusError) as error:
        await sdk.responses.create(model='official-chat', input='test', max_output_tokens=11)
    assert error.value.status_code == 422 and len(state.seen) == 1


@pytest.mark.parametrize('status,usage',[
    ('failed',True),('queued',True),('in_progress',True),('completed',False),('completed','invalid')])
async def test_nonterminal_or_invalid_usage_preserves_response_without_settlement(sdk_api,monkeypatch,status,usage):
    sdk,_,_=sdk_api
    result=response(status=status,usage=usage is True)
    if usage=='invalid':result['usage']=['not','usage']
    monkeypatch.setattr('services.platform.chat.provider_client',lambda config:AsyncOpenAI(
        api_key='synthetic',base_url='https://vendor.example/v1',max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=result)))))
    raw=await sdk._client.post('https://platform.example/v1/responses',json={'model':'official-chat','input':'test'},headers=sdk.auth_headers)
    assert raw.status_code==200 and raw.json()==result
    assert (await PlatformCallReceipt.get()).state=='review'
    assert not await BalanceTransaction.filter(type='consume').exists()


@pytest.mark.parametrize('terminal_error',[False,True])
async def test_terminal_response_does_not_bill_earlier_usage_or_nested_error(sdk_api,monkeypatch,terminal_error):
    sdk,_,_=sdk_api
    terminal=response(usage=terminal_error)
    if terminal_error:terminal['error']={'code':'provider_error','message':'synthetic failure'}
    events=[{'type':'response.in_progress','response':response()},
            {'type':'response.completed','response':terminal}]
    wire=''.join('data: '+json.dumps(event)+'\n\n' for event in events)
    monkeypatch.setattr('services.platform.chat.provider_client',lambda config:AsyncOpenAI(
        api_key='synthetic',base_url='https://vendor.example/v1',max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=wire,headers={'content-type':'text/event-stream'})))))
    raw=await sdk._client.post('https://platform.example/v1/responses',json={'model':'official-chat','input':'test','stream':True},headers=sdk.auth_headers)
    assert raw.status_code==200 and raw.text==wire
    assert (await PlatformCallReceipt.get()).state=='review'
    assert not await BalanceTransaction.filter(type='consume').exists()
