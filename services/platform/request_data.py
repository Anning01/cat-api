"""Only bounded JSON metadata crosses the public generation API."""
import json

from fastapi import HTTPException, Request
from pydantic import ValidationError


MAX_REQUEST_BYTES = 1024 * 1024
UPLOAD_HINT = "本地素材请通过 /v1/media/uploads 直传 OSS，然后在生成请求中使用 media_ref。"


def reject_inline_media(value):
    if isinstance(value, dict):
        if any(key in value for key in ("b64_json", "file_data", "inline_data", "inlineData")):
            raise HTTPException(422, UPLOAD_HINT)
        if value.get("type") == "base64" and "data" in value:
            raise HTTPException(422, UPLOAD_HINT)
        for key, child in value.items():
            if key in ("audio", "input_audio") and isinstance(child, dict) and isinstance(child.get("data"), str):
                raise HTTPException(422, UPLOAD_HINT)
            reject_inline_media(child)
    elif isinstance(value, list):
        for child in value:
            reject_inline_media(child)
    elif isinstance(value, str) and value.lstrip()[:5].lower() == "data:":
        raise HTTPException(422, UPLOAD_HINT)


async def bounded_json_body(request: Request):
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type == "multipart/form-data":
        raise HTTPException(422, UPLOAD_HINT)
    if content_type != "application/json":
        raise HTTPException(400, "生成接口需要 JSON。" + UPLOAD_HINT)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
        raise HTTPException(413, "JSON 请求上限为 1 MiB。" + UPLOAD_HINT)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "JSON 请求上限为 1 MiB。" + UPLOAD_HINT)
        body.extend(chunk)
    request._body = bytes(body)
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise HTTPException(400, "Request body must be valid JSON") from None
    try:
        reject_inline_media(data)
    except RecursionError:
        raise HTTPException(400, "JSON nesting is too deep") from None
    request._json = data


def validated_body(schema, values):
    try:
        return schema.model_validate(values)
    except ValidationError as error:
        detail = error.errors()[0]
        field = ".".join(str(value) for value in detail["loc"])
        raise HTTPException(422, f"{field}: {detail['msg']}") from None


def sdk_request_schema(model):
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
    return {"requestBody":{"required":True, "content":content}}
