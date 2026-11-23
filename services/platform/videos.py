"""Durable public video jobs, provider reconciliation and account settlement."""
import asyncio
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import logging
from math import gcd
import re
from math import isfinite
import time
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from tortoise.transactions import in_transaction
from auth.models import PlatformCallReceipt, PlatformVideoJob
from models.config import AiModelConfig
from services.billing.pricing import compute_input_image_cost, compute_video_cost
from services.platform.calls import CALL_TIMEOUT, admit, digest, settle, require_video_price, video_price_resolution, request_keys
from services.platform.images import media_url
from services.platform.http_contract import UpstreamResponseError, public_upstream
from services.video import get_generator
from services.video.base import VideoProviderError
from services.video.capabilities import capabilities_for, validate_selection
from services.video.provider_http import REFERENCE_MEDIA_SIZE_ERROR, REFERENCE_MEDIA_SIZE_MESSAGE, structured_video_error
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)
IMAGE_REFERENCE_FORMATS = {'seedance_2': '@图片{}', 'seedance_2_mini': '@图片{}', 'seedance_2_fast': '@图片{}', 'seedance_2_5': '@图片{}', 'seedance_2_5_flash': '@图片{}', 'minimax_h3': '<Picture {}>', 'minimax_h3_autodl': '<Picture {}>', 'wan_3': '图{}'}


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image", "video", "audio"]
    role: Literal["reference", "first_frame", "last_frame"] = "reference"
    url: str
    @model_validator(mode="after")
    def validate_input(self):
        from services.platform.inline_media import media_input
        self.url = media_input(self.url, self.type)
        return self

class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field("sora-2", min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    input_reference: str | None = None
    seconds: str | None = Field(None, pattern=r"^[1-9][0-9]*$")
    size: str | None = Field(None, pattern=r"^[1-9][0-9]*x[1-9][0-9]*$")
    duration: int = Field(4, gt=0)
    resolution: str = "720p"
    aspect_ratio: str = "16:9"
    references: list[Reference] = Field(default_factory=list)
    generate_audio: bool | None = None
    return_last_frame: bool = False
    watermark: Literal[False] = False
    request_id: UUID | None = None
    _specified: set = PrivateAttr(default_factory=set)

    @model_validator(mode="after")
    def reference_roles(self):
        self._specified = set(self.model_fields_set)
        if not self.model_fields_set.intersection({"size", "aspect_ratio", "resolution", "duration"}):
            self.size = "720x1280"
        if self.seconds is not None:
            if "duration" in self.model_fields_set and self.duration != int(self.seconds):
                raise ValueError("seconds and duration must agree")
            self.duration = int(self.seconds)
        if self.size is not None:
            width, height = (int(value) for value in self.size.split("x"))
            divisor = gcd(width, height)
            ratio, resolution = f"{width // divisor}:{height // divisor}", f"{min(width, height)}p"
            for candidate in ("16:9", "9:16"):
                if self.size == video_size(resolution, candidate):
                    ratio = candidate
                    break
            if "aspect_ratio" in self.model_fields_set and self.aspect_ratio != ratio:
                raise ValueError("size and aspect_ratio must agree")
            if "resolution" in self.model_fields_set and self.resolution.lower() != resolution:
                raise ValueError("size and resolution must agree")
            self.aspect_ratio, self.resolution = ratio, resolution
        if self.input_reference:
            if self.references:
                raise ValueError("Use input_reference or references")
            self.references = [Reference(type="image", url=self.input_reference)]
        roles = [r.role for r in self.references]
        if any(r != "reference" for r in roles):
            if sorted(roles) != ["first_frame","last_frame"] or any(r.type != "image" for r in self.references):
                raise ValueError("首尾帧须分别提供一张图片")
        elif len({(r.type,r.url) for r in self.references}) != len(roles):
            raise ValueError("参考素材重复")
        return self


def video_options(config, body):
    if 4 not in (config.task_types or [config.task_type]) or config.api_protocol == "novelvids":
        raise HTTPException(422, "所选配置不是上游视频模型")
    refs = body["references"]
    mode = "keyframes" if any(r["role"]=="first_frame" for r in refs) else "reference"
    selected = validate_selection(config.video_model_type, api_protocol=config.api_protocol, generation_mode=mode,
        resolution=body["resolution"],aspect_ratio=body["aspect_ratio"],duration=body["duration"],output_format="mp4",
        generate_audio=body.get("generate_audio"),return_last_frame=body["return_last_frame"])
    caps = capabilities_for(config.video_model_type,config.api_protocol)
    counts = Counter(r["type"] for r in refs)
    if mode=="reference" and (counts["image"] > caps.max_reference_images or counts["video"] > caps.max_reference_videos
                              or counts["audio"] > caps.max_reference_audios):
        raise HTTPException(422, "参考素材数量超过所选模型限制")
    rates = config.pricing or {}
    require_video_price(rates, selected.resolution, has_video_reference=bool(counts["video"]))
    return rates


def route_hash(config):
    return digest([config.base_url,config.api_protocol,config.model,config.video_model_type])


async def submit_video(ctx, request, key, *, image=None):
    body = request.model_dump(mode="json",exclude_none=True)
    legacy_hash = digest(body)
    body["specified_size_fields"] = sorted(request._specified & {"resolution", "aspect_ratio", "size", "duration"})
    if image:
        body["file_sha256"] = hashlib.sha256(image[1]).hexdigest()
    def validate(config, _):
        if config.api_protocol == "autodl" and not request._specified.intersection({"size", "resolution"}):
            request.resolution = "768p"
            request.size = None
            if "aspect_ratio" not in request._specified:
                request.aspect_ratio = "16:9"
        # Older workbenches always serialize these two fields on fixed-spec JSON orders.
        legacy_workbench_order = request.request_id is not None and {
            "duration", "resolution", "aspect_ratio"
        }.issubset(request._specified) and not request._specified.intersection({"seconds", "size"})
        strict_switches = config.api_protocol == "openai_video" or (
            config.api_protocol == "autodl" and not legacy_workbench_order
        )
        if strict_switches and (request.generate_audio is not None or request.return_last_frame):
            raise HTTPException(422, "该视频渠道不支持切换音轨或返回尾帧")
        if config.api_protocol == "openai_video":
            if 4 not in (config.task_types or [config.task_type]) or config.video_model_type != "openai_video":
                raise HTTPException(422, "所选配置不是通用视频模型")
            from services.video.compatible import compatible_options
            caps = compatible_options(config.processing_options)
            if not request._specified.intersection({"size","resolution","aspect_ratio"}):
                defaults = VideoRequest(prompt=request.prompt, size=caps.sizes[0])
                request.size, request.resolution, request.aspect_ratio = defaults.size, defaults.resolution, defaults.aspect_ratio
            if not request._specified.intersection({"seconds","duration"}):
                request.duration = caps.seconds[0]
            size = request.size
            if size is None and re.fullmatch(r"[1-9][0-9]{0,3}:[1-9][0-9]{0,3}", request.aspect_ratio) and re.fullmatch(r"[1-9][0-9]{1,3}p", request.resolution):
                size = video_size(request.resolution, request.aspect_ratio)
            if size not in caps.sizes or request.duration not in caps.seconds:
                raise HTTPException(422, "所选通道不支持该尺寸或时长")
            if image and "file" not in caps.reference_inputs or request.references and (
                "url" not in caps.reference_inputs or len(request.references) != 1 or request.references[0].type != "image"
                or request.references[0].role != "reference"
            ):
                raise HTTPException(422, "不支持该参考素材")
            require_video_price(config.pricing or {}, request.resolution)
            return config.pricing
        options = request.model_dump()
        if image:
            options["references"] = [{"type": "image", "role": "reference"}]
        return video_options(config, options)

    if request.request_id and key and str(request.request_id) != key:
        raise HTTPException(422, "request_id 与 Idempotency-Key 不一致")
    key = str(request.request_id) if request.request_id else key

    async def replay():
        if not key:
            return None
        matches = await PlatformCallReceipt.filter(user_id=ctx.user.id, dedup_key__in=await request_keys(ctx.user.id,key)).limit(2)
        if not matches:
            return None
        if len(matches) != 1:
            raise HTTPException(409, "请使用原回执编号查询")
        previous = matches[0]
        from services.platform.access import authorize_model
        authorize_model(ctx, previous.model_config_id)
        hashes = {digest(body)} if image else {digest(body), legacy_hash}
        if previous.pricing.get("type") != "video" or previous.payload_hash not in hashes:
            raise HTTPException(409, "请求标识已用于不同的请求", headers={"X-Request-Id":str(previous.public_id), "X-Cat-Request-Id":str(previous.public_id)})
        prior_job = await PlatformVideoJob.get_or_none(receipt_id=previous.id)
        status = prior_job.status if prior_job else "queued"
        if previous.state in {"review","rejected"} and status!="completed":
            status="failed"
        return {**video_object(previous, prior_job, status=status), "billing_status":previous.state,
                "metadata":prior_job.output if prior_job else None}

    if previous_job := await replay():
        return previous_job
    try:
        async with in_transaction():
            config, receipt = await admit(ctx, request.model, body, key, validate=validate, kind="video")
            refs = request.references
            frames = {r.role:r.url for r in refs if r.role!="reference"}
            types = {kind:[r.url for r in refs if r.type==kind and r.role=="reference"] for kind in ("image","video","audio")}
            resolution = request.resolution if config.api_protocol == "openai_video" else next(r for r in capabilities_for(config.video_model_type,config.api_protocol).resolutions
                              if r.lower()==request.resolution.lower())
            job = await PlatformVideoJob.create(receipt=receipt,route_hash=route_hash(config),inputs={
                "duration":request.duration, "resolution":resolution, "stream_content":True, "input_image_count":int(image is not None) + len(frames) + len(types["image"]),
                "has_video_reference":bool(types["video"]), "public_model":request.model, "size":request.size or video_size(request.resolution, request.aspect_ratio)})
    except HTTPException as exc:
        if exc.status_code == 409 and (previous_job := await replay()):
            return previous_job
        raise
    label = IMAGE_REFERENCE_FORMATS.get(config.video_model_type, "[图{}]")
    prompt = re.sub(r"@image(\d+)", lambda m: label.format(int(m[1])), request.prompt)
    def media_label(match):
        kind, number = match.groups()
        if label.startswith("<Picture"):
            return f"<{kind.title()} {number}>"
        return ("@音频" if kind=="audio" else "@视频") + number
    prompt = re.sub(r"@(audio|video)(\d+)", media_label, prompt)
    try:
        if config.api_protocol == "autodl" and config.video_model_type == "minimax_h3_autodl":
            from services.platform.temporary_media import known_upload_bytes
            if await known_upload_bytes(ctx.user.id, [ref.url for ref in refs]) > 50 * 1024**2:
                raise VideoProviderError(f"{REFERENCE_MEDIA_SIZE_MESSAGE}（{REFERENCE_MEDIA_SIZE_ERROR}）")
        from services.platform.temporary_media import resolve_reference
        from services.platform.inline_media import decode_media
        from services.platform.video_uploads import store_video_reference
        for ref in refs:
            ref.url = await resolve_reference(ctx.user.id, ref.url)
            if ref.url.startswith("data:") and config.api_protocol in {"openai_video", "autodl"}:
                mime, content = decode_media(ref.url, ref.type)
                if config.api_protocol == "openai_video" and len(refs) == 1 and ref.type == "image" and ref.role == "reference":
                    image = ("reference." + mime.split("/")[1], content, mime)
                    continue
                ref.url = await store_video_reference(ctx.user.id, ("reference", content, mime))
        frames = {r.role:r.url for r in refs if r.role!="reference"}
        types = {kind:[r.url for r in refs if r.type==kind and r.role=="reference"
                       and not (image and r.url.startswith("data:"))] for kind in ("image","video","audio")}
        if image and config.api_protocol != "openai_video":
            types["image"] = [await store_video_reference(ctx.user.id, image)]
        with public_upstream(str(receipt.public_id), config.api_key):
            async with asyncio.timeout(CALL_TIMEOUT):
                upstream_id = await get_generator(config).submit(prompt=request.prompt if config.api_protocol == "openai_video" else prompt,
                    size=job.inputs["size"], reference_file=image, platform_request_key=receipt.public_id, duration=request.duration,
                    resolution=resolution, aspect_ratio=request.aspect_ratio, output_format="mp4", generate_audio=request.generate_audio,
                    return_last_frame=request.return_last_frame, generation_mode="keyframes" if frames else "reference",
                    first_frame_url=frames.get("first_frame"),last_frame_url=frames.get("last_frame"),reference_images=types["image"],
                    reference_videos=types["video"], reference_audios=types["audio"],user_id=ctx.user.id)
        if not upstream_id:
            raise ValueError("missing upstream task")
        await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(provider_id=upstream_id,state="processing")
    except (Exception, asyncio.CancelledError) as exc:
        definite = isinstance(exc, HTTPException) or (isinstance(exc,VideoProviderError) and not exc.submission_uncertain) or (
            isinstance(exc,UpstreamResponseError) and exc.status < 500 and exc.status != 408)
        error = {}
        if definite:
            if isinstance(exc, UpstreamResponseError):
                try:
                    error = structured_video_error(json.loads(exc.content), secrets=(config.api_key,))
                except ValueError:
                    pass  # The original HTTP response still reaches the caller.
            else:
                error = structured_video_error({"message": str(exc)}, secrets=(config.api_key,))
        async with in_transaction():
            if error:
                await PlatformVideoJob.filter(id=job.id).update(status="failed", output={"error": error})
            await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(state="rejected" if definite else "review")
        if isinstance(exc, asyncio.CancelledError):
            raise
        if isinstance(exc, UpstreamResponseError):
            raise
        if isinstance(exc, HTTPException):
            raise HTTPException(exc.status_code, exc.detail, headers={**(exc.headers or {}),
                "X-Request-Id":str(receipt.public_id), "X-Cat-Request-Id":str(receipt.public_id)}) from None
        if message := error.get("message"):
            code = error.get("code")
            detail = f"{message}（{code}）" if code else message
            raise HTTPException(422, detail, headers={"X-Request-Id": str(receipt.public_id)}) from None
        raise HTTPException(422 if definite else 502,"未能确认视频提交，请凭请求编号核对",
                            headers={"X-Request-Id":str(receipt.public_id)}) from None
    return video_object(receipt, job)


def video_size(resolution, aspect_ratio):
    side = int(re.sub(r"\D", "", resolution))
    if resolution.lower() == "4k":
        side = 2160
    if aspect_ratio == "adaptive":
        return "auto"
    width, height = (int(value) for value in aspect_ratio.split(":"))
    return f"{round(side * width / min(width, height))}x{round(side * height / min(width, height))}"


def video_object(receipt, job, *, status=None):
    inputs = job.inputs if job else {}
    state = status or job.status
    return {"id":str(receipt.public_id), "object":"video", "model":inputs.get("public_model", receipt.model),
            "status":state, "progress":job.progress if job else 0,
            "created_at":int(receipt.created_at.timestamp()),
            "completed_at":int(job.updated_at.timestamp()) if job and state == "completed" else None,
            "seconds":str(inputs.get("duration", 4)), "size":inputs.get("size", "1280x720"),
            "error":(job.output or {}).get("error") if job and state == "failed" else None}


def nonnegative(value):
    return type(value) in {int,float} and isfinite(value) and value >= 0


def measured(inputs, metadata, rates):
    raw = metadata.get("usage") or {}
    seconds = metadata.get("duration")
    if seconds is None:
        seconds = inputs["duration"]  # Fixed-duration order; auto duration is not accepted here.
    if not nonnegative(seconds) or seconds <= 0:
        return None
    usage = {**{k:v for k,v in inputs.items() if k not in {"stream_content", "poll_errors"}}, "seconds":seconds, "duration_source":"provider" if metadata.get("duration") is not None else "order"}
    tokens = raw.get("completion_tokens") if isinstance(raw,dict) else None
    if rates.get("billing_unit") != "second" and type(tokens) is int and tokens > 0:
        return {**usage,"video_tokens":tokens}
    inp = raw.get("input_video_duration") if isinstance(raw,dict) else None
    if inputs["has_video_reference"] and not nonnegative(inp):
        return None
    return {**usage,"input_video_seconds":inp if inputs["has_video_reference"] else 0}


def video_cost(usage,rates):
    resolution = video_price_resolution(usage["resolution"])
    rates = {**rates, **{name:{video_price_resolution(k):v for k,v in rates[name].items()}
                         for name in ("prices","video_reference_prices") if rates.get(name)}}
    require_video_price(rates, resolution, has_video_reference=usage["has_video_reference"])
    if "video_tokens" in usage:
        prices = (rates.get("video_reference_prices") or rates["prices"]) if usage["has_video_reference"] else rates["prices"]
        charge = Decimal(usage["video_tokens"]) * Decimal(str(prices[resolution])) / Decimal(1000000)
        charge *= Decimal(str(rates.get("discount") or 1))
        return charge.quantize(Decimal("0.000001"),rounding=ROUND_HALF_UP) + compute_input_image_cost(usage["input_image_count"],rates)
    return compute_video_cost(usage["seconds"],resolution,rates,usage["input_video_seconds"],
                              usage["has_video_reference"],usage["input_image_count"])


async def refresh_job(job, receipt, *, renew=False):
    if job.inputs.get("native_protocol"):
        from services.platform.native import reconcile
        claimed = await PlatformVideoJob.filter(id=job.id, poll_after__lte=int(time.time())).update(poll_after=int(time.time())+CALL_TIMEOUT+15)
        if claimed:
            await reconcile(job, receipt)
        return
    now = int(time.time())
    token = uuid4()
    statuses = ["completed"] if renew else ["queued", "in_progress"]
    claimed = await PlatformVideoJob.filter(id=job.id,status__in=statuses,poll_after__lte=now).update(
        poll_token=token,poll_after=now+100)
    if not claimed:
        return
    config = await AiModelConfig.get_or_none(id=receipt.model_config_id,scope="official")
    ours = PlatformVideoJob.filter(id=job.id,poll_token=token)
    if config and route_hash(config) != job.route_hash:
        from services.video.ark_migration import legacy_query_config
        previous = legacy_query_config(config)
        if previous and route_hash(previous) == job.route_hash:
            config = previous
    if not config or route_hash(config)!=job.route_hash:
        if renew:
            await ours.update(poll_token=None, poll_after=now+60)
            return
        async with in_transaction():
            if await ours.update(status="failed",poll_token=None):
                await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(state="review")
        return
    try:
        with public_upstream(str(receipt.public_id), config.api_key):
            async with asyncio.timeout(90):
                result = await get_generator(config).query(receipt.provider_id)
        status = TaskStatusEnum(result["status"])
        metadata = result.get("metadata") or {}
        if renew and status != TaskStatusEnum.completed:
            await ours.update(poll_after=now+30,poll_token=None)
            return
        if status == TaskStatusEnum.completed:
            try:
                if config.api_protocol == "openai_video" and metadata.get("protected_content"):
                    output = {"url": f"/v1/videos/{receipt.public_id}/content"}
                else:
                    output = {"url":media_url(result.get("url"))}
                if metadata.get("last_frame_url"):
                    output["last_frame_url"] = media_url(metadata["last_frame_url"])
            except ValueError:
                if renew:
                    await ours.update(poll_after=now+30,poll_token=None)
                else:
                    async with in_transaction():
                        if await ours.update(status="failed",poll_token=None):
                            await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(state="review")
                return
            if renew:
                await ours.update(output={**(job.output or {}),**output},poll_after=now+30,poll_token=None)
                return
            usage = measured(job.inputs,metadata,receipt.pricing)
            if usage:
                output["duration"] = usage["seconds"]
            async with in_transaction():
                if await ours.update(status="completed",progress=100,output=output,poll_after=now+15,poll_token=None):
                    await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(
                        state="measured" if usage else "review", usage=usage)
            if usage:
                await settle(receipt.id)
        elif status in (TaskStatusEnum.failed,TaskStatusEnum.cancelled):
            async with in_transaction():
                error = metadata.get("error") or {"code":"video_generation_failed", "message":result.get("error") or "Video generation failed"}
                if not isinstance(error, dict):
                    error = {"code":"video_generation_failed", "message":str(error)}
                param = error.get("param")
                error = structured_video_error({"error":error}, secrets=(config.api_key,)) or {"code":"video_generation_failed"}
                if isinstance(param, str) and re.fullmatch(r"[a-z][a-z0-9_.]{0,63}", param):
                    error["param"] = param
                if await ours.update(status="failed",output={"error":error},poll_token=None):
                    await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(state="rejected")
        else:
            await ours.update(status="queued" if status==TaskStatusEnum.queued else "in_progress",
                              inputs={**job.inputs, "poll_errors":0}, progress=result.get("progress") or 0,poll_after=now+5,poll_token=None)
    except Exception as exc:
        errors = job.inputs.get("poll_errors", 0) + 1
        if errors >= 8 and not renew:
            async with in_transaction():
                if await ours.update(status="failed", poll_token=None):
                    await PlatformCallReceipt.filter(id=receipt.id, state="processing").update(state="review")
        else:
            await ours.update(inputs={**job.inputs, "poll_errors":errors}, poll_after=int(time.time())+15, poll_token=None)
        if isinstance(exc, UpstreamResponseError):
            raise
        logger.warning("Video status check deferred: receipt=%s",receipt.public_id)


async def video_status(ctx, public_id=None, key=None, *, refresh=False):
    lookup = {"dedup_key__in":await request_keys(ctx.user.id,key)} if key else {"public_id":public_id}
    rows = await PlatformCallReceipt.filter(user_id=ctx.user.id,**lookup).limit(2)
    if len(rows) > 1:
        raise HTTPException(409,"旧请求标识对应多条记录，请使用原请求编号查询")
    receipt = rows[0] if rows else None
    job = await PlatformVideoJob.get_or_none(receipt_id=receipt.id) if receipt else None
    if not job:
        raise HTTPException(404,"视频请求不存在")
    from services.platform.access import authorize_model
    authorize_model(ctx, receipt.model_config_id)
    if receipt.state=="processing" or refresh and job.status=="completed":
        await refresh_job(job,receipt,renew=job.status=="completed")
        await job.refresh_from_db()
        await receipt.refresh_from_db()
    status = "failed" if job.status!="completed" and receipt.state in {"review","rejected"} else job.status
    return {**video_object(receipt, job, status=status), "metadata":job.output, "billing_status":receipt.state}


async def reconcile_videos():
    while True:
        try:
            jobs = await PlatformVideoJob.filter(status__in=["queued","in_progress"],receipt__state="processing",
                       poll_after__lte=int(time.time())).order_by("poll_after","id").limit(16).select_related("receipt")
            await asyncio.gather(*(refresh_job(job,job.receipt) for job in jobs))
        except Exception:
            logger.warning("Platform video reconciliation deferred")
        await asyncio.sleep(3)
