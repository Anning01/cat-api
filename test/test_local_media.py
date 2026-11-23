import base64
import hashlib
import os
import time
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from auth.models import StudioMediaLease, User
from config import settings
from services.balance import top_up
from services.platform import local_media
from services.platform.temporary_media import UploadSpec, expire_uploads, issue_upload, resolve_reference


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OSS_PROVIDER", "local")
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path / "public"))
    monkeypatch.setattr(settings, "STUDIO_TEMP_PATH", str(tmp_path / "private"))
    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://cat.example/v1")
    app = FastAPI()
    app.include_router(local_media.router, prefix="/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cat.example")


async def test_private_upload_range_quota_switch_and_purge(storage, monkeypatch, tmp_path):
    owner = await User.create(username="owner")
    payload = b"video-bytes"
    spec = UploadSpec(byte_length=len(payload), content_type="video/mp4",
                      content_md5=base64.b64encode(hashlib.md5(payload).digest()).decode())
    with pytest.raises(HTTPException) as unpaid:
        await issue_upload(owner.id, spec)
    assert unpaid.value.status_code == 402
    await top_up(owner.id, Decimal("1"))
    ticket = await issue_upload(owner.id, spec)
    ref = ticket["media_ref"]
    assert "read_url" not in ticket and "media_id" not in ticket
    lease = await StudioMediaLease.get()
    path = local_media.path_for(lease.object_key, lease.expires_epoch)
    assert not path.exists() and lease.expires_epoch <= time.time() + 48*3600
    async with storage as client:
        async def put(content):
            return await client.put(ticket["upload_url"], headers=ticket["headers"], content=content)
        assert (await client.get(ticket["upload_url"])).status_code == 403
        assert (await put(b"x"*len(payload))).status_code == 422
        assert not path.exists() and not list(path.parent.glob("*.part"))
        monkeypatch.setattr(settings, "STUDIO_TEMP_FREE_BYTES", 2**60)
        assert (await put(payload)).status_code == 507
        monkeypatch.setattr(settings, "STUDIO_TEMP_FREE_BYTES", 0)
        assert (await put(payload)).status_code == 204
        assert (await put(payload)).status_code == 409
        with pytest.raises(HTTPException) as other:
            await resolve_reference(owner.id+1, ref)
        assert other.value.status_code == 404
        url = await resolve_reference(owner.id, ref)
        assert (await client.head(url)).headers["content-length"] == str(len(payload))
        partial = await client.get(url, headers={"Range":"bytes=2-4"})
        assert partial.status_code == 206 and partial.content == payload[2:5]
        # Move the clocks forward; the object deadline is immutable in both the ticket and the filename.
        from datetime import datetime, timezone
        from services.platform import temporary_media
        future = lease.expires_epoch + 1
        class AfterExpiry(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(future, tz=tz or timezone.utc)
        monkeypatch.setattr(temporary_media, "datetime", AfterExpiry)
        monkeypatch.setattr(local_media.time, "time", lambda: future)
        assert (await client.get(url)).status_code == 404
        monkeypatch.setattr(settings, "OSS_PROVIDER", "aliyun")
        await expire_uploads()
        assert not path.exists() and not await StudioMediaLease.exists()
    avatar = tmp_path / "public/avatars/old.png"
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b"avatar")
    leftover = path.with_suffix(".mp4.part")
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_bytes(b"partial")
    past = time.time()-49*3600
    os.utime(avatar, (past, past))
    # A partial write close to expiry must not extend disk retention.
    os.utime(leftover, (future, future))
    local_media.sweep_orphans()
    assert avatar.exists() and not leftover.exists()


async def test_interrupted_upload_leaves_no_payload_and_retry_succeeds(storage):
    from services.platform.temporary_media import reserve
    owner = await User.create(username="retry-owner")
    data = b"payload"
    spec = UploadSpec(content_type="video/mp4", byte_length=len(data),
                      content_md5=base64.b64encode(hashlib.md5(data).digest()).decode())
    lease, headers, put = await reserve(owner.id, spec)
    async def interrupted():
        yield data[:2]
        raise ConnectionError("interrupted")
    with pytest.raises(ConnectionError):
        await local_media.write_chunks(lease, spec.content_md5, interrupted(), lease.expires_epoch)
    path = local_media.path_for(lease.object_key, lease.expires_epoch)
    assert not path.exists() and not list(path.parent.glob("*.part"))
    async with storage as client:
        assert (await client.put(put, headers=headers, content=data)).status_code == 204
    assert path.read_bytes() == data
