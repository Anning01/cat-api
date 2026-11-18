"""Phone-first authentication with persistent quotas and one-time challenges."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from auth.models import PhoneAuthGuard, PhoneChallenge, PhoneIdentity, User, UserAdminEvent, UserSession
from auth.security import hash_token, new_session_token
from auth.service import auth_service
from config import settings
from services import sms


def enabled() -> bool:
    return bool(settings.PHONE_AUTH_ENABLED and len(settings.PHONE_AUTH_SECRET) >= 32
                and settings.SMS_ACCESS_KEY_ID and settings.SMS_ACCESS_KEY_SECRET
                and settings.SMS_SIGN_NAME and settings.SMS_TEMPLATE_CODE)


def require_enabled():
    if not enabled():
        raise HTTPException(503, "手机验证码登录尚未配置")


def digest(value: str) -> str:
    return hmac.new(settings.PHONE_AUTH_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def masked(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:]


async def _guard(now: float):
    guard = await PhoneAuthGuard.get(name="sms").select_for_update()
    guard.events = [e for e in guard.events if e[0] > now - 86400]
    return guard


def _challenge_hash(token: str, binding_attempt: str | None) -> str:
    return hash_token(f"wechat-bind:{binding_attempt}:{token}" if binding_attempt else token)


async def start(phone: str, ip: str, user: User | None = None, *, wechat_attempt: str | None = None) -> dict:
    require_enabled()
    key = digest("phone:" + phone)
    if user:
        if str(user.id) in settings.PHONE_BIND_BLOCKED_USER_IDS:
            raise HTTPException(403, "当前账号暂不能绑定手机，请联系支持处理账号异常")
        if wechat_attempt:
            from auth.wechat import require_confirmed_binding
            await require_confirmed_binding(wechat_attempt, user)
            current = await PhoneIdentity.get_or_none(user_id=user.id)
            if current and current.phone_hash != key:
                raise HTTPException(409, "请验证当前账号已绑定的手机号")
        elif await PhoneIdentity.filter(user_id=user.id).exists():
            raise HTTPException(409, "账号已绑定手机号；更换手机号请联系支持")
    await PhoneAuthGuard.get_or_create(name="sms")
    now = datetime.now(timezone.utc)
    stamp, ip_key = now.timestamp(), digest("ip:" + ip)
    token, code = new_session_token(), f"{secrets.randbelow(1000000):06d}"
    challenge_hash = _challenge_hash(token, wechat_attempt if user else None)
    async with in_transaction():
        guard = await _guard(stamp)
        sent = [e for e in guard.events if e[1] == "send"]
        personal = [e for e in sent if e[2] == key]
        by_ip = [e for e in sent if e[3] == ip_key]
        if (any(e[0] > stamp - 60 for e in personal) or len(personal) >= 10
                or sum(e[0] > stamp - 3600 for e in personal) >= 5
                or len(by_ip) >= 50 or sum(e[0] > stamp - 3600 for e in by_ip) >= 20
                or len(sent) >= settings.SMS_DAILY_LIMIT):
            raise HTTPException(429, "验证码请求过于频繁，请稍后再试", headers={"Retry-After": "60"})
        if sum(e[1] == "fail" and e[2] == key and e[0] > stamp - 900 for e in guard.events) >= 5:
            raise HTTPException(429, "验证码错误次数过多，请15分钟后重试")
        guard.events.append([stamp, "send", key, ip_key])
        await guard.save(update_fields=["events", "updated_at"])
        await PhoneChallenge.filter(expires_at__lte=now - timedelta(days=1)).delete()
        await PhoneChallenge.filter(phone_hash=key, consumed=False).update(consumed=True)
        await PhoneChallenge.create(token_hash=challenge_hash, phone_hash=key,
                                    purpose="bind" if user else "login", user=user,
                                    code_hash=digest(token + ":" + code),
                                    expires_at=now + timedelta(minutes=5))
    await sms.send_code(phone, code)
    await PhoneChallenge.filter(token_hash=challenge_hash, consumed=False).update(ready=True)
    return {"challenge": token, "expires_in": 300, "retry_after": 60}


async def verify(phone: str, token: str, code: str, user: User | None = None, *,
                 agreed: bool = False, wechat_attempt: str | None = None):
    require_enabled()
    await PhoneAuthGuard.get_or_create(name="sms")
    now = datetime.now(timezone.utc)
    key = digest("phone:" + phone)
    error = None
    result = None
    try:
        async with in_transaction():
            guard = await _guard(now.timestamp())
            challenge = await PhoneChallenge.get_or_none(
                token_hash=_challenge_hash(token, wechat_attempt if user else None)).select_for_update()
            if (not challenge or not challenge.ready or challenge.consumed or challenge.expires_at <= now
                    or challenge.phone_hash != key or challenge.user_id != (user.id if user else None)
                    or challenge.purpose != ("bind" if user else "login")):
                raise HTTPException(400, "验证码无效或已过期，请重新获取")
            if sum(e[1] == "fail" and e[2] == key and e[0] > now.timestamp() - 900 for e in guard.events) >= 5:
                raise HTTPException(429, "验证码错误次数过多，请15分钟后重试")
            if not hmac.compare_digest(challenge.code_hash, digest(token + ":" + code)):
                challenge.failures += 1
                challenge.consumed = challenge.failures >= 5
                await challenge.save(update_fields=["failures", "consumed", "updated_at"])
                guard.events.append([now.timestamp(), "fail", key, ""])
                await guard.save(update_fields=["events", "updated_at"])
                error = HTTPException(400, "验证码错误，请重新输入")
            else:
                challenge.consumed = True
                await challenge.save(update_fields=["consumed", "updated_at"])
                identity = await PhoneIdentity.get_or_none(phone_hash=key).select_related("user")
                if user:
                    target = await User.get(id=user.id).select_for_update()
                    current = await PhoneIdentity.get_or_none(user_id=target.id)
                    if target.status != 1 or str(user.id) in settings.PHONE_BIND_BLOCKED_USER_IDS:
                        error = HTTPException(403, "当前账号暂不能绑定手机，请联系支持")
                    elif current and wechat_attempt and current.phone_hash != key:
                        error = HTTPException(409, "请验证当前账号已绑定的手机号")
                    elif (identity and identity.user_id != target.id) or (current and not wechat_attempt):
                        error = HTTPException(409, "手机号或账号已绑定，不能合并账号")
                    else:
                        if not current:
                            await PhoneIdentity.create(user=target, phone_hash=key, masked_phone=masked(phone))
                            await UserAdminEvent.create(account_user_id=user.id, operator_user_id=user.id,
                                                        action="phone_bind", note=masked(phone))
                            await UserSession.filter(user_id=user.id).delete()
                        if wechat_attempt:
                            from auth.wechat import link_verified_phone
                            await link_verified_phone(wechat_attempt, target, binding=True)
                            result = await auth_service.issue_session(target)
                        else:
                            result = {"status": "bound"}
                else:
                    if identity:
                        target = identity.user
                    elif not settings.PHONE_SIGNUP_ENABLED:
                        target = None
                        error = HTTPException(409, (
                            "手机号尚未绑定账号，请联系支持"
                            if settings.AUTH_PROVIDER == "wechat"
                            else "手机号尚未绑定，请先登录原账号绑定"
                        ))
                    else:
                        if not agreed:
                            raise HTTPException(400, "请先阅读并同意用户协议和隐私政策")
                        from services.legal_documents import require_profile
                        require_profile()
                        target = await User.create(username="phone-" + uuid4().hex, nickname="手机用户")
                        await PhoneIdentity.create(user=target, phone_hash=key, masked_phone=masked(phone))
                    if target:
                        if target.status != 1:
                            error = HTTPException(403, "账号已停用")
                        else:
                            if wechat_attempt:
                                from auth.wechat import link_verified_phone
                                await link_verified_phone(wechat_attempt, target)
                            result = await auth_service.issue_session(target)
    except IntegrityError:
        raise HTTPException(409, "手机号或账号已绑定，请重新登录") from None
    if error:
        raise error
    return result
