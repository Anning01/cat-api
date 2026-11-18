"""Multipart image edits use local fixtures, never a real paid generation."""
import base64
import json
from auth.models import PlatformCallReceipt
from models.usage_record import ModelUsageRecord
from test.test_sdk_contract import sdk_api

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ4kAAAAASUVORK5CYII=')


def result(state):
    state.failure=200,json.dumps({'created':1,'data':[{'url':'https://cdn.example/result.png'}]}).encode(),{'content-type':'application/json'}


async def test_official_sdk_file_edit_preserves_files_model_and_usage(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    result(state)
    image.public_alias='gpt-image-2-discount';await image.save()
    response=await sdk.images.edit(model=image.public_alias,image=[('reference.png',PNG,'image/png')],
        mask=('mask.png',PNG,'image/png'),prompt='edit',size='1024x1024',response_format='url',
        extra_headers={'Idempotency-Key':'file-edit-once'})
    assert response.data[0].url=='https://cdn.example/result.png'
    sent=state.seen[0]
    assert sent.url.path=='/v1/images/edits'
    assert sent.headers['content-type'].startswith('multipart/form-data; boundary=')
    assert PNG in sent.content and b'official-image' in sent.content and b'gpt-image-2-discount' not in sent.content
    assert b'name="image[]"' in sent.content and b'name="mask"' in sent.content
    receipt=await PlatformCallReceipt.get()
    assert receipt.state=='completed' and receipt.usage['input_image_count']==1
    assert await ModelUsageRecord.all().count()==1
    repeat=await sdk._client.post('https://platform.example/v1/images/edits',
        headers={'Authorization':'Bearer '+sdk.api_key,'Idempotency-Key':'file-edit-once'},
        data={'model':image.public_alias,'prompt':'edit','size':'1024x1024','response_format':'url'},
        files=[('image[]',('reference.png',PNG,'image/png')),('mask',('mask.png',PNG,'image/png'))])
    assert repeat.status_code==409 and len(state.seen)==1


async def test_unauthorized_or_invalid_file_never_reaches_supplier(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    response=await sdk._client.post('https://platform.example/v1/images/edits',
        data={'model':f'nv-{image.id}','prompt':'edit'},files={'image':('x.png',PNG,'image/png')})
    assert response.status_code==401
    response=await sdk._client.post('https://platform.example/v1/images/edits',
        headers={'Authorization':'Bearer '+sdk.api_key},data={'model':f'nv-{image.id}','prompt':'edit'},
        files={'image':('not-image.txt',b'not an image','text/plain')})
    assert response.status_code==422 and not state.seen
    assert await PlatformCallReceipt.all().count()==0


async def test_file_request_size_limit_prevents_supplier_call(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    response=await sdk._client.post('https://platform.example/v1/images/edits',
        headers={'Authorization':'Bearer '+sdk.api_key,'Content-Length':str(65*1024**2)},
        data={'model':f'nv-{image.id}','prompt':'edit'},files={'image':('x.png',PNG,'image/png')})
    assert response.status_code==413 and not state.seen


async def test_standard_base64_file_edit_preserves_result_and_settles(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    encoded=base64.b64encode(PNG).decode()
    state.failure=200,json.dumps({'created':1,'data':[{'b64_json':encoded}]}).encode(),{'content-type':'application/json'}
    response=await sdk.images.edit(model=f'nv-{image.id}',image=('reference.png',PNG,'image/png'),
        prompt='edit',response_format='b64_json')
    assert response.data[0].b64_json==encoded
    assert b'b64_json' in state.seen[0].content
    receipt=await PlatformCallReceipt.get()
    assert receipt.state=='completed' and receipt.usage['image_count']==1


async def test_file_hash_prevents_reusing_a_key_for_different_reference(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    result(state)
    headers={'Authorization':'Bearer '+sdk.api_key,'Idempotency-Key':'file-content-identity'}
    async def submit(data):
        return await sdk._client.post('https://platform.example/v1/images/edits',headers=headers,
            data={'model':f'nv-{image.id}','prompt':'edit'},files={'image':('x.png',data,'image/png')})
    assert (await submit(PNG)).status_code==200
    changed=await submit(PNG+b'changed')
    assert changed.status_code==409 and len(state.seen)==1


async def test_official_sdk_file_edit_preserves_requested_base64_result_and_billing(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    encoded=base64.b64encode(PNG).decode()
    state.failure=200,json.dumps({'created':1,'data':[{'b64_json':encoded}]}).encode(),{'content-type':'application/json'}
    response=await sdk.images.edit(model=f'nv-{image.id}',image=('x.png',PNG,'image/png'),
        prompt='edit',response_format='b64_json',size='1024x1024')
    assert response.data[0].b64_json==encoded
    receipt=await PlatformCallReceipt.get()
    assert receipt.state=='completed' and receipt.usage['image_count']==1
    assert receipt.usage['input_image_count']==1
    assert b'b64_json' in state.seen[0].content


async def test_file_edit_rejects_url_only_provider_before_submission(sdk_api):
    sdk,state,(_,image,_)=sdk_api
    image.api_protocol='volcengine_ark';await image.save()
    reply=await sdk._client.post('https://platform.example/v1/images/edits',
        headers={'Authorization':'Bearer '+sdk.api_key},data={'model':f'nv-{image.id}','prompt':'edit'},
        files={'image':('x.png',PNG,'image/png')})
    assert reply.status_code==422 and not state.seen
    assert await PlatformCallReceipt.all().count()==0
