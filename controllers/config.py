
from utils.messages import localized_message
import math
from fastapi import HTTPException

from services.billing.catalog import IMAGE_PRICING, LLM_PRICING, VIDEO_PRICING, ASR_PRICING
from models.config import AiModelConfig, GeneralConfig
from schemas.config import AiModelConfigCreate, AiModelConfigUpdate, GeneralConfigUpdate
from services.image_generation.capabilities import (
    PROTOCOLS as IMAGE_PROTOCOLS,
    GPT_IMAGE_MODELS,
    capabilities_for as image_capabilities_for,
    validate_protocol as validate_image_protocol,
)
from services.video.capabilities import (
    capabilities_for as video_capabilities_for,
    protocol_options as video_protocol_options,
    validate_protocol as validate_video_protocol,
)
from services.video.factory import video_generator_factory
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, ImageModelTypeEnum, VideoGenerationModelTypeEnum


def _validate_text_pricing(pricing: dict) -> None:
    if pricing.get("type") != "text":
        raise HTTPException(status_code=400, detail=localized_message('文本模型的费用配置 type 必须为 text'))
    for key in ("input_price_per_1m", "output_price_per_1m"):
        value = pricing.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise HTTPException(status_code=400, detail=localized_message('文本费用缺少合法的 {p1}', p1=f'{key}'))
    cache_price = pricing.get("cache_input_price_per_1m")
    if cache_price is not None and (isinstance(cache_price, bool) or not isinstance(cache_price, (int, float)) or not math.isfinite(cache_price) or cache_price < 0):
        raise HTTPException(status_code=400, detail=localized_message('文本费用缺少合法的 {p1}', p1='cache_input_price_per_1m'))


def _validate_image_pricing(pricing: dict, model_type) -> None:
    if pricing.get("type") != "image":
        raise HTTPException(status_code=400, detail=localized_message('生图模型的费用配置 type 必须为 image'))
    prices = pricing.get("prices")
    if not isinstance(prices, dict):
        raise HTTPException(status_code=400, detail=localized_message('生图费用需要 prices 档位对象'))
    allowed = set(image_capabilities_for(model_type).clarities)
    if pricing.get("billing_unit") == "pixel_tier":
        allowed = set(IMAGE_PRICING.get(model_type, {}).get("prices", {}))
        if not allowed or prices.keys() != allowed:
            raise HTTPException(400, "请配置该模型的全部像素价格档位")
    elif model_type == "seedream_5_5":
        raise HTTPException(400, "Seedream 5.5 需要像素分档价格")
    for tier, value in prices.items():
        if tier not in allowed:
            raise HTTPException(status_code=400, detail=localized_message('生图费用包含不支持的清晰度档位：{p1}', p1=f'{tier}'))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise HTTPException(status_code=400, detail=localized_message('清晰度档位 {p1} 的费用必须为非负数字', p1=f'{tier}'))
    if model_type in GPT_IMAGE_MODELS and not allowed.issubset(prices):
        raise HTTPException(status_code=400, detail=localized_message('请配置全部清晰度档位的输出图单价'))
    _validate_input_image_pricing(pricing, "生图")


def _validate_input_image_pricing(pricing: dict, label: str) -> None:
    input_fee = pricing.get("input_image")
    if input_fee is not None:
        if not isinstance(input_fee, dict):
            raise HTTPException(status_code=400, detail=localized_message('{p0}输入图费用必须是对象', p0=f'{label}'))
        if not isinstance(input_fee.get("first_free"), (int, float)) or input_fee["first_free"] < 0:
            raise HTTPException(status_code=400, detail=localized_message('输入图免费张数 first_free 必须为非负数字'))
        if not isinstance(input_fee.get("price_per_image"), (int, float)) or input_fee["price_per_image"] < 0:
            raise HTTPException(status_code=400, detail=localized_message('输入图超出单价 price_per_image 必须为非负数字'))


def _validate_video_pricing(pricing: dict, model_type) -> None:
    if pricing.get("type") != "video":
        raise HTTPException(status_code=400, detail=localized_message('视频模型的费用配置 type 必须为 video'))
    prices = pricing.get("prices")
    if not isinstance(prices, dict):
        raise HTTPException(status_code=400, detail=localized_message('视频费用需要 prices 档位对象'))
    allowed = set(video_capabilities_for(model_type).resolutions)
    for tier, value in prices.items():
        if tier not in allowed:
            raise HTTPException(status_code=400, detail=localized_message('视频费用包含不支持的分辨率档位：{p1}', p1=f'{tier}'))
        if not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=localized_message('分辨率档位 {p1} 的费用必须为非负数字', p1=f'{tier}'))
    ref_prices = pricing.get("video_reference_prices")
    if ref_prices is not None:
        if not isinstance(ref_prices, dict):
            raise HTTPException(status_code=400, detail=localized_message('视频参考价格必须是档位对象'))
        for tier, value in ref_prices.items():
            if tier not in allowed:
                raise HTTPException(status_code=400, detail=localized_message('视频参考价格包含不支持的分辨率档位：{p1}', p1=f'{tier}'))
            if not isinstance(value, (int, float)) or value < 0:
                raise HTTPException(status_code=400, detail=localized_message('视频参考分辨率档位 {p1} 的费用必须为非负数字', p1=f'{tier}'))
    model_key = str(model_type)
    expected_unit = VIDEO_PRICING.get(model_key, {}).get("billing_unit", "token")
    billing_unit = pricing.get("billing_unit", "token")
    if billing_unit not in {"token", "second"}:
        raise HTTPException(status_code=400, detail=localized_message('视频计费单位 billing_unit 仅支持 token 或 second'))
    if billing_unit != expected_unit:
        unit_label = "按秒" if expected_unit == "second" else "按 token"
        raise HTTPException(status_code=400, detail=localized_message('当前视频模型必须使用{p1}计费', p1=f'{unit_label}'))
    _validate_input_image_pricing(pricing, "视频")


def _validate_asr_pricing(pricing: dict) -> None:
    if pricing.get("type") != "asr":
        raise HTTPException(status_code=400, detail=localized_message('语音识别模型的费用配置 type 必须为 asr'))
    price_per_minute = pricing.get("price_per_minute")
    if price_per_minute is None or isinstance(price_per_minute, bool) or not isinstance(price_per_minute, (int, float)) or not math.isfinite(price_per_minute) or price_per_minute < 0:
        raise HTTPException(status_code=400, detail=localized_message('语音识别费用缺少合法的 price_per_minute'))


class AiModelConfigController(CRUDBase[AiModelConfig, AiModelConfigCreate, AiModelConfigUpdate]):
    def __init__(self):
        super().__init__(model=AiModelConfig)

    @staticmethod
    def _capabilities(config: AiModelConfig) -> set[int]:
        return {int(value) for value in (config.task_types or [config.task_type])}

    @staticmethod
    def _normalize_payload(obj_in) -> dict:
        data = obj_in.model_dump(exclude_unset=True, exclude={"id", "scope"})
        if "task_types" in data:
            values = list(dict.fromkeys(int(value) for value in (data["task_types"] or [])))
            if not values:
                values = [int(data.get("task_type"))]
            data["task_types"] = values
            data["task_type"] = values[0]
        elif "task_type" in data:
            data["task_types"] = [int(data["task_type"])]
        return data

    @staticmethod
    def _validate_image_payload(data: dict, instance: AiModelConfig | None = None) -> None:
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        if AiTaskTypeEnum.reference_image.value not in (task_types or []):
            return
        model_type = data.get("image_model_type")
        if model_type is None and instance is not None:
            model_type = instance.image_model_type
        protocol = data.get("api_protocol")
        if protocol is None and instance is not None:
            protocol = instance.api_protocol
        image_capabilities_for(model_type)
        validate_image_protocol(model_type, str(protocol))
        pricing = data.get("pricing", instance.pricing if instance else None)
        if pricing is not None:
            _validate_image_pricing(pricing, model_type)

    @staticmethod
    def _validate_video_payload(data: dict, instance: AiModelConfig | None = None) -> None:
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        if AiTaskTypeEnum.video.value not in (task_types or []):
            return
        model_type = data.get("video_model_type")
        if model_type is None and instance is not None:
            model_type = instance.video_model_type
        protocol = data.get("api_protocol")
        if protocol is None and instance is not None:
            protocol = instance.api_protocol
        video_capabilities_for(model_type)
        validate_video_protocol(model_type, str(protocol))
        video_generator_factory.validate_model_type(model_type)

    @staticmethod
    def _validate_pricing(data: dict, instance: AiModelConfig | None = None) -> None:
        pricing = data.get("pricing")
        if pricing is None:
            return
        if not isinstance(pricing, dict):
            raise HTTPException(status_code=400, detail=localized_message('费用配置必须是对象'))
        discount = pricing.get("discount")
        if discount is not None and (isinstance(discount, bool) or not isinstance(discount, (int, float)) or not math.isfinite(discount) or discount <= 0):
            raise HTTPException(status_code=400, detail=localized_message('折扣倍数 discount 必须为正数'))
        description = pricing.get("discount_description")
        if description is not None and not isinstance(description, str):
            raise HTTPException(status_code=400, detail=localized_message('折扣描述 discount_description 必须是字符串'))
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        task_types = [int(value) for value in (task_types or [])]
        if AiTaskTypeEnum.reference_image.value in task_types:
            return
        if AiTaskTypeEnum.video.value in task_types:
            model_type = data.get("video_model_type") or (
                instance.video_model_type if instance else None
            )
            _validate_video_pricing(pricing, model_type)
            return
        if AiTaskTypeEnum.audio_recognition.value in task_types:
            _validate_asr_pricing(pricing)
            return
        _validate_text_pricing(pricing)

    @classmethod
    def _validate_generation_payload(cls, data: dict, instance: AiModelConfig | None = None) -> None:
        tasks = data.get('task_types', (instance.task_types or [instance.task_type]) if instance else [])
        if AiTaskTypeEnum.video_enhancement.value in tasks:
            from pydantic import ValidationError
            from services.video_enhancement.contract import EnhancementOptions, EnhancementPricing, enhancement_cost, RESOLUTION_SHORT_SIDE
            if tasks != [AiTaskTypeEnum.video_enhancement.value]:
                raise HTTPException(400, localized_message('媒体处理配置不能与生成模型共用'))
            protocol = data.get('api_protocol', instance.api_protocol if instance else None)
            model = data.get('model', instance.model if instance else None)
            if str(protocol) != 'volcengine_mediakit' or model != 'enhance-video-generative':
                raise HTTPException(400, localized_message('请选择 MediaKit 大模型画质增强协议'))
            try:
                data['processing_options'] = EnhancementOptions.model_validate(
                    data.get('processing_options', instance.processing_options if instance else None) or {}
                ).model_dump(mode='json')
                pricing = data.get('pricing', instance.pricing if instance else None)
                if pricing is not None:
                    EnhancementPricing.model_validate(pricing)
                    for resolution in data['processing_options']['output_resolutions']:
                        for fps in (30, 60, 120):
                            enhancement_cost(1, RESOLUTION_SHORT_SIDE[resolution], fps, pricing)
                elif data.get('is_active', instance.is_active if instance else False):
                    raise ValueError('missing media processing pricing')
            except (ValueError, ValidationError):
                raise HTTPException(400, localized_message('画质增强能力或价格配置不完整')) from None
            return
        cls._validate_image_payload(data, instance)
        cls._validate_video_payload(data, instance)
        cls._validate_pricing(data, instance)

    async def create(self, obj_in: AiModelConfigCreate, **kwargs) -> AiModelConfig:
        data = self._normalize_payload(obj_in)
        self._validate_generation_payload(data)
        config = await super().create(data, **kwargs)
        from services.platform.model_aliases import ensure_model_alias
        await ensure_model_alias(config)
        return config

    async def update(self, config_id: int, obj_in: AiModelConfigUpdate) -> AiModelConfig:
        instance = await self.get(config_id)
        data = self._normalize_payload(obj_in)
        from services.video.ark_migration import LEGACY_ROUTE
        old_route = (instance.processing_options or {}).get(LEGACY_ROUTE)
        if old_route and "processing_options" in data:
            data["processing_options"] = {**(data["processing_options"] or {}), LEGACY_ROUTE: old_route}
        self._validate_generation_payload(data, instance)
        return await super().update(instance, data)

    async def patch(self, config_id: int, obj_in) -> AiModelConfig:
        instance = await self.get(config_id)
        data = self._normalize_payload(obj_in)
        from services.video.ark_migration import LEGACY_ROUTE
        old_route = (instance.processing_options or {}).get(LEGACY_ROUTE)
        if old_route and "processing_options" in data:
            data["processing_options"] = {**(data["processing_options"] or {}), LEGACY_ROUTE: old_route}
        self._validate_generation_payload(data, instance)
        return await super().patch(instance, data)

    async def remove(self, config_id: int) -> None:
        instance = await self.get(config_id)
        await super().remove(instance)

    async def activate(self, config_id: int) -> AiModelConfig:
        """独立启用当前渠道配置，同类型的其他渠道可同时运行。"""
        instance = await self.get(config_id)
        self._validate_generation_payload({'is_active': True} if instance.task_type == 8 else {}, instance)
        instance.is_active = True
        await instance.save(update_fields=["is_active", "updated_at"])
        return instance

    async def list_generation_capabilities(self) -> dict:
        from services.video_enhancement.contract import ENHANCEMENT_PRESET, RESOLUTION_SHORT_SIDE
        return {
            "image": {model.value: list(image_capabilities_for(model.value).clarities) for model in ImageModelTypeEnum},
            "image_pricing": IMAGE_PRICING,
            "image_protocols": {model.value: [protocol.value for protocol in protocols] for model, protocols in IMAGE_PROTOCOLS.items()},
            "video": {model.value: list(video_capabilities_for(model.value).resolutions) for model in VideoGenerationModelTypeEnum},
            "video_protocols": video_protocol_options(),
            "video_pricing": VIDEO_PRICING,
            "text_pricing": {model: {"type":"text", "currency":"CNY", **prices} for model, prices in LLM_PRICING.items()},
            "audio_recognition": {"base_url":"https://openspeech.bytedance.com/api/v3/auc/bigmodel",
                "model":"volc.seedasr.auc", "api_protocol":"volcengine_openspeech", "pricing":ASR_PRICING["volc.seedasr.auc"]},
            "media_processing": {**ENHANCEMENT_PRESET, "resolutions":[
                {"value":value,"short_side":short} for value,short in RESOLUTION_SHORT_SIDE.items()]},
        }

    async def deactivate(self, config_id: int) -> AiModelConfig:
        """停用指定配置，不影响同用途下的其他运行配置。"""
        instance = await self.get(config_id)
        instance.is_active = False
        await instance.save(update_fields=["is_active", "updated_at"])
        return instance

ai_model_config_controller = AiModelConfigController()


class GeneralConfigController:
    """管理应用级单例配置。"""

    async def get(self) -> GeneralConfig:
        config, _ = await GeneralConfig.get_or_create(
            id=1,
            defaults={"prompt_language": "en"},
        )
        return config

    async def update(self, obj_in: GeneralConfigUpdate) -> GeneralConfig:
        config = await self.get()
        values = obj_in.model_dump(exclude_unset=True, exclude_none=True)
        config.update_from_dict(values)
        await config.save(update_fields=[*values, "updated_at"])
        return config

    async def get_prompt_language(self) -> str:
        return (await self.get()).prompt_language


general_config_controller = GeneralConfigController()
