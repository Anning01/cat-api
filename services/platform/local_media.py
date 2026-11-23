"""Private local storage for expiring provider inputs."""
import asyncio
import base64
import hashlib
import hmac
import logging
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.responses import FileResponse

from auth.models import StudioMediaLease
from config import settings

router = APIRouter()
LOCAL_BUCKET = "@local"
ROUTE = "/media/temporary/"
OBJECT = re.compile(r"[1-9][0-9]*/[a-f0-9]{32}\.[a-z0-9]{2,5}")
PREFIX = "studio-temporary/v1/"


def directory():
    root = Path(settings.STUDIO_TEMP_PATH).resolve()
    if root.is_relative_to(Path(settings.MEDIA_PATH).resolve()):
        raise HTTPException(503, "临时素材目录必须独立于公开媒体目录")
    return root


def path_for(key, expires_epoch):
    relative = key.removeprefix(PREFIX)
    if not key.startswith(PREFIX) or not OBJECT.fullmatch(relative):
        raise ValueError("invalid temporary object key")
    account, filename = relative.split("/")
    return directory() / account / f"{int(expires_epoch)}-{filename}"


def sweep_orphans():
    """Recover managed files left by a crash or database restore, including partial uploads."""
    root = directory()
    if not root.is_dir():
        return
    now = time.time()
    for account in root.iterdir():
        if not account.name.isdecimal() or account.is_symlink() or not account.is_dir():
            continue
        for file in account.iterdir():
            deadline, separator, filename = file.name.removesuffix(".part").partition("-")
            if (separator and deadline.isascii() and deadline.isdecimal() and len(deadline) <= 12
                    and int(deadline) <= now and OBJECT.fullmatch(f"{account.name}/{filename}")
                    and not file.is_symlink()):
                file.unlink(missing_ok=True)


def signature(method, key, expires, checksum):
    secret = settings.STUDIO_TEMP_SIGNING_KEY or settings.API_KEY_ENCRYPTION_KEY
    if not secret:
        raise HTTPException(503, "本地临时素材签名密钥尚未配置")
    return hmac.new(secret.encode(), f"cat-media-v1\n{method}\n{key}\n{expires}\n{checksum}".encode(), hashlib.sha256).hexdigest()


def signed_url(method, key, expires, checksum=""):
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    url = urlsplit(base)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise HTTPException(503, "需要配置 Cat API 公网 HTTPS 地址")
    if not base.endswith("/v1"):
        base += "/v1"
    query = urlencode({"expires":expires, "sig":signature(method, key, expires, checksum)})
    return base + ROUTE + key.removeprefix(PREFIX) + "?" + query


async def write_chunks(lease, checksum, chunks, expires):
    dest = path_for(lease.object_key, lease.expires_epoch)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    def check_space(size):
        if shutil.disk_usage(dest.parent).free < settings.STUDIO_TEMP_FREE_BYTES + size:
            raise HTTPException(507, "服务器临时空间不足")
    check_space(lease.byte_length)
    if dest.exists():
        raise HTTPException(409, "素材已上传")
    try:
        handle = partial.open("xb")
    except FileExistsError:
        raise HTTPException(409, "素材正在上传") from None
    try:
        total = 0
        digest = hashlib.md5(usedforsecurity=False)
        with handle:
            async for chunk in chunks:
                total += len(chunk)
                if total > lease.byte_length:
                    raise HTTPException(413, "上传长度超过申请值")
                if time.time() >= expires:
                    raise HTTPException(410, "上传已过期")
                check_space(len(chunk))
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
        if total != lease.byte_length or base64.b64encode(digest.digest()).decode() != checksum:
            raise HTTPException(422, "上传长度或校验和不匹配")
        if time.time() >= expires:
            raise HTTPException(410, "上传已过期")
        os.link(partial, dest)
    except FileExistsError:
        raise HTTPException(409, "素材已上传") from None
    finally:
        partial.unlink(missing_ok=True)


@router.api_route(ROUTE+"{relative:path}", methods=["PUT", "GET", "HEAD"], include_in_schema=False)
async def transfer(relative: str, request: Request, expires: int, sig: str):
    if not OBJECT.fullmatch(relative) or time.time() >= expires:
        raise HTTPException(404)
    key = PREFIX + relative
    method = "GET" if request.method == "HEAD" else request.method
    checksum = request.headers.get("content-md5", "") if method == "PUT" else ""
    if not re.fullmatch("[a-f0-9]{64}", sig) or not hmac.compare_digest(signature(method, key, expires, checksum), sig):
        raise HTTPException(403)
    lease = await StudioMediaLease.get_or_none(object_key=key, bucket=LOCAL_BUCKET, expires_epoch__gte=expires)
    if not lease:
        raise HTTPException(404)
    from services.platform.temporary_media import TYPES
    mime = next((t for t, suffix in TYPES.items() if key.endswith("."+suffix)), "application/octet-stream")
    if method == "PUT":
        if request.headers.get("content-length") != str(lease.byte_length):
            raise HTTPException(422, "上传长度不匹配")
        if TYPES.get(request.headers.get("content-type")) != relative.rsplit(".", 1)[1]:
            raise HTTPException(422, "上传类型不匹配")
        try:
            async with asyncio.timeout(max(0, lease.expires_epoch - time.time())):
                await write_chunks(lease, checksum, request.stream(), lease.expires_epoch)
        except TimeoutError:
            raise HTTPException(410, "上传已过期") from None
        return Response(status_code=204)
    dest = path_for(key, lease.expires_epoch)
    if not dest.is_file():
        raise HTTPException(404)
    return FileResponse(dest, media_type=mime, headers={"Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff"})


async def sweep_periodically():
    while True:
        try:
            await asyncio.to_thread(sweep_orphans)
        except (HTTPException, OSError):
            logging.getLogger(__name__).exception("Local temporary directory sweep deferred")
        await asyncio.sleep(60)


if __name__ == "__main__":
    sweep_orphans()
