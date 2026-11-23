"""A single bounded image for the Videos multipart contract."""
import io

from PIL import Image
from starlette.concurrency import run_in_threadpool

from fastapi import HTTPException
from starlette.datastructures import UploadFile

from services.platform.image_uploads import MAX_FILE_BYTES, image_mime, read_bounded_form
from services.platform.request_data import validated_body
from services.platform.temporary_media import store_input


def verify_reference(data):
    mime = image_mime(data)
    try:
        with Image.open(io.BytesIO(data), formats=["PNG", "JPEG", "WEBP"]) as image:
            if image.width * image.height > 36_000_000:
                raise HTTPException(413, "参考图像素过多")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise HTTPException(422, "无法读取参考图") from None
    return mime


async def parse_video_form(request, schema):
    await read_bounded_form(request)
    fields, image = {}, None
    async with request.form(max_files=1, max_fields=12, max_part_size=1024**2) as form:
        for name, value in form.multi_items():
            if isinstance(value, UploadFile):
                if name != "input_reference":
                    raise HTTPException(422, "参考图文件字段须为 input_reference")
                data = await value.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise HTTPException(413, "参考图不能超过 50 MiB")
                mime = await run_in_threadpool(verify_reference, data)
                image = ("reference." + mime.split("/")[1], data, mime)
            else:
                if name in fields or name not in {"model", "prompt", "seconds", "size"}:
                    raise HTTPException(422, "视频表单字段重复或不支持")
                fields[name] = value
    return validated_body(schema, fields), image


async def store_video_reference(user_id, image):
    _, data, mime = image
    return await store_input(user_id, data, mime)
