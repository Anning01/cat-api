import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from auth import phone
from auth.models import PhoneAuthGuard, PhoneChallenge, PhoneIdentity, QilingIdentity, User, UserSession
from auth.service import auth_service
from config import settings


@pytest.fixture
def sms(monkeypatch):
    for name, value in {"PHONE_AUTH_ENABLED": True, "PHONE_AUTH_SECRET": "test-secret-" * 5,
                        "SMS_ACCESS_KEY_ID": "test", "SMS_ACCESS_KEY_SECRET": "test",
                        "SMS_SIGN_NAME": "测试", "SMS_TEMPLATE_CODE": "test", "PHONE_BIND_BLOCKED_USER_IDS": [],
                        "PHONE_SIGNUP_ENABLED": False}.items():
        monkeypatch.setattr(settings, name, value)
    mock = AsyncMock()
    monkeypatch.setattr(phone.sms, "send_code", mock)
    return mock


async def challenge(sms, user=None, number="13800138000", ip="192.0.2.1"):
    result = await phone.start(number, ip, user)
    code = sms.call_args.args[1]
    return number, result["challenge"], code


async def test_binding_preserves_user_and_revokes_sessions(sms):
    from auth.models import UserWallet, PlatformApiKey
    user = await User.create(username="old", nickname="原账号")
    await UserWallet.create(user=user, balance=123)
    key=await PlatformApiKey.create(user=user,name="existing",token_hash="a"*64,preview="test")
    await auth_service.issue_session(user)
    await auth_service.issue_session(user)
    args = await challenge(sms, user)
    assert await phone.verify(*args, user) == {"status": "bound"}
    assert await User.all().count() == 1
    assert await UserSession.filter(user=user).count() == 0
    assert (await PhoneIdentity.get(user=user)).masked_phone == "138****8000"
    assert (await UserWallet.get(user=user)).balance == 123
    assert (await PlatformApiKey.get(id=key.id)).revoked_at is None
    with pytest.raises(HTTPException):
        await phone.verify(*args, user)


async def test_login_cannot_create_account_when_signup_is_disabled(sms):
    args = await challenge(sms)
    with pytest.raises(HTTPException) as error:
        await phone.verify(*args, agreed=True)
    assert error.value.status_code == 409
    assert await User.all().count() == 0


async def test_phone_sign_in_creates_an_account_once_after_verification_and_consent(sms, monkeypatch):
    monkeypatch.setattr(settings, "PHONE_SIGNUP_ENABLED", True)
    monkeypatch.setattr("services.legal_documents.require_profile", lambda: None)
    args = await challenge(sms)
    with pytest.raises(HTTPException) as error:
        await phone.verify(*args)
    assert error.value.status_code == 400
    assert not await User.exists()
    results = await asyncio.gather(phone.verify(*args, agreed=True), phone.verify(*args, agreed=True),
                                   return_exceptions=True)
    successes = [result for result in results if not isinstance(result, Exception)]
    assert len(successes) == 1
    result = successes[0]
    assert result.user.username.startswith("phone-")
    assert (await PhoneIdentity.get(phone_hash=phone.digest("phone:"+args[0]))).user_id == result.user.id
    await PhoneAuthGuard.all().update(events=[])
    second = await phone.verify(*await challenge(sms))
    assert second.user.id == result.user.id
    assert await User.all().count() == 1


async def test_phone_cannot_be_stolen_or_auto_merged(sms):
    owner = await User.create(username="owner")
    attacker = await User.create(username="another")
    await PhoneIdentity.create(user=owner, phone_hash=phone.digest("phone:13800138000"), masked_phone="138****8000")
    args = await challenge(sms, attacker)
    with pytest.raises(HTTPException) as error:
        await phone.verify(*args, attacker)
    assert error.value.status_code == 409
    assert (await PhoneIdentity.get(phone_hash=phone.digest("phone:"+args[0]))).user_id == owner.id


async def test_challenge_is_bound_to_purpose_user_and_number(sms):
    user = await User.create(username="original")
    other = await User.create(username="other")
    args = await challenge(sms, user)
    for attempt in [(*args, None), (*args, other), ("13900139000",args[1],args[2],user)]:
        with pytest.raises(HTTPException):
            await phone.verify(*attempt)
    assert await phone.verify(*args, user) == {"status": "bound"}


async def test_wrong_attempts_commit_and_resending_does_not_reset_lockout(sms):
    args = await challenge(sms)
    wrong = "111111" if args[2] != "111111" else "222222"
    for _ in range(5):
        with pytest.raises(HTTPException):
            await phone.verify(args[0], args[1], wrong)
    record = await PhoneChallenge.get()
    assert record.failures == 5 and record.consumed
    with pytest.raises(HTTPException):
        await phone.verify(*args)
    guard = await PhoneAuthGuard.get()
    guard.events = [e for e in guard.events if e[1] == "fail"]
    await guard.save()
    with pytest.raises(HTTPException) as error:
        await phone.start(args[0], "192.0.2.9")
    assert error.value.status_code == 429
    assert sms.await_count == 1


async def test_concurrent_send_is_limited_and_delivery_failure_keeps_quota(sms):
    results = await asyncio.gather(phone.start("13800138000","192.0.2.1"),
                                   phone.start("13800138000","192.0.2.2"), return_exceptions=True)
    assert sum(isinstance(r,dict) for r in results) == 1
    assert sms.await_count == 1
    sms.side_effect = HTTPException(503, "failed")
    with pytest.raises(HTTPException):
        await phone.start("13900139000", "192.0.2.1")
    with pytest.raises(HTTPException) as error:
        await phone.start("13900139000", "192.0.2.2")
    assert error.value.status_code == 429
    assert await PhoneChallenge.filter(ready=False).count() == 1


async def test_only_one_concurrent_verification_issues_a_session(sms):
    user = await User.create(username="phone-owner")
    await PhoneIdentity.create(user=user, phone_hash=phone.digest("phone:13800138000"), masked_phone="138****8000")
    args = await challenge(sms)
    results = await asyncio.gather(phone.verify(*args),phone.verify(*args),return_exceptions=True)
    assert sum(not isinstance(r,Exception) for r in results) == 1
    assert await UserSession.all().count() == 1


async def test_expired_code_and_disabled_user_are_rejected(sms):
    user = await User.create(username="disabled",status=0)
    await PhoneIdentity.create(user=user,phone_hash=phone.digest("phone:13800138000"),masked_phone="138****8000")
    args = await challenge(sms)
    with pytest.raises(HTTPException) as error:
        await phone.verify(*args)
    assert error.value.status_code == 403
    args = await challenge(sms, number="13900139000")
    await PhoneChallenge.all().update(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    with pytest.raises(HTTPException):
        await phone.verify(*args)
    assert await UserSession.all().count() == 0


async def test_secrets_and_full_phone_are_not_persisted(sms):
    args = await challenge(sms)
    record = str(await PhoneChallenge.all().values()) + str(await PhoneAuthGuard.all().values())
    assert args[0] not in record and args[1] not in record
    assert (await PhoneChallenge.get()).code_hash != args[2]


async def test_daily_budget_blocks_distributed_sends(sms,monkeypatch):
    monkeypatch.setattr(settings,"SMS_DAILY_LIMIT",1)
    await challenge(sms)
    with pytest.raises(HTTPException) as error:
        await phone.start("13900139000","192.0.2.200")
    assert error.value.status_code == 429
    assert sms.await_count == 1


@pytest.mark.parametrize("scope,count,age",[("phone",5,120),("phone",10,7200),("ip",20,120),("ip",50,7200)])
async def test_phone_and_ip_quotas_cover_hour_and_day(sms,scope,count,age):
    now=datetime.now(timezone.utc).timestamp()
    events=[[now-age,"send",phone.digest("phone:13800138000") if scope=="phone" else str(i),
             phone.digest("ip:192.0.2.1") if scope=="ip" else str(i)] for i in range(count)]
    await PhoneAuthGuard.create(name="sms",events=events)
    with pytest.raises(HTTPException) as error:
        await phone.start("13800138000","192.0.2.1")
    assert error.value.status_code==429
    assert sms.await_count==0


async def test_incident_account_cannot_bind(sms,monkeypatch):
    user=await User.create(username="incident")
    args=await challenge(sms,user)
    monkeypatch.setattr(settings,"PHONE_BIND_BLOCKED_USER_IDS",[str(user.id)])
    with pytest.raises(HTTPException):
        await phone.verify(*args,user)
    assert not await PhoneIdentity.all().exists()


async def test_migrated_account_cannot_login_through_qiling(sms,monkeypatch):
    from auth import qiling
    from auth.models import QilingLoginAttempt
    from auth.security import hash_token
    user=await User.create(username="migrated")
    monkeypatch.setattr(settings,"AUTH_PROVIDER","qiling")
    monkeypatch.setattr(settings,"QILING_API_BASE_URL","https://identity.example")
    await QilingIdentity.create(user=user,issuer=settings.QILING_API_BASE_URL,subject="old-id")
    await PhoneIdentity.create(user=user,phone_hash=phone.digest("phone:13800138000"),masked_phone="138****8000")
    await QilingLoginAttempt.create(token_hash=hash_token("test-attempt"),upstream_state="state",
        issuer=settings.QILING_API_BASE_URL,expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
    monkeypatch.setattr(qiling,"_request",AsyncMock(side_effect=[{"status":"completed","access_token":"fake"},{"sub":"old-id"}]))
    with pytest.raises(HTTPException) as error:
        await qiling.poll("test-attempt")
    assert error.value.status_code==403
    assert await UserSession.all().count()==0


async def test_api_validates_input_and_requires_auth_for_binding(sms,monkeypatch):
    from main import app
    from httpx import AsyncClient,ASGITransport
    from services.security.login_throttle import login_throttle
    monkeypatch.setattr(settings, "PHONE_SIGNUP_ENABLED", True)
    monkeypatch.setattr("services.legal_documents.require_profile", lambda: None)
    await login_throttle.reset()
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        for number in ["13800138000,13900139000", "1380013800", "+8613800138000", "１３８００１３８０００"]:
            reply=await client.post("/api/auth/phone/start",json={"phone":number})
            assert reply.json()["code"]==422
        reply=await client.post("/api/auth/phone/bind/start",json={"phone":"13800138000"})
        assert reply.json()["code"]==401
        assert sms.await_count==0
        reply=await client.post("/api/auth/phone/start",json={"phone":"13800138000"})
        payload=reply.json()["data"]
        assert set(payload)=={"challenge","expires_in","retry_after"}
        body = {"phone":"13800138000","code":sms.call_args.args[1],"challenge":payload["challenge"]}
        reply=await client.post("/api/auth/phone/login",json={**body,"agreed":False})
        assert reply.json()["code"]==400
        reply=await client.post("/api/auth/phone/login",json={**body,"agreed":True})
        assert reply.json()["data"]["user"]["id"] == (await PhoneIdentity.get()).user_id


async def test_provider_uses_approved_template_and_does_not_retry_or_expose_secrets(monkeypatch):
    from services import sms as provider
    from unittest.mock import Mock
    from types import SimpleNamespace
    fake=SimpleNamespace(send_sms_with_options_async=AsyncMock(return_value=SimpleNamespace(body=SimpleNamespace(code="OK"))))
    monkeypatch.setattr(provider,"Client",Mock(return_value=fake))
    monkeypatch.setattr(settings,"SMS_SIGN_NAME","approved-sign")
    monkeypatch.setattr(settings,"SMS_TEMPLATE_CODE","SMS_TEST")
    await provider.send_code("13800138000","012345")
    request,options=fake.send_sms_with_options_async.call_args.args
    assert request.phone_numbers=="13800138000" and request.sign_name=="approved-sign"
    assert request.template_code=="SMS_TEST" and "012345" in request.template_param
    assert options.autoretry is False
    fake.send_sms_with_options_async.side_effect=RuntimeError("provider-secret-012345")
    with pytest.raises(HTTPException) as error:
        await provider.send_code("13800138000","012345")
    assert "provider-secret" not in str(error.value) and "012345" not in str(error.value)
