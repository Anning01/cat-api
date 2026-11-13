"""URL-only image generation; media bytes travel between clients, storage and suppliers."""
import asyncio
import json
import re
from ipaddress import ip_address
from math import gcd, isfinite
from typing import Literal

import httpx
from fastapi import HTTPException
from fastapi import Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator, model_validator

from auth.models import PlatformCallReceipt
from services.billing.catalog import IMAGE_PRICING
from services.image_generation.capabilities import capabilities_for, validate_protocol, validate_selection
from services.platform.calls import CALL_TIMEOUT, admit, record_measurement, preserve_result
from services.platform.http_contract import UpstreamResponseError, response_headers, redact_secret
from services.platform.request_data import reject_inline_media


def media_url(value):
    url = TypeAdapter(HttpUrl).validate_python(value)
    if url.scheme != "https" or url.username or url.password or not url.host or "." not in url.host or url.host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("需要可读取的公网 HTTPS 图片地址")
    try:
        ip = ip_address(url.host.strip("[]"))
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise ValueError("需要可读取的公网 HTTPS 图片地址")
    return str(url)


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    size: str | None = Field(None, max_length=32)
    aspect_ratio: str | None = Field(None, max_length=16)
    n: int = Field(1, gt=0)
    output_format: str = Field("png", max_length=10)
    image: str | list[str] = Field(default_factory=list)
    images: list[dict] | None = None
    input_references: list[dict] | None = None
    mask: dict | None = None
    frame_count: int | None = None
    frame_duration_ms: int | None = None
    response_format: Literal["url"] = "url"
    quality: str | None = None
    background: str | None = None
    moderation: str | None = None
    output_compression: int | None = Field(None, ge=0, le=100)
    layer_decomposition: bool = False
    style: str | None = None
    user: str | None = None
    stream: bool = False
    partial_images: int | None = Field(None, ge=0, le=3)

    @field_validator("image")
    @classmethod
    def public_references(cls, values):
        if isinstance(values, str):
            return media_url(values)
        return [media_url(v) for v in values]

    @model_validator(mode="after")
    def url_references(self):
        if sum(bool(v) for v in (self.image, self.images, self.input_references)) > 1:
            raise ValueError("Use only one reference image format")
        for item in self.images or []:
            if set(item) != {"image_url"}:
                raise ValueError("images must contain image_url objects from temporary uploads")
            media_url(item["image_url"])
        for item in self.input_references or []:
            if item.get("type") != "image_url" or not isinstance(item.get("image_url"), dict):
                raise ValueError("input_references must contain image_url references")
            media_url(item["image_url"].get("url"))
        if self.mask:
            if set(self.mask) != {"image_url"}:
                raise ValueError("mask must contain an image_url from temporary uploads")
            media_url(self.mask["image_url"])
        return self

    def reference_urls(self):
        if self.image:
            return [self.image] if isinstance(self.image, str) else self.image
        return [item["image_url"] for item in self.images or []] or [item["image_url"]["url"] for item in self.input_references or []]


def selection(config, body):
    caps = capabilities_for(config.image_model_type)
    size = body.get("size")
    if size == "auto":
        size = None
    ratio = body.get("aspect_ratio")
    if size and "x" in size:
        match = next(((tier, caps.aspect_ratios[sizes.index(size)]) for tier, sizes in caps.sizes.items() if size in sizes), None)
        if not match and config.api_protocol == "openai_compatible":
            try:
                width, height = (int(value) for value in size.split("x"))
                divisor = gcd(width, height)
                native_ratio = f"{width // divisor}:{height // divisor}"
                tier = next(tier for tier, sizes in caps.sizes.items()
                            if min(width, height) == int(sizes[0].split("x")[0]))
                if native_ratio in caps.aspect_ratios:
                    match = tier, native_ratio
            except (ValueError, StopIteration, ZeroDivisionError):
                pass
        if not match or ratio and ratio != match[1]:
            raise HTTPException(422, "尺寸与所选模型画幅不匹配")
        size, ratio = match
    return validate_selection(config.image_model_type, clarity=size, aspect_ratio=ratio,
        output_format=body["output_format"], generation_count=1, frame_count=body.get("frame_count"),
        frame_duration_ms=body.get("frame_duration_ms"))


def image_options(config, body):
    if 2 not in (config.task_types or [config.task_type]):
        raise HTTPException(422, "所选模型不支持图像生成")
    if config.api_protocol == "novelvids":
        raise HTTPException(422, "平台模型需要配置上游供应商")
    validate_protocol(config.image_model_type, config.api_protocol)
    if body.get("stream"):
        raise HTTPException(400, "Image results must use URLs; image binary streams are not supported")
    selected = selection(config, body)
    pricing = config.pricing or {}
    if pricing.get("type") == "image" and pricing.get("billing_unit") == "pixel_tier":
        expected = IMAGE_PRICING.get(config.image_model_type, {}).get("prices")
        prices = pricing.get("prices")
        if not expected or not isinstance(prices, dict) or prices.keys() != expected.keys() or not all(
            type(rate) in (int, float) and isfinite(rate) and rate >= 0 for rate in prices.values()
        ):
            raise HTTPException(422, "模型像素档位价格不完整")
        return pricing
    price = (pricing.get("prices") or {}).get(selected.clarity)
    if pricing.get("type") != "image" or type(price) not in (float, int) or not isfinite(price) or price < 0:
        raise HTTPException(422, "所选清晰度尚未配置图片价格")
    return pricing


def output_pixel_tier(size, model_type, layered):
    match = re.fullmatch(r"([1-9][0-9]{0,5})x([1-9][0-9]{0,5})", size or "")
    if not match:
        raise ValueError("Provider did not confirm output dimensions")
    pixels = int(match[1]) * int(match[2])
    low = pixels <= 2_610_000
    if model_type == "seedream_5_5":
        if pixels > 4_630_000:
            raise ValueError("Output exceeds configured pixel tiers")
        return "low" if low else "high_capped"
    return ("layer_" if layered else "single_") + ("low" if low else "high")


def needs_pixel_client(model_type, pricing):
    return model_type == "seedream_5_5" or (pricing or {}).get("billing_unit") == "pixel_tier"


async def generate(ctx, request, key, *, edit=False, protocol=None, legacy_studio=False):
    body = request.model_dump(exclude_none=True)
    def validate(config, values):
        if legacy_studio and needs_pixel_client(config.image_model_type, config.pricing):
            raise HTTPException(409, "此生图渠道需要新版工作台，请联系部署管理员升级")
        if protocol and config.api_protocol != protocol:
            raise HTTPException(422, "所选模型与接口协议不匹配")
        return image_options(config, values)
    config, receipt = await admit(ctx, request.model, body, key, validate=validate, kind="image")
    headers = {"X-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    selected = selection(config, body)
    references = request.reference_urls()
    payload = request.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    payload["model"] = config.model
    payload["response_format"] = "url"
    for field in ("images", "image", "input_references"):
        payload.pop(field, None)
    if config.api_protocol == "openai_compatible":
        upstream_path = "/images/edits" if edit or references else "/images/generations"
        if references:
            payload["images"] = request.images or [{"image_url":url} for url in references]
    elif config.api_protocol == "openrouter_compatible":
        upstream_path = "/images"
        if references:
            payload["input_references"] = request.input_references or [{"type":"image_url", "image_url":{"url":url}} for url in references]
    else:
        upstream_path = "/images/generations"
        if references:
            payload["image"] = request.image or references
    if request.size and "x" not in request.size and request.size != "auto" and config.api_protocol == "openai_compatible":
        payload["size"] = selected.provider_size
    if config.api_protocol == "openai_compatible":
        payload.pop("aspect_ratio", None)
    upstream_body = {"json":payload}
    provider_id = None
    client, upstream = None, None
    input_count = len(references)
    deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT
    try:
        client = httpx.AsyncClient(timeout=CALL_TIMEOUT, follow_redirects=False)
        async with asyncio.timeout_at(deadline):
            upstream = await client.send(client.build_request("POST", config.base_url.rstrip("/") + upstream_path,
                headers={"Authorization":"Bearer "+config.api_key}, **upstream_body), stream=True)
            provider_id = upstream.headers.get("x-request-id")
            max_bytes = 1024 * 1024
            length = upstream.headers.get("content-length")
            if length and int(length) > max_bytes:
                raise ValueError("Image response exceeds limit")
            payload = bytearray()
            async for chunk in upstream.aiter_bytes(chunk_size=16*1024):
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise ValueError("Image response exceeds limit")
        if upstream.status_code >= 400:
            state = "rejected" if upstream.status_code < 500 and upstream.status_code != 408 else "review"
            await PlatformCallReceipt.filter(id=receipt.id).update(state=state, provider_id=provider_id)
            raise UpstreamResponseError(httpx.Response(upstream.status_code, content=bytes(payload), headers={k:v for k,v in upstream.headers.items() if k not in {"content-encoding", "content-length"}}),
                str(receipt.public_id), config.api_key)
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("Missing image result")
        if raw.get("error"):
            await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected", provider_id=provider_id)
            raise UpstreamResponseError(httpx.Response(200, content=bytes(payload), headers={k:v for k,v in upstream.headers.items() if k not in {"content-encoding", "content-length"}}), str(receipt.public_id), config.api_key)
        try:
            reject_inline_media(raw)
        except HTTPException:
            await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="review", provider_id=provider_id)
            raise HTTPException(502, "供应商返回了不允许的内联媒体，请选择支持 URL 结果的通道", headers=headers) from None
        async def measure():
            items = raw.get("data", raw.get("images", []))
            pixel_billing = receipt.pricing.get("billing_unit") == "pixel_tier"
            layered = pixel_billing and request.layer_decomposition
            items = [item for item in items if not (isinstance(item, dict) and item.get("error") and not item.get("url"))]
            if not items:
                raise ValueError("Provider did not confirm generated image count")
            options = body.get("sequential_image_generation_options") or {}
            limit = options.get("max_images", request.n) if body.get("sequential_image_generation") == "auto" else request.n
            if not layered and (type(limit) is not int or len(items) > limit):
                raise ValueError("Provider returned more images than authorized; retain results for review")
            tier_counts = {}
            for item in items:
                url = item.get("url") if isinstance(item, dict) else item
                if not isinstance(url, str) or not url:
                    raise ValueError("Provider did not confirm generated image URL")
                if pixel_billing:
                    tier = output_pixel_tier(item.get("size"), config.image_model_type, layered)
                    tier_counts[tier] = tier_counts.get(tier, 0) + 1
            usage = {"image_count":len(items), "clarity":selected.clarity, "input_image_count":input_count}
            if pixel_billing:
                usage.update(output_tier_counts=tier_counts, layer_decomposition=layered)
            await record_measurement(receipt, usage, provider_id)
        await preserve_result(receipt, measure())
        return Response(redact_secret(bytes(payload), config.api_key), status_code=upstream.status_code,
                        headers=response_headers(upstream, receipt.public_id, config.api_key))
    except (HTTPException, UpstreamResponseError):
        raise
    except Exception:
        await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(state="review",provider_id=provider_id)
        raise HTTPException(502, "未能确认图片生成结果，请凭请求编号核对", headers=headers) from None
    finally:
        if upstream is not None:
            await upstream.aclose()
        if client is not None:
            await client.aclose()
