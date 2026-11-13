"""鉴权依赖：当前用户、角色守卫、团队访问校验。

开关语义：`AUTH_ENABLED=false` 时所有依赖退化为 no-op（匿名放行），
行为与无鉴权版本完全一致；`true` 时执行严格鉴权与角色检查。
"""

from utils.messages import localized_message

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request

from auth.models import TeamMember, User, UserSession
from auth.security import hash_token
from config import settings
from utils.enums import UserStatusEnum, AiTaskTypeEnum


@dataclass
class AuthContext:
    """鉴权上下文：当前用户、团队成员身份与超管标记。"""

    user: Optional[User] = None
    membership: Optional[TeamMember] = None
    team_id: Optional[int] = None
    is_super_admin: bool = False
    platform_key_id: int | None = None

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
    """组装鉴权上下文。超管跨团队；普通用户按侧边栏选中的团队（X-Team-Id）
    解析成员身份，未指定时回退到第一个可用团队成员。"""
    if auth_disabled() or user is None:
        return AuthContext()
    return await context_for_team(user, _selected_team_id(request))


async def context_for_team(user: User, team_id: int | None) -> AuthContext:
    """超管跨团队并保持超管权限；选定团队时附带该团队上下文与成员身份。"""
    if user.is_super_admin and team_id is None:
        return AuthContext(user=user, is_super_admin=True)
    query = TeamMember.filter(user=user, team__status=1, status=1).order_by("id")
    if team_id is not None:
        membership = await (
            query.filter(team_id=team_id).select_related("team").first()
        )
    else:
        membership = await query.select_related("team").first()
    if membership is None:
        if user.is_super_admin:
            return AuthContext(user=user, team_id=team_id, is_super_admin=True)
        raise HTTPException(status_code=403, detail=localized_message('没有加入任何可用团队'))
    return AuthContext(
        user=user,
        membership=membership,
        team_id=membership.team_id,
        is_super_admin=user.is_super_admin,
    )


def _selected_team_id(request: Request) -> Optional[int]:
    """解析 X-Team-Id 请求头（侧边栏团队选择器写入）。"""
    raw = request.headers.get("X-Team-Id", "")
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def require_roles(*roles: str):
    """角色守卫依赖工厂：超管放行；普通成员必须命中 roles 之一，否则 403。"""

    async def dependency(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth_disabled() or ctx.user is None or ctx.is_super_admin:
            return ctx
        if ctx.membership is None or ctx.membership.role not in roles:
            raise HTTPException(status_code=403, detail=localized_message('没有权限执行此操作'))
        return ctx

    return dependency


def ensure_project_creation_team(ctx: AuthContext) -> None:
    if not auth_disabled() and ctx.team_id is None:
        raise HTTPException(403, localized_message('请先切换到要创建作品的团队'))


async def require_super_admin(
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """超管守卫：仅平台超级管理员可访问。"""
    if auth_disabled():
        return ctx
    if not ctx.is_super_admin:
        raise HTTPException(status_code=403, detail=localized_message('仅超级管理员可执行此操作'))
    return ctx
