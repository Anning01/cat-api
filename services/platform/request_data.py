"""Only bounded JSON metadata crosses the public generation API."""
import json

from fastapi import HTTPException, Request
from pydantic import ValidationError

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


async def bounded_json_body(request: Request, *, allow_form=False):
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if allow_form and content_type == "multipart/form-data":
        return  # Authenticate in the endpoint before reading a bounded file body.
    if content_type != "application/json":
        raise HTTPException(400, "Send JSON with media URLs; request a direct upload at /v1/media/uploads")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
        raise HTTPException(413, "JSON request exceeds 1 MB; upload media directly to temporary OSS")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "JSON request exceeds 1 MB; upload media directly to temporary OSS")
        body.extend(chunk)
    request._body = bytes(body)
    try:
        data = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Request body must be valid JSON") from None
    reject_inline_media(data)


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
