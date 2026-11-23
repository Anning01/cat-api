"""Public labels and tariffs come from active platform-owned configurations."""
from math import isfinite
import re
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum
from services.video_enhancement.contract import EnhancementOptions
from services.platform.model_metadata import model_identifier, modality_metadata


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
    AiTaskTypeEnum.voice_design: "voice_design",
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
        "input_price_per_1m","cache_input_price_per_1m","output_price_per_1m","price_per_minute","price_per_second","discount"
    } and number(v)}
    data["currency"] = "CNY"
    if raw.get("type") in {"text", "image", "video", "asr", "media_processing", "voice_design"}:
        data["type"] = raw["type"]
    if raw.get("billing_unit") in {"token", "second", "minute", "pixel_tier", "call"}:
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
        "id","name","model","public_alias","created_at","image_model_type","video_model_type","api_protocol","task_type","task_types","pricing","supports_tool_calls","supports_json_output","supports_strict_output","text_api","concurrency","processing_options")
    models = []
    for row in rows:
        task_types = row["task_types"] or [row["task_type"]]
        kinds = list(dict.fromkeys(PUBLIC_KINDS[task] for task in task_types if task in PUBLIC_KINDS))
        if not kinds:
            continue
        private_channel = row['api_protocol'] == 'autodl' or row['video_model_type'] == 'minimax_h3_autodl'
        public_name = re.sub('autodl', '', row['name'], flags=re.I).strip(' -·/') if private_channel else row['name']
        public_alias = row['public_alias']
        if private_channel and public_alias:
            public_alias = public_alias.replace('-autodl', '')
        models.append({
            "id": f"nv-{row['id']}", "name": public_name, "alias":public_alias, "kinds": kinds,
            "model_id":model_identifier(row),
            "task_types": [task for task in task_types if task in PUBLIC_KINDS],
            "created": int(row["created_at"].timestamp()),
            "image_model_type": row["image_model_type"],
            "video_model_type": {"minimax_h3_autodl": "minimax_h3", "seedance_2_5_guangying_fixed": "seedance_2_5",
                                 "seedance_2_5_guangying_97": "seedance_2_5"}.get(
                row["video_model_type"], row["video_model_type"]),
            "reference_image_urls": bool(row["image_model_type"] and row["api_protocol"] in {"openai_compatible", "volcengine_ark", "openrouter_compatible"}),
            "pricing": public_tariff(row["pricing"]), "tool_calls": row["supports_tool_calls"],
            "json_output": row["supports_json_output"], "strict_output": row["supports_strict_output"], "text_api": row["text_api"],
            "concurrency": max(1, row["concurrency"]),
            **({"native_api":NATIVE_APIS[row["api_protocol"]]} if row["api_protocol"] in NATIVE_APIS and row["api_protocol"] != "autodl"
               and any(kind in kinds for kind in ("video", "asr", "media_processing")) else {}),
            **({"processing_options": public_processing_options(row["processing_options"])}
               if AiTaskTypeEnum.video_enhancement in task_types else {}),
        })
        public = models[-1]
        declared_inputs = (row["processing_options"] or {}).get("input_modalities")
        if "text" in kinds and isinstance(declared_inputs, list):
            public["text_input_modalities"] = ["text", *(m for m in ("image","video") if m in declared_inputs)]
        public.update(modality_metadata(public, kinds))
        operations = {}
        if "text" in kinds:
            path = "/v1/responses" if row["text_api"] == "responses" else "/v1/chat/completions"
            operations[row["text_api"]] = {"path":path, "inputs":["json"], "stream":True}
        if "voice_design" in kinds:
            operations["voice_design"] = {"path":"/v1/chat/completions","inputs":["json"],"stream":False}
        native = public.get("native_api")
        for kind in ("media_processing","asr"):
            if kind in kinds and native:
                operations[kind] = {"path":"/v1"+native["submit"], "query":"/v1"+native["query"],
                                    "inputs":["url"], "query_method":"POST" if kind=="asr" else "GET"}
        if "image" in kinds:
            operations["images.generate"] = {"path":"/v1/images/generations", "inputs":["json"]}
            if public["reference_image_urls"]:
                formats = ["url", "file"] if row["api_protocol"] == "openai_compatible" else ["url"]
                operations["images.edit"] = {"path":"/v1/images/edits", "inputs":formats}
        if "video" in kinds and row["video_model_type"]:
            from services.video.capabilities import CAPABILITIES
            from services.platform.videos import video_size
            caps = CAPABILITIES.get(row["video_model_type"])
            if caps:
                prices = public["pricing"].get("prices", {})
                resolutions = [r for r in caps.resolutions if prices.get(r, 0) > 0]
                sizes = [video_size(r, ratio) for r in resolutions for ratio in caps.aspect_ratios if ratio != "adaptive"]
                seconds = {"min":caps.duration_min, "max":caps.duration_max}
                inputs = ["url", "file"]
                if row["api_protocol"] == "openai_video":
                    from services.video.compatible import compatible_options
                    compatible = compatible_options(row["processing_options"])
                    resolutions = [r for r in compatible.resolutions if prices.get(r, 0) > 0]
                    sizes = [s for s in compatible.sizes if f"{min(map(int,s.split('x')))}p" in resolutions]
                    seconds = compatible.seconds
                    inputs = compatible.reference_inputs
                    if not inputs and set(kinds) == {"video"}:
                        public["input_modalities"].remove("image")
                operations["videos.create"] = {"path":"/v1/videos", "inputs":["json", *(["file"] if "file" in inputs else [])], "reference_inputs":inputs, "seconds":seconds,
                    "resolutions":resolutions, "sizes":sizes, "max_reference_images":caps.max_reference_images if inputs else 0,
                    "max_reference_videos":caps.max_reference_videos,"max_reference_audios":caps.max_reference_audios}
                for modality, count in (("video",caps.max_reference_videos),("audio",caps.max_reference_audios)):
                    if count and modality not in public["input_modalities"]:
                        public["input_modalities"].append(modality)
                public["architecture"]["modality"] = "+".join(public["input_modalities"])+"->"+"+".join(public["output_modalities"])
        public["operations"] = operations
    return models
