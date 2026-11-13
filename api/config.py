
from utils.messages import localized_message
import re
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, SecretStr, field_validator

from auth.deps import AuthContext, get_auth_context, require_user, require_super_admin
from config import settings
from controllers.config import ai_model_config_controller, general_config_controller
from models.config import AiModelConfig
from schemas.config import (
    AiModelConfigCreate,
    AiModelConfigOut,
    AiModelConfigPatch,
    AiModelConfigUpdate,
    GeneralConfigOut,
    GeneralConfigUpdate,
    LocaleOut,
    ImageGenerationModelOut,
    VideoGenerationModelOut,
)
from tortoise.expressions import Q
from utils.enums import (
    AssetTypeEnum,
    AiTaskTypeEnum,
    ImageSourceEnum,
    TaskStatusEnum,
    VideoGenerationModelTypeEnum,
    ImageModelTypeEnum,
    WorkflowStatus,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema
from schemas.platform_billing import PlatformAccountOut

router = APIRouter()

# 模型能力/枚举清单不含密钥，登录用户（含创作者/查看者）可读，供工作台使用
_LOGGED_IN = Depends(get_auth_context)
_ADMIN = Depends(require_super_admin)


def _check_config_ownership(instance: AiModelConfig, ctx: AuthContext) -> None:
    """Only administrators may update platform configuration."""
    if instance.scope == "studio_platform":
        raise HTTPException(409, localized_message("请通过平台同步管理此模型"))
    if ctx.user is None or ctx.is_super_admin:
        return
    raise HTTPException(403, "仅超级管理员可执行此操作")


def _check_config_read_access(instance: AiModelConfig, ctx: AuthContext) -> None:
    """Only administrators may read platform configuration."""
    if ctx.user is None or ctx.is_super_admin:
        return
    raise HTTPException(403, "仅超级管理员可执行此操作")


def _mask_official_key(item: AiModelConfigOut, ctx: AuthContext) -> AiModelConfigOut:
    """Keys are visible only in administrator configuration views."""
    if item.scope == "studio_platform" or (ctx.user is not None and not ctx.is_super_admin and item.scope == "official"):
        item.api_key = None
    return item


@router.post("", summary="创建模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def create_config(config: AiModelConfigCreate, ctx: AuthContext = _ADMIN):
    instance = await ai_model_config_controller.create(
        config,
        scope="official",
    )
    return ResponseSchema(data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx))


@router.get(
    "", summary="获取模型配置列表", response_model=ResponseSchema[PaginationResponse[AiModelConfigOut]]
)
async def get_config_list(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = _ADMIN,
):
    base_query = None
    result = await ai_model_config_controller.list(
        params, AiModelConfigOut, base_query=base_query
    )
    for item in result["items"]:
        _mask_official_key(item, ctx)
    return ResponseSchema(data=result)


@router.get("/{config_id}", summary="获取模型配置详情", response_model=ResponseSchema[AiModelConfigOut])
async def get_config(config_id: int, ctx: AuthContext = _ADMIN):
    instance = await ai_model_config_controller.get(config_id)
    _check_config_read_access(instance, ctx)
    return ResponseSchema(
        data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx)
    )


@router.put("/{config_id}", summary="全量更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def update_config(config_id: int, config: AiModelConfigUpdate, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.update(config_id, config)
    return ResponseSchema(data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx))


@router.patch("/{config_id}", summary="局部更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def patch_config(config_id: int, config: AiModelConfigPatch, ctx: AuthContext = _ADMIN):
    instance = await ai_model_config_controller.get(config_id)
    _check_config_ownership(instance, ctx)
    instance = await ai_model_config_controller.patch(config_id, config)
    return ResponseSchema(data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx))


@router.delete("/{config_id}", summary="删除模型配置", response_model=ResponseSchema)
async def delete_config(config_id: int, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    await ai_model_config_controller.remove(config_id)
    return ResponseSchema()


@router.post("/{config_id}/activate", summary="启用模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def activate_config(config_id: int, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.activate(config_id)
    return ResponseSchema(data=instance)


@router.post("/{config_id}/deactivate", summary="停用模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def deactivate_config(config_id: int, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.deactivate(config_id)
    return ResponseSchema(data=instance)
