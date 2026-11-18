"""鉴权 API：状态探测 / 登录 / 当前用户 / 登出。

`public_router`（/status）在两种模式下都注册，供前端判断开关状态；
其余路由仅在 AUTH_ENABLED=true 时由 main.py 注册。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auth import qiling, phone, wechat
from auth.deps import AuthContext, extract_bearer_token, get_auth_context, get_current_user
from auth.schemas import ChangePasswordIn, LoginIn, LoginOut, MeOut, ProfileUpdateIn, RegisterIn, UserOut
from auth.service import auth_service
from config import settings
from services.security.login_throttle import login_throttle, client_ip
from utils.response_format import ResponseSchema
from services.legal_documents import profile_status, render
from typing import Literal

public_router = APIRouter()

router = APIRouter()


@public_router.get("/status", summary="登录功能状态探测", response_model=ResponseSchema[dict])
async def auth_status():
    legal, missing = profile_status()
    return ResponseSchema(data={"enabled": settings.AUTH_ENABLED, "provider": settings.AUTH_PROVIDER,
                                "deployment_role": settings.DEPLOYMENT_ROLE,
                                "legacy_works_enabled": settings.LEGACY_WORKS_ENABLED,
                                "qiling_enabled": qiling.enabled(), "legal_ready": legal is not None,
                                "phone_enabled": phone.enabled(),
                                "wechat_enabled": wechat.enabled(),
                                "phone_signup_enabled": settings.PHONE_SIGNUP_ENABLED,
                                "legal_missing": missing})


@public_router.get("/legal/{kind}", response_class=HTMLResponse)
async def legal_document(kind: Literal["terms", "privacy"]):
    return HTMLResponse(render(kind), headers={"Cache-Control": "no-store"})


def password_provider():
    if settings.AUTH_PROVIDER != "password":
        raise HTTPException(404, "账号密码登录未启用")


@router.post("/login", response_model=ResponseSchema[LoginOut], dependencies=[Depends(password_provider)])
async def password_login(data: LoginIn, request: Request):
    attempt = await login_throttle.before_attempt(request, data.username)
    try:
        result = await auth_service.login(data)
    except HTTPException:
        await login_throttle.record_failure(attempt)
        raise
    await login_throttle.record_success(attempt)
    return ResponseSchema(data=result)


@router.post("/register", response_model=ResponseSchema[LoginOut], dependencies=[Depends(password_provider)])
async def password_register(data: RegisterIn, request: Request):
    await login_throttle.before_attempt(request, data.username)
    return ResponseSchema(data=await auth_service.register(data))


@router.post("/change-password", dependencies=[Depends(password_provider)])
async def password_change(data: ChangePasswordIn, user=Depends(get_current_user)):
    await auth_service.change_password(user, data.old_password, data.new_password)
    return ResponseSchema(data=None, message="密码已修改")


class QilingPollIn(BaseModel):
    attempt: str = Field(min_length=32, max_length=64)


class PhoneIn(BaseModel):
    phone: str = Field(pattern=r"^1[3-9][0-9]{9}$", min_length=11, max_length=11)


class PhoneBindingIn(PhoneIn):
    wechat_attempt: str | None = Field(default=None, min_length=32, max_length=64)


class PhoneVerifyIn(PhoneBindingIn):
    challenge: str = Field(min_length=32, max_length=64)
    code: str = Field(pattern=r"^[0-9]{6}$", min_length=6, max_length=6)
    agreed: bool = False


@router.post("/phone/start")
async def phone_start(data: PhoneIn, request: Request):
    await login_throttle.before_attempt(request, "phone-send")
    return ResponseSchema(data=await phone.start(data.phone, client_ip(request)))


@router.post("/phone/login")
async def phone_login(data: PhoneVerifyIn, request: Request):
    await login_throttle.before_attempt(request, "phone-verify")
    if data.wechat_attempt and not data.agreed:
        raise HTTPException(400, "请先阅读并同意用户协议和隐私政策")
    return ResponseSchema(data=await phone.verify(data.phone, data.challenge, data.code,
        agreed=data.agreed, wechat_attempt=data.wechat_attempt))


@router.post("/wechat/start")
async def wechat_start(request: Request):
    await login_throttle.before_attempt(request, "wechat-start")
    return ResponseSchema(data=await wechat.start())


@router.post("/wechat/poll")
async def wechat_poll(data: QilingPollIn, request: Request):
    await login_throttle.before_attempt(request, "wechat-poll")
    return ResponseSchema(data=await wechat.poll(data.attempt))


@router.post("/wechat/bind/start")
async def wechat_bind_start(request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "wechat-start")
    return ResponseSchema(data=await wechat.start(user))


@router.post("/wechat/bind/poll")
async def wechat_bind_poll(data: QilingPollIn, request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "wechat-poll")
    return ResponseSchema(data=await wechat.poll(data.attempt, user))


@router.get("/wechat/callback", response_class=HTMLResponse)
async def wechat_callback(code: str = Query(min_length=1, max_length=512),
                          state: str = Query(min_length=32, max_length=128)):
    try:
        confirmation = await wechat.callback(code, state)
        return wechat_page('请确认在发起扫码的设备上登录 Cat API。如果不是你本人发起，请关闭此页面。'
            '<form method="post" action="/api/auth/wechat/confirm">'
            '<input type="hidden" name="confirmation" value="'+confirmation+'">'
            '<button type="submit">确认登录</button></form>',200)
    except HTTPException:
        return wechat_page("微信验证未完成或二维码已失效，请返回登录页重新扫码。",400)


@router.post("/wechat/confirm",response_class=HTMLResponse)
async def wechat_confirm(confirmation: str = Form(min_length=32,max_length=64)):
    try:
        await wechat.confirm(confirmation)
        return wechat_page('微信验证完成，请返回发起扫码的页面继续。'
            '<p>如果在本手机发起登录，可<a href="/#/login?method=wechat">返回登录页面</a>继续。</p>',200)
    except HTTPException:
        return wechat_page("微信确认已失效，请返回登录页重新扫码。",400)


def wechat_page(message: str, status: int):
    # Only static strings and server-generated URL-safe secrets are rendered here.
    return HTMLResponse('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>微信登录 · Cat API</title><style>body{font:16px/1.7 system-ui,sans-serif;'
        'margin:0;background:#f6f7fb;color:#202532}main{max-width:28rem;margin:10vh auto;padding:24px}'
        'button{font:inherit;min-height:48px;padding:10px 28px;border:0;border-radius:8px;'
        'background:#5d54d9;color:white;margin-top:24px;cursor:pointer}'
        'button:focus-visible{outline:3px solid #24205f;outline-offset:4px}</style></head>'
        '<body><main><h1>Cat API</h1><div>'+message+'</div></main></body></html>',status_code=status,
        headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer"})


@router.post("/phone/bind/start")
async def phone_bind_start(data: PhoneBindingIn, request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "phone-bind-send")
    return ResponseSchema(data=await phone.start(data.phone, client_ip(request), user, wechat_attempt=data.wechat_attempt))


@router.post("/phone/bind")
async def phone_bind(data: PhoneVerifyIn, request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "phone-bind-verify")
    return ResponseSchema(data=await phone.verify(data.phone, data.challenge, data.code, user, wechat_attempt=data.wechat_attempt))


@router.post("/qiling/start")
async def qiling_start(request: Request):
    await login_throttle.before_attempt(request, "qiling-start")
    return ResponseSchema(data=await qiling.start())


@router.post("/qiling/poll")
async def qiling_poll(data: QilingPollIn, request: Request):
    await login_throttle.before_attempt(request, "qiling-poll")
    return ResponseSchema(data=await qiling.poll(data.attempt))


@router.post("/qiling/bind/start")
async def qiling_bind_start(request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "qiling-bind-start")
    return ResponseSchema(data=await qiling.start(user))


@router.post("/qiling/bind/poll")
async def qiling_bind_poll(data: QilingPollIn, request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "qiling-bind-poll")
    return ResponseSchema(data=await qiling.poll(data.attempt, user))


@router.get("/me", summary="当前用户信息", response_model=ResponseSchema[MeOut])
async def me(user=Depends(get_current_user)):
    return ResponseSchema(data=await auth_service.me(user))


@router.patch('/profile', summary='修改本人的昵称', response_model=ResponseSchema[UserOut])
async def update_profile(data: ProfileUpdateIn, user=Depends(get_current_user)):
    from services.user_profile import update_nickname
    return ResponseSchema(data=await update_nickname(user, data.nickname))


@router.post('/avatar', summary='上传本人的头像', response_model=ResponseSchema[UserOut])
async def upload_avatar(file: UploadFile = File(...), user=Depends(get_current_user)):
    from services.user_profile import update_avatar
    return ResponseSchema(data=await update_avatar(user, file))


@router.post("/logout", summary="退出登录", response_model=ResponseSchema[None])
async def logout(request: Request):
    await auth_service.logout(extract_bearer_token(request))
    return ResponseSchema(data=None, message="已退出登录")
