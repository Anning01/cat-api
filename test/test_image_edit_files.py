"""Multipart image edits use local fixtures, never a real paid generation."""
import base64
import json
from auth.models import PlatformCallReceipt
from models.usage_record import ModelUsageRecord
from test.test_sdk_contract import sdk_api

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ4kAAAAASUVORK5CYII=')


async def test_file_edit_requires_oss_upload_before_billing(sdk_api):
    sdk, state, (_, image, _) = sdk_api
    response = await sdk._client.post("https://platform.example/v1/images/edits",
        headers={"Authorization": "Bearer " + sdk.api_key}, data={"model": image.model, "prompt": "edit"},
        files={"image": ("reference.png", PNG, "image/png")})
    assert response.status_code == 422 and "/v1/media/uploads" in response.text
    assert not state.seen and not await PlatformCallReceipt.exists()


async def test_url_edit_preserves_requested_output_format_and_usage(sdk_api):
    sdk, state, (_, image, _) = sdk_api
    encoded = base64.b64encode(PNG).decode()
    state.failure = 200, json.dumps({"data": [{"b64_json": encoded}]}).encode(), {"content-type": "application/json"}
    response = await sdk._client.post("https://platform.example/v1/images/edits",
        headers={"Authorization": "Bearer " + sdk.api_key}, json={"model": image.model, "prompt": "edit",
        "image": ["https://cdn.example/reference.png"], "size": "1024x1024", "response_format": "b64_json"})
    assert response.status_code == 200 and response.json()["data"][0]["b64_json"] == encoded
    receipt = await PlatformCallReceipt.get()
    assert receipt.state == "completed" and receipt.usage["input_image_count"] == 1
    assert await ModelUsageRecord.all().count() == 1
