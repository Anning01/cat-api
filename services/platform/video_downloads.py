"""Stream completed artifacts. External storage never receives a channel credential."""
import asyncio
from ipaddress import ip_address
import socket

from fastapi import HTTPException, Response
from fastapi.responses import RedirectResponse, StreamingResponse
import httpx

from auth.models import PlatformCallReceipt, PlatformVideoJob
from models.config import AiModelConfig
from services.oss.temporary import suppress_signed_queries
from services.platform.images import media_url
from services.platform.videos import route_hash, video_status
from services.video.unified import _endpoint


async def public_destination(url):
    """Pin this connection to a validated public address while retaining TLS identity."""
    target = httpx.URL(media_url(str(url)))
    async with asyncio.timeout(10):
        addresses = await asyncio.get_running_loop().getaddrinfo(
            target.host, target.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("invalid media destination")
    return target.copy_with(host=addresses[0][4][0]), {"Host": target.netloc.decode()}, {"sni_hostname": target.host}


async def download_video(ctx, identifier, request):
    result = await video_status(ctx, public_id=identifier, refresh=True)
    url = (result.get("metadata") or {}).get("url")
    if result["status"] != "completed" or not url:
        raise HTTPException(409, "Video is not ready")
    receipt = await PlatformCallReceipt.get(public_id=identifier, user_id=ctx.user.id)
    job = await PlatformVideoJob.get(receipt_id=receipt.id)
    if not job.inputs.get("stream_content"):
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})

    protected = url == f"/v1/videos/{identifier}/content"
    headers, extensions = {}, {}
    if protected:
        config = await AiModelConfig.get_or_none(id=receipt.model_config_id, scope="official")
        if not config or config.api_protocol != "openai_video" or route_hash(config) != job.route_hash:
            raise HTTPException(409, "Original content channel is unavailable")
        url = _endpoint(config.base_url, receipt.provider_id) + "/content"
        headers["Authorization"] = "Bearer " + config.api_key
    suppress_signed_queries()
    client = httpx.AsyncClient(timeout=60, trust_env=False)
    try:
        for _ in range(4):
            if not protected:
                destination, headers, extensions = await public_destination(url)
            else:
                destination = url
            if value := request.headers.get("range"):
                headers["Range"] = value
            outgoing = client.build_request(request.method, destination, headers=headers, extensions=extensions)
            outgoing.headers.pop("cookie", None)
            upstream = await client.send(outgoing, stream=True, follow_redirects=False)
            if request.method == "HEAD" and (upstream.status_code in {405, 501} or
                                              not protected and upstream.status_code == 403):
                # A signed GET lease may not authorize HEAD. Read the headers and close the stream.
                await upstream.aclose()
                fallback = client.build_request("GET", destination, headers=headers, extensions=extensions)
                fallback.headers.pop("cookie", None)
                upstream = await client.send(fallback, stream=True, follow_redirects=False)
            if not upstream.is_redirect:
                break
            await upstream.aclose()
            url = httpx.URL(url).join(upstream.headers["location"])
            protected = False
        if upstream.status_code not in {200, 206}:
            raise HTTPException(410 if upstream.status_code in {404, 410} else 502, "Video content unavailable")
        mime = upstream.headers.get("content-type", "").partition(";")[0].lower()
        if mime not in {"video/mp4", "application/octet-stream", "video/webm", "video/quicktime"}:
            raise HTTPException(502, "Invalid video content type")
        output = {k:v for k,v in upstream.headers.items() if k in {"content-type","accept-ranges","content-range"}}
        if "content-length" in upstream.headers and "content-encoding" not in upstream.headers:
            output["content-length"] = upstream.headers["content-length"]
        output.update({"cache-control":"private, no-store","x-content-type-options":"nosniff"})
        if request.method == "HEAD":
            await upstream.aclose()
            await client.aclose()
            return Response(headers=output, status_code=upstream.status_code)
    except BaseException as exc:
        await client.aclose()
        if isinstance(exc, (ValueError, KeyError, httpx.HTTPError, OSError)):
            raise HTTPException(502, "Video content unavailable") from None
        raise

    async def chunks():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=output)
