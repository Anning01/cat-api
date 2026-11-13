"""Catalog/ownership regression tests only: no supplier calls or real payments."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from api.platform import console_router, developer_router
from auth.deps import AuthContext, get_auth_context
from auth.models import StudioMediaLease, User
from models.config import AiModelConfig
from schemas.platform_media import EnhancementRequest, TranscriptSegment
from services.platform.access import create_key
from services.platform.catalog import PUBLIC_PROCESSING_OPTIONS
from services.platform.temporary_media import PREFIX, UploadSpec, issue_upload, owned_media_url


async def test_catalog_media_models_and_admin_updates():
    admin = await User.create(username="catalog-admin", is_super_admin=True)
    normal = await User.create(username="catalog-reader")
    common = dict(is_active=True, base_url="https://private-vendor.example", api_key="supplier-secret", model="private-model")
    options = dict(queue_id="private-queue", media_base_url="https://private-media.example", account_concurrency=37,
                   output_resolutions=["720p", "1080p", "2k", "4k"])
    enhancement = await AiModelConfig.create(**{**common,"model":"enhance-video-generative"}, task_type=8, task_types=[8], name="Enhance", concurrency=3,
        api_protocol="volcengine_mediakit", processing_options=options,
        pricing={"type":"media_processing", "billing_unit":"minute", "tiers":[{"short_side_max":2160,"fps_max":120,"price":5}]})
    asr = await AiModelConfig.create(**common, task_type=9, name="ASR", concurrency=2,
        pricing={"type":"asr", "billing_unit":"minute", "price_per_minute":0.015})
    await AiModelConfig.create(**{**common,"is_active":False}, task_type=9, name="Disabled")
    await AiModelConfig.create(**common, task_type=9, name="Team", scope="team")
    await AiModelConfig.create(**common, task_type=9, name="Loop", api_protocol="novelvids")
    keys = [(await create_key(AuthContext(user=normal), "reader", studio=studio))["key"] for studio in (False, True)]
    app = FastAPI()
    app.include_router(developer_router, prefix="/v1")
    app.include_router(console_router, prefix="/api")
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=admin, is_super_admin=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/models")).status_code == 401
        for key in keys:
            response = await client.get("/v1/models", headers={"Authorization":f"Bearer {key}"})
            assert response.status_code == 200
            data = response.json()["data"]
            assert [row["id"] for row in data] == [f"nv-{enhancement.id}", f"nv-{asr.id}"]
            assert [row["task_types"] for row in data] == [[8], [9]]
            assert [row["kinds"] for row in data] == [["media_processing"], ["asr"]]
            assert [row["concurrency"] for row in data] == [3, 2]
            assert set(data[0]["processing_options"]) == PUBLIC_PROCESSING_OPTIONS
            assert data[0]["processing_options"]["input_short_side_min"] == 360
            assert data[0]["pricing"]["tiers"][0]["price"] == 5
            assert data[1]["pricing"]["price_per_minute"] == 0.015
            for secret in ("supplier-secret", "private-vendor", "private-media", "private-queue", "account_concurrency", "queue_id", "base_url"):
                assert secret not in response.text
        changed = await client.patch(f"/api/config/{enhancement.id}", json={"concurrency":5,
            "processing_options":{**options,"poll_seconds":20},
            "pricing":{"type":"media_processing","billing_unit":"minute","tiers":[{"short_side_max":2160,"fps_max":120,"price":7}]}})
        assert changed.status_code == 200 and changed.json()["code"] == 0
        headers = {"Authorization":f"Bearer {keys[1]}"}
        updated = (await client.get("/v1/models", headers=headers)).json()["data"][0]
        assert updated["concurrency"] == 5 and updated["processing_options"]["poll_seconds"] == 20
        assert updated["pricing"]["tiers"][0]["price"] == 7
        assert (await client.patch(f"/api/config/{enhancement.id}", json={"is_active":False})).json()["code"] == 0
        assert len((await client.get("/v1/models", headers=headers)).json()["data"]) == 1
        app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=normal)
        assert (await client.patch(f"/api/config/{asr.id}", json={"concurrency":9})).status_code == 403


async def test_owned_media_rejects_cross_account_expired_and_wrong_kind(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp())
    bucket = SimpleNamespace(bucket="test-bucket", region="test-region", sign=lambda *args: "signed-owned-url")
    monkeypatch.setattr("services.platform.temporary_media.bucket_config", lambda: bucket)
    lease = await StudioMediaLease.create(object_key=f"{PREFIX}1/fixture.mp4", account_user_id=1,
        bucket=bucket.bucket, region=bucket.region, byte_length=100, expires_epoch=now+600)
    assert await owned_media_url(1, lease.id, "video") == "signed-owned-url"
    for user, kind in ((2,"video"), (1,"audio")):
        with pytest.raises(HTTPException) as error:
            await owned_media_url(user, lease.id, kind)
        assert error.value.status_code == 404
    await StudioMediaLease.filter(id=lease.id).update(expires_epoch=now-1)
    with pytest.raises(HTTPException):
        await owned_media_url(1, lease.id, "video")


async def test_upload_returns_recoverable_owned_media_identifier(monkeypatch):
    user = await User.create(username="media-uploader")
    bucket = SimpleNamespace(bucket="test-bucket", region="test-region", sign=lambda *args: "signed-url")
    monkeypatch.setattr("services.platform.temporary_media.bucket_config", lambda: bucket)
    response = await issue_upload(user.id, UploadSpec(content_type="audio/wav", byte_length=100,
        content_md5="AAAAAAAAAAAAAAAAAAAAAA=="))
    lease = await StudioMediaLease.get(id=response["media_id"])
    assert lease.account_user_id == user.id
    assert response["upload_url"] == response["read_url"] == "signed-url"
    assert await owned_media_url(user.id, response["media_id"], "audio") == "signed-url"
    await StudioMediaLease.filter(id=lease.id).update(bucket="other-bucket")
    with pytest.raises(HTTPException) as error:
        await owned_media_url(user.id, lease.id, "audio")
    assert error.value.status_code == 503


def test_proposed_wire_types_reject_private_fields_and_invalid_timestamps():
    with pytest.raises(ValidationError):
        EnhancementRequest(model="nv-1", media_id=1, request_id="12345678-1234-1234-1234-123456789abc",
                           output_resolution="1080p", api_key="forbidden")
    for start, end in ((2,1), (-1,1), (0,float("nan"))):
        with pytest.raises(ValidationError):
            TranscriptSegment(start=start, end=end, text="fixture")
