"""Standalone Cat API application."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from utils.response_format import ResponseSchema
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from tortoise import Tortoise

from api.billing import router as billing_router
from api.platform import console_router, developer_router
from api.account import router as account_router
from api.user import router as user_router
from auth.api import router as auth_router, public_router
from auth.bootstrap import ensure_super_admin
from config import settings
from controllers.account import account_controller
from exceptions.handlers import http_exception_handler, validation_exception_handler
from services.security.headers import SecurityHeadersMiddleware
from services.platform.calls import recover_measured
from services.platform.chat import settle_periodically, stop_streams
from services.platform.http_contract import DEVELOPER_EXCEPTION_HANDLERS
from services.platform.temporary_media import expire_periodically
from services.platform.videos import reconcile_videos
from services.schema_compat import (
    _ensure_qiling_issuer_columns, ensure_billing_integration_schema, ensure_recharge_refund_columns,
)


@asynccontextmanager
async def lifespan(_app):
    if settings.DATABASE_URL == "sqlite://./data/cat-api.db":
        Path("data").mkdir(exist_ok=True)
    await Tortoise.init(db_url=settings.DATABASE_URL, modules={
        "models": ["auth.models", "models.config", "models.usage_record"],
    }, timezone=settings.TIMEZONE)
    try:
        await ensure_billing_integration_schema()
        await _ensure_qiling_issuer_columns(Tortoise.get_connection("default"))
        await ensure_recharge_refund_columns()
        if settings.GENERATE_SCHEMAS:
            await Tortoise.generate_schemas(safe=True)
        from services.video.ark_migration import migrate_legacy_video_channels
        await migrate_legacy_video_channels()
        from services.migrations.user_accounts import migrate_user_accounts
        await migrate_user_accounts()
        await ensure_super_admin()
        await recover_measured()
        workers = [asyncio.create_task(worker()) for worker in
                   (settle_periodically, expire_periodically, reconcile_videos)]
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await stop_streams()
    finally:
        await Tortoise.close_connections()


app = FastAPI(title="Cat API", lifespan=lifespan, docs_url="/console-docs")
app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-Id", "X-Novelvids-Request-Id"])
if settings.SECURITY_HEADERS_ENABLED:
    app.add_middleware(SecurityHeadersMiddleware, content_security_policy=settings.CONTENT_SECURITY_POLICY,
                       docs_content_security_policy=settings.DOCS_CONTENT_SECURITY_POLICY)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


@app.get("/api/config/locale")
async def locale():
    from services.language import configured_language
    return ResponseSchema(data={"locale": await configured_language()})

app.include_router(console_router, prefix="/api")
app.include_router(billing_router, prefix="/api/billing")
app.include_router(public_router, prefix="/api/auth")
app.include_router(auth_router, prefix="/api/auth")
app.include_router(account_router, prefix="/api/account")
app.include_router(user_router, prefix="/api/users")

developer_api = FastAPI(title="Cat API", version="1", docs_url="/docs", redoc_url=None,
                        exception_handlers=DEVELOPER_EXCEPTION_HANDLERS)
developer_api.include_router(developer_router)
app.mount("/v1", developer_api)


@app.get("/health")
async def health():
    await Tortoise.get_connection("default").execute_query("SELECT 1")
    return {"status": "ok"}


@app.post("/api/payment/wechat/notify")
async def wechat_notify(request: Request):
    return await account_controller.handle_wechat_notify(await request.body(), headers=request.headers)


media = Path(settings.MEDIA_PATH)
app.mount("/media", StaticFiles(directory=media, check_dir=False), name="media")
