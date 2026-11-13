"""用户管理 API（仅超级管理员）。仅在 AUTH_ENABLED=true 时注册。"""

from fastapi import APIRouter, Depends, Query
from typing import Literal

from auth.api import password_provider
from auth.deps import AuthContext, require_super_admin
from controllers.user import user_controller
from schemas.user import UserCreateIn, UserOut, UserPatchIn, UserStatsOut, UserDetailOut, UserEventOut
from schemas.account import BalanceTransactionOut
from controllers.account import account_controller
from utils.page import get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

_SUPER = Depends(require_super_admin)


def _operator_id(ctx: AuthContext) -> int:
    return ctx.user.id if ctx.user else 0


@router.get(
    "/stats",
    summary="用户与账户总览统计（仅超级管理员）",
    response_model=ResponseSchema[UserStatsOut],
)
async def get_user_stats(_: AuthContext = _SUPER):
    return ResponseSchema(data=await user_controller.stats())


@router.get(
    "",
    summary="用户列表（仅超级管理员）",
    response_model=ResponseSchema[PaginationResponse[UserOut]],
)
async def list_users(
    _: AuthContext = _SUPER,
    params=Depends(get_list_params),
    search: str | None = Query(default=None, max_length=100),
    status: Literal[0, 1] | None = None,
    role: Literal['user', 'admin'] | None = None,
    balance_view: Literal['low', 'negative'] | None = None,
    order_by: Literal['id', '-id', 'created_at', '-created_at'] = '-id',
):
    return ResponseSchema(
        data=await user_controller.list_users(params.page, params.page_size, search, status, role, balance_view, order_by)
    )


@router.post(
    "",
    summary="手动创建用户（仅超级管理员）",
    response_model=ResponseSchema[UserOut],
    dependencies=[Depends(password_provider)],
)
async def create_user(payload: UserCreateIn, ctx: AuthContext = _SUPER):
    return ResponseSchema(
        data=await user_controller.create_user(
            payload.username, payload.password, payload.nickname, _operator_id(ctx)
        )
    )


@router.get('/{user_id}', response_model=ResponseSchema[UserDetailOut])
async def user_detail(user_id: int, _: AuthContext = _SUPER):
    return ResponseSchema(data=await user_controller.detail(user_id))


@router.get('/{user_id}/transactions', response_model=ResponseSchema[PaginationResponse[BalanceTransactionOut]])
async def user_transactions(user_id: int, _: AuthContext = _SUPER, params=Depends(get_list_params)):
    await user_controller._get_user(user_id)
    return ResponseSchema(data=await account_controller.transactions(user_id, params.page, params.page_size))


@router.get('/{user_id}/events', response_model=ResponseSchema[PaginationResponse[UserEventOut]])
async def user_events(user_id: int, _: AuthContext = _SUPER, params=Depends(get_list_params)):
    return ResponseSchema(data=await user_controller.events(user_id, params.page, params.page_size))


@router.patch(
    "/{user_id}",
    summary="禁用/启用用户登录（仅超级管理员）",
    response_model=ResponseSchema[UserOut],
)
async def patch_user(
    user_id: int,
    payload: UserPatchIn,
    ctx: AuthContext = _SUPER,
):
    return ResponseSchema(
        data=await user_controller.set_status(
            user_id, payload.status, _operator_id(ctx)
        )
    )


@router.delete(
    "/{user_id}",
    summary="删除用户（仅超级管理员）",
    response_model=ResponseSchema[None],
)
async def delete_user(
    user_id: int,
    ctx: AuthContext = _SUPER,
):
    await user_controller.remove_user(user_id, _operator_id(ctx))
    return ResponseSchema(data=None, message="用户已删除")
