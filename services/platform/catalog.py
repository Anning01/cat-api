"""Public labels and tariffs come from active platform-owned configurations."""
from math import isfinite
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum
from services.video_enhancement.contract import EnhancementOptions


PUBLIC_KINDS = {
    AiTaskTypeEnum.extraction: "text",
    AiTaskTypeEnum.reference_image: "image",
    AiTaskTypeEnum.storyboard: "text",
    AiTaskTypeEnum.video: "video",
    AiTaskTypeEnum.video_enhancement: "media_processing",
    AiTaskTypeEnum.audio_recognition: "asr",
    AiTaskTypeEnum.project_analysis: "text",
    AiTaskTypeEnum.remake_decomposition: "text",
    AiTaskTypeEnum.creation_agent: "text",
    AiTaskTypeEnum.screenplay: "text",
    AiTaskTypeEnum.prompt_optimization: "text",
}

NATIVE_APIS = {
    "volcengine_ark":{"submit":"/api/v3/contents/generations/tasks", "query":"/api/v3/contents/generations/tasks/{task_id}"},
    "minimax":{"submit":"/v2/video_generation", "query":"/v2/query/video_generation/{task_id}"},
    "dashscope":{"submit":"/api/v1/services/aigc/video-generation/video-synthesis", "query":"/api/v1/tasks/{task_id}"},
    "autodl":{"submit":"/api/v1/comfyui/comfyui_workflow/{model_id}", "query":"/api/v1/comfyui/comfyui_workflow/result/{task_id}"},
    "volcengine_mediakit":{"submit":"/api/v1/tools/enhance-video-generative", "query":"/api/v1/tasks/{task_id}"},
    "volcengine_openspeech":{"submit":"/api/v3/auc/bigmodel/submit", "query":"/api/v3/auc/bigmodel/query"},
}


# Deliberately independent of the provider configuration's private fields.
PUBLIC_PROCESSING_OPTIONS = {
    "input_short_side_min", "input_short_side_max", "input_long_side_max",
    "input_fps_min", "input_fps_max", "max_duration_seconds", "max_file_bytes",
    "poll_seconds", "local_upload_max_bytes", "output_resolutions",
}


def public_processing_options(raw):
    allowed = {key: value for key, value in (raw or {}).items() if key in PUBLIC_PROCESSING_OPTIONS}
    options = EnhancementOptions.model_validate(allowed).model_dump(mode="json")
    return {key: value for key, value in options.items() if key in PUBLIC_PROCESSING_OPTIONS}


def public_tariff(raw):
    if not isinstance(raw, dict):
        return {}
    def number(v):
        return isinstance(v, (float, int)) and not isinstance(v, bool) and isfinite(v) and v >= 0
    data = {k: v for k,v in raw.items() if k in {
        "input_price_per_1m","cache_input_price_per_1m","output_price_per_1m","price_per_minute","discount"
    } and number(v)}
    data["currency"] = "CNY"
    if raw.get("type") in {"text", "image", "video", "asr", "media_processing"}:
        data["type"] = raw["type"]
    if raw.get("billing_unit") in {"token", "second", "minute", "pixel_tier"}:
        data["billing_unit"] = raw["billing_unit"]
    for k in ("prices","video_reference_prices"):
        if isinstance(raw.get(k), dict):
            data[k] = {str(tier):v for tier,v in raw[k].items() if number(v)}
    if isinstance(raw.get("input_image"), dict):
        data["input_image"] = {k:v for k,v in raw["input_image"].items() if k in {"first_free","price_per_image"} and number(v)}
    if isinstance(raw.get("tiers"), list):
        data["tiers"] = [{k:v for k,v in tier.items() if k in {"short_side_max","fps_max","price"} and number(v)}
                         for tier in raw["tiers"] if isinstance(tier, dict)]
    return data


async def model_catalog():
    rows = await AiModelConfig.filter(scope="official", is_active=True).exclude(api_protocol="novelvids").order_by("id").values(
        "id","name","public_alias","created_at","image_model_type","video_model_type","api_protocol","task_type","task_types","pricing","supports_tool_calls","supports_json_output","concurrency","processing_options")
    models = []
    for row in rows:
        task_types = row["task_types"] or [row["task_type"]]
        kinds = list(dict.fromkeys(PUBLIC_KINDS[task] for task in task_types if task in PUBLIC_KINDS))
        if not kinds:
            continue
        models.append({
            "id": f"nv-{row['id']}", "name": row["name"], "alias":row["public_alias"], "kinds": kinds,
            "task_types": [task for task in task_types if task in PUBLIC_KINDS],
            "created": int(row["created_at"].timestamp()),
            "image_model_type": row["image_model_type"], "video_model_type": row["video_model_type"],
            "reference_image_urls": bool(row["image_model_type"] and row["api_protocol"] in {"openai_compatible", "volcengine_ark", "openrouter_compatible"}),
            "pricing": public_tariff(row["pricing"]), "tool_calls": row["supports_tool_calls"],
            "json_output": row["supports_json_output"],
            "concurrency": max(1, row["concurrency"]),
            **({"native_api":NATIVE_APIS[row["api_protocol"]]} if row["api_protocol"] in NATIVE_APIS
               and any(kind in kinds for kind in ("video", "asr", "media_processing")) else {}),
            **({"processing_options": public_processing_options(row["processing_options"])}
               if AiTaskTypeEnum.video_enhancement in task_types else {}),
        })
    return models
