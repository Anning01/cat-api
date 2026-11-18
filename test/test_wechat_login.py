import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from auth import phone, wechat
from auth.models import PhoneAuthGuard, PhoneIdentity, User, UserSession, WechatIdentity, WechatLoginAttempt
from auth.security import hash_token
from auth.service import auth_service
from config import settings
from test.test_phone_auth import sms, challenge


@pytest.fixture
def wx(sms,monkeypatch):
    for key,value in {"WECHAT_LOGIN_ENABLED":True,"WECHAT_LOGIN_APP_ID":"wx-test-app",
        "WECHAT_LOGIN_APP_SECRET":"synthetic-secret","WECHAT_LOGIN_ORIGIN":"https://login.example"}.items():
        monkeypatch.setattr(settings,key,value)
    exchange=AsyncMock(return_value="wechat-person-a")
    monkeypatch.setattr(wechat,"exchange",exchange)
    return exchange


async def scan(wx,subject="wechat-person-a",confirm=True,user=None):
    wx.return_value=subject
    result=await wechat.start(user)
    state=parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]
    confirmation=await wechat.callback("only-test-code",state)
    if confirm:
        await wechat.confirm(confirmation)
    return result["attempt"],state,confirmation


async def phone_user(number="13800138000"):
    user=await User.create(username="user-"+number)
    await PhoneIdentity.create(user=user,phone_hash=phone.digest("phone:"+number),masked_phone=phone.masked(number))
    return user


async def test_unconfigured_is_disabled_without_creating_attempts(monkeypatch):
    monkeypatch.setattr(settings,"WECHAT_LOGIN_ENABLED",False)
    assert not wechat.enabled()
    with pytest.raises(HTTPException):await wechat.start()
    assert not await WechatLoginAttempt.all().exists()


async def test_qr_has_no_poll_secret_and_requires_explicit_phone_confirmation(wx):
    token,state,confirmation=await scan(wx,confirm=False)
    assert len(state)<=128 and state.isalnum()
    assert state!=token and confirmation!=token
    assert await wechat.poll(state)=={"status":"expired"}
    assert await wechat.poll(token)=={"status":"pending"}
    with pytest.raises(HTTPException):await wechat.confirm(state)
    await wechat.confirm(confirmation)
    assert (await wechat.poll(token))["status"]=="phone_required"
    assert not await User.all().exists() and not await UserSession.all().exists()
    with pytest.raises(HTTPException):await wechat.confirm(confirmation)


async def test_phone_verification_links_existing_account_then_scan_logs_it_in(wx,sms):
    owner=await phone_user()
    token,_,_=await scan(wx)
    args=await challenge(sms)
    result=await phone.verify(*args,wechat_attempt=token)
    assert result.user.id==owner.id
    identity=await WechatIdentity.get()
    assert identity.user_id==owner.id and identity.app_id=="wx-test-app"
    assert identity.subject_hash==hash_token("wx-test-app:wechat-person-a")
    assert await User.all().count()==1
    assert await wechat.poll(token)=={"status":"expired"}
    token,_,_=await scan(wx)
    result=await wechat.poll(token)
    assert result["status"]=="completed" and result["session"].user.id==owner.id
    assert await wechat.poll(token)=={"status":"expired"}


@pytest.mark.parametrize("already_has_phone", [False, True])
async def test_signed_in_migration_and_later_scan_login_work_without_sms(wx, sms, monkeypatch, already_has_phone):
    owner = await phone_user() if already_has_phone else await User.create(username="legacy-user")
    other = await User.create(username="other-user")
    monkeypatch.setattr(settings, "PHONE_AUTH_ENABLED", False)
    attempt, _, _ = await scan(wx, user=owner)

    assert await wechat.poll(attempt, other) == {"status": "expired"}
    assert await wechat.poll(attempt) == {"status": "expired"}
    replies = await asyncio.gather(*[wechat.poll(attempt, owner) for _ in range(4)])
    completed = [r for r in replies if r["status"] == "completed"]
    assert len(completed) == 1 and completed[0]["session"].user.id == owner.id
    assert (await WechatIdentity.get()).user_id == owner.id
    assert await PhoneIdentity.filter(user_id=owner.id).exists() == already_has_phone
    assert sms.await_count == 0

    public_attempt, _, _ = await scan(wx)
    assert (await wechat.poll(public_attempt))["session"].user.id == owner.id


@pytest.mark.parametrize("already_has_phone", [False, True])
async def test_previous_client_can_finish_an_in_flight_sms_migration(wx, sms, already_has_phone):
    number = "13800138000"
    owner = await phone_user(number) if already_has_phone else await User.create(username="legacy-user")
    other = await User.create(username="other-user")
    old_session = await auth_service.issue_session(owner)
    attempt, _, _ = await scan(wx, user=owner)
    assert await wechat.poll(attempt, other) == {"status": "expired"}
    assert await wechat.poll(attempt) == {"status": "expired"}

    with pytest.raises(HTTPException):
        await phone.start(number, "127.0.0.1", other, wechat_attempt=attempt)
    sent = await phone.start(number, "127.0.0.1", owner, wechat_attempt=attempt)
    code = sms.await_args.args[1]
    with pytest.raises(HTTPException):
        await phone.verify(number, sent["challenge"], code, owner)
    result = await phone.verify(number, sent["challenge"], code, owner, wechat_attempt=attempt)

    assert result.user.id == owner.id
    assert (await WechatIdentity.get()).user_id == owner.id
    assert (await PhoneIdentity.get()).user_id == owner.id
    assert await UserSession.filter(token_hash=hash_token(old_session.token)).exists() == already_has_phone
    assert await wechat.poll(attempt, owner) == {"status": "expired"}
    public_attempt, _, _ = await scan(wx)
    assert (await wechat.poll(public_attempt))["session"].user.id == owner.id


async def test_signed_in_migration_cannot_claim_a_phone_owned_by_another_account(wx, sms):
    other = await phone_user()
    owner = await User.create(username="legacy-user")
    attempt, _, _ = await scan(wx, user=owner)
    sent = await phone.start("13800138000", "127.0.0.1", owner, wechat_attempt=attempt)

    with pytest.raises(HTTPException, match="不能合并账号"):
        await phone.verify("13800138000", sent["challenge"], sms.await_args.args[1], owner, wechat_attempt=attempt)

    assert (await PhoneIdentity.get()).user_id == other.id
    assert not await WechatIdentity.exists()


async def test_unbound_wechat_creates_one_account_shared_with_sms_after_phone_verification(wx,sms,monkeypatch):
    token,_,_=await scan(wx)
    args=await challenge(sms)
    with pytest.raises(HTTPException):await phone.verify(*args,agreed=True,wechat_attempt=token)
    assert not await User.all().exists() and not await WechatIdentity.all().exists()
    monkeypatch.setattr(settings,"PHONE_SIGNUP_ENABLED",True)
    monkeypatch.setattr("services.legal_documents.require_profile",lambda:None)
    args=await challenge(sms,number="13900139000")
    result=await phone.verify(*args,agreed=True,wechat_attempt=token)
    assert (await PhoneIdentity.get()).user_id==result.user.id
    assert (await WechatIdentity.get()).user_id==result.user.id
    public_attempt, _, _ = await scan(wx)
    assert (await wechat.poll(public_attempt))["session"].user.id == result.user.id
    await PhoneAuthGuard.all().update(events=[])
    sms_session = await phone.verify(*await challenge(sms, number=args[0]), agreed=True)
    assert sms_session.user.id == result.user.id
    assert await User.all().count() == 1


async def test_wrong_sms_never_binds_wechat(wx,sms):
    await phone_user()
    token,_,_=await scan(wx)
    number,challenge_token,code=await challenge(sms)
    with pytest.raises(HTTPException):
        await phone.verify(number,challenge_token,"000000" if code!="000000" else "111111",wechat_attempt=token)
    assert not await WechatIdentity.all().exists() and not await UserSession.all().exists()


async def test_cannot_move_wechat_between_phone_accounts(wx,sms):
    first=await phone_user()
    await phone_user("13900139000")
    await WechatIdentity.create(user=first,app_id="wx-test-app",subject_hash=hash_token("wx-test-app:wechat-person-a"))
    token,_,_=await scan(wx)
    with pytest.raises(HTTPException) as error:
        await phone.verify(*await challenge(sms,number="13900139000"),wechat_attempt=token)
    assert error.value.status_code==409
    assert (await WechatIdentity.get()).user_id==first.id
    assert not await UserSession.all().exists()


async def test_cannot_replace_existing_wechat_and_failed_link_rolls_back_new_signup(wx,sms,monkeypatch):
    owner=await phone_user()
    await WechatIdentity.create(user=owner,app_id="wx-test-app",subject_hash=hash_token("wx-test-app:other-person"))
    token,_,_=await scan(wx)
    with pytest.raises(HTTPException):await phone.verify(*await challenge(sms),wechat_attempt=token)
    assert (await WechatIdentity.get()).subject_hash==hash_token("wx-test-app:other-person")
    monkeypatch.setattr(settings,"PHONE_SIGNUP_ENABLED",True)
    monkeypatch.setattr("services.legal_documents.require_profile",lambda:None)
    with pytest.raises(HTTPException):
        await phone.verify(*await challenge(sms,number="13900139000"),agreed=True,wechat_attempt="invalid"*8)
    assert await User.all().count()==1 and await PhoneIdentity.all().count()==1


async def test_expired_or_changed_app_attempts_cannot_be_used(wx,monkeypatch):
    token,_,_=await scan(wx)
    monkeypatch.setattr(settings,"WECHAT_LOGIN_APP_ID","wx-different-app")
    assert await wechat.poll(token)=={"status":"expired"}
    monkeypatch.setattr(settings,"WECHAT_LOGIN_APP_ID","wx-test-app")
    await WechatLoginAttempt.all().update(expires_at=wechat.now()-timedelta(seconds=1))
    assert await wechat.poll(token)=={"status":"expired"}


async def test_parallel_callbacks_exchange_once_and_poll_issues_one_session(wx):
    owner=await phone_user()
    await WechatIdentity.create(user=owner,app_id="wx-test-app",subject_hash=hash_token("wx-test-app:wechat-person-a"))
    started=await wechat.start()
    state=parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]
    replies=await asyncio.gather(*[wechat.callback("test-code",state) for _ in range(8)],return_exceptions=True)
    assert wx.await_count==1
    confirmations=[r for r in replies if isinstance(r,str)]
    assert len(confirmations)==1
    await wechat.confirm(confirmations[0])
    replies=await asyncio.gather(*[wechat.poll(started["attempt"]) for _ in range(8)])
    assert sum(r["status"]=="completed" for r in replies)==1
    assert await UserSession.all().count()==1


async def test_disabled_account_cannot_scan_login(wx):
    owner=await phone_user()
    await WechatIdentity.create(user=owner,app_id="wx-test-app",subject_hash=hash_token("wx-test-app:wechat-person-a"))
    token,_,_=await scan(wx)
    await User.filter(id=owner.id).update(status=0)
    with pytest.raises(HTTPException):await wechat.poll(token)
    assert not await UserSession.all().exists()


async def test_signed_in_migration_preserves_existing_wechat_and_incident_block(wx, monkeypatch):
    owner = await User.create(username="old-owner")
    other = await User.create(username="other-owner")
    await WechatIdentity.create(user=other, app_id=settings.WECHAT_LOGIN_APP_ID,
                                subject_hash=hash_token(settings.WECHAT_LOGIN_APP_ID + ":wechat-person-a"))
    taken, _, _ = await scan(wx, user=owner)
    with pytest.raises(HTTPException) as conflict:
        await wechat.poll(taken, owner)
    assert conflict.value.status_code == 409

    monkeypatch.setattr(settings, "PHONE_BIND_BLOCKED_USER_IDS", [str(owner.id)])
    blocked, _, _ = await scan(wx, user=owner, subject="new-wechat")
    with pytest.raises(HTTPException) as restriction:
        await wechat.poll(blocked, owner)
    assert restriction.value.status_code == 403
    assert (await WechatIdentity.get()).user_id == other.id


async def test_transport_is_fixed_to_wechat_and_sanitizes_provider_errors(monkeypatch):
    client=httpx.AsyncClient
    monkeypatch.setattr(settings,"WECHAT_LOGIN_APP_ID","wx-test")
    monkeypatch.setattr(settings,"WECHAT_LOGIN_APP_SECRET","do-not-expose")
    async def check(payload,status=200):
        def handler(request):
            assert request.url.host=="api.weixin.qq.com"
            assert request.url.params["appid"]=="wx-test"
            return httpx.Response(status,json=payload)
        monkeypatch.setattr(wechat.httpx,"AsyncClient",lambda **kw:client(transport=httpx.MockTransport(handler),**kw))
        return await wechat.exchange("test-code")
    assert await check({"openid":"person","access_token":"secret","scope":"snsapi_base"})=="person"
    for payload in [{"openid":123},{"openid":"person","access_token":"secret","scope":"wrong"},
                    {"errcode":40029,"errmsg":"do-not-expose"}]:
        with pytest.raises(HTTPException) as error:await check(payload)
        assert "do-not-expose" not in str(error.value)


async def test_callback_page_has_no_login_token_and_confirmation_is_one_time(wx):
    import re
    from main import app
    from httpx import ASGITransport,AsyncClient
    started=await wechat.start()
    state=parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]
    async with AsyncClient(transport=ASGITransport(app=app),base_url="https://test") as client:
        page=await client.get('/api/auth/wechat/callback',params={"code":"test-code","state":state})
        assert page.status_code==200 and '确认登录' in page.text
        assert started['attempt'] not in page.text and state not in page.text
        assert page.headers['referrer-policy']=='no-referrer'
        token=re.search(r'name="confirmation" value="([^"]+)"',page.text)[1]
        reply=await client.post('/api/auth/wechat/confirm',data={'confirmation':token})
        assert reply.status_code==200
        reply=await client.post('/api/auth/wechat/confirm',data={'confirmation':token})
        assert reply.status_code==400
        assert not await UserSession.all().exists()
