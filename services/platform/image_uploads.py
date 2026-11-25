"""Image signatures used to verify provider results."""
from fastapi import HTTPException


def image_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise HTTPException(422, '参考图须为 PNG、JPEG 或 WebP 文件')
