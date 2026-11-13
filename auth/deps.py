"""鉴权依赖：当前用户、角色守卫、账户访问校验。

开关语义：`AUTH_ENABLED=false` 时所有依赖退化为 no-op（匿名放行），
行为与无鉴权版本完全一致；`true` 时执行严格鉴权与角色检查。
"""

from utils.messages import localized_message

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request

from auth.models import User, UserSession
from auth.security import hash_token
from config import settings
from utils.enums import UserStatusEnum, AiTaskTypeEnum


@dataclass
class AuthContext:
    """鉴权上下文：当前用户、账户账户身份与超管标记。"""

    user: Optional[User] = None
    is_super_admin: bool = False
    platform_key_id: int | None = None
    allowed_model_ids: frozenset[str] | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.user is None


def auth_disabled() -> bool:
    return not settings.AUTH_ENABLED


def extract_bearer_token(request: Request) -> Optional[str]:
    """从 Authorization: Bearer <token> 提取令牌，也支持 ?token=xxx 查询参数供媒体流式播放（video/audio标签）使用；缺失返回 None。"""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    token = request.query_params.get("token")
    if token:
        return token.strip()
    return None


async def get_current_user(request: Request) -> Optional[User]:
    """解析当前登录用户。开关关闭时返回 None（匿名模式）。"""
    if auth_disabled():
        return None
    token = extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail=localized_message('未登录'))
    session = await UserSession.get_or_none(
        token_hash=hash_token(token)
    ).select_related("user")
    now = datetime.now(timezone.utc)
    if session is None or session.expires_at <= now:
        if session is not None:
            await session.delete()
        raise HTTPException(status_code=401, detail=localized_message('登录已失效，请重新登录'))
    if session.user.status != UserStatusEnum.active.value:
        raise HTTPException(status_code=403, detail=localized_message('账号已停用'))
    session.last_seen_at = now
    await session.save(update_fields=["last_seen_at", "updated_at"])
    return session.user


async def get_auth_context(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
) -> AuthContext:
    """Resolve the signed-in user and platform administrator status."""
    if auth_disabled() or user is None:
        return AuthContext()
    return AuthContext(user=user, is_super_admin=user.is_super_admin)


async def require_user(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.user is None:
        raise HTTPException(401, "需要登录")
    return ctx


async def require_super_admin(
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """超管守卫：仅平台超级管理员可访问。"""
    if not ctx.is_super_admin:
        raise HTTPException(status_code=403, detail=localized_message('仅超级管理员可执行此操作'))
    return ctx
