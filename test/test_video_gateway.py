"""Exercise discovery, paid submission, polling and download across the public HTTP boundary."""
import io
import json

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI, APIStatusError
from PIL import Image

from api.config import router as admin_routes
from api.platform import developer_router
from auth.deps import AuthContext, require_super_admin
from auth.models import BalanceTransaction, PlatformCallReceipt, User, UserWallet
from services.platform.access import create_key
from services.platform.http_contract import DEVELOPER_EXCEPTION_HANDLERS
from test.test_sdk_contract import sdk_api


def png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_import_two_models_once_then_submit_poll_and_download(monkeypatch):
    admin = await User.create(username="gateway-admin", is_super_admin=True)
    ctx = AuthContext(user=admin, is_super_admin=True)
    key = (await create_key(ctx, "client"))["key"]
    await UserWallet.create(user=admin, balance=10)
    app = FastAPI(exception_handlers=DEVELOPER_EXCEPTION_HANDLERS)
    app.include_router(developer_router, prefix="/v1")
    app.include_router(admin_routes, prefix="/admin")
    app.dependency_overrides[require_super_admin] = lambda: ctx
    transport = httpx.ASGITransport(app)
    posts = []
    from config import settings
    from services.oss.temporary import TemporaryBucket
    monkeypatch.setattr(settings, "OSS_PROVIDER", "aliyun")
    monkeypatch.setattr("services.platform.temporary_media.bucket_config",
        lambda: TemporaryBucket("example", "cn-hangzhou", "test-access", "test-key"))
    image = png("red")

    async def route(req):
        if req.url.host == "cat.test":
            return await transport.handle_async_request(req)
        assert req.url.host == "gateway.test" and req.headers["authorization"] == "Bearer fixture"
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"data":[{"id":"demo-alpha"}, {"id":"demo-beta"}]})
        if req.method == "POST":
            assert req.url.path == "/v1/videos"
            body = await req.aread()
            if posts:
                submitted = json.loads(body)
                assert submitted["model"] == "demo-beta"
                assert httpx.URL(submitted["input_reference"]).host == "example.oss-cn-hangzhou.aliyuncs.com"
            else:
                assert json.loads(body) == {"model":"demo-alpha","size":"720x1280","prompt":"pan","seconds":"4"}
            posts.append(req.headers["idempotency-key"])
            return httpx.Response(200, json={"id":f"task-{len(posts)}"})
        if req.url.path.endswith("/content"):
            if req.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(200, content=b"test video", headers={"content-type":"video/mp4"})
        return httpx.Response(200,json={"id":"provider-task","status":"completed","seconds":"4"})

    adapter = httpx.MockTransport(route)
    original = httpx.AsyncClient
    class Client(original):
        def __init__(self, **kwargs):
            super().__init__(**{"transport":adapter, **kwargs})
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    async with Client(base_url="https://cat.test", headers={"Authorization":"Bearer "+key}) as client:
        channel = {"base_url":"https://gateway.test", "api_key":"fixture"}
        ids = (await client.post("/admin/channel/models",json=channel)).json()["data"]
        template = {**channel,"name":"template","model":ids[0],"task_type":4,"task_types":[4],
                    "api_protocol":"openai_video","video_model_type":"openai_video","is_active":True,
                    "pricing":{"type":"video","billing_unit":"second","prices":{"720p":0.2}}}
        payload = {"template":template,"models":ids}
        imported = await client.post("/admin/channel/import",json=payload)
        assert imported.status_code == 200, imported.text
        assert (await client.post("/admin/channel/import",json=payload)).json()["data"] == imported.json()["data"]
        sdk = AsyncOpenAI(base_url="https://cat.test/v1",api_key=key,http_client=client,max_retries=0)
        assert [item.id for item in (await sdk.models.list()).data] == ids
        import base64
        import hashlib
        ticket = await client.post("/v1/media/uploads", json={"byte_length": len(image), "content_type": "image/png",
            "content_md5": base64.b64encode(hashlib.md5(image).digest()).decode()})
        assert ticket.status_code == 200
        for index, model in enumerate(ids):
            options = {"extra_body": {"input_reference": ticket.json()["media_ref"]}} if index else {}
            create = dict(model=model, prompt="pan", extra_headers={"Idempotency-Key":model}, **options)
            task = await sdk.videos.create(**create)
            replay = await sdk.videos.create(**create)
            assert replay.id == task.id
            assert (await sdk.videos.retrieve(task.id)).status == "completed"
            assert await (await sdk.videos.download_content(task.id)).aread() == b"test video"
            head = await client.head(f"/v1/videos/{task.id}/content")
            assert head.status_code == 200 and not head.content
            receipt = (await client.get("/v1/requests",params={"request_key":model})).json()
            assert receipt["id"] == task.id and receipt["settlement"]["amount"] == "0.800000"
        with pytest.raises(APIStatusError) as conflict:
            await sdk.videos.create(**{**create, "extra_body": {"input_reference": "https://cdn.example/other.png"}})
        assert conflict.value.status_code == 409
        assert len(set(posts)) == 2 and len(posts) == 2
        assert await BalanceTransaction.all().count() == 2


async def test_autodl_default_price_uncertain_response_and_rounded_size(sdk_api):
    sdk, state, (_, _, config) = sdk_api
    config.video_model_type = "minimax_h3_autodl"
    config.api_protocol = "autodl"
    config.pricing = {"type":"video","billing_unit":"second","prices":{"768p":0.2}}
    config.concurrency = 3
    await config.save()
    task = await sdk.videos.create(model="official-video",prompt="pan")
    assert task.size == "1365x768"
    assert json.loads(state.seen[-1].content)["resolution"] == "768p横"
    await sdk.videos.create(model="official-video",prompt="pan",size=task.size)
    with pytest.raises(APIStatusError):
        await sdk.videos.create(model="official-video",prompt="pan",size="720x1280")
    assert len(state.seen) == 2
    state.failure = (200,b'{"code":"Success","data":{}}',{})
    with pytest.raises(APIStatusError) as unknown:
        await sdk.videos.create(model="official-video",prompt="pan",extra_headers={"Idempotency-Key":"lost"})
    assert unknown.value.status_code == 502
    assert (await PlatformCallReceipt.get(state="review")).provider_id is None
    assert len(state.seen) == 3



async def test_custom_channel_spec_is_shared_by_price_config_catalog_and_request(sdk_api, monkeypatch):
    from controllers.config import ai_model_config_controller
    from schemas.config import AiModelConfigCreate
    from services.video.unified import OpenAIVideoGenerator

    sdk, _, _ = sdk_api
    model = await ai_model_config_controller.create(AiModelConfigCreate(
        name="custom", model="short-film", api_key="fixture", base_url="https://gateway.test",
        api_protocol="openai_video", video_model_type="openai_video", task_type=4, is_active=True,
        processing_options={"video":{"sizes":["960x540"],"seconds":[18],"reference_inputs":[]}},
        pricing={"type":"video","billing_unit":"second","prices":{"540p":0.1}}), scope="official")
    captured = []
    async def submit(self, method, **kwargs):
        captured.append(kwargs["payload"])
        return {"id":"original"}
    monkeypatch.setattr(OpenAIVideoGenerator, "_request", submit)
    rows = await sdk.models.list()
    row = next(r for r in rows.data if r.id == model.public_alias)
    contract = row.model_extra["operations"]["videos.create"]
    assert contract["sizes"] == ["960x540"] and contract["seconds"] == [18]
    assert contract["max_reference_images"] == 0 and row.model_extra["input_modalities"] == ["text"]
    for options in [{"size":"1280x720"}, {"seconds":"4"}, {"input_reference":("in.png", png("red"), "image/png")}]:
        with pytest.raises(APIStatusError) as rejected:
            await sdk.videos.create(model=model.public_alias, prompt="pan", **options)
        assert rejected.value.status_code == 422
    result = await sdk.videos.create(model=model.public_alias, prompt="pan")
    assert result.seconds == "18" and result.size == "960x540"
    assert captured == [{"model":"short-film","prompt":"pan","size":"960x540","seconds":"18"}]


async def test_native_file_upload_uses_owned_lease_and_sends_exact_bytes(monkeypatch):
    from services.platform import video_uploads
    from config import settings
    monkeypatch.setattr(settings, "OSS_PROVIDER", "aliyun")
    from services.oss.temporary import TemporaryBucket
    from auth.models import StudioMediaLease
    user = await User.create(username="file-upload")
    data = png("green")
    monkeypatch.setattr("services.platform.temporary_media.bucket_config",
                        lambda: TemporaryBucket("example", "cn-hangzhou", "test-access", "test-key"))
    sent = []
    async def put(request):
        assert request.method == "PUT" and request.content == data
        assert request.headers["content-type"] == "image/png" and "authorization" not in request.headers
        sent.append(request.url.path)
        return httpx.Response(200)
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:client(transport=httpx.MockTransport(put),**kw))
    result = await video_uploads.store_video_reference(user.id, ("ref.png", data, "image/png"))
    lease = await StudioMediaLease.get(account_user_id=user.id)
    assert httpx.URL(result).path == sent[0] == "/" + lease.object_key
    assert lease.byte_length == len(data)


async def test_admin_declared_vision_inputs_reach_upstream(sdk_api):
    sdk,state,(config,_,_) = sdk_api
    config.processing_options = {"input_modalities":["text","image"]}
    await config.save()
    rows = await sdk.models.list()
    entry = next(row for row in rows.data if row.id == config.model)
    assert entry.model_extra["input_modalities"] == ["text","image"]
    content = [{"type":"text","text":"看图"},{"type":"image_url","image_url":{"url":"https://cdn.example/ref.png"}}]
    await sdk.chat.completions.create(model=entry.id,messages=[{"role":"user","content":content}])
    assert json.loads(state.seen[-1].content)["messages"][0]["content"] == content
    assert (await PlatformCallReceipt.get()).state == "completed"


async def test_video_read_replay_and_download_require_original_model_permission(sdk_api):
    sdk, state, (text, _, config) = sdk_api
    job = await sdk.videos.create(model=config.model,prompt="pan",size="1280x720",
                                  extra_headers={"Idempotency-Key":"original"})
    client = sdk._client
    owner = await User.get(username="sdk-client")
    limited = (await create_key(AuthContext(user=owner),"limited",allowed_model_ids=[f"nv-{text.id}"]))["key"]
    outsider = await User.create(username="other-account")
    other = (await create_key(AuthContext(user=outsider),"external"))["key"]
    before = len(state.seen)
    for key, code in ((other,404),(limited,403)):
        headers = {"Authorization":"Bearer "+key}
        for method, path in [("GET",f"/videos/{job.id}"),("GET",f"/requests/{job.id}"),
                             ("GET",f"/videos/{job.id}/content"),("HEAD",f"/videos/{job.id}/content")]:
            r = await client.request(method,"https://platform.example/v1"+path,headers=headers)
            assert r.status_code == code
    replay = await client.post("https://platform.example/v1/videos",
        headers={"Authorization":"Bearer "+limited,"Idempotency-Key":"original"},
        json={"model":config.model,"prompt":"pan","size":"1280x720"})
    assert replay.status_code == 403
    assert len(state.seen) == before


@pytest.mark.parametrize("operation", ["chat_completions", "responses", "images.generate"])
async def test_compatible_import_preserves_per_model_routing_for_other_operations(sdk_api, monkeypatch, operation):
    from models.config import AiModelConfig
    from schemas.config import AiModelConfigCreate
    from services.platform.channel_models import import_models
    from test.test_responses import response as response_fixture

    sdk, state, (text, image, _) = sdk_api
    template = AiModelConfigCreate.model_validate(image if operation == "images.generate" else text, from_attributes=True)
    if operation == "images.generate":
        from services.image_generation.capabilities import capabilities_for
        template.pricing = {"type":"image","prices":dict.fromkeys(capabilities_for(template.image_model_type).clarities, 0.2)}
    if operation == "responses":
        template.text_api = "responses"
        def responses_upstream(req):
            assert req.url.path == "/v1/responses"
            state.seen.append(req)
            return httpx.Response(200,json=response_fixture())
        monkeypatch.setattr("services.platform.chat.provider_client", lambda config: AsyncOpenAI(
            base_url=config.base_url, api_key=config.api_key, max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(responses_upstream))))
    models = ["test-model-a", "test-model-b"]
    ids = await import_models(template, models)
    for id, upstream in zip(ids, models, strict=True):
        public = (await AiModelConfig.get(id=id)).public_alias
        if operation == "responses":
            await sdk.responses.create(model=public,input="hello")
        elif operation == "chat_completions":
            await sdk.chat.completions.create(model=public,messages=[{"role":"user","content":"hello"}])
        else:
            await sdk.images.generate(model=public,prompt="hello",size="1024x1024")
        assert json.loads(state.seen[-1].content)["model"] == upstream
        assert (await PlatformCallReceipt.get(model_config_id=id)).state == "completed"


@pytest.mark.parametrize("audio,last_frame", [(True, False), (False, True)])
async def test_workbench_h3_submit_recover_and_settle(sdk_api, audio, last_frame):
    from uuid import uuid4

    sdk, state, (_, _, config) = sdk_api
    config.video_model_type = "minimax_h3_autodl"
    config.api_protocol = "autodl"
    config.pricing = {"type": "video", "billing_unit": "second", "prices": {"768p": 0.2}}
    await config.save()
    headers = {"Authorization": "Bearer " + sdk.api_key, "X-NovelVids-Capabilities": "pixel_tier_images"}
    base = "https://platform.example/v1"
    catalog = await sdk._client.get(base + "/models", headers=headers)
    model = next(m for m in catalog.json()["data"] if m["id"] == f"nv-{config.id}")
    assert model["video_model_type"] == "minimax_h3"
    key = str(uuid4())
    headers["Idempotency-Key"] = key
    body = {"model": model["id"], "prompt": "pan", "duration": 4, "aspect_ratio": "16:9",
            "resolution": "768P", "watermark": False, "generate_audio": audio,
            "return_last_frame": last_frame, "request_id": key}
    first = await sdk._client.post(base + "/videos", headers=headers, json=body)
    assert first.status_code == 200, first.text
    replay = await sdk._client.post(base + "/videos", headers=headers, json=body)
    assert replay.json()["id"] == first.json()["id"] and len(state.seen) == 1
    assert json.loads(state.seen[0].content)["resolution"] == "768p横"
    result_url = "https://cdn.example/result.mp4"
    state.failure = (200, json.dumps({"code":"Success","data":{"status":"SUCCESS","results":[
        {"type":"video","url":result_url}]}}).encode(), {})
    recovered = await sdk._client.get(base + "/videos/req-" + key, headers=headers)
    assert recovered.json()["status"] == "completed"
    assert recovered.json()["metadata"]["url"] == result_url
    receipt = await sdk._client.get(base + "/requests/" + first.json()["id"], headers=headers)
    assert receipt.json()["settlement"]["amount"] == "0.800000"
