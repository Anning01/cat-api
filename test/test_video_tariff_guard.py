from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from services.platform.calls import require_video_price
from services.platform.videos import VideoRequest,video_options


@pytest.mark.parametrize('value',[None,0,-1,True,float('nan'),float('inf')])
def test_legacy_rejects_disabled_or_invalid_output_tariffs(value):
 prices={'720p':1}
 if value is not None:prices['4k']=value
 config=SimpleNamespace(task_type=4,task_types=[4],api_protocol='volcengine_ark',video_model_type='seedance_2',pricing={'type':'video','prices':prices})
 request=VideoRequest(model='nv-20',prompt='fixture',resolution='4k',duration=4,aspect_ratio='16:9')
 with pytest.raises(HTTPException) as error:video_options(config,request.model_dump(mode='json'))
 assert error.value.status_code==422


def test_free_reference_seconds_do_not_make_paid_output_free():
 pricing={'type':'video','billing_unit':'second','prices':{'768p':.1},'video_reference_prices':{'768p':0}}
 assert require_video_price(pricing,'768p横',has_video_reference=True)=='768p'
 pricing['billing_unit']='token'
 with pytest.raises(HTTPException):require_video_price(pricing,'768p',has_video_reference=True)
