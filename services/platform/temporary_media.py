"""Account-scoped temporary model inputs on local disk or in a private OSS prefix."""
import asyncio
import base64
import hashlib
import io
from pathlib import Path
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import re
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from tortoise.expressions import F, Q
from tortoise.functions import Sum
from tortoise.transactions import in_transaction

from auth.models import StudioMediaLease, User
from config import settings
from services.platform import local_media
from services.oss.temporary import TemporaryBucket, suppress_signed_queries

PREFIX = local_media.PREFIX
REF = "https://cat-media.invalid/"
PROVIDER_READ_SECONDS = 3600
READ_SECONDS = 48 * 60 * 60
UPLOAD_SECONDS = 10 * 60
TYPES = {"image/png":"png","image/jpeg":"jpg","image/webp":"webp","image/gif":"gif","image/bmp":"bmp",
         "image/heic":"heic","image/heif":"heif","image/tiff":"tif","video/mp4":"mp4","video/quicktime":"mov",
         "audio/wav":"wav","audio/x-wav":"wav","audio/mpeg":"mp3","audio/mp4":"m4a","audio/flac":"flac",
         "audio/ogg":"ogg","audio/aac":"aac"}


class UploadSpec(BaseModel):
    content_type: str = Field(max_length=64)
    byte_length: int = Field(gt=0, le=5 * 1024**3)
    content_md5: str = Field(pattern=r"^[A-Za-z0-9+/]{22}==$")


def bucket_config():
    bucket = settings.STUDIO_TEMP_BUCKET or settings.OSS_BUCKET
    region = settings.STUDIO_TEMP_REGION
    if not region:
        endpoint = settings.OSS_ENDPOINT.removeprefix("https://").removeprefix("http://").rstrip("/")
        match = re.fullmatch(r"oss-([a-z0-9-]+)\.aliyuncs\.com", endpoint)
        region = match[1] if match else ""
    if not (re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket)
            and re.fullmatch(r"[a-z0-9-]+", region)
            and settings.OSS_ACCESS_KEY_ID and settings.OSS_ACCESS_KEY_SECRET):
        return None
    return TemporaryBucket(bucket, region, settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)


async def reserve(account_user_id, spec):
    bucket = bucket_config() if settings.OSS_PROVIDER == "aliyun" else None
    if settings.OSS_PROVIDER == "aliyun" and not bucket:
        raise HTTPException(503, "平台临时素材存储尚未配置")
    if spec.content_type not in TYPES:
        raise HTTPException(422, "不支持的参考素材类型")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(seconds=READ_SECONDS - 120)  # Leave two cleanup ticks before the 48-hour ceiling.
    key = f"{PREFIX}{account_user_id}/{uuid4().hex}.{TYPES[spec.content_type]}"
    headers = {"content-length":str(spec.byte_length), "content-type":spec.content_type, "content-md5":spec.content_md5}
    if bucket:
        headers.update({"x-oss-object-acl":"private","x-oss-forbid-overwrite":"true"})
        upload_url = bucket.sign("PUT",key,now,UPLOAD_SECONDS,headers)
    else:
        upload_url = local_media.signed_url("PUT", key, int(now.timestamp()) + UPLOAD_SECONDS, spec.content_md5)
    async with in_transaction() as db:
        if not await User.filter(id=account_user_id, status=1).using_db(db).update(status=F("status")):
            raise HTTPException(403, "账户已停用")
        totals = await StudioMediaLease.filter(account_user_id=account_user_id).using_db(db).annotate(total=Sum("byte_length")).values_list("total",flat=True)
        allocated = sum(t or 0 for t in totals)
        if allocated + spec.byte_length > settings.STUDIO_TEMP_ACCOUNT_BYTES:
            raise HTTPException(429, "账户临时素材空间已满")
        lease = await StudioMediaLease.create(using_db=db, object_key=key, bucket=bucket.bucket if bucket else local_media.LOCAL_BUCKET, region=bucket.region if bucket else "disk",
                                      account_user_id=account_user_id, byte_length=spec.byte_length, expires_epoch=int(expires.timestamp()))
    return lease, headers, upload_url


async def store_input(user_id: int, source: bytes | Path, mime: str):
    """Stage an already-admitted URL-only model input, streaming from the same descriptor."""
    with (source.open("rb") if isinstance(source, Path) else io.BytesIO(source)) as stream:
        size = stream.seek(0, 2)
        stream.seek(0)
        digest = await asyncio.to_thread(hashlib.file_digest, stream, "md5")
        stream.seek(0)
        checksum = base64.b64encode(digest.digest()).decode()
        spec = UploadSpec(content_type=mime, byte_length=size, content_md5=checksum)
        lease, headers, url = await reserve(user_id, spec)

        async def chunks():
            while chunk := await asyncio.to_thread(stream.read, 1024 * 1024):
                yield chunk

        if lease.bucket == local_media.LOCAL_BUCKET:
            await local_media.write_chunks(lease, checksum, chunks(), lease.expires_epoch)
        else:
            suppress_signed_queries()
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    response = await client.put(url, headers=headers, content=chunks())
                    response.raise_for_status()
            except httpx.HTTPError:
                raise HTTPException(503, "参考素材暂存失败") from None
    return provider_url(lease)


async def issue_upload(account_user_id, spec):
    from services.balance import ensure_solvent
    await ensure_solvent(account_user_id)
    lease, headers, upload_url = await reserve(account_user_id, spec)
    # A reference can only be exchanged inside an authenticated model request.
    return {"upload_url":upload_url, "headers":headers, "media_ref":REF + lease.object_key,
            "expires_at":lease.expires_epoch}


def provider_url(lease):
    now = datetime.now(timezone.utc)
    seconds = min(PROVIDER_READ_SECONDS, lease.expires_epoch - int(now.timestamp()))
    if seconds <= 0:
        raise HTTPException(410, "临时素材已过期")
    if lease.bucket == local_media.LOCAL_BUCKET:
        if not local_media.path_for(lease.object_key, lease.expires_epoch).is_file():
            raise HTTPException(404, "临时素材尚未上传")
        return local_media.signed_url("GET", lease.object_key, int(now.timestamp()) + seconds)
    bucket = bucket_config()
    if not bucket or (lease.bucket, lease.region) != (bucket.bucket, bucket.region):
        raise HTTPException(503, "平台临时素材存储不可用")
    return bucket.sign("GET", lease.object_key, now, seconds)


async def resolve_reference(user_id, value):
    if not isinstance(value, str) or not value.startswith(REF):
        return value
    lease = await StudioMediaLease.get_or_none(account_user_id=user_id, object_key=value[len(REF):],
                                               expires_epoch__gt=int(datetime.now(timezone.utc).timestamp()))
    if not lease:
        raise HTTPException(404, "临时素材不存在或已过期")
    return provider_url(lease)


async def resolve_payload(user_id, value, field=""):
    """Resolve private references only in media fields, never in prompts or other text."""
    if isinstance(value, dict):
        # Do not sign URLs inside user-defined tool schemas, metadata, or echoed text.
        containers = {"content", "messages", "input", "input_references", "images", "media", "mask",
                      "image_url", "input_image", "audio", "video_url", "audio_url", "subject_reference",
                      "image", "video", "parameters", "image_list", "reference_images", "reference_videos"}
        result = dict(value)
        for name, child in value.items():
            if name in containers or name.endswith("_url") or name.startswith(("ref_image_", "ref_audio_")) or name in {
                "first_frame_image", "last_frame_image"} or (name == "url" and field in containers):
                result[name] = await resolve_payload(user_id, child, name)
        return result
    if isinstance(value, list):
        return [await resolve_payload(user_id, v, field) for v in value]
    if isinstance(value, str) and value.startswith(REF) and (
        field in {"url","image","image_url","video","audio","first_frame_image","last_frame_image","subject_reference"}
        or field.endswith("_url") or field.startswith(("ref_image_", "ref_audio_"))
    ):
        return await resolve_reference(user_id, value)
    return value


async def owned_media_url(user_id: int, media_id: int, kind: str) -> str:
    """Resolve a live account-owned lease; provider adapters must still probe its bytes."""
    extensions = {"audio": {"wav", "mp3", "m4a", "flac", "ogg", "aac"}, "video": {"mp4", "mov"}}
    if kind not in extensions:
        raise ValueError("Unsupported media kind")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    lease = await StudioMediaLease.get_or_none(id=media_id, account_user_id=user_id,
                                               expires_epoch__gt=int(now.timestamp()))
    if not lease or not lease.object_key.startswith(f"{PREFIX}{user_id}/") or lease.object_key.rsplit(".", 1)[-1] not in extensions[kind]:
        raise HTTPException(404, "素材不存在、已过期或类型不匹配")
    return provider_url(lease)


async def known_upload_bytes(user_id: int, urls: list[str]) -> int:
    """Sum account-owned uploads without making requests to caller-supplied URLs."""
    objects = []
    for url in urls:
        parts = urlsplit(url)
        key = parts.path.lstrip("/")
        if parts.scheme == "https" and parts.port in (None, 443) and key.startswith(f"{PREFIX}{user_id}/"):
            objects.append((key, parts.hostname))
    if not objects:
        return 0
    rows = await StudioMediaLease.filter(account_user_id=user_id, object_key__in={key for key, _ in objects},
                                         expires_epoch__gt=int(datetime.now(timezone.utc).timestamp()))
    sizes = {(row.object_key, f"{row.bucket}.oss-{row.region}.aliyuncs.com"): row.byte_length for row in rows}
    sizes.update({(row.object_key, "cat-media.invalid"): row.byte_length for row in rows})
    return sum(sizes.get(item, 0) for item in objects)


async def expire_uploads():
    bucket = bucket_config()
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    backend = Q(bucket=local_media.LOCAL_BUCKET)
    if bucket:
        backend |= Q(bucket=bucket.bucket, region=bucket.region)
    due = await StudioMediaLease.filter(backend, Q(retry_epoch__isnull=True) | Q(retry_epoch__lte=epoch),
                                        object_key__startswith=PREFIX, expires_epoch__lte=epoch).order_by("expires_epoch").limit(100)
    if not due:
        return False
    suppress_signed_queries()
    async with httpx.AsyncClient(timeout=15) as client:
        for record in due:
            if record.bucket == local_media.LOCAL_BUCKET:
                dest = local_media.path_for(record.object_key, record.expires_epoch)
                try:
                    dest.unlink(missing_ok=True)
                    dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
                except OSError:
                    await StudioMediaLease.filter(id=record.id).update(retry_epoch=epoch+60)
                    continue
                await StudioMediaLease.filter(id=record.id).delete()
                continue
            url = bucket.sign("DELETE",record.object_key,datetime.now(timezone.utc),60)
            try:
                status = (await client.delete(url)).status_code
            except httpx.HTTPError:
                status = None
            if status in (200, 204, 404):
                await StudioMediaLease.filter(id=record.id).delete()
            else:
                await StudioMediaLease.filter(id=record.id).update(retry_epoch=epoch+300)

    return len(due) == 100


async def expire_periodically():
    while True:
        try:
            while await expire_uploads():
                await asyncio.sleep(0)
        except Exception:
            logging.getLogger(__name__).error("Temporary object cleanup deferred")
        await asyncio.sleep(60)
