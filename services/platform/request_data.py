"""Only bounded JSON metadata crosses the public generation API."""
import json

from fastapi import HTTPException, Request
from pydantic import ValidationError
from services.platform.inline_media import MAX_INLINE_JSON, decode_media

MAX_REQUEST_BYTES = 1024 * 1024


def reject_inline_media(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"b64_json", "file_data"} or key == "input_audio" and isinstance(child, dict) and "data" in child:
                raise HTTPException(422, "Upload media directly to temporary OSS and send its read_url")
            reject_inline_media(child)
    elif isinstance(value, list):
        for child in value:
            reject_inline_media(child)
    elif isinstance(value, str) and value.lstrip().lower().startswith("data:"):
        raise HTTPException(422, "Inline media is not accepted; use temporary OSS URLs")


def validate_media_inputs(value, field=""):
    """Return the encoded media length so metadata keeps its independent 1 MiB limit."""
    if isinstance(value, dict):
        if field == "input_audio" and {"data", "format"} <= value.keys():
            mime = {"wav":"audio/wav", "mp3":"audio/mpeg"}.get(value["format"]) if isinstance(value["format"], str) else None
            encoded = value["data"]
            if not isinstance(encoded, str) or not mime:
                raise HTTPException(422, "input_audio 需要有效的音频格式和 Base64 数据")
            try:
                decode_media("data:" + mime + ";base64," + encoded, "audio")
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            return len(encoded)
        if "file_data" in value or "b64_json" in value:
            raise HTTPException(422, "请在媒体输入字段中使用 Base64 data URL")
        return sum(validate_media_inputs(child, name) for name, child in value.items())
    if isinstance(value, list):
        return sum(validate_media_inputs(child, field) for child in value)
    if isinstance(value, str) and value.lstrip().lower().startswith("data:"):
        if (field not in {"url", "image_url", "image", "input_reference", "first_frame_image", "last_frame_image"}
                and not field.endswith("_url") and not field.startswith(("ref_image_", "ref_audio_"))):
            raise HTTPException(422, "Base64 仅支持媒体输入字段")
        try:
            decode_media(value)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return len(value)
    return 0


async def bounded_json_body(request: Request, *, allow_form=False):
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if allow_form and content_type == "multipart/form-data":
        return  # Authenticate in the endpoint before reading a bounded file body.
    if content_type != "application/json":
        raise HTTPException(400, "Send JSON with media URLs; request a direct upload at /v1/media/uploads")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_INLINE_JSON:
        raise HTTPException(413, "JSON 请求超过 16 MiB，请使用临时上传或 HTTPS 地址")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_INLINE_JSON:
            raise HTTPException(413, "JSON 请求超过 16 MiB，请使用临时上传或 HTTPS 地址")
        body.extend(chunk)
    request._body = bytes(body)
    try:
        data = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Request body must be valid JSON") from None
    encoded_size = validate_media_inputs(data)
    if len(body) - encoded_size > MAX_REQUEST_BYTES:
        raise HTTPException(413, "JSON metadata exceeds 1 MB")


def validated_body(schema, values):
    try:
        return schema.model_validate(values)
    except ValidationError as error:
        detail = error.errors()[0]
        field = ".".join(str(value) for value in detail["loc"])
        raise HTTPException(422, f"{field}: {detail['msg']}") from None


def sdk_request_schema(model, *, multipart=False, video_file=False):
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    def inline(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return inline(definitions[value["$ref"].rsplit("/", 1)[1]])
            return {key:inline(item) for key,item in value.items()}
        if isinstance(value, list):
            return [inline(item) for item in value]
        return value
    content = {"application/json":{"schema":inline(schema)}}
    if video_file:
        for key in ("duration","resolution","aspect_ratio"):
            schema["properties"][key].pop("default", None)
            schema["properties"][key]["description"] = "省略时使用所选视频渠道的默认规格"
        properties = {k: v for k, v in schema["properties"].items() if k in {"model", "prompt", "seconds", "size"}}
        properties["input_reference"] = {"type": "string", "format": "binary"}
        content["multipart/form-data"] = {"schema": {"type": "object", "properties": properties, "required": ["prompt"]}}
    if multipart:
        file_schema = inline(schema)
        file_schema['properties']['image'] = {'type':'array','minItems':1,'maxItems':16,
            'items':{'type':'string','format':'binary'}}
        file_schema['properties']['mask'] = {'type':'string','format':'binary','description':'可选 PNG 蒙版'}
        for key in ('images','input_references'):
            file_schema['properties'].pop(key,None)
        file_schema['required'] = list(dict.fromkeys([*file_schema.get('required',[]),'image']))
        content['multipart/form-data'] = {'schema':file_schema}
    return {"requestBody":{"required":True, "content":content}}
