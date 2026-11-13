"""Admit a developer request once and atomically settle a provider-reported usage snapshot."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from types import SimpleNamespace
from math import isfinite
import re
from uuid import uuid4

from fastapi import HTTPException
from tortoise.expressions import F, Q
from tortoise.transactions import in_transaction

from auth.models import PlatformCallReceipt
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.balance import consume, ensure_solvent
from services.platform.access import authorize_model
from services.billing.pricing import compute_image_cost, compute_input_image_cost, compute_pixel_tier_cost, compute_text_cost
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message

logger = logging.getLogger(__name__)
CALL_TIMEOUT = 600


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


async def request_keys(user_id, key):
    scopes = await PlatformCallReceipt.filter(user_id=user_id, legacy_scope_id__not_isnull=True).distinct().values_list('legacy_scope_id', flat=True)
    return [digest([user_id, str(key)]), *[digest([scope, user_id, str(key)]) for scope in scopes]]


def text_pricing(config):
    rates = config.pricing or {}
    if rates.get("type") != "text" or not all(
        type(rates.get(k)) in {float, int} and isfinite(rates[k]) and rates[k] >= 0
        for k in ("input_price_per_1m", "output_price_per_1m")
    ):
        raise HTTPException(422, "所选模型尚未配置文本调用价格")
    return rates


def video_price_resolution(value):
    # AutoDL's documented workflow values can include an orientation suffix.
    return re.sub(r"(?:横|竖|\(1:1\))$", "", str(value)).lower()


def require_video_price(rates, resolution, *, has_video_reference=False):
    """Missing/zero output tariffs disable a tier; free input references remain legitimate."""
    prices = rates.get("prices") or {}
    selected = next((key for key in prices if video_price_resolution(key) == video_price_resolution(resolution)), None)
    def valid(value, *, zero=False):
        return type(value) in {int, float} and isfinite(value) and (value >= 0 if zero else value > 0)
    if rates.get("type") != "video" or selected is None or not valid(prices[selected]):
        raise HTTPException(422, "该分辨率未配置有效的视频收费价格，暂不可调用")
    if has_video_reference:
        references = rates.get("video_reference_prices") or prices
        reference = next((key for key in references if video_price_resolution(key) == video_price_resolution(resolution)), None)
        if reference is None or not valid(references[reference], zero=rates.get("billing_unit") == "second"):
            raise HTTPException(422, "该分辨率未配置有效的参考视频收费价格，暂不可调用")
    return selected


def chat_options(config, body):
    if not set(config.task_types or [config.task_type]).intersection({1,3,5,6,7,10,11}):
        raise HTTPException(422, "该模型不支持对话请求")
    if body.get("tools") and not config.supports_tool_calls:
        raise HTTPException(422, "该模型配置未启用工具调用")
    if (body.get("response_format") or {}).get("type") in {"json_object", "json_schema"} and not config.supports_json_output:
        raise HTTPException(422, "该模型配置未启用结构化输出")
    requested = body.get("max_tokens") or body.get("max_completion_tokens")
    if requested and config.max_tokens and requested > config.max_tokens:
        raise HTTPException(422, "请求的输出 token 超出模型配置上限")
    return text_pricing(config)


async def admit(ctx, model, body, key, *, validate=chat_options, kind="text"):
    identifier = uuid4()
    dedup = digest([ctx.user.id, key or str(identifier)])
    signature = digest(body)
    async with in_transaction() as db:
        eligible = AiModelConfig.filter(scope="official", is_active=True).exclude(api_protocol="novelvids").using_db(db)
        if isinstance(model, int) or re.fullmatch(r"nv-[1-9][0-9]{0,9}", model):
            model_id = model if isinstance(model, int) else int(model[3:])
        else:
            from services.platform.catalog import PUBLIC_KINDS
            candidates = await eligible.filter(Q(name=model) | Q(model=model)).values("id", "task_type", "task_types")
            matched = [row["id"] for row in candidates if any(PUBLIC_KINDS.get(task) == kind for task in
                                                               (row["task_types"] or [row["task_type"]]))]
            if not matched:
                raise HTTPException(404, "平台模型不存在或已停用")
            if len(matched) > 1:
                raise HTTPException(400, "该模型名称对应多个配置，请使用模型目录中的 ID")
            model_id = matched[0]
        authorize_model(ctx, model_id)
        selected = eligible.filter(id=model_id)
        # Serialize admission across workers before checking concurrency or a repeated key.
        if not await selected.update(concurrency=F("concurrency")):
            raise HTTPException(404, "平台模型不存在或已停用")
        config = await selected.get()
        previous = await PlatformCallReceipt.filter(dedup_key__in=await request_keys(ctx.user.id, key or str(identifier))).first().using_db(db)
        if previous:
            detail = "请求标识已用于不同的请求" if previous.payload_hash != signature else "该请求已受理，请查询原请求状态"
            raise HTTPException(409, detail, headers={"X-Request-Id":str(previous.public_id)})
        rates = validate(config, body)
        try:
            await ensure_solvent(ctx.user.id)
        except HTTPException as error:
            if error.status_code == 402:
                raise HTTPException(402, localized_message("API 平台账户可用额度不足，请前往 API 平台检查余额和限额")) from None
            raise
        recent = datetime.now(timezone.utc) - timedelta(seconds=CALL_TIMEOUT+15)
        count = await PlatformCallReceipt.filter(Q(state="processing") | Q(state="submitted", created_at__gte=recent),
                                                 model_config_id=model_id).using_db(db).count()
        if count >= config.concurrency:
            raise HTTPException(429, "模型并发已满，请稍后重试", headers={"Retry-After":"2"})
        receipt = await PlatformCallReceipt.create(using_db=db, public_id=identifier, dedup_key=dedup,
            payload_hash=signature, account_user_id=ctx.user.id, user_id=ctx.user.id, api_key_id=ctx.platform_key_id, model_config_id=config.id,
            model_name=config.name, model=config.model, pricing=rates)
    return config, receipt


async def settle(receipt_id):
    async with in_transaction() as db:
        # Claiming the state is also the SQLite write lock. Rollback preserves a retryable measurement.
        changed = await PlatformCallReceipt.filter(id=receipt_id, state="measured").using_db(db).update(state="settling")
        if not changed:
            return
        r = await PlatformCallReceipt.get(id=receipt_id).using_db(db)
        kind = r.pricing["type"]
        if kind == "image":
            if r.pricing.get("billing_unit") == "pixel_tier":
                cost = compute_pixel_tier_cost(r.usage["output_tier_counts"], r.pricing)
            else:
                cost = compute_image_cost(r.usage["image_count"], r.usage["clarity"], r.pricing)
            cost += compute_input_image_cost(r.usage["input_image_count"], r.pricing)
        elif kind == "video":
            from services.platform.videos import video_cost
            cost = video_cost(r.usage, r.pricing)
        elif kind == "asr":
            from services.billing.pricing import compute_asr_cost
            cost = compute_asr_cost(r.usage["seconds"], r.pricing)
        elif kind == "media_processing":
            from services.video_enhancement.contract import enhancement_cost
            cost = enhancement_cost(r.usage["seconds"], r.usage["short_side"], r.usage["fps"], r.pricing)
        else:
            cost = compute_text_cost(r.usage, r.pricing)
        record = await ModelUsageRecord.create(using_db=db, novel_id=0, task_type={"image":AiTaskTypeEnum.reference_image,"video":AiTaskTypeEnum.video,"text":AiTaskTypeEnum.creation_agent, "asr":AiTaskTypeEnum.audio_recognition,
                "media_processing":AiTaskTypeEnum.video_enhancement}[kind],
            billing_type=kind, model_config_id=r.model_config_id, model_name=r.model_name, model=r.model,
            pricing_snapshot=r.pricing, usage={**r.usage, "platform_request_id":str(r.public_id)},
            cost=cost, platform_cost=cost, local_charge=0, settlement_status="settled",
            cost_source="balance", account_user_id=r.account_user_id, user_id=r.user_id)
        await consume(r.account_user_id, cost, usage_record_id=record.id, strict=True)
        await PlatformCallReceipt.filter(id=r.id).using_db(db).update(state="completed", usage_record_id=record.id)


async def finish(receipt, usage, provider_id):
    if isinstance(usage, dict):
        usage = SimpleNamespace(**{**usage, "prompt_tokens_details":SimpleNamespace(**(usage.get("prompt_tokens_details") or {}))})
    if usage is None or any(type(v) is not int or v < 0 for v in (getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None))):
        await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="review", provider_id=provider_id)
        raise ValueError("Missing provider token counts")
    from services.llm.usage import completion_cache_usage
    tokens = {"input_tokens":usage.prompt_tokens, "output_tokens":usage.completion_tokens, **completion_cache_usage(usage)}
    await record_measurement(receipt, tokens, provider_id)


async def record_measurement(receipt, usage, provider_id):
    await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(
        state="measured", usage=usage, provider_id=provider_id)
    await settle(receipt.id)


async def preserve_result(receipt, operation):
    """Accounting must never turn an already successful provider result into a client failure."""
    try:
        await operation
    except Exception:
        logger.error("Settlement deferred receipt=%s", receipt.public_id)
        try:
            await PlatformCallReceipt.filter(id=receipt.id, state__in=["submitted", "processing"]).update(state="review")
        except Exception:
            logger.error("Settlement state update deferred receipt=%s", receipt.public_id)


async def recover_measured():
    for receipt_id in await PlatformCallReceipt.filter(state="measured").values_list("id", flat=True):
        try:
            await settle(receipt_id)
        except Exception:
            logger.error("Settlement retry deferred receipt_id=%s", receipt_id)
    await PlatformCallReceipt.filter(state="submitted", created_at__lt=datetime.now(timezone.utc)-timedelta(seconds=CALL_TIMEOUT+15)).update(state="review")
