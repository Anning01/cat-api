"""Bounded OpenAI image-edit file input. Bytes are forwarded, never stored in receipts."""
from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile
from services.platform.images import ImageRequest
from services.platform.request_data import validated_body

MAX_EDIT_BYTES = 64 * 1024**2
MAX_FILE_BYTES = 50 * 1024**2


def image_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise HTTPException(422, '参考图须为 PNG、JPEG 或 WebP 文件')


async def read_bounded_form(request: Request):
    length = request.headers.get('content-length','')
    if length.isdigit() and int(length) > MAX_EDIT_BYTES:
        raise HTTPException(413, '文件请求总大小不能超过 64 MiB')
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_EDIT_BYTES:
            raise HTTPException(413, '文件请求总大小不能超过 64 MiB')
        content.extend(chunk)
    request._body = bytes(content)


async def parse_image_edit(request: Request):
    await read_bounded_form(request)
    values, files = {}, []
    try:
        async with request.form(max_files=17,max_fields=32,max_part_size=1024**2) as form:
            for field, value in form.multi_items():
                if isinstance(value,UploadFile):
                    if field not in {'image','image[]','mask'}:
                        raise HTTPException(422, '只支持 image、image[] 和 mask 文件字段')
                    data = await value.read(MAX_FILE_BYTES+1)
                    if not data or len(data)>MAX_FILE_BYTES:
                        raise HTTPException(413, '单张参考图须非空且不超过 50 MiB')
                    mime = image_mime(data)
                    if field=='mask' and mime!='image/png':
                        raise HTTPException(422, 'mask 须为 PNG 文件')
                    name=(value.filename or 'image').replace('\\','/').rsplit('/',1)[-1]
                    files.append(('mask' if field=='mask' else 'image[]',(name,data,mime)))
                else:
                    if field in values:
                        raise HTTPException(422, '请求包含重复的文本字段')
                    values[field]=value
    except HTTPException:
        raise
    except (ValueError,KeyError) as exc:
        raise HTTPException(400, '图片编辑文件表单无效') from exc
    if not 1 <= sum(field=='image[]' for field,_ in files) <= 16 or sum(field=='mask' for field,_ in files)>1:
        raise HTTPException(422, '请提供 1 至 16 张参考图，最多一张 mask')
    body = validated_body(ImageRequest,values)
    if body.reference_urls() or body.mask:
        raise HTTPException(422, '文件表单不能同时提交 URL 参考图或 URL mask')
    return body,files
