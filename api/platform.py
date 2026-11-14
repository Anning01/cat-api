"""Account console, read-only legacy migration and external developer API."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import AwareDatetime, BaseModel, Field

from auth.deps import AuthContext, require_user, require_super_admin
from controllers.billing import billing_scope
from services.billing.aggregation import summary
from auth.models import PlatformApiKey, PlatformCallReceipt, StudioKeyGrant
from services.platform.temporary_media import UploadSpec, issue_upload
from schemas.platform_chat import ChatRequest
from schemas.platform_billing import PlatformReceiptOut, PlatformAccountOut
from services.platform.receipts import call_receipt
from services.platform.videos import VideoRequest, submit_video, video_status
from services.platform.images import needs_pixel_client, ImageRequest, generate as generate_platform_image
from services.platform.chat import complete
from services.platform.access import console_owner, create_key, developer_identity, key_view, reveal_key, revoke_key, studio_identity
from services.platform.catalog import model_catalog
from services.platform.http_contract import DeveloperRoute
from services.platform.documentation import agent_guide
from services.platform.request_data import validated_body, sdk_request_schema
from utils.response_format import ResponseSchema


console_router = APIRouter()
developer_router = APIRouter(route_class=DeveloperRoute)
from api.config import router as model_config_router
console_router.include_router(model_config_router, prefix="/config", dependencies=[Depends(require_super_admin)], include_in_schema=False)


class NewKey(BaseModel):
    # Retained for older clients; the console does not categorize keys by purpose.
    purpose: Literal["api", "studio"] = "api"
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    allowed_model_ids: list[Annotated[str, Field(pattern=r"^nv-[1-9][0-9]{0,9}$")]] | None = Field(default=None, min_length=1, max_length=1000)
    expires_at: AwareDatetime | None = None


@console_router.get("/platform/usage", include_in_schema=False)
async def platform_usage(
    ctx: AuthContext = Depends(require_user),
    days: Annotated[int | None, Query(ge=1, le=90)] = None,
):
    user_id = billing_scope(ctx)
    return ResponseSchema(data=await summary(account_user_id=user_id, cost_source="balance", recent_days=days))


@console_router.get("/platform/catalog")
async def console_catalog():
    return ResponseSchema(data=await model_catalog())


@console_router.get("/platform/keys", include_in_schema=False)
async def list_keys(ctx: AuthContext = Depends(console_owner)):
    rows = await PlatformApiKey.filter(user_id=ctx.user.id, revoked_at__isnull=True).order_by("-id")
    granted = set(await StudioKeyGrant.filter(key_id__in=[row.id for row in rows]).values_list("key_id", flat=True))
    return ResponseSchema(data=[{**key_view(row), "purpose":"studio" if row.id in granted else "api"} for row in rows])


@console_router.post("/platform/keys", include_in_schema=False)
async def new_key(body: NewKey, response: Response, ctx: AuthContext = Depends(console_owner)):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await create_key(ctx, body.name.strip(), studio=body.purpose == "studio",
        allowed_model_ids=body.allowed_model_ids, expires_at=body.expires_at))


@console_router.delete("/platform/keys/{key_id}", include_in_schema=False)
async def delete_key(key_id: int, ctx: AuthContext = Depends(console_owner)):
    await revoke_key(ctx, key_id)
    return ResponseSchema()


@console_router.get("/platform/keys/{key_id}/secret", include_in_schema=False)
async def read_key_secret(key_id: int, response: Response, ctx: AuthContext = Depends(console_owner)):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return ResponseSchema(data=await reveal_key(ctx, key_id))


@developer_router.get("/agent-guide.md", include_in_schema=False)
async def ai_integration_guide(request: Request):
    base_url = str(request.url).split("?", 1)[0].removesuffix("/agent-guide.md")
    return Response(agent_guide(base_url), media_type="text/markdown")


@developer_router.get("/llms.txt", include_in_schema=False)
async def ai_document_index(request: Request):
    base_url = str(request.url).split("?", 1)[0].removesuffix("/llms.txt")
    return Response(f"# 猫影模型 API\n\n- [AI Agent 接入说明]({base_url}/agent-guide.md)\n- [OpenAPI]({base_url}/openapi.json)\n", media_type="text/plain")


async def legacy_studio_images(request: Request, ctx):
    capabilities = request.headers.get("X-NovelVids-Capabilities")
    if capabilities is not None:
        return "pixel_tier_images" not in {v.strip() for v in capabilities.split(",")}
    return await StudioKeyGrant.filter(key_id=ctx.platform_key_id).exists()


@developer_router.get("/models", summary="列出当前平台模型")
async def models(request: Request, identifier: Literal["legacy", "alias"] = "legacy", ctx: AuthContext = Depends(developer_identity)):
    legacy = await legacy_studio_images(request, ctx)
    rows = [item for item in await model_catalog()
        if (ctx.allowed_model_ids is None or item["id"] in ctx.allowed_model_ids)
        and not (legacy and needs_pixel_client(item["image_model_type"], item["pricing"]))]
    return {"object":"list","data":[{"object":"model", "owned_by":"novelvids", **item,
        "legacy_id":item["id"], "id":item["alias"] if identifier == "alias" and item["alias"] else item["id"]} for item in rows]}


@developer_router.get("/account", summary="查询 Key 所属平台账户余额", response_model=PlatformAccountOut)
async def platform_account(request: Request, response: Response, ctx: AuthContext = Depends(developer_identity)):
    from services.balance import get_balance
    response.headers["Cache-Control"] = "no-store"
    origin = str(request.url).split("/v1/", 1)[0]
    return PlatformAccountOut(balance=await get_balance(ctx.user.id), recharge_url=f"{origin}/#/profile?recharge=1")



@developer_router.post("/chat/completions", summary="对话生成与流式返回")
async def chat_completions(body: ChatRequest, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    return await complete(ctx, body, idempotency_key)


@developer_router.get("/requests/{request_id}", summary="查询调用及结算状态", response_model=PlatformReceiptOut)
async def call_status(request_id: UUID, response: Response, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await call_receipt(request_id, ctx)


@developer_router.get("/requests", summary="按原请求标识恢复结算回执", response_model=PlatformReceiptOut)
async def call_status_by_key(request_key: Annotated[str, Query(min_length=1, max_length=200)], response: Response, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await call_receipt(request_key, ctx, by_key=True)




@developer_router.post("/studio/media-lease", include_in_schema=False)
async def studio_media_lease(body: UploadSpec, response: Response, ctx: AuthContext = Depends(studio_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await issue_upload(ctx.user.id, body)


@developer_router.post("/images/generations", summary="生成图像并返回结果链接")
async def images(request: Request, body: ImageRequest, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    return await generate_platform_image(ctx, body, idempotency_key, legacy_studio=await legacy_studio_images(request, ctx))


@developer_router.post("/images/edits", summary="使用已上传的参考图", openapi_extra=sdk_request_schema(ImageRequest))
async def edit_images(request: Request, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    body = validated_body(ImageRequest, await request.json())
    if not body.reference_urls():
        raise HTTPException(400, "image must contain reference URLs uploaded to temporary storage")
    return await generate_platform_image(ctx, body, idempotency_key, edit=True, legacy_studio=await legacy_studio_images(request, ctx))


@developer_router.post("/images", summary="OpenRouter 原生图片接口")
async def openrouter_images(request: Request, body: ImageRequest, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    return await generate_platform_image(ctx, body, idempotency_key, protocol="openrouter_compatible", legacy_studio=await legacy_studio_images(request, ctx))


@developer_router.post("/media/uploads", summary="申请临时 OSS 直传地址")
async def temporary_upload(body: UploadSpec, response: Response, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await issue_upload(ctx.user.id, body)


@developer_router.post("/videos", summary="提交视频生成", openapi_extra=sdk_request_schema(VideoRequest))
async def create_video(request: Request, response: Response, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    body = validated_body(VideoRequest, await request.json())
    job = await submit_video(ctx, body, idempotency_key)
    response.headers["X-Request-Id"] = job["id"]
    response.headers["Cache-Control"] = "no-store"
    return job


@developer_router.get("/videos/{identifier}", summary="查询视频生成状态及结果链接")
async def read_video(identifier: str, response: Response, refresh: bool = False, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    try:
        by_key = identifier.startswith("req-")
        value = UUID(identifier[4:] if by_key else identifier)
    except ValueError:
        raise HTTPException(404, "视频请求不存在") from None
    return await video_status(ctx, key=value,refresh=refresh) if by_key else await video_status(ctx, public_id=value,refresh=refresh)


@developer_router.get("/videos/{identifier}/content", summary="下载已完成的视频")
async def video_content(identifier: str, variant: Literal["video", "thumbnail", "spritesheet"] = "video",
    ctx: AuthContext = Depends(developer_identity)):
    if variant != "video":
        raise HTTPException(400, "Selected provider does not expose this video variant")
    try:
        value = UUID(identifier)
    except ValueError:
        raise HTTPException(404, "Video not found") from None
    job = await video_status(ctx, public_id=value, refresh=True)
    url = (job.get("metadata") or {}).get("url")
    if job["status"] != "completed" or not url:
        raise HTTPException(409, "Video is not ready")
    return RedirectResponse(url, status_code=307, headers={"Cache-Control":"no-store"})


from api.native import router as native_router
developer_router.include_router(native_router)


from services.platform.docs_settings import DocumentationSettings, documentation_settings, update_documentation


@console_router.get("/platform/documentation", include_in_schema=False)
async def read_documentation_settings():
    return ResponseSchema(data=(await documentation_settings()).model_dump())


@console_router.patch("/platform/documentation", include_in_schema=False)
async def save_documentation_settings(body: DocumentationSettings, ctx: AuthContext = Depends(require_super_admin)):
    return ResponseSchema(data=(await update_documentation(body)).model_dump())


@console_router.get("/platform/openapi-export", include_in_schema=False)
async def export_public_openapi():
    from fastapi.responses import JSONResponse
    from main import developer_api
    return JSONResponse(developer_api.openapi(), headers={
        "Content-Disposition":'attachment; filename="cat-api-openapi.json"', "Cache-Control":"no-store"})
