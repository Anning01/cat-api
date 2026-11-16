"""Aliyun SMS delivery. Never log phone numbers, codes or provider exceptions."""
import json

from alibabacloud_dysmsapi20170525.client import Client
from alibabacloud_dysmsapi20170525.models import SendSmsRequest
from alibabacloud_tea_openapi.models import Config
from alibabacloud_tea_util.models import RuntimeOptions
from fastapi import HTTPException

from config import settings


async def send_code(phone: str, code: str) -> None:
    client = Client(Config(access_key_id=settings.SMS_ACCESS_KEY_ID,
                           access_key_secret=settings.SMS_ACCESS_KEY_SECRET,
                           endpoint="dysmsapi.aliyuncs.com", protocol="https"))
    try:
        response = await client.send_sms_with_options_async(
            SendSmsRequest(phone_numbers=phone, sign_name=settings.SMS_SIGN_NAME,
                           template_code=settings.SMS_TEMPLATE_CODE,
                           template_param=json.dumps({settings.SMS_CODE_PARAMETER: code})),
            RuntimeOptions(autoretry=False, read_timeout=8000, connect_timeout=5000),
        )
        if response.body is not None and response.body.code == "OK":
            return
    except Exception:
        pass
    # A timeout can still mean delivery. Keep the reserved quota; do not auto-retry.
    raise HTTPException(503, "短信暂时发送失败，请稍后重新获取验证码")
