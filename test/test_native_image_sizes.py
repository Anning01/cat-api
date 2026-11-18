"""Native pixel sizes must not be gated by the workspace preset ratio list."""
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from services.platform.images import selection
from test.test_sdk_contract import sdk_api
from test.test_image_edit_files import PNG


@pytest.mark.parametrize('size,ratio,tier',[
 ('1536x864','16:9','1K'),('1536x1024','16:9','1K'),('1424x800','16:9','1K'),
 ('2048x1152','16:9','2K'),('3840x2160','16:9','4K'),('3072x1024',None,'1K'),
 ('864x1536','9:16','1K'),
])
def test_native_pixels_are_preserved_and_private_ratio_does_not_block(size,ratio,tier):
    chosen=selection(SimpleNamespace(image_model_type='gpt_image_2_6',api_protocol='openai_compatible'),
        {'size':size,'aspect_ratio':ratio,'output_format':'png'})
    assert chosen.provider_size==size and chosen.clarity==tier


@pytest.mark.parametrize('size',['0x1024','1024x576','1537x864','4096x2160','3840x3840','3840x1024','axb'])
def test_invalid_native_sizes_fail_with_specific_size_error(size):
    with pytest.raises(HTTPException) as error:
        selection(SimpleNamespace(image_model_type='gpt_image_2_6',api_protocol='openai_compatible'),
            {'size':size,'output_format':'png'})
    assert error.value.status_code==422 and 'size' in error.value.detail


async def test_sdk_edit_keeps_native_size_and_existing_price_band(sdk_api):
    sdk,state,(_,model,_)=sdk_api
    state.failure=200,json.dumps({'created':1,'data':[{'url':'https://cdn.example/result.png'}]}).encode(),{'content-type':'application/json'}
    result=await sdk.images.edit(model=f'nv-{model.id}',prompt='test',image=('reference.png',PNG,'image/png'),
        size='1536x864',extra_body={'aspect_ratio':'16:9'})
    assert result.data[0].url=='https://cdn.example/result.png'
    assert b'1536x864' in state.seen[0].content
    assert b'aspect_ratio' not in state.seen[0].content
    from auth.models import PlatformCallReceipt
    assert (await PlatformCallReceipt.get()).usage['clarity']=='1K'
