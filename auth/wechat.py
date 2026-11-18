"""Service-account OAuth with private polling secrets and account-scoped binding."""
from datetime import datetime, timedelta, timezone
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from auth.models import PhoneIdentity, User, UserAdminEvent, WechatIdentity, WechatLoginAttempt
from auth.security import hash_token, new_session_token
from auth.service import auth_service
from config import settings


def enabled() -> bool:
    try:
        origin = urlsplit(settings.WECHAT_LOGIN_ORIGIN)
        valid = (origin.scheme == "https" and origin.hostname and not origin.username
                 and not origin.password and not origin.query and not origin.fragment and not origin.path)
    except ValueError:
        valid = False
    return bool(settings.WECHAT_LOGIN_ENABLED and settings.WECHAT_LOGIN_APP_ID
                and settings.WECHAT_LOGIN_APP_SECRET and valid)


def require_enabled():
    if not enabled():
        raise HTTPException(503, "微信直登尚未配置，请使用其他登录方式")


def now():
    return datetime.now(timezone.utc)


def _attempt_hash(token: str, user_id: int | None) -> str:
    # Binding attempts can only be looked up by the account that started them.
    return hash_token(token if user_id is None else f"wechat-bind:{user_id}:{token}")


async def start(user: User | None = None) -> dict:
    require_enabled()
    state, token = secrets.token_hex(24), new_session_token()
    await WechatLoginAttempt.filter(expires_at__lte=now() - timedelta(days=1)).delete()
    await WechatLoginAttempt.create(token_hash=_attempt_hash(token, user.id if user else None), state_hash=hash_token(state),
                                   app_id=settings.WECHAT_LOGIN_APP_ID, expires_at=now()+timedelta(minutes=5))
    query = urlencode({"appid": settings.WECHAT_LOGIN_APP_ID,
                       "redirect_uri": settings.WECHAT_LOGIN_ORIGIN + "/api/auth/wechat/callback",
                       "response_type": "code", "scope": "snsapi_base", "state": state})
    return {"attempt": token, "authorization_url": "https://open.weixin.qq.com/connect/oauth2/authorize?"
            + query + "#wechat_redirect", "expires_in": 300}


async def exchange(code: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            response = await client.get("https://api.weixin.qq.com/sns/oauth2/access_token", params={
                "appid": settings.WECHAT_LOGIN_APP_ID, "secret": settings.WECHAT_LOGIN_APP_SECRET,
                "code": code, "grant_type": "authorization_code"})
            response.raise_for_status()
            data = response.json()
            if (isinstance(data, dict) and "errcode" not in data
                    and isinstance(data.get("openid"), str) and 0 < len(data["openid"]) <= 128
                    and data["openid"].strip() == data["openid"]
                    and isinstance(data.get("access_token"), str) and data["access_token"]
                    and "snsapi_base" in str(data.get("scope", "")).split(",")):
                return data["openid"]
    except (httpx.HTTPError, ValueError):
        pass
    raise HTTPException(502, "微信授权失败，请重新扫码")


async def callback(code: str, state: str) -> str:
    require_enabled()
    # Claim before contacting WeChat: duplicate/concurrent callbacks never exchange twice.
    claimed = await WechatLoginAttempt.filter(state_hash=hash_token(state),
        app_id=settings.WECHAT_LOGIN_APP_ID, status="pending", expires_at__gt=now()).update(status="exchanging")
    if not claimed:
        raise HTTPException(400, "二维码已使用或过期，请在登录页重新获取")
    try:
        subject = await exchange(code)
    except HTTPException:
        await WechatLoginAttempt.filter(state_hash=hash_token(state),status="exchanging").update(status="failed")
        raise
    confirmation = new_session_token()
    changed = await WechatLoginAttempt.filter(state_hash=hash_token(state),status="exchanging",
        app_id=settings.WECHAT_LOGIN_APP_ID, expires_at__gt=now()).update(
            status="confirm", subject_hash=hash_token(settings.WECHAT_LOGIN_APP_ID+":"+subject),
            confirmation_hash=hash_token(confirmation))
    if not changed:
        raise HTTPException(400, "二维码已过期，请重新扫码")
    return confirmation


async def confirm(token: str) -> None:
    require_enabled()
    changed = await WechatLoginAttempt.filter(confirmation_hash=hash_token(token), status="confirm",
        app_id=settings.WECHAT_LOGIN_APP_ID, expires_at__gt=now()).update(
            status="verified",confirmation_hash=None,expires_at=now()+timedelta(minutes=5))
    if not changed:
        raise HTTPException(400, "微信确认已失效，请重新扫码")


def _attempt(token: str, user_id: int | None = None):
    return WechatLoginAttempt.get_or_none(token_hash=_attempt_hash(token, user_id),
        app_id=settings.WECHAT_LOGIN_APP_ID, expires_at__gt=now())


async def poll(token: str, user: User | None = None) -> dict:
    require_enabled()
    try:
        async with in_transaction():
            # Authenticated binding and the previous SMS path lock the account first.
            target = await User.get(id=user.id).select_for_update() if user else None
            attempt = await _attempt(token, user.id if user else None).select_for_update()
            if not attempt or attempt.status == "consumed":
                return {"status": "expired"}
            if attempt.status in {"pending", "exchanging", "confirm"}:
                return {"status": "pending"}
            if attempt.status != "verified" or not attempt.subject_hash:
                return {"status": "failed"}
            if target:
                if target.status != 1 or str(target.id) in settings.PHONE_BIND_BLOCKED_USER_IDS:
                    raise HTTPException(403, "当前账号暂不能绑定微信，请联系支持")
                await _link_identity(attempt, target)
            else:
                identity = await WechatIdentity.get_or_none(app_id=attempt.app_id, subject_hash=attempt.subject_hash)
                if not identity:
                    from auth import phone
                    phone.require_enabled()
                    return {"status": "phone_required", "expires_in": max(0, int((attempt.expires_at - now()).total_seconds()))}
                target = await User.get(id=identity.user_id).select_for_update()
                if target.status != 1:
                    raise HTTPException(403, "账号不可登录，请联系支持")
                await _consume_attempt(attempt)
            return {"status": "completed", "session": await auth_service.issue_session(target)}
    except IntegrityError:
        raise HTTPException(409, "微信或账号已有其他绑定，不能覆盖或合并账号") from None


async def require_confirmed_binding(token: str, user: User):
    require_enabled()
    attempt = await _attempt(token, user.id)
    if not attempt or attempt.status != "verified" or not attempt.subject_hash:
        raise HTTPException(400, "微信授权已失效，请重新扫码后验证手机号")


async def link_verified_phone(token: str, user: User, *, binding: bool = False):
    """Called only inside the successful SMS verification transaction, before login."""
    require_enabled()
    attempt = await _attempt(token, user.id if binding else None).select_for_update()
    if not attempt or attempt.status != "verified" or not attempt.subject_hash:
        raise HTTPException(400, "微信授权已失效，请重新扫码后验证手机号")
    target = await User.get(id=user.id).select_for_update()
    if target.status != 1 or not await PhoneIdentity.filter(user_id=target.id).exists():
        raise HTTPException(403, "请先验证手机号")
    await _link_identity(attempt, target)


async def _link_identity(attempt: WechatLoginAttempt, target: User):
    identity = await WechatIdentity.get_or_none(app_id=attempt.app_id, subject_hash=attempt.subject_hash)
    current = await WechatIdentity.get_or_none(user_id=target.id)
    if ((identity and identity.user_id != target.id)
            or (current and (current.app_id != attempt.app_id or current.subject_hash != attempt.subject_hash))):
        raise HTTPException(409, "微信或手机号账号已有其他绑定，不能覆盖或合并账号")
    if not identity:
        await WechatIdentity.create(user=target, app_id=attempt.app_id, subject_hash=attempt.subject_hash)
        await UserAdminEvent.create(account_user_id=target.id,operator_user_id=target.id,action="wechat_bind")
    await _consume_attempt(attempt)


async def _consume_attempt(attempt: WechatLoginAttempt):
    attempt.status = "consumed"
    await attempt.save(update_fields=["status", "updated_at"])
