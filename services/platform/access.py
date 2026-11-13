"""Developer keys authorize external model requests within the issuing user's account."""
from datetime import datetime, timezone
import secrets
from cryptography.fernet import Fernet, InvalidToken

from fastapi import Depends, HTTPException, Request
from auth.deps import AuthContext, require_user
from auth.models import PlatformApiKey, StudioKeyGrant
from tortoise.transactions import in_transaction
from auth.security import hash_token
from utils.enums import UserStatusEnum
from config import settings


async def console_owner(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    if not ctx.user:
        raise HTTPException(403, "请登录")
    return ctx


def key_view(row):
    return {"id": row.id, "name": row.name, "preview": row.preview, "created_at": row.created_at,
            "allowed_model_ids": row.allowed_model_ids, "expires_at": row.expires_at,
            "is_expired": row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc),
            "can_reveal": bool(row.encrypted_token)}


def _key_cipher() -> Fernet:
    try:
        return Fernet(settings.API_KEY_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "API Key 加密配置缺失或无效，请联系管理员") from None


async def reveal_key(ctx, key_id):
    row = await PlatformApiKey.get_or_none(id=key_id, user_id=ctx.user.id, revoked_at__isnull=True)
    if row is None:
        raise HTTPException(404, "API Key 不存在")
    if not row.encrypted_token:
        raise HTTPException(409, "旧密钥尚无可恢复副本，正常使用一次后可再次查看")
    try:
        raw = _key_cipher().decrypt(row.encrypted_token.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise HTTPException(503, "密钥暂时无法读取，请检查服务端加密配置") from None
    if not secrets.compare_digest(hash_token(raw), row.token_hash):
        raise HTTPException(503, "密钥数据校验失败，请联系管理员")
    return {"key": raw}


async def create_key(ctx, name, *, studio=False, allowed_model_ids=None, expires_at=None):
    if expires_at is not None and (expires_at.utcoffset() is None or expires_at <= datetime.now(timezone.utc)):
        raise HTTPException(422, "到期时间必须晚于当前时间，并包含时区")
    if allowed_model_ids is not None:
        from services.platform.catalog import model_catalog
        available = {model["id"] for model in await model_catalog()}
        if not allowed_model_ids or not set(allowed_model_ids).issubset(available):
            raise HTTPException(422, "请选择有效且已启用的模型")
        allowed_model_ids = sorted(set(allowed_model_ids))
    raw = "nv_" + secrets.token_urlsafe(32)
    encrypted = _key_cipher().encrypt(raw.encode()).decode()
    async with in_transaction() as db:
        row = await PlatformApiKey.create(using_db=db, user_id=ctx.user.id, name=name,
                                          token_hash=hash_token(raw), preview=raw[:7] + "…" + raw[-4:],
                                          allowed_model_ids=allowed_model_ids, expires_at=expires_at, encrypted_token=encrypted)
        if studio:
            await StudioKeyGrant.create(using_db=db, key=row)
    return {**key_view(row), "key": raw, "purpose":"studio" if studio else "api"}


async def revoke_key(ctx, key_id):
    updated = await PlatformApiKey.filter(id=key_id, user_id=ctx.user.id,
        revoked_at__isnull=True).update(revoked_at=datetime.now(timezone.utc))
    if not updated:
        raise HTTPException(404, "API Key 不存在")


async def developer_identity(request: Request) -> AuthContext:
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    if not authorization and "/auc/bigmodel/" in request.url.path:
        scheme, value = "bearer", request.headers.get("x-api-key") or request.headers.get("x-api-access-key", "")
    elif authorization.startswith("nv_") and "/comfyui_workflow/" in request.url.path:
        scheme, value = "bearer", authorization
    if scheme.lower() != "bearer" or not value.startswith("nv_") or len(value) > 128:
        raise HTTPException(401, "需要有效的 API Key", headers={"WWW-Authenticate": "Bearer"})
    row = await PlatformApiKey.get_or_none(token_hash=hash_token(value), revoked_at__isnull=True).select_related("user")
    if not row:
        raise HTTPException(401, "API Key 无效或已撤销", headers={"WWW-Authenticate": "Bearer"})
    if row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "API Key 已过期", headers={"WWW-Authenticate": "Bearer"})
    if row.user.status != UserStatusEnum.active.value:
        raise HTTPException(403, "账户已停用")
    if row.encrypted_token is None and settings.API_KEY_ENCRYPTION_KEY:
        try:
            encrypted = _key_cipher().encrypt(value.encode()).decode()
        except HTTPException:
            pass  # Archival configuration must not invalidate an existing, valid credential.
        else:
            await PlatformApiKey.filter(id=row.id, encrypted_token__isnull=True).update(encrypted_token=encrypted)
    request.state.platform_key_id = row.id
    ctx = AuthContext(user=row.user, is_super_admin=row.user.is_super_admin, platform_key_id=row.id,
                      allowed_model_ids=frozenset(row.allowed_model_ids) if row.allowed_model_ids is not None else None)
    return ctx


async def studio_identity(request: Request, ctx: AuthContext = Depends(developer_identity)):
    # Compatibility alias for /media/uploads; keys are not restricted by client purpose.
    return ctx


def authorize_model(ctx: AuthContext, model_id: int) -> None:
    if ctx.allowed_model_ids is not None and f"nv-{model_id}" not in ctx.allowed_model_ids:
        raise HTTPException(403, "此 API Key 未获准调用该模型")
