"""Provider-native JSON forwarding. Only routing, ownership and accounting are platform concerns."""
import json
import logging
import time
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException, Response

from auth.models import PlatformCallReceipt, PlatformVideoJob
from models.config import AiModelConfig
from services.platform.access import authorize_model
from services.platform.calls import CALL_TIMEOUT, admit, digest, preserve_result, settle, require_video_price, video_price_resolution
from services.platform.http_contract import redact_secret, response_headers
from services.platform.images import media_url
from services.platform.request_data import reject_inline_media

logger = logging.getLogger(__name__)
PROTOCOLS = {
    "volcengine_ark": ("video", "/contents/generations/tasks"),
    "minimax": ("video", "/v2/video_generation"),
    "dashscope": ("video", "/api/v1/services/aigc/video-generation/video-synthesis"),
    "autodl": ("video", "/api/v1/comfyui/comfyui_workflow"),
    "volcengine_mediakit": ("media_processing", "/api/v1/tools/enhance-video-generative"),
    "volcengine_openspeech": ("asr", "/api/v3/auc/bigmodel/submit"),
}
TASK_TYPES = {"video":4, "media_processing":8, "asr":9}


def routing_hash(config):
    return digest([config.base_url, config.api_protocol, config.model])


def endpoint(config, protocol, task_id=None):
    root = config.base_url.rstrip("/")
    if protocol == "volcengine_ark":
        root = root.split("/contents/generations/tasks", 1)[0]
        path = "/contents/generations/tasks"
    elif protocol == "minimax":
        from services.video.minimax import _minimax_endpoint
        return _minimax_endpoint(root, "query" if task_id else "submit", task_id)
    elif protocol == "dashscope":
        from services.video.wan import _wan_endpoint
        return _wan_endpoint(root, "query" if task_id else "submit", task_id)
    elif protocol == "autodl":
        from services.video.autodl import _workflow_endpoint
        root = _workflow_endpoint(root)
        return root + ("/result/" + quote(task_id, safe="") if task_id else "/" + quote(config.model, safe=""))
    elif protocol == "volcengine_mediakit":
        root = root.split("/api/v1/", 1)[0]
        path = "/api/v1/tasks" if task_id else "/api/v1/tools/enhance-video-generative"
    else:
        root = root.split("/api/v3/auc/bigmodel", 1)[0]
        return root + "/api/v3/auc/bigmodel/" + ("query" if task_id else "submit")
    return root + path + ("/" + quote(task_id, safe="") if task_id else "")


def provider_headers(config, protocol, task_id=None, incoming=None):
    incoming = incoming or {}
    if protocol == "volcengine_openspeech":
        raw = config.api_key
        separator = ":" if ":" in raw else ";" if ";" in raw else None
        app, token = raw.split(separator, 1) if separator else ("", raw)
        headers = {"X-Api-Resource-Id":config.model, "X-Api-Request-Id":task_id,
                   "X-Api-Sequence":incoming.get("x-api-sequence", "-1")}
        headers.update({"X-Api-App-Key":app.strip(), "X-Api-Access-Key":token.strip()} if app else {"X-Api-Key":token})
        return headers
    headers = {"Authorization":config.api_key if protocol == "autodl" else "Bearer " + config.api_key}
    if protocol == "dashscope":
        headers["X-DashScope-Async"] = "enable"
        for name in ("x-dashscope-ossresourceresolve", "x-dashscope-data-inspection"):
            if incoming.get(name):
                headers[name] = incoming[name]
    return headers


def numeric(value):
    from math import isfinite
    return type(value) in {int, float} and isfinite(value) and value >= 0


def validate_urls(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if (key == "url" or key.endswith("_url") or key.startswith(("ref_image_", "ref_audio_"))) and isinstance(child, str):
                # Provider-side file IDs and oss:// references are not temporary-upload URLs.
                media_url(child)
            else:
                validate_urls(child)
    elif isinstance(value, list):
        for item in value:
            validate_urls(item)


def validate_native(config, body, protocol):
    kind = PROTOCOLS[protocol][0]
    if config.api_protocol != protocol or TASK_TYPES[kind] not in (config.task_types or [config.task_type]):
        raise HTTPException(422, "所选模型与原生接口协议不匹配")
    pricing = config.pricing or {}
    if pricing.get("type") != kind:
        raise HTTPException(422, "所选模型尚未配置调用价格")
    if kind == "video":
        parameters = body.get("parameters") or {}
        resolution = parameters.get("resolution") if protocol == "dashscope" else body.get("resolution")
        if resolution is None:
            from services.video.capabilities import capabilities_for
            if config.video_model_type:
                resolution = capabilities_for(config.video_model_type, protocol).default_resolution
            else:
                # Unregistered test/legacy configurations can only infer a single published tier.
                tiers = pricing.get("prices") or {}
                if len(tiers) != 1:
                    raise HTTPException(422, "请明确指定已配置价格的分辨率")
                resolution = next(iter(tiers))
        inputs = accounting_inputs(body, protocol)
        require_video_price(pricing, resolution, has_video_reference=inputs["has_video_reference"])
    if kind == "asr":
        if not numeric(pricing.get("price_per_minute")):
            raise HTTPException(422, "所选模型尚未配置识别价格")
        audio = body.get("audio") or {}
        if not isinstance(audio, dict) or audio.get("data") or not audio.get("url"):
            raise HTTPException(422, "语音识别请使用临时上传后的 audio.url")
    if kind == "media_processing":
        from services.video_enhancement.contract import EnhancementPricing
        EnhancementPricing.model_validate(pricing)
        if not body.get("video_url"):
            raise HTTPException(422, "画质增强需要 video_url")
    try:
        validate_urls(body)
    except ValueError:
        raise HTTPException(422, "媒体参数需要临时上传后的公网 HTTPS URL") from None
    return pricing


async def send(config, protocol, *, task_id=None, body=None, incoming=None, query=None):
    headers = provider_headers(config, protocol, task_id or (incoming or {}).get("x-api-request-id") or str(uuid4()), incoming)
    method = "POST" if not task_id or protocol == "volcengine_openspeech" else "GET"
    async with httpx.AsyncClient(timeout=CALL_TIMEOUT, follow_redirects=False) as client:
        request = client.build_request(method, endpoint(config, protocol, task_id), headers=headers,
                                       params=query or None, **({"json":body if body is not None else {}} if method == "POST" else {}))
        response = await client.send(request, stream=True)
        try:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 4 * 1024 * 1024:
                    raise HTTPException(502, "供应商元数据超出转发上限")
            return httpx.Response(response.status_code, content=bytes(content),
                                  headers={k:v for k,v in response.headers.items() if k not in {"content-encoding", "content-length"}})
        finally:
            await response.aclose()


def json_object(response):
    try:
        body = response.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def business_failed(protocol, data, response):
    if response.status_code >= 400 or data.get("error") or data.get("success") is False:
        return True
    if protocol == "volcengine_openspeech":
        return response.headers.get("x-api-status-code", "20000000") not in {"20000000", "20000001", "20000002"}
    if protocol == "minimax":
        return bool((data.get("base_resp") or {}).get("status_code"))
    if protocol == "autodl":
        return data.get("code", "Success") not in {"Success", 0, 200, "0", "200"}
    return bool(data.get("code")) and "output" not in data


def raw_response(response, receipt, config):
    secret = config.api_key
    secrets = [secret]
    if config.api_protocol == "volcengine_openspeech":
        separator = ":" if ":" in secret else ";" if ";" in secret else None
        if separator:
            secrets.append(secret.split(separator, 1)[1].strip())
    # Reject inline media in either direction, even if an upstream disregards URL-only requests.
    if response.status_code < 400:
        try:
            reject_inline_media(json_object(response))
        except HTTPException:
            raise HTTPException(502, "供应商返回了不允许的内联媒体，请选择支持 URL 结果的通道") from None
    content = response.content
    for value in secrets:
        content = redact_secret(content, value)
    headers = response_headers(response, receipt.public_id, secret)
    headers = {name:value for name,value in headers.items() if not any(token and token in value for token in secrets)}
    return Response(content, status_code=response.status_code, headers=headers)


def task_identifier(protocol, data, supplied=None):
    if protocol == "volcengine_ark":
        return data.get("id")
    if protocol == "autodl":
        return (data.get("data") or {}).get("task_id")
    if protocol == "dashscope":
        return (data.get("output") or {}).get("task_id")
    return data.get("task_id") or (supplied if protocol == "volcengine_openspeech" else None)


def accounting_inputs(body, protocol):
    parameters = body.get("parameters") or {}
    content = body.get("content") or (body.get("input") or {}).get("media") or []
    images = sum(item.get("type") in {"image", "image_url"} for item in content if isinstance(item, dict))
    videos = any(item.get("type") in {"video", "video_url"} for item in content if isinstance(item, dict))
    images += sum(key.startswith("ref_image_") for key in body)
    return {"native_protocol":protocol, "duration":body.get("duration", parameters.get("duration")),
            "resolution":video_price_resolution(body.get("resolution", parameters.get("resolution"))) if body.get("resolution", parameters.get("resolution")) is not None else None, "fps":body.get("fps"),
            "input_image_count":images, "has_video_reference":videos}


async def submit(ctx, protocol, body, *, model=None, key=None, incoming=None):
    incoming = incoming or {}
    identifier = incoming.get("x-api-request-id") if protocol == "volcengine_openspeech" else None
    if protocol == "volcengine_openspeech" and not identifier:
        raise HTTPException(400, "缺少 X-Api-Request-Id")
    selector = incoming.get("x-cat-model") or model or body.get("model") or incoming.get("x-api-resource-id")
    if not isinstance(selector, str) or not selector:
        raise HTTPException(400, "请用 model 或 X-Cat-Model 指定模型目录 ID")
    for part in body.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "draft_task":
            reference = part.get("draft_task") or {}
            reference_id = reference.get("id") if isinstance(reference, dict) else reference
            if not isinstance(reference_id, str):
                raise HTTPException(422, "draft_task 缺少任务 ID")
            await find_task(ctx, reference_id, [protocol])
    config, receipt = await admit(ctx, selector, {"protocol":protocol, "body":body, "native_task_id":identifier}, key or identifier,
        validate=lambda c, _:validate_native(c, body, protocol), kind=PROTOCOLS[protocol][0])
    payload = dict(body)
    if protocol in {"volcengine_ark", "minimax", "dashscope"}:
        payload["model"] = config.model
    try:
        response = await send(config, protocol, body=payload, incoming=incoming)
        data = json_object(response)
        try:
            forwarded = raw_response(response, receipt, config)
        except HTTPException:
            await PlatformCallReceipt.filter(id=receipt.id).update(state="review")
            raise
        async def track():
            if business_failed(protocol, data, response):
                await PlatformCallReceipt.filter(id=receipt.id).update(state="rejected" if response.status_code < 500 else "review")
            else:
                task_id = task_identifier(protocol, data, identifier)
                if isinstance(task_id, str) and task_id and len(task_id) <= 255:
                    await PlatformCallReceipt.filter(id=receipt.id).update(state="processing", provider_id=task_id)
                    inputs = accounting_inputs(body, protocol)
                    # IDs and billable quantities only: no prompts, transcripts or signed media URLs persist here.
                    await PlatformVideoJob.create(receipt=receipt, route_hash=routing_hash(config), inputs=inputs,
                        poll_after=int(time.time())+5)
                else:
                    await PlatformCallReceipt.filter(id=receipt.id).update(state="review")
        await preserve_result(receipt, track())
        return forwarded
    except (httpx.HTTPError, TimeoutError):
        await PlatformCallReceipt.filter(id=receipt.id).update(state="review")
        raise HTTPException(502, "未能确认供应商提交结果，请查询调用回执", headers={"X-Cat-Request-Id":str(receipt.public_id)}) from None


async def find_task(ctx, task_id, protocols, model=None):
    rows = await PlatformCallReceipt.filter(user_id=ctx.user.id, provider_id=task_id).order_by("-id")
    matches = []
    for receipt in rows:
        job = await PlatformVideoJob.get_or_none(receipt_id=receipt.id)
        if job and job.inputs.get("native_protocol") in protocols:
            candidate = await AiModelConfig.filter(id=receipt.model_config_id).only("public_alias").first() if model else None
            alias = candidate.public_alias if candidate else None
            if not model or model == f"nv-{receipt.model_config_id}" or model.lower() == alias:
                matches.append((receipt, job))
    if not matches:
        raise HTTPException(404, "任务不存在")
    if len(matches) > 1:
        raise HTTPException(409, "任务编号对应多个通道，请用 X-Cat-Model 指定模型目录 ID")
    receipt, job = matches[0]
    authorize_model(ctx, receipt.model_config_id)
    config = await AiModelConfig.get_or_none(id=receipt.model_config_id, scope="official")
    if not config or routing_hash(config) != job.route_hash:
        raise HTTPException(409, "任务原通道已变更，请恢复原通道后查询")
    return receipt, job, config


def result_status(protocol, data, response):
    if protocol == "volcengine_openspeech":
        code = response.headers.get("x-api-status-code")
        return "completed" if code == "20000000" else "processing" if code in {"20000001", "20000002"} else "failed" if code else "review"
    values = data.get("data") if protocol == "autodl" else data.get("output") if protocol == "dashscope" else data
    state = str((values or {}).get("task_status", (values or {}).get("status", ""))).lower()
    if state in {"succeeded", "completed", "success"}:
        return "completed"
    if state in {"failed", "error", "cancelled", "canceled", "expired", "unknown"}:
        return "failed"
    return "processing" if state in {"queued", "pending", "running", "processing", "in_progress"} else "review"


def measurement(job, data):
    protocol = job.inputs["native_protocol"]
    if protocol == "volcengine_openspeech":
        milliseconds = (data.get("audio_info") or {}).get("duration")
        return {"seconds":milliseconds / 1000} if numeric(milliseconds) and milliseconds > 0 else None
    values = data.get("output") if protocol == "dashscope" else data.get("data") if protocol == "autodl" else data
    values = values or {}
    if protocol == "volcengine_mediakit":
        result = data.get("result") or {}
        from services.video_enhancement.contract import resolution_short_side
        side = resolution_short_side(str(result.get("resolution") or job.inputs.get("resolution") or ""))
        duration, fps = result.get("duration"), result.get("fps")
        return {"seconds":duration, "short_side":side, "fps":fps} if numeric(duration) and duration > 0 and side and numeric(fps) and fps > 0 else None
    from services.platform.videos import measured
    rates = job.receipt.pricing
    usage = data.get("usage") or values.get("usage") or {}
    resolution = values.get("resolution") or usage.get("SR") or job.inputs.get("resolution")
    tiers = rates.get("prices") or {}
    matching = next((key for key in tiers if key.lower() == str(resolution).lower() or key.lower() == f"{resolution}p".lower()), None)
    if not matching:
        return None
    inputs = {**job.inputs, "resolution":matching}
    duration = values.get("duration") if protocol != "autodl" else None
    duration = usage.get("output_video_duration", usage.get("duration", duration))
    if duration is None:
        duration = inputs.get("duration")
    if not numeric(duration) or duration <= 0:
        return None
    return measured(inputs, {"duration":duration, "usage":usage}, rates)


async def account_result(job, receipt, data, response):
    protocol = job.inputs["native_protocol"]
    state = result_status(protocol, data, response)
    if state == "processing":
        await PlatformVideoJob.filter(id=job.id).update(poll_after=int(time.time())+15)
        return
    async def update():
        if state == "review":
            await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="review")
            return
        if state == "failed":
            await PlatformVideoJob.filter(id=job.id).update(status="failed")
            await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="rejected")
            return
        job.receipt = receipt
        usage = measurement(job, data)
        await PlatformVideoJob.filter(id=job.id).update(status="completed", progress=100)
        if usage:
            await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="measured", usage=usage)
            await settle(receipt.id)
        else:
            await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="review")
    await preserve_result(receipt, update())


async def query(ctx, task_id, protocols, *, incoming=None, query_params=None):
    incoming = incoming or {}
    receipt, job, config = await find_task(ctx, task_id, protocols, incoming.get("x-cat-model"))
    protocol = job.inputs["native_protocol"]
    try:
        response = await send(config, protocol, task_id=task_id, incoming=incoming, query=query_params)
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(502, "供应商任务查询暂时不可用，请稍后重试") from None
    try:
        forwarded = raw_response(response, receipt, config)
    except HTTPException:
        await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="review")
        raise
    if response.status_code < 400:
        await account_result(job, receipt, json_object(response), response)
    return forwarded


async def reconcile(job, receipt):
    config = await AiModelConfig.get_or_none(id=receipt.model_config_id, scope="official")
    if not config or routing_hash(config) != job.route_hash:
        return
    try:
        response = await send(config, job.inputs["native_protocol"], task_id=receipt.provider_id)
        if response.status_code < 400:
            try:
                raw_response(response, receipt, config)
            except HTTPException:
                await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="review")
                return
            await account_result(job, receipt, json_object(response), response)
    except Exception:
        logger.warning("Native task reconciliation deferred receipt=%s", receipt.public_id)
    finally:
        await PlatformVideoJob.filter(id=job.id).update(poll_after=int(time.time())+15, poll_token=None)
