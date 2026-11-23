"""Bounded media input. Encoded bytes live only in the forwarding request."""
import base64
import binascii

from services.platform.temporary_media import TYPES

MAX_INLINE_JSON = 16 * 1024**2


def decode_media(value, kind=None):
    header, comma, encoded = value.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if (not comma or not header.endswith(";base64") or mime not in TYPES or not encoded
            or len(encoded) > MAX_INLINE_JSON or (kind and not mime.startswith(kind + "/"))):
        raise ValueError("无效或过大的 Base64 媒体，请使用带 MIME 类型的 data URL")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Base64 媒体编码无效") from None
    if not data:
        raise ValueError("参考素材为空")
    signatures = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff", "image/gif": b"GIF"}
    if mime in {"audio/wav", "audio/x-wav"} and not (data.startswith(b"RIFF") and data[8:12] == b"WAVE"):
        raise ValueError("Base64 WAV 文件头无效")
    if mime in signatures and not data.startswith(signatures[mime]):
        raise ValueError("Base64 媒体内容与声明格式不匹配")
    return mime, data


def media_input(value, kind=None):
    if isinstance(value, str) and value.startswith("data:"):
        decode_media(value, kind)
        return value
    from services.platform.images import media_url
    return media_url(value)
