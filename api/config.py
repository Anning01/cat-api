
from utils.messages import localized_message
import re
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, SecretStr, field_validator

from auth.deps import AuthContext, get_auth_context, require_roles, require_super_admin
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
    ModelConfigSourceOut,
    ModelConfigSourceUpdate,
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
# 设置类接口（模型配置 CRUD 与通用配置）仅团队管理员与超管可访问
_ADMIN = Depends(require_roles("admin"))


def _check_config_ownership(instance: AiModelConfig, ctx: AuthContext) -> None:
    """团队管理员只能修改本团队自定义配置；官方配置对其只读（404 不泄露）。"""
    if instance.scope == "studio_platform":
        raise HTTPException(409, localized_message("请通过平台同步管理此模型"))
    if ctx.user is None or ctx.is_super_admin:
        return
    if instance.team_id is None or instance.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail=localized_message('配置不存在或无权操作'))


def _check_config_read_access(instance: AiModelConfig, ctx: AuthContext) -> None:
    """平台级配置仅超管可见；团队管理员只可读本团队自定义配置。"""
    if ctx.user is None or ctx.is_super_admin:
        return
    if instance.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail=localized_message('配置不存在或无权操作'))


def _mask_official_key(item: AiModelConfigOut, ctx: AuthContext) -> AiModelConfigOut:
    """平台级配置不向团队暴露（列表/详情均已隔离）；超管可看全量。保留掩码以防他处复用。"""
    if item.scope == "studio_platform" or (ctx.user is not None and not ctx.is_super_admin and item.scope == "official"):
        item.api_key = None
    return item


@router.post("", summary="创建模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def create_config(config: AiModelConfigCreate, ctx: AuthContext = _ADMIN):
    # 开放平台模型归属平台，侧边栏选中的团队只影响用量等团队页面。
    team_id = None if settings.DEPLOYMENT_ROLE == "platform" else ctx.team_id
    instance = await ai_model_config_controller.create(
        config,
        team_id=team_id,
        scope="team" if team_id else "official",
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
    if ctx.user is not None and not ctx.is_super_admin:
        # 团队管理员仅可见本团队自定义配置；平台级配置只有超管可见
        base_query = AiModelConfig.filter(team_id=ctx.team_id)
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
