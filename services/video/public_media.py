"""Resolve local video references through the application's object storage."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from config import settings
from services.platform.inline_media import decode_media
from services.platform.temporary_media import store_input
from services.video.base import VideoProviderError
from utils.messages import localized_message


_HTTP_URL = TypeAdapter(AnyHttpUrl)


def public_media_url(value: str) -> str:
    try:
        parsed = _HTTP_URL.validate_python(value)
        if parsed.username or parsed.password:
            raise ValueError
    except (ValidationError, ValueError):
        raise VideoProviderError(localized_message('参考素材需要可访问的公网 HTTP(S) 地址')) from None
    return value


class PublicMediaResolver:
    """Upload local inputs once per request; never send Base64 to the video API."""

    def __init__(self, *, user_id: int | None, model_config=None):
        self.model_config = model_config
        self.user_id = user_id
        self._resolved: dict[str, str] = {}

    async def resolve(self, source: str) -> str:
        if source in self._resolved:
            return self._resolved[source]
        if not source.startswith(("data:", "/media/")):
            return public_media_url(source)
        if not self.user_id:
            raise VideoProviderError("暂存参考素材需要有效账户")
        if source.startswith("data:"):
            mime, data = decode_media(source)
            url = await store_input(self.user_id, data, mime)
        else:
            root = Path(settings.MEDIA_PATH).resolve()
            path = (root / source.removeprefix("/media/")).resolve()
            if root not in path.parents or not path.is_file():
                raise VideoProviderError(localized_message('本地参考素材不存在'))
            url = await store_input(self.user_id, path, mimetypes.guess_type(path.name)[0] or "")
        self._resolved[source] = url
        return url
